"""Real-world grounding for site coordinates.

Two failure modes this module exists to prevent:
1. Jurisdiction mismatch — citing New York regulations for a New Jersey
   site. Jurisdiction is resolved by reverse geocoding (Nominatim/OSM) and
   cross-checked against the U.S. Census Bureau's TIGER boundaries (the
   authoritative state/county geography — free, no key). Only a Census-backed
   state counts as verified. An optional Tavily web search adds sources on
   the state's wetland program.
2. Fabricated named entities — invented "official-sounding" feature names.
   NWI polygons are unnamed in the source data, so wetlands get descriptive
   labels flagged name_verified=False; PAD-US unit names are real.

Every network call degrades gracefully: no key / no network → explicit
"unverified" status, never a silent guess.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

from models import Jurisdiction

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
TAVILY_URL = "https://api.tavily.com/search"
# Nominatim country codes covered by the U.S. federal datasets (states + territories).
US_COUNTRY_CODES = ("us", "pr", "gu", "vi", "as", "mp", "um")
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


# Lookup outcomes: ("ok", data) | ("no_result", None) — the service answered
# that nothing is there (ocean / foreign) | ("failed", None) — no answer.
Lookup = tuple[str, Optional[dict[str, Any]]]


async def _reverse_geocode(lat: float, lon: float) -> Lookup:
    """Nominatim reverse geocode → address dict."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12},
                headers={"User-Agent": "GridSentry-demo/0.1 (environmental permitting agent)"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return "failed", None
    address = data.get("address")
    return ("ok", address) if address else ("no_result", None)


async def _census_lookup(lat: float, lon: float) -> Lookup:
    """U.S. Census geocoder → {"state", "state_code", "county"} from TIGER boundaries."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                CENSUS_URL,
                params={
                    "x": lon, "y": lat, "benchmark": "Public_AR_Current",
                    "vintage": "Current_Current", "layers": "States,Counties", "format": "json",
                },
            )
            resp.raise_for_status()
            geos = resp.json()["result"]["geographies"]
    except Exception:
        return "failed", None
    states = geos.get("States") or []
    if not states:
        return "no_result", None
    counties = geos.get("Counties") or []
    return "ok", {
        "state": states[0].get("NAME"),
        "state_code": states[0].get("STUSAB"),
        "county": (counties[0].get("NAME") or None) if counties else None,
    }


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
    # Full precision: a coarse key would let two points either side of a state
    # line share one (verified) jurisdiction.
    cache_key = f"{lat:.6f}:{lon:.6f}"
    if cache_key in _jurisdiction_cache:
        return _jurisdiction_cache[cache_key]

    (nom_status, address), (cen_status, census) = await asyncio.gather(
        _reverse_geocode(lat, lon), _census_lookup(lat, lon)
    )
    nom_us = nom_status == "ok" and address.get("country_code") == "us" and address.get("state")
    # Nominatim positively placed the point in another country (U.S. territories,
    # which the federal datasets do cover, are not "foreign").
    nom_foreign = nom_status == "ok" and address.get("country_code") not in (None, *US_COUNTRY_CODES)
    sources: list[dict[str, str]] = []

    if cen_status == "ok" or nom_us:
        locality = county = None
        nom_state = nom_code = None
        if nom_us:
            nom_state = address["state"]
            nom_code = STATE_CODES.get(nom_state.lower()) or address.get("ISO3166-2-lvl4", "US-??").split("-")[-1]
            county = address.get("county")
            locality = (
                address.get("town") or address.get("city") or address.get("village")
                or address.get("hamlet") or address.get("municipality")
            )
            sources.append({
                "title": "OpenStreetMap Nominatim reverse geocoding",
                "url": f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}",
            })
        if cen_status == "ok":
            sources.append({
                "title": "U.S. Census Bureau TIGER boundaries (Census Geocoder)",
                "url": f"https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x={lon}&y={lat}&benchmark=Public_AR_Current&vintage=Current_Current&layers=States,Counties&format=json",
            })
            state, state_code = census["state"], census["state_code"]
            county = census["county"] or county
            if nom_status == "ok" and nom_code != state_code:
                # Border sites: two sources disagree (including Nominatim
                # placing the point outside the U.S.) → never guess.
                verified, method = False, "conflict"
            else:
                verified, method = True, ("nominatim+census" if nom_us else "census")
        else:
            state, state_code = nom_state, nom_code
            verified, method = False, "nominatim"

        if verified:
            # Optional: corroborate the state's wetland program on the web.
            results = await _tavily_search(
                f"{state} state freshwater wetlands regulation permit program statute site:gov OR official"
            )
            state_l = (state or "").lower()
            hits = [
                r for r in results or []
                if state_l in (r.get("title", "") + r.get("content", "") + r.get("url", "")).lower()
            ]
            if hits:
                method += "+tavily"
                sources += [{"title": r.get("title", "Web source"), "url": r.get("url", "")} for r in hits[:2]]

        jurisdiction = Jurisdiction(
            state=state, state_code=state_code, county=county, locality=locality,
            country_code="us", verified=verified, method=method, in_coverage=True, sources=sources,
        )
    elif nom_foreign or (cen_status == "no_result" and nom_status == "no_result"):
        # Positively outside U.S. coverage: Nominatim resolved a foreign
        # country (even if the Census lookup failed), or both services answered
        # with nothing (open ocean beyond state waters).
        foreign = address.get("country_code") if nom_status == "ok" else None
        jurisdiction = Jurisdiction(
            state=None, state_code=None, county=None, locality=None,
            country_code=foreign, verified=False, method="unresolved", in_coverage=False, sources=[],
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

    # Only cache when both services answered — a transient outage of either
    # must not pin this site to an unverified/unresolved jurisdiction for the
    # life of the process.
    if nom_status != "failed" and cen_status != "failed":
        _jurisdiction_cache[cache_key] = jurisdiction
    return jurisdiction

