"""Live end-to-end checks against the real federal services (opt-in).

    GRIDSENTRY_LIVE=1 ./.venv/bin/python -m pytest tests/test_live_sites.py -v

Runs the full pipeline for sites that pin each README claim. Assertions are
deliberately coarse (verdict, gate category, jurisdiction, provenance) so
routine dataset updates don't break them; a failure here means a service
moved, changed its schema, or a claim stopped holding.
"""
from __future__ import annotations

import os

import pytest

from agents import orchestrator
from models import SiteInput

pytestmark = [
    pytest.mark.skipif(not os.environ.get("GRIDSENTRY_LIVE"), reason="set GRIDSENTRY_LIVE=1 to hit live services"),
    pytest.mark.timeout(120),
]


async def run(lat: float, lon: float, **kw):
    async def emit(_e):
        return None

    return await orchestrator.run_pipeline("live", SiteInput(lat=lat, lon=lon, **kw), emit)


@pytest.mark.parametrize(
    "name, lat, lon, category",
    [
        ("Grand Canyon NP (PAD-US ownership)", 36.2120, -111.9781, "federal_protected"),
        ("Okefenokee NWR wilderness", 30.8000, -82.3000, "federal_protected"),
        ("Midtown Manhattan (NLCD urban core)", 40.7426, -73.9898, "urban_built"),
        ("Lake Michigan (NLCD open water)", 43.5000, -87.0000, "open_water"),
        ("London (outside U.S.)", 51.5000, -0.1200, "outside_coverage"),
        ("Atlantic, beyond state waters", 39.5000, -72.0000, "outside_coverage"),
    ],
)
async def test_land_status_gate_trips(name, lat, lon, category):
    gis, report = await run(lat, lon)
    assert report.verdict == "not_viable", name
    assert report.land_status.category == category, name
    assert set(gis.provenance.model_dump().values()) == {"not_assessed"}


async def test_demo_site_is_live_verified_and_cited():
    gis, report = await run(42.9, -74.3)
    j = gis.site.jurisdiction
    assert (j.state_code, j.verified, j.in_coverage) == ("NY", True, True)
    assert "census" in j.method
    assert gis.provenance.model_dump() == {k: "live" for k in ("wetlands", "species", "flood", "protected")}
    assert gis.wetlands, "NWI returned no wetlands near the demo site"
    assert report.verdict == "assessed"
    known = {c.id for c in report.citations}
    assert all(cid in known for s in report.sections for f in s.findings for cid in f.citation_ids)


async def test_designated_critical_habitat_is_detected_live():
    """Rio Grande in Albuquerque: designated critical habitat for the silvery minnow."""
    gis, report = await run(35.08, -106.68)
    assert any(h.basis == "critical_habitat" for h in gis.habitats)
    assert report.risk_level == "high"


async def test_payload_stays_small():
    """Server-side generalization keeps a run's stored/transmitted payload bounded."""
    gis, _ = await run(35.5, -115.4)  # Mojave: huge FEMA/PAD-US polygons
    assert len(gis.model_dump_json()) < 3_000_000
