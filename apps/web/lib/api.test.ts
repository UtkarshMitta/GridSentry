// Run with: npm test --workspace apps/web   (Node >= 22.18 strips TS types natively)
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCoordinates } from "./api.ts";

const ok: [string, number, number][] = [
  ["42.9, -74.3", 42.9, -74.3],
  ["42.9 -74.3", 42.9, -74.3],
  ["42.9,-74.3", 42.9, -74.3],
  ["  42.9000 , -74.3000  ", 42.9, -74.3],
  ["-33.86, 151.2", -33.86, 151.2],
  ["(42.9, -74.3)", 42.9, -74.3],
  ["[42.9, -74.3]", 42.9, -74.3],
  ["42.9°N, 74.3°W", 42.9, -74.3],
  ["42.9 N 74.3 W", 42.9, -74.3],
  ["74.3°W, 42.9°N", 42.9, -74.3], // longitude-first pair is swapped
  ["33.86°S, 151.2°E", -33.86, 151.2],
];

const rejected = [
  "", "abc", "42.9", "91, 0", "0, 181", "42.9,, -74.3",
  "42.9°N, -74.3",   // hemisphere on one value only: ambiguous
  "-42.9°N, 74.3°W", // minus sign and hemisphere together
  "42.9°N, 42.9°S",  // two latitudes
  "91°N, 74.3°W",
];

for (const [input, lat, lon] of ok) {
  test(`parses ${JSON.stringify(input)}`, () => {
    assert.deepEqual(parseCoordinates(input), { lat, lon });
  });
}

for (const input of rejected) {
  test(`rejects ${JSON.stringify(input)}`, () => {
    assert.equal(parseCoordinates(input), null);
  });
}
