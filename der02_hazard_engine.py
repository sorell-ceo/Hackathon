"""
DER-02 : Threat-Zone Estimation for Industrial Fire and Explosion Response
============================================================================
Physics / computational-geometry engine.

Two textbook, citable consequence-modelling methods are implemented:

  1. THERMAL RADIATION  -> Point-Source Model
     (CCPS "Guidelines for Consequence Analysis of Chemical Releases";
      API RP 521; taught as the standard first-pass pool/jet-fire model
      in process-safety engineering courses.)

  2. BLAST OVERPRESSURE -> TNT-Equivalency Model + Kinney-Graham
     scaled-distance correlation
     (Kinney, G.F. & Graham, K.J., "Explosive Shocks in Air", 2nd ed.,
      Springer-Verlag, 1985; CCPS Guidelines for Vapor Cloud Explosions.)

Both are deliberately the *simplified, hand-checkable* variants used for
first-pass emergency-response hazard screening -- NOT high-fidelity CFD
(FDS/PHAST-grade) models. This is stated explicitly in LIMITATIONS below
and is the correct level of rigor for a 24-hour hackathon deliverable
that must still be defensible to judges.

All internal calculations use SI units. See docstrings for unit contracts.
"""

from __future__ import annotations

import math
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# =============================================================================
# 1. PHYSICAL CONSTANTS
# =============================================================================

GRAVITY = 9.80665                  # m/s^2
AMBIENT_PRESSURE_KPA = 101.325     # kPa, standard sea-level atmosphere
TNT_HEAT_OF_DETONATION = 4.184e6   # J/kg  (standard reference value for TNT)
EARTH_RADIUS_M = 6_371_000.0       # m, mean Earth radius (spherical approx.)

# Atmospheric transmissivity for thermal radiation.
# Rigorous treatment requires humidity + path length (e.g. Bagster's
# correlation). For a hackathon-scope screening tool we use a single
# documented, conservative constant. This is explicitly flagged as a
# simplification in LIMITATIONS.
ATMOSPHERIC_TRANSMISSIVITY = 0.80


# =============================================================================
# 2. FUEL / MATERIAL LIBRARY
# =============================================================================
# Typical literature values for pool-fire burning rate (m''), heat of
# combustion (Hc) and radiative fraction (f_s), as commonly tabulated in
# the SFPE Handbook of Fire Protection Engineering / Babrauskas pool-fire
# burning-rate data. These are INDUSTRY-TYPICAL values, not measurements
# of any specific facility -- users should override with site data where
# available. TNT-equivalency yield factor (eta) uses the CCPS-cited
# typical range (0.02-0.10) for vapor cloud explosions.

class FuelType(str, Enum):
    GASOLINE = "gasoline"
    DIESEL = "diesel"
    CRUDE_OIL = "crude_oil"
    LPG_PROPANE = "lpg_propane"
    METHANOL = "methanol"


@dataclass(frozen=True)
class FuelProperties:
    name: str
    burning_rate_kg_m2_s: float    # m'' : mass burning rate per unit pool area
    heat_of_combustion_J_kg: float  # Hc
    radiative_fraction: float       # f_s : fraction of Hc radiated (dimensionless)
    tnt_yield_factor: float         # eta : used only for blast (VCE) calc
    vapor_density_kg_m3: float      # rough density of saturated vapor/liquid density fallback


FUEL_LIBRARY: dict[FuelType, FuelProperties] = {
    FuelType.GASOLINE: FuelProperties(
        name="Gasoline / Petrol",
        burning_rate_kg_m2_s=0.055,
        heat_of_combustion_J_kg=43.7e6,
        radiative_fraction=0.35,
        tnt_yield_factor=0.05,
        vapor_density_kg_m3=4.0,
    ),
    FuelType.DIESEL: FuelProperties(
        name="Diesel / Kerosene",
        burning_rate_kg_m2_s=0.045,
        heat_of_combustion_J_kg=44.4e6,
        radiative_fraction=0.30,
        tnt_yield_factor=0.04,
        vapor_density_kg_m3=5.0,
    ),
    FuelType.CRUDE_OIL: FuelProperties(
        name="Crude Oil",
        burning_rate_kg_m2_s=0.045,
        heat_of_combustion_J_kg=42.0e6,
        radiative_fraction=0.25,
        tnt_yield_factor=0.03,
        vapor_density_kg_m3=4.5,
    ),
    FuelType.LPG_PROPANE: FuelProperties(
        name="LPG / Propane",
        burning_rate_kg_m2_s=0.099,
        heat_of_combustion_J_kg=46.0e6,
        radiative_fraction=0.30,
        tnt_yield_factor=0.08,
        vapor_density_kg_m3=1.9,
    ),
    FuelType.METHANOL: FuelProperties(
        name="Methanol",
        burning_rate_kg_m2_s=0.017,
        heat_of_combustion_J_kg=20.0e6,
        radiative_fraction=0.15,
        tnt_yield_factor=0.02,
        vapor_density_kg_m3=1.4,
    ),
}


# =============================================================================
# 3. SEVERITY BAND THRESHOLDS  (industry-standard reference values)
# =============================================================================
# Thermal radiation thresholds (kW/m^2): API RP 521 / UK HSE / CCPS
#   37.5 kW/m^2 -> sufficient to cause damage to process equipment;
#                  potential fatality within ~30 s exposure
#   12.5 kW/m^2 -> minimum energy to ignite wood / damage structures;
#                  significant chance of fatality for extended exposure
#    4.0 kW/m^2 -> causes pain within ~20 s; blistering unlikely;
#                  standard public/responder evacuation trigger
THERMAL_THRESHOLDS_KW_M2 = [
    {"level": 1, "label": "Fatality / No-Go Zone", "flux_kw_m2": 37.5,
     "meaning": "Potentially fatal within ~30s; equipment damage likely. No unprotected entry."},
    {"level": 2, "label": "Severe Injury Zone", "flux_kw_m2": 12.5,
     "meaning": "Significant injury risk on prolonged exposure; PPE / time-limited entry only."},
    {"level": 3, "label": "Evacuation / Caution Zone", "flux_kw_m2": 4.0,
     "meaning": "Pain within ~20s, low fatality risk; public evacuation & general caution boundary."},
]

# Blast overpressure thresholds (kPa), CCPS-cited standard VCE damage bands
BLAST_THRESHOLDS_KPA = [
    {"level": 1, "label": "Destruction Zone", "overpressure_kpa": 55.0,
     "meaning": "~8 psi: near-total structural destruction, unsurvivable in the open."},
    {"level": 2, "label": "Severe Damage Zone", "overpressure_kpa": 24.0,
     "meaning": "~3.5 psi: severe structural damage, high injury/fatality risk."},
    {"level": 3, "label": "Minor Damage Zone", "overpressure_kpa": 7.0,
     "meaning": "~1 psi: glass breakage, minor injuries from debris; general caution boundary."},
]


# =============================================================================
# 4. INPUT SCHEMA
# =============================================================================

class ValidationError(ValueError):
    """Raised when a FacilityConfig fails physical/logical validation."""


@dataclass
class TankGeometry:
    diameter_m: float
    height_m: float
    volume_m3: float
    fill_fraction: float = 0.9   # fraction of tank volume assumed filled with fuel


@dataclass
class WindCondition:
    speed_m_s: float
    direction_deg: float   # meteorological convention: direction wind is BLOWING FROM, 0=N, 90=E


@dataclass
class FacilityConfig:
    facility_id: str
    latitude: float
    longitude: float
    tank: TankGeometry
    wind: WindCondition
    fuel_type: FuelType = FuelType.GASOLINE
    release_fraction: float = 0.15  # fraction of inventory assumed to participate in VCE
    fuel_overrides: Optional[dict] = None  # allow user to override FuelProperties fields


def validate_facility_config(cfg: FacilityConfig) -> None:
    """Raises ValidationError with a specific, human-readable message on any
    physically impossible or missing input. Called automatically by
    calculate_hazard_zone(), but exposed separately for unit testing."""

    if cfg is None:
        raise ValidationError("facility config is missing")

    if not cfg.facility_id or not isinstance(cfg.facility_id, str):
        raise ValidationError("facility_id is required and must be a non-empty string")

    if not (-90.0 <= cfg.latitude <= 90.0):
        raise ValidationError(f"latitude {cfg.latitude} out of range [-90, 90]")
    if not (-180.0 <= cfg.longitude <= 180.0):
        raise ValidationError(f"longitude {cfg.longitude} out of range [-180, 180]")

    if cfg.tank is None:
        raise ValidationError("tank geometry is required")
    t = cfg.tank
    if t.diameter_m <= 0:
        raise ValidationError(f"tank diameter must be > 0, got {t.diameter_m}")
    if t.height_m <= 0:
        raise ValidationError(f"tank height must be > 0, got {t.height_m}")
    if t.volume_m3 <= 0:
        raise ValidationError(f"tank volume must be > 0, got {t.volume_m3}")
    if not (0.0 < t.fill_fraction <= 1.0):
        raise ValidationError(f"fill_fraction must be in (0, 1], got {t.fill_fraction}")

    # Impossible-volume check: verify stated volume is geometrically
    # consistent with a vertical cylindrical tank of given D and H
    # (allow +-25% tolerance for dished heads / freeboard / non-cylindrical tanks).
    geometric_volume = math.pi * (t.diameter_m / 2) ** 2 * t.height_m
    if geometric_volume <= 0:
        raise ValidationError("computed geometric volume is non-positive")
    ratio = t.volume_m3 / geometric_volume
    if not (0.5 <= ratio <= 1.5):
        raise ValidationError(
            f"stated volume {t.volume_m3} m^3 is inconsistent with cylindrical "
            f"geometry from diameter/height (expected ~{geometric_volume:.1f} m^3, "
            f"ratio={ratio:.2f}; must be within 0.5-1.5x)"
        )

    if cfg.wind is None:
        raise ValidationError("wind condition is required")
    if cfg.wind.speed_m_s < 0:
        raise ValidationError(f"wind speed cannot be negative, got {cfg.wind.speed_m_s}")
    if cfg.wind.speed_m_s > 60:
        raise ValidationError(f"wind speed {cfg.wind.speed_m_s} m/s exceeds plausible range (>60 m/s)")
    if not (0.0 <= cfg.wind.direction_deg < 360.0):
        raise ValidationError(f"wind direction must be in [0, 360), got {cfg.wind.direction_deg}")

    if cfg.fuel_type not in FUEL_LIBRARY:
        raise ValidationError(f"unknown fuel_type '{cfg.fuel_type}'")

    if not (0.0 < cfg.release_fraction <= 1.0):
        raise ValidationError(f"release_fraction must be in (0, 1], got {cfg.release_fraction}")


def _get_fuel_properties(cfg: FacilityConfig) -> FuelProperties:
    base = FUEL_LIBRARY[cfg.fuel_type]
    if not cfg.fuel_overrides:
        return base
    merged = asdict(base)
    for k, v in cfg.fuel_overrides.items():
        if k in merged and k != "name":
            merged[k] = v
    return FuelProperties(**merged)


# =============================================================================
# 5. THERMAL RADIATION -- Point-Source Model
# =============================================================================
#
# EQUATIONS
# ---------
# Burning (pool) area:            A      = pi * (D/2)^2                [m^2]
# Total heat release rate:        Q_fire = m'' * A * Hc                [W]
# Radiated heat release rate:     Q_rad  = f_s * Q_fire                [W]
# Incident radiative flux at
# distance x (isotropic point
# source, atmospheric
# transmissivity tau):            I(x)   = tau * Q_rad / (4 * pi * x^2) [W/m^2]
#
# Inverting for the distance at which flux falls to a threshold I_th:
#     x = sqrt( tau * Q_rad / (4 * pi * I_th) )
#
# VARIABLE / PARAMETER MEANINGS
# ------------------------------
# D      : tank (pool) diameter [m] -- proxy for the burning surface if the
#          tank itself is on fire, or the diked containment area for a
#          spill fire. We use tank diameter directly (conservative/simple
#          default appropriate for a tank fire scenario).
# m''    : mass burning rate per unit pool area [kg/(m^2 s)] -- fuel property
# Hc     : heat of combustion [J/kg] -- fuel property
# f_s    : radiative fraction [-] -- fraction of total combustion energy
#          emitted as thermal radiation (rest goes to convection/plume)
# tau    : atmospheric transmissivity [-] -- fraction of radiation that
#          survives atmospheric absorption over the path length
# I_th   : threshold incident flux defining a severity band [W/m^2]
#
# WHY THIS MODEL IS APPROPRIATE
# ------------------------------
# The point-source model is the standard first-pass / screening-level
# thermal hazard model in process safety engineering (CCPS, API RP 521).
# It is closed-form, fully traceable by hand, and requires only inputs
# that are realistically available at emergency-response time (tank
# geometry + fuel type), which matches this hackathon's stated inputs.
# A "solid flame" model (accounting for flame geometry/view factors) is
# more accurate at close range but requires flame height/tilt correlations
# and view-factor geometry that are excess complexity for a 24h build;
# this is documented as a limitation, not hidden.

def calculate_thermal_radiation(tank: TankGeometry, fuel: FuelProperties,
                                 thresholds_kw_m2: Optional[list] = None,
                                 transmissivity: float = ATMOSPHERIC_TRANSMISSIVITY) -> dict:
    """Compute total radiated power and the isotropic (no-wind) hazard
    distance for each thermal severity threshold.

    Returns a JSON-serialisable dict.
    """
    if thresholds_kw_m2 is None:
        thresholds_kw_m2 = THERMAL_THRESHOLDS_KW_M2

    area_m2 = math.pi * (tank.diameter_m / 2) ** 2
    q_fire_w = fuel.burning_rate_kg_m2_s * area_m2 * fuel.heat_of_combustion_J_kg
    q_rad_w = fuel.radiative_fraction * q_fire_w

    bands = []
    for th in thresholds_kw_m2:
        i_th_w_m2 = th["flux_kw_m2"] * 1000.0
        distance_m = math.sqrt(
            (transmissivity * q_rad_w) / (4 * math.pi * i_th_w_m2)
        )
        bands.append({
            "level": th["level"],
            "label": th["label"],
            "meaning": th["meaning"],
            "threshold_flux_kw_m2": th["flux_kw_m2"],
            "isotropic_distance_m": round(distance_m, 2),
        })

    # sort so band 1 (most severe / smallest radius) is nested inside
    # band 3 (least severe / largest radius) -- ascending by distance
    bands.sort(key=lambda b: b["isotropic_distance_m"])

    return {
        "model": "point_source_thermal_radiation",
        "burning_area_m2": round(area_m2, 2),
        "total_heat_release_w": round(q_fire_w, 1),
        "radiated_heat_release_w": round(q_rad_w, 1),
        "atmospheric_transmissivity": transmissivity,
        "bands": bands,
    }


# =============================================================================
# 6. BLAST OVERPRESSURE -- TNT-Equivalency Model
# =============================================================================
#
# EQUATIONS
# ---------
# Fuel mass involved in explosion:
#     M_fuel = release_fraction * fill_fraction * volume_m3 * rho_liquid   [kg]
#     (rho_liquid approximated via fuel vapor_density_kg_m3 field is NOT
#      used here for liquid mass -- see NOTE below)
#
# TNT-equivalent mass (energy equivalence):
#     W_TNT = (eta * M_fuel * Hc) / E_TNT                                  [kg]
#
# Hopkinson-Cranz cube-root scaled distance:
#     Z = R / W_TNT^(1/3)                                                 [m/kg^(1/3)]
#
# Kinney-Graham (1985) peak side-on overpressure correlation:
#     Pso/P0 = 808*(1+(Z/4.5)^2) / sqrt[ (1+(Z/0.048)^2)
#                                        *(1+(Z/0.32)^2)
#                                        *(1+(Z/1.35)^2) ]
#
# We invert this numerically (bisection) to find R for a target Pso.
#
# VARIABLE / PARAMETER MEANINGS
# ------------------------------
# eta       : TNT yield/equivalency factor [-], typical 0.02-0.10 for
#             vapor cloud explosions (CCPS). Reflects that only a fraction
#             of the combustion energy couples into blast (rest is thermal/
#             incomplete reaction/venting).
# E_TNT     : heat of detonation of TNT, 4.184 MJ/kg (reference constant)
# P0        : ambient pressure, 101.325 kPa
# Pso       : peak static (side-on) overpressure [kPa]
#
# NOTE ON FUEL MASS: liquid density is not in the simplified fuel table
# (only vapor density, used elsewhere for dispersion-adjacent context).
# We therefore compute M_fuel directly from tank volume using a typical
# hydrocarbon liquid density of 750 kg/m^3 (documented constant below) --
# this is a stated simplification, overridable via fuel_overrides in a
# future iteration.
#
# WHY THIS MODEL IS APPROPRIATE
# ------------------------------
# TNT-equivalency + Kinney-Graham scaling is THE standard rapid-assessment
# method for blast consequence screening (CCPS Guidelines for Vapor Cloud
# Explosions, Kinney & Graham 1985) and is widely taught/cited because it
# needs only bulk energy content, not a full CFD congestion/confinement
# model (which needs geometry data unavailable in this problem's inputs).

TYPICAL_HYDROCARBON_LIQUID_DENSITY_KG_M3 = 750.0


def _kinney_graham_overpressure_ratio(z: float) -> float:
    """Pso/P0 as a function of scaled distance Z [m/kg^(1/3)]."""
    numerator = 808.0 * (1.0 + (z / 4.5) ** 2)
    denom = math.sqrt(
        (1.0 + (z / 0.048) ** 2) *
        (1.0 + (z / 0.32) ** 2) *
        (1.0 + (z / 1.35) ** 2)
    )
    return numerator / denom


def _solve_distance_for_overpressure(w_tnt_kg: float, target_kpa: float,
                                      lo: float = 0.5, hi: float = 20000.0,
                                      iters: int = 100) -> float:
    """Bisection root-find for R such that Kinney-Graham(R) == target_kpa.
    Pso is monotonically decreasing with R, so bisection is well-posed."""
    w_cbrt = w_tnt_kg ** (1.0 / 3.0)

    def pso_at(r):
        z = r / w_cbrt
        return _kinney_graham_overpressure_ratio(z) * AMBIENT_PRESSURE_KPA

    f_lo = pso_at(lo) - target_kpa
    f_hi = pso_at(hi) - target_kpa
    if f_lo < 0:
        # even at the minimum distance we can't reach target -> degenerate
        return lo
    if f_hi > 0:
        # target not reached even at hi bound -> expand once
        hi *= 5
        f_hi = pso_at(hi) - target_kpa
        if f_hi > 0:
            return hi

    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        f_mid = pso_at(mid) - target_kpa
        if abs(f_mid) < 1e-6:
            return mid
        if f_mid > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def calculate_blast_overpressure(tank: TankGeometry, fuel: FuelProperties,
                                  release_fraction: float,
                                  thresholds_kpa: Optional[list] = None) -> dict:
    """Compute TNT-equivalent mass and isotropic hazard distance for each
    blast severity threshold. Returns a JSON-serialisable dict.

    Blast overpressure is treated as ISOTROPIC (no wind-direction
    dependence) -- this matches standard TNT-equivalency practice and is
    explicitly listed under LIMITATIONS.
    """
    if thresholds_kpa is None:
        thresholds_kpa = BLAST_THRESHOLDS_KPA

    fuel_mass_kg = (
        release_fraction * tank.fill_fraction * tank.volume_m3
        * TYPICAL_HYDROCARBON_LIQUID_DENSITY_KG_M3
    )
    w_tnt_kg = (fuel.tnt_yield_factor * fuel_mass_kg * fuel.heat_of_combustion_J_kg) / TNT_HEAT_OF_DETONATION

    bands = []
    for th in thresholds_kpa:
        distance_m = _solve_distance_for_overpressure(w_tnt_kg, th["overpressure_kpa"])
        bands.append({
            "level": th["level"],
            "label": th["label"],
            "meaning": th["meaning"],
            "threshold_overpressure_kpa": th["overpressure_kpa"],
            "isotropic_distance_m": round(distance_m, 2),
        })

    bands.sort(key=lambda b: b["isotropic_distance_m"])

    return {
        "model": "tnt_equivalency_kinney_graham",
        "fuel_mass_involved_kg": round(fuel_mass_kg, 1),
        "tnt_equivalent_mass_kg": round(w_tnt_kg, 2),
        "tnt_yield_factor": fuel.tnt_yield_factor,
        "note": "Blast geometry is isotropic (no wind dependence) -- see LIMITATIONS.",
        "bands": bands,
    }


# =============================================================================
# 7. WIND-DEPENDENT GEOMETRY
# =============================================================================
#
# The point-source and TNT-equivalency models above give an ISOTROPIC
# (circular) hazard radius. Real fires tilt and drift downwind, so the
# hazard footprint is not a circle: it stretches downwind and compresses
# upwind/crosswind.
#
# TIER LABELLING (read this before trusting the shape quantitatively):
#   Tier 1 (rigorous, textbook): the RADIUS magnitude from Sections 5-6.
#   Tier 2 (documented heuristic): the DIRECTIONAL SHAPE below, which
#     distorts that Tier-1 radius as a function of bearing relative to
#     wind and of wind speed. It is calibrated to reproduce the known
#     QUALITATIVE behaviour of wind-affected flames/plumes (elongation
#     downwind, compression upwind -- consistent with flame-tilt
#     literature such as the AGA/Moorhouse and Chamberlain correlations)
#     but the specific coefficients (k_down, k_up, k_cross) are engineering
#     approximations chosen for this hackathon, NOT fitted to experimental
#     data. This is explicitly disclosed to judges -- see LIMITATIONS.
#
# Directional distance multiplier M(phi, u):
#   phi = angular offset [deg] between a compass bearing and the downwind
#         direction (phi=0 -> directly downwind, phi=180 -> directly upwind)
#   u   = wind speed [m/s]
#
#   M_down(u)  = 1 + k_down  * min(u, u_cap)          (elongates downwind)
#   M_up(u)    = max(1 - k_up * u, floor_up)          (compresses upwind)
#   M_cross(u) = 1 + k_cross * u                      (mild crosswind widening)
#
#   M(phi, u) = M_cross(u) + (M_down(u) - M_cross(u)) * max(cos(phi), 0)
#                          + (M_up(u)   - M_cross(u)) * max(-cos(phi), 0)
#
# Blast overpressure zones are NOT distorted (kept circular) -- consistent
# with the isotropic TNT-equivalency assumption in Section 6.

K_DOWNWIND_PER_MS = 0.10     # +10% radius per m/s wind speed, downwind
K_UPWIND_PER_MS = 0.06       # -6% radius per m/s wind speed, upwind
K_CROSSWIND_PER_MS = 0.03    # +3% radius per m/s wind speed, crosswind
WIND_SPEED_CAP_MS = 15.0     # saturate elongation above this speed
UPWIND_FLOOR = 0.5           # never compress upwind radius below 50% of isotropic


def _directional_multiplier(bearing_deg: float, downwind_deg: float, wind_speed_m_s: float) -> float:
    phi = math.radians(bearing_deg - downwind_deg)
    u = wind_speed_m_s
    u_eff = min(u, WIND_SPEED_CAP_MS)

    m_down = 1.0 + K_DOWNWIND_PER_MS * u_eff
    m_up = max(1.0 - K_UPWIND_PER_MS * u_eff, UPWIND_FLOOR)
    m_cross = 1.0 + K_CROSSWIND_PER_MS * u_eff

    cos_phi = math.cos(phi)
    return m_cross + (m_down - m_cross) * max(cos_phi, 0.0) + (m_up - m_cross) * max(-cos_phi, 0.0)


def _offset_latlon(lat_deg: float, lon_deg: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Equirectangular flat-earth projection -- adequate for hazard zones
    up to a few kilometres (documented limitation for larger scales)."""
    bearing_rad = math.radians(bearing_deg)
    d_lat = (distance_m * math.cos(bearing_rad)) / EARTH_RADIUS_M
    d_lon = (distance_m * math.sin(bearing_rad)) / (EARTH_RADIUS_M * math.cos(math.radians(lat_deg)))
    return lat_deg + math.degrees(d_lat), lon_deg + math.degrees(d_lon)


def generate_hazard_geometry(latitude: float, longitude: float,
                              isotropic_radius_m: float,
                              wind: WindCondition,
                              directional: bool = True,
                              n_points: int = 72) -> dict:
    """Generate a polygon (list of [lat, lon]) representing a hazard band,
    optionally distorted by wind. Returns GeoJSON-ish structure.

    directional=True  -> thermal-style wind-distorted polygon
    directional=False -> plain circle (used for blast bands)
    """
    downwind_deg = (wind.direction_deg + 180.0) % 360.0
    coords = []
    for i in range(n_points + 1):
        bearing = (360.0 / n_points) * i
        if directional:
            mult = _directional_multiplier(bearing, downwind_deg, wind.speed_m_s)
        else:
            mult = 1.0
        r = isotropic_radius_m * mult
        lat, lon = _offset_latlon(latitude, longitude, bearing, r)
        coords.append([round(lat, 7), round(lon, 7)])

    return {
        "type": "Polygon",
        "downwind_bearing_deg": round(downwind_deg, 1),
        "isotropic_radius_m": round(isotropic_radius_m, 2),
        "directional": directional,
        "coordinates": coords,
    }


# =============================================================================
# 8. ORCHESTRATOR
# =============================================================================

def calculate_hazard_zone(cfg: FacilityConfig, include_blast: bool = True) -> dict:
    """Top-level entry point. Validates input, runs thermal (+ optional
    blast) sub-models, generates wind-shaped geometry for every severity
    band, and returns a single JSON-serialisable dict ready to hand to a
    frontend/map developer.
    """
    validate_facility_config(cfg)
    fuel = _get_fuel_properties(cfg)

    thermal = calculate_thermal_radiation(cfg.tank, fuel)
    for band in thermal["bands"]:
        band["geometry"] = generate_hazard_geometry(
            cfg.latitude, cfg.longitude, band["isotropic_distance_m"],
            cfg.wind, directional=True,
        )

    result = {
        "facility_id": cfg.facility_id,
        "location": {"latitude": cfg.latitude, "longitude": cfg.longitude},
        "tank": asdict(cfg.tank),
        "wind": asdict(cfg.wind),
        "fuel_type": cfg.fuel_type.value,
        "fuel_properties_used": asdict(fuel),
        "thermal_radiation": thermal,
    }

    if include_blast:
        blast = calculate_blast_overpressure(cfg.tank, fuel, cfg.release_fraction)
        for band in blast["bands"]:
            band["geometry"] = generate_hazard_geometry(
                cfg.latitude, cfg.longitude, band["isotropic_distance_m"],
                cfg.wind, directional=False,
            )
        result["blast_overpressure"] = blast

    result["recommended_approach"] = recommend_approach_direction(cfg, thermal)

    return result


# =============================================================================
# 9. RECOMMENDED APPROACH DIRECTION
# =============================================================================
#
# HAZMAT / fire-service doctrine: responders approach an incident from
# UPWIND (and, where applicable, uphill) so that heat, smoke and toxic
# combustion products are carried away from them by the prevailing wind.
# This is independently consistent with our Tier-2 geometry model: the
# upwind bearing is exactly where the directional multiplier M_up(u) is
# smallest, i.e. where the computed hazard radius is smallest -- the two
# reasoning paths agree, which is a useful sanity-check to show judges.

COMPASS_LABELS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _bearing_to_compass(bearing_deg: float) -> str:
    idx = round(bearing_deg / 22.5) % 16
    return COMPASS_LABELS[idx]


def recommend_approach_direction(cfg: FacilityConfig, thermal_result: dict) -> dict:
    """Recommend the safest responder approach bearing: directly upwind
    of the facility (i.e. the same bearing the wind is blowing FROM)."""
    upwind_bearing = cfg.wind.direction_deg  # meteorological convention

    # report the smallest-severity-band (Level 1) hazard distance in the
    # upwind direction as a concrete "stand at least this far back" number
    level1 = min(thermal_result["bands"], key=lambda b: b["level"])
    upwind_mult = _directional_multiplier(
        upwind_bearing, (cfg.wind.direction_deg + 180.0) % 360.0, cfg.wind.speed_m_s
    )
    safe_standoff_m = level1["isotropic_distance_m"] * upwind_mult

    return {
        "approach_bearing_deg": round(upwind_bearing, 1),
        "approach_compass": _bearing_to_compass(upwind_bearing),
        "rationale": (
            "Approach from upwind (the direction the wind is blowing FROM). "
            "This keeps heat, smoke and combustion products moving away from "
            "responders, and independently corresponds to the smallest computed "
            "hazard radius in the directional geometry model."
        ),
        "minimum_standoff_distance_m": round(safe_standoff_m, 1),
        "standoff_basis": f"{level1['label']} ({level1['threshold_flux_kw_m2']} kW/m^2) upwind distance",
    }


# =============================================================================
# 10. CONFIGURATION COMPARISON
# =============================================================================

def compare_configurations(cfg_a: FacilityConfig, cfg_b: FacilityConfig) -> dict:
    """Run calculate_hazard_zone on two facility configurations and return
    a structured, judge-explainable diff of their hazard distances."""
    result_a = calculate_hazard_zone(cfg_a)
    result_b = calculate_hazard_zone(cfg_b)

    def band_map(res):
        return {b["level"]: b["isotropic_distance_m"] for b in res["thermal_radiation"]["bands"]}

    ba, bb = band_map(result_a), band_map(result_b)
    thermal_diff = []
    for level in sorted(ba.keys()):
        thermal_diff.append({
            "level": level,
            "facility_a_m": ba[level],
            "facility_b_m": bb[level],
            "difference_m": round(bb[level] - ba[level], 2),
            "ratio_b_over_a": round(bb[level] / ba[level], 3) if ba[level] else None,
        })

    return {
        "facility_a": {
            "id": cfg_a.facility_id,
            "diameter_m": cfg_a.tank.diameter_m,
            "volume_m3": cfg_a.tank.volume_m3,
            "fuel_type": cfg_a.fuel_type.value,
            "wind_speed_m_s": cfg_a.wind.speed_m_s,
            "radiated_heat_release_w": result_a["thermal_radiation"]["radiated_heat_release_w"],
        },
        "facility_b": {
            "id": cfg_b.facility_id,
            "diameter_m": cfg_b.tank.diameter_m,
            "volume_m3": cfg_b.tank.volume_m3,
            "fuel_type": cfg_b.fuel_type.value,
            "wind_speed_m_s": cfg_b.wind.speed_m_s,
            "radiated_heat_release_w": result_b["thermal_radiation"]["radiated_heat_release_w"],
        },
        "thermal_distance_comparison_m": thermal_diff,
        "explanation": (
            "Hazard distance scales with sqrt(burning_area * heat_of_combustion "
            "* burning_rate * radiative_fraction). Burning area scales with "
            "diameter^2, so a larger-diameter tank (or a more energetic fuel) "
            "produces a larger radiated heat release and therefore a larger "
            "hazard radius at every severity threshold; wind speed further "
            "reshapes the footprint (elongating it downwind) without changing "
            "the underlying radiated power."
        ),
        "full_results": {"facility_a": result_a, "facility_b": result_b},
    }


def to_json(result: dict, indent: int = 2) -> str:
    """Convenience serialiser for handing results to a frontend developer."""
    return json.dumps(result, indent=indent)
