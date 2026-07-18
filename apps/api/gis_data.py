"""GIS ingestion — real live geospatial queries with a flagged fallback.

The primary path (`ingest_live`) builds the site geometry, then queries real
public datasets for the *actual* coordinates via `geodata.py`:
USFWS NWI (wetlands), USFWS IPaC (ESA species + critical habitat),
FEMA NFHL (flood), and USGS PAD-US (nearby protected areas). Distances and
bearings are computed from returned geometry, so results genuinely vary by
location — Ripley farmland and Midtown Manhattan no longer share a template.

If every live service is unreachable, `ingest` produces a clearly-flagged
*simulated* payload (provenance = "simulated") so the app still renders; the
Red-Team Critic surfaces that provenance prominently rather than passing off
synthetic features as real findings.

Grounding rules (see grounding.py): jurisdiction comes from real reverse
geocoding; NWI polygons are unnamed in the source data, so we never invent
proper nouns for them (name_verified stays false).
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Any, Optional

import geodata
from models import (
    DataProvenance,
    FloodZone,
    GISPayload,
    Habitat,
    Jurisdiction,
    ProtectedLand,
    Site,
    SiteInput,
    Wetland,
)

EARTH_R = 6_371_000.0

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

NWI_CLASSES = [
    ("PEM1E", "Freshwater Emergent Wetland (seasonally flooded/saturated)"),
    ("PFO1A", "Freshwater Forested Wetland (temporarily flooded)"),
    ("PSS1C", "Freshwater Shrub Wetland (seasonally flooded)"),
    ("PUBH", "Freshwater Pond (permanently flooded)"),
]

# Region-specific listed-species pools so the flagged species is plausible
# for the site. Keyed by USPS state code; falls back to SPECIES_GENERIC.
SPECIES_NORTHEAST = [
    ("Myotis septentrionalis", "Northern Long-eared Bat", "Endangered"),
    ("Glyptemys muhlenbergii", "Bog Turtle", "Threatened"),
    ("Plebejus melissa samuelis", "Karner Blue Butterfly", "Endangered"),
    ("Myotis sodalis", "Indiana Bat", "Endangered"),
]
SPECIES_SOUTHWEST = [
    ("Gymnogyps californianus", "California Condor", "Endangered"),
    ("Strix occidentalis lucida", "Mexican Spotted Owl", "Threatened"),
    ("Empidonax traillii extimus", "Southwestern Willow Flycatcher", "Endangered"),
    ("Gopherus agassizii", "Mojave Desert Tortoise", "Threatened"),
]
SPECIES_CALIFORNIA = [
    ("Gymnogyps californianus", "California Condor", "Endangered"),
    ("Gopherus agassizii", "Mojave Desert Tortoise", "Threatened"),
    ("Vulpes macrotis mutica", "San Joaquin Kit Fox", "Endangered"),
    ("Branchinecta lynchi", "Vernal Pool Fairy Shrimp", "Threatened"),
]
SPECIES_SOUTHEAST = [
    ("Picoides borealis", "Red-cockaded Woodpecker", "Endangered"),
    ("Gopherus polyphemus", "Gopher Tortoise", "Threatened"),
    ("Trichechus manatus", "West Indian Manatee", "Threatened"),
    ("Puma concolor coryi", "Florida Panther", "Endangered"),
]
SPECIES_PLAINS = [
    ("Grus americana", "Whooping Crane", "Endangered"),
    ("Tympanuchus cupido attwateri", "Attwater's Prairie-Chicken", "Endangered"),
    ("Mustela nigripes", "Black-footed Ferret", "Endangered"),
    ("Charadrius melodus", "Piping Plover", "Threatened"),
]
SPECIES_GENERIC = [
    ("Charadrius melodus", "Piping Plover", "Threatened"),
    ("Bombus affinis", "Rusty Patched Bumble Bee", "Endangered"),
    ("Emydoidea blandingii", "Blanding's Turtle", "Threatened"),
    ("Haliaeetus leucocephalus", "Bald Eagle", "Protected (BGEPA)"),
]

SPECIES_BY_STATE: dict[str, list] = {
    # Northeast
    **{s: SPECIES_NORTHEAST for s in ("NY", "NJ", "CT", "MA", "VT", "NH", "ME", "RI", "PA")},
    # Southwest / Colorado Plateau
    **{s: SPECIES_SOUTHWEST for s in ("AZ", "NM", "UT", "NV", "CO")},
    "CA": SPECIES_CALIFORNIA,
    # Southeast
    **{s: SPECIES_SOUTHEAST for s in ("FL", "GA", "AL", "SC", "NC", "MS", "LA")},
    # Great Plains
    **{s: SPECIES_PLAINS for s in ("TX", "OK", "KS", "NE", "SD", "ND")},
}

# State wetland regulatory classes for the headline protected wetland.
# Keyed by USPS state code; each entry is (class label, managing agency).
STATE_WETLAND_PROGRAMS: dict[str, tuple[str, str]] = {
    "NY": ("NYS Class I (6 NYCRR 664)", "NYS Department of Environmental Conservation"),
    "NJ": ("Exceptional Resource Value (N.J.A.C. 7:7A-3.2)", "NJ Department of Environmental Protection"),
    "CT": ("Inland wetland (CGS § 22a-36 et seq.)", "CT DEEP / municipal inland wetlands agency"),
    "MA": ("Bordering Vegetated Wetland (310 CMR 10.55)", "MassDEP / local conservation commission"),
    "PA": ("Exceptional Value wetland (25 Pa. Code Ch. 105)", "PA Department of Environmental Protection"),
}
DEFAULT_WETLAND_PROGRAM = (
    "State-regulated wetland (program unverified — confirm with state agency)",
    "State environmental agency (unverified)",
)


def _seed_for(lat: float, lon: float) -> int:
    key = f"{round(lat, 3)}:{round(lon, 3)}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)


def site_acreage(lat: float, lon: float) -> float:
    """The acreage `ingest` will assign for these coordinates.

    Acreage is the first draw from the coordinate-seeded RNG, so the Land
    Status Gate can know the footprint size before ingestion runs and the
    numbers stay consistent across the pipeline.
    """
    return round(random.Random(_seed_for(lat, lon)).uniform(120, 480), 1)


def _dest(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """Destination point given start, bearing and distance (haversine)."""
    br = math.radians(bearing_deg)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    d = dist_m / EARTH_R
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def _compass(bearing_deg: float) -> str:
    return COMPASS[int(((bearing_deg % 360) + 22.5) // 45) % 8]


def _blob(rng: random.Random, lat: float, lon: float, radius_m: float, points: int = 10) -> dict[str, Any]:
    """Irregular polygon (GeoJSON, [lon, lat]) around a center point."""
    coords = []
    for i in range(points):
        angle = 360.0 * i / points
        r = radius_m * rng.uniform(0.65, 1.35)
        plat, plon = _dest(lat, lon, angle, r)
        coords.append([round(plon, 6), round(plat, 6)])
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _rect(lat: float, lon: float, half_m: float) -> dict[str, Any]:
    corners = [_dest(lat, lon, b, half_m * math.sqrt(2)) for b in (45, 135, 225, 315)]
    coords = [[round(c[1], 6), round(c[0], 6)] for c in corners]
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _build_site(site_input: SiteInput, jurisdiction: Jurisdiction) -> Site:
    lat, lon = site_input.lat, site_input.lon
    locality = jurisdiction.locality or jurisdiction.county or "Proposed Site"
    project_names = {
        "solar": f"{locality} Solar Energy Center",
        "wind": f"{locality} Wind Project",
        "transmission": f"{locality} Transmission Corridor",
    }
    acreage = site_acreage(lat, lon)
    half = math.sqrt(acreage * 4046.86) / 2
    return Site(
        lat=lat,
        lon=lon,
        project_type=site_input.project_type,
        name=site_input.name or project_names[site_input.project_type],
        acreage=acreage,
        footprint=_rect(lat, lon, half),
        jurisdiction=jurisdiction,
    )


def _base_sources(jurisdiction: Jurisdiction) -> list[str]:
    sources = [f"Jurisdiction: {s['title']}" for s in jurisdiction.sources]
    return sources


async def ingest_live(site_input: SiteInput, jurisdiction: Jurisdiction) -> GISPayload:
    """Primary ingestion: build the site, then query real datasets for it."""
    site = _build_site(site_input, jurisdiction)
    state_code = jurisdiction.state_code
    data = await geodata.fetch_all(site.lat, site.lon, site.acreage, state_code)

    prov = DataProvenance(**data["provenance"])
    wetlands: list[Wetland] = data["wetlands"]
    habitats: list[Habitat] = data["habitats"]
    protected: list[ProtectedLand] = data["protected_lands"]
    flood_zones: list[FloodZone] = data["flood_zones"]

    # If every live layer failed, fall back to the flagged simulated payload
    # rather than presenting an empty (and misleadingly clean) assessment.
    if not prov.any_live:
        return _simulated_payload(site_input, jurisdiction, site)

    sources: list[str] = []
    layer_sources = {
        "wetlands": "USFWS National Wetlands Inventory (NWI) — live point query",
        "species": "USFWS IPaC official species list — live query",
        "flood": "FEMA National Flood Hazard Layer (NFHL) — live query",
        "protected": "USGS Protected Areas Database (PAD-US) — live query",
    }
    for layer, label in layer_sources.items():
        state = getattr(prov, layer)
        sources.append(label if state == "live" else f"{label} [UNAVAILABLE at run time]")
    sources += _base_sources(jurisdiction)

    return GISPayload(
        site=site,
        wetlands=wetlands,
        habitats=habitats,
        protected_lands=protected,
        flood_zones=flood_zones,
        sources=sources,
        provenance=prov,
    )


def _simulated_payload(
    site_input: SiteInput, jurisdiction: Jurisdiction, site: Optional[Site] = None
) -> GISPayload:
    """Deterministic synthetic payload — used ONLY as a last-resort fallback
    when live services are unreachable. Flagged provenance='simulated' so the
    critic never presents these as real findings."""
    lat, lon = site_input.lat, site_input.lon
    rng = random.Random(_seed_for(lat, lon))

    county = jurisdiction.county or "the surrounding county"
    locality = jurisdiction.locality or jurisdiction.county or "Proposed Site"
    state_code = jurisdiction.state_code
    wetland_class, wetland_agency = STATE_WETLAND_PROGRAMS.get(
        state_code or "", DEFAULT_WETLAND_PROGRAM
    )
    site = site or _build_site(site_input, jurisdiction)

    # --- Wetlands: headline feature ~183 m (200 yd) east, always state-relevant ---
    # Real NWI polygons are unnamed, so use honest descriptive names.
    wetlands: list[Wetland] = []
    head_bearing = rng.uniform(80, 100)
    head_dist = rng.uniform(175, 195)
    wlat, wlon = _dest(lat, lon, head_bearing, head_dist)
    cls, cls_name = NWI_CLASSES[0]
    wetlands.append(
        Wetland(
            id=f"NWI-{rng.randint(100000, 999999)}",
            name=f"Unnamed emergent marsh complex ({county})",
            classification=cls,
            wetland_type=cls_name,
            distance_m=round(head_dist, 1),
            bearing=_compass(head_bearing),
            area_acres=round(rng.uniform(14, 38), 1),
            state_protected=True,
            state_class=wetland_class,
            geometry=_blob(rng, wlat, wlon, rng.uniform(140, 220)),
            name_verified=False,
        )
    )
    for _ in range(rng.randint(1, 2)):
        b, d = rng.uniform(0, 360), rng.uniform(450, 1100)
        plat, plon = _dest(lat, lon, b, d)
        cls, cls_name = rng.choice(NWI_CLASSES[1:])
        wetlands.append(
            Wetland(
                id=f"NWI-{rng.randint(100000, 999999)}",
                name=f"Unnamed {cls_name.split(' (')[0].lower()}",
                classification=cls,
                wetland_type=cls_name,
                distance_m=round(d, 1),
                bearing=_compass(b),
                area_acres=round(rng.uniform(2, 16), 1),
                state_protected=False,
                geometry=_blob(rng, plat, plon, rng.uniform(60, 140)),
                name_verified=False,
            )
        )

    # --- Critical habitat: one listed species unit within ~1.5 km ---
    pool = SPECIES_BY_STATE.get(state_code or "", SPECIES_GENERIC)
    sci, common, status = pool[rng.randrange(len(pool))]
    hb, hd = rng.uniform(0, 360), rng.uniform(700, 1500)
    hlat, hlon = _dest(lat, lon, hb, hd)
    habitats = [
        Habitat(
            id=f"ECOS-{rng.randint(10000, 99999)}",
            species=sci,
            common_name=common,
            status=status,
            unit_name=f"Unit {rng.choice('ABCDE')}{rng.randint(1, 9)} — {county} watershed",
            distance_m=round(hd, 1),
            bearing=_compass(hb),
            geometry=_blob(rng, hlat, hlon, rng.uniform(320, 520), points=12),
        )
    ]

    # --- Protected lands: 2–3.5 km out ---
    pb, pd = rng.uniform(0, 360), rng.uniform(2000, 3500)
    plat, plon = _dest(lat, lon, pb, pd)
    protected = [
        ProtectedLand(
            id=f"PADUS-{rng.randint(100000, 999999)}",
            name=f"Conservation land near {locality} (PAD-US record)",
            designation="State conservation / open space",
            manager=wetland_agency,
            distance_m=round(pd, 1),
            bearing=_compass(pb),
            geometry=_blob(rng, plat, plon, rng.uniform(600, 900), points=12),
            name_verified=False,
        )
    ]

    # --- Flood zone: present ~60% of the time ---
    flood_zones: list[FloodZone] = []
    if rng.random() < 0.6:
        fb, fd = rng.uniform(0, 360), rng.uniform(350, 800)
        flat, flon = _dest(lat, lon, fb, fd)
        flood_zones.append(
            FloodZone(
                id=f"NFHL-{rng.randint(10000, 99999)}",
                zone="AE",
                description="1% annual chance flood hazard (base flood elevation determined)",
                distance_m=round(fd, 1),
                geometry=_blob(rng, flat, flon, rng.uniform(200, 350)),
            )
        )

    sources = [
        "SIMULATED DATA — live geospatial services were unreachable at run time",
        "Schema basis: USFWS NWI, USFWS IPaC, USGS PAD-US, FEMA NFHL",
    ]
    sources += [f"Jurisdiction: {s['title']}" for s in jurisdiction.sources]

    return GISPayload(
        site=site,
        wetlands=wetlands,
        habitats=habitats,
        protected_lands=protected,
        flood_zones=flood_zones,
        sources=sources,
        provenance=DataProvenance(
            wetlands="simulated", species="simulated", flood="simulated", protected="simulated"
        ),
    )


def ingest(site_input: SiteInput, jurisdiction: Jurisdiction) -> GISPayload:
    """Synchronous simulated ingestion (used by the infeasible short-circuit
    path, which only needs the site geometry — features are dropped there)."""
    return _simulated_payload(site_input, jurisdiction)
