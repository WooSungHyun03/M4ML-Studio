import test from "node:test";
import assert from "node:assert/strict";
import { screenToImage } from "../src/geometry.ts";
test("clicks map to physical pixels through fit, zoom and translated pan", () => {
  for (const zoom of [0.25, 0.5, 1, 1.3, 2, 8]) {
    const scale = 0.41 * zoom,
      rect = {
        left: -311.2,
        top: 87.5,
        width: 1009 * scale,
        height: 753 * scale,
      };
    const point = screenToImage(
      rect.left + 380.25 * scale,
      rect.top + 349.5 * scale,
      rect,
      1009,
      753,
    );
    assert.ok(Math.abs(point.x - 380.25) < 1e-9);
    assert.ok(Math.abs(point.y - 349.5) < 1e-9);
  }
});
test("out of bounds clips safely; invalid canvas is rejected", () => {
  assert.deepEqual(
    screenToImage(
      -2,
      300,
      { left: 0, top: 0, width: 100, height: 100 },
      200,
      200,
    ),
    { x: 0, y: 199 },
  );
  assert.throws(() =>
    screenToImage(0, 0, { left: 0, top: 0, width: 0, height: 1 }, 2, 2),
  );
});
