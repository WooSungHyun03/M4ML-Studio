// Page-scoped real QtWebEngine QA; no global keyboard or mouse injection.
import { connectQt } from "./qt_cdp.mjs";
import fs from "node:fs";
const [debug, project, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const q = await connectQt(debug);
const report = {
  checks: [],
  scope:
    "real source PySide6 window; project settings, colored mesh, native CUDA Gaussian; isolated data",
};
const check = (name, ok, detail) => {
  report.checks.push({ name, ok: !!ok, detail });
  if (!ok) throw Error(name);
};
try {
  await q.waitFor("!!window.m4mlReady");
  check("native bridge active", await q.evaluate("!!window.__M4ML_DESKTOP__"));
  await q.evaluate(
    `setTimeout(()=>location.assign(location.origin+'/?project=${project}'),100);true`,
  );
  await q.waitFor(
    'Number(document.querySelector(".three-host")?.dataset.colorMeshes)>0',
    60000,
  );
  check("real colored mesh loads in Qt", true);
  await q.click(".toolbar button", "표시 설정");
  await q.waitFor(
    '!!document.querySelector(".task-settings input[type=number]")',
  );
  await q.click(".task-settings input[type=number]");
  await q.send("Input.dispatchKeyEvent", {
    type: "rawKeyDown",
    key: "a",
    code: "KeyA",
    windowsVirtualKeyCode: 65,
    modifiers: 2,
  });
  await q.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "a",
    code: "KeyA",
    windowsVirtualKeyCode: 65,
    modifiers: 2,
  });
  await q.send("Input.insertText", { text: "0.5" });
  await q.click(".task-settings button", "저장");
  await q.waitFor(
    'document.querySelector(".three-host")?.dataset.renderScale==="0.5"',
  );
  check("Qt UI saves actual render scaling", true);
  await q.click('.task-settings button[aria-label="세부 설정 닫기"]');
  await q.send("Page.reload");
  await q.waitFor(
    'document.querySelector(".three-host")?.dataset.renderScale==="0.5"',
    60000,
  );
  check("Qt page restart restores project display settings", true);
  const before = await q.evaluate(
    '(()=>{const c=document.querySelector(".three-host canvas");return [c.width,c.height]})()',
  );
  report.meshResolution = before;
  await q.click(".toolbar button", "표시 설정");
  await q.click(".task-settings button", "현재 그룹 기본값 복원");
  check(
    "reset visibly remains draft",
    await q.evaluate(
      'document.querySelector(".task-settings").innerText.includes("미리 보고")',
    ),
  );
  await q.click(".task-settings button", "저장");
  await q.waitFor(
    'document.querySelector(".three-host")?.dataset.renderScale==="1"',
  );
  await q.click('.task-settings button[aria-label="세부 설정 닫기"]');
  await q.click('[aria-label="3D 표시 방식"] button', "실시간 렌더");
  await q.waitFor(
    'Number(document.querySelector(".live-surface")?.dataset.frames)>0',
    120000,
  );
  check("standalone Gaussian renders natively in Qt", true);
  report.liveFrame = await q.evaluate(
    '(()=>{const i=document.querySelector(".live-surface img");return [i.naturalWidth,i.naturalHeight]})()',
  );
  const shot = await q.send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(
    out + "/native-settings-gaussian.png",
    Buffer.from(shot.data, "base64"),
  );
  await q.click('[aria-label="3D 표시 방식"] button', "메시");
  await q.waitFor(
    'Number(document.querySelector(".three-host")?.dataset.colorMeshes)>0',
  );
  report.errors = q.errors;
  check("Qt console exceptions absent", q.errors.length === 0, q.errors);
  report.passed = true;
} catch (e) {
  report.error = String(e);
} finally {
  q.close();
  fs.writeFileSync(out + "/result.json", JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.passed ? 0 : 1;
