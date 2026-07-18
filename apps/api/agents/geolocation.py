"""Agent 1 — Geolocation Analyst.

Interprets the raw GIS payload: which features matter, how close they are,
and what spatial interactions the project footprint creates. Produces a
structured observation set handed to the Legal Compliance Officer.
"""
from __future__ import annotations

from typing import Any

from models import GISPayload

from . import llm

SYSTEM = """You are the Geolocation Analyst on an environmental permitting team.
Given GIS features near a proposed energy site, write a JSON object:
{"summary": "<3-4 sentence spatial analysis>",
 "observations": [{"feature_id": "...", "kind": "wetland|habitat|protected_land|flood_zone",
                   "severity": "high|moderate|low", "note": "<1-2 sentences>"}]}
Be precise about distances and bearings. Flag anything within 300 m as high severity."""


def _yd(meters: float) -> int:
    return round(meters * 1.09361 / 10) * 10


def _fallback(gis: GISPayload) -> dict[str, Any]:
    obs: list[dict[str, Any]] = []
    for w in gis.wetlands:
        if w.crosses_footprint:
            sev = "high"
            loc = "inside the project footprint"
        elif w.distance_m < 300:
            sev = "moderate"
            loc = f"{w.distance_m:.0f} m (~{_yd(w.distance_m)} yd) {w.bearing} of the centroid"
        else:
            sev = "low"
            loc = f"{w.distance_m:.0f} m (~{_yd(w.distance_m)} yd) {w.bearing} of the centroid"
        note = (
            f"{w.wetland_type} ({w.classification}), {w.area_acres} ac, mapped {loc}."
        )
        if w.state_protected and w.state_class:
            note += f" {w.state_class}."
        obs.append({"feature_id": w.id, "kind": "wetland", "severity": sev, "note": note})
    for h in gis.habitats:
        if h.basis == "critical_habitat":
            sev = "high"
            where = f"{h.distance_m / 1000:.1f} km {h.bearing}" if h.distance_m is not None else "overlapping the location"
            note = (
                f"Designated critical habitat for {h.common_name} ({h.species}, {h.status}) "
                f"{where}. Action area under ESA §7 plausibly reaches this unit."
            )
        elif h.currently_listed:
            sev = "moderate"
            note = (
                f"{h.common_name} ({h.species}, {h.status}) appears on the IPaC official species "
                "list for the location — a presence screen, not a designated critical-habitat unit."
            )
        else:
            sev = "low"
            note = f"{h.common_name} ({h.species}, {h.status}) — proposed/candidate; monitor only."
        obs.append({"feature_id": h.id, "kind": "habitat", "severity": sev, "note": note})
    for p in gis.protected_lands:
        obs.append(
            {
                "feature_id": p.id,
                "kind": "protected_land",
                "severity": "low",
                "note": (
                    f"{p.name} ({p.designation}, managed by {p.manager}) lies "
                    f"{p.distance_m / 1000:.1f} km {p.bearing}; relevant for viewshed and "
                    "cumulative-effects analysis."
                ),
            }
        )
    for f in gis.flood_zones:
        inside = f.distance_m <= 1.0
        obs.append(
            {
                "feature_id": f.id,
                "kind": "flood_zone",
                "severity": "moderate" if inside or f.distance_m < 300 else "low",
                "note": (
                    f"FEMA Zone {f.zone} ({f.description}) "
                    + ("intersects the site" if inside else f"mapped {f.distance_m:.0f} m away")
                    + "; grading and stormwater design must document floodplain avoidance."
                ),
            }
        )

    jur = gis.site.jurisdiction
    location = (
        f"in {jur.county + ', ' if jur.county else ''}{jur.state}"
        if jur.state
        else "in an unresolved jurisdiction"
    )
    verify = (
        "jurisdiction verified via reverse geocoding and web cross-check"
        if jur.verified
        else "jurisdiction NOT independently verified"
    )
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    listed = [h for h in gis.habitats if h.currently_listed]

    if crossing:
        lead = (
            f"The controlling spatial constraint is a mapped {crossing[0].wetland_type} polygon "
            f"inside the {gis.site.acreage}-acre footprint."
        )
    elif gis.wetlands:
        w = gis.wetlands[0]
        lead = (
            f"The nearest mapped wetland ({w.wetland_type}) is {w.distance_m:.0f} m {w.bearing} of "
            "the centroid — a setback consideration, not a footprint conflict."
        )
    else:
        lead = "No NWI wetland polygons were returned within 1.6 km of the site."
    if crithab:
        sp = f" Designated critical habitat for the {crithab[0].common_name} overlaps the action area."
    elif listed:
        sp = f" {len(listed)} ESA-listed species appear on the IPaC screen, with no designated critical habitat at the site."
    else:
        sp = " The IPaC query returned no ESA-listed species at this location."

    summary = (
        f"The {gis.site.acreage}-acre {gis.site.project_type} footprint at "
        f"({gis.site.lat:.4f}, {gis.site.lon:.4f}), {location} ({verify}), was screened against "
        f"live NWI, IPaC, FEMA, and PAD-US data. {lead}{sp}"
    )
    return {"summary": summary, "observations": obs}


async def run(gis: GISPayload) -> dict[str, Any]:
    result = await llm.complete_json(SYSTEM, gis.model_dump_json())
    fallback = _fallback(gis)
    if not result or "observations" not in result:
        return fallback
    # Keep deterministic observations as the structural source of truth;
    # let the LLM improve the narrative summary.
    fallback["summary"] = result.get("summary", fallback["summary"])
    return fallback
