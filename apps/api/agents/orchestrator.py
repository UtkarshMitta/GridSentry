"""Sequential 3-agent pipeline with live progress events.

Geolocation Analyst → Legal Compliance Officer → Red-Team Critic, with
structured JSON handoffs. Emits granular status events consumed by the
frontend's SSE stream to animate each agent's "thinking" steps.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from models import GISPayload, Report, SiteInput
import gis_data
import grounding
import land_status

from . import critic, geolocation, legal, llm

Emit = Callable[[dict[str, Any]], Awaitable[None]]

# (agent, message, pause_after_s) — pacing tuned so a full run lands ~15-20 s
SCRIPT_INGEST = [
    ("system", "Reverse-geocoding coordinates to resolve state & county…", 0.6),
    ("system", "Cross-checking jurisdiction against state wetland program (web)…", 0.9),
    ("system", "Querying USFWS National Wetlands Inventory within 2 km…", 1.0),
    ("system", "Querying USFWS critical habitat (ECOS) and PAD-US protected areas…", 0.9),
    ("system", "Querying FEMA National Flood Hazard Layer…", 0.6),
]
SCRIPT_GEO = [
    ("geolocation", "Computing distances and bearings for all mapped features…", 1.0),
    ("geolocation", "Checking project footprint against wetland adjacent areas…", 1.3),
    ("geolocation", "Delineating plausible ESA § 7 action area…", 1.0),
]
SCRIPT_LEGAL = [
    ("legal", "Matching wetland findings to CWA § 404 / 33 CFR § 328.3 jurisdiction…", 1.2),
    ("legal", "Screening state wetland statutes and adjacent-area rules…", 1.2),
    ("legal", "Determining NEPA review level (CE / EA / EIS) under 40 CFR § 1501.3…", 1.0),
    ("legal", "Drafting cited findings and alternative routing analysis…", 1.1),
]
SCRIPT_CRITIC = [
    ("critic", "Challenging distance measurements and delineation currency…", 1.1),
    ("critic", "Auditing citation strength and survey-data gaps…", 1.2),
    ("critic", "Scanning for stop-work triggers and enforcement exposure…", 1.0),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _play(emit: Emit, script: list[tuple[str, str, float]], base: float, span: float) -> None:
    for i, (agent, message, pause) in enumerate(script):
        await emit(
            {
                "type": "status",
                "agent": agent,
                "state": "thinking",
                "message": message,
                "progress": round(base + span * i / len(script), 3),
                "ts": _now(),
            }
        )
        await asyncio.sleep(pause)


async def run_pipeline(run_id: str, site_input: SiteInput, emit: Emit) -> tuple[GISPayload, Report]:
    # Phase 0 — grounding + ingestion
    await emit({"type": "status", "agent": "system", "state": "thinking", "message": SCRIPT_INGEST[0][1], "progress": 0.02, "ts": _now()})
    jurisdiction = await grounding.resolve_jurisdiction(site_input.lat, site_input.lon)
    where = f"{jurisdiction.county + ', ' if jurisdiction.county else ''}{jurisdiction.state}" if jurisdiction.state else "unresolved location"
    verify_note = "verified" if jurisdiction.verified else "UNVERIFIED"
    await emit(
        {
            "type": "status",
            "agent": "system",
            "state": "thinking",
            "message": f"Jurisdiction resolved: {where} ({verify_note}, via {jurisdiction.method}).",
            "progress": 0.08,
            "ts": _now(),
        }
    )
    # Step 0.5 — Land Status Gate: ownership (PAD-US point-in-polygon) +
    # physical buildability (NLCD land-cover grid over the footprint).
    acreage = gis_data.site_acreage(site_input.lat, site_input.lon)
    await emit({"type": "status", "agent": "system", "state": "thinking", "message": f"Land Status Gate: checking federal ownership (PAD-US) + land cover across the {acreage}-acre footprint (NLCD)…", "progress": 0.12, "ts": _now()})
    status = await land_status.check(site_input.lat, site_input.lon, acreage)

    if not status.developable:
        if status.category == "federal_protected":
            gate_msg = f"GATE TRIPPED: site inside {status.unit_name} ({status.designation}, {status.manager}). Halting standard assessment."
        elif status.category == "open_water":
            gate_msg = "GATE TRIPPED: footprint is open water — no land at these coordinates. Halting standard assessment."
        else:
            hi = int(round((status.high_intensity_fraction or 0) * 100))
            detail = f"{hi}% medium/high-intensity developed cover (NLCD)" if status.land_cover_checked else "known dense urban core (offline reference)"
            gate_msg = f"GATE TRIPPED: no buildable land — {detail}. A {acreage}-acre greenfield project cannot physically exist here. Halting standard assessment."
        await emit(
            {
                "type": "status",
                "agent": "system",
                "state": "done",
                "message": gate_msg,
                "progress": 0.2,
                "ts": _now(),
            }
        )
        return await _run_infeasible(run_id, site_input, jurisdiction, status, emit)

    cover_note = (
        f"dominant land cover {status.dominant_cover}" if status.land_cover_checked else "land cover unverified"
    )
    await emit({"type": "status", "agent": "system", "state": "thinking", "message": f"Land Status Gate cleared: no federal protected area; {cover_note} ({status.method}).", "progress": 0.14, "ts": _now()})

    await _play(emit, SCRIPT_INGEST[2:], 0.14, 0.06)
    gis = await gis_data.ingest_live(site_input, jurisdiction)
    gis.site.land_status = status
    prov = gis.provenance
    prov_bits = ", ".join(
        f"{k}={getattr(prov, k)}" for k in ("wetlands", "species", "flood", "protected")
    )
    await emit(
        {
            "type": "gis",
            "agent": "system",
            "state": "done",
            "message": (
                f"Live query in {where}: {len(gis.wetlands)} NWI wetlands, "
                f"{len(gis.habitats)} IPaC species, {len(gis.flood_zones)} FEMA flood zones, "
                f"{len(gis.protected_lands)} PAD-US areas. Provenance: {prov_bits}."
            ),
            "progress": 0.18,
            "ts": _now(),
        }
    )

    # Phase 1 — Geolocation Analyst
    await emit({"type": "status", "agent": "geolocation", "state": "start", "message": "Geolocation Analyst engaged", "progress": 0.2, "ts": _now()})
    await _play(emit, SCRIPT_GEO, 0.2, 0.2)
    geo = await geolocation.run(gis)
    await emit({"type": "status", "agent": "geolocation", "state": "done", "message": f"Flagged {sum(1 for o in geo['observations'] if o['severity'] == 'high')} high-severity spatial conflicts.", "progress": 0.42, "ts": _now()})

    # Phase 2 — Legal Compliance Officer
    await emit({"type": "status", "agent": "legal", "state": "start", "message": "Legal Compliance Officer engaged", "progress": 0.44, "ts": _now()})
    await _play(emit, SCRIPT_LEGAL, 0.44, 0.26)
    legal_out = await legal.run(gis, geo)
    await emit({"type": "status", "agent": "legal", "state": "done", "message": f"Drafted {len(legal_out['sections'])} sections with {len(legal_out['citations'])} regulatory citations.", "progress": 0.72, "ts": _now()})

    # Phase 3 — Red-Team Critic
    await emit({"type": "status", "agent": "critic", "state": "start", "message": "Red-Team Critic engaged", "progress": 0.74, "ts": _now()})
    await _play(emit, SCRIPT_CRITIC, 0.74, 0.2)
    critic_out = await critic.run(gis, legal_out)
    await emit({"type": "status", "agent": "critic", "state": "done", "message": f"Raised {len(critic_out['notes'])} challenges, {len(critic_out['stop_work_risks'])} stop-work risks. Confidence {critic_out['confidence']}%.", "progress": 0.95, "ts": _now()})

    risk_level, risk_score = critic.score_risk(gis)
    report = Report(
        run_id=run_id,
        developable=True,
        verdict="assessed",
        risk_level=risk_level,
        risk_score=risk_score,
        confidence=critic_out["confidence"],
        land_status=status,
        executive_summary=legal_out["executive_summary"],
        sections=legal_out["sections"],
        stop_work_risks=critic_out["stop_work_risks"],
        alternatives=legal_out["alternatives"],
        critic_notes=critic_out["notes"],
        citations=legal_out["citations"],
        generated_at=_now(),
        engine=llm.engine(),
    )
    return gis, report


async def _run_infeasible(
    run_id: str,
    site_input: SiteInput,
    jurisdiction,
    status,
    emit: Emit,
) -> tuple[GISPayload, Report]:
    """Short-circuit path: site is on non-developable federal land.

    Skips the wetland/species template entirely and emits a 'not viable'
    verdict grounded in the land-status finding.
    """
    # Minimal GIS payload (site only) so the map can still render the point.
    gis = gis_data.ingest(site_input, jurisdiction)
    gis.site.land_status = status
    # Drop the simulated environmental features — they are not the story here
    # and would imply an assessment we are explicitly declining to make.
    gis.wetlands = []
    gis.habitats = []
    gis.protected_lands = []
    gis.flood_zones = []

    is_physical = status.category in ("urban_built", "open_water")
    await emit({"type": "status", "agent": "legal", "state": "start", "message": "Legal Compliance Officer engaged — evaluating site eligibility", "progress": 0.55, "ts": _now()})
    await asyncio.sleep(1.0)
    legal_out = legal.build_infeasible(gis)
    verdict_msg = (
        "Verdict: project not physically buildable at these coordinates."
        if is_physical
        else "Verdict: development not legally possible."
    )
    await emit({"type": "status", "agent": "legal", "state": "done", "message": f"{verdict_msg} Cited {len(legal_out['citations'])} authorities.", "progress": 0.78, "ts": _now()})

    await emit({"type": "status", "agent": "critic", "state": "start", "message": "Red-Team Critic engaged — land-status sanity check", "progress": 0.82, "ts": _now()})
    await asyncio.sleep(1.0)
    critic_out = critic.infeasible_review(gis)
    await emit({"type": "status", "agent": "critic", "state": "done", "message": f"Confirmed non-viable verdict. Confidence {critic_out['confidence']}%.", "progress": 0.95, "ts": _now()})

    report = Report(
        run_id=run_id,
        developable=False,
        verdict="not_viable",
        risk_level="high",
        risk_score=100,
        confidence=critic_out["confidence"],
        land_status=status,
        executive_summary=legal_out["executive_summary"],
        sections=legal_out["sections"],
        stop_work_risks=critic_out["stop_work_risks"],
        alternatives=[],
        critic_notes=critic_out["notes"],
        citations=legal_out["citations"],
        generated_at=_now(),
        engine=llm.engine(),
    )
    return gis, report
