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
- `apps/api/tests` — pytest suite (offline, with recorded service payloads) plus
  opt-in live checks against the real federal services

## Live geospatial data (`geodata.py`)

Environmental findings come from real, per-coordinate queries against public
federal datasets — not a template. Distances/bearings are computed from the
returned geometry, so results genuinely vary by site:

- **Wetlands** → USFWS National Wetlands Inventory (NWI) ArcGIS MapServer,
  with an exact polygon-vs-footprint overlap flag (`crosses_footprint`).
  State-regulated flags apply only to palustrine vegetated wetlands in a
  *verified* jurisdiction (streams and lakes are not freshwater wetlands).
- **Species** → USFWS IPaC official-species-list Location API, separating
  designated critical habitat in the footprint (HIGH), proposed critical
  habitat, ESA-listed species (a presence screen), and taxa with no §7
  obligation (proposed/candidate, non-essential experimental populations).
- **Flood** → FEMA National Flood Hazard Layer (NFHL). Only the 1%-annual-chance
  Special Flood Hazard Area (A*/V* zones) counts as floodplain; shaded Zone X
  and Zone D (undetermined) are reported but are not floodplain constraints.
- **Protected areas** → USGS PAD-US (real unit names and managers). A
  footprint overlap with land managed for biodiversity (GAP 1–2) or a site
  inside dedicated parkland is HIGH.

Geometry is generalized server-side (~5 m), so a run stays in the hundreds of
kilobytes rather than 4–10 MB, and each layer has a hard deadline.

Every layer carries a provenance flag (`live` / `unavailable` / `simulated` /
`not_assessed`). A layer that did not answer is reported as **NOT ASSESSED**,
never as clean, and blocks a Categorical Exclusion recommendation. If all live
services are unreachable, ingestion falls back to a clearly flagged synthetic
payload: every feature and section is labelled SIMULATED, no review level is
recommended, and the Red-Team Critic raises a blocker. Risk scoring is derived
from what the data actually shows. Any one of a vegetated wetland in the
footprint, designated critical habitat, or protected land in the footprint
drives HIGH. Open-water ponds and nearby-only features are moderate or low,
and a genuinely clean site can reach a Categorical Exclusion.

## Grounding (jurisdiction + named-entity verification)

Before any environmental data is generated, `grounding.py` resolves the site's
**real** state and county by reverse-geocoding the coordinates (OpenStreetMap
Nominatim) and cross-checking them against the **U.S. Census Bureau's TIGER
boundaries** (free, no key). A state counts as verified only when the Census
places the point in it. If Nominatim and the Census disagree (border sites),
the jurisdiction is marked unverified. This prevents the two failure modes a
compliance tool cannot have:

- **Wrong-state citations** — state law (e.g. NY 6 NYCRR Part 663 vs. NJ
  N.J.A.C. 7:7A) is chosen from the *verified* state, never a coordinate
  bounding box. If the state can't be verified, state citations are withheld
  and the Red-Team Critic raises a blocker.
- **Fabricated named entities** — NWI wetland polygons are unnamed in the
  source data, so they get descriptive labels ("Unnamed freshwater emergent
  wetland") flagged `name_verified: false`, never invented proper nouns.
  Protected-area names come straight from PAD-US.

Optionally, a Tavily key adds web sources on the state's wetland program to a
verified jurisdiction (it is not needed for verification):

```bash
export TAVILY_API_KEY=tvly-...   # or put it in apps/api/.env — see apps/api/.env.example
```

If the Census is unreachable, grounding falls back to Nominatim alone (marked
unverified, so state citations are withheld). Fully offline, it falls back to a
coarse bounding box (also unverified).

## Land Status Gate (threshold feasibility checks)

Before the agent pipeline runs, `land_status.py` answers "can anything be
built here at all?" with deterministic checks against authoritative federal
data, no LLM involved:

0. **Coverage**: if neither the Census nor OpenStreetMap places the point in a
   U.S. state (a foreign country, or open ocean beyond state waters), the run
   halts with "outside analysis coverage". Every dataset below is U.S.-only,
   so an empty answer there means "no data", not "no constraints".
1. **Ownership (legal eligibility)** — point-in-polygon against USGS PAD-US.
   A site inside a National Park, Wilderness Area, Wildlife Refuge, etc.
   short-circuits to a "not viable" eligibility determination. The governing
   statutes are chosen by designation *and* managing agency (a Fish & Wildlife
   Service wilderness cites the Wilderness Act and the Refuge Administration
   Act, not the NPS Organic Act).
2. **Buildability (physical plausibility)** — a 5×5 grid sample of USGS/MRLC
   NLCD 2021 land cover across the proposed footprint. If ≥50% of samples are
   medium/high-intensity developed (dense urban core) or ≥60% open water, the
   input is rejected as physically infeasible — a several-hundred-acre
   greenfield project cannot exist in Midtown Manhattan or on the ocean.
   NLCD no-data pixels (outside the CONUS raster) never count as land.

Both checks have curated offline fallbacks (major federal units, major urban
cores) so flagship failure cases still gate without network access, marked
unverified.

## Quick start

```bash
# 1. Install frontend deps (workspace root)
npm install

# 2. Set up the Python API (creates apps/api/.venv with runtime + test deps)
npm run setup:api

# 3. Run both services
npm run dev
# web: http://localhost:3000   api: http://localhost:8000
```

Requirements: Node 18.17+ (22.18+ to run the web tests) and Python 3.10+
(tested on 3.12 and 3.14). No API keys are needed; optional settings are listed
in `apps/api/.env.example` and `apps/web/.env.example`.

The analyzer takes coordinates (decimal degrees such as `42.9, -74.3`, or
hemisphere form such as `42.9°N, 74.3°W`), a project type, and an optional
footprint in acres. If you leave the acreage blank, a 300-acre square footprint is assumed,
labelled "(assumed)" in the report, and flagged by the Red-Team Critic. Every
"inside the footprint" finding depends on that value.

## Tests

```bash
npm run test:api    # 85 offline tests: parsers on recorded payloads, gates, report logic, API/SSE
npm run test:web    # 21 coordinate-input parsing tests (Node >= 22.18, no extra deps)
npm run test:live   # opt-in: full pipeline against the live federal services
```

## LLM keys (optional)

The agent pipeline uses a real LLM when a key is available, and falls back to
a deterministic offline reasoning engine otherwise, so the demo works either way.
The LLM only rewrites narrative summaries: findings, risk, citations and
provenance stay deterministic. It sees attributes and distances, never raw
polygons, and it never narrates simulated data. The report's `Engine` label
names an LLM only if a call actually succeeded.

```bash
export OPENAI_API_KEY=sk-...        # model: OPENAI_MODEL (default gpt-4o-mini), or
export ANTHROPIC_API_KEY=sk-ant-... # model: ANTHROPIC_MODEL (default claude-haiku-4-5)
```

## Deployment (why the hosted site needs two services)

The frontend (`apps/web`) and the API (`apps/api`) deploy separately. The API
holds long-lived Server-Sent Event connections for the live agent progress
stream, which Vercel's serverless functions do not support — so host the API on
a platform that keeps a process running (Render, Railway, Fly.io, etc.).

If the hosted site shows *"Could not reach the analysis engine at …"*, the
URL in the message is the API the frontend is calling. Without
`NEXT_PUBLIC_API_URL`, dev builds call `localhost:8000` and production builds
call `https://gridsentry-api.onrender.com`. On Render's free plan the first
request after a spin-down can take ~1 minute.

**1. Deploy the API** (Render, using the included `render.yaml`):

- Render dashboard → New → Blueprint → select this repo → apply.
- This builds `apps/api` and runs `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- Optionally set `TAVILY_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the dashboard.
- Copy the resulting public URL, e.g. `https://gridsentry-api.onrender.com`.

**2. Point the frontend at it** (Vercel → project → Settings → Environment
Variables), then redeploy:

```
NEXT_PUBLIC_API_URL = https://gridsentry-api.onrender.com   # baked into the browser bundle
API_URL             = https://gridsentry-api.onrender.com   # used by the server-side PDF route
```

`NEXT_PUBLIC_API_URL` is read at build time, so a **redeploy is required** after
setting it. CORS is already open on the API (`allow_origins=["*"]`).

The map uses Esri's keyless World Dark Gray basemap (CARTO's `dark_all` tiles
now need an API key). Set `NEXT_PUBLIC_TILE_URL` to use another tile provider
(see `apps/web/.env.example`).

Runs are stored in SQLite (`apps/api/gridsentry.db`). On Render's free plan the
disk is ephemeral, so saved runs disappear on redeploy. If the API restarts
mid-run with no client connected, that run is marked "interrupted" rather than
left hanging.

## Demo script

Paste `42.9000, -74.3000` (Mohawk Valley farmland, upstate New York) into the
analyzer, or click anywhere on the map. In about 20 seconds GridSentry verifies
the jurisdiction (Montgomery County, NY, confirmed by OpenStreetMap and the U.S.
Census). With the default 300-acre footprint, live NWI data places a
scrub-shrub wetland (PSS1E) and a streambed inside the footprint, so the site
is HIGH risk and routed to an Environmental Assessment. The report cites
CWA §404 / 33 CFR §328.3 and proposes a wetland setback and an interconnection
re-route. Re-run with a 40-acre footprint and the conflict disappears (LOW risk).

Stress tests worth showing:

- `36.2120, -111.9781` (Grand Canyon): the Land Status Gate trips on federal
  ownership (USGS PAD-US) and returns "not viable" instead of a permit report.
- `40.7426, -73.9898` (Midtown Manhattan): the buildability check trips on
  NLCD land cover (100% high-intensity developed) and rejects the input as
  physically infeasible.
- `51.5000, -0.1200` (London), or the same numbers with a dropped minus sign:
  the coverage gate refuses to report a site with no U.S. data as clean.
- `35.0800, -106.6800` (Rio Grande, Albuquerque): IPaC reports designated
  critical habitat for the Rio Grande silvery minnow, so the site is HIGH risk
  with a formal §7 consultation posture.
- `39.8000, -74.5000` (NJ Pine Barrens): forested wetlands in a verified New
  Jersey jurisdiction cite N.J.S.A. 13:9B / N.J.A.C. 7:7A, and the footprint
  overlaps conservation land managed for biodiversity.

> Confidential — Demo Build
