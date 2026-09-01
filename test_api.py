"""
Automated tests for the THREATZONE API.
========================================
Exercises the full path: frontend-style JSON -> FastAPI -> Pydantic
validation -> der02_hazard_engine -> JSON response.

Run from backend/:
    pytest -v

None of these configurations are hardcoded example scenarios from the
engine's own docstrings -- they're new tank sizes / fuels / winds chosen
to prove the API genuinely calls the physics engine rather than
returning canned output.
"""

import math

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def make_facility(**overrides):
    """A valid baseline facility payload; override any field via kwargs
    using dotted-ish shortcuts handled below."""
    payload = {
        "facility_id": "REFINERY-ALPHA-7",
        "latitude": 29.7604,
        "longitude": -95.3698,
        "tank": {
            "diameter_m": 10.0,
            "height_m": 12.0,
            "volume_m3": 942.0,   # pi*(5^2)*12 ≈ 942, geometrically consistent
            "fill_fraction": 0.85,
        },
        "wind": {
            "speed_m_s": 5.0,
            "direction_deg": 270.0,
        },
        "fuel_type": "diesel",
        "release_fraction": 0.15,
    }
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Health / meta
# -----------------------------------------------------------------------

def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_fuel_types_lists_all_five_and_is_engine_sourced():
    resp = client.get("/api/fuel-types")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "gasoline", "diesel", "crude_oil", "lpg_propane", "methanol",
    }
    # spot-check one field to confirm it's the real engine data, not a stub
    assert body["gasoline"]["heat_of_combustion_J_kg"] == pytest.approx(43.7e6)


# -----------------------------------------------------------------------
# /api/calculate -- happy path, brand-new configurations
# -----------------------------------------------------------------------

def test_calculate_new_lpg_configuration_end_to_end():
    """A configuration that does not appear anywhere in the engine file:
    large LPG sphere-ish tank, gusty coastal wind."""
    body = {
        "facility": make_facility(
            facility_id="LPG-TERMINAL-9",
            tank={"diameter_m": 14.0, "height_m": 14.0, "volume_m3": 2155.0, "fill_fraction": 0.7},
            wind={"speed_m_s": 9.5, "direction_deg": 135.0},
            fuel_type="lpg_propane",
            release_fraction=0.25,
        ),
        "include_blast": True,
    }
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 200
    data = resp.json()

    # facility info + inputs echoed back
    assert data["facility_id"] == "LPG-TERMINAL-9"
    assert data["location"]["latitude"] == pytest.approx(29.7604)
    assert data["fuel_type"] == "lpg_propane"
    assert data["wind"]["speed_m_s"] == pytest.approx(9.5)

    # thermal: 3+ severity bands, each with hazard geometry
    thermal_bands = data["thermal_radiation"]["bands"]
    assert len(thermal_bands) >= 3
    for b in thermal_bands:
        assert b["isotropic_distance_m"] > 0
        assert b["geometry"]["type"] == "Polygon"
        assert len(b["geometry"]["coordinates"]) > 10
        # every coordinate is [lat, lon]
        for pt in b["geometry"]["coordinates"]:
            assert len(pt) == 2

    # blast: 3+ severity bands, present because include_blast=True
    assert "blast_overpressure" in data
    blast_bands = data["blast_overpressure"]["bands"]
    assert len(blast_bands) >= 3
    for b in blast_bands:
        assert b["isotropic_distance_m"] > 0
        assert b["geometry"]["type"] == "Polygon"

    # bands are properly ordered (level 1 = smallest / most severe distance)
    distances = [b["isotropic_distance_m"] for b in thermal_bands]
    assert distances == sorted(distances)

    # wind info + recommended approach direction present and sane
    assert data["recommended_approach"]["approach_compass"] in {
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    }
    assert data["recommended_approach"]["minimum_standoff_distance_m"] > 0

    # calculation metadata present
    assert data["thermal_radiation"]["model"] == "point_source_thermal_radiation"
    assert data["blast_overpressure"]["model"] == "tnt_equivalency_kinney_graham"
    assert "fuel_properties_used" in data


def test_calculate_small_methanol_tank_no_blast():
    """A second, very different new configuration: small methanol tank,
    calm wind, blast model explicitly disabled."""
    body = {
        "facility": make_facility(
            facility_id="LAB-SITE-3",
            latitude=51.5074,
            longitude=-0.1278,
            tank={"diameter_m": 3.0, "height_m": 4.0, "volume_m3": 28.0, "fill_fraction": 0.95},
            wind={"speed_m_s": 0.5, "direction_deg": 10.0},
            fuel_type="methanol",
        ),
        "include_blast": False,
    }
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["facility_id"] == "LAB-SITE-3"
    assert "blast_overpressure" not in data
    assert len(data["thermal_radiation"]["bands"]) >= 3
    # methanol has a low heat of combustion -> distances should be modest
    assert data["thermal_radiation"]["bands"][-1]["isotropic_distance_m"] < 50


def test_calculate_crude_oil_large_tank():
    """Third distinct new configuration: a big crude-oil storage tank."""
    body = {
        "facility": make_facility(
            facility_id="CRUDE-FARM-12",
            tank={"diameter_m": 30.0, "height_m": 15.0, "volume_m3": 10603.0, "fill_fraction": 0.9},
            wind={"speed_m_s": 3.0, "direction_deg": 90.0},
            fuel_type="crude_oil",
            release_fraction=0.1,
        )
    }
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["fuel_type"] == "crude_oil"
    # a 30m-diameter tank should produce materially larger hazard
    # distances than the small methanol tank above -- cross-check against
    # the engine directly to make sure the API isn't returning fake/static
    # numbers.
    import der02_hazard_engine as engine
    cfg = engine.FacilityConfig(
        facility_id="CRUDE-FARM-12",
        latitude=29.7604, longitude=-95.3698,
        tank=engine.TankGeometry(diameter_m=30.0, height_m=15.0, volume_m3=10603.0, fill_fraction=0.9),
        wind=engine.WindCondition(speed_m_s=3.0, direction_deg=90.0),
        fuel_type=engine.FuelType.CRUDE_OIL,
        release_fraction=0.1,
    )
    direct = engine.calculate_hazard_zone(cfg)
    api_distances = [b["isotropic_distance_m"] for b in data["thermal_radiation"]["bands"]]
    direct_distances = [b["isotropic_distance_m"] for b in direct["thermal_radiation"]["bands"]]
    assert api_distances == direct_distances


def test_calculate_with_fuel_overrides():
    """fuel_overrides should actually change the result, proving the API
    passes them through to the engine instead of ignoring them."""
    base_body = {"facility": make_facility(facility_id="OVR-1", fuel_type="gasoline")}
    overridden_body = {
        "facility": make_facility(
            facility_id="OVR-1", fuel_type="gasoline",
            fuel_overrides={"heat_of_combustion_J_kg": 10.0e6},  # much lower than stock 43.7e6
        )
    }
    base = client.post("/api/calculate", json=base_body).json()
    overridden = client.post("/api/calculate", json=overridden_body).json()

    base_dist = base["thermal_radiation"]["bands"][-1]["isotropic_distance_m"]
    overridden_dist = overridden["thermal_radiation"]["bands"][-1]["isotropic_distance_m"]
    assert overridden_dist < base_dist  # lower Hc -> smaller hazard radius


# -----------------------------------------------------------------------
# /api/compare
# -----------------------------------------------------------------------

def test_compare_two_new_configurations():
    body = {
        "facility_a": make_facility(
            facility_id="SITE-A",
            tank={"diameter_m": 8.0, "height_m": 10.0, "volume_m3": 502.0, "fill_fraction": 0.85},
            fuel_type="diesel",
        ),
        "facility_b": make_facility(
            facility_id="SITE-B",
            tank={"diameter_m": 16.0, "height_m": 10.0, "volume_m3": 2010.0, "fill_fraction": 0.85},
            fuel_type="diesel",
        ),
    }
    resp = client.post("/api/compare", json=body)
    assert resp.status_code == 200
    data = resp.json()

    assert data["facility_a"]["id"] == "SITE-A"
    assert data["facility_b"]["id"] == "SITE-B"
    assert len(data["thermal_distance_comparison_m"]) >= 3

    # larger tank (SITE-B, double the diameter) must produce larger
    # hazard distances at every severity level
    for row in data["thermal_distance_comparison_m"]:
        assert row["facility_b_m"] > row["facility_a_m"]

    # full per-facility results (for map drawing) are embedded
    assert "full_results" in data
    assert data["full_results"]["facility_a"]["facility_id"] == "SITE-A"
    assert data["full_results"]["facility_b"]["facility_id"] == "SITE-B"
    assert "explanation" in data


# -----------------------------------------------------------------------
# Validation errors -- malformed / physically-impossible requests
# -----------------------------------------------------------------------

def test_missing_required_field_returns_422():
    body = {"facility": make_facility()}
    del body["facility"]["tank"]
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422
    assert resp.json()["error"] == "malformed_request"


def test_negative_diameter_returns_422():
    body = {"facility": make_facility(tank={
        "diameter_m": -5.0, "height_m": 10.0, "volume_m3": 942.0, "fill_fraction": 0.85,
    })}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422


def test_latitude_out_of_range_returns_422():
    body = {"facility": make_facility(latitude=200.0)}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422


def test_geometrically_inconsistent_volume_returns_422_with_engine_message():
    """diameter/height imply ~942 m^3 but we claim 50,000 m^3 -- the
    engine's own cross-check should reject this, and its exact message
    should come through untouched."""
    body = {"facility": make_facility(tank={
        "diameter_m": 10.0, "height_m": 12.0, "volume_m3": 50000.0, "fill_fraction": 0.85,
    })}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"] == "invalid_facility_configuration"
    assert "inconsistent with cylindrical geometry" in payload["detail"]


def test_invalid_fuel_type_returns_422():
    body = {"facility": make_facility(fuel_type="unobtainium")}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422


def test_wind_speed_too_high_returns_422():
    body = {"facility": make_facility(wind={"speed_m_s": 999.0, "direction_deg": 0.0})}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422


def test_malformed_json_body_handled_safely():
    resp = client.post(
        "/api/calculate",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_extra_unknown_fields_rejected():
    body = {"facility": make_facility(), "flux_capacitor": True}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422


def test_empty_facility_id_rejected():
    body = {"facility": make_facility(facility_id="")}
    resp = client.post("/api/calculate", json=body)
    assert resp.status_code == 422
