"""
Sahayata Atlas Backend
Implements the Backend Requirements and Frontend API Agreement (v1).
"""
import time
import uuid
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.errors import ApiError
from app.schemas import NearbyResponse, HealthResponse
from app.location import resolve_city, validate_coordinates, LocationError
from app.aggregator import aggregate_resources, UpstreamError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sahayata")

app = FastAPI(title="Sahayata Atlas API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request id to every request/response and time the request."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={"path": request.url.path, "duration_ms": round(duration_ms, 1), "request_id": request_id},
        )
        return response


app.add_middleware(RequestIDMiddleware)


def _error_body(code: str, message: str, retryable: bool, request_id: str, details=None):
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
            "details": details or [],
        }
    }


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.retryable, request_id, exc.details),
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Translate FastAPI/Pydantic's default 422 shape into the documented error contract."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", []) if p != "query") or "request"
    message = f"Invalid value for '{field}'." if field != "request" else "Malformed query parameters."
    return JSONResponse(
        status_code=400,
        content=_error_body(
            "INVALID_REQUEST", message, False, request_id,
            details=[{"field": field, "reason": first.get("msg", "invalid")}],
        ),
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.exception("unhandled error", extra={"request_id": request_id})
    return JSONResponse(
        status_code=500,
        content=_error_body(
            "INTERNAL_ERROR",
            "An unexpected error occurred. Please try again.",
            True,
            request_id,
        ),
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


@app.get("/api/v1/health", response_model=HealthResponse)
async def health(request: Request):
    body = {
        "status": "ok",
        "version": "1.0.0",
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return JSONResponse(
        content=body,
        headers={
            "X-Request-ID": request.state.request_id,
            "Cache-Control": "no-store",
            "Content-Type": "application/json; charset=utf-8",
        },
    )


@app.get("/api/v1/resources/nearby", response_model=NearbyResponse)
async def nearby(
    request: Request,
    city: str | None = Query(default=None),
    latitude: float | None = Query(default=None),
    longitude: float | None = Query(default=None),
    radius_km: int = Query(default=10, ge=1, le=50),
):
    request_id = request.state.request_id
    has_city = city is not None and city.strip() != ""
    has_coords = latitude is not None or longitude is not None

    if has_city and has_coords:
        raise ApiError(400, "INVALID_REQUEST",
                        "Provide either a city or coordinates, not both.", False)

    if not has_city and not has_coords:
        raise ApiError(400, "INVALID_REQUEST",
                        "Provide a city name or a latitude/longitude pair.", False)

    if has_coords and (latitude is None or longitude is None):
        raise ApiError(400, "INVALID_REQUEST",
                        "Both latitude and longitude are required together.", False)

    if has_city:
        trimmed = city.strip()
        if not (2 <= len(trimmed) <= 100):
            raise ApiError(400, "INVALID_REQUEST",
                            "City name must be between 2 and 100 characters.", False)
        try:
            location = await resolve_city(trimmed)
        except LocationError as e:
            raise ApiError(e.status_code, e.code, e.message, False) from e
    else:
        try:
            validate_coordinates(latitude, longitude)
            location = await validate_coordinates_in_service_area(latitude, longitude)
        except LocationError as e:
            raise ApiError(e.status_code, e.code, e.message, False) from e

    try:
        resources, coverage = await aggregate_resources(location, radius_km)
    except UpstreamError as e:
        raise ApiError(e.status_code, e.code, e.message, True) from e

    body = {
        "schema_version": "1.0",
        "request_id": request_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "location": location.to_dict(),
        "coverage": coverage,
        "resources": [r.to_dict() for r in resources],
        "meta": {"total": len(resources)},
    }

    cache_control = "public, max-age=60, stale-if-error=300"
    return JSONResponse(
        content=body,
        headers={
            "X-Request-ID": request_id,
            "Cache-Control": cache_control,
            "Content-Type": "application/json; charset=utf-8",
        },
    )


async def validate_coordinates_in_service_area(lat: float, lon: float):
    from app.location import resolve_coordinates
    return await resolve_coordinates(lat, lon)
