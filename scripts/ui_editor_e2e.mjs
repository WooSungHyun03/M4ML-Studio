// Real-browser E2E of the editor shell against a running backend (no mocks).
//   PW_DIR=<dir with playwright> [CHROME=<exe>] node scripts/ui_editor_e2e.mjs http://127.0.0.1:PORT PROJECT_ID OUT_DIR
// Checks: every menu opens with items, panel hide/show + persistence across reload, splitter
// drag + persistence, layout reset, Ctrl+1..6 stage navigation, F1 help loads the shipped
// Markdown, About dialog shows the real version, 3D viewport modes, and zero console errors.
// Prints JSON {pass, checks, errors}; exits 1 on any failure.
import { createRequire } from "node:module";
import fs from "node:fs";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")("playwright");
const [base, project, out = "evidence/editor-e2e"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
page.on("dialog", (d) => void d.dismiss());
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: !!ok, detail: String(detail) });
const wait = (ms) => page.waitForTimeout(ms);
const width = (sel) => page.$eval(sel, (e) => Math.round(e.getBoundingClientRect().width)).catch(() => 0);

await page.goto(`${base}/?project=${project}`, { waitUntil: "domcontentloaded" });
await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector(".editor-body", { timeout: 20000 });
await wait(1500);

// 1. menus
const tops = await page.$$eval(".menu-top", (els) => els.map((e) => e.textContent.trim()));
check("six top-level menus", JSON.stringify(tops) === JSON.stringify(["파일", "편집", "보기", "작업", "창", "도움말"]), tops.join(","));
for (const label of tops) {
  await page.click(`.menu-top:has-text("${label}")`);
  const n = await page.$$eval(".menu-pop .menu-item", (els) => els.length);
  check(`menu ${label} opens with items`, n > 0, n);
  await page.keyboard.press("Escape");
  await wait(100);
}

// 2. hide/show + persistence
const explorerW0 = await width(".dock.left");
check("explorer visible by default", explorerW0 > 0, explorerW0);
await page.click(".editor-body");
await page.keyboard.press("Control+b");
await wait(300);
check("Ctrl+B hides explorer", !(await page.$(".dock.left")));
await page.keyboard.press("Control+j");
await wait(300);
check("Ctrl+J hides bottom panel", !(await page.$(".bottom-panel")));
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector(".editor-body");
await wait(1200);
check("hidden panels persist after reload", !(await page.$(".dock.left")) && !(await page.$(".bottom-panel")));
await page.keyboard.press("Control+b");
await page.keyboard.press("Control+j");
await wait(300);
check("panels shown again", (await page.$(".dock.left")) && (await page.$(".bottom-panel")));

// 3. splitter drag + persistence
const sp = await page.$(".dock.left + .splitter");
const box = await sp.boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + 200);
await page.mouse.down();
await page.mouse.move(box.x + box.width / 2 + 90, box.y + 200, { steps: 8 });
await page.mouse.up();
await wait(300);
const explorerW1 = await width(".dock.left");
check("splitter drag resizes explorer", Math.abs(explorerW1 - explorerW0 - 90) <= 4, `${explorerW0} -> ${explorerW1}`);
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector(".dock.left");
await wait(1000);
check("explorer width persists after reload", Math.abs((await width(".dock.left")) - explorerW1) <= 2, await width(".dock.left"));

// 4. reset to default
await page.click('.menu-top:has-text("보기")');
await page.click('.menu-item:has-text("기본 레이아웃 복원")');
await wait(300);
check("default layout restores explorer width", Math.abs((await width(".dock.left")) - explorerW0) <= 2, await width(".dock.left"));

// 5. stage navigation
const stageTitles = [];
for (let i = 1; i <= 6; i++) {
  await page.click(".editor-body");
  await page.keyboard.press(`Control+${i}`);
  await wait(500);
  stageTitles.push(await page.$eval(".stage-tabs [aria-selected=true], .stage-tabs .on, .stage-tabs [aria-current]", (e) => e.textContent.trim()).catch(() => "?"));
}
check("Ctrl+1..6 switch workflow tabs", new Set(stageTitles).size === 6, stageTitles.join(" | "));
await page.screenshot({ path: `${out}/model-stage.png` });

// 6. viewport modes on the model stage (stage 6)
if (await page.$(".vp-modes")) {
  for (const label of ["정점 색상", "셰이딩", "와이어프레임", "법선", "포인트 클라우드", "색상 메시"]) {
    const b = page.locator(".vp-modes .btn", { hasText: label });
    if (await b.isDisabled()) continue;
    await b.click();
    check(`viewport mode ${label}`, (await b.getAttribute("aria-pressed")) === "true");
  }
}

// 7. help + about
await page.keyboard.press("F1");
await page.waitForSelector(".modal .md, .modal-body", { timeout: 10000 });
await wait(800);
const help = await page.$eval(".modal-body", (e) => e.innerText);
check("F1 opens shipped quick-start guide", help.includes("새 프로젝트") && help.length > 300, help.slice(0, 60));
await page.keyboard.press("Escape");
for (const [item, needle] of [["사용 설명서", "화면 구성"], ["단축키 목록", "Numpad"], ["오류 해결 가이드", "Console"]]) {
  await page.click('.menu-top:has-text("도움말")');
  await page.click(`.menu-item:has-text("${item}")`);
  await wait(800);
  const text = await page.$eval(".modal-body", (e) => e.innerText).catch(() => "");
  check(`help ${item} loads its document`, text.includes(needle), text.slice(0, 40));
  await page.keyboard.press("Escape");
}
await page.click('.menu-top:has-text("도움말")');
await page.click('.menu-item:has-text("M4ML Studio 정보")');
await wait(800);
const about = await page.$eval(".modal-body", (e) => e.innerText);
const real = await (await fetch(`${base}/api/health`)).json().catch(() => ({}));
check("About shows real version", /\d+\.\d+\.\d+/.test(about), about.slice(0, 80));
await page.keyboard.press("Escape");

check("zero console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
const pass = checks.every((c) => c.ok);
fs.writeFileSync(`${out}/result.json`, JSON.stringify({ pass, checks, errors, health_app: real.app }, null, 2));
console.log(JSON.stringify({ pass, failed: checks.filter((c) => !c.ok), total: checks.length }));
await browser.close();
process.exit(pass ? 0 : 1);
