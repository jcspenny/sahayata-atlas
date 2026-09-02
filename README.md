# Sahayata Atlas

`backend/` — FastAPI service implementing the API agreement (place resolution, OSM aggregation, dedup, error contract).
`frontend/` — static site (`index.html` + `static/`) that consumes the backend exactly per `static/config.js`.

## Get a live link in ~10 minutes (Render, free tier)

Render is used here because it deploys a Python API and a static site from
one repo with zero server management. Railway or Fly.io work too — same
shape, different dashboard.

### 1. Push this folder to GitHub

```bash
cd sahayata-atlas
git init
git add .
git commit -m "Sahayata Atlas: backend + frontend"
```
Create an empty repo on GitHub, then:
```bash
git remote add origin https://github.com/<you>/sahayata-atlas.git
git branch -M main
git push -u origin main
```

### 2. Deploy the backend

1. [render.com](https://render.com) → **New → Web Service** → connect the repo.
2. Root directory: `backend`
3. Runtime: Python 3
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Create the service. When it's live, copy its URL — something like
   `https://sahayata-atlas-api.onrender.com`.

### 3. Deploy the frontend

1. **New → Static Site** → same repo.
2. Root directory: `frontend`
3. Build command: `bash build.sh`
4. Publish directory: `.`
5. Under **Environment**, add `API_BASE_URL` = the backend URL from step 2
   (e.g. `https://sahayata-atlas-api.onrender.com` — no trailing slash).
6. Deploy. You'll get a URL like `https://sahayata-atlas-frontend.onrender.com`
   — **this is your live link.**

### 4. Point the backend's CORS at the frontend

Back on the backend service → **Environment** → add:
```
CORS_ALLOWED_ORIGINS = https://sahayata-atlas-frontend.onrender.com
```
(exact origin, no trailing slash) → save → the service redeploys automatically.

Open the frontend URL. The connection dot in the header should turn green
within a couple of seconds, and a search for "Mumbai" should return results.

### Alternative: `render.yaml` blueprint

`render.yaml` at the repo root defines both services so Render can create
them together via **New → Blueprint**. Its two URL env vars
(`CORS_ALLOWED_ORIGINS`, `API_BASE_URL`) are left as placeholders because
Render's blueprint variable references only expose a bare hostname, not a
full `https://` URL — after the first deploy, do step 4 above once (copy
each service's real URL into the other's env var, then redeploy both). After
that one-time fix, future pushes to `main` redeploy both services automatically.

## Local development

Terminal 1:
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2:
```bash
cd frontend
python3 -m http.server 5005
```

Open `http://127.0.0.1:5005`. `static/config.js` already points at
`http://127.0.0.1:8000`, matching the backend's default CORS allowlist — no
changes needed for local dev.

## Why not deployed for you automatically

This response is generated in a sandboxed environment with no inbound
networking, so nothing built here can be reached from outside it — there's
no way to hand you a working `https://` URL without a real host. The steps
above are the fastest path from this code to one.
