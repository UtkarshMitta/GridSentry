"""Agent 1 — Geolocation Analyst.

Interprets the raw GIS payload: which features matter, how close they are,
and what spatial interactions the project footprint creates. Produces a
structured observation set handed to the Legal Compliance Officer.
"""
from __future__ import annotations

import json
from typing import Any

import geodata
from models import GISPayload

from . import llm
from .critic import protected_overlap_severity

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
            note = (
                f"Designated critical habitat for {h.common_name} ({h.species}, {h.status}) "
                "overlaps the project footprint. The ESA §7 action area reaches this unit."
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
        gap = f"PAD-US GAP {p.gap_status}" if p.gap_status else "GAP unknown"
        if p.overlaps_footprint:
            sev = protected_overlap_severity(p)
            note = f"{p.name} ({p.designation}, managed by {p.manager}; {gap}) overlaps the project footprint."
        else:
            sev = "low"
            note = (
                f"{p.name} ({p.designation}, managed by {p.manager}; {gap}) lies "
                f"{p.distance_m / 1000:.1f} km {p.bearing}; relevant for viewshed and "
                "cumulative-effects analysis."
            )
        obs.append({"feature_id": p.id, "kind": "protected_land", "severity": sev, "note": note})
    for f in gis.flood_zones:
        where = "intersects the project footprint" if f.overlaps_footprint else f"is mapped {f.distance_m:.0f} m away"
        if f.sfha:
            sev = "moderate" if f.overlaps_footprint else "low"
            tail = "; grading and stormwater design must document base-floodplain avoidance."
        else:
            sev = "low"
            tail = "; outside the 1%-annual-chance base floodplain."
        obs.append(
            {
                "feature_id": f.id,
                "kind": "flood_zone",
                "severity": sev,
                "note": f"FEMA Zone {f.zone} ({f.description}) {where}{tail}",
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

    prov = gis.provenance
    if prov.wetlands != "live" and not prov.any_simulated:
        lead = "Wetlands were NOT screened: the NWI service did not respond."
    elif crossing:
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
        radius = geodata._search_radius_m(geodata.half_width_m(gis.site.acreage), geodata.NWI_SEARCH_M, 800)
        lead = f"No NWI wetland polygons were returned within {radius / 1000:.1f} km of the site."
    if prov.species != "live" and not prov.any_simulated:
        sp = " Species were NOT screened: the IPaC service did not respond."
    elif crithab:
        sp = f" Designated critical habitat for the {crithab[0].common_name} overlaps the action area."
    elif listed:
        sp = f" {len(listed)} ESA-listed species appear on the IPaC screen, with no designated critical habitat at the site."
    else:
        sp = " The IPaC query returned no ESA-listed species at this location."

    names = {"wetlands": "NWI", "species": "IPaC", "flood": "FEMA", "protected": "PAD-US"}
    if prov.any_simulated:
        screened = "SIMULATED placeholder data (live services unreachable)"
    else:
        live = [names[k] for k in names if getattr(prov, k) == "live"]
        screened = f"live {', '.join(live)} data" if live else "no live data"
    summary = (
        f"The {gis.site.acreage}-acre {gis.site.project_type} footprint at "
        f"({gis.site.lat:.4f}, {gis.site.lon:.4f}), {location} ({verify}), was screened against "
        f"{screened}. {lead}{sp}"
    )
    return {"summary": summary, "observations": obs}


def _llm_view(gis: GISPayload) -> str:
    """Compact, geometry-free view of the payload for the LLM.

    Raw polygons run to megabytes per site; the model only needs the
    attributes, distances and overlap flags already computed from them.
    """
    drop = {"geometry", "footprint"}
    view = {
        "site": gis.site.model_dump(exclude=drop | {"land_status"}),
        "provenance": gis.provenance.model_dump(),
        "wetlands": [w.model_dump(exclude=drop) for w in gis.wetlands],
        "habitats": [h.model_dump(exclude=drop) for h in gis.habitats],
        "protected_lands": [p.model_dump(exclude=drop) for p in gis.protected_lands],
        "flood_zones": [f.model_dump(exclude=drop) for f in gis.flood_zones],
    }
    return json.dumps(view, default=str)


async def run(gis: GISPayload) -> dict[str, Any]:
    fallback = _fallback(gis)
    if gis.provenance.any_simulated:
        return fallback  # never let a model narrate synthetic features as findings
    result = await llm.complete_json(SYSTEM, _llm_view(gis))
    if not result or "observations" not in result:
        return fallback
    # Keep deterministic observations as the structural source of truth;
    # let the LLM improve the narrative summary.
    if isinstance(result.get("summary"), str) and result["summary"].strip():
        fallback["summary"] = result["summary"]
    return fallback
