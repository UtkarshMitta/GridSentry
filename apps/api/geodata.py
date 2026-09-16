"""Live geospatial ingestion — real API calls, not templated output.

Every feature returned here comes from an authoritative public dataset,
queried for the *actual* project coordinates:

- Wetlands   → USFWS National Wetlands Inventory (NWI) ArcGIS MapServer
- Species    → USFWS IPaC "official species list" Location API (ESA-listed)
- Critical habitat → IPaC crithabs (only when a designated unit is present)
- Flood      → FEMA National Flood Hazard Layer (NFHL) ArcGIS
- Protected  → USGS PAD-US (nearby managed/protected areas)

Distances and bearings are computed from the returned geometry against the
site centroid, and footprint overlap is an exact polygon-vs-square test —
there is no hard-coded "~190 m east" template. When a layer's live service is
unreachable (or exceeds its deadline), that layer is reported as unavailable
(provenance = "unavailable") rather than silently backfilled with fiction.
"""
from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable
from typing import Any, TypeVar

import httpx

from models import FloodZone, Habitat, ProtectedLand, Wetland

TIMEOUT = 20.0
# httpx timeouts apply per network operation, so a server that trickles bytes
# can hold a request open indefinitely. Each layer also gets a hard deadline.
LAYER_DEADLINE = 30.0
# Server-side generalization (~5 m) keeps full-resolution floodplain/wetland
# polygons from ballooning a single run to 10+ MB. Well inside NWI's own
# positional accuracy (tens of metres).
GEOMETRY_OFFSET_DEG = 0.00005
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
# Minimum search radii (m); both grow with the footprint via _search_radius_m.
NWI_SEARCH_M = 1600
FEMA_SEARCH_M = 1200

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

# ESA listing-status codes IPaC returns → (human label, subject to ESA §7
# consultation as a listed species). Nonessential experimental populations are
# treated as *proposed* for §7 purposes (ESA §10(j)(2)(C)), and
# similarity-of-appearance listings carry no §7 obligation.
LISTING_STATUS = {
    "E": ("Endangered", True),
    "T": ("Threatened", True),
    "EXPE": ("Experimental Population, Essential", True),
    "EXPN": ("Experimental Population, Non-Essential", False),
    "SAT": ("Threatened (Similarity of Appearance)", False),
    "PE": ("Proposed Endangered", False),
    "PT": ("Proposed Threatened", False),
    "C": ("Candidate", False),
    "RT": ("Resolved Taxon", False),
}

T = TypeVar("T")


# Pages fetched per layer before giving up. A footprint whose result set is
# larger is reported as not assessed rather than silently truncated.
MAX_PAGES = 5


def _search_radius_m(half_m: float, base_m: float, buffer_m: float) -> float:
    """Cover the whole square footprint (corners at half_m·√2) plus a buffer."""
    return max(base_m, half_m * math.sqrt(2) + buffer_m)


async def _query_all(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an ArcGIS query, paging past maxRecordCount until complete."""
    feats: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        resp = await client.get(url, params={**params, "resultOffset": len(feats)})
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(data["error"])
        batch = data.get("features", [])
        feats += batch
        if not data.get("exceededTransferLimit") or not batch:
            return feats
    raise ValueError(f"more than {len(feats)} features — too many to assess completely")


async def _with_deadline(coro: Awaitable[T | None]) -> T | None:
    try:
        return await asyncio.wait_for(coro, LAYER_DEADLINE)
    except Exception:  # includes asyncio.TimeoutError
        return None


def _arcgis_point_params(lat: float, lon: float, distance_m: float, out_fields: str) -> dict[str, Any]:
    return {
        "geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": distance_m,
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": GEOMETRY_OFFSET_DEG,
        "geometryPrecision": 6,
        "f": "json",
    }


# --- geometry helpers -------------------------------------------------------

def _compass(bearing_deg: float) -> str:
    return COMPASS[int(((bearing_deg % 360) + 22.5) // 45) % 8]


def _m_per_deg_lon(lat: float) -> float:
    return 111_320 * math.cos(math.radians(lat))


def _rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    """Normalize esriGeometry / GeoJSON polygon into a flat list of [lon,lat] rings."""
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


def _local_rings(lat: float, lon: float, geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Rings projected into a local equirectangular metre frame centred on the site."""
    kx, ky = _m_per_deg_lon(lat), 111_320.0
    return [[((p[0] - lon) * kx, (p[1] - lat) * ky) for p in ring] for ring in _rings(geometry)]


def _point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _origin_in_polygon(rings: list[list[tuple[float, float]]]) -> bool:
    """Even-odd rule across all rings, so a point inside a hole is outside."""
    return sum(_point_in_ring(0.0, 0.0, r) for r in rings) % 2 == 1


def _closest_on_segment(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return a
    t = max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / seg2))
    return a[0] + t * dx, a[1] + t * dy


def _nearest(lat: float, lon: float, geometry: dict[str, Any]) -> tuple[float, tuple[float, float] | None]:
    """(distance m, nearest boundary point in local metres); (0, None) if inside."""
    rings = _local_rings(lat, lon, geometry)
    if not rings:
        return float("inf"), None
    if _origin_in_polygon(rings):
        return 0.0, None
    best, best_pt = float("inf"), None
    for ring in rings:
        for i in range(len(ring) - 1):
            cx, cy = _closest_on_segment(ring[i], ring[i + 1])
            d = math.hypot(cx, cy)
            if d < best:
                best, best_pt = d, (cx, cy)
    return best, best_pt


def nearest_distance_m(lat: float, lon: float, geometry: dict[str, Any]) -> float:
    """0 if the site centroid is inside the polygon, else nearest-edge distance in metres."""
    return _nearest(lat, lon, geometry)[0]


def _segment_hits_square(a: tuple[float, float], b: tuple[float, float], h: float) -> bool:
    """Liang–Barsky clip of segment a-b against the square [-h, h]²."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] + h), (dx, h - a[0]), (-dy, a[1] + h), (dy, h - a[1])):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def footprint_overlaps(lat: float, lon: float, half_m: float, geometry: dict[str, Any]) -> bool:
    """True if the polygon intersects the square project footprint (half-side half_m)."""
    rings = _local_rings(lat, lon, geometry)
    if not rings:
        return False
    if _origin_in_polygon(rings):  # footprint centre inside (covers polygon ⊇ footprint)
        return True
    return any(
        _segment_hits_square(ring[i], ring[i + 1], half_m)
        for ring in rings
        for i in range(len(ring) - 1)
    )


def _bearing_to(lat: float, lon: float, geometry: dict[str, Any], nearest_pt: tuple[float, float] | None) -> str:
    """Compass bearing from site to the nearest boundary point (or polygon centroid if inside)."""
    if nearest_pt is None:
        rings = _local_rings(lat, lon, geometry)
        if not rings:
            return "—"
        ring = rings[0]
        nearest_pt = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    x, y = nearest_pt
    if abs(x) < 1e-6 and abs(y) < 1e-6:
        return "—"
    return _compass(math.degrees(math.atan2(x, y)))


def _signed_area(ring: list[list[float]]) -> float:
    return sum(
        ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)
    ) / 2


def _to_geojson(geometry: dict[str, Any]) -> dict[str, Any]:
    """Convert an esri polygon to GeoJSON for the frontend map.

    Esri polygons list every ring flat: clockwise rings are exteriors,
    counter-clockwise rings are holes. A multi-part feature must become a
    MultiPolygon, or Leaflet renders the second part as a hole in the first.
    """
    if not geometry:
        return {"type": "Polygon", "coordinates": []}
    if "rings" not in geometry:
        return geometry
    outers: list[list[list[list[float]]]] = []
    holes: list[list[list[float]]] = []
    for ring in geometry["rings"]:
        (outers.append([ring]) if _signed_area(ring) < 0 else holes.append(ring))
    if not outers:
        return {"type": "Polygon", "coordinates": geometry["rings"]}
    for hole in holes:
        hx, hy = hole[0]
        owner = next(
            (poly for poly in outers if _point_in_ring(hx, hy, [(p[0], p[1]) for p in poly[0]])),
            outers[0],
        )
        owner.append(hole)
    if len(outers) == 1:
        return {"type": "Polygon", "coordinates": outers[0]}
    return {"type": "MultiPolygon", "coordinates": outers}


# --- NWI wetlands -----------------------------------------------------------

# Palustrine vegetated Cowardin classes (emergent, forested, scrub-shrub,
# aquatic bed). State freshwater-wetland statutes regulate these — not
# riverine channels (R*), lakes (L*), or tidal/estuarine systems (E*, M*),
# which fall under separate stream, lake, or tidal-wetland regimes.
FRESHWATER_VEGETATED = ("PEM", "PFO", "PSS", "PAB")


def _wetland_state_class(
    state_code: str | None, acres: float, classification: str = ""
) -> tuple[bool, str | None]:
    """Best-effort *conditional* state-jurisdiction flag from real attributes.

    We do NOT assert a state class we can't verify. We only note where a
    mapped freshwater vegetated wetland meets a state's statutory screen,
    which is a defensible, data-grounded signal (final status still needs
    delineation). `state_code` must be a *verified* jurisdiction.
    """
    if not (classification or "").upper().startswith(FRESHWATER_VEGETATED):
        return False, None
    if state_code == "NY" and acres >= 12.4:
        return True, "Likely NYS-regulated (≥12.4 ac, ECL Art. 24 threshold) — confirm by delineation"
    if state_code == "NJ":
        return True, "May be NJ-regulated (FWPA) — resource-value class set by delineation"
    return False, None


async def _fetch_wetlands(
    client: httpx.AsyncClient, lat: float, lon: float, half_m: float, state_code: str | None
) -> list[Wetland] | None:
    params = _arcgis_point_params(
        lat, lon, _search_radius_m(half_m, NWI_SEARCH_M, 800),
        "Wetlands.ATTRIBUTE,Wetlands.WETLAND_TYPE,Wetlands.ACRES",
    )
    try:
        feats = await _query_all(client, NWI_URL, params)
    except Exception:
        return None

    scored: list[tuple[float, Wetland]] = []
    for i, f in enumerate(feats):
        a = f.get("attributes", {})
        geometry = f.get("geometry", {})
        dist, nearest_pt = _nearest(lat, lon, geometry)
        if not math.isfinite(dist):
            continue
        acres = float(a.get("Wetlands.ACRES") or 0.0)
        code = (a.get("Wetlands.ATTRIBUTE") or "").strip()
        wtype = (a.get("Wetlands.WETLAND_TYPE") or "Wetland").strip()
        protected, state_class = _wetland_state_class(state_code, acres, code)
        scored.append(
            (
                dist,
                Wetland(
                    id=f"NWI-{code or i}-{i}",
                    name=f"Unnamed {wtype.lower()}",
                    classification=code or "n/a",
                    wetland_type=wtype,
                    distance_m=round(dist, 1),
                    bearing=_bearing_to(lat, lon, geometry, nearest_pt),
                    area_acres=round(acres, 2),
                    state_protected=protected,
                    state_class=state_class,
                    geometry=_to_geojson(geometry),
                    name_verified=False,
                    crosses_footprint=footprint_overlaps(lat, lon, half_m, geometry),
                    source="USFWS National Wetlands Inventory (live query)",
                ),
            )
        )
    # Footprint conflicts first, then by distance.
    scored.sort(key=lambda t: (not t[1].crosses_footprint, t[0]))
    return [w for _, w in scored[:8]]


# --- IPaC species + critical habitat ---------------------------------------

def _sid_key(sid: Any) -> str | None:
    """IPaC population ids come as {"id": 176, "val": "Population$Sid[176]"} or a bare string."""
    if isinstance(sid, dict):
        sid = sid.get("val") or (f"Population$Sid[{sid['id']}]" if "id" in sid else None)
    return str(sid) if sid else None


async def _fetch_species(
    client: httpx.AsyncClient, lat: float, lon: float, half_m: float
) -> list[Habitat] | None:
    # The project footprint square itself: crithab hits are reported as
    # "intersecting the footprint", so the query area must be exactly that.
    d = half_m / 111_320
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
    in_list = res.get("populationsBySid") or {}
    # IPaC's crithabs are the critical-habitat units intersecting the footprint.
    crithab_type: dict[str, str] = {}
    for ch in res.get("crithabs", []) or []:
        key = _sid_key(ch.get("populationSid") or ch.get("sid"))
        if key:
            prev = crithab_type.get(key)
            crithab_type[key] = "Final" if "Final" in (prev, ch.get("type")) else (ch.get("type") or "Final")
    for key, entry in in_list.items():
        if isinstance(entry, dict) and entry.get("crithabInFootprint") and key not in crithab_type:
            crithab_type[key] = "Final"

    habitats: list[Habitat] = []
    for sid, p in pops.items():
        # Only species on the official list for this footprint (or with habitat in it).
        if in_list and sid not in in_list and sid not in crithab_type:
            continue
        info = LISTING_STATUS.get(p.get("listingStatusCode"))
        if not info:
            continue
        label, is_listed = info
        ch = crithab_type.get(sid)
        basis = (
            "critical_habitat" if ch == "Final"
            else "proposed_critical_habitat" if ch
            else "ipac_species_list"
        )
        habitats.append(
            Habitat(
                id=f"IPAC-{sid.replace('$', '-').replace('[', '-').replace(']', '')}",
                species=p.get("optionalScientificName") or "",
                common_name=p.get("optionalCommonName") or "Listed species",
                status=label,
                unit_name={
                    "critical_habitat": "Designated critical habitat overlaps the project footprint",
                    "proposed_critical_habitat": "Proposed critical habitat overlaps the project footprint",
                }.get(basis, "IPaC official species list — may be present in the action area"),
                basis=basis,
                currently_listed=is_listed,
                source="USFWS IPaC (live query)",
            )
        )
    # Critical habitat first, then listed, then proposed/candidate.
    habitats.sort(key=lambda h: (h.basis == "ipac_species_list", not h.currently_listed, h.common_name))
    return habitats


# --- FEMA flood -------------------------------------------------------------

FLOOD_DESCRIPTIONS = {
    "A": "1% annual chance flood hazard (no base flood elevation)",
    "AE": "1% annual chance flood hazard (base flood elevation determined)",
    "AH": "1% annual chance shallow flooding (ponding)",
    "AO": "1% annual chance shallow flooding (sheet flow)",
    "AR": "1% annual chance flood hazard (levee being restored)",
    "A99": "1% annual chance flood hazard (federal levee under construction)",
    "V": "Coastal high hazard (wave action)",
    "VE": "Coastal high hazard (wave action, base flood elevation determined)",
    "D": "Area of undetermined flood hazard (not studied)",
}
# Zones that are not flood-hazard constraints at all.
_NON_HAZARD_ZONES = {"OPEN WATER", "AREA NOT INCLUDED"}


def _is_sfha(zone: str) -> bool:
    """Special Flood Hazard Area = the 1%-annual-chance (base) floodplain."""
    return zone[:1] in ("A", "V") and zone not in _NON_HAZARD_ZONES


async def _fetch_flood(
    client: httpx.AsyncClient, lat: float, lon: float, half_m: float
) -> list[FloodZone] | None:
    params = _arcgis_point_params(lat, lon, _search_radius_m(half_m, FEMA_SEARCH_M, 400), "FLD_ZONE,ZONE_SUBTY")
    try:
        feats = await _query_all(client, FEMA_URL, params)
    except Exception:
        return None

    zones: list[FloodZone] = []
    for i, f in enumerate(feats):
        a = f.get("attributes", {})
        zone = (a.get("FLD_ZONE") or "").strip().upper()
        subty = (a.get("ZONE_SUBTY") or "").strip()
        # Unshaded Zone X ("minimal hazard") and non-hazard polygons aren't constraints.
        if not zone or zone in _NON_HAZARD_ZONES or (zone == "X" and "MINIMAL" in subty.upper()):
            continue
        geometry = f.get("geometry", {})
        dist = nearest_distance_m(lat, lon, geometry)
        if zone == "X":
            desc = (
                "Reduced flood risk due to levee" if "LEVEE" in subty.upper()
                else "0.2% annual chance flood hazard (moderate risk, outside the base floodplain)"
            )
        else:
            desc = FLOOD_DESCRIPTIONS.get(zone, subty or f"FEMA flood zone {zone}")
        zones.append(
            FloodZone(
                id=f"NFHL-{zone}-{i}",
                zone=zone,
                description=desc,
                distance_m=round(dist, 1),
                geometry=_to_geojson(geometry),
                sfha=_is_sfha(zone),
                overlaps_footprint=footprint_overlaps(lat, lon, half_m, geometry),
                source="FEMA National Flood Hazard Layer (live query)",
            )
        )
    # Base-floodplain zones first, then nearest.
    zones.sort(key=lambda z: (not z.sfha, not z.overlaps_footprint, z.distance_m))
    return zones[:4]


# --- PAD-US nearby protected areas -----------------------------------------

# PAD-US "Mang_Name" (manager name) domain codes.
PADUS_MANAGERS = {
    "BLM": "Bureau of Land Management", "BOEM": "Bureau of Ocean Energy Management",
    "BOR": "Bureau of Reclamation", "DOD": "U.S. Department of Defense", "DOE": "U.S. Department of Energy",
    "FWS": "U.S. Fish and Wildlife Service", "NOAA": "National Oceanic and Atmospheric Administration",
    "NPS": "National Park Service", "NRCS": "Natural Resources Conservation Service",
    "USACE": "U.S. Army Corps of Engineers", "USFS": "U.S. Forest Service", "TVA": "Tennessee Valley Authority",
    "OTHF": "Other federal agency", "BIA": "Bureau of Indian Affairs", "TRIB": "Tribal government",
    "SDC": "State conservation department", "SDNR": "State natural resources department",
    "SDOL": "State land department", "SFW": "State fish & wildlife agency", "SLB": "State land board",
    "SPR": "State park & recreation agency", "OTHS": "State agency (other)", "CITY": "City government",
    "CNTY": "County government", "REG": "Regional agency / special district", "RWD": "Regional water district",
    "JNT": "Joint management", "UNKL": "Local government", "NGO": "Non-governmental organization",
    "PVT": "Private", "UNK": "Unknown manager",
}
# PAD-US "Mang_Type" fallback when the manager code is unfamiliar.
PADUS_MANAGER_TYPES = {
    "FED": "Federal agency", "STAT": "State agency", "LOC": "Local government", "DIST": "Special district",
    "TRIB": "Tribal government", "JNT": "Joint management", "NGO": "Non-governmental organization",
    "PVT": "Private", "TERR": "Territorial government", "UNK": "Unknown manager",
}
# PAD-US "Des_Tp" (designation type) codes — used when Loc_Ds is blank.
PADUS_DESIGNATIONS = {
    "ACEC": "Area of Critical Environmental Concern", "AGRE": "Agricultural easement",
    "CONE": "Conservation easement", "FOTH": "Federal land (other)", "HCA": "Historic or cultural area",
    "IRA": "Inventoried Roadless Area", "LCA": "Local conservation area", "LHCA": "Local historic/cultural area",
    "LOTH": "Local land (other)", "LP": "Local park", "LREC": "Local recreation area",
    "LRMA": "Local resource management area", "MIL": "Military land", "MPA": "Marine protected area",
    "NCA": "National Conservation Area", "NF": "National Forest", "NG": "National Grassland",
    "NLS": "National Lakeshore or Seashore", "NM": "National Monument", "NP": "National Park",
    "NRA": "National Recreation Area", "NT": "National Scenic or Historic Trail", "NWR": "National Wildlife Refuge",
    "OCS": "Outer Continental Shelf lease area", "PCON": "Private conservation land",
    "PUB": "Public land (multiple use)", "RNA": "Research Natural Area", "SCA": "State conservation area",
    "SHCA": "State historic/cultural area", "SOTH": "State land (other)", "SP": "State Park",
    "SREC": "State recreation area", "SRMA": "State resource management area", "SW": "State wilderness",
    "TRIBL": "Tribal land", "WA": "Wilderness Area", "WSA": "Wilderness Study Area", "WSR": "Wild & Scenic River",
}


async def _fetch_protected(
    client: httpx.AsyncClient, lat: float, lon: float, half_m: float
) -> list[ProtectedLand] | None:
    fields = "Unit_Nm,Des_Tp,Loc_Ds,Mang_Name,Mang_Type,GAP_Sts"
    # Suburban areas hold hundreds of PAD-US records within 5 km, returned in
    # arbitrary order, so a capped "nearby" query can miss the unit the site
    # sits in. Query units intersecting the footprint separately (few, never
    # capped away), plus a capped nearby query for context.
    dlat = half_m / 111_320
    dlon = half_m / _m_per_deg_lon(lat)
    overlap_params = _arcgis_point_params(lat, lon, 0, fields)
    overlap_params.pop("distance")
    overlap_params.pop("units")
    overlap_params.update(
        geometry=json.dumps({"xmin": lon - dlon, "ymin": lat - dlat, "xmax": lon + dlon, "ymax": lat + dlat,
                             "spatialReference": {"wkid": 4326}}),
        geometryType="esriGeometryEnvelope",
    )
    nearby_params = _arcgis_point_params(lat, lon, 5000, fields)
    nearby_params["resultRecordCount"] = 25

    async def nearby_query() -> list[dict[str, Any]]:
        # Deliberately capped: nearby units are context only; every unit that
        # touches the footprint comes from the complete (paged) overlap query.
        resp = await client.get(PADUS_URL, params=nearby_params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(data["error"])
        return data.get("features", [])

    try:
        overlapping, nearby = await asyncio.gather(
            _query_all(client, PADUS_URL, overlap_params), nearby_query()
        )
    except Exception:
        return None
    feats = overlapping + nearby

    # PAD-US stacks several records per place (fee, easement, designation);
    # merge them per unit name: most protective GAP status, any footprint
    # overlap, and the geometry/distance of the nearest *overlapping* record
    # (or the nearest record when none overlaps) so map and text agree.
    best: dict[str, ProtectedLand] = {}
    for i, f in enumerate(feats):
        a = f.get("attributes", {})
        name = (a.get("Unit_Nm") or "").strip()
        if not name:
            continue
        geometry = f.get("geometry", {})
        dist, nearest_pt = _nearest(lat, lon, geometry)
        des_tp = (a.get("Des_Tp") or "").strip()
        loc_ds = (a.get("Loc_Ds") or "").strip()
        desig = loc_ds if loc_ds and loc_ds.upper() != des_tp.upper() else PADUS_DESIGNATIONS.get(des_tp, des_tp or "Protected/managed area")
        mang_code = (a.get("Mang_Name") or "").strip()
        mang = PADUS_MANAGERS.get(mang_code) or PADUS_MANAGER_TYPES.get((a.get("Mang_Type") or "").strip(), mang_code or "Land manager")
        gap = str(a.get("GAP_Sts") or "").strip()
        land = ProtectedLand(
            id=f"PADUS-{i}",
            name=name,
            designation=desig,
            manager=mang,
            distance_m=round(dist, 1),
            bearing=_bearing_to(lat, lon, geometry, nearest_pt),
            geometry=_to_geojson(geometry),
            name_verified=True,
            designation_code=des_tp or None,
            gap_status=gap,
            overlaps_footprint=footprint_overlaps(lat, lon, half_m, geometry),
            source="USGS PAD-US (live query)",
        )
        prev = best.get(name)
        if prev is None:
            best[name] = land
            continue
        base = land if (land.gap_status or "9") < (prev.gap_status or "9") else prev
        shown = [r for r in (prev, land) if r.overlaps_footprint] or [prev, land]
        near = min(shown, key=lambda r: r.distance_m)
        best[name] = base.model_copy(update={
            "overlaps_footprint": prev.overlaps_footprint or land.overlaps_footprint,
            "distance_m": near.distance_m,
            "bearing": near.bearing,
            "geometry": near.geometry,
        })
    out = sorted(best.values(), key=lambda p: (not p.overlaps_footprint, p.distance_m))
    return out[:4]


# --- orchestration ----------------------------------------------------------

def half_width_m(acreage: float) -> float:
    return math.sqrt(acreage * 4046.86) / 2


async def fetch_all(
    lat: float, lon: float, acreage: float, state_code: str | None = None
) -> dict[str, Any]:
    """Query every live layer concurrently. Returns features + provenance.

    provenance values per layer:
      "live"        — service answered (may legitimately be an empty list)
      "unavailable" — service unreachable / errored / over deadline (no fabricated backfill)
    """
    half_m = half_width_m(acreage)
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "GridSentry/1.0"}) as client:
        wetlands, habitats, flood, protected = await asyncio.gather(
            _with_deadline(_fetch_wetlands(client, lat, lon, half_m, state_code)),
            _with_deadline(_fetch_species(client, lat, lon, half_m)),
            _with_deadline(_fetch_flood(client, lat, lon, half_m)),
            _with_deadline(_fetch_protected(client, lat, lon, half_m)),
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
    }
