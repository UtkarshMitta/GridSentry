"""Pydantic schemas shared across the ingestion + agent pipeline.

These mirror the TypeScript types in apps/web/lib/types.ts — keep in sync.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProjectType = Literal["solar", "wind", "transmission"]
RiskLevel = Literal["high", "moderate", "low"]
RunStatus = Literal["running", "complete", "error"]


class SiteInput(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    project_type: ProjectType = "solar"
    name: str | None = None
    # Proposed project footprint in acres. Optional: when omitted a fixed,
    # clearly-labelled default is assumed (never a per-coordinate guess).
    acreage: float | None = Field(default=None, ge=1, le=50_000)


class Jurisdiction(BaseModel):
    """Resolved real-world jurisdiction for the site coordinates."""
    state: str | None = None          # e.g. "New Jersey"
    state_code: str | None = None     # e.g. "NJ"
    county: str | None = None
    locality: str | None = None       # town/city
    country_code: str | None = None
    verified: bool = False               # cross-checked against web sources
    method: str = "unresolved"           # nominatim+census[+tavily] | census | nominatim | conflict | bbox-fallback | unresolved
    # True: inside a U.S. state/territory (datasets apply). False: positively
    # outside (foreign country / open ocean). None: lookups failed, unknown.
    in_coverage: bool | None = None
    sources: list[dict[str, str]] = []   # {title, url} used for verification


class LandStatus(BaseModel):
    """Result of the Land Status Gate — ownership + physical buildability."""
    developable: bool = True
    category: str = "developable"        # developable | federal_protected | urban_built | open_water | outside_coverage
    owner_type: str | None = None     # e.g. "Federal"
    manager: str | None = None        # e.g. "National Park Service"
    manager_code: str | None = None   # e.g. "NPS"
    unit_name: str | None = None      # e.g. "Grand Canyon National Park"
    designation: str | None = None    # e.g. "National Park"
    designation_code: str | None = None  # PAD-US Des_Tp code, e.g. "NP", "WA"
    gap_status: str = ""                 # PAD-US GAP status code (1-4)
    # Land-cover / buildability check (NLCD grid sample over the footprint)
    land_cover_checked: bool = False
    dominant_cover: str | None = None     # e.g. "Developed, High Intensity"
    dominant_cover_class: int | None = None  # NLCD class code, e.g. 24
    developed_fraction: float | None = None  # share of samples in classes 21-24
    high_intensity_fraction: float | None = None  # share in classes 23-24
    water_fraction: float | None = None      # share in class 11
    verified: bool = False
    method: str = "unverified"           # padus+nlcd | padus | nlcd | offline-bbox | unverified
    sources: list[dict[str, str]] = []


class Site(BaseModel):
    lat: float
    lon: float
    project_type: ProjectType
    name: str
    acreage: float
    acreage_assumed: bool = False  # True when the caller gave no acreage and a default was used
    footprint: dict[str, Any]  # GeoJSON Polygon
    jurisdiction: Jurisdiction = Jurisdiction()
    land_status: LandStatus = LandStatus()


class Wetland(BaseModel):
    id: str
    name: str
    classification: str          # NWI code, e.g. PEM1E
    wetland_type: str            # human-readable, e.g. "Freshwater Emergent Wetland"
    distance_m: float
    bearing: str                 # compass, e.g. "E"
    area_acres: float
    state_protected: bool
    state_class: str | None = None  # e.g. "NYS Class I"
    geometry: dict[str, Any]
    name_verified: bool = False        # name confirmed against real-world sources
    crosses_footprint: bool = False    # polygon intersects the project footprint square
    source: str = "USFWS National Wetlands Inventory"


class Habitat(BaseModel):
    id: str
    species: str                 # scientific name
    common_name: str
    status: str                  # "Endangered" | "Threatened" | proposed/candidate label
    unit_name: str
    basis: str = "ipac_species_list"     # ipac_species_list | critical_habitat | proposed_critical_habitat
    currently_listed: bool = True        # False for proposed/candidate/non-§7 taxa (e.g. NEP, SAT)
    source: str = "USFWS Critical Habitat (ECOS)"


class ProtectedLand(BaseModel):
    id: str
    name: str
    designation: str
    manager: str
    distance_m: float
    bearing: str
    geometry: dict[str, Any]
    name_verified: bool = False
    designation_code: str | None = None  # PAD-US Des_Tp
    gap_status: str = ""                    # PAD-US GAP 1-4 (1-2 = managed for biodiversity)
    overlaps_footprint: bool = False
    source: str = "USGS Protected Areas Database (PAD-US)"


class FloodZone(BaseModel):
    id: str
    zone: str                    # e.g. "AE"
    description: str
    distance_m: float
    geometry: dict[str, Any]
    sfha: bool = False                 # Special Flood Hazard Area (1% annual chance, A*/V* zones)
    overlaps_footprint: bool = False
    source: str = "FEMA National Flood Hazard Layer"


class DataProvenance(BaseModel):
    """Per-layer record of whether real live data backed each section."""
    wetlands: str = "unavailable"    # live | unavailable | simulated | not_assessed
    species: str = "unavailable"
    flood: str = "unavailable"
    protected: str = "unavailable"

    @property
    def any_live(self) -> bool:
        return any(v == "live" for v in (self.wetlands, self.species, self.flood, self.protected))

    @property
    def any_simulated(self) -> bool:
        return any(v == "simulated" for v in (self.wetlands, self.species, self.flood, self.protected))

    def unavailable_layers(self) -> list[str]:
        return [k for k in ("wetlands", "species", "flood", "protected") if getattr(self, k) == "unavailable"]


class GISPayload(BaseModel):
    site: Site
    wetlands: list[Wetland]
    habitats: list[Habitat]
    protected_lands: list[ProtectedLand]
    flood_zones: list[FloodZone]
    sources: list[str]
    provenance: DataProvenance = DataProvenance()


class Citation(BaseModel):
    id: str
    label: str                   # short badge label, e.g. "33 CFR § 328.3"
    title: str
    source: str
    url: str
    excerpt: str


class Finding(BaseModel):
    id: str
    title: str
    severity: Literal["high", "moderate", "low", "info"]
    detail: str
    citation_ids: list[str] = []
    feature_id: str | None = None


class ReportSection(BaseModel):
    id: str
    title: str
    risk: Literal["high", "moderate", "low", "none", "unknown"]  # unknown = data unavailable
    summary: str
    findings: list[Finding]
    citation_ids: list[str] = []


class Alternative(BaseModel):
    id: str
    title: str
    description: str
    impact_reduction: str


class CriticNote(BaseModel):
    id: str
    severity: Literal["blocker", "warning", "info"]
    target: str                  # section id or "report"
    note: str


class StopWorkRisk(BaseModel):
    id: str
    title: str
    detail: str
    trigger: str
    citation_ids: list[str] = []


class Report(BaseModel):
    run_id: str
    developable: bool = True     # False when Land Status Gate blocks the site
    verdict: str = "assessed"    # "assessed" | "not_viable"
    risk_level: RiskLevel
    risk_score: int              # 0-100 (100 = infeasible when not developable)
    confidence: int              # 0-100, set by critic
    land_status: LandStatus = LandStatus()
    executive_summary: str
    sections: list[ReportSection]
    stop_work_risks: list[StopWorkRisk]
    alternatives: list[Alternative]
    critic_notes: list[CriticNote]
    citations: list[Citation]
    generated_at: str
    engine: str                  # "openai" | "anthropic" | "deterministic"


class PipelineEvent(BaseModel):
    """One progress event from the agent pipeline (SSE payload)."""
    type: str                              # status | gis | complete | error
    agent: str | None = None            # system | geolocation | legal | critic
    state: str | None = None            # start | thinking | done
    message: str | None = None
    progress: float | None = None       # 0-1
    ts: str | None = None


class RunCreated(BaseModel):
    run_id: str


class RunBase(BaseModel):
    """Fields every run carries, with or without its payloads."""
    id: str
    created_at: str
    name: str
    lat: float
    lon: float
    project_type: ProjectType
    status: RunStatus


class RunSummary(RunBase):
    """A row of run history: the verdict at a glance, no payloads."""
    verdict: str | None = None            # assessed | not_viable (None until complete)
    risk_level: RiskLevel | None = None   # None until the run completes
    risk_score: int | None = None


class RunDetail(RunBase):
    """A full run: the GIS payload, the report, and the events it emitted.
    The verdict and risk live on `report` — never duplicated here."""
    gis: GISPayload | None = None
    report: Report | None = None
    events: list[PipelineEvent] = []


class Health(BaseModel):
    status: str
    engine: str          # openai | anthropic | deterministic (configured engine)
    version: str
