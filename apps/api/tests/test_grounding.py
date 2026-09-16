"""Jurisdiction resolution: Nominatim + US Census cross-check + coverage."""
from __future__ import annotations

import httpx
import respx

import grounding


NY_ADDR = {"address": {"county": "Montgomery County", "state": "New York",
                       "ISO3166-2-lvl4": "US-NY", "country_code": "us", "village": "Glen"}}
UK_ADDR = {"address": {"city": "London", "state": "England", "country_code": "gb"}}


def census(state=None, code=None, county=None):
    geos = {}
    if state:
        geos = {"States": [{"NAME": state, "STUSAB": code}], "Counties": [{"NAME": county or ""}]}
    return {"result": {"geographies": geos}}


async def resolve(nominatim, census_resp, lat=42.9, lon=-74.3):
    with respx.mock:
        respx.get(grounding.NOMINATIM_URL).mock(return_value=nominatim)
        respx.get(grounding.CENSUS_URL).mock(return_value=census_resp)
        return await grounding.resolve_jurisdiction(lat, lon)


async def test_census_agreement_verifies_without_any_api_key():
    j = await resolve(httpx.Response(200, json=NY_ADDR),
                      httpx.Response(200, json=census("New York", "NY", "Montgomery County")))
    assert j.verified and j.state_code == "NY" and j.in_coverage is True
    assert "census" in j.method


async def test_non_us_site_is_out_of_coverage():
    j = await resolve(httpx.Response(200, json=UK_ADDR), httpx.Response(200, json=census()), 51.5, -0.12)
    assert j.in_coverage is False and not j.verified and j.state is None


async def test_open_ocean_is_out_of_coverage():
    j = await resolve(httpx.Response(200, json={"error": "Unable to geocode"}),
                      httpx.Response(200, json=census()), 39.5, -72.0)
    assert j.in_coverage is False


async def test_state_disagreement_is_unverified():
    j = await resolve(httpx.Response(200, json=NY_ADDR),
                      httpx.Response(200, json=census("New Jersey", "NJ", "Bergen County")))
    assert not j.verified and j.method == "conflict"


async def test_census_alone_is_authoritative():
    j = await resolve(httpx.Response(500), httpx.Response(200, json=census("New York", "NY", "Montgomery County")))
    assert j.verified and j.state_code == "NY" and j.county == "Montgomery County"


async def test_nominatim_alone_is_unverified():
    j = await resolve(httpx.Response(200, json=NY_ADDR), httpx.Response(500))
    assert not j.verified and j.state_code == "NY" and j.in_coverage is True


async def test_everything_offline_uses_flagged_bbox_fallback():
    j = await resolve(httpx.Response(500), httpx.Response(500))
    assert j.method == "bbox-fallback" and not j.verified and j.in_coverage is None


async def test_failed_lookups_are_not_cached():
    """A transient outage must not pin a site to 'unresolved' for the process lifetime."""
    await resolve(httpx.Response(500), httpx.Response(500), 30.0, -90.0)
    j = await resolve(httpx.Response(200, json=NY_ADDR),
                      httpx.Response(200, json=census("New York", "NY")), 30.0, -90.0)
    assert j.verified


async def test_transient_census_failure_is_not_cached():
    """One Census timeout must not pin a site as unverified (state law withheld) until restart."""
    j = await resolve(httpx.Response(200, json=NY_ADDR), httpx.Response(503), 43.1, -75.2)
    assert not j.verified
    j = await resolve(httpx.Response(200, json=NY_ADDR),
                      httpx.Response(200, json=census("New York", "NY", "Oneida County")), 43.1, -75.2)
    assert j.verified and j.county == "Oneida County"


async def test_foreign_site_is_out_of_coverage_even_when_census_is_down():
    """Nominatim positively resolving another country is enough to gate the site."""
    j = await resolve(httpx.Response(200, json=UK_ADDR), httpx.Response(503), 51.5, -0.12)
    assert j.in_coverage is False and j.state is None


async def test_census_state_contradicted_by_foreign_nominatim_is_unverified():
    """Near a border, Census says NY but Nominatim says Canada → conflict, no state law."""
    ca = {"address": {"state": "Ontario", "country_code": "ca"}}
    j = await resolve(httpx.Response(200, json=ca), httpx.Response(200, json=census("New York", "NY")), 43.0, -79.05)
    assert not j.verified and j.method == "conflict" and j.in_coverage is True


async def test_nearby_points_across_a_state_line_are_resolved_separately():
    """A ~30 m move must not reuse the first point's jurisdiction from the cache."""
    a = await resolve(httpx.Response(200, json=NY_ADDR), httpx.Response(200, json=census("New York", "NY")),
                      41.0000, -74.0000)
    nj = {"address": {"state": "New Jersey", "country_code": "us", "county": "Bergen County"}}
    b = await resolve(httpx.Response(200, json=nj), httpx.Response(200, json=census("New Jersey", "NJ")),
                      41.0003, -74.0000)
    assert (a.state_code, b.state_code) == ("NY", "NJ")
