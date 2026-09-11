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
