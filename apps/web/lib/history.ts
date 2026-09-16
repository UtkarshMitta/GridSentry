import type { RunSummary } from "./types";

const KEY = "gridsentry.runs";
const MAX = 12;

/**
 * Run ids started in this browser. The hosted API serves one shared database,
 * so the UI lists only the visitor's own analyses rather than everyone's.
 * Stored client-side only; unavailable storage simply means no history.
 */
export function rememberRun(id: string): void {
  try {
    const ids = [id, ...recentRunIds().filter((existing) => existing !== id)].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    // private mode / storage disabled — history is a convenience, not a feature
  }
}

export function recentRunIds(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

/** Drop ids the API no longer knows (e.g. its database was reset). */
export function pruneRunIds(found: RunSummary[]): void {
  try {
    const alive = new Set(found.map((r) => r.id));
    localStorage.setItem(KEY, JSON.stringify(recentRunIds().filter((id) => alive.has(id))));
  } catch {
    /* ignore */
  }
}
