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
        Citation(
            id="ceq-1501",
            label="40 CFR § 1501.3",
            title="CEQ Regulations — Determining the appropriate level of NEPA review",
            source="Council on Environmental Quality",
            url="https://www.ecfr.gov/current/title-40/chapter-V/subchapter-A/part-1501/section-1501.3",
            excerpt="Agencies assess whether effects are significant, considering affected environment and degree of effects, to select CE, EA, or EIS.",
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
            url="https://www.nj.gov/dep/landuse/fww.html",
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
            id="nps-101905",
            label="54 U.S.C. § 101905",
            title="NPS rights-of-way / commercial use limits",
            source="Title 54, U.S. Code",
            url="https://www.law.cornell.edu/uscode/text/54/101905",
            excerpt="Rights-of-way and commercial uses within National Park System units are tightly constrained and generally incompatible with utility-scale energy generation.",
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

# Which citations apply to each barring federal designation.
FEDERAL_LAND_CITES: dict[str, list[str]] = {
    "National Park": ["nps-organic", "nps-101905", "nepa-4332"],
    "Wilderness Area": ["wilderness-act", "nps-organic", "nepa-4332"],
    "Wilderness Study / Proposed Wilderness Area": ["wilderness-act", "flpma", "nepa-4332"],
    "National Monument": ["antiquities", "flpma", "nepa-4332"],
    "National Wildlife Refuge": ["nwrs-improvement", "nepa-4332"],
    "National Recreation Area": ["flpma", "nepa-4332"],
    "National Seashore": ["nps-organic", "nepa-4332"],
    "National Conservation Area": ["flpma", "nepa-4332"],
    "Wild & Scenic River corridor": ["flpma", "nepa-4332"],
    "Research Natural Area": ["flpma", "nepa-4332"],
}


def build_infeasible(gis: GISPayload) -> dict[str, Any]:
    """Report content for a site the Land Status Gate marks non-developable."""
    ls = gis.site.land_status
    if ls.category in ("urban_built", "open_water"):
        return _build_unbuildable(gis)
    unit = ls.unit_name or "a federal protected area"
    desig = ls.designation or "protected federal land"
    manager = ls.manager or "a federal land-management agency"
    cite_ids = FEDERAL_LAND_CITES.get(desig, ["nps-organic", "nepa-4332"])
    verify_clause = (
        "confirmed against the USGS Protected Areas Database (PAD-US)"
        if ls.verified
        else "flagged from an offline reference set (not independently confirmed — verify against PAD-US before relying on this)"
    )

    summary = (
        f"THRESHOLD FINDING — SITE NOT VIABLE. The proposed coordinates fall inside "
        f"{unit}, a {desig} managed by the {manager}, {verify_clause}. This is the "
        "controlling fact for the site and supersedes any wetland, species, or floodplain "
        f"analysis: utility-scale {gis.site.project_type} development inside this unit is "
        "categorically barred or requires a special act of Congress, not an environmental "
        "permit. GridSentry does not proceed to the standard impact assessment for a site "
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
    cite_ids = ["ceq-1501", "nepa-4332"]
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


SYSTEM = """You are the Legal Compliance Officer on an environmental permitting team.
Given spatial observations for a proposed energy project, return JSON:
{"executive_summary": "<4-5 sentences, professional EIS-draft register>"}
Reference the specific regulations implicated (NEPA, CWA 404, ESA 7, state wetland law).
Only cite the state regulations for the state provided — never another state's."""

# State wetland regimes, keyed by resolved USPS state code (from the
# grounding step — never inferred from coordinates here).
STATE_REGIMES: dict[str, dict[str, object]] = {
    "NY": {
        "citations": ["nycrr-663", "ecl-24"],
        "buffer": "regulated 100-ft adjacent area",
        "permit": "an Article 24 Freshwater Wetlands permit from NYS DEC",
        "standard": "Class I wetlands carry the most stringent 'compatibility' standard and permits are rarely granted for avoidable encroachments",
    },
    "NJ": {
        "citations": ["njsa-13-9b", "njac-77a"],
        "buffer": "regulated transition area (up to 150 ft for Exceptional Resource Value wetlands)",
        "permit": "an FWPA individual permit and transition-area waiver from NJDEP — note NJDEP administers the federal § 404 program in-state under assumed authority",
        "standard": "Exceptional Resource Value wetlands carry the largest transition areas and the most demanding avoidance/minimization showing",
    },
}
GENERIC_REGIME: dict[str, object] = {
    "citations": ["eo-11990"],
    "buffer": "any state-regulated buffer or adjacent area",
    "permit": "the applicable state wetland permit (program unverified — confirm with the state environmental agency)",
    "standard": "federal actions affecting wetlands additionally trigger avoidance obligations under E.O. 11990",
}


def _regime(gis: GISPayload) -> dict[str, object]:
    code = gis.site.jurisdiction.state_code
    return STATE_REGIMES.get(code or "", GENERIC_REGIME)


VEGETATED_PREFIXES = ("PEM", "PFO", "PSS", "EEM", "E2EM", "PAB")


def _is_vegetated(classification: str) -> bool:
    """Vegetated (marsh/forested/scrub) wetlands are higher permitting value than
    open-water/excavated ponds (PUB*/PABx)."""
    code = (classification or "").upper()
    return any(code.startswith(p) for p in VEGETATED_PREFIXES)


def _jurisdiction_label(jur) -> str:
    parts: list[str] = []
    for p in (jur.county, jur.state):
        if p and p not in parts:
            parts.append(p)
    return ", ".join(parts) if parts else "an unresolved jurisdiction"


def build_sections(gis: GISPayload, geo: dict[str, Any]) -> tuple[list[ReportSection], list[Alternative], list[str]]:
    """Data-driven section construction from live features.

    Every section is conditional on real returned data. When a layer is empty
    (a genuinely clean site) the section says so instead of manufacturing a
    constraint. Distances, crossings, and risk come from the actual geometry.
    """
    regime = _regime(gis)
    jur = gis.site.jurisdiction
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

    jurisdiction_label = _jurisdiction_label(jur)
    unverified_clause = "" if jur.verified else " (jurisdiction unverified — confirm before relying on state citations)"

    # Partition wetlands into those the footprint overlaps vs merely nearby.
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    nearby = [w for w in gis.wetlands if not w.crosses_footprint]
    state_cites: list[str] = list(regime["citations"])  # type: ignore[arg-type]
    # Vegetated wetlands (marsh/forested/scrub) are higher-value and harder to
    # permit than open-water/excavated ponds; a footprint conflict with the
    # former is HIGH, with only the latter it is MODERATE (designable-around).
    veg_crossing = [w for w in crossing if _is_vegetated(w.classification)]

    # -- Wetlands section (only if NWI returned polygons) --
    wetland_risk = "none"
    if gis.wetlands:
        head = crossing[0] if crossing else gis.wetlands[0]
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
                        severity="high",
                        detail=(
                            f"{obs_note(w.id)} The mapped polygon lies inside the {gis.site.acreage}-acre "
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
            summary = (
                f"USFWS NWI mapping places {len(crossing)} wetland "
                f"{'polygon' if len(crossing) == 1 else 'polygons'} inside the project footprint "
                f"(nearest {head.wetland_type}, {head.classification}). This is the controlling "
                "permitting constraint for the current layout."
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

    # -- Species section (only if IPaC returned listed/proposed species) --
    listed = [h for h in gis.habitats if h.currently_listed]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    proposed = [h for h in gis.habitats if not h.currently_listed]
    species_risk = "none"
    if gis.habitats:
        sp_findings: list[Finding] = []
        if crithab:
            species_risk = "high"
            for i, h in enumerate(crithab, start=1):
                where = (
                    f"{h.distance_m / 1000:.1f} km {h.bearing}" if h.distance_m is not None else "at the location"
                )
                sp_findings.append(
                    Finding(
                        id=f"f-sp-ch{i}",
                        title=f"Designated critical habitat — {h.common_name}",
                        severity="high",
                        detail=(
                            f"IPaC reports designated critical habitat for the {h.common_name} "
                            f"({h.species}, {h.status}) overlapping the location ({where}). A federal "
                            "nexus makes formal ESA § 7 consultation likely; destruction/adverse "
                            "modification of critical habitat is the controlling standard."
                        ),
                        citation_ids=cite("esa-7", "cfr-402"),
                        feature_id=h.id,
                    )
                )
        if listed:
            if species_risk != "high":
                species_risk = "moderate"
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
                        "presence/absence surveys scheduled in the appropriate season. Absent "
                        "designated critical habitat here, effects are usually manageable through "
                        "seasonal restrictions and standard conservation measures."
                    ),
                    citation_ids=cite("esa-7", "cfr-402"),
                )
            )
        if proposed:
            names = ", ".join(f"{h.common_name} ({h.status})" for h in proposed[:6])
            sp_findings.append(
                Finding(
                    id="f-sp-prop",
                    title=f"Proposed/candidate species to monitor ({len(proposed)})",
                    severity="info",
                    detail=(
                        f"IPaC also flags proposed or candidate taxa: {names}. These carry no "
                        "current § 7 obligation but should be tracked, as a listing during "
                        "development would change the consultation posture."
                    ),
                    citation_ids=cite("esa-7"),
                )
            )
        sections.append(
            ReportSection(
                id="species",
                title="Threatened & Endangered Species",
                risk=species_risk,
                summary=(
                    f"The live IPaC query returned {len(listed)} ESA-listed and {len(proposed)} "
                    f"proposed/candidate species"
                    + (f", including designated critical habitat for {crithab[0].common_name}. "
                       "This elevates the section to a formal § 7 posture."
                       if crithab else
                       ". No designated critical habitat overlaps the site, so this is a species-screen "
                       "obligation rather than a habitat-destruction constraint.")
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

    # -- Protected lands (only if PAD-US returned nearby units) --
    if gis.protected_lands:
        pl_findings = []
        for i, p in enumerate(gis.protected_lands[:3], start=1):
            pl_findings.append(
                Finding(
                    id=f"f-pl-{i}",
                    title=f"{p.name} — {p.designation}",
                    severity="low",
                    detail=obs_note(p.id, f"{p.name} ({p.designation}, {p.manager}) is {p.distance_m/1000:.1f} km {p.bearing}."),
                    citation_ids=cite("ceq-1501"),
                    feature_id=p.id,
                )
            )
        nearest_p = gis.protected_lands[0]
        sections.append(
            ReportSection(
                id="protected-lands",
                title="Protected & Public Lands",
                risk="low",
                summary=(
                    f"PAD-US maps {len(gis.protected_lands)} managed/protected "
                    f"{'area' if len(gis.protected_lands) == 1 else 'areas'} within 5 km; nearest is "
                    f"{nearest_p.name} ({nearest_p.distance_m/1000:.1f} km {nearest_p.bearing}). "
                    "Relevant for cumulative-effects and viewshed analysis."
                ),
                findings=pl_findings,
                citation_ids=cite("ceq-1501"),
            )
        )

    # -- Floodplain (only if NFHL returned a real hazard zone) --
    flood_risk = "none"
    if gis.flood_zones:
        f = gis.flood_zones[0]
        inside = f.distance_m <= 1.0
        flood_risk = "moderate" if inside or f.distance_m < 300 else "low"
        sections.append(
            ReportSection(
                id="floodplain",
                title="Floodplain Management",
                risk=flood_risk,
                summary=(
                    f"FEMA NFHL maps Zone {f.zone} "
                    + ("intersecting the site" if inside else f"{f.distance_m:.0f} m away")
                    + ". Grading and collector-line routing must document floodplain avoidance where practicable."
                ),
                findings=[
                    Finding(
                        id="f-fl-1",
                        title=f"FEMA Zone {f.zone} {'at site' if inside else 'in vicinity'}",
                        severity=flood_risk,
                        detail=obs_note(f.id, f"FEMA Zone {f.zone}: {f.description}."),
                        citation_ids=cite("eo-11988"),
                        feature_id=f.id,
                    )
                ],
                citation_ids=cite("eo-11988"),
            )
        )

    # -- NEPA pathway (level derived from the real findings) --
    has_high = bool(veg_crossing) or species_risk == "high"
    has_mod = "moderate" in (wetland_risk, species_risk, flood_risk)
    if has_high:
        nepa_level = "Environmental Assessment (EA), targeting a mitigated FONSI"
        nepa_risk = "moderate"
        nepa_detail = (
            "A footprint wetland conflict and/or designated critical habitat means a Categorical "
            "Exclusion is not defensible. Prepare an EA under 40 CFR § 1501.3 with the record built "
            "to withstand an EIS-elevation challenge; early avoidance materially improves the FONSI."
        )
    elif has_mod:
        nepa_level = "Environmental Assessment (EA) or documented Categorical Exclusion"
        nepa_risk = "low"
        nepa_detail = (
            "Constraints are proximity-based rather than direct footprint conflicts. Depending on "
            "the lead agency's CE list and final delineation/survey results, a documented CE may be "
            "available; otherwise a short-form EA under 40 CFR § 1501.3 is appropriate."
        )
    else:
        nepa_level = "Categorical Exclusion (CE) likely available"
        nepa_risk = "low"
        nepa_detail = (
            "The live datasets show no wetland footprint conflict, no designated critical habitat, "
            "and no mapped flood hazard at the site. Subject to final field verification, this "
            "project profile is a strong candidate for a Categorical Exclusion under 40 CFR § 1501.4."
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
                    citation_ids=cite("nepa-4332", "ceq-1501"),
                )
            ],
            citation_ids=cite("nepa-4332", "ceq-1501"),
        )
    )

    # -- Alternatives only make sense when there's a footprint wetland to avoid --
    if crossing:
        head = crossing[0]
        alternatives = [
            Alternative(
                id="alt-1",
                title="Alternative A — Array setback from mapped wetland",
                description=(
                    f"Pull the array and access roads back to a ≥150 ft setback from the "
                    f"{head.wetland_type} polygon mapped inside the footprint ({head.distance_m:.0f} m "
                    f"{head.bearing} of centroid), keeping equipment out of the wetland and its buffer. "
                    "Recovers most nameplate capacity through minor block reconfiguration."
                ),
                impact_reduction="Removes the CWA § 404 footprint conflict; converts the wetlands section from HIGH toward LOW.",
                geometry=None,
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

    return sections, alternatives, sorted(used)


STATE_REG_LABELS = {
    "NY": "6 NYCRR Part 663 and ECL Article 24",
    "NJ": "the NJ Freshwater Wetlands Protection Act (N.J.S.A. 13:9B) and N.J.A.C. 7:7A",
}


def _fallback_summary(gis: GISPayload, sections: list[ReportSection]) -> str:
    jur = gis.site.jurisdiction
    location = (
        f"in {jur.locality + ', ' if jur.locality else ''}{_jurisdiction_label(jur)}"
        if jur.state
        else "in an unresolved jurisdiction (state law citations withheld pending verification)"
    )
    crossing = [w for w in gis.wetlands if w.crosses_footprint]
    crithab = [h for h in gis.habitats if h.basis == "critical_habitat"]
    listed = [h for h in gis.habitats if h.currently_listed]
    nepa = next((s for s in sections if s.id == "nepa-pathway"), None)
    nepa_line = f" {nepa.summary}" if nepa else ""

    # Build the constraint clause from what the live data actually returned.
    constraints: list[str] = []
    if crossing:
        w = crossing[0]
        constraints.append(
            f"{len(crossing)} NWI wetland "
            f"{'polygon' if len(crossing)==1 else 'polygons'} inside the project footprint "
            f"(nearest {w.wetland_type} at {w.distance_m:.0f} m {w.bearing})"
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

    if constraints:
        constraint_clause = "Live datasets show " + "; and ".join(constraints) + "."
    else:
        constraint_clause = (
            "Live USFWS NWI and IPaC queries returned no wetland footprint conflict and no "
            "ESA-listed critical habitat at this location."
        )

    veg_crossing = [w for w in crossing if _is_vegetated(w.classification)]
    overall = (
        "an elevated permitting risk profile" if veg_crossing or crithab
        else "a moderate, designable-around risk profile" if (crossing or gis.wetlands or listed)
        else "a low permitting risk profile"
    )
    return (
        f"The proposed {gis.site.acreage}-acre {gis.site.project_type} project, located "
        f"{location}, presents {overall}. {constraint_clause}{nepa_line} All findings are drawn "
        "from live queries against the cited federal datasets for these exact coordinates; a "
        "field wetland delineation and species survey should confirm the desktop record before permitting."
    )


async def run(gis: GISPayload, geo: dict[str, Any]) -> dict[str, Any]:
    sections, alternatives, used_ids = build_sections(gis, geo)
    summary = _fallback_summary(gis, sections)

    jur = gis.site.jurisdiction
    result = await llm.complete_json(
        SYSTEM,
        f"State (verified jurisdiction): {jur.state or 'UNKNOWN'} "
        f"({jur.county or 'county unknown'})\n"
        f"Spatial analysis: {geo['summary']}\n\nObservations: {geo['observations']}",
    )
    if result and isinstance(result.get("executive_summary"), str) and len(result["executive_summary"]) > 100:
        summary = result["executive_summary"]

    return {
        "executive_summary": summary,
        "sections": [s.model_dump() for s in sections],
        "alternatives": [a.model_dump() for a in alternatives],
        "citations": [CITATIONS[cid].model_dump() for cid in used_ids],
    }
