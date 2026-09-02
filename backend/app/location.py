"""
Location resolution.

- City mode: geocode via Nominatim, restricted to India (countrycodes=in).
- Coordinate mode: validate range and reverse-geocode to check the point
  falls within the supported Indian service area.
"""
import httpx

from app.config import settings

# Rough bounding box for India (including islands), used as a cheap first-pass
# reject before hitting the reverse-geocoder for out-of-area coordinates.
INDIA_BBOX = {
    "min_lat": 6.5,
    "max_lat": 37.6,
    "min_lon": 68.0,
    "max_lon": 97.5,
}


class LocationError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ResolvedLocation:
    def __init__(self, query_type, display_name, city, district, state,
                 country_code, latitude, longitude):
        self.query_type = query_type
        self.display_name = display_name
        self.city = city
        self.district = district
        self.state = state
        self.country_code = country_code
        self.latitude = latitude
        self.longitude = longitude

    def to_dict(self):
        return {
            "query_type": self.query_type,
            "display_name": self.display_name,
            "city": self.city,
            "district": self.district,
            "state": self.state,
            "country_code": self.country_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


def validate_coordinates(latitude: float, longitude: float) -> None:
    if latitude is None or longitude is None:
        raise LocationError(400, "INVALID_REQUEST", "Latitude and longitude are both required.")
    if not (-90 <= latitude <= 90):
        raise LocationError(400, "INVALID_REQUEST", "Latitude must be between -90 and 90.")
    if not (-180 <= longitude <= 180):
        raise LocationError(400, "INVALID_REQUEST", "Longitude must be between -180 and 180.")


async def resolve_city(city: str) -> ResolvedLocation:
    params = {
        "q": city,
        "format": "jsonv2",
        "countrycodes": "in",
        "addressdetails": 1,
        "limit": 1,
    }
    headers = {"User-Agent": settings.nominatim_user_agent}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.get(f"{settings.nominatim_base_url}/search", params=params, headers=headers)
    except httpx.TimeoutException as e:
        raise LocationError(504, "UPSTREAM_TIMEOUT", "Location lookup timed out. Please try again.") from e
    except httpx.HTTPError as e:
        raise LocationError(502, "UPSTREAM_FAILURE", "Location lookup service failed. Please try again.") from e

    if resp.status_code != 200:
        raise LocationError(502, "UPSTREAM_FAILURE", "Location lookup service failed. Please try again.")

    results = resp.json()
    if not results:
        raise LocationError(404, "LOCATION_NOT_FOUND", "That city could not be found in India.")

    top = results[0]
    address = top.get("address", {})
    country_code = (address.get("country_code") or "").upper()
    if country_code != "IN":
        raise LocationError(404, "LOCATION_NOT_FOUND", "That city could not be found in India.")

    resolved_city = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("municipality") or city
    )
    district = address.get("state_district") or address.get("county")
    state = address.get("state")

    return ResolvedLocation(
        query_type="city",
        display_name=top.get("display_name", city).split(",")[0].strip() or city,
        city=resolved_city,
        district=district,
        state=state,
        country_code="IN",
        latitude=float(top["lat"]),
        longitude=float(top["lon"]),
    )


async def resolve_coordinates(latitude: float, longitude: float) -> ResolvedLocation:
    if not (INDIA_BBOX["min_lat"] <= latitude <= INDIA_BBOX["max_lat"]
            and INDIA_BBOX["min_lon"] <= longitude <= INDIA_BBOX["max_lon"]):
        raise LocationError(422, "LOCATION_OUTSIDE_SERVICE_AREA",
                             "These coordinates are outside the supported service area.")

    params = {"lat": latitude, "lon": longitude, "format": "jsonv2", "addressdetails": 1, "zoom": 10}
    headers = {"User-Agent": settings.nominatim_user_agent}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.get(f"{settings.nominatim_base_url}/reverse", params=params, headers=headers)
    except httpx.TimeoutException as e:
        raise LocationError(504, "UPSTREAM_TIMEOUT", "Location lookup timed out. Please try again.") from e
    except httpx.HTTPError as e:
        raise LocationError(502, "UPSTREAM_FAILURE", "Location lookup service failed. Please try again.") from e

    if resp.status_code != 200:
        raise LocationError(502, "UPSTREAM_FAILURE", "Location lookup service failed. Please try again.")

    data = resp.json()
    address = data.get("address", {})
    country_code = (address.get("country_code") or "").upper()

    if country_code != "IN":
        raise LocationError(422, "LOCATION_OUTSIDE_SERVICE_AREA",
                             "These coordinates are outside the supported service area.")

    resolved_city = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("municipality")
    )
    district = address.get("state_district") or address.get("county")
    state = address.get("state")
    display_name = resolved_city or district or state or "Selected location"

    return ResolvedLocation(
        query_type="coordinates",
        display_name=display_name,
        city=resolved_city,
        district=district,
        state=state,
        country_code="IN",
        latitude=latitude,
        longitude=longitude,
    )
