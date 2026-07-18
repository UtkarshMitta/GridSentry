# GridSentry

Autonomous NEPA environmental permit agent. Ingests proposed energy
infrastructure coordinates and auto-generates a fully cited environmental
impact assessment draft by cross-referencing wetlands, endangered species
habitat, and protected lands data.

## Architecture

- `apps/web` — Next.js 14 (App Router), TypeScript, Tailwind, Framer Motion, Leaflet
- `apps/api` — Python FastAPI: real-world grounding, **live** GIS ingestion,
  3-agent pipeline (Geolocation Analyst → Legal Compliance Officer →
  Red-Team Critic), SSE progress streaming, SQLite persistence

## Live geospatial data (`geodata.py`)

Environmental findings come from real, per-coordinate queries against public
federal datasets — not a template. Distances/bearings are computed from the
returned geometry, so results genuinely vary by site:

- **Wetlands** → USFWS National Wetlands Inventory (NWI) ArcGIS MapServer,
  with a footprint-overlap flag (`crosses_footprint`) from real polygons.
- **Species** → USFWS IPaC official-species-list Location API (ESA-listed +
  proposed/candidate), distinguishing designated critical habitat from a
  species-presence screen.
- **Flood** → FEMA National Flood Hazard Layer (NFHL).
- **Protected areas** → USGS PAD-US (nearby managed units, real names).

Every layer carries a provenance flag (`live` / `unavailable` / `simulated`).
If all live services are unreachable, ingestion falls back to a clearly
flagged synthetic payload and the Red-Team Critic raises a blocker — synthetic
features are never presented as real findings. Risk scoring is derived from
what the data actually shows (a footprint vegetated-wetland conflict or
designated critical habitat drives HIGH; open-water ponds or nearby-only
features are moderate/low; a genuinely clean site can reach a Categorical
Exclusion).

## Grounding (jurisdiction + named-entity verification)

Before any environmental data is generated, `grounding.py` resolves the site's
**real** state and county by reverse-geocoding the coordinates (OpenStreetMap
Nominatim) and cross-checking the state's wetland program via Tavily web
search. This prevents the two failure modes a compliance tool cannot have:

- **Wrong-state citations** — state law (e.g. NY 6 NYCRR Part 663 vs. NJ
  N.J.A.C. 7:7A) is chosen from the *verified* state, never a coordinate
  bounding box. If the state can't be verified, state citations are withheld
  and the Red-Team Critic raises a blocker.
- **Fabricated named entities** — wetland/protected-land names are honest
  descriptive placeholders anchored to the real county, flagged
  `name_verified: false`, never invented proper nouns.

Set the Tavily key (a working dev key is already in `apps/api/.env`):

```bash
export TAVILY_API_KEY=tvly-...
```

Without it, grounding still works via Nominatim alone (marked unverified),
and fully offline it falls back to a coarse bounding box (also unverified).

## Land Status Gate (threshold feasibility checks)

Before the agent pipeline runs, `land_status.py` answers "can anything be
built here at all?" with two deterministic queries against authoritative
federal data — no LLM involved:

1. **Ownership (legal eligibility)** — point-in-polygon against USGS PAD-US.
   A site inside a National Park, Wilderness Area, Wildlife Refuge, etc.
   short-circuits to a "not viable" eligibility determination with federal
   statute citations, instead of a mitigation-style permit report.
2. **Buildability (physical plausibility)** — a 5×5 grid sample of USGS/MRLC
   NLCD 2021 land cover across the proposed footprint. If ≥50% of samples are
   medium/high-intensity developed (dense urban core) or ≥60% open water, the
   input is rejected as physically infeasible — a several-hundred-acre
   greenfield project cannot exist in Midtown Manhattan or on the ocean.

Both checks have curated offline fallbacks (major federal units, major urban
cores) so flagship failure cases still gate without network access, marked
unverified.

## Quick start

```bash
# 1. Install frontend deps (workspace root)
npm install

# 2. Set up the Python API (creates apps/api/.venv)
npm run setup:api

# 3. Run both services
npm run dev
# web: http://localhost:3000   api: http://localhost:8000
```

## LLM keys (optional)

The agent pipeline uses a real LLM when a key is available, and falls back to
a deterministic offline reasoning engine otherwise — the demo works either way.

```bash
export OPENAI_API_KEY=sk-...      # or
export ANTHROPIC_API_KEY=sk-ant-...
```

## Deployment (why the hosted site needs two services)

The frontend (`apps/web`) and the API (`apps/api`) deploy separately. The API
holds long-lived Server-Sent Event connections for the live agent progress
stream, which Vercel's serverless functions do not support — so host the API on
a platform that keeps a process running (Render, Railway, Fly.io, etc.).

If the hosted site shows *"Could not reach the analysis engine. Is the API
running on :8000?"*, it means the frontend has no API URL configured and is
falling back to `localhost:8000` (which only exists on a developer's machine).

**1. Deploy the API** (Render, using the included `render.yaml`):

- Render dashboard → New → Blueprint → select this repo → apply.
- This builds `apps/api` and runs `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- Optionally set `TAVILY_API_KEY` / `OPENAI_API_KEY` in the dashboard.
- Copy the resulting public URL, e.g. `https://gridsentry-api.onrender.com`.

**2. Point the frontend at it** (Vercel → project → Settings → Environment
Variables), then redeploy:

```
NEXT_PUBLIC_API_URL = https://gridsentry-api.onrender.com   # baked into the browser bundle
API_URL             = https://gridsentry-api.onrender.com   # used by the server-side PDF route
```

`NEXT_PUBLIC_API_URL` is read at build time, so a **redeploy is required** after
setting it. CORS is already open on the API (`allow_origins=["*"]`).

## Demo script

Paste `42.9000, -74.3000` (Mohawk Valley farmland, upstate New York) into the
analyzer, or click anywhere on the map. Within ~20 seconds GridSentry maps the
site, flags a state-protected wetland crossing ~200 yards east, cites the exact
regulation (6 NYCRR Part 663, CWA §404), and proposes an alternative routing
corridor.

Stress tests worth showing:

- `36.2120, -111.9781` (Grand Canyon) — the Land Status Gate trips on federal
  ownership (USGS PAD-US) and returns "not viable" instead of a permit report.
- `40.7426, -73.9898` (Midtown Manhattan) — the buildability check trips on
  NLCD land cover (100% high-intensity developed) and rejects the input as
  physically infeasible.

> Confidential — Demo Build
