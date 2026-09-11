"""Agent 3 — Red-Team Critic.

Adversarially reviews the draft assessment: challenges weak citations,
surfaces stop-work risks the first two agents underplayed, and assigns a
confidence score. Its notes render inline in the report UI.
"""
from __future__ import annotations

from typing import Any

from models import CriticNote, GISPayload, ProtectedLand, StopWorkRisk

from . import llm

# Cowardin system prefixes for vegetated (higher-value) wetlands vs
# open-water / pond features (lower permitting value, easier to design around).
VEGETATED_PREFIXES = ("PEM", "PFO", "PSS", "EEM", "E2EM", "PAB")


def is_vegetated_wetland(classification: str) -> bool:
    code = (classification or "").upper()
    return any(code.startswith(p) for p in VEGETATED_PREFIXES)


# PAD-US designation codes for dedicated public parkland. GAP status measures
# biodiversity management, not dedication: Harriman State Park is GAP 4, yet
# converting it to a utility use would need legislative approval.
PARKLAND_CODES = {"NP", "SP", "LP", "SREC", "LREC"}


def is_parkland(p: ProtectedLand) -> bool:
    return (p.designation_code or "") in PARKLAND_CODES or "park" in (p.designation or "").lower()


def protected_overlap_severity(p: ProtectedLand) -> str:
    """How much a PAD-US unit constrains the footprint: high | moderate | low."""
    if not p.overlaps_footprint:
        return "low"
    if p.gap_status in ("1", "2") or (is_parkland(p) and p.distance_m <= 0):
        return "high"
    if is_parkland(p) or p.gap_status == "3":
        return "moderate"
    return "low"

SYSTEM = """You are the Red-Team Critic on an environmental permitting team.
Adversarially review a draft NEPA assessment. Return JSON:
{"notes": [{"severity": "blocker|warning|info", "target": "<section id>", "note": "..."}],
 "confidence": <0-100>}
Challenge unstated assumptions, survey gaps, and weak citations. Be specific."""


def infeasible_review(gis: GISPayload) -> dict[str, Any]:
    """Red-team content for a Land-Status-gated (non-developable) site."""
    ls = gis.site.land_status
    if ls.category == "outside_coverage":
        return _out_of_coverage_review(gis)
    if ls.category in ("urban_built", "open_water"):
        return _unbuildable_review(gis)
    from .legal import federal_cites  # local import: legal imports this module

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
            citation_ids=federal_cites(ls.designation_code, ls.manager_code),
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
            citation_ids=["nepa-4336", "nepa-4332"],
        )
    ]
    return {
        "notes": [n.model_dump() for n in notes],
        "stop_work_risks": [s.model_dump() for s in stop_work],
        "confidence": 95 if ls.land_cover_checked else 68,
    }


def _out_of_coverage_review(gis: GISPayload) -> dict[str, Any]:
    """Red-team content for coordinates outside U.S. state jurisdiction."""
    notes = [
        CriticNote(
            id="cn-cov-1",
            severity="blocker",
            target="coverage",
            note=(
                "Coverage sanity check: every environmental layer this tool uses is a U.S. dataset. "
                "Had the pipeline run here, each would have returned an empty result and the report "
                "would have read as a clean site eligible for a Categorical Exclusion — a false "
                "negative. The correct output is 'outside analysis coverage', which this report gives. "
                "Most often this means latitude/longitude were swapped or a sign was dropped."
            ),
        )
    ]
    return {"notes": [n.model_dump() for n in notes], "stop_work_risks": [], "confidence": 90}


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
    # makes state-law conclusions unusable, so they are withheld entirely.
    if not jur.verified or not jur.state:
        if jur.method == "conflict":
            why = f"reverse geocoding and U.S. Census boundaries disagree on the state (Census: {jur.state})"
        elif jur.state:
            why = f"it was resolved as {jur.state} ({jur.method}) but not confirmed against U.S. Census boundaries"
        else:
            why = "it could not be resolved at all"
        notes.append(
            CriticNote(
                id="cn-jur",
                severity="blocker",
                target="report",
                note=(
                    f"JURISDICTION NOT VERIFIED: {why}. All state wetland-law citations have been "
                    "withheld from this draft, so state permitting obligations are NOT analysed. "
                    "Confirm the site's state and county before relying on this report — a "
                    "wrong-state citation voids the compliance analysis."
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
        head = next((w for w in crossing if is_vegetated_wetland(w.classification)), crossing[0])
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
    if gis.site.acreage_assumed:
        notes.append(
            CriticNote(
                id="cn-acre",
                severity="info",
                target="report",
                note=(
                    f"No project acreage was supplied, so a {gis.site.acreage:.0f}-acre square footprint "
                    "was assumed. Every 'inside the footprint' finding depends on that assumption — "
                    "re-run with the actual layout acreage."
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
    }.get(jur.state_code if jur.verified else "", ("the applicable state wetland permit", ["eo-11990"]))
    stop_work: list[StopWorkRisk] = []
    if crossing:
        head = next((w for w in crossing if is_vegetated_wetland(w.classification)), crossing[0])
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
                trigger=(
                    "Mobilization on the array/interconnection area around the mapped wetland "
                    + ("(at the site centroid)" if head.distance_m <= 0 else f"({head.distance_m:.0f} m {head.bearing} of centroid)")
                    + " before permits issue"
                ),
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
    blocking_lands = [p for p in gis.protected_lands if protected_overlap_severity(p) == "high"]
    if blocking_lands:
        p = blocking_lands[0]
        why = (
            f"which PAD-US records as GAP {p.gap_status} (managed for biodiversity)"
            if p.gap_status in ("1", "2") else "dedicated public parkland"
        )
        stop_work.append(
            StopWorkRisk(
                id="sw-3",
                title=f"Construction on protected land — {p.name}",
                detail=(
                    f"The footprint overlaps {p.name} ({p.designation}, {p.manager}), {why}. Site "
                    "work without the land manager's written authorization is trespass, and no "
                    "environmental permit substitutes for that authorization."
                ),
                trigger="Any survey staking, clearing, or access-road work inside the unit",
                citation_ids=["nepa-4332"],
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


def score_risk(gis: GISPayload) -> tuple[str, int]:
    """Data-driven overall risk (0-100) from the actual live features.

    Any single controlling constraint — a vegetated wetland in the footprint,
    designated critical habitat, or conservation land in the footprint —
    reaches HIGH (>= 65) on its own; lesser constraints accumulate.
    """
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    nearby = [w for w in gis.wetlands if not w.crosses_footprint]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    prop_ch = [h for h in gis.habitats if h.basis == "proposed_critical_habitat"]
    listed = [h for h in gis.habitats if h.currently_listed]
    veg_crossing = [w for w in crossing if is_vegetated_wetland(w.classification)]

    score = 8  # baseline for any greenfield build
    if veg_crossing:
        # Vegetated wetland (marsh/forested/scrub) in the footprint — the serious case.
        score += 57 + min(12, (len(veg_crossing) - 1) * 4)
        if any(w.state_protected for w in veg_crossing):
            score += 6
    elif crossing:
        # Only open-water / excavated ponds in the footprint — a designable-around
        # constraint (panels are routed around them), never on its own a HIGH.
        score += 16 + min(8, (len(crossing) - 1) * 2)
    elif nearby:
        nearest = min(w.distance_m for w in nearby)
        score += 14 if nearest < 300 else 6
    if crithab:
        score += 57
    elif prop_ch:
        score += 20
    elif listed:
        score += 12
    land_sev = {protected_overlap_severity(p) for p in gis.protected_lands}
    if "high" in land_sev:
        score += 57
    elif "moderate" in land_sev:
        score += 12
    sfha = [f for f in gis.flood_zones if f.sfha]
    if any(f.overlaps_footprint for f in sfha):
        score += 10
    elif sfha:
        score += 4
    score = max(3, min(score, 96))
    level = "high" if score >= 65 else ("moderate" if score >= 35 else "low")
    return level, score


async def run(gis: GISPayload, legal: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback(gis, legal)
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
