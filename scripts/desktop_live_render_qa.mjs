// QA of the live Gaussian viewport inside the REAL desktop window (PySide6/QtWebEngine).
// Mouse input is delivered ONLY to the M4ML page through QtWebEngine DevTools
// Input.dispatchMouseEvent (Chromium's real input pipeline → OrbitControls pointer events);
// no global OS input is injected, so other windows on a shared desktop are never touched. Requires the app started with
// QTWEBENGINE_REMOTE_DEBUGGING=127.0.0.1:9333 (test runs only).
//   PW_DIR=... node scripts/desktop_live_render_qa.mjs PROJECT_ID WINDOW_ID ORIGIN_X ORIGIN_Y OUT_DIR
import { execFileSync } from "node:child_process";
import fs from "node:fs";
const [project, windowId, ox, oy, out = "evidence/gaussian-viewer/desktop"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const x = (...a) => execFileSync("python3", ["scripts/x11_input.py", ...a.map(String)]);
const shot = (name) => execFileSync("import", ["-window", windowId, "-resize", "50%", `${out}/${name}`]);
// Minimal CDP client (QtWebEngine does not implement Playwright's browser-context API).
const target = (await (await fetch("http://127.0.0.1:9333/json")).json()).find((t) => t.type === "page");
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok) => ws.addEventListener("open", ok, { once: true }));
let seq = 0;
const pending = new Map();
const errors = [];
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.text);
  if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") errors.push(msg.params.args.map((a) => a.value ?? a.description).join(" "));
});
const send = (method, params = {}) => new Promise((ok) => { const id = ++seq; pending.set(id, ok); ws.send(JSON.stringify({ id, method, params })); });
await send("Runtime.enable");
const evaluate = async (expr, ms = 15000) => {
  const r = await Promise.race([
    send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }),
    new Promise((_, no) => setTimeout(() => no(new Error("evaluate timeout: " + expr.slice(0, 60))), ms)),
  ]);
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + expr.slice(0, 80));
  return r.result?.result?.value;
};
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const waitFor = async (expr, timeout = 60000) => {
  const t = Date.now();
  while (Date.now() - t < timeout) { if (await evaluate(expr).catch(() => false)) return true; await sleep(200); }
  throw new Error("timeout: " + expr);
};
const clickText = (sel, text) => evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})].find((n) => n.textContent.includes(${JSON.stringify(text)})); if (!e) return false; e.click(); return true; })()`);
const page = {
  getAttribute: (sel, attr) => evaluate(`document.querySelector(${JSON.stringify(sel)})?.getAttribute(${JSON.stringify(attr)})`),
};
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: !!ok, detail: String(detail) });
const wait = sleep;
const frames = async () => Number(await page.getAttribute(".live-surface", "data-frames")) || 0;
const hash = () => evaluate(`(async () => { const img = document.querySelector(".live-surface img"); const buf = await (await fetch(img.src)).arrayBuffer(); let h = 2166136261; const a = new Uint8Array(buf); for (let i = 0; i < a.length; i += 7) { h ^= a[i]; h = Math.imul(h, 16777619) >>> 0; } return h.toString(16) + ":" + a.length; })()`);
const dpr = await evaluate("window.devicePixelRatio");
const desktop = await evaluate("!!window.__M4ML_TOKEN__");
check("running inside the desktop shell (token injected, no browser)", desktop, `devicePixelRatio ${dpr}`);

send("Runtime.evaluate", { expression: `setTimeout(() => { location.href = location.origin + "/?project=${project}"; }, 50); true` });
await sleep(2500);
await waitFor(`!!document.querySelector(".stage-tabs")`, 30000);
await clickText(".stage-tab", "3D 모델");
await waitFor(`!!document.querySelector('[aria-label="3D 표시 방식"]')`);
const t0 = Date.now();
await clickText('[aria-label="3D 표시 방식"] button', "실시간 렌더");
await waitFor(`!!document.querySelector('.live-frame[data-state="rendering"]')`, 120000);
await waitFor(`Number(document.querySelector(".live-surface")?.dataset.frames || 0) > 0`);
const firstFrame = Date.now() - t0;
await wait(1500);
check("first frame in desktop window", true, `${firstFrame} ms after click`);
shot("01-desktop-live-initial.png");
const r = await evaluate(`(() => { const b = document.querySelector(".live-surface").getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height }; })()`);
// CDP input uses CSS pixels of the page.
const sx = (v) => v, sy = (v) => v;
const mouse = (type, px, py, button = "none", extra = {}) => send("Input.dispatchMouseEvent", { type, x: px, y: py, button, buttons: button === "left" ? 1 : button === "right" ? 2 : 0, clickCount: type === "mousePressed" || type === "mouseReleased" ? 1 : 0, ...extra });
const drag = async (x1, y1, x2, y2, button = "left", steps = 20) => {
  await mouse("mouseMoved", x1, y1);
  await mouse("mousePressed", x1, y1, button);
  for (let i = 1; i <= steps; i++) { await mouse("mouseMoved", x1 + ((x2 - x1) * i) / steps, y1 + ((y2 - y1) * i) / steps, button); await sleep(16); }
  await mouse("mouseReleased", x2, y2, button);
};
const wheel = async (px, py, clicks) => { for (let i = 0; i < Math.abs(clicks); i++) { await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: px, y: py, deltaX: 0, deltaY: Math.sign(clicks) * 120 }); await sleep(30); } };
const cx = r.x + r.w / 2, cy = r.y + r.h / 2;

let h0 = await hash();
let f0 = await frames();
let t = Date.now();
await drag(cx, cy, cx + 260, cy + 50, "left", 30);
const dragMs = Date.now() - t;
await wait(1000);
let h1 = await hash();
check("left-drag rotates the Gaussians", h1 !== h0, `${h0} -> ${h1}; ${(await frames()) - f0} frames during/after a ${dragMs} ms drag`);
shot("02-desktop-live-rotated.png");
await wheel(cx, cy, -6);
await wait(1000);
let h2 = await hash();
check("wheel zooms", h2 !== h1, `${h1} -> ${h2}`);
await drag(cx, cy, cx - 180, cy - 80, "right", 20);
await wait(1000);
let h3 = await hash();
check("right-drag pans", h3 !== h2, `${h2} -> ${h3}`);
shot("03-desktop-live-zoom-pan.png");

// Sustained interaction: measure delivered frame rate and latency while dragging for ~3 s.
f0 = await frames();
t = Date.now();
await drag(cx - 300, cy, cx + 300, cy + 20, "left", 180);
const sustained = (Date.now() - t) / 1000;
const delivered = (await frames()) - f0;
const perf = await evaluate(`document.querySelector(".vp-stats").innerText`);
check("sustained drag frame rate", delivered / sustained >= 10, `${delivered} frames in ${sustained.toFixed(2)} s = ${(delivered / sustained).toFixed(1)} fps; HUD: ${perf.replace(/\n/g, " ")}`);

// Viewport resize inside the editor (hide bottom panel + Inspector) → new aspect re-rendered.
await sleep(800);
const before = await page.getAttribute(".live-surface", "data-last-size");
const s1 = await evaluate(`(() => { const b = document.querySelector(".live-surface").getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; })()`);
await evaluate(`document.querySelector('[aria-label="아래 패널 숨기기"]')?.click()`);
await evaluate(`[...document.querySelectorAll(".icon-btn")].find((b) => (b.title || "").startsWith("속성 패널") || (b.title || "").startsWith("Inspector"))?.click()`);
await sleep(2500);
const after = await page.getAttribute(".live-surface", "data-last-size");
const r2 = await evaluate(`(() => { const b = document.querySelector(".live-surface").getBoundingClientRect(); return [b.width, b.height]; })()`);
const [aw, ah] = (after || "0x0").split("x").map(Number);
check("viewport resize re-renders at the new aspect", (r2[0] !== s1[0] || Math.round(r2[1]) !== s1[1]) && Math.abs(aw / ah - r2[0] / r2[1]) < 0.01, `surface ${s1.join("x")} -> ${r2.map(Math.round).join("x")} css; frame ${before} -> ${after}`);
shot("04-desktop-live-resized.png");
await evaluate(`[...document.querySelectorAll(".icon-btn")].find((b) => (b.title || "").startsWith("속성 패널") || (b.title || "").startsWith("Inspector"))?.click()`);
await evaluate(`[...document.querySelectorAll(".icon-btn")].find((b) => (b.title || "").startsWith("아래 패널") || (b.title || "").startsWith("작업 패널"))?.click()`);
await sleep(1500);
const inspector = (await evaluate(`document.querySelector(".insp-stage")?.innerText || ""`)) || "";
check("Inspector shows real renderer data", /Gaussian/.test(inspector) && /렌더링 중/.test(inspector), inspector.replace(/\n/g, " ").slice(0, 200));
check("no console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
const pass = checks.every((c) => c.ok);
fs.writeFileSync(`${out}/result.json`, JSON.stringify({ pass, checks }, null, 2));
console.log(JSON.stringify({ pass, checks }, null, 1));
ws.close();
process.exit(pass ? 0 : 1);
