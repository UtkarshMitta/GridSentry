"""Real-world grounding for site coordinates.

Two failure modes this module exists to prevent:
1. Jurisdiction mismatch — citing New York regulations for a New Jersey
   site. Jurisdiction is resolved by reverse geocoding (Nominatim/OSM),
   cross-checked with a Tavily web search of the state's wetland program.
2. Fabricated named entities — invented "official-sounding" feature names.
   Names are verified against the web via Tavily; unverified names are
   flagged so downstream agents and the report treat them as placeholders.

Every network call degrades gracefully: no key / no network → explicit
"unverified" status, never a silent guess.
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

import httpx

from models import Jurisdiction

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT = 12.0

_jurisdiction_cache: dict[str, Jurisdiction] = {}

STATE_CODES = {
    "new york": "NY", "new jersey": "NJ", "connecticut": "CT", "pennsylvania": "PA",
    "massachusetts": "MA", "vermont": "VT", "new hampshire": "NH", "maine": "ME",
    "rhode island": "RI", "california": "CA", "texas": "TX", "florida": "FL",
    "ohio": "OH", "michigan": "MI", "illinois": "IL", "virginia": "VA",
    "maryland": "MD", "delaware": "DE", "north carolina": "NC", "georgia": "GA",
    "arizona": "AZ", "nevada": "NV", "colorado": "CO", "utah": "UT",
    "washington": "WA", "oregon": "OR", "minnesota": "MN", "wisconsin": "WI",
    "iowa": "IA", "kansas": "KS", "missouri": "MO", "indiana": "IN",
    "tennessee": "TN", "kentucky": "KY", "alabama": "AL", "louisiana": "LA",
    "oklahoma": "OK", "arkansas": "AR", "mississippi": "MS", "south carolina": "SC",
    "west virginia": "WV", "nebraska": "NE", "south dakota": "SD", "north dakota": "ND",
    "montana": "MT", "wyoming": "WY", "idaho": "ID", "new mexico": "NM",
    "alaska": "AK", "hawaii": "HI",
}


def tavily_available() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY"))


async def _tavily_search(query: str, max_results: int = 3) -> Optional[list[dict[str, Any]]]:
    """Tavily advanced search. Returns result list or None on any failure."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                },
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
    except Exception:
        return None


async def _reverse_geocode(lat: float, lon: float) -> Optional[dict[str, Any]]:
    """Nominatim reverse geocode → address dict, or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12},
                headers={"User-Agent": "GridSentry-demo/0.1 (environmental permitting agent)"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("address")
    except Exception:
        return None


def _bbox_fallback(lat: float, lon: float) -> Optional[tuple[str, str]]:
    """Very coarse offline fallback. Only used when all lookups fail, and
    the result is always marked unverified. Deliberately conservative: only
    regions that don't overlap a neighboring state's core territory."""
    if 42.0 <= lat <= 45.0 and -79.8 <= lon <= -73.3:
        return ("New York", "NY")
    if 39.0 <= lat <= 41.35 and -75.6 <= lon <= -73.9:
        return ("New Jersey", "NJ")
    return None


async def resolve_jurisdiction(lat: float, lon: float) -> Jurisdiction:
    """Determine which state/county the site actually falls in."""
    cache_key = f"{round(lat, 3)}:{round(lon, 3)}"
    if cache_key in _jurisdiction_cache:
        return _jurisdiction_cache[cache_key]

    address = await _reverse_geocode(lat, lon)
    sources: list[dict[str, str]] = []

    if address and address.get("country_code") == "us" and address.get("state"):
        state = address["state"]
        state_code = STATE_CODES.get(state.lower()) or address.get("ISO3166-2-lvl4", "US-??").split("-")[-1]
        county = address.get("county")
        locality = (
            address.get("town") or address.get("city") or address.get("village")
            or address.get("hamlet") or address.get("municipality")
        )
        sources.append({
            "title": "OpenStreetMap Nominatim reverse geocoding",
            "url": f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}",
        })

        # Cross-check the state's wetland regulatory program via Tavily.
        verified = False
        method = "nominatim"
        results = await _tavily_search(
            f"{state} state freshwater wetlands regulation permit program statute site:gov OR official"
        )
        if results:
            state_l = state.lower()
            if any(
                state_l in (r.get("title", "") + r.get("content", "") + r.get("url", "")).lower()
                for r in results
            ):
                verified = True
                method = "nominatim+tavily"
                sources += [
                    {"title": r.get("title", "Web source"), "url": r.get("url", "")}
                    for r in results[:2]
                ]

        jurisdiction = Jurisdiction(
            state=state, state_code=state_code, county=county, locality=locality,
            country_code="us", verified=verified, method=method, sources=sources,
        )
    else:
        fallback = _bbox_fallback(lat, lon)
        if fallback:
            state, state_code = fallback
            jurisdiction = Jurisdiction(
                state=state, state_code=state_code, county=None, locality=None,
                country_code="us", verified=False, method="bbox-fallback", sources=[],
            )
        else:
            jurisdiction = Jurisdiction(
                state=None, state_code=None, county=None, locality=None,
                country_code=None, verified=False, method="unresolved", sources=[],
            )

    _jurisdiction_cache[cache_key] = jurisdiction
    return jurisdiction


async def verify_feature_name(name: str, state: Optional[str]) -> bool:
    """Check whether a named feature actually exists in the real world.
    Returns False (unverified) unless web results plausibly match the name."""
    if not name or not tavily_available():
        return False
    results = await _tavily_search(f'"{name}" {state or ""} wetland OR conservation OR wildlife', 3)
    if not results:
        return False
    name_l = name.lower()
    return any(
        name_l in (r.get("title", "") + r.get("content", "")).lower() for r in results
    )
