import type { ProjectType, Run } from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function createRun(input: {
  lat: number;
  lon: number;
  project_type: ProjectType;
  name?: string;
}): Promise<{ run_id: string }> {
  const res = await fetch(`${API_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`Failed to start analysis (${res.status})`);
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

/** Parse "lat, lon" in decimal degrees. Returns null if invalid. */
export function parseCoordinates(raw: string): { lat: number; lon: number } | null {
  const match = raw
    .trim()
    .match(/^(-?\d{1,2}(?:\.\d+)?)[,\s]+(-?\d{1,3}(?:\.\d+)?)$/);
  if (!match) return null;
  const lat = parseFloat(match[1]);
  const lon = parseFloat(match[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}
