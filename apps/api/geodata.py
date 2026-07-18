"""Live geospatial ingestion — real API calls, not templated output.

Every feature returned here comes from an authoritative public dataset,
queried for the *actual* project coordinates:

- Wetlands   → USFWS National Wetlands Inventory (NWI) ArcGIS MapServer
- Species    → USFWS IPaC "official species list" Location API (ESA-listed)
- Critical habitat → IPaC crithabs (only when a designated unit is present)
- Flood      → FEMA National Flood Hazard Layer (NFHL) ArcGIS
- Protected  → USGS PAD-US (nearby managed/protected areas)

Distances and bearings are computed from the returned geometry against the
site centroid — there is no hard-coded "~190 m east" template. When a layer's
live service is unreachable, that layer is reported as unavailable
(provenance = "unavailable") rather than silently backfilled with fiction.
"""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Optional

import httpx

from models import FloodZone, Habitat, ProtectedLand, Wetland

TIMEOUT = 20.0
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

NWI_URL = (
    "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/"
    "Wetlands/MapServer/0/query"
)
IPAC_URL = "https://ipac.ecosphere.fws.gov/location/api/resources"
FEMA_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
PADUS_URL = (
    "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
    "Manager_Name/FeatureServer/0/query"
)

EARTH_R = 6_371_000.0

# ESA listing-status codes IPaC returns, mapped to human labels + whether the
# code represents a currently-listed (vs proposed/candidate) species.
LISTING_STATUS = {
    "E": ("Endangered", True),
    "T": ("Threatened", True),
    "EXPN": ("Experimental Population, Non-Essential", True),
    "EXPE": ("Experimental Population, Essential", True),
    "SAT": ("Threatened (Similarity of Appearance)", True),
    "PE": ("Proposed Endangered", False),
    "PT": ("Proposed Threatened", False),
    "C": ("Candidate", False),
    "RT": ("Resolved Taxon", False),
}


# --- geometry helpers -------------------------------------------------------

def _compass(bearing_deg: float) -> str:
    return COMPASS[int(((bearing_deg % 360) + 22.5) // 45) % 8]


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, in degrees."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    """Normalize esriGeometry / GeoJSON polygon into a list of [lon,lat] rings."""
    if not geometry:
        return []
    if "rings" in geometry:
        return geometry["rings"]
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        return coords
    if gtype == "MultiPolygon":
        return [ring for poly in coords for ring in poly]
    return []


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _seg_dist_m(lat: float, lon: float, a: list[float], b: list[float]) -> float:
    """Distance (m) from point to segment a-b, in a local equirectangular frame."""
    mlat = math.radians(lat)
    kx = 111_320 * math.cos(mlat)
    ky = 111_320
    px, py = 0.0, 0.0
    ax, ay = (a[0] - lon) * kx, (a[1] - lat) * ky
    bx, by = (b[0] - lon) * kx, (b[1] - lat) * ky
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def nearest_distance_m(lat: float, lon: float, geometry: dict[str, Any]) -> float:
    """0 if the point is inside the polygon, else nearest-edge distance in metres."""
    rings = _rings(geometry)
    if not rings:
        return float("inf")
    for ring in rings:
        if _point_in_ring(lon, lat, ring):
            return 0.0
    best = float("inf")
    for ring in rings:
        for i in range(len(ring) - 1):
            best = min(best, _seg_dist_m(lat, lon, ring[i], ring[i + 1]))
    return best


def _feature_bearing(lat: float, lon: float, geometry: dict[str, Any]) -> str:
    """Compass bearing from site to the polygon's centroid."""
    rings = _rings(geometry)
    if not rings:
        return "—"
    ring = rings[0]
    clon = sum(p[0] for p in ring) / len(ring)
    clat = sum(p[1] for p in ring) / len(ring)
    return _compass(_bearing(lat, lon, clat, clon))


def _to_geojson(geometry: dict[str, Any]) -> dict[str, Any]:
    """Convert an esri polygon to a GeoJSON Polygon for the frontend map."""
    rings = _rings(geometry)
    return {"type": "Polygon", "coordinates": rings}


# --- NWI wetlands -----------------------------------------------------------

# NWI ATTRIBUTE code prefix → NWI system (for a plain-language type when the
# WETLAND_TYPE field is terse). Codes follow Cowardin classification.
def _wetland_state_class(state_code: Optional[str], acres: float) -> tuple[bool, Optional[str]]:
    """Best-effort *conditional* state-jurisdiction flag from real acreage.

    We do NOT assert a state class we can't verify. We only note where the
    real mapped size crosses a state's statutory size threshold, which is a
    defensible, data-grounded signal (final status still needs delineation).
    """
    if state_code == "NY" and acres >= 12.4:
        return True, "Likely NYS-regulated (≥12.4 ac, ECL Art. 24 threshold) — confirm by delineation"
    if state_code == "NJ":
        return True, "May be NJ-regulated (FWPA) — resource-value class set by delineation"
    return False, None


async def _fetch_wetlands(
    client: httpx.AsyncClient, lat: float, lon: float, half_m: float, state_code: Optional[str]
) -> Optional[list[Wetland]]:
    geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})
    params = {
        "geometry": geom,
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": 1600,
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "Wetlands.ATTRIBUTE,Wetlands.WETLAND_TYPE,Wetlands.ACRES",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    try:
        resp = await client.get(NWI_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        feats = data.get("features", [])
    except Exception:
        return None

    scored: list[tuple[float, Wetland]] = []
    for i, f in enumerate(feats):
        a = f.get("attributes", {})
        geometry = f.get("geometry", {})
        dist = nearest_distance_m(lat, lon, geometry)
        if not math.isfinite(dist):
            continue
        acres = float(a.get("Wetlands.ACRES") or 0.0)
        code = (a.get("Wetlands.ATTRIBUTE") or "").strip()
        wtype = (a.get("Wetlands.WETLAND_TYPE") or "Wetland").strip()
        protected, state_class = _wetland_state_class(state_code, acres)
        crosses = dist <= half_m
        scored.append(
            (
                dist,
                Wetland(
                    id=f"NWI-{code or i}-{i}",
                    name=f"Unnamed {wtype.lower()}",
                    classification=code or "n/a",
                    wetland_type=wtype,
                    distance_m=round(dist, 1),
                    bearing=_feature_bearing(lat, lon, geometry),
                    area_acres=round(acres, 2),
                    state_protected=protected,
                    state_class=state_class,
                    geometry=_to_geojson(geometry),
                    name_verified=False,
                    crosses_footprint=crosses,
                    data_source="USFWS National Wetlands Inventory (live query)",
                ),
            )
        )
    scored.sort(key=lambda t: t[0])
    return [w for _, w in scored[:8]]


# --- IPaC species + critical habitat ---------------------------------------

async def _fetch_species(
    client: httpx.AsyncClient, lat: float, lon: float, half_m: float
) -> Optional[list[Habitat]]:
    # A small footprint polygon around the site (IPaC wants an area).
    d = max(half_m, 400) / 111_320
    dlon = d / max(math.cos(math.radians(lat)), 0.1)
    footprint = {
        "type": "Polygon",
        "coordinates": [[
            [lon - dlon, lat - d], [lon + dlon, lat - d],
            [lon + dlon, lat + d], [lon - dlon, lat + d], [lon - dlon, lat - d],
        ]],
    }
    body = {
        "location.footprint": json.dumps(footprint),
        "timeoutInMinutes": 2,
        "apiVersion": "1.0.0",
        "includeOtherFwsResources": False,
        "includeCrithabGeometry": False,
    }
    try:
        resp = await client.post(IPAC_URL, json=body)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    res = data.get("resources", {})
    pops = res.get("allReferencedPopulationsBySid", {})
    crithab_sids = set()
    for ch in res.get("crithabs", []) or []:
        sid = ch.get("sid") or ch.get("populationSid")
        if sid:
            crithab_sids.add(str(sid))

    habitats: list[Habitat] = []
    for sid, p in pops.items():
        code = p.get("listingStatusCode")
        info = LISTING_STATUS.get(code)
        if not info:
            continue
        label, is_listed = info
        # Only surface currently-listed species (proposed/candidate noted separately below).
        common = p.get("optionalCommonName") or "Listed species"
        sci = p.get("optionalScientificName") or ""
        has_ch = str(sid).split("[")[-1].rstrip("]") in crithab_sids
        habitats.append(
            Habitat(
                id=f"IPAC-{str(sid).replace('$','-').replace('[','-').replace(']','')}",
                species=sci,
                common_name=common,
                status=label,
                unit_name=(
                    "Designated critical habitat overlaps the location"
                    if has_ch
                    else "IPaC official species list — may be present in the action area"
                ),
                distance_m=None,
                bearing=None,
                geometry=None,
                basis="critical_habitat" if has_ch else "ipac_species_list",
                currently_listed=is_listed,
                source="USFWS IPaC (live query)",
            )
        )
    # Listed species first, then proposed/candidate; stable within groups.
    habitats.sort(key=lambda h: (not h.currently_listed, h.common_name))
    return habitats


# --- FEMA flood -------------------------------------------------------------

async def _fetch_flood(
    client: httpx.AsyncClient, lat: float, lon: float
) -> Optional[list[FloodZone]]:
    geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})
    params = {
        "geometry": geom,
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": 1200,
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    try:
        resp = await client.get(FEMA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        feats = data.get("features", [])
    except Exception:
        return None

    zones: list[tuple[float, FloodZone]] = []
    for i, f in enumerate(feats):
        a = f.get("attributes", {})
        zone = (a.get("FLD_ZONE") or "").strip()
        subty = (a.get("ZONE_SUBTY") or "").strip()
        # Skip "AREA OF MINIMAL FLOOD HAZARD" (Zone X unshaded) — not a constraint.
        if not zone or (zone == "X" and "MINIMAL" in subty.upper()):
            continue
        geometry = f.get("geometry", {})
        dist = nearest_distance_m(lat, lon, geometry)
        desc = subty or {
            "AE": "1% annual chance flood hazard (base flood elevation determined)",
            "A": "1% annual chance flood hazard",
            "AO": "Shallow flooding (sheet flow)",
            "VE": "Coastal high hazard (wave action)",
            "X": "0.2% annual chance / reduced-risk area",
        }.get(zone, f"FEMA flood zone {zone}")
        zones.append(
            (
                dist,
                FloodZone(
                    id=f"NFHL-{zone}-{i}",
                    zone=zone,
                    description=desc,
                    distance_m=round(dist, 1),
                    geometry=_to_geojson(geometry),
                    source="FEMA National Flood Hazard Layer (live query)",
                ),
            )
        )
    zones.sort(key=lambda t: t[0])
    return [z for _, z in zones[:3]]


# --- PAD-US nearby protected areas -----------------------------------------

async def _fetch_protected(
    client: httpx.AsyncClient, lat: float, lon: float
) -> Optional[list[ProtectedLand]]:
    geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})
    params = {
        "geometry": geom,
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": 5000,
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "Unit_Nm,Des_Tp,Loc_Ds,Mang_Name,Mang_Type",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultRecordCount": 12,
    }
    try:
        resp = await client.get(PADUS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        feats = data.get("features", [])
    except Exception:
        return None

    manager_names = {
        "NPS": "National Park Service", "FWS": "U.S. Fish and Wildlife Service",
        "USFS": "U.S. Forest Service", "BLM": "Bureau of Land Management",
        "STAT": "State agency", "LOC": "Local government", "PVT": "Private",
        "NGO": "Non-governmental organization", "JNT": "Joint management",
    }
    seen: set[str] = set()
    out: list[tuple[float, ProtectedLand]] = []
    for i, f in enumerate(feats):
        a = f.get("attributes", {})
        name = (a.get("Unit_Nm") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        geometry = f.get("geometry", {})
        dist = nearest_distance_m(lat, lon, geometry)
        desig = (a.get("Loc_Ds") or a.get("Des_Tp") or "Protected/managed area").strip()
        mang = manager_names.get((a.get("Mang_Name") or "").strip(), (a.get("Mang_Name") or "land manager").strip())
        out.append(
            (
                dist,
                ProtectedLand(
                    id=f"PADUS-{i}",
                    name=name,
                    designation=desig,
                    manager=mang,
                    distance_m=round(dist, 1),
                    bearing=_feature_bearing(lat, lon, geometry),
                    geometry=_to_geojson(geometry),
                    name_verified=True,
                    source="USGS PAD-US (live query)",
                ),
            )
        )
    out.sort(key=lambda t: t[0])
    return [p for _, p in out[:3]]


# --- orchestration ----------------------------------------------------------

async def fetch_all(
    lat: float, lon: float, acreage: float, state_code: Optional[str] = None
) -> dict[str, Any]:
    """Query every live layer concurrently. Returns features + provenance.

    provenance values per layer:
      "live"        — service answered (may legitimately be an empty list)
      "unavailable" — service unreachable / errored (no fabricated backfill)
    """
    half_m = math.sqrt(acreage * 4046.86) / 2
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "GridSentry/1.0"}) as client:
        wetlands, habitats, flood, protected = await asyncio.gather(
            _fetch_wetlands(client, lat, lon, half_m, state_code),
            _fetch_species(client, lat, lon, half_m),
            _fetch_flood(client, lat, lon),
            _fetch_protected(client, lat, lon),
        )
    provenance = {
        "wetlands": "live" if wetlands is not None else "unavailable",
        "species": "live" if habitats is not None else "unavailable",
        "flood": "live" if flood is not None else "unavailable",
        "protected": "live" if protected is not None else "unavailable",
    }
    return {
        "wetlands": wetlands or [],
        "habitats": habitats or [],
        "flood_zones": flood or [],
        "protected_lands": protected or [],
        "provenance": provenance,
        "half_m": half_m,
    }


async def fetch_wetlands_stateaware(
    lat: float, lon: float, acreage: float, state_code: Optional[str]
) -> Optional[list[Wetland]]:
    half_m = math.sqrt(acreage * 4046.86) / 2
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "GridSentry/1.0"}) as client:
        return await _fetch_wetlands(client, lat, lon, half_m, state_code)
