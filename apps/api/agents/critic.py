"""Agent 3 — Red-Team Critic.

Adversarially reviews the draft assessment: challenges weak citations,
surfaces stop-work risks the first two agents underplayed, and assigns a
confidence score. Its notes render inline in the report UI.
"""
from __future__ import annotations

from typing import Any

from models import CriticNote, GISPayload, StopWorkRisk

from . import llm

# Cowardin system prefixes for vegetated (higher-value) wetlands vs
# open-water / pond features (lower permitting value, easier to design around).
VEGETATED_PREFIXES = ("PEM", "PFO", "PSS", "EEM", "E2EM", "PAB")


def is_vegetated_wetland(classification: str) -> bool:
    code = (classification or "").upper()
    return any(code.startswith(p) for p in VEGETATED_PREFIXES)

SYSTEM = """You are the Red-Team Critic on an environmental permitting team.
Adversarially review a draft NEPA assessment. Return JSON:
{"notes": [{"severity": "blocker|warning|info", "target": "<section id>", "note": "..."}],
 "confidence": <0-100>}
Challenge unstated assumptions, survey gaps, and weak citations. Be specific."""


def infeasible_review(gis: GISPayload) -> dict[str, Any]:
    """Red-team content for a Land-Status-gated (non-developable) site."""
    ls = gis.site.land_status
    if ls.category in ("urban_built", "open_water"):
        return _unbuildable_review(gis)
    unit = ls.unit_name or "a federal protected area"
    notes = [
        CriticNote(
            id="cn-land-1",
            severity="blocker",
            target="land-status",
            note=(
                f"Land-status sanity check: the site sits inside {unit}. Any report that "
                "recommended mitigation, alternatives, or a risk score out of 100 here would be "
                "wrong — the correct output is 'development not legally possible', which this "
                "report gives. Do not advance this site to environmental permitting."
            ),
        ),
    ]
    if not ls.verified:
        notes.append(
            CriticNote(
                id="cn-land-2",
                severity="warning",
                target="land-status",
                note=(
                    "The land-status determination came from an offline reference set, not a live "
                    "PAD-US query. Confirm the boundary against USGS PAD-US before treating the "
                    "'not viable' verdict as final."
                ),
            )
        )
    stop_work = [
        StopWorkRisk(
            id="sw-land",
            title="Development on federal protected land",
            detail=(
                f"Ground-disturbing activity within {unit} without statutory authorization is "
                "a federal trespass/violation and cannot be cured by a state or Corps permit."
            ),
            trigger="Any site work prior to (improbable) Congressional/agency authorization",
            citation_ids=["nps-organic", "nepa-4332"],
        )
    ]
    return {
        "notes": [n.model_dump() for n in notes],
        "stop_work_risks": [s.model_dump() for s in stop_work],
        "confidence": 96 if ls.verified else 70,
    }


def _unbuildable_review(gis: GISPayload) -> dict[str, Any]:
    """Red-team content for a buildability-gated site (urban core / open water)."""
    ls = gis.site.land_status
    site = gis.site
    is_water = ls.category == "open_water"
    what = "open water" if is_water else "a fully built-up urban core"
    notes = [
        CriticNote(
            id="cn-build-1",
            severity="blocker",
            target="buildability",
            note=(
                f"Buildability sanity check: the proposed {site.acreage}-acre footprint sits on "
                f"{what}. Any report that produced wetland distances, species habitat units, or "
                "floodplain findings here would be fabricating features that cannot exist at these "
                "coordinates — the correct output is 'input validation failed: no buildable land', "
                "which this report gives."
            ),
        ),
    ]
    if ls.land_cover_checked:
        notes.append(
            CriticNote(
                id="cn-build-2",
                severity="info",
                target="buildability",
                note=(
                    f"Determination is grounded in a live NLCD 2021 grid sample "
                    f"(dominant cover: {ls.dominant_cover}; "
                    f"{int(round((ls.high_intensity_fraction or 0) * 100))}% medium/high-intensity developed, "
                    f"{int(round((ls.water_fraction or 0) * 100))}% open water), not an LLM inference."
                ),
            )
        )
    else:
        notes.append(
            CriticNote(
                id="cn-build-2",
                severity="warning",
                target="buildability",
                note=(
                    "The live NLCD land-cover query was unavailable; this verdict came from an "
                    "offline urban-core reference set. Confirm against NLCD/current imagery before "
                    "treating it as final."
                ),
            )
        )
    stop_work = [
        StopWorkRisk(
            id="sw-build",
            title="Project premise invalid — no buildable land at coordinates",
            detail=(
                f"Advancing this {site.project_type} project as specified would require "
                + ("siting utility-scale infrastructure on open water, outside the scope of this terrestrial assessment."
                   if is_water
                   else "large-scale acquisition and demolition of existing urban development — a categorically different action requiring a new proposal and full re-analysis.")
            ),
            trigger="Any permitting submission using the current coordinates and acreage",
            citation_ids=["ceq-1501", "nepa-4332"],
        )
    ]
    return {
        "notes": [n.model_dump() for n in notes],
        "stop_work_risks": [s.model_dump() for s in stop_work],
        "confidence": 95 if ls.land_cover_checked else 68,
    }


def _fallback(gis: GISPayload, legal: dict[str, Any]) -> dict[str, Any]:
    jur = gis.site.jurisdiction
    prov = gis.provenance
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    notes: list[CriticNote] = []

    # Highest-priority red-team check: data provenance. If any core layer is
    # simulated or unavailable, that dwarfs every downstream nuance.
    if prov.any_simulated:
        notes.append(
            CriticNote(
                id="cn-prov",
                severity="blocker",
                target="report",
                note=(
                    "SIMULATED DATA: live geospatial services (NWI/IPaC/FEMA/PAD-US) were "
                    "unreachable, so the wetland, species, and flood features in this draft are "
                    "synthetic placeholders, not real findings. Do not rely on any distance, "
                    "species, or risk score here until the run is repeated against live data."
                ),
            )
        )
    else:
        unavailable = [k for k in ("wetlands", "species", "flood", "protected") if getattr(prov, k) == "unavailable"]
        if unavailable:
            notes.append(
                CriticNote(
                    id="cn-prov",
                    severity="warning",
                    target="report",
                    note=(
                        f"Partial data: the {', '.join(unavailable)} layer(s) did not respond on this "
                        "run, so that section may understate constraints. Re-run to confirm before relying on it."
                    ),
                )
            )

    # Grounding integrity: a wrong-state citation or unverified jurisdiction
    # makes state-law conclusions unusable.
    if not jur.verified or not jur.state:
        notes.append(
            CriticNote(
                id="cn-jur",
                severity="blocker",
                target="report",
                note=(
                    "JURISDICTION NOT VERIFIED: the state used for all state-law citations was "
                    f"{'resolved as ' + jur.state + ' but not confirmed against an authoritative source' if jur.state else 'not resolved at all'} "
                    f"(method: {jur.method}). Do not rely on any state regulation in this draft "
                    "until the site's state and county are confirmed — a wrong-state citation "
                    "voids the compliance analysis."
                ),
            )
        )
    ls = gis.site.land_status
    if not ls.verified:
        notes.append(
            CriticNote(
                id="cn-land-check",
                severity="warning",
                target="report",
                note=(
                    "Land-ownership status was NOT verified against USGS PAD-US (live query "
                    "failed). This report assumes the site is on development-eligible land — if it "
                    "actually falls within a National Park, Wilderness, or Wildlife Refuge, the "
                    "entire assessment is moot. Confirm land ownership before proceeding."
                ),
            )
        )
    # Analytical red-team notes, conditional on what the live data returned.
    if crossing:
        head = crossing[0]
        notes.append(
            CriticNote(
                id="cn-1",
                severity="warning",
                target="wetlands",
                note=(
                    f"The {head.distance_m:.0f} m distance to the mapped {head.wetland_type} is "
                    "computed from live NWI geometry to the site centroid, not the nearest array or "
                    "access-road disturbance limit. A field-run delineation (current within 5 years) "
                    "is required before the footprint-conflict conclusion is final — NWI polygons are "
                    "desktop-mapped and routinely off by 30–80 m."
                ),
            )
        )
    elif gis.wetlands:
        notes.append(
            CriticNote(
                id="cn-1",
                severity="info",
                target="wetlands",
                note=(
                    "Wetlands are mapped near, but not within, the footprint. Confirm the setback "
                    "survives final array layout and stormwater design; NWI is a desktop screen and a "
                    "delineation may shift boundaries."
                ),
            )
        )
    if crithab or [h for h in gis.habitats if h.currently_listed]:
        notes.append(
            CriticNote(
                id="cn-2",
                severity="warning",
                target="species",
                note=(
                    "IPaC returns species that may occur at the location; it is not a presence/absence "
                    "survey. Commission field/acoustic surveys in the appropriate season before finalizing "
                    "any 'may affect' or 'no effect' determination."
                ),
            )
        )
    notes.append(
        CriticNote(
            id="cn-3",
            severity="info",
            target="report",
            note=(
                "Cultural resources are unaddressed: no SHPO records check or Phase IA reconnaissance "
                "is cited. NHPA § 106 review runs parallel to NEPA and can independently affect schedule."
            ),
        )
    )

    # State permit label + citations follow the resolved jurisdiction.
    state_permit = {
        "NY": ("an Article 24 Freshwater Wetlands permit", ["nycrr-663", "ecl-24"]),
        "NJ": ("an NJDEP Freshwater Wetlands / transition-area permit", ["njsa-13-9b", "njac-77a"]),
    }.get(jur.state_code or "", ("the applicable state wetland permit", ["eo-11990"]))
    stop_work: list[StopWorkRisk] = []
    if crossing:
        head = crossing[0]
        stop_work.append(
            StopWorkRisk(
                id="sw-1",
                title="Unpermitted disturbance of a mapped wetland inside the footprint",
                detail=(
                    f"Clearing, grading, or trenching in the {head.wetland_type} polygon mapped inside "
                    f"the footprint before a CWA § 404 permit"
                    + (f" and {state_permit[0]}" if head.state_protected else "")
                    + " issues constitutes a violation subject to stop-work orders and restoration liability."
                ),
                trigger="Mobilization on the eastern array/interconnection area before permits issue",
                citation_ids=["cwa-404"] + (state_permit[1] if head.state_protected else []),
            )
        )
    if crithab:
        stop_work.append(
            StopWorkRisk(
                id="sw-2",
                title=f"Take risk — designated critical habitat for {crithab[0].common_name}",
                detail=(
                    "Ground disturbance affecting designated critical habitat without completed ESA § 7 "
                    "consultation risks unauthorized take under ESA § 9 and immediate federal enforcement."
                ),
                trigger="Vegetation clearing or grading before § 7 consultation concludes",
                citation_ids=["esa-7", "cfr-402"],
            )
        )
    # Confidence reflects how much we can trust the draft. Live, verified data
    # earns a high ceiling; simulated data or an unverified jurisdiction caps it.
    prov = gis.provenance
    if prov.any_simulated:
        confidence = 30
    elif not jur.verified:
        confidence = 38 if jur.state else 22
    else:
        confidence = 82
        if any(getattr(prov, k) == "unavailable" for k in ("wetlands", "species", "flood", "protected")):
            confidence -= 12
    return {
        "notes": [n.model_dump() for n in notes],
        "stop_work_risks": [s.model_dump() for s in stop_work],
        "confidence": confidence,
    }


# Numeric weight per section risk level, summed into an overall 0-100 score.
def score_risk(gis: GISPayload) -> tuple[str, int]:
    """Data-driven overall risk from the actual live features."""
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    nearby = [w for w in gis.wetlands if not w.crosses_footprint]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    listed = [h for h in gis.habitats if h.currently_listed]

    veg_crossing = [w for w in crossing if is_vegetated_wetland(w.classification)]
    score = 8  # baseline for any greenfield build
    if veg_crossing:
        # Vegetated wetland (marsh/forested/scrub) in the footprint — the serious case.
        score += 45 + min(12, (len(veg_crossing) - 1) * 4)
        if any(w.state_protected for w in veg_crossing):
            score += 8
    elif crossing:
        # Only open-water / excavated ponds in the footprint — a designable-around
        # constraint (panels are routed around them), never on its own a HIGH.
        score += 16 + min(8, (len(crossing) - 1) * 2)
    elif nearby:
        nearest = min(w.distance_m for w in nearby)
        score += 14 if nearest < 300 else 6
    if crithab:
        score += 30
    elif listed:
        score += 12
    if gis.flood_zones:
        f = gis.flood_zones[0]
        score += 10 if f.distance_m <= 1.0 else 4
    score = max(3, min(score, 96))
    level = "high" if score >= 65 else ("moderate" if score >= 35 else "low")
    return level, score


async def run(gis: GISPayload, legal: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback(gis, legal)
    jur = gis.site.jurisdiction
    prov = gis.provenance
    # Provenance + grounding-integrity notes are never overridden by the LLM.
    pinned_ids = ("cn-prov", "cn-jur", "cn-land-check")
    grounding_notes = [n for n in fallback["notes"] if n["id"] in pinned_ids]

    result = await llm.complete_json(
        SYSTEM,
        f"Executive summary: {legal['executive_summary']}\n\nSections: {legal['sections']}",
    )
    if result and isinstance(result.get("notes"), list) and result["notes"]:
        merged = []
        for i, n in enumerate(result["notes"][:4]):
            if all(k in n for k in ("severity", "target", "note")) and n["severity"] in ("blocker", "warning", "info"):
                merged.append({"id": f"cn-llm-{i+1}", **{k: n[k] for k in ("severity", "target", "note")}})
        if merged:
            fallback["notes"] = grounding_notes + merged + [
                n for n in fallback["notes"] if n["id"] not in pinned_ids
            ][:1]
        if isinstance(result.get("confidence"), int):
            capped = max(30, min(95, result["confidence"]))
            # Never let the LLM raise confidence above the deterministic ceiling.
            fallback["confidence"] = min(capped, fallback["confidence"])
    return fallback
