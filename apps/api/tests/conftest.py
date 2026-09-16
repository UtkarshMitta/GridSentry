"""Shared test setup: import path, hermetic env, and feature builders."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

FIXTURES = Path(__file__).parent / "fixtures"

import grounding  # noqa: E402
from models import (  # noqa: E402
    FloodZone,
    Habitat,
    Jurisdiction,
    LandStatus,
    ProtectedLand,
    Wetland,
)


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    """No real LLM / Tavily calls, no cached jurisdictions, no pacing sleeps."""
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    grounding._jurisdiction_cache.clear()

    from agents import orchestrator

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(orchestrator, "_sleep", no_sleep)
    yield


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


# --- feature builders -------------------------------------------------------

LAT, LON = 42.9, -74.3


def square_geojson(lat: float, lon: float, cx_m: float, cy_m: float, half_m: float) -> dict:
    """GeoJSON square centred (cx_m east, cy_m north) of (lat, lon)."""
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 111_320
    pts = [(-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)]
    ring = [[lon + (cx_m + sx * half_m) / kx, lat + (cy_m + sy * half_m) / ky] for sx, sy in pts]
    return {"type": "Polygon", "coordinates": [ring]}


def esri_square(lat: float, lon: float, cx_m: float, cy_m: float, half_m: float) -> dict:
    return {"rings": square_geojson(lat, lon, cx_m, cy_m, half_m)["coordinates"]}


def jur(state="New York", code="NY", verified=True, in_coverage=True, method="nominatim+census") -> Jurisdiction:
    return Jurisdiction(
        state=state, state_code=code, county="Montgomery County", locality="Glen",
        country_code="us" if in_coverage else None, verified=verified, method=method,
        in_coverage=in_coverage, sources=[],
    )


def wetland(cls="PEM1E", dist=0.0, acres=15.0, crosses=True, state_protected=False, bearing="E", i=0) -> Wetland:
    return Wetland(
        id=f"NWI-{cls}-{i}", name=f"Unnamed {cls}", classification=cls, wetland_type="Freshwater Emergent Wetland",
        distance_m=dist, bearing=bearing, area_acres=acres, state_protected=state_protected,
        state_class="Likely NYS-regulated" if state_protected else None,
        geometry=square_geojson(LAT, LON, 0, 0, 50), crosses_footprint=crosses,
        source="USFWS National Wetlands Inventory (live query)",
    )


def habitat(common="Whooping crane", basis="ipac_species_list", listed=True, status="Endangered", i=0) -> Habitat:
    return Habitat(
        id=f"IPAC-{i}", species="Grus americana", common_name=common, status=status,
        unit_name="x", basis=basis, currently_listed=listed, source="USFWS IPaC (live query)",
    )


def protected(name="Harriman State Park", gap="2", overlaps=True, dist=0.0, code="SP",
              designation="State Park") -> ProtectedLand:
    return ProtectedLand(
        id="PADUS-0", name=name, designation=designation, manager="State park & recreation agency",
        distance_m=dist, bearing="N", geometry=square_geojson(LAT, LON, 0, 0, 900),
        name_verified=True, designation_code=code, gap_status=gap, overlaps_footprint=overlaps,
        source="USGS PAD-US (live query)",
    )


def flood(zone="AE", sfha=True, overlaps=True, dist=0.0) -> FloodZone:
    return FloodZone(
        id=f"NFHL-{zone}-0", zone=zone, description="x", distance_m=dist,
        geometry=square_geojson(LAT, LON, 0, 0, 200), sfha=sfha, overlaps_footprint=overlaps,
        source="FEMA National Flood Hazard Layer (live query)",
    )


def developable_status() -> LandStatus:
    return LandStatus(developable=True, category="developable", verified=True, method="padus+nlcd")
