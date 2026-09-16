// Run with: npm test --workspace apps/web
import assert from "node:assert/strict";
import { test } from "node:test";
import { riskHeadline, unassessedLayers } from "./report.ts";
import type { Run } from "./types.ts";

function run(risk_level: "high" | "moderate" | "low", provenance: Record<string, string>): Run {
  return {
    gis: { provenance },
    report: { risk_level, risk_score: risk_level === "high" ? 80 : 8 },
  } as unknown as Run;
}
const live = { wetlands: "live", species: "live", flood: "live", protected: "live" };

test("complete data shows the score", () => {
  assert.deepEqual(riskHeadline(run("low", live)), { text: "low risk · 8/100", incomplete: false });
});

test("a missing layer never shows a clean LOW score", () => {
  const h = riskHeadline(run("low", { ...live, species: "unavailable" }));
  assert.equal(h.incomplete, true);
  assert.match(h.text, /risk not scored \(IPaC not assessed\)/);
});

test("a HIGH found in live data still stands, flagged incomplete", () => {
  const h = riskHeadline(run("high", { ...live, flood: "unavailable" }));
  assert.equal(h.incomplete, false);
  assert.equal(h.text, "high risk · 80/100 · incomplete data");
});

test("gated runs (not_assessed) are not 'unavailable'", () => {
  const na = { wetlands: "not_assessed", species: "not_assessed", flood: "not_assessed", protected: "not_assessed" };
  assert.deepEqual(unassessedLayers(run("high", na)), []);
});
