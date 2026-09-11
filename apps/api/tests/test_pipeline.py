"""End-to-end agent pipeline with stubbed data services.

Each scenario pins one README claim: what the report must (and must not) say
for a given combination of live findings, provenance, and jurisdiction.
"""
from __future__ import annotations


import geodata
import grounding
import land_status
from agents import llm, orchestrator
from conftest import developable_status, flood, habitat, jur, protected, wetland
from models import LandStatus, SiteInput


ALL_LIVE = {"wetlands": "live", "species": "live", "flood": "live", "protected": "live"}


def stub(monkeypatch, *, jurisdiction=None, status=None, wetlands=(), habitats=(), flood_zones=(),
         protected_lands=(), provenance=None):
    calls = {"fetch_all": 0}

    async def fake_jur(lat, lon):
        return jurisdiction or jur()

    async def fake_check(lat, lon, acreage=300.0):
        return status or developable_status()

    async def fake_fetch(lat, lon, acreage, state_code=None):
        calls["fetch_all"] += 1
        prov = provenance or ALL_LIVE
        return {
            "wetlands": list(wetlands) if prov["wetlands"] == "live" else [],
            "habitats": list(habitats) if prov["species"] == "live" else [],
            "flood_zones": list(flood_zones) if prov["flood"] == "live" else [],
            "protected_lands": list(protected_lands) if prov["protected"] == "live" else [],
            "provenance": prov,
        }

    monkeypatch.setattr(grounding, "resolve_jurisdiction", fake_jur)
    monkeypatch.setattr(land_status, "check", fake_check)
    monkeypatch.setattr(geodata, "fetch_all", fake_fetch)
    return calls


async def run(lat=42.9, lon=-74.3, **kw):
    events = []

    async def emit(e):
        events.append(e)

    gis, report = await orchestrator.run_pipeline("test", SiteInput(lat=lat, lon=lon, **kw), emit)
    return gis, report, events


def section(report, sid):
    return next((s for s in report.sections if s.id == sid), None)


def cite_ids(report):
    return {c.id for c in report.citations}


def assert_citations_resolve(report):
    known = cite_ids(report)
    for s in report.sections:
        for cid in s.citation_ids:
            assert cid in known, cid
        for f in s.findings:
            for cid in f.citation_ids:
                assert cid in known, cid
    for r in report.stop_work_risks:
        for cid in r.citation_ids:
            assert cid in known, cid


def nepa(report):
    return section(report, "nepa-pathway").summary


# --- README: "designated critical habitat drives HIGH" -------------------------

async def test_designated_critical_habitat_drives_high(monkeypatch):
    stub(monkeypatch, habitats=[habitat(basis="critical_habitat")])
    _, report, _ = await run()
    assert section(report, "species").risk == "high"
    assert report.risk_level == "high"
    assert "Categorical Exclusion (CE) likely" not in nepa(report)
    assert any("critical habitat" in s.title.lower() for s in report.stop_work_risks)
    assert_citations_resolve(report)


# --- README: "a footprint vegetated-wetland conflict drives HIGH" ---------------

async def test_vegetated_wetland_in_footprint_drives_high_and_cites_verified_state_law(monkeypatch):
    stub(monkeypatch, wetlands=[wetland("PEM1E", state_protected=True)])
    _, report, _ = await run()
    assert section(report, "wetlands").risk == "high"
    assert report.risk_level == "high"
    assert {"nycrr-663", "ecl-24", "cwa-404"} <= cite_ids(report)
    assert report.alternatives
    assert_citations_resolve(report)


async def test_open_water_pond_in_footprint_is_moderate(monkeypatch):
    stub(monkeypatch, wetlands=[wetland("PUBHx", acres=0.3)])
    _, report, _ = await run()
    assert section(report, "wetlands").risk == "moderate"
    assert report.risk_level != "high"


# --- README: "a genuinely clean site can reach a Categorical Exclusion" --------

async def test_clean_site_reaches_categorical_exclusion(monkeypatch):
    stub(monkeypatch, habitats=[habitat("Monarch butterfly", listed=False, status="Proposed Threatened")])
    _, report, _ = await run()
    assert "Categorical Exclusion (CE) likely" in nepa(report)
    assert report.risk_level == "low"
    assert_citations_resolve(report)


# --- README: unavailable layers are not backfilled / presented as clean --------

async def test_unavailable_layer_is_not_reported_as_clean(monkeypatch):
    stub(monkeypatch, provenance={**ALL_LIVE, "species": "unavailable"})
    _, report, _ = await run()
    sp = section(report, "species")
    assert sp.risk == "unknown"
    assert "returned no ESA-listed species" not in sp.summary
    assert "Categorical Exclusion (CE) likely" not in nepa(report)
    assert any(n.id == "cn-prov" for n in report.critic_notes)


async def test_unavailable_flood_layer_gets_its_own_section(monkeypatch):
    stub(monkeypatch, provenance={**ALL_LIVE, "flood": "unavailable"})
    _, report, _ = await run()
    fl = section(report, "floodplain")
    assert fl is not None and fl.risk == "unknown"


async def test_all_services_down_is_flagged_simulated_everywhere(monkeypatch):
    stub(monkeypatch, provenance={k: "unavailable" for k in ALL_LIVE})
    gis, report, _ = await run()
    assert gis.provenance.any_simulated
    assert "SIMULATED" in report.executive_summary
    assert "drawn from live queries" not in report.executive_summary
    assert all("simulated" in w.source.lower() for w in gis.wetlands)
    assert "Categorical Exclusion (CE) likely" not in nepa(report)
    prov = next(n for n in report.critic_notes if n.id == "cn-prov")
    assert prov.severity == "blocker"
    assert report.confidence <= 30


# --- README: "if the state can't be verified, state citations are withheld" --

async def test_unverified_jurisdiction_withholds_state_citations(monkeypatch):
    stub(monkeypatch, jurisdiction=jur(verified=False, method="nominatim"),
         wetlands=[wetland("PEM1E", state_protected=True)])
    _, report, _ = await run()
    assert not {"nycrr-663", "ecl-24"} & cite_ids(report)
    jur_note = next(n for n in report.critic_notes if n.id == "cn-jur")
    assert jur_note.severity == "blocker"
    assert_citations_resolve(report)


# --- Coverage gate: non-US / offshore -------------------------------------------

async def test_outside_us_is_gated_not_cleared(monkeypatch):
    calls = stub(monkeypatch, jurisdiction=jur(state=None, code=None, verified=False, in_coverage=False,
                                               method="unresolved"))
    gis, report, _ = await run(51.5, -0.12)
    assert report.verdict == "not_viable" and not report.developable
    assert report.land_status.category == "outside_coverage"
    assert calls["fetch_all"] == 0
    assert "Categorical Exclusion" not in report.executive_summary
    assert_citations_resolve(report)


# --- Gated runs never claim simulated data ------------------------------------

async def test_gated_run_provenance_is_not_simulated(monkeypatch):
    status = LandStatus(developable=False, category="federal_protected", owner_type="Federal",
                        manager="National Park Service", manager_code="NPS",
                        unit_name="Grand Canyon National Park", designation="National Park",
                        designation_code="NP", verified=True, method="padus")
    stub(monkeypatch, jurisdiction=jur("Arizona", "AZ"), status=status)
    gis, report, _ = await run(36.212, -111.9781)
    assert report.verdict == "not_viable"
    assert not any("SIMULATED" in s for s in gis.sources)
    assert set(gis.provenance.model_dump().values()) == {"not_assessed"}
    assert {"nps-organic", "nps-100902"} <= cite_ids(report)
    assert_citations_resolve(report)


async def test_refuge_wilderness_cites_refuge_and_wilderness_law_not_nps(monkeypatch):
    status = LandStatus(developable=False, category="federal_protected", owner_type="Federal",
                        manager="U.S. Fish and Wildlife Service", manager_code="FWS",
                        unit_name="Okefenokee National Wildlife Refuge.Wilderness Area",
                        designation="WILDERNESS AREA", designation_code="WA", verified=True, method="padus")
    stub(monkeypatch, jurisdiction=jur("Georgia", "GA"), status=status)
    _, report, _ = await run(30.8, -82.3)
    ids = cite_ids(report)
    assert {"wilderness-act", "nwrs-improvement"} <= ids
    assert "nps-organic" not in ids
    assert_citations_resolve(report)


# --- Protected land the site sits inside --------------------------------------

async def test_site_inside_state_park_is_high(monkeypatch):
    stub(monkeypatch, protected_lands=[protected(gap="2", overlaps=True)])
    _, report, _ = await run()
    assert section(report, "protected-lands").risk == "high"
    assert report.risk_level == "high"
    assert report.stop_work_risks
    assert_citations_resolve(report)


async def test_site_inside_park_is_high_even_with_gap_4(monkeypatch):
    """Real PAD-US record: Harriman State Park is GAP 4 — dedicated parkland regardless."""
    stub(monkeypatch, protected_lands=[protected(gap="4", overlaps=True, dist=0.0)])
    _, report, _ = await run()
    assert section(report, "protected-lands").risk == "high"
    assert report.risk_level == "high"


async def test_footprint_edge_clipping_a_park_is_moderate(monkeypatch):
    stub(monkeypatch, protected_lands=[protected("Tom Cooper", gap="4", overlaps=True, dist=400,
                                                 code="LP", designation="Local park")])
    _, report, _ = await run()
    assert section(report, "protected-lands").risk == "moderate"


async def test_multiple_use_land_nearby_stays_low(monkeypatch):
    stub(monkeypatch, protected_lands=[protected("State Trust Land", gap="4", overlaps=False, dist=3000,
                                                 code="SOTH", designation="State Trust Land")])
    _, report, _ = await run()
    assert section(report, "protected-lands").risk == "low"


# --- Flood zones ---------------------------------------------------------------

async def test_zone_d_is_not_treated_as_floodplain(monkeypatch):
    stub(monkeypatch, flood_zones=[flood("D", sfha=False)])
    _, report, _ = await run()
    assert section(report, "floodplain").risk == "low"
    assert "eo-11988" not in cite_ids(report)
    assert "Categorical Exclusion (CE) likely" in nepa(report)


async def test_sfha_in_footprint_is_moderate_and_cites_eo_11988(monkeypatch):
    stub(monkeypatch, flood_zones=[flood("AE", sfha=True)])
    _, report, _ = await run()
    assert section(report, "floodplain").risk == "moderate"
    assert "eo-11988" in cite_ids(report)


# --- No leftover template text ---------------------------------------------------

async def test_stop_work_trigger_uses_real_bearing(monkeypatch):
    stub(monkeypatch, wetlands=[wetland("PFO1A", dist=120, bearing="W")])
    _, report, _ = await run()
    trig = " ".join(r.trigger for r in report.stop_work_risks)
    assert "eastern" not in trig.lower()


# --- Acreage is an input, not a random number ------------------------------------

async def test_acreage_input_is_used(monkeypatch):
    stub(monkeypatch)
    gis, _, _ = await run(acreage=55)
    assert gis.site.acreage == 55 and gis.site.acreage_assumed is False


async def test_default_acreage_is_labelled_assumed(monkeypatch):
    stub(monkeypatch)
    gis_a, _, _ = await run(42.9, -74.3)
    gis_b, _, _ = await run(35.0, -100.0)
    assert gis_a.site.acreage == gis_b.site.acreage  # not a per-coordinate random draw
    assert gis_a.site.acreage_assumed is True


# --- LLM integration ----------------------------------------------------------------

async def test_llm_prompts_exclude_geometry_and_engine_is_honest(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    prompts = []

    async def failing_openai(system, user):
        prompts.append(user)
        raise RuntimeError("503 from provider")  # simulate an API failure

    monkeypatch.setattr(llm, "_openai", failing_openai)
    stub(monkeypatch, wetlands=[wetland("PEM1E")], protected_lands=[protected(overlaps=False, dist=3000, gap="3")])
    _, report, _ = await run()
    assert prompts and all('"coordinates"' not in p for p in prompts)
    assert all(len(p) < 20_000 for p in prompts)
    assert report.engine.startswith("deterministic")


async def test_llm_success_is_reported(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def ok_openai(system, user):
        return {"summary": "LLM spatial summary " * 5, "observations": [],
                "executive_summary": "An LLM-written executive summary. " * 5,
                "notes": [{"severity": "warning", "target": "wetlands", "note": "check"}], "confidence": 70}

    monkeypatch.setattr(llm, "_openai", ok_openai)
    stub(monkeypatch)
    _, report, _ = await run()
    assert report.engine == "openai"
