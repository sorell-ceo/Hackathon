"""
DER-02 demonstration script.

Produces hazard-zone output for TWO facility configurations and shows
they differ for a physically explainable reason (Facility B has a larger
tank AND a more energetic/volatile fuel [LPG] than Facility A [gasoline],
under stronger wind) -- exactly what the hackathon brief asks us to
demonstrate.

Run:  python3 examples.py
Writes:  facility_a_result.json, facility_b_result.json, comparison_result.json
"""
import math
import json

import der02_hazard_engine as der


def cylindrical_volume(diameter_m, height_m):
    return round(math.pi * (diameter_m / 2) ** 2 * height_m, 1)


# ---------------------------------------------------------------------------
# FACILITY A -- small gasoline storage tank, VIT Chennai area, light wind
# ---------------------------------------------------------------------------
FACILITY_A = der.FacilityConfig(
    facility_id="FAC-A-GASOLINE-SMALL",
    latitude=12.8406,       # approx. VIT Chennai campus
    longitude=80.1534,
    tank=der.TankGeometry(
        diameter_m=12.0,
        height_m=10.0,
        volume_m3=cylindrical_volume(12.0, 10.0),
        fill_fraction=0.85,
    ),
    wind=der.WindCondition(speed_m_s=3.0, direction_deg=225.0),  # gentle SW wind
    fuel_type=der.FuelType.GASOLINE,
    release_fraction=0.15,
)

# ---------------------------------------------------------------------------
# FACILITY B -- large LPG storage tank, industrial estate nearby, stronger wind
# ---------------------------------------------------------------------------
FACILITY_B = der.FacilityConfig(
    facility_id="FAC-B-LPG-LARGE",
    latitude=13.1231,       # approx. Manali/Ennore industrial belt, Chennai
    longitude=80.2653,
    tank=der.TankGeometry(
        diameter_m=28.0,
        height_m=16.0,
        volume_m3=cylindrical_volume(28.0, 16.0),
        fill_fraction=0.85,
    ),
    wind=der.WindCondition(speed_m_s=9.0, direction_deg=60.0),  # brisk NE wind
    fuel_type=der.FuelType.LPG_PROPANE,
    release_fraction=0.15,
)


def main():
    result_a = der.calculate_hazard_zone(FACILITY_A)
    result_b = der.calculate_hazard_zone(FACILITY_B)
    comparison = der.compare_configurations(FACILITY_A, FACILITY_B)

    with open("facility_a_result.json", "w") as f:
        f.write(der.to_json(result_a))
    with open("facility_b_result.json", "w") as f:
        f.write(der.to_json(result_b))
    with open("comparison_result.json", "w") as f:
        # full_results duplicates result_a/result_b; write a slimmer diff file
        slim = {k: v for k, v in comparison.items() if k != "full_results"}
        f.write(json.dumps(slim, indent=2))

    print("=" * 78)
    print("FACILITY A:", FACILITY_A.facility_id, "|", FACILITY_A.fuel_type.value,
          "| D=%.1fm H=%.1fm V=%.0fm^3 | wind %.1f m/s @ %.0f deg" % (
              FACILITY_A.tank.diameter_m, FACILITY_A.tank.height_m,
              FACILITY_A.tank.volume_m3, FACILITY_A.wind.speed_m_s, FACILITY_A.wind.direction_deg))
    for b in result_a["thermal_radiation"]["bands"]:
        print(f"  [Thermal L{b['level']}] {b['label']:26s} {b['threshold_flux_kw_m2']:>5.1f} kW/m^2 -> {b['isotropic_distance_m']:>7.2f} m (isotropic)")
    for b in result_a["blast_overpressure"]["bands"]:
        print(f"  [Blast   L{b['level']}] {b['label']:26s} {b['threshold_overpressure_kpa']:>5.1f} kPa   -> {b['isotropic_distance_m']:>7.2f} m (isotropic)")
    print("  Recommended approach:", result_a["recommended_approach"]["approach_compass"],
          f"({result_a['recommended_approach']['approach_bearing_deg']} deg), "
          f"standoff >= {result_a['recommended_approach']['minimum_standoff_distance_m']} m")

    print("=" * 78)
    print("FACILITY B:", FACILITY_B.facility_id, "|", FACILITY_B.fuel_type.value,
          "| D=%.1fm H=%.1fm V=%.0fm^3 | wind %.1f m/s @ %.0f deg" % (
              FACILITY_B.tank.diameter_m, FACILITY_B.tank.height_m,
              FACILITY_B.tank.volume_m3, FACILITY_B.wind.speed_m_s, FACILITY_B.wind.direction_deg))
    for b in result_b["thermal_radiation"]["bands"]:
        print(f"  [Thermal L{b['level']}] {b['label']:26s} {b['threshold_flux_kw_m2']:>5.1f} kW/m^2 -> {b['isotropic_distance_m']:>7.2f} m (isotropic)")
    for b in result_b["blast_overpressure"]["bands"]:
        print(f"  [Blast   L{b['level']}] {b['label']:26s} {b['threshold_overpressure_kpa']:>5.1f} kPa   -> {b['isotropic_distance_m']:>7.2f} m (isotropic)")
    print("  Recommended approach:", result_b["recommended_approach"]["approach_compass"],
          f"({result_b['recommended_approach']['approach_bearing_deg']} deg), "
          f"standoff >= {result_b['recommended_approach']['minimum_standoff_distance_m']} m")

    print("=" * 78)
    print("WHY THEY DIFFER:")
    print(" ", comparison["explanation"])
    print()
    print("Thermal distance comparison (Level, A_m, B_m, diff_m, ratio B/A):")
    for row in comparison["thermal_distance_comparison_m"]:
        print(f"  L{row['level']}: {row['facility_a_m']:>7.2f} m  vs  {row['facility_b_m']:>7.2f} m"
              f"   (+{row['difference_m']:.2f} m, x{row['ratio_b_over_a']})")

    print("=" * 78)
    print("Files written: facility_a_result.json, facility_b_result.json, comparison_result.json")


if __name__ == "__main__":
    main()
