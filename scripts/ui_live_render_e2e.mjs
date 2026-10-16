// Real-browser E2E of the "실시간 렌더" viewport against a running backend + GPU renderer.
//   PW_DIR=<dir with playwright> [CHROME=<exe>] node scripts/ui_live_render_e2e.mjs http://127.0.0.1:PORT PROJECT_ID [OUT_DIR] [OTHER_PROJECT_ID]
// Verifies with frame hashes (not element presence) that the rendered image changes with
// rotate / zoom / pan / mode / resize, the mesh view still works, switching back stops the
// renderer, and (optionally) that opening another project renders that project's model.
import { createRequire } from "node:module";
import crypto from "node:crypto";
import fs from "node:fs";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")("playwright");
const [base, project, out = "evidence/gaussian-viewer/e2e", other] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: !!ok, detail: String(detail) });
const wait = (ms) => page.waitForTimeout(ms);
const api = async (path, method = "GET") => page.evaluate(async ([p, m]) => {
  const tok = (await (await fetch("/api/session")).json()).token;
  const r = await fetch("/api" + p, { method: m, headers: { "x-studio-token": tok } });
  return r.json();
}, [path, method]);
// Hash of the currently displayed rendered frame (bytes of the blob the <img> shows).
const frameHash = async () => page.evaluate(async () => {
  const img = document.querySelector(".live-surface img");
  if (!img || !img.src) return null;
  const buf = await (await fetch(img.src)).arrayBuffer();
  const d = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(d)).slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
});
const frames = async () => Number(await page.getAttribute(".live-surface", "data-frames").catch(() => 0)) || 0;
const settle = async (ms = 900) => { await wait(ms); };

await page.goto(`${base}/?project=${project}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".stage-tabs", { timeout: 20000 });
await page.click('.stage-tabs >> text=3D 모델');
await page.waitForSelector('[aria-label="3D 표시 방식"]', { timeout: 15000 });
const t0 = Date.now();
await page.click('[aria-label="3D 표시 방식"] >> text=실시간 렌더');
await page.waitForSelector('.live-frame[data-state="rendering"]', { timeout: 120000 });
await page.waitForFunction(() => Number(document.querySelector(".live-surface")?.dataset.frames || 0) > 0, null, { timeout: 60000 });
check("first frame rendered", true, `${Date.now() - t0} ms from click`);
await settle(1500);
await page.screenshot({ path: `${out}/01-live-initial.png` });
const status = await api(`/projects/${project}/live-render`);
check("renderer session running for project", status.session?.state === "rendering", JSON.stringify(status.session?.modes?.map((m) => m.key)));

const surface = await page.$(".live-surface");
const box = await surface.boundingBox();
const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
let h0 = await frameHash();
// rotate
await page.mouse.move(cx, cy);
await page.mouse.down();
await page.mouse.move(cx + 220, cy + 40, { steps: 12 });
await page.mouse.up();
await settle();
let h1 = await frameHash();
check("left-drag rotates (frame changed)", h0 && h1 && h0 !== h1, `${h0} -> ${h1}`);
await page.screenshot({ path: `${out}/02-live-rotated.png` });
// zoom
await page.mouse.move(cx, cy);
await page.mouse.wheel(0, -600);
await settle();
let h2 = await frameHash();
check("wheel zooms (frame changed)", h2 && h2 !== h1, `${h1} -> ${h2}`);
await page.screenshot({ path: `${out}/03-live-zoomed.png` });
// pan (right drag)
await page.mouse.move(cx, cy);
await page.mouse.down({ button: "right" });
await page.mouse.move(cx - 150, cy - 60, { steps: 10 });
await page.mouse.up({ button: "right" });
await settle();
let h3 = await frameHash();
check("right-drag pans (frame changed)", h3 && h3 !== h2, `${h2} -> ${h3}`);
// responsiveness during a drag: frames delivered while moving
const before = await frames();
const t1 = Date.now();
await page.mouse.move(cx, cy);
await page.mouse.down();
for (let i = 0; i < 40; i++) await page.mouse.move(cx + i * 6, cy + Math.sin(i / 5) * 30);
await page.mouse.up();
const dragMs = Date.now() - t1;
await settle();
const during = (await frames()) - before;
check("frames stream during drag", during >= 5, `${during} frames in ${dragMs} ms drag`);
// reset view
await page.click('[aria-label="시점 초기화"]');
await settle();
const hReset = await frameHash();
check("시점 초기화 returns to training view", hReset && hReset !== h3, hReset);
// modes
for (const label of ["불투명도", "깊이", "법선", "객체 점수", "색상"]) {
  const b = page.locator(".vp-modes .btn", { hasText: label });
  if (!(await b.count())) { check(`mode ${label} offered`, false); continue; }
  const hb = await frameHash();
  await b.click();
  await settle(1200);
  const ha = await frameHash();
  check(`mode ${label} changes the image`, ha && ha !== hb && (await b.getAttribute("aria-pressed")) === "true", `${hb} -> ${ha}`);
  if (label !== "색상") await page.screenshot({ path: `${out}/04-mode-${label}.png` });
}
// resize: viewport size change → new frame with the new aspect
const sizeBefore = await page.getAttribute(".live-surface", "data-last-size");
await page.setViewportSize({ width: 1280, height: 900 });
await settle(1500);
const sizeAfter = await page.getAttribute(".live-surface", "data-last-size");
const surf2 = await (await page.$(".live-surface")).boundingBox();
const [rw, rh] = (sizeAfter || "0x0").split("x").map(Number);
check("resize re-renders at new aspect", sizeAfter !== sizeBefore && Math.abs(rw / rh - surf2.width / surf2.height) < 0.01, `${sizeBefore} -> ${sizeAfter}, surface ${Math.round(surf2.width)}x${Math.round(surf2.height)}`);
await page.setViewportSize({ width: 1600, height: 1000 });
await settle(1200);
// fullscreen of the viewport (element fullscreen; the desktop shell maps it to the window)
await page.click('[aria-label="전체 화면"]');
await settle(1500);
const fs1 = await page.evaluate(() => [!!document.fullscreenElement, document.fullscreenElement?.className || "", document.querySelector(".live-surface").dataset.lastSize]);
await page.screenshot({ path: `${out}/05a-fullscreen.png` });
await page.click('[aria-label="전체 화면"]');
await settle(1200);
const fs2 = await page.evaluate(() => !!document.fullscreenElement);
check("fullscreen toggles the viewport and re-renders", fs1[0] && /live-frame/.test(fs1[1]) && !fs2, `${fs1.join(" ")} → exit ${!fs2}`);
// screenshot download
const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }), page.click('[aria-label="스크린샷 저장"]')]);
await dl.saveAs(`${out}/05-screenshot-download.png`);
check("screenshot downloads a PNG", (await dl.suggestedFilename()).endsWith(".png"), await dl.suggestedFilename());
// mesh view preserved and renderer stopped when leaving the live view
await page.click('[aria-label="3D 표시 방식"] >> text=메시');
await page.waitForSelector(".vp-modes >> text=색상 메시", { timeout: 20000 });
await settle(3000);
await page.screenshot({ path: `${out}/06-mesh-view.png` });
const after = await api(`/projects/${project}/live-render`);
check("leaving live view stops the renderer", !after.session, JSON.stringify(after.session));
check("mesh viewer still works", (await page.$(".vp-modes >> text=와이어프레임")) !== null);
// back to live: reconnects
await page.click('[aria-label="3D 표시 방식"] >> text=실시간 렌더');
await page.waitForSelector('.live-frame[data-state="rendering"]', { timeout: 120000 });
await page.waitForFunction(() => Number(document.querySelector(".live-surface")?.dataset.frames || 0) > 0, null, { timeout: 60000 });
check("live view reopens after mesh view", true);
if (other) {
  const tSwitch = Date.now();
  await page.goto(`${base}/?project=${other}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".stage-tabs", { timeout: 20000 });
  await page.click('.stage-tabs >> text=3D 모델');
  await page.click('[aria-label="3D 표시 방식"] >> text=실시간 렌더').catch(() => {});
  await page.waitForSelector('.live-frame[data-state="rendering"]', { timeout: 120000 });
  await page.waitForFunction(() => Number(document.querySelector(".live-surface")?.dataset.frames || 0) > 0, null, { timeout: 60000 });
  await settle(1500);
  await page.screenshot({ path: `${out}/07-other-project.png` });
  const o = await api(`/projects/${other}/live-render`);
  const p = await api(`/projects/${project}/live-render`);
  check("other project renders its own model", o.session?.state === "rendering" && !p.session, `other gaussians ${o.session?.gaussians}, first project session ${JSON.stringify(p.session)}`);
  check("project switch time", true, `${Date.now() - tSwitch} ms to first frame`);
}
check("zero console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
// Closing a browser page does not run React unmount effects. Explicitly release
// only this test's renderer sessions before browser shutdown.
for (const id of [project, other].filter(Boolean)) {
  await api(`/projects/${id}/live-render/stop`, "POST");
  const status = await api(`/projects/${id}/live-render`);
  check(`renderer released after QA ${id}`, !status.session);
}
const pass = checks.every((c) => c.ok);
fs.writeFileSync(`${out}/result.json`, JSON.stringify({ pass, checks, errors }, null, 2));
console.log(JSON.stringify({ pass, failed: checks.filter((c) => !c.ok), total: checks.length }));
await browser.close();
process.exit(pass ? 0 : 1);
