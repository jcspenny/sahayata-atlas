"""
Aggregates resource listings from upstream providers (currently OpenStreetMap
via the Overpass API), classifies and deduplicates them, computes distance,
and produces the coverage block described in the API agreement.
"""
import math
import httpx

from app.config import settings

OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:{timeout}];
(
  node["amenity"="hospital"](around:{radius},{lat},{lon});
  way["amenity"="hospital"](around:{radius},{lat},{lon});
  node["amenity"="clinic"](around:{radius},{lat},{lon});
  way["amenity"="clinic"](around:{radius},{lat},{lon});
  node["healthcare"="clinic"](around:{radius},{lat},{lon});
  node["amenity"="community_centre"](around:{radius},{lat},{lon});
  node["amenity"="social_facility"](around:{radius},{lat},{lon});
  node["amenity"="police"](around:{radius},{lat},{lon});
  way["amenity"="police"](around:{radius},{lat},{lon});
  node["amenity"="townhall"](around:{radius},{lat},{lon});
  node["office"="government"](around:{radius},{lat},{lon});
);
out center tags;
"""


class UpstreamError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ResourceRecord:
    def __init__(self, id_, name, category, facility_type, latitude, longitude,
                 distance_metres, org_type, org_name, org_inferred, source_name,
                 record_id, record_url, updated_at):
        self.id = id_
        self.name = name
        self.category = category
        self.facility_type = facility_type
        self.latitude = latitude
        self.longitude = longitude
        self.distance_metres = distance_metres
        self.org_type = org_type
        self.org_name = org_name
        self.org_inferred = org_inferred
        self.source_name = source_name
        self.record_id = record_id
        self.record_url = record_url
        self.updated_at = updated_at

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "facility_type": self.facility_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "distance_metres": self.distance_metres,
            "organisation": {
                "type": self.org_type,
                "name": self.org_name,
                "inferred": self.org_inferred,
            },
            "listing_status": "listed",
            "source": {
                "name": self.source_name,
                "record_id": self.record_id,
                "record_url": self.record_url,
                "updated_at": self.updated_at,
            },
        }


def _haversine_metres(lat1, lon1, lat2, lon2):
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _classify(tags: dict):
    amenity = tags.get("amenity")
    healthcare = tags.get("healthcare")
    office = tags.get("office")

    if amenity == "hospital":
        return "medical", "hospital"
    if amenity == "clinic" or healthcare == "clinic":
        return "medical", "clinic"
    if amenity in ("social_facility", "community_centre"):
        return "shelter", "public_place"
    if amenity == "police":
        return "security", "public_place"
    if amenity == "townhall" or office == "government":
        return "general", "public_place"
    return "general", "public_place"


GOVERNMENT_HINTS = ("municipal", "government", "govt", "district", "state", "national", "public")


def _infer_organisation(tags: dict):
    operator = tags.get("operator")
    operator_type = tags.get("operator:type")
    name = tags.get("name", "")

    if operator_type == "government":
        return "government", operator, False
    if operator_type == "private":
        return "private", operator, False
    if operator_type in ("ngo", "cooperative"):
        return "public_sector", operator, False

    haystack = f"{operator or ''} {name}".lower()
    if any(hint in haystack for hint in GOVERNMENT_HINTS):
        return "government", operator or None, True

    if operator:
        return "private", operator, True

    return "unclassified", None, True


def _dedup_key(name: str, lat: float, lon: float):
    # Round coordinates to ~11m precision and normalise name for near-duplicate collapsing.
    return (round(lat, 4), round(lon, 4), (name or "").strip().lower())


async def aggregate_resources(location, radius_km: int):
    radius_metres = radius_km * 1000

    query = OVERPASS_QUERY_TEMPLATE.format(
        timeout=30,
        radius=radius_metres,
        lat=location.latitude,
        lon=location.longitude,
    )

    warnings = []
    is_partial = False
    elements = []

    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
    ]

    headers = {
        "User-Agent": "SahayataAtlas/1.0"
    }

    for server in overpass_servers:
        try:
            print(f"Trying Overpass server: {server}")

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    server,
                    data={"data": query},
                    headers=headers,
                )

            print(f"Overpass status: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])

                print(f"Found {len(elements)} elements")

                break

        except Exception as e:
            print(f"Overpass server failed: {server}")
            print(str(e))

    if not elements:
        warnings.append(
            "Live facility data is temporarily unavailable."
        )
        is_partial = True

    seen = {}

    for el in elements:

        tags = el.get("tags", {})

        name = tags.get("name")

        if not name:
            continue

        name = name.strip()[:200]

        if el["type"] == "node":

            lat = el.get("lat")
            lon = el.get("lon")

        else:

            center = el.get("center") or {}

            lat = center.get("lat")
            lon = center.get("lon")

        if lat is None or lon is None:
            continue

        category, facility_type = _classify(tags)

        org_type, org_name, org_inferred = _infer_organisation(tags)

        distance = round(
            _haversine_metres(
                location.latitude,
                location.longitude,
                lat,
                lon,
            )
        )

        obj_type_short = {
            "node": "node",
            "way": "way",
            "relation": "relation",
        }.get(el["type"], "node")

        record = ResourceRecord(

            id_=f"osm:{obj_type_short}:{el['id']}",

            name=name,

            category=category,

            facility_type=facility_type,

            latitude=lat,

            longitude=lon,

            distance_metres=distance,

            org_type=org_type,

            org_name=org_name,

            org_inferred=org_inferred,

            source_name="OpenStreetMap",

            record_id=f"{obj_type_short}/{el['id']}",

            record_url=f"https://www.openstreetmap.org/{obj_type_short}/{el['id']}",

            updated_at=None,
        )

        key = _dedup_key(name, lat, lon)

        existing = seen.get(key)

        if (
            existing is None
            or record.distance_metres < existing.distance_metres
        ):
            seen[key] = record

    resources = list(seen.values())

    resources.sort(
        key=lambda r: (
            r.distance_metres is None,
            r.distance_metres or 0,
        )
    )

    resources = resources[:settings.max_resources]

    healthcare_status = "available"

    if not any(r.category == "medical" for r in resources):

        healthcare_status = "unavailable"

    if is_partial:

        healthcare_status = "partial"

    coverage = {

        "radius_metres": radius_metres,

        "healthcare_status": healthcare_status,

        "is_partial": is_partial,

        "warnings": warnings,

    }

    return resources, coverage