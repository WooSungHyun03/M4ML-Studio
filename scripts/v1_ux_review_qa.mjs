// Full-screen UX review captures in the REAL Qt window (scripts/v1_desktop_host.py).
//   node scripts/v1_ux_review_qa.mjs DEBUG_URL PROJECT_ID OUT_DIR COMMANDS_JSON
// For 1366x768 and 1920x1080, dark and light: welcome, all six stages, live render + mesh,
// four settings tabs, help/about dialogs, every top menu. Captures with the host's own
// QMainWindow.grab (never global desktop capture); asserts no horizontal overflow, no JS errors.
import fs from "node:fs";
import { connectQt } from "./qt_cdp.mjs";
const [debug, project, out, commands] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const q = await connectQt(debug);
const report = { checks: [], screens: [] };
const check = (name, ok, detail = "") => report.checks.push({ name, ok: !!ok, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
let seq = 0;
const host = async (request, ackSuffix) => {
  const sequence = ++seq + Date.now();
  fs.writeFileSync(commands, JSON.stringify({ ...request, sequence }));
  const ack = commands.replace(/\.[^.]+$/, "") + ackSuffix;
  const end = Date.now() + 10000;
  while (Date.now() < end) {
    try { const a = JSON.parse(fs.readFileSync(ack)); if ((a.request?.sequence ?? a.sequence) === sequence) return a; } catch {}
    await q.sleep(100);
  }
  throw Error("host did not acknowledge " + JSON.stringify(request));
};
const shot = async (name) => {
  await q.sleep(500);
  const overflow = await q.evaluate(`[document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight]`);
  // Offscreen Qt cannot QWidget.grab() the WebEngine compositor; use the page's own frame.
  const img = await q.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.mkdirSync(out + "/" + name.split("/")[0], { recursive: true });
  fs.writeFileSync(`${out}/${name}.png`, Buffer.from(img.data, "base64"));
  report.screens.push({ name, overflow });
  if (overflow[0] > overflow[1] + 1) check(`no horizontal page overflow: ${name}`, false, overflow);
};
const setTheme = (t) => q.evaluate(`localStorage.setItem('m4ml-theme','${t}'); true`);
try {
  for (const [w, h] of [[1366, 768], [1920, 1080]]) {
    const ack = await host({ size: [w, h] }, ".ack.json");
    check(`window ${w}x${h}`, ack.size[0] === w && ack.size[1] === h && ack.korean_glyphs, ack);
    for (const theme of ["dark", "light"]) {
      const tag = `${w}-${theme}`;
      await setTheme(theme);
      await q.navigate("/", ".start-tile, .welcome, .menubar");
      await q.sleep(1500);
      await shot(`${tag}/00-welcome`);
      await q.navigate(`/?project=${project}`, ".stage-tabs");
      await q.sleep(1200);
      const stages = await q.evaluate(`[...document.querySelectorAll('.stage-tab')].map(e=>e.childNodes[1]?.textContent?.trim() || e.textContent.trim())`);
      check(`six workflow tabs ${tag}`, stages.length === 6, stages);
      for (let i = 0; i < stages.length; i++) {
        await q.evaluate(`document.querySelectorAll('.stage-tab')[${i}].click(); true`);
        await q.sleep(i === 5 ? 3500 : 1500);
        await shot(`${tag}/0${i + 1}-${stages[i].replace(/ /g, "_")}`);
      }
      // 3D: both views
      const hasLive = await q.evaluate(`!!document.querySelector('[aria-label="3D 표시 방식"]')`);
      if (hasLive) {
        await q.click('[aria-label="3D 표시 방식"] button', "메시");
        await q.sleep(3000);
        await shot(`${tag}/07-mesh`);
        await q.click('[aria-label="3D 표시 방식"] button', "실시간 렌더");
        await q.waitFor(`!!document.querySelector('.live-frame[data-state="rendering"]') && Number(document.querySelector('.live-surface')?.dataset.frames||0)>0`, 90000);
        await q.sleep(1500);
        await shot(`${tag}/08-live`);
        await q.click('[aria-label="3D 표시 방식"] button', "메시");
        await q.sleep(800);
      }
      // menus
      const menus = await q.evaluate(`[...document.querySelectorAll('.menu-top')].map(e=>e.textContent.trim())`);
      for (const m of menus) {
        await q.click(".menu-top", m);
        await q.sleep(400);
        await shot(`${tag}/menu-${m}`);
        await q.evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); document.body.click(); true`);
        await q.sleep(200);
      }
      // settings tabs
      await q.click(".menu-top", "편집");
      await q.sleep(300);
      await q.click(".menu-item", "환경 설정");
      await q.sleep(800);
      const tabs = await q.evaluate(`[...document.querySelectorAll('.tabs [role=tab]')].map(e=>e.textContent.trim())`);
      for (const t of tabs) {
        await q.click(".tabs [role=tab]", t);
        await q.sleep(900);
        await shot(`${tag}/settings-${t.replace(/[ ·/]/g, "_")}`);
      }
      check(`settings tabs ${tag}`, tabs.length >= 4, tabs);
      await q.evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); true`);
      await q.navigate(`/?project=${project}`, ".stage-tabs");
      // help dialogs
      await q.click(".menu-top", "도움말");
      await q.sleep(300);
      const helpItems = await q.evaluate(`[...document.querySelectorAll('.menu-pop .menu-item .mi-label')].map(e=>e.textContent.trim())`);
      await q.evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); document.body.click(); true`);
      report.help_items = helpItems;
      for (const item of helpItems.filter((t) => !/폴더|환경 진단/.test(t))) {  // folder opens the OS file manager
        await q.click(".menu-top", "도움말");
        await q.sleep(300);
        await q.click(".menu-item", item);
        await q.sleep(1000);
        await shot(`${tag}/help-${item.replace(/ /g, "_")}`);
        await q.evaluate(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); true`);
        await q.sleep(300);
      }
    }
  }
  await setTheme("dark");
  check("no JS exceptions", q.errors.length === 0, q.errors.slice(0, 5));
  report.passed = report.checks.every((c) => c.ok);
} catch (e) {
  report.error = String(e.stack || e);
} finally {
  q.close();
  fs.writeFileSync(out + "/result.json", JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ passed: report.passed, error: report.error, failed: report.checks.filter((c) => !c.ok), screens: report.screens.length }));
process.exitCode = report.passed ? 0 : 1;
