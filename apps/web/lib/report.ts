import type { CriticNote, Report, Run } from "./types";

const SEVERITY_ORDER = { blocker: 0, warning: 1, info: 2 } as const;

/** Critic notes aimed at the whole report (or a section that isn't rendered). */
export function reportLevelNotes(report: Report): CriticNote[] {
  const sectionIds = new Set(report.sections.map((s) => s.id));
  return report.critic_notes
    .filter((n) => !sectionIds.has(n.target))
    .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
}

/** True when the report was built on synthetic placeholder features. */
export function isSimulated(run: Run): boolean {
  const p = run.gis?.provenance;
  return !!p && Object.values(p).includes("simulated");
}

/** Environmental layers whose live service did not answer on this run. */
export function unassessedLayers(run: Run): string[] {
  const p = run.gis?.provenance;
  if (!p) return [];
  const labels = { wetlands: "NWI", species: "IPaC", flood: "FEMA", protected: "PAD-US" } as const;
  return (Object.keys(labels) as (keyof typeof labels)[])
    .filter((k) => p[k] === "unavailable")
    .map((k) => labels[k]);
}

/**
 * Headline risk text. With layers missing, a LOW/MODERATE score only reflects
 * the data that answered, so it is not shown as a clean verdict; a HIGH still
 * stands because the constraint was found in live data.
 */
export function riskHeadline(run: Run): { text: string; incomplete: boolean } {
  const r = run.report!;
  const missing = unassessedLayers(run);
  if (missing.length && r.risk_level !== "high") {
    return { text: `Incomplete data · risk not scored (${missing.join(", ")} not assessed)`, incomplete: true };
  }
  const base = `${r.risk_level} risk · ${r.risk_score}/100`;
  return { text: missing.length ? `${base} · incomplete data` : base, incomplete: false };
}

/** Short label for a Land Status Gate verdict. */
export function verdictLabel(category: string): string {
  switch (category) {
    case "urban_built":
      return "no buildable land";
    case "open_water":
      return "open water";
    case "outside_coverage":
      return "outside U.S. coverage";
    default:
      return "federal land";
  }
}
