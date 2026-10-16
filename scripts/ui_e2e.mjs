// Real browser end-to-end run of the M4ML Studio UI (Playwright, real backend + GPU).
//   PW_DIR=<node_modules with playwright> CHROME=<chrome-headless-shell> \
//   node scripts/ui_e2e.mjs http://127.0.0.1:8767 <images-dir> <count> <out-dir>
// Every step uses visible UI controls only (buttons, file chooser, canvas clicks, keys).
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")("playwright");
const [url, imagesDir, count = "16", out = "evidence/ui-e2e"] = process.argv.slice(2);
const resumeProject = process.env.STUDIO_UI_PROJECT;
const resumeFromReview = process.env.STUDIO_UI_FROM === "review";
const testIterations = process.env.STUDIO_UI_ITERATIONS || "2000";
const testMeshRes = process.env.STUDIO_UI_MESH_RES || "512";
fs.mkdirSync(out, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 960 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("dialog", (d) => d.accept());
const shot = (n) => page.screenshot({ path: path.join(out, n + ".png") });
const result = { steps: [], test_iterations: Number(testIterations), test_mesh_res: Number(testMeshRes) };
const prompts = [];
page.on("request", (r) => {
  if (r.method() === "POST" && /\/prompt$/.test(r.url())) prompts.push(r.postDataJSON());
});
async function latestPreview(action) {
  const sent = page.waitForRequest((r) => r.method() === "POST" && /\/prompt$/.test(r.url()), { timeout: 30000 });
  await action();
  await sent;
  await page.waitForTimeout(250);
  const request = prompts.at(-1);
  await page.waitForResponse(async (r) => {
    if (r.request().method() !== "GET" || !/\/projects\/[^/]+$/.test(r.url())) return false;
    const p = await r.json().catch(() => ({}));
    return p.preview?.session_id === request.session_id && p.preview?.prompt_revision === request.prompt_revision;
  }, { timeout: 300000 });
  await page.getByText("최신 클릭 반영됨", { exact: true }).waitFor({ timeout: 30000 });
  return request;
}
const step = async (name, fn) => {
  const t = Date.now();
  await fn();
  result.steps.push({ name, seconds: (Date.now() - t) / 1000 });
  log("✓", name, ((Date.now() - t) / 1000).toFixed(1) + "s");
  await shot(String(result.steps.length).padStart(2, "0") + "-" + name);
};
const stageText = async () => (await page.locator(".statusbar").innerText()).replace(/\s+/g, " ");
async function waitFor(fn, timeoutMs, label) {
  const t = Date.now();
  while (Date.now() - t < timeoutMs) {
    if (await fn()) return;
    await page.waitForTimeout(1000);
  }
  throw new Error("timeout: " + label + " | " + (await stageText()));
}
try {
  await page.goto(resumeProject ? `${url}/?project=${encodeURIComponent(resumeProject)}` : url);
  if (!resumeProject) {
  await step("welcome", async () => {
    await page.getByText("새 프로젝트 시작").waitFor();
  });
  await step("create-project", async () => {
    await page.fill("#project-name", "UI E2E " + new Date().toISOString().slice(0, 16));
    await page.getByRole("button", { name: /프로젝트 만들기/ }).click();
    await page.getByText("이미지를 불러오세요").waitFor({ timeout: 60000 });
  });
  await step("upload-images", async () => {
    const files = fs.readdirSync(imagesDir).filter((f) => /\.(jpe?g|png)$/i.test(f)).sort().slice(0, +count).map((f) => path.join(imagesDir, f));
    await page.locator("input[type=file][accept*='image']").first().setInputFiles(files);
    await waitFor(async () => (await page.locator(".grid .cell").count()) >= files.length, 300000, "uploads");
  });
  await step("camera-registration", async () => {
    await page.getByRole("button", { name: /불러오기 완료/ }).click();
    await page.getByText("카메라 등록").first().waitFor({ timeout: 60000 });
    await waitFor(async () => (await page.getByRole("button", { name: /다음: 마스크 생성/ }).isEnabled()), 1800000, "camera");
    result.camera = await page.locator(".pipe").innerText();
  });
  } else {
    result.resumed_project = resumeProject;
    await step("resume-project", async () => {
      await page.locator(".nav button", { hasText: resumeFromReview ? "마스크 검토" : "마스크 생성" }).click();
    });
  }
  if (!resumeFromReview) {
  await step("select-object", async () => {
    if (!resumeProject) await page.getByRole("button", { name: /다음: 마스크 생성/ }).click();
    const canvas = page.locator("canvas.edit");
    await canvas.waitFor();
    await waitFor(async () => Number(await canvas.getAttribute("width")) > 100 && (await canvas.boundingBox()).width > 100, 60000, "decoded image canvas");
    if (await page.getByRole("button", { name: "클릭 모두 지우기" }).isEnabled()) {
      await page.getByRole("button", { name: "클릭 모두 지우기" }).click();
      await page.waitForTimeout(500);
    }
    const box = await canvas.boundingBox();
    const t0 = Date.now();
    const positive = await latestPreview(() => canvas.click({ position: { x: box.width * 0.42, y: box.height * 0.45 } }));
    assert.deepEqual(positive.labels, [1]);
    result.first_click_seconds = (Date.now() - t0) / 1000;
    const t1 = Date.now();
    const negative = await latestPreview(() => canvas.click({ position: { x: box.width * 0.92, y: box.height * 0.08 }, modifiers: ["Alt"] }));
    assert.deepEqual(negative.labels, [1, 0]);
    result.second_click_seconds = (Date.now() - t1) / 1000;
  });
  await step("rapid-clicks-zoom-frame", async () => {
    const canvas = page.locator("canvas.edit");
    const box = await canvas.boundingBox();
    const last = await latestPreview(async () => {
      for (let i = 0; i < 5; i++) {
        await canvas.click({ position: { x: box.width * (0.40 + i * 0.01), y: box.height * 0.47 } });
        await page.waitForTimeout(220);
      }
    });
    const final = prompts.at(-1);
    assert.equal(final.labels.length, 7);
    result.rapid_clicks = { sent: prompts.length, first_revision: last.prompt_revision, final_revision: final.prompt_revision };
    await page.getByRole("button", { name: "확대", exact: true }).click();
    await page.waitForTimeout(300); // allow React layout + ResizeObserver to settle
    const zoomed = await canvas.boundingBox();
    const w = Number(await canvas.getAttribute("width")), h = Number(await canvas.getAttribute("height"));
    const viewport = await page.locator(".image-viewport").boundingBox();
    const x = Math.max(zoomed.x + 1, Math.min(zoomed.x + zoomed.width - 1, viewport.x + viewport.width * .5));
    const y = Math.max(zoomed.y + 1, Math.min(zoomed.y + zoomed.height - 1, viewport.y + viewport.height * .5));
    const expected = [(x - zoomed.x) / zoomed.width * w, (y - zoomed.y) / zoomed.height * h];
    // Click a visible client coordinate: locator.click may scroll an oversized canvas
    // after the box was measured, invalidating the test's expected pixel coordinate.
    const request = await latestPreview(() => page.mouse.click(x, y));
    const xy = request.points.at(-1);
    assert.ok(Math.abs(xy[0] - expected[0]) < 2 && Math.abs(xy[1] - expected[1]) < 2, JSON.stringify({ xy, expected, w, h }));
    result.zoom_coordinates = { xy, expected };
    await page.getByRole("button", { name: "화면 맞춤", exact: true }).click();
    await page.locator(".film-row .cell").nth(1).click();
    await page.waitForTimeout(1000);
    const nextBox = await canvas.boundingBox();
    const next = await latestPreview(() => canvas.click({ position: { x: nextBox.width * .42, y: nextBox.height * .45 } }));
    assert.notEqual(next.reference, request.reference);
    result.frame_switch = { before: request.reference, after: next.reference };
    // The test's earlier centre point selects the occluding tree in this fixture.
    // Return to frame1 and explicitly choose the visible brick wall for propagation.
    await page.locator(".film-row .cell").first().click();
    await page.waitForTimeout(1000);
    if (await page.getByRole("button", { name: "클릭 모두 지우기" }).isEnabled())
      await page.getByRole("button", { name: "클릭 모두 지우기" }).click();
    await page.waitForTimeout(500);
    const firstBox = await canvas.boundingBox();
    await latestPreview(() => canvas.click({ position: { x: firstBox.width * .25, y: firstBox.height * .5 } }));
    await latestPreview(() => canvas.click({ position: { x: firstBox.width * .92, y: firstBox.height * .08 }, modifiers: ["Alt"] }));
    if (resumeProject) {
      await page.getByRole("button", { name: /^수정 저장/ }).click();
      await page.waitForTimeout(1000);
      // Saving consumes the preview; another explicit exclusion refreshes it for propagation.
      await latestPreview(() => canvas.click({ position: { x: firstBox.width * .9, y: firstBox.height * .09 }, modifiers: ["Alt"] }));
    }
  });
  await step("propagate", async () => {
    await page.getByRole("button", { name: /등록된 \d+장에 전파/ }).click();
    await waitFor(async () => (await page.locator(".nav-item", { hasText: "마스크 생성" }).locator(".meta").innerText()) !== "완료", 60000, "propagation actually started");
    await waitFor(async () => (await page.locator(".nav-item", { hasText: "마스크 생성" }).locator(".meta").innerText()) === "완료", 1800000, "propagation");
  });
  }
  await step("review", async () => {
    await page.locator(".nav button", { hasText: "마스크 검토" }).click();
    await page.getByRole("button", { name: /확인 · 다음|수정 완료 · 다음/ }).waitFor();
    const canvas = page.locator("canvas.edit");
    await waitFor(async () => Number(await canvas.getAttribute("width")) > 100, 60000, "review decoded photo");
    result.reprompted_invalid_frames = [];
    // Real temporal propagation may lose the object across viewpoints. Exercise the
    // user's correction path instead of skipping invalid candidates or forging masks.
    for (let repaired = 0; repaired < Number(count); repaired++) {
      const invalid = page.locator(".film-row .cell").filter({ has: page.locator(".err") }).first();
      if (!(await invalid.count())) break;
      const name = await invalid.getAttribute("title");
      await invalid.click();
      await page.waitForTimeout(1000);
      await page.getByRole("button", { name: "포함 클릭 (1)", exact: true }).click();
      const box = await canvas.boundingBox();
      await latestPreview(() => canvas.click({ position: { x: box.width * .3, y: box.height * .6 } }));
      await page.getByRole("button", { name: /^수정 저장/ }).click();
      await page.waitForTimeout(1000);
      result.reprompted_invalid_frames.push(name);
    }
    assert.equal(await page.locator(".film-row .cell").filter({ has: page.locator(".err") }).count(), 0, "Invalid masks must be corrected, never skipped");
    await page.getByRole("button", { name: "지우개", exact: true }).click();
    const box = await canvas.boundingBox();
    await canvas.click({ position: { x: box.width * .25, y: box.height * .5 } });
    await page.keyboard.press("Control+z");
    await page.keyboard.press("Control+Shift+z");
    await page.getByRole("button", { name: /^수정 저장/ }).click();
    await page.waitForTimeout(1000);
    for (let i = 0; i < 2; i++) {
      await page.keyboard.press("Space");
      await page.waitForTimeout(1500);
    }
    await page.getByRole("button", { name: /남은 검토 건너뛰기/ }).click();
    await waitFor(async () => await page.getByRole("button", { name: /3D 재구성으로/ }).isEnabled(), 60000, "review done");
    result.review = await page.locator(".toolbar").innerText();
  });
  await step("train", async () => {
    await page.getByRole("button", { name: /3D 재구성으로/ }).click();
    await page.getByText("고급 설정").click();
    await page.locator("input[type=number]").fill(testIterations);
    await page.getByRole("combobox", { name: "3D 모델 해상도", exact: true }).selectOption(testMeshRes);
    await page.getByRole("button", { name: /학습 시작/ }).click();
    await page.getByText("학습 중").first().waitFor({ timeout: 120000 });
    await page.waitForTimeout(15000);
    await shot("train-running");
    await waitFor(async () => (await page.locator(".nav-item", { hasText: "3D 모델 보기" }).locator(".meta").innerText()) === "완료", 3600000, "train+mesh");
  });
  await step("model-viewer", async () => {
    await page.locator(".nav button", { hasText: "3D 모델 보기" }).click();
    await page.getByText("색상 표시 중").waitFor({ timeout: 120000 });
    result.model = await page.locator(".panel.insp").innerText();
    result.color_meshes = await page.locator(".three-host").getAttribute("data-color-meshes");
  });
  result.status = "PASS";
} catch (e) {
  result.status = "FAIL";
  result.error = String(e);
  await shot("failure");
} finally {
  result.console_errors = errors;
  if (errors.length && result.status === "PASS") {
    result.status = "FAIL";
    result.error = "Browser console errors: " + errors.join("; ");
  }
  fs.writeFileSync(path.join(out, "result.json"), JSON.stringify(result, null, 2));
  log(result.status, result.error || "");
  await browser.close();
  if (result.status !== "PASS" || errors.length) process.exitCode = 1;
}
