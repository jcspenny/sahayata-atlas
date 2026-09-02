# Sahayata Atlas Backend

Implements the "Backend Requirements and Frontend API Agreement" (v1) for the
Sahayata Atlas frontend: place resolution, resource aggregation from
OpenStreetMap, deduplication, distance calculation, provenance, and error
handling.

## Requirements

- Python 3.11+

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run locally

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The frontend's `static/config.js` should point its API base URL at
`http://127.0.0.1:8000` in local development (no version path, no trailing
slash — the code appends `/api/v1/...` itself).

## Endpoints

- `GET /api/v1/resources/nearby?city=Mumbai&radius_km=10`
- `GET /api/v1/resources/nearby?latitude=19.076&longitude=72.8777&radius_km=10`
- `GET /api/v1/health`

Interactive API docs (Swagger UI) are available at `/docs` when running.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `http://127.0.0.1:5005,http://localhost:5005` | Comma-separated allowlist |
| `NOMINATIM_BASE_URL` | `https://nominatim.openstreetmap.org` | Geocoding provider |
| `OVERPASS_BASE_URL` | `https://overpass-api.de/api/interpreter` | POI data provider |
| `NOMINATIM_USER_AGENT` | `SahayataAtlas/1.0 (contact: ops@example.org)` | Required by Nominatim's usage policy — set a real contact |
| `UPSTREAM_TIMEOUT_SECONDS` | `12` | Per-upstream-call timeout |
| `RATE_LIMIT_PER_MINUTE` | `60` | Advisory; enforce via reverse proxy/gateway in production |

For production, set `CORS_ALLOWED_ORIGINS` to the single deployed frontend
origin, and put a real rate limiter (e.g. at your reverse proxy or API
gateway) in front of this service, since in-process rate limiting is not
reliable across multiple instances.

## Design notes / how each contract requirement is met

- **Exactly one location mode**: `/api/v1/resources/nearby` rejects requests
  with both `city` and coordinates, and requests with neither, using
  `400 INVALID_REQUEST`.
- **India-only resolution**: city search calls Nominatim with
  `countrycodes=in`; coordinate search reverse-geocodes and checks the
  returned country code, additionally pre-filtering with a bounding box.
  Out-of-area coordinates return `422 LOCATION_OUTSIDE_SERVICE_AREA`.
- **Source aggregation**: resources currently come from OpenStreetMap via
  Overpass. The `aggregator.py` module is structured so additional providers
  can be merged into the same dedup step.
- **Deduplication**: records are collapsed by rounded coordinate + normalised
  name before being returned.
- **Distance**: computed server-side with the haversine formula; results are
  sorted ascending, with unknown-distance items (there are none in the OSM
  path, but the field is nullable per the contract) sorted last.
- **Provenance**: every resource carries `source.name`, `source.record_id`,
  and a public `source.record_url` pointing at the OSM object.
- **Partial-data handling**: if Overpass fails or times out but there were
  still elements from a prior successful pass, `coverage.is_partial` is set
  and a warning is added; if there is no usable data at all, the endpoint
  returns `502 UPSTREAM_FAILURE` / `504 UPSTREAM_TIMEOUT` instead of a
  misleading empty success.
- **Errors**: all non-2xx responses use the documented
  `{ "error": { code, message, retryable, request_id, details } }` shape via
  a single `ApiError` exception type and handler.
- **`X-Request-ID`**: generated per-request in middleware and returned on
  every response, success or error.
- **Privacy**: raw coordinates/city text are never written to persistent
  storage; only path, duration, and request id are logged.
- **Caching headers**: successful searches get
  `Cache-Control: public, max-age=60, stale-if-error=300`; errors and the
  health check get `Cache-Control: no-store`.

## What is intentionally out of scope here

- A production-grade distributed rate limiter (use your gateway/proxy).
- TLS termination (terminate HTTPS at your load balancer/reverse proxy).
- Dependency/secret scanning pipelines (wire into your CI).
- A persistent cache/database in front of Nominatim/Overpass — for real
  production traffic you should cache city-name → coordinate lookups and
  Overpass results to stay within those services' usage policies, or run
  self-hosted instances.

## Manual smoke test

```bash
curl "http://127.0.0.1:8000/api/v1/resources/nearby?city=Mumbai&radius_km=10"
curl "http://127.0.0.1:8000/api/v1/resources/nearby?latitude=19.076&longitude=72.8777"
curl "http://127.0.0.1:8000/api/v1/resources/nearby?city=Paris"          # 404 LOCATION_NOT_FOUND
curl "http://127.0.0.1:8000/api/v1/resources/nearby?latitude=48.85&longitude=2.35"  # 422 LOCATION_OUTSIDE_SERVICE_AREA
curl "http://127.0.0.1:8000/api/v1/resources/nearby?city=Mumbai&latitude=19&longitude=72" # 400 INVALID_REQUEST
curl "http://127.0.0.1:8000/api/v1/health"
```
