import type { ProjectType, Run, RunSummary } from "./types";

// Env var takes precedence; local dev uses the local API; deployed builds
// default to the hosted Render backend.
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://gridsentry-api.onrender.com");

export async function createRun(input: {
  lat: number;
  lon: number;
  project_type: ProjectType;
  name?: string;
  acreage?: number;
}): Promise<{ run_id: string }> {
  const res = await fetch(`${API_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`Failed to start analysis (${res.status})`);
  return res.json();
}

export async function listRuns(limit = 6, ids?: string[]): Promise<RunSummary[]> {
  const filter = ids ? `&ids=${encodeURIComponent(ids.join(","))}` : "";
  const res = await fetch(`${API_URL}/runs?limit=${limit}${filter}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Could not list runs (${res.status})`);
  return res.json();
}

export async function getRun(runId: string): Promise<Run> {
  const res = await fetch(`${API_URL}/runs/${runId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Run not found (${res.status})`);
  return res.json();
}

export function eventsUrl(runId: string): string {
  return `${API_URL}/runs/${runId}/events`;
}

const COORD_PART = String.raw`([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([NSEW])?`;
const COORD_RE = new RegExp(`^${COORD_PART}\\s*[,;\\s]\\s*${COORD_PART}$`, "i");

/**
 * Parse "lat, lon" in decimal degrees. Also accepts hemisphere suffixes
 * ("42.9°N, 74.3°W" — the sign comes from N/S/E/W, and a longitude-first
 * pair is swapped) and surrounding brackets. Returns null if invalid or
 * ambiguous (a minus sign *and* a hemisphere letter).
 */
export function parseCoordinates(raw: string): { lat: number; lon: number } | null {
  const match = raw.trim().replace(/^[([]\s*|\s*[)\]]$/g, "").match(COORD_RE);
  if (!match) return null;
  const parts = [
    { value: parseFloat(match[1]), hemi: match[2]?.toUpperCase(), signed: /^[+-]/.test(match[1]) },
    { value: parseFloat(match[3]), hemi: match[4]?.toUpperCase(), signed: /^[+-]/.test(match[3]) },
  ];
  if (parts.some((p) => p.hemi && p.signed)) return null;
  if (!!parts[0].hemi !== !!parts[1].hemi) return null; // "42.9N, -74.3" is ambiguous
  let [a, b] = parts;
  if (a.hemi && b.hemi) {
    const isLat = (h: string) => h === "N" || h === "S";
    if (isLat(a.hemi) === isLat(b.hemi)) return null; // both latitudes or both longitudes
    if (!isLat(a.hemi)) [a, b] = [b, a];
  }
  const lat = a.hemi === "S" ? -a.value : a.value;
  const lon = b.hemi === "W" ? -b.value : b.value;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}
