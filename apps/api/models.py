"""Pydantic schemas shared across the ingestion + agent pipeline.

These mirror the TypeScript types in apps/web/lib/types.ts — keep in sync.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ProjectType = Literal["solar", "wind", "transmission"]
RiskLevel = Literal["high", "moderate", "low"]


class SiteInput(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    project_type: ProjectType = "solar"
    name: Optional[str] = None


class Jurisdiction(BaseModel):
    """Resolved real-world jurisdiction for the site coordinates."""
    state: Optional[str] = None          # e.g. "New Jersey"
    state_code: Optional[str] = None     # e.g. "NJ"
    county: Optional[str] = None
    locality: Optional[str] = None       # town/city
    country_code: Optional[str] = None
    verified: bool = False               # cross-checked against web sources
    method: str = "unresolved"           # nominatim+tavily | nominatim | bbox-fallback | unresolved
    sources: list[dict[str, str]] = []   # {title, url} used for verification


class LandStatus(BaseModel):
    """Result of the Land Status Gate — ownership + physical buildability."""
    developable: bool = True
    category: str = "developable"        # developable | federal_protected | urban_built | open_water
    owner_type: Optional[str] = None     # e.g. "Federal"
    manager: Optional[str] = None        # e.g. "National Park Service"
    manager_code: Optional[str] = None   # e.g. "NPS"
    unit_name: Optional[str] = None      # e.g. "Grand Canyon National Park"
    designation: Optional[str] = None    # e.g. "National Park"
    gap_status: str = ""                 # PAD-US GAP status code (1-4)
    # Land-cover / buildability check (NLCD grid sample over the footprint)
    land_cover_checked: bool = False
    dominant_cover: Optional[str] = None     # e.g. "Developed, High Intensity"
    dominant_cover_class: Optional[int] = None  # NLCD class code, e.g. 24
    developed_fraction: Optional[float] = None  # share of samples in classes 21-24
    high_intensity_fraction: Optional[float] = None  # share in classes 23-24
    water_fraction: Optional[float] = None      # share in class 11
    verified: bool = False
    method: str = "unverified"           # padus+nlcd | padus | nlcd | offline-bbox | unverified
    sources: list[dict[str, str]] = []


class Site(BaseModel):
    lat: float
    lon: float
    project_type: ProjectType
    name: str
    acreage: float
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
    state_class: Optional[str] = None  # e.g. "NYS Class I"
    geometry: dict[str, Any]
    name_verified: bool = False        # name confirmed against real-world sources
    crosses_footprint: bool = False    # polygon within the project footprint half-width
    source: str = "USFWS National Wetlands Inventory"


class Habitat(BaseModel):
    id: str
    species: str                 # scientific name
    common_name: str
    status: str                  # "Endangered" | "Threatened" | proposed/candidate label
    unit_name: str
    distance_m: Optional[float] = None   # only when a mapped critical-habitat polygon exists
    bearing: Optional[str] = None
    geometry: Optional[dict[str, Any]] = None
    basis: str = "ipac_species_list"     # ipac_species_list | critical_habitat
    currently_listed: bool = True        # False for proposed/candidate species
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
    source: str = "USGS Protected Areas Database (PAD-US)"


class FloodZone(BaseModel):
    id: str
    zone: str                    # e.g. "AE"
    description: str
    distance_m: float
    geometry: dict[str, Any]
    source: str = "FEMA National Flood Hazard Layer"


class DataProvenance(BaseModel):
    """Per-layer record of whether real live data backed each section."""
    wetlands: str = "unavailable"    # live | unavailable | simulated
    species: str = "unavailable"
    flood: str = "unavailable"
    protected: str = "unavailable"

    @property
    def any_live(self) -> bool:
        return any(v == "live" for v in (self.wetlands, self.species, self.flood, self.protected))

    @property
    def any_simulated(self) -> bool:
        return any(v == "simulated" for v in (self.wetlands, self.species, self.flood, self.protected))


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
    feature_id: Optional[str] = None


class ReportSection(BaseModel):
    id: str
    title: str
    risk: Literal["high", "moderate", "low", "none"]
    summary: str
    findings: list[Finding]
    citation_ids: list[str] = []


class Alternative(BaseModel):
    id: str
    title: str
    description: str
    impact_reduction: str
    geometry: Optional[dict[str, Any]] = None  # GeoJSON LineString or Polygon


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
