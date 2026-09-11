"""Agent 2 — Legal Compliance Officer.

Maps the Geolocation Analyst's observations to specific federal and state
regulations, producing cited report sections. Citations come from a
curated knowledge base of real statutes/regulations so every badge in the
UI links to an authoritative source.
"""
from __future__ import annotations

from typing import Any

from models import Alternative, Citation, Finding, GISPayload, ReportSection

from . import llm
from .critic import is_parkland, protected_overlap_severity
from .critic import is_vegetated_wetland as _is_vegetated

# --- Regulation knowledge base (real citations) -----------------------------

CITATIONS: dict[str, Citation] = {
    c.id: c
    for c in [
        Citation(
            id="nepa-4332",
            label="42 U.S.C. § 4332",
            title="NEPA § 102 — Detailed statement requirement (EIS)",
            source="National Environmental Policy Act",
            url="https://www.law.cornell.edu/uscode/text/42/4332",
            excerpt="Requires a detailed statement on the environmental impact of major federal actions significantly affecting the quality of the human environment.",
        ),
        # CEQ's NEPA regulations (40 CFR Parts 1500-1508) were rescinded
        # effective 2025-04-11; the level-of-review test is now statutory.
        Citation(
            id="nepa-4336",
            label="42 U.S.C. § 4336",
            title="NEPA § 106 — Procedure for determination of level of review",
            source="National Environmental Policy Act (as amended 2023)",
            url="https://www.law.cornell.edu/uscode/text/42/4336",
            excerpt="No environmental document is required where an action falls within an agency categorical exclusion; an EIS is required for a reasonably foreseeable significant effect, and an EA where effects are not significant or their significance is unknown.",
        ),
        Citation(
            id="cwa-404",
            label="CWA § 404",
            title="Clean Water Act § 404 — Discharge of dredged or fill material (33 U.S.C. § 1344)",
            source="Clean Water Act",
            url="https://www.law.cornell.edu/uscode/text/33/1344",
            excerpt="Requires a permit from the U.S. Army Corps of Engineers for discharge of dredged or fill material into waters of the United States, including many wetlands.",
        ),
        Citation(
            id="cfr-328",
            label="33 CFR § 328.3",
            title="Definition of Waters of the United States",
            source="U.S. Army Corps of Engineers",
            url="https://www.ecfr.gov/current/title-33/chapter-II/part-328/section-328.3",
            excerpt="Defines jurisdictional waters, including wetlands adjacent to traditional navigable waters, for CWA § 404 purposes.",
        ),
        Citation(
            id="esa-7",
            label="ESA § 7",
            title="Endangered Species Act § 7 — Interagency consultation (16 U.S.C. § 1536)",
            source="Endangered Species Act",
            url="https://www.law.cornell.edu/uscode/text/16/1536",
            excerpt="Federal agencies must ensure actions are not likely to jeopardize listed species or destroy/adversely modify designated critical habitat.",
        ),
        Citation(
            id="cfr-402",
            label="50 CFR § 402.14",
            title="Formal consultation requirements",
            source="USFWS / NMFS",
            url="https://www.ecfr.gov/current/title-50/chapter-IV/subchapter-A/part-402/subpart-B/section-402.14",
            excerpt="Formal consultation is required when a federal action may affect listed species or designated critical habitat.",
        ),
        Citation(
            id="nycrr-663",
            label="6 NYCRR Part 663",
            title="Freshwater Wetlands Permit Requirements",
            source="New York State DEC",
            url="https://govt.westlaw.com/nycrr/Browse/Home/NewYork/NewYorkCodesRulesandRegulations?guid=I50b2ee80b5a011dda0a4e17826ebc834",
            excerpt="Regulates activities in state freshwater wetlands and their 100-foot adjacent areas; Class I wetlands receive the most stringent protection standard of 'compatibility'.",
        ),
        Citation(
            id="ecl-24",
            label="NY ECL Art. 24",
            title="New York Freshwater Wetlands Act",
            source="NYS Environmental Conservation Law",
            url="https://www.nysenate.gov/legislation/laws/ENV/A24",
            excerpt="Establishes state jurisdiction over freshwater wetlands of 12.4 acres or more (and smaller wetlands of unusual local importance) and their adjacent areas.",
        ),
        Citation(
            id="njsa-13-9b",
            label="N.J.S.A. 13:9B",
            title="New Jersey Freshwater Wetlands Protection Act",
            source="New Jersey Statutes",
            url="https://dep.nj.gov/wlm/lrp/freshwater-wetlands/",
            excerpt="Regulates freshwater wetlands and transition areas in New Jersey; NJDEP administers the federal CWA § 404 program in-state under assumed authority.",
        ),
        Citation(
            id="njac-77a",
            label="N.J.A.C. 7:7A",
            title="Freshwater Wetlands Protection Act Rules",
            source="New Jersey Administrative Code (NJDEP)",
            url="https://dep.nj.gov/rules/njac-7-7a/",
            excerpt="Implements the FWPA: wetland resource-value classification (Exceptional/Intermediate/Ordinary), transition areas up to 150 ft for Exceptional Resource Value wetlands, and permit requirements.",
        ),
        Citation(
            id="eo-11990",
            label="E.O. 11990",
            title="Executive Order 11990 — Protection of Wetlands",
            source="Executive Office of the President",
            url="https://www.archives.gov/federal-register/codification/executive-order/11990.html",
            excerpt="Federal agencies must avoid undertaking or assisting new construction in wetlands unless no practicable alternative exists.",
        ),
        Citation(
            id="eo-11988",
            label="E.O. 11988",
            title="Executive Order 11988 — Floodplain Management",
            source="Executive Office of the President",
            url="https://www.fema.gov/glossary/executive-order-11988-floodplain-management",
            excerpt="Requires agencies to avoid direct or indirect support of floodplain development wherever there is a practicable alternative.",
        ),
        Citation(
            id="nhpa-106",
            label="NHPA § 106",
            title="National Historic Preservation Act § 106 (54 U.S.C. § 306108)",
            source="National Historic Preservation Act",
            url="https://www.law.cornell.edu/uscode/text/54/306108",
            excerpt="Federal agencies must take into account the effects of undertakings on historic properties prior to approval.",
        ),
        # --- Federal land-status citations (Land Status Gate) ---
        Citation(
            id="nps-organic",
            label="54 U.S.C. § 100101",
            title="National Park Service Organic Act",
            source="National Park Service Organic Act",
            url="https://www.law.cornell.edu/uscode/text/54/100101",
            excerpt="Directs the NPS to conserve park scenery, natural and historic objects, and wildlife and leave them unimpaired for future generations — the standard under which non-conforming commercial development inside a park unit is barred.",
        ),
        Citation(
            id="nps-100902",
            label="54 U.S.C. § 100902",
            title="Rights of way through National Park System units for public utilities",
            source="Title 54, U.S. Code",
            url="https://www.law.cornell.edu/uscode/text/54/100902",
            excerpt="A right of way through a System unit for electrical plants, poles, and lines may be granted only under Secretarial regulations, with the Secretary's approval, and on a finding that it is not incompatible with the public interest; its width is limited to the occupied ground plus 50 feet on each side.",
        ),
        Citation(
            id="wilderness-act",
            label="16 U.S.C. § 1133(c)",
            title="Wilderness Act — prohibited uses",
            source="Wilderness Act of 1964",
            url="https://www.law.cornell.edu/uscode/text/16/1133",
            excerpt="Prohibits commercial enterprise, permanent roads, structures, and installations within designated wilderness, subject to narrow exceptions.",
        ),
        Citation(
            id="nwrs-improvement",
            label="16 U.S.C. § 668dd",
            title="National Wildlife Refuge System Administration Act",
            source="NWRS Improvement Act of 1997",
            url="https://www.law.cornell.edu/uscode/text/16/668dd",
            excerpt="Uses of a national wildlife refuge must be compatible with the refuge's establishment purposes; incompatible commercial uses are not permitted.",
        ),
        Citation(
            id="flpma",
            label="43 U.S.C. § 1701",
            title="Federal Land Policy and Management Act (FLPMA)",
            source="FLPMA of 1976",
            url="https://www.law.cornell.edu/uscode/text/43/1701",
            excerpt="Governs BLM public lands; energy development on federal land requires a right-of-way grant and full NEPA review, and is excluded where land-use plans or designations prohibit it.",
        ),
        Citation(
            id="antiquities",
            label="54 U.S.C. § 320301",
            title="Antiquities Act — National Monuments",
            source="Antiquities Act of 1906",
            url="https://www.law.cornell.edu/uscode/text/54/320301",
            excerpt="Authorizes protection of national monuments; monument proclamations typically withdraw the land from new mineral and energy development.",
        ),
    ]
}

# Organic/administration statute for each federal land manager.
AGENCY_LAW = {"NPS": ["nps-organic"], "FWS": ["nwrs-improvement"], "BLM": ["flpma"]}


def federal_cites(code: str | None, manager_code: str | None) -> list[str]:
    """Governing authorities for a barred federal unit, by designation *and* agency.

    Keyed on the PAD-US designation code, never the free-text label, and on
    the managing agency — a Fish & Wildlife Service wilderness is governed by
    the Refuge Administration Act, not the NPS Organic Act.
    """
    agency_law = AGENCY_LAW.get(manager_code or "", [])
    by_code = {
        "NP": ["nps-organic", "nps-100902"],
        "WA": ["wilderness-act"] + agency_law,
        "WSA": ["wilderness-act"] + (agency_law or ["flpma"]),
        "NM": ["antiquities"] + agency_law,
        "NWR": ["nwrs-improvement"],
        "NS": ["nps-organic"],
        "NLS": ["nps-organic"],
    }.get(code or "", agency_law)
    return list(dict.fromkeys(by_code + ["nepa-4332"]))


def build_infeasible(gis: GISPayload) -> dict[str, Any]:
    """Report content for a site the Land Status Gate marks non-developable."""
    ls = gis.site.land_status
    if ls.category == "outside_coverage":
        return _build_out_of_coverage(gis)
    if ls.category in ("urban_built", "open_water"):
        return _build_unbuildable(gis)
    unit = ls.unit_name or "a federal protected area"
    desig = ls.designation or "protected federal land"
    manager = ls.manager or "a federal land-management agency"
    cite_ids = federal_cites(ls.designation_code, ls.manager_code)
    verify_clause = (
        "confirmed against the USGS Protected Areas Database (PAD-US)"
        if ls.verified
        else "flagged from an offline reference set (not independently confirmed — verify against PAD-US before relying on this)"
    )

    summary = (
        f"THRESHOLD FINDING — SITE NOT VIABLE. The proposed coordinates fall inside "
        f"{unit}, a {desig} managed by the {manager}, {verify_clause}. This is the "
        "controlling fact for the site and supersedes any wetland, species, or floodplain "
        f"analysis: utility-scale {gis.site.project_type} development inside this unit is not a "
        "permitted use of the land and would require extraordinary agency or Congressional "
        "authorization, not an environmental permit. GridSentry does not proceed to the standard impact assessment for a site "
        "where development is not legally possible. Recommended action: relocate the project "
        "to non-federal or development-eligible land and re-run the analysis."
    )

    sections = [
        ReportSection(
            id="land-status",
            title="Land Ownership & Development Eligibility",
            risk="high",
            summary=(
                f"The site is located within {unit} ({desig}), managed by the {manager}. "
                "Non-conforming commercial energy development is prohibited on this land "
                "category."
            ),
            findings=[
                Finding(
                    id="f-land-1",
                    title=f"Site is inside a federal protected unit — {unit}",
                    severity="high",
                    detail=(
                        f"A point-in-polygon check against USGS PAD-US places the coordinates "
                        f"inside {unit}, a {desig} unit. Under the governing federal statute, the "
                        "managing agency must conserve the unit's resources unimpaired; "
                        "utility-scale energy generation is not a permitted use and cannot be "
                        "authorized through the ordinary NEPA/CWA/ESA permitting path."
                    ),
                    citation_ids=cite_ids,
                    feature_id=None,
                )
            ],
            citation_ids=cite_ids,
        )
    ]
    return {
        "executive_summary": summary,
        "sections": [s.model_dump() for s in sections],
        "alternatives": [],
        "citations": [CITATIONS[cid].model_dump() for cid in cite_ids],
    }


def _build_unbuildable(gis: GISPayload) -> dict[str, Any]:
    """Report content when the buildability check (NLCD land cover) trips:
    dense urban core or open water — no physical land for the footprint."""
    ls = gis.site.land_status
    site = gis.site
    jur = site.jurisdiction
    # Dedupe repeated names (e.g. locality "New York" + state "New York").
    where_parts: list[str] = []
    for part in (jur.locality, jur.county, jur.state):
        if part and part not in where_parts:
            where_parts.append(part)
    where = ", ".join(where_parts) or "the resolved jurisdiction"
    cite_ids = ["nepa-4336", "nepa-4332"]
    is_water = ls.category == "open_water"

    if ls.land_cover_checked:
        hi = int(round((ls.high_intensity_fraction or 0) * 100))
        dev = int(round((ls.developed_fraction or 0) * 100))
        wat = int(round((ls.water_fraction or 0) * 100))
        if is_water:
            evidence = (
                f"A grid sample of the USGS/MRLC National Land Cover Database (NLCD 2021) across the "
                f"proposed {site.acreage}-acre footprint returns {wat}% open water "
                f"(dominant cover: {ls.dominant_cover})."
            )
        else:
            evidence = (
                f"A grid sample of the USGS/MRLC National Land Cover Database (NLCD 2021) across the "
                f"proposed {site.acreage}-acre footprint returns {hi}% medium/high-intensity developed "
                f"cover ({dev}% developed overall; dominant cover: {ls.dominant_cover})."
            )
    else:
        evidence = (
            f"The coordinates fall inside {ls.unit_name or 'a known dense urban core'} per an offline "
            "reference set (live NLCD query unavailable — confirm against NLCD before relying on this)."
        )

    problem = (
        "the site is open water — there is no land at these coordinates to host the project"
        if is_water
        else (
            f"the footprint is fully built-up urban land in {where}. There is no contiguous "
            f"undeveloped parcel remotely approaching {site.acreage} acres at this location; "
            "the project would require mass acquisition and demolition of existing structures, "
            "which is a land-assembly and eminent-domain problem, not a wetland-permitting problem"
        )
    )

    summary = (
        f"THRESHOLD FINDING — SITE NOT PHYSICALLY BUILDABLE. Before any wetland, species, or "
        f"floodplain analysis applies, the proposed {site.acreage}-acre {site.project_type} project "
        f"fails on basic physical feasibility: {problem}. {evidence} GridSentry does not generate "
        "an environmental impact assessment for a site where the stated project cannot physically "
        "exist — doing so would produce fabricated wetland and species findings. Recommended "
        "action: correct the coordinates or relocate the project to open land, then re-run the analysis."
    )

    sections = [
        ReportSection(
            id="buildability",
            title="Physical Buildability & Land Cover",
            risk="high",
            summary=(
                "The land-cover check found no developable open land at the proposed footprint. "
                "This threshold failure supersedes the standard environmental review."
            ),
            findings=[
                Finding(
                    id="f-build-1",
                    title=(
                        "Proposed footprint is open water"
                        if is_water
                        else f"Proposed {site.acreage}-acre footprint conflicts with existing dense urban development"
                    ),
                    severity="high",
                    detail=(
                        f"{evidence} Under NEPA, the review level (CE/EA/EIS) is assessed for a "
                        "proposed action that is actually capable of implementation; a project with "
                        "no physically available site fails input validation and should be returned "
                        "to the proponent rather than advanced to environmental review."
                    ),
                    citation_ids=cite_ids,
                    feature_id=None,
                )
            ],
            citation_ids=cite_ids,
        )
    ]
    return {
        "executive_summary": summary,
        "sections": [s.model_dump() for s in sections],
        "alternatives": [],
        "citations": [CITATIONS[cid].model_dump() for cid in cite_ids],
    }


def _build_out_of_coverage(gis: GISPayload) -> dict[str, Any]:
    """Report content when the site is outside U.S. state jurisdiction."""
    site = gis.site
    country = site.jurisdiction.country_code
    where = (
        f"outside the United States (country code: {country.upper()})"
        if country
        else "in open water beyond U.S. state waters (federal Outer Continental Shelf or international waters)"
    )
    cite_ids = ["nepa-4332"]
    summary = (
        f"THRESHOLD FINDING — SITE OUTSIDE ANALYSIS COVERAGE. The coordinates "
        f"({site.lat:.4f}, {site.lon:.4f}) fall {where}: neither the U.S. Census Bureau nor "
        "OpenStreetMap places them in any U.S. state or county. Every dataset GridSentry relies on "
        "(USFWS NWI and IPaC, FEMA NFHL, USGS PAD-US and NLCD) covers U.S. land only, so an empty "
        "result here means 'no data', not 'no constraints'. No environmental assessment has been "
        "generated. "
        + ("Use the environmental review framework of the host country. "
           if country else "Offshore energy siting is governed by BOEM under the Outer Continental Shelf Lands Act. ")
        + "Recommended action: check the coordinates (latitude/longitude order and sign) and re-run."
    )
    sections = [
        ReportSection(
            id="coverage",
            title="Analysis Coverage",
            risk="unknown",
            summary="The site is outside the geographic coverage of every federal dataset this assessment uses.",
            findings=[
                Finding(
                    id="f-cov-1",
                    title="No U.S. state jurisdiction at these coordinates",
                    severity="high",
                    detail=(
                        "The U.S. Census Bureau geocoder returned no state or county, and reverse "
                        "geocoding did not resolve a U.S. address. NEPA applies to major federal "
                        "actions; the wetland, species, and floodplain datasets it is paired with "
                        "here cannot be screened at this location."
                    ),
                    citation_ids=cite_ids,
                )
            ],
            citation_ids=cite_ids,
        )
    ]
    return {
        "executive_summary": summary,
        "sections": [s.model_dump() for s in sections],
        "alternatives": [],
        "citations": [CITATIONS[cid].model_dump() for cid in cite_ids],
    }


SYSTEM = """You are the Legal Compliance Officer on an environmental permitting team.
Given spatial observations for a proposed energy project, return JSON:
{"executive_summary": "<4-5 sentences, professional EIS-draft register>"}
Reference the specific regulations implicated (NEPA, CWA 404, ESA 7, state wetland law).
Only cite the state regulations for the state provided — never another state's.
If the state is marked UNVERIFIED, cite no state law at all. Never describe a
layer listed as "not assessed" as clean or free of constraints."""

# State wetland statutes, keyed by USPS state code of a *verified*
# jurisdiction (from the grounding step — never inferred from coordinates).
STATE_WETLAND_CITES: dict[str, list[str]] = {
    "NY": ["nycrr-663", "ecl-24"],
    "NJ": ["njsa-13-9b", "njac-77a"],
}
# Unverified or other states: only the federal wetland-avoidance order.
GENERIC_WETLAND_CITES = ["eo-11990"]


def state_wetland_cites(jur) -> list[str]:
    """State wetland citations — only for a *verified* jurisdiction."""
    if not jur.verified:
        return GENERIC_WETLAND_CITES
    return STATE_WETLAND_CITES.get(jur.state_code or "", GENERIC_WETLAND_CITES)


LAYER_LABELS = {
    "wetlands": "USFWS National Wetlands Inventory",
    "species": "USFWS IPaC species",
    "flood": "FEMA flood hazard (NFHL)",
    "protected": "USGS PAD-US protected areas",
}
RISK_ORDER = {"none": 0, "low": 1, "moderate": 2, "high": 3}
SIMULATED_TAG = "[SIMULATED — not a real finding] "


def _max_risk(*levels: str) -> str:
    return max(levels, key=lambda r: RISK_ORDER.get(r, 0))


def _jurisdiction_label(jur) -> str:
    parts: list[str] = []
    for p in (jur.county, jur.state):
        if p and p not in parts:
            parts.append(p)
    return ", ".join(parts) if parts else "an unresolved jurisdiction"


def _where_phrase(distance_m: float, bearing: str) -> str:
    if distance_m <= 0:
        return "the mapped polygon contains the site centroid"
    return f"{distance_m:.0f} m {bearing} of centroid"


def build_sections(gis: GISPayload, geo: dict[str, Any]) -> tuple[list[ReportSection], list[Alternative], list[str]]:
    """Data-driven section construction from live features.

    Every section is conditional on real returned data *and* its provenance.
    A layer that answered with nothing is a genuinely clean result; a layer
    that did not answer is reported as NOT ASSESSED — never as clean.
    Distances, crossings, and risk come from the actual geometry.
    """
    jur = gis.site.jurisdiction
    prov = gis.provenance
    obs_by_id = {o["feature_id"]: o for o in geo["observations"]}
    sections: list[ReportSection] = []
    used: set[str] = set()
    alternatives: list[Alternative] = []

    def cite(*ids: str) -> list[str]:
        used.update(ids)
        return list(ids)

    def obs_note(fid: str, default: str = "") -> str:
        o = obs_by_id.get(fid)
        return o["note"] if o else default

    def not_assessed(sid: str, title: str, layer: str, *cite_ids: str) -> ReportSection:
        return ReportSection(
            id=sid,
            title=title,
            risk="unknown",
            summary=(
                f"NOT ASSESSED — the {LAYER_LABELS[layer]} service did not respond at run time, so "
                "this section has no findings. The absence of findings here is NOT evidence that no "
                "constraint exists; re-run the analysis before relying on this report."
            ),
            findings=[],
            citation_ids=cite(*cite_ids),
        )

    jurisdiction_label = _jurisdiction_label(jur)
    unverified_clause = "" if jur.verified else " (jurisdiction unverified — state-law citations withheld)"

    # Partition wetlands into those the footprint overlaps vs merely nearby.
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    nearby = [w for w in gis.wetlands if not w.crosses_footprint]
    state_cites = state_wetland_cites(jur)
    # Vegetated wetlands (marsh/forested/scrub) are higher-value and harder to
    # permit than open-water/excavated ponds; a footprint conflict with the
    # former is HIGH, with only the latter it is MODERATE (designable-around).
    veg_crossing = [w for w in crossing if _is_vegetated(w.classification)]

    # -- Wetlands --
    wetland_risk = "none"
    if prov.wetlands == "unavailable":
        wetland_risk = "unknown"
        sections.append(not_assessed("wetlands", "Wetlands & Waters of the U.S.", "wetlands", "cwa-404"))
    elif gis.wetlands:
        wet_findings: list[Finding] = []
        if crossing:
            wetland_risk = "high" if veg_crossing else "moderate"
            for i, w in enumerate(crossing, start=1):
                state_line = (
                    f" This polygon is {w.state_class}." if w.state_protected and w.state_class else ""
                )
                wet_findings.append(
                    Finding(
                        id=f"f-wet-c{i}",
                        title=f"Wetland within project footprint — {w.wetland_type} ({w.classification})",
                        severity="high" if _is_vegetated(w.classification) else "moderate",
                        detail=(
                            f"{obs_note(w.id)} The mapped polygon intersects the {gis.site.acreage}-acre "
                            f"project footprint, so array/access-road siting will require avoidance or a "
                            f"CWA § 404 permit from the Army Corps and a § 401 state water-quality "
                            f"certification.{state_line} Site is in {jurisdiction_label}{unverified_clause}."
                        ),
                        citation_ids=cite("cwa-404", "cfr-328", *(state_cites if w.state_protected else [])),
                        feature_id=w.id,
                    )
                )
        for i, w in enumerate(nearby[:4], start=1):
            sev = "moderate" if w.distance_m < 300 else "low"
            if sev == "moderate" and wetland_risk != "high":
                wetland_risk = "moderate"
            elif wetland_risk == "none":
                wetland_risk = "low"
            wet_findings.append(
                Finding(
                    id=f"f-wet-n{i}",
                    title=f"Nearby NWI wetland — {w.wetland_type} ({w.classification})",
                    severity=sev,
                    detail=(
                        f"{obs_note(w.id)} Outside the footprint; relevant if grading, stormwater, or "
                        "collector lines extend toward it. If determined jurisdictional, fill triggers "
                        "CWA § 404 / § 401 review."
                    ),
                    citation_ids=cite("cwa-404", "cfr-328"),
                    feature_id=w.id,
                )
            )
        if crossing:
            head = next((w for w in crossing if _is_vegetated(w.classification)), crossing[0])
            summary = (
                f"USFWS NWI mapping places {len(crossing)} wetland "
                f"{'polygon' if len(crossing) == 1 else 'polygons'} inside the project footprint "
                f"(nearest {head.wetland_type}, {head.classification}). This is the controlling "
                "permitting constraint for the current layout."
                if veg_crossing else
                f"USFWS NWI mapping places {len(crossing)} open-water or non-vegetated "
                f"{'feature' if len(crossing) == 1 else 'features'} inside the footprint "
                f"({head.wetland_type}, {head.classification}) — a designable-around constraint "
                "rather than a vegetated-wetland conflict."
            )
        else:
            nearest = gis.wetlands[0]
            summary = (
                f"No NWI wetland polygon falls inside the footprint. The nearest mapped wetland "
                f"({nearest.wetland_type}, {nearest.classification}) is {nearest.distance_m:.0f} m "
                f"{nearest.bearing}. Wetlands are a manageable setback constraint, not a footprint conflict."
            )
        sections.append(
            ReportSection(
                id="wetlands",
                title="Wetlands & Waters of the U.S.",
                risk=wetland_risk,
                summary=summary,
                findings=wet_findings,
                citation_ids=cite("cwa-404", "cfr-328"),
            )
        )
    else:
        sections.append(
            ReportSection(
                id="wetlands",
                title="Wetlands & Waters of the U.S.",
                risk="none",
                summary=(
                    "A live USFWS National Wetlands Inventory query returned no mapped wetland "
                    "polygons within 1.6 km of the site. A field delineation is still prudent, but "
                    "the desktop record shows no wetland constraint at this location."
                ),
                findings=[],
                citation_ids=cite("cwa-404"),
            )
        )

    # -- Species --
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    prop_ch = [h for h in gis.habitats if h.basis == "proposed_critical_habitat"]
    listed = [h for h in gis.habitats if h.currently_listed]
    non_listed = [h for h in gis.habitats if not h.currently_listed]
    species_risk = "none"
    if prov.species == "unavailable":
        species_risk = "unknown"
        sections.append(not_assessed("species", "Threatened & Endangered Species", "species", "esa-7"))
    elif gis.habitats:
        sp_findings: list[Finding] = []
        for i, h in enumerate(crithab, start=1):
            sp_findings.append(
                Finding(
                    id=f"f-sp-ch{i}",
                    title=f"Designated critical habitat — {h.common_name}",
                    severity="high",
                    detail=(
                        f"IPaC reports designated critical habitat for the {h.common_name} "
                        f"({h.species}, {h.status}) intersecting the project footprint. A federal "
                        "nexus makes formal ESA § 7 consultation likely; destruction/adverse "
                        "modification of critical habitat is the controlling standard."
                    ),
                    citation_ids=cite("esa-7", "cfr-402"),
                    feature_id=h.id,
                )
            )
        for i, h in enumerate(prop_ch, start=1):
            sp_findings.append(
                Finding(
                    id=f"f-sp-pch{i}",
                    title=f"Proposed critical habitat — {h.common_name}",
                    severity="moderate",
                    detail=(
                        f"IPaC reports proposed (not yet final) critical habitat for the {h.common_name} "
                        f"({h.species}, {h.status}) intersecting the footprint. ESA § 7(a)(4) requires a "
                        "conference if the action is likely to adversely modify it, and the posture "
                        "escalates to formal consultation if the designation is finalized."
                    ),
                    citation_ids=cite("esa-7"),
                    feature_id=h.id,
                )
            )
        if listed:
            names = ", ".join(f"{h.common_name} ({h.status})" for h in listed[:6])
            sp_findings.append(
                Finding(
                    id="f-sp-list",
                    title=f"ESA-listed species on the IPaC official list ({len(listed)})",
                    severity="moderate",
                    detail=(
                        f"The USFWS IPaC official species list for this location includes: {names}. "
                        "This is a species-presence screen, not a critical-habitat designation: a "
                        "'may affect' determination requires informal § 7 consultation, with "
                        "presence/absence surveys scheduled in the appropriate season."
                        + ("" if crithab else " Absent designated critical habitat here, effects are "
                           "usually manageable through seasonal restrictions and standard conservation measures.")
                    ),
                    citation_ids=cite("esa-7", "cfr-402"),
                )
            )
        if non_listed:
            names = ", ".join(f"{h.common_name} ({h.status})" for h in non_listed[:6])
            sp_findings.append(
                Finding(
                    id="f-sp-prop",
                    title=f"Proposed, candidate, or non-§7 taxa to monitor ({len(non_listed)})",
                    severity="info",
                    detail=(
                        f"IPaC also flags: {names}. These carry no current § 7 consultation "
                        "obligation (proposed/candidate species, non-essential experimental "
                        "populations, and similarity-of-appearance listings) but should be tracked, "
                        "as a listing during development would change the consultation posture."
                    ),
                    citation_ids=cite("esa-7"),
                )
            )
        species_risk = "high" if crithab else "moderate" if (prop_ch or listed) else "low"
        if crithab:
            tail = (f", including designated critical habitat for {crithab[0].common_name} in the "
                    "footprint. This elevates the section to a formal § 7 posture.")
        elif prop_ch:
            tail = f", with proposed critical habitat for {prop_ch[0].common_name} in the footprint."
        else:
            tail = (". No designated critical habitat overlaps the site, so this is a species-screen "
                    "obligation rather than a habitat-destruction constraint.")
        sections.append(
            ReportSection(
                id="species",
                title="Threatened & Endangered Species",
                risk=species_risk,
                summary=(
                    f"The live IPaC query returned {len(listed)} ESA-listed and {len(non_listed)} "
                    f"proposed/candidate/non-§7 species{tail}"
                ),
                findings=sp_findings,
                citation_ids=cite("esa-7", "cfr-402"),
            )
        )
    else:
        sections.append(
            ReportSection(
                id="species",
                title="Threatened & Endangered Species",
                risk="none",
                summary=(
                    "The live USFWS IPaC query returned no ESA-listed species for this location. "
                    "Confirm at the time of application, but the desktop record shows no listed-species "
                    "constraint."
                ),
                findings=[],
                citation_ids=cite("esa-7"),
            )
        )

    # -- Protected lands (PAD-US): GAP status + footprint overlap drive risk --
    protected_risk = "none"
    inside_conservation = [p for p in gis.protected_lands if protected_overlap_severity(p) == "high"]
    if prov.protected == "unavailable":
        protected_risk = "unknown"
        sections.append(not_assessed("protected-lands", "Protected & Public Lands", "protected", "nepa-4332"))
    elif gis.protected_lands:
        pl_findings = []
        for i, p in enumerate(gis.protected_lands[:4], start=1):
            gap = f"PAD-US GAP {p.gap_status}" if p.gap_status else "PAD-US GAP status unknown"
            sev = protected_overlap_severity(p)
            if sev == "high" and p.gap_status in ("1", "2"):
                detail = (
                    f"The project footprint overlaps {p.name} ({p.designation}, {p.manager}; {gap} — "
                    "managed for biodiversity). Conservation land of this kind is generally unavailable "
                    "for utility-scale development without the managing agency's authorization, and "
                    "dedicated parkland typically requires legislative action to convert. Treat this as "
                    "a siting blocker until the land manager confirms otherwise."
                )
            elif sev == "high":
                detail = (
                    f"The site centroid lies inside {p.name} ({p.designation}, {p.manager}), dedicated "
                    "public parkland. Converting parkland to a utility use generally requires legislative "
                    "approval (e.g. state parkland-alienation rules) on top of any environmental permit. "
                    "Treat this as a siting blocker."
                )
            elif is_parkland(p) and p.overlaps_footprint:
                detail = (
                    f"The edge of the project footprint overlaps {p.name} ({p.designation}, {p.manager}), "
                    "dedicated public parkland. Adjust the layout to stay out of the park boundary."
                )
            elif p.overlaps_footprint and p.gap_status == "3":
                detail = (
                    f"The project footprint overlaps {p.name} ({p.designation}, {p.manager}; {gap} — "
                    "multiple use). Development requires the land manager's lease or right-of-way "
                    "authorization and conformance with its land-use plan."
                )
            elif p.overlaps_footprint:
                detail = (
                    f"The project footprint overlaps {p.name} ({p.designation}, {p.manager}; {gap}). "
                    "Confirm ownership and any easement restrictions with the land manager."
                )
            else:
                detail = obs_note(
                    p.id, f"{p.name} ({p.designation}, {p.manager}) is {p.distance_m / 1000:.1f} km {p.bearing}."
                )
            protected_risk = _max_risk(protected_risk, sev)
            blm = p.overlaps_footprint and p.manager == "Bureau of Land Management"
            pl_findings.append(
                Finding(
                    id=f"f-pl-{i}",
                    title=f"{p.name} — {p.designation}" + (" (inside footprint)" if p.overlaps_footprint else ""),
                    severity=sev,
                    detail=detail,
                    citation_ids=cite("nepa-4332", *(["flpma"] if blm else [])),
                    feature_id=p.id,
                )
            )
        if inside_conservation:
            pl_summary = (
                f"The project footprint overlaps {inside_conservation[0].name} "
                f"({inside_conservation[0].designation}). This is a land-availability constraint that "
                "environmental permits cannot cure."
            )
        else:
            nearest_p = gis.protected_lands[0]
            pl_summary = (
                f"PAD-US maps {len(gis.protected_lands)} managed/protected "
                f"{'area' if len(gis.protected_lands) == 1 else 'areas'} within 5 km; nearest is "
                f"{nearest_p.name} ({'overlapping the footprint' if nearest_p.overlaps_footprint else f'{nearest_p.distance_m / 1000:.1f} km {nearest_p.bearing}'}). "
                "Relevant for cumulative-effects and viewshed analysis."
            )
        sections.append(
            ReportSection(
                id="protected-lands",
                title="Protected & Public Lands",
                risk=protected_risk,
                summary=pl_summary,
                findings=pl_findings,
                citation_ids=cite("nepa-4332"),
            )
        )

    # -- Floodplain: only the 1%-annual-chance SFHA is a floodplain constraint --
    flood_risk = "none"
    if prov.flood == "unavailable":
        flood_risk = "unknown"
        sections.append(not_assessed("floodplain", "Floodplain Management", "flood", "eo-11988"))
    elif gis.flood_zones:
        sfha = [f for f in gis.flood_zones if f.sfha]
        sfha_in = [f for f in sfha if f.overlaps_footprint]
        if sfha_in:
            flood_risk = "moderate"
            f = sfha_in[0]
            fl_summary = (
                f"FEMA NFHL maps Zone {f.zone} — the 1%-annual-chance base floodplain — intersecting the "
                "project footprint. Grading, equipment elevation, and collector-line routing must "
                "document floodplain avoidance where practicable."
            )
        elif sfha:
            flood_risk = "low"
            f = sfha[0]
            fl_summary = (
                f"The nearest base-floodplain zone (FEMA Zone {f.zone}) is {f.distance_m:.0f} m from the "
                "centroid, outside the footprint. Keep stormwater and collector lines out of it."
            )
        else:
            flood_risk = "low"
            fl_summary = (
                "No Special Flood Hazard Area (1%-annual-chance floodplain) is mapped within 1.2 km. "
                "Nearby FEMA zones: "
                + "; ".join(f"Zone {z.zone} — {z.description}" for z in gis.flood_zones[:3])
                + "."
            )
        fl_findings = []
        for i, z in enumerate(gis.flood_zones[:3], start=1):
            sev = "moderate" if (z.sfha and z.overlaps_footprint) else "low" if z.sfha else "info"
            fl_findings.append(
                Finding(
                    id=f"f-fl-{i}",
                    title=f"FEMA Zone {z.zone} {'in footprint' if z.overlaps_footprint else 'in vicinity'}",
                    severity=sev,
                    detail=obs_note(z.id, f"FEMA Zone {z.zone}: {z.description}."),
                    citation_ids=cite("eo-11988") if z.sfha else [],
                    feature_id=z.id,
                )
            )
        sections.append(
            ReportSection(
                id="floodplain",
                title="Floodplain Management",
                risk=flood_risk,
                summary=fl_summary,
                findings=fl_findings,
                citation_ids=cite("eo-11988") if sfha else [],
            )
        )

    # -- NEPA pathway (level derived from the real findings and their provenance) --
    missing = [LAYER_LABELS[k] for k in prov.unavailable_layers()]
    has_high = bool(veg_crossing) or bool(crithab) or bool(inside_conservation)
    has_mod = "moderate" in (wetland_risk, species_risk, flood_risk, protected_risk)
    if prov.any_simulated:
        nepa_level = "Undetermined — no live data"
        nepa_risk = "unknown"
        nepa_detail = (
            "This draft is built on simulated placeholder features because every live federal "
            "geospatial service was unreachable. No review level can be recommended until the "
            "analysis is re-run against live data."
        )
    elif has_high:
        nepa_level = "Environmental Assessment (EA), targeting a mitigated FONSI"
        nepa_risk = "moderate"
        nepa_detail = (
            "A footprint conflict with a vegetated wetland, designated critical habitat, or "
            "protected land means a Categorical Exclusion is not defensible. Prepare an EA under "
            "NEPA § 106(b)(2) with the record built to withstand elevation to an EIS "
            "(§ 106(b)(1)); early avoidance materially improves the FONSI."
        )
    elif missing:
        nepa_level = "Undetermined — incomplete data"
        nepa_risk = "unknown"
        nepa_detail = (
            f"The {', '.join(missing)} layer(s) did not respond at run time. A Categorical Exclusion "
            "cannot be supported on an incomplete record; re-run the analysis to determine the "
            "review level."
        )
    elif has_mod:
        nepa_level = "Environmental Assessment (EA) or documented Categorical Exclusion"
        nepa_risk = "low"
        nepa_detail = (
            "Constraints are proximity-based rather than direct footprint conflicts. Depending on "
            "the lead agency's categorical exclusions and final delineation/survey results, a "
            "documented CE may be available (NEPA § 106(a)(2)); otherwise a concise EA under "
            "§ 106(b)(2) is appropriate."
        )
    else:
        nepa_level = "Categorical Exclusion (CE) likely available"
        nepa_risk = "low"
        nepa_detail = (
            "The live datasets show no wetland footprint conflict, no designated critical habitat, "
            "no conservation-land overlap, and no base floodplain at the site. Subject to "
            "extraordinary-circumstances review and field verification, this project profile is a "
            "strong candidate for a categorical exclusion under the lead agency's NEPA procedures "
            "(NEPA § 106(a)(2))."
        )
    sections.append(
        ReportSection(
            id="nepa-pathway",
            title="NEPA Review Pathway",
            risk=nepa_risk,
            summary=f"Recommended review level: {nepa_level}.",
            findings=[
                Finding(
                    id="f-nepa-1",
                    title=f"Recommended review level — {nepa_level.split(',')[0]}",
                    severity="info",
                    detail=nepa_detail,
                    citation_ids=cite("nepa-4336", "nepa-4332"),
                )
            ],
            citation_ids=cite("nepa-4336", "nepa-4332"),
        )
    )

    # -- Alternatives only make sense when there's a footprint wetland to avoid --
    if crossing:
        head = next((w for w in crossing if _is_vegetated(w.classification)), crossing[0])
        alternatives = [
            Alternative(
                id="alt-1",
                title="Alternative A — Array setback from mapped wetland",
                description=(
                    f"Pull the array and access roads back to a ≥150 ft setback from the "
                    f"{head.wetland_type} polygon mapped inside the footprint "
                    f"({_where_phrase(head.distance_m, head.bearing)}), keeping equipment out of the "
                    "wetland and its buffer. Recovers most nameplate capacity through block reconfiguration."
                ),
                impact_reduction="Removes the CWA § 404 footprint conflict; converts the wetlands section from HIGH toward LOW.",
            ),
            Alternative(
                id="alt-2",
                title="Alternative B — Interconnection re-route",
                description=(
                    "Route the gen-tie/collector corridor around the mapped wetland rather than "
                    "across it, trading a modest conductor increase for removal of the wetland permit "
                    "from the critical path."
                ),
                impact_reduction="Avoids wetland disturbance on the interconnection path; minor added conductor length.",
            ),
        ]

    if prov.any_simulated:
        for sec in sections:
            if sec.id != "nepa-pathway":
                sec.summary = SIMULATED_TAG + sec.summary
                for f in sec.findings:
                    f.title = SIMULATED_TAG + f.title

    return sections, alternatives, sorted(used)


def _fallback_summary(gis: GISPayload, sections: list[ReportSection]) -> str:
    jur = gis.site.jurisdiction
    prov = gis.provenance
    location = (
        f"in {jur.locality + ', ' if jur.locality else ''}{_jurisdiction_label(jur)}"
        if jur.state
        else "in an unresolved jurisdiction (state law citations withheld pending verification)"
    )
    acreage = f"{gis.site.acreage}-acre" + (" (assumed default footprint)" if gis.site.acreage_assumed else "")
    if prov.any_simulated:
        return (
            "SIMULATED DATA — NOT A SITE ASSESSMENT. Every live federal geospatial service (USFWS "
            "NWI and IPaC, FEMA NFHL, USGS PAD-US) was unreachable when this run executed, so the "
            f"features in this draft for the proposed {acreage} {gis.site.project_type} project "
            f"{location} are synthetic placeholders generated only so the report renders. No "
            "distance, species, risk score, or review-level conclusion here describes the real "
            "site. Re-run the analysis when the services are reachable."
        )

    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    listed = [h for h in gis.habitats if h.currently_listed]
    inside_conservation = [p for p in gis.protected_lands if protected_overlap_severity(p) == "high"]
    nepa = next((s for s in sections if s.id == "nepa-pathway"), None)
    nepa_line = f" {nepa.summary}" if nepa else ""

    # Build the constraint clause from what the live data actually returned.
    constraints: list[str] = []
    if crossing:
        w = next((x for x in crossing if _is_vegetated(x.classification)), crossing[0])
        constraints.append(
            f"{len(crossing)} NWI wetland "
            f"{'polygon' if len(crossing) == 1 else 'polygons'} inside the project footprint "
            f"(nearest {w.wetland_type}; {_where_phrase(w.distance_m, w.bearing)})"
        )
    elif gis.wetlands:
        w = gis.wetlands[0]
        constraints.append(
            f"the nearest mapped wetland {w.distance_m:.0f} m {w.bearing} (outside the footprint)"
        )
    if crithab:
        constraints.append(f"designated critical habitat for the {crithab[0].common_name}")
    elif listed:
        constraints.append(f"{len(listed)} ESA-listed species on the IPaC screen (no designated critical habitat)")
    if inside_conservation:
        constraints.append(f"a footprint overlap with {inside_conservation[0].name} (protected land)")

    if constraints:
        constraint_clause = "Live datasets show " + "; and ".join(constraints) + "."
    else:
        constraint_clause = "The live datasets that responded show no footprint conflict."

    veg_crossing = [w for w in crossing if _is_vegetated(w.classification)]
    overall = (
        "an elevated permitting risk profile" if veg_crossing or crithab or inside_conservation
        else "a moderate, designable-around risk profile" if (crossing or gis.wetlands or listed)
        else "a low permitting risk profile"
    )
    live = [LAYER_LABELS[k] for k in LAYER_LABELS if getattr(prov, k) == "live"]
    missing = [LAYER_LABELS[k] for k in prov.unavailable_layers()]
    data_clause = f" Findings are drawn from live queries for these exact coordinates against {', '.join(live)}."
    if missing:
        data_clause += (
            f" The {', '.join(missing)} service(s) did not respond, so those constraints were NOT "
            "assessed and the overall profile may understate risk."
        )
    return (
        f"The proposed {acreage} {gis.site.project_type} project, located "
        f"{location}, presents {overall}. {constraint_clause}{nepa_line}{data_clause} A field wetland "
        "delineation and species survey should confirm the desktop record before permitting."
    )


async def run(gis: GISPayload, geo: dict[str, Any]) -> dict[str, Any]:
    sections, alternatives, used_ids = build_sections(gis, geo)
    summary = _fallback_summary(gis, sections)

    jur = gis.site.jurisdiction
    prov = gis.provenance
    state_line = (
        f"{jur.state} ({jur.county or 'county unknown'}) — verified"
        if jur.verified and jur.state
        else "UNVERIFIED — do not cite any state law"
    )
    result = await llm.complete_json(
        SYSTEM,
        f"State: {state_line}\n"
        f"Data layers not assessed (service unavailable): {', '.join(prov.unavailable_layers()) or 'none'}\n"
        f"Spatial analysis: {geo['summary']}\n\nObservations: {geo['observations']}\n\n"
        f"Section conclusions: {[(s.id, s.risk, s.summary) for s in sections]}",
    )
    # Never let a model-written summary replace the simulated-data warning.
    if (
        not prov.any_simulated
        and result
        and isinstance(result.get("executive_summary"), str)
        and len(result["executive_summary"]) > 100
    ):
        summary = result["executive_summary"]
        missing = [LAYER_LABELS[k] for k in prov.unavailable_layers()]
        if missing:
            summary += f" Note: the {', '.join(missing)} layer(s) were unavailable at run time and are not assessed."

    return {
        "executive_summary": summary,
        "sections": [s.model_dump() for s in sections],
        "alternatives": [a.model_dump() for a in alternatives],
        "citations": [CITATIONS[cid].model_dump() for cid in used_ids],
    }
