"""
THREATZONE API -- FastAPI backend for DER-02
=============================================
Thin, validating HTTP layer around der02_hazard_engine.py. This file
contains NO physics: every hazard number returned by this API comes
from calling into the existing engine (calculate_hazard_zone /
compare_configurations). Nothing here hardcodes distances, metrics,
or example configurations.

Run with:
    uvicorn main:app --reload --port 8000

See README.md for full documentation.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

import der02_hazard_engine as engine
from schemas import CalculateRequest, CompareRequest, ErrorResponse

logger = logging.getLogger("threatzone")

app = FastAPI(
    title="THREATZONE API",
    description=(
        "DER-02 hazard-zone calculation API. Wraps der02_hazard_engine.py "
        "(point-source thermal radiation + TNT-equivalency/Kinney-Graham "
        "blast overpressure) for arbitrary, user-submitted facility "
        "configurations."
    ),
    version="1.0.0",
)

# -----------------------------------------------------------------------
# CORS -- local React dev servers (CRA default :3000, Vite default :5173)
# -----------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------
# Error handling
# -----------------------------------------------------------------------
# The engine's own validate_facility_config() raises ValidationError with
# an already human-readable message (e.g. "tank diameter must be > 0, got
# -5"). We surface that message verbatim as a 422 rather than reformatting
# or guessing at it -- the engine is the source of truth for *why* a
# config is invalid.

@app.exception_handler(engine.ValidationError)
async def engine_validation_error_handler(request: Request, exc: engine.ValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="invalid_facility_configuration",
            detail=str(exc),
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def pydantic_validation_error_handler(request: Request, exc: RequestValidationError):
    # Turn Pydantic's error list into a single human-readable string,
    # e.g. "facility.tank.diameter_m: ensure this value is > 0"
    messages = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        messages.append(f"{loc}: {err.get('msg')}" if loc else err.get("msg", "invalid request"))
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="malformed_request",
            detail="; ".join(messages),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # Never leak internals / stack traces to the client; log server-side.
    logger.exception("Unhandled error while processing %s", request.url)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            detail="An unexpected error occurred while processing the request.",
        ).model_dump(),
    )


# -----------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------

@app.get("/api/health", tags=["meta"])
async def health():
    """Simple liveness check."""
    return {"status": "ok", "service": "threatzone-api"}


@app.get("/api/fuel-types", tags=["meta"])
async def fuel_types():
    """List the fuel types the engine currently supports, with the
    literature-sourced properties it will use for each (straight from
    engine.FUEL_LIBRARY -- nothing hardcoded here)."""
    from dataclasses import asdict
    return {
        fuel.value: asdict(props)
        for fuel, props in engine.FUEL_LIBRARY.items()
    }


@app.post("/api/calculate", tags=["hazard"])
async def calculate(payload: CalculateRequest):
    """
    Run the full DER-02 hazard calculation for a single facility
    configuration.

    Calls der02_hazard_engine.calculate_hazard_zone() directly. Returns:
      - facility information (id, lat/lon)
      - the input parameters actually used (tank, wind, fuel)
      - thermal radiation results (3 severity bands + GeoJSON-style polygons)
      - blast overpressure results (3 severity bands + polygons), if enabled
      - wind information
      - recommended responder approach direction + minimum standoff
      - calculation/model metadata (equations used, transmissivity, etc.)
    """
    cfg = payload.facility.to_engine()
    result = engine.calculate_hazard_zone(cfg, include_blast=payload.include_blast)
    return result


@app.post("/api/compare", tags=["hazard"])
async def compare(payload: CompareRequest):
    """
    Run calculate_hazard_zone() on two facility configurations and return
    a structured, judge-explainable diff of their hazard distances.

    Calls der02_hazard_engine.compare_configurations() directly -- includes
    full per-facility results (for map drawing) plus a level-by-level
    thermal distance comparison and a plain-English explanation of why
    they differ.
    """
    cfg_a = payload.facility_a.to_engine()
    cfg_b = payload.facility_b.to_engine()
    result = engine.compare_configurations(cfg_a, cfg_b)
    return result
