"""Land Status Gate (pipeline Step 0.5).

Before any wetland/species analysis runs, this deterministic gate answers
the two threshold questions a permitting officer asks first:

1. **Ownership** — who owns/manages this land, and is development legally
   possible here at all? Point-in-polygon against real federal boundary
   data (USGS PAD-US via its public ArcGIS REST service). Catches sites
   inside National Parks, Wilderness, Wildlife Refuges, etc.

2. **Physical buildability** — is there actually undeveloped land here?
   A grid of point samples over the project footprint against the real
   USGS/MRLC National Land Cover Database (NLCD). If the footprint is
   dominated by high-intensity developed cover (a dense urban core) or
   open water, no greenfield project of this acreage can physically
   exist there and the pipeline short-circuits.

Neither check is an LLM guess — both are deterministic queries against
authoritative federal raster/vector data, with curated offline fallbacks
so flagship failure cases (Grand Canyon, Manhattan) still gate without
network access.
"""
from __future__ import annotations

import asyncio
import math
from collections import Counter
from typing import Any, Optional

import httpx

from models import LandStatus

PADUS_URL = (
    "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
    "Manager_Name/FeatureServer/0/query"
)
NLCD_WMS_URL = "https://www.mrlc.gov/geoserver/mrlc_display/wms"
NLCD_LAYER = "NLCD_2021_Land_Cover_L48"
TIMEOUT = 15.0

# NLCD 2021 legend (Anderson Level II codes actually present in the product)
NLCD_LABELS: dict[int, str] = {
    11: "Open Water",
    12: "Perennial Ice/Snow",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
}
DEVELOPED_CLASSES = {21, 22, 23, 24}
HIGH_INTENSITY_CLASSES = {23, 24}

# Footprint is rejected as a dense urban core when at least half of the
# sampled pixels are medium/high-intensity developed. (Calibrated: Midtown
# Manhattan = 100%, downtown Schenectady = 72%, suburban Bergen NJ = 0%,
# Iowa farmland fringe = 28%.)
URBAN_HIGH_FRACTION = 0.5
WATER_FRACTION = 0.6

# PAD-US designation-type codes (Des_Tp) that bar or severely restrict
# non-conforming commercial energy development. Maps code -> (label, agency law).
BARRED_DESIGNATIONS: dict[str, str] = {
    "NP": "National Park",
    "WA": "Wilderness Area",
    "WSA": "Wilderness Study / Proposed Wilderness Area",
    "NM": "National Monument",
    "NWR": "National Wildlife Refuge",
    "WSR": "Wild & Scenic River corridor",
    "RNA": "Research Natural Area",
    "NRA": "National Recreation Area",
    "NS": "National Seashore",
    "NCA": "National Conservation Area",
}
# Manager agencies whose flagship units are treated as non-developable when
# combined with a barred designation.
FEDERAL_AGENCIES = {"NPS", "FWS", "USFS", "BLM", "DOD"}

AGENCY_NAMES = {
    "NPS": "National Park Service",
    "FWS": "U.S. Fish and Wildlife Service",
    "USFS": "U.S. Forest Service",
    "BLM": "Bureau of Land Management",
    "DOD": "U.S. Department of Defense",
}

# Offline fallback for dense urban cores: (min_lat, max_lat, min_lon, max_lon, name)
_FALLBACK_URBAN_CORES = [
    (40.700, 40.880, -74.020, -73.905, "Manhattan, New York City"),
    (41.850, 41.910, -87.660, -87.600, "Chicago Loop"),
    (34.030, 34.070, -118.280, -118.230, "Downtown Los Angeles"),
    (37.770, 37.800, -122.420, -122.390, "Downtown San Francisco"),
    (42.340, 42.370, -71.080, -71.040, "Downtown Boston"),
    (38.890, 38.910, -77.050, -77.000, "Downtown Washington, DC"),
    (29.740, 29.770, -95.380, -95.350, "Downtown Houston"),
    (39.940, 39.965, -75.180, -75.140, "Center City Philadelphia"),
]

# Curated offline fallback: (min_lat, max_lat, min_lon, max_lon, unit, agency, desig)
_FALLBACK_UNITS = [
    (35.9, 36.6, -113.0, -111.6, "Grand Canyon National Park", "NPS", "National Park"),
    (44.1, 45.1, -111.2, -109.8, "Yellowstone National Park", "NPS", "National Park"),
    (37.5, 38.2, -119.9, -119.2, "Yosemite National Park", "NPS", "National Park"),
    (38.0, 38.6, -109.9, -109.4, "Arches / Canyonlands NP area", "NPS", "National Park"),
    (36.4, 36.9, -117.0, -116.6, "Death Valley National Park", "NPS", "National Park"),
    (48.2, 49.0, -114.5, -113.2, "Glacier National Park", "NPS", "National Park"),
    (35.5, 35.7, -83.8, -83.2, "Great Smoky Mountains NP", "NPS", "National Park"),
    (25.1, 25.9, -81.2, -80.4, "Everglades National Park", "NPS", "National Park"),
]


def _classify(attrs: dict[str, Any]) -> Optional[LandStatus]:
    """Turn a PAD-US feature into a non-developable LandStatus, or None if
    the feature doesn't bar development."""
    des_tp = (attrs.get("Des_Tp") or "").strip()
    mang = (attrs.get("Mang_Name") or "").strip()
    own_type = (attrs.get("Own_Type") or "").strip()
    unit = (attrs.get("Unit_Nm") or attrs.get("Loc_Nm") or "Federal protected area").strip()
    loc_ds = (attrs.get("Loc_Ds") or BARRED_DESIGNATIONS.get(des_tp, "protected area")).strip()

    if des_tp in BARRED_DESIGNATIONS and (mang in FEDERAL_AGENCIES or own_type == "FED"):
        agency = AGENCY_NAMES.get(mang, mang or "a federal agency")
        return LandStatus(
            developable=False,
            category="federal_protected",
            owner_type="Federal",
            manager=agency,
            manager_code=mang,
            unit_name=unit,
            designation=loc_ds,
            gap_status=str(attrs.get("GAP_Sts") or ""),
            verified=True,
            method="padus",
            sources=[
                {"title": f"USGS PAD-US — {unit} ({loc_ds}, {agency})",
                 "url": "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview"},
            ],
        )
    return None


async def _query_padus(lat: float, lon: float) -> Optional[list[dict[str, Any]]]:
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "Own_Type,Own_Name,Mang_Name,Mang_Type,Des_Tp,Loc_Ds,Unit_Nm,Loc_Nm,GAP_Sts",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(PADUS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                return None
            return data.get("features", [])
    except Exception:
        return None


# --- Check 2: physical buildability (NLCD land cover) -----------------------

async def _nlcd_point(client: httpx.AsyncClient, lat: float, lon: float) -> Optional[int]:
    """Sample the NLCD land-cover class at one point via WMS GetFeatureInfo."""
    d = 0.0002
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetFeatureInfo",
        "layers": NLCD_LAYER,
        "query_layers": NLCD_LAYER,
        "srs": "EPSG:4326",
        "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "width": 3,
        "height": 3,
        "x": 1,
        "y": 1,
        "info_format": "application/json",
    }
    try:
        resp = await client.get(NLCD_WMS_URL, params=params)
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return None
        return int(features[0]["properties"]["PALETTE_INDEX"])
    except Exception:
        return None


async def _sample_footprint_cover(
    lat: float, lon: float, acreage: float
) -> Optional[list[int]]:
    """5x5 grid of NLCD samples covering the proposed project footprint.

    Returns the list of land-cover classes, or None if the service is
    unreachable / returns too few samples to judge.
    """
    half_m = math.sqrt(acreage * 4046.86) / 2
    dlat = half_m / 111_320
    dlon = half_m / (111_320 * math.cos(math.radians(lat)))
    points = [
        (lat + dlat * i / 2, lon + dlon * j / 2)
        for i in range(-2, 3)
        for j in range(-2, 3)
    ]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            results = await asyncio.gather(
                *(_nlcd_point(client, plat, plon) for plat, plon in points)
            )
    except Exception:
        return None
    classes = [c for c in results if c is not None]
    return classes if len(classes) >= 13 else None  # need a majority of the grid


def _cover_stats(classes: list[int]) -> dict[str, Any]:
    n = len(classes)
    dominant_class, _ = Counter(classes).most_common(1)[0]
    return {
        "dominant_cover_class": dominant_class,
        "dominant_cover": NLCD_LABELS.get(dominant_class, f"NLCD class {dominant_class}"),
        "developed_fraction": round(sum(c in DEVELOPED_CLASSES for c in classes) / n, 2),
        "high_intensity_fraction": round(sum(c in HIGH_INTENSITY_CLASSES for c in classes) / n, 2),
        "water_fraction": round(sum(c == 11 for c in classes) / n, 2),
    }


NLCD_SOURCE = {
    "title": "USGS/MRLC National Land Cover Database (NLCD 2021) — footprint grid sample",
    "url": "https://www.mrlc.gov/data/nlcd-2021-land-cover-conus",
}


def _urban_fallback(lat: float, lon: float) -> Optional[LandStatus]:
    for min_lat, max_lat, min_lon, max_lon, name in _FALLBACK_URBAN_CORES:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return LandStatus(
                developable=False,
                category="urban_built",
                owner_type=None,
                manager=None,
                manager_code=None,
                unit_name=name,
                designation="Dense urban core (fully built environment)",
                land_cover_checked=False,
                verified=False,
                method="offline-bbox",
                sources=[{"title": f"Offline reference — {name} urban core", "url": ""}],
            )
    return None


def _fallback(lat: float, lon: float) -> Optional[LandStatus]:
    for min_lat, max_lat, min_lon, max_lon, unit, agency, desig in _FALLBACK_UNITS:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return LandStatus(
                developable=False,
                category="federal_protected",
                owner_type="Federal",
                manager=AGENCY_NAMES.get(agency, agency),
                manager_code=agency,
                unit_name=unit,
                designation=desig,
                gap_status="",
                verified=False,
                method="offline-bbox",
                sources=[{"title": f"Offline reference — {unit}", "url": ""}],
            )
    return None


async def check(lat: float, lon: float, acreage: float = 300.0) -> LandStatus:
    """Resolve land status for a coordinate. Developable unless proven otherwise.

    Runs both threshold checks concurrently: PAD-US ownership (legal
    eligibility) and NLCD land cover over the project footprint (physical
    buildability). Ownership takes precedence when both trip.
    """
    features, cover = await asyncio.gather(
        _query_padus(lat, lon),
        _sample_footprint_cover(lat, lon, acreage),
    )

    # --- Check 1: ownership (PAD-US) ---
    ownership_verified = features is not None
    if features is not None:
        # Real data reached. Prefer the most restrictive matching feature.
        best: Optional[LandStatus] = None
        priority = {"NP": 0, "WA": 1, "WSA": 1, "NM": 2, "NWR": 2}
        for f in features:
            status = _classify(f.get("attributes", {}))
            if status is None:
                continue
            if best is None or priority.get(f["attributes"].get("Des_Tp", ""), 9) < priority.get(
                _rev_desig(best.designation), 9
            ):
                best = status
        if best is not None:
            if cover is not None:
                _apply_cover(best, cover)
            return best
    else:
        fb = _fallback(lat, lon)
        if fb is not None:
            return fb

    # --- Check 2: physical buildability (NLCD) ---
    if cover is not None:
        stats = _cover_stats(cover)
        if stats["high_intensity_fraction"] >= URBAN_HIGH_FRACTION:
            return LandStatus(
                developable=False,
                category="urban_built",
                owner_type=None,
                manager=None,
                manager_code=None,
                unit_name=None,
                designation="Dense urban core — high-intensity developed land cover",
                land_cover_checked=True,
                verified=True,
                method="padus+nlcd" if ownership_verified else "nlcd",
                sources=[NLCD_SOURCE],
                **stats,
            )
        if stats["water_fraction"] >= WATER_FRACTION:
            return LandStatus(
                developable=False,
                category="open_water",
                owner_type=None,
                manager=None,
                manager_code=None,
                unit_name=None,
                designation="Open water — no land at these coordinates",
                land_cover_checked=True,
                verified=True,
                method="padus+nlcd" if ownership_verified else "nlcd",
                sources=[NLCD_SOURCE],
                **stats,
            )
    else:
        ufb = _urban_fallback(lat, lon)
        if ufb is not None:
            return ufb

    # --- Both checks clear (or were unreachable with no fallback match) ---
    status = LandStatus(
        developable=True,
        category="developable",
        verified=ownership_verified,
        method=(
            "padus+nlcd" if ownership_verified and cover is not None
            else "padus" if ownership_verified
            else "nlcd" if cover is not None
            else "unverified"
        ),
        sources=(
            [{"title": "USGS PAD-US — no federal protected area at this point",
              "url": "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview"}]
            if ownership_verified else []
        ),
    )
    if cover is not None:
        _apply_cover(status, cover)
        status.sources.append(NLCD_SOURCE)
    return status


def _apply_cover(status: LandStatus, classes: list[int]) -> None:
    stats = _cover_stats(classes)
    status.land_cover_checked = True
    status.dominant_cover_class = stats["dominant_cover_class"]
    status.dominant_cover = stats["dominant_cover"]
    status.developed_fraction = stats["developed_fraction"]
    status.high_intensity_fraction = stats["high_intensity_fraction"]
    status.water_fraction = stats["water_fraction"]


def _rev_desig(loc_ds: Optional[str]) -> str:
    if not loc_ds:
        return ""
    for code, label in BARRED_DESIGNATIONS.items():
        if label.lower() in loc_ds.lower():
            return code
    return ""
