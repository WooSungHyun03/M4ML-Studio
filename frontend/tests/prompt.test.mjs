import test from "node:test";
import assert from "node:assert/strict";
import { isLatestPrompt } from "../src/promptRevision.ts";
test("five delayed responses cannot replace latest prompt across frame/session/project changes", () => {
  const current = {
    project_id: "project",
    frame_id: "image-2",
    session_id: "new-session",
    revision: 6,
  };
  for (let revision = 1; revision < 6; revision++)
    assert.equal(isLatestPrompt(current, { ...current, revision }), false);
  assert.equal(
    isLatestPrompt(current, { ...current, session_id: "old-session" }),
    false,
  );
  assert.equal(
    isLatestPrompt(current, { ...current, frame_id: "image-1" }),
    false,
  );
  assert.equal(
    isLatestPrompt(current, { ...current, project_id: "other-project" }),
    false,
  );
  assert.equal(isLatestPrompt(current, { ...current }), true);
});

import { restorePromptPoints } from "../src/promptRevision.ts";
test("legacy empty session cannot blank the UI and exact failed input survives reopening", () => {
  assert.deepEqual(
    restorePromptPoints(
      "one",
      { reference: "one" },
      {
        reference: "one",
        points: [
          [1, 2],
          [4, 5],
        ],
        labels: [1, 0],
      },
    ),
    [
      { x: 1, y: 2, label: 1 },
      { x: 4, y: 5, label: 0 },
    ],
  );
  assert.deepEqual(
    restorePromptPoints("one", {
      reference: "one",
      points: [[3, 4]],
      labels: [0],
    }),
    [{ x: 3, y: 4, label: 0 }],
  );
  assert.deepEqual(
    restorePromptPoints("two", {
      reference: "one",
      points: [[3, 4]],
      labels: [0],
    }),
    [],
  );
  assert.deepEqual(restorePromptPoints("one", { reference: "one" }), []);
});
