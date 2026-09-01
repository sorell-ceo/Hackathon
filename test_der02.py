"""
Automated tests for DER-02 hazard estimation engine.

Run with:  python3 -m pytest test_der02.py -v      (if pytest is available)
       or: python3 test_der02.py                    (built-in fallback runner,
                                                       no dependencies required)
"""
import math

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

    class _PytestShim:
        """Minimal stand-in for the pieces of pytest this file uses, so the
        suite still runs on a machine without pytest installed (e.g. an
        offline hackathon judging laptop)."""

        class _RaisesCtx:
            def __init__(self, exc_type, match=None):
                self.exc_type = exc_type
                self.match = match

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise AssertionError(f"expected {self.exc_type.__name__} but none was raised")
                if not issubclass(exc_type, self.exc_type):
                    return False
                if self.match and self.match not in str(exc_val):
                    raise AssertionError(
                        f"expected message containing '{self.match}', got '{exc_val}'"
                    )
                return True

        def raises(self, exc_type, match=None):
            return self._RaisesCtx(exc_type, match)

    pytest = _PytestShim()

import der02_hazard_engine as der


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def make_tank(diameter_m=20.0, height_m=15.0, fill_fraction=0.9):
    volume = math.pi * (diameter_m / 2) ** 2 * height_m
    return der.TankGeometry(diameter_m=diameter_m, height_m=height_m,
                             volume_m3=round(volume, 2), fill_fraction=fill_fraction)


def make_config(**overrides):
    defaults = dict(
        facility_id="FAC-TEST",
        latitude=13.0067,
        longitude=80.2206,
        tank=make_tank(),
        wind=der.WindCondition(speed_m_s=5.0, direction_deg=270.0),
        fuel_type=der.FuelType.GASOLINE,
        release_fraction=0.15,
    )
    defaults.update(overrides)
    return der.FacilityConfig(**defaults)


# -----------------------------------------------------------------------
# Validation: normal cases
# -----------------------------------------------------------------------

def test_valid_config_passes_validation():
    cfg = make_config()
    der.validate_facility_config(cfg)  # should not raise


def test_calculate_hazard_zone_normal_case_returns_expected_structure():
    cfg = make_config()
    result = der.calculate_hazard_zone(cfg)
    assert result["facility_id"] == "FAC-TEST"
    assert "thermal_radiation" in result
    assert "blast_overpressure" in result
    assert "recommended_approach" in result
    assert len(result["thermal_radiation"]["bands"]) == 3
    assert len(result["blast_overpressure"]["bands"]) == 3


def test_thermal_bands_are_monotonically_increasing_in_distance_with_decreasing_severity():
    cfg = make_config()
    result = der.calculate_hazard_zone(cfg)
    bands = sorted(result["thermal_radiation"]["bands"], key=lambda b: b["level"])
    # level 1 = most severe = smallest distance; level 3 = least severe = largest
    dists = [b["isotropic_distance_m"] for b in bands]
    assert dists[0] < dists[1] < dists[2]


# -----------------------------------------------------------------------
# Validation: edge / invalid cases
# -----------------------------------------------------------------------

def test_negative_wind_speed_rejected():
    cfg = make_config(wind=der.WindCondition(speed_m_s=-3.0, direction_deg=90.0))
    with pytest.raises(der.ValidationError, match="wind speed"):
        der.validate_facility_config(cfg)


def test_invalid_wind_direction_rejected_negative():
    cfg = make_config(wind=der.WindCondition(speed_m_s=5.0, direction_deg=-10.0))
    with pytest.raises(der.ValidationError, match="wind direction"):
        der.validate_facility_config(cfg)


def test_invalid_wind_direction_rejected_over_360():
    cfg = make_config(wind=der.WindCondition(speed_m_s=5.0, direction_deg=360.0))
    with pytest.raises(der.ValidationError, match="wind direction"):
        der.validate_facility_config(cfg)


def test_zero_diameter_rejected():
    tank = make_tank(diameter_m=20.0)
    tank.diameter_m = 0.0
    cfg = make_config(tank=tank)
    with pytest.raises(der.ValidationError, match="diameter"):
        der.validate_facility_config(cfg)


def test_negative_height_rejected():
    tank = make_tank()
    tank.height_m = -5.0
    cfg = make_config(tank=tank)
    with pytest.raises(der.ValidationError, match="height"):
        der.validate_facility_config(cfg)


def test_impossible_volume_rejected():
    # Diameter/height imply ~4700 m^3 but we claim 50,000 m^3 -> geometrically impossible
    tank = der.TankGeometry(diameter_m=20.0, height_m=15.0, volume_m3=50000.0, fill_fraction=0.9)
    cfg = make_config(tank=tank)
    with pytest.raises(der.ValidationError, match="inconsistent with cylindrical"):
        der.validate_facility_config(cfg)


def test_negative_volume_rejected():
    tank = make_tank()
    tank.volume_m3 = -100.0
    cfg = make_config(tank=tank)
    with pytest.raises(der.ValidationError, match="volume"):
        der.validate_facility_config(cfg)


def test_fill_fraction_out_of_range_rejected():
    tank = make_tank()
    tank.fill_fraction = 1.5
    cfg = make_config(tank=tank)
    with pytest.raises(der.ValidationError, match="fill_fraction"):
        der.validate_facility_config(cfg)


def test_latitude_out_of_range_rejected():
    cfg = make_config(latitude=120.0)
    with pytest.raises(der.ValidationError, match="latitude"):
        der.validate_facility_config(cfg)


def test_longitude_out_of_range_rejected():
    cfg = make_config(longitude=-200.0)
    with pytest.raises(der.ValidationError, match="longitude"):
        der.validate_facility_config(cfg)


def test_missing_facility_id_rejected():
    cfg = make_config(facility_id="")
    with pytest.raises(der.ValidationError, match="facility_id"):
        der.validate_facility_config(cfg)


def test_missing_tank_rejected():
    cfg = make_config()
    cfg.tank = None
    with pytest.raises(der.ValidationError, match="tank geometry"):
        der.validate_facility_config(cfg)


def test_missing_wind_rejected():
    cfg = make_config()
    cfg.wind = None
    with pytest.raises(der.ValidationError, match="wind condition"):
        der.validate_facility_config(cfg)


def test_unrealistic_wind_speed_rejected():
    cfg = make_config(wind=der.WindCondition(speed_m_s=200.0, direction_deg=90.0))
    with pytest.raises(der.ValidationError, match="plausible range"):
        der.validate_facility_config(cfg)


def test_calculate_hazard_zone_raises_on_invalid_config():
    cfg = make_config(wind=der.WindCondition(speed_m_s=-1.0, direction_deg=0.0))
    with pytest.raises(der.ValidationError):
        der.calculate_hazard_zone(cfg)


# -----------------------------------------------------------------------
# Wind-dependence of geometry
# -----------------------------------------------------------------------

def test_zero_wind_produces_circular_geometry():
    cfg = make_config(wind=der.WindCondition(speed_m_s=0.0, direction_deg=45.0))
    result = der.calculate_hazard_zone(cfg)
    band = result["thermal_radiation"]["bands"][0]
    coords = band["geometry"]["coordinates"]
    lat0, lon0 = result["location"]["latitude"], result["location"]["longitude"]
    # all vertices should be (approximately) equidistant from centre at zero wind
    dists = []
    for lat, lon in coords:
        dlat = math.radians(lat - lat0)
        dlon = math.radians(lon - lon0)
        d = math.sqrt(dlat**2 + (dlon * math.cos(math.radians(lat0)))**2) * der.EARTH_RADIUS_M
        dists.append(d)
    assert max(dists) - min(dists) < 0.01 * max(dists)  # within 1% -> effectively a circle


def test_higher_wind_speed_elongates_downwind_and_compresses_upwind():
    cfg_calm = make_config(wind=der.WindCondition(speed_m_s=1.0, direction_deg=270.0))
    cfg_windy = make_config(wind=der.WindCondition(speed_m_s=12.0, direction_deg=270.0))

    downwind_bearing = 90.0  # wind FROM 270 (west) blows TOWARD east (90)
    upwind_bearing = 270.0

    mult_calm_down = der._directional_multiplier(downwind_bearing, downwind_bearing, cfg_calm.wind.speed_m_s)
    mult_windy_down = der._directional_multiplier(downwind_bearing, downwind_bearing, cfg_windy.wind.speed_m_s)
    assert mult_windy_down > mult_calm_down  # more wind -> more downwind elongation

    mult_calm_up = der._directional_multiplier(upwind_bearing, downwind_bearing, cfg_calm.wind.speed_m_s)
    mult_windy_up = der._directional_multiplier(upwind_bearing, downwind_bearing, cfg_windy.wind.speed_m_s)
    assert mult_windy_up < mult_calm_up  # more wind -> more upwind compression


def test_downwind_distance_exceeds_upwind_distance():
    cfg = make_config(wind=der.WindCondition(speed_m_s=10.0, direction_deg=0.0))  # wind from N, blows to S (180)
    result = der.calculate_hazard_zone(cfg)
    band = result["thermal_radiation"]["bands"][0]
    coords = band["geometry"]["coordinates"]
    lat0 = result["location"]["latitude"]
    # bearing 180 (south, downwind) vertex vs bearing 0 (north, upwind) vertex
    n_points = len(coords) - 1
    idx_downwind = round(180 / (360 / n_points))
    idx_upwind = 0
    lat_down, lon_down = coords[idx_downwind]
    lat_up, lon_up = coords[idx_upwind]

    def dist_m(lat, lon):
        dlat = math.radians(lat - lat0)
        dlon = math.radians(lon - result["location"]["longitude"])
        return math.sqrt(dlat**2 + (dlon * math.cos(math.radians(lat0)))**2) * der.EARTH_RADIUS_M

    assert dist_m(lat_down, lon_down) > dist_m(lat_up, lon_up)


# -----------------------------------------------------------------------
# recommend_approach_direction
# -----------------------------------------------------------------------

def test_recommended_approach_matches_wind_from_direction():
    cfg = make_config(wind=der.WindCondition(speed_m_s=6.0, direction_deg=135.0))
    result = der.calculate_hazard_zone(cfg)
    assert result["recommended_approach"]["approach_bearing_deg"] == 135.0


# -----------------------------------------------------------------------
# compare_configurations: two facilities must differ for an explainable reason
# -----------------------------------------------------------------------

def test_larger_tank_produces_larger_hazard_distances():
    small = make_config(facility_id="SMALL", tank=make_tank(diameter_m=10.0, height_m=8.0))
    large = make_config(facility_id="LARGE", tank=make_tank(diameter_m=30.0, height_m=18.0))
    comparison = der.compare_configurations(small, large)
    for row in comparison["thermal_distance_comparison_m"]:
        assert row["facility_b_m"] > row["facility_a_m"]


def test_different_fuel_types_produce_different_hazard_distances():
    gasoline_cfg = make_config(facility_id="GAS", fuel_type=der.FuelType.GASOLINE)
    lpg_cfg = make_config(facility_id="LPG", fuel_type=der.FuelType.LPG_PROPANE)
    comparison = der.compare_configurations(gasoline_cfg, lpg_cfg)
    # LPG has higher Hc, burning rate and radiative fraction -> strictly larger distances
    for row in comparison["thermal_distance_comparison_m"]:
        assert row["facility_b_m"] > row["facility_a_m"]


# -----------------------------------------------------------------------
# JSON serialisability (contract with frontend developer)
# -----------------------------------------------------------------------

def test_result_is_json_serialisable():
    cfg = make_config()
    result = der.calculate_hazard_zone(cfg)
    json_str = der.to_json(result)
    assert isinstance(json_str, str)
    assert '"facility_id"' in json_str


if __name__ == "__main__":
    import sys
    if HAVE_PYTEST:
        sys.exit(pytest.main([__file__, "-v"]))
    else:
        # Fallback runner: execute every test_* function in this module.
        test_fns = [(name, obj) for name, obj in list(globals().items())
                    if name.startswith("test_") and callable(obj)]
        passed, failed = 0, []
        for name, fn in test_fns:
            try:
                fn()
                print(f"PASS  {name}")
                passed += 1
            except Exception as e:  # noqa: BLE001
                print(f"FAIL  {name}  ->  {type(e).__name__}: {e}")
                failed.append(name)
        print(f"\n{passed}/{len(test_fns)} passed")
        if failed:
            print("Failed tests:", ", ".join(failed))
        sys.exit(0 if not failed else 1)
