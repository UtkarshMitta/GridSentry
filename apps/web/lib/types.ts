// Mirrors apps/api/models.py — keep in sync.

export type ProjectType = "solar" | "wind" | "transmission";
export type RiskLevel = "high" | "moderate" | "low";
export type Severity = "high" | "moderate" | "low" | "info";

export interface GeoJSONGeometry {
  type: string;
  coordinates: unknown;
}

export interface Jurisdiction {
  state: string | null;
  state_code: string | null;
  county: string | null;
  locality: string | null;
  country_code: string | null;
  verified: boolean;
  method: string;
  sources: { title: string; url: string }[];
}

export interface LandStatus {
  developable: boolean;
  category: string; // developable | federal_protected | urban_built | open_water
  owner_type: string | null;
  manager: string | null;
  manager_code: string | null;
  unit_name: string | null;
  designation: string | null;
  land_cover_checked: boolean;
  dominant_cover: string | null;
  dominant_cover_class: number | null;
  developed_fraction: number | null;
  high_intensity_fraction: number | null;
  water_fraction: number | null;
  gap_status: string;
  verified: boolean;
  method: string;
  sources: { title: string; url: string }[];
}

export interface Site {
  lat: number;
  lon: number;
  project_type: ProjectType;
  name: string;
  acreage: number;
  footprint: GeoJSONGeometry;
  jurisdiction: Jurisdiction;
  land_status: LandStatus;
}

export interface Wetland {
  id: string;
  name: string;
  classification: string;
  wetland_type: string;
  distance_m: number;
  bearing: string;
  area_acres: number;
  state_protected: boolean;
  state_class: string | null;
  geometry: GeoJSONGeometry;
  name_verified: boolean;
  crosses_footprint: boolean;
  source: string;
}

export interface Habitat {
  id: string;
  species: string;
  common_name: string;
  status: string;
  unit_name: string;
  distance_m: number | null;
  bearing: string | null;
  geometry: GeoJSONGeometry | null;
  basis: string; // ipac_species_list | critical_habitat
  currently_listed: boolean;
  source: string;
}

export interface ProtectedLand {
  id: string;
  name: string;
  designation: string;
  manager: string;
  distance_m: number;
  bearing: string;
  geometry: GeoJSONGeometry;
  name_verified: boolean;
  source: string;
}

export interface FloodZone {
  id: string;
  zone: string;
  description: string;
  distance_m: number;
  geometry: GeoJSONGeometry;
  source: string;
}

export interface DataProvenance {
  wetlands: string; // live | unavailable | simulated
  species: string;
  flood: string;
  protected: string;
}

export interface GISPayload {
  site: Site;
  wetlands: Wetland[];
  habitats: Habitat[];
  protected_lands: ProtectedLand[];
  flood_zones: FloodZone[];
  sources: string[];
  provenance: DataProvenance;
}

export interface Citation {
  id: string;
  label: string;
  title: string;
  source: string;
  url: string;
  excerpt: string;
}

export interface Finding {
  id: string;
  title: string;
  severity: Severity;
  detail: string;
  citation_ids: string[];
  feature_id: string | null;
}

export interface ReportSection {
  id: string;
  title: string;
  risk: "high" | "moderate" | "low" | "none";
  summary: string;
  findings: Finding[];
  citation_ids: string[];
}

export interface Alternative {
  id: string;
  title: string;
  description: string;
  impact_reduction: string;
  geometry: GeoJSONGeometry | null;
}

export interface CriticNote {
  id: string;
  severity: "blocker" | "warning" | "info";
  target: string;
  note: string;
}

export interface StopWorkRisk {
  id: string;
  title: string;
  detail: string;
  trigger: string;
  citation_ids: string[];
}

export interface Report {
  run_id: string;
  developable: boolean;
  verdict: "assessed" | "not_viable";
  risk_level: RiskLevel;
  risk_score: number;
  confidence: number;
  land_status: LandStatus;
  executive_summary: string;
  sections: ReportSection[];
  stop_work_risks: StopWorkRisk[];
  alternatives: Alternative[];
  critic_notes: CriticNote[];
  citations: Citation[];
  generated_at: string;
  engine: string;
}

export interface Run {
  id: string;
  created_at: string;
  name: string;
  lat: number;
  lon: number;
  project_type: ProjectType;
  status: "running" | "complete" | "error";
  gis: GISPayload | null;
  report: Report | null;
}

export type AgentId = "system" | "geolocation" | "legal" | "critic";

export interface PipelineEvent {
  type: "status" | "gis" | "complete" | "error";
  agent?: AgentId;
  state?: "start" | "thinking" | "done";
  message?: string;
  progress?: number;
  ts?: string;
}
