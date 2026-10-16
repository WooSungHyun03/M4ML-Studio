import test from "node:test";
import assert from "node:assert/strict";
import { formatIterations } from "../src/format.ts";

test("short training and loss-axis labels preserve meaningful iteration values", () => {
  assert.deepEqual([0, 25, 50, 75, 100].map(formatIterations), ["0", "25", "50", "75", "100"]);
  assert.deepEqual([1000, 2500, 30000].map(formatIterations), ["1k", "2.5k", "30k"]);
});
