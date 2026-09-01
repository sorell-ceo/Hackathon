"""
Pydantic request models for the THREATZONE API.
=================================================
These models describe the wire format the frontend sends. They are
intentionally "dumb" (just type/shape validation) -- all PHYSICAL /
domain validation (e.g. "is this volume consistent with this diameter?")
is left to der02_hazard_engine.validate_facility_config, which is the
single source of truth for what makes a configuration valid. We convert
these Pydantic models into the engine's own dataclasses before calling it,
so the engine's validation logic is never duplicated or bypassed.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from der02_hazard_engine import (
    FuelType,
    TankGeometry,
    WindCondition,
    FacilityConfig,
)


class TankGeometryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_m: float = Field(..., gt=0, description="Tank diameter, metres")
    height_m: float = Field(..., gt=0, description="Tank height, metres")
    volume_m3: float = Field(..., gt=0, description="Nominal tank volume, m^3")
    fill_fraction: float = Field(
        0.9, gt=0, le=1.0,
        description="Fraction of tank volume filled with fuel (0, 1]",
    )

    def to_engine(self) -> TankGeometry:
        return TankGeometry(
            diameter_m=self.diameter_m,
            height_m=self.height_m,
            volume_m3=self.volume_m3,
            fill_fraction=self.fill_fraction,
        )


class WindConditionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speed_m_s: float = Field(..., ge=0, description="Wind speed, m/s")
    direction_deg: float = Field(
        ..., ge=0, lt=360,
        description="Meteorological convention: direction wind is BLOWING FROM, 0=N, 90=E",
    )

    def to_engine(self) -> WindCondition:
        return WindCondition(speed_m_s=self.speed_m_s, direction_deg=self.direction_deg)


class FacilityConfigIn(BaseModel):
    """Mirrors der02_hazard_engine.FacilityConfig exactly, field-for-field."""

    model_config = ConfigDict(extra="forbid")

    facility_id: str = Field(..., min_length=1, description="Unique facility identifier")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    tank: TankGeometryIn
    wind: WindConditionIn
    fuel_type: FuelType = Field(FuelType.GASOLINE, description="One of the supported fuel types")
    release_fraction: float = Field(
        0.15, gt=0, le=1.0,
        description="Fraction of inventory assumed to participate in the vapor cloud explosion",
    )
    fuel_overrides: Optional[dict] = Field(
        None,
        description="Optional overrides for individual FuelProperties fields "
                    "(e.g. {'heat_of_combustion_J_kg': 4.5e7})",
    )

    def to_engine(self) -> FacilityConfig:
        return FacilityConfig(
            facility_id=self.facility_id,
            latitude=self.latitude,
            longitude=self.longitude,
            tank=self.tank.to_engine(),
            wind=self.wind.to_engine(),
            fuel_type=self.fuel_type,
            release_fraction=self.release_fraction,
            fuel_overrides=self.fuel_overrides,
        )


class CalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility: FacilityConfigIn
    include_blast: bool = Field(
        True, description="Whether to also run the blast-overpressure (VCE) model",
    )


class CompareRequest(BaseModel):
    """Note: compare_configurations() in the engine always runs the full
    calculate_hazard_zone() (thermal + blast) for both facilities -- this
    is the engine's own behaviour and is not reconfigurable from the API,
    to avoid re-implementing/duplicating any of its orchestration logic."""

    model_config = ConfigDict(extra="forbid")

    facility_a: FacilityConfigIn
    facility_b: FacilityConfigIn


class ErrorResponse(BaseModel):
    error: str
    detail: str
