// Real UI screenshots of the running app with Playwright (no mocks).
//   PW_DIR=<node_modules dir containing playwright> node scripts/ui_capture.mjs URL OUT.png [W H] [steps.json]
// steps.json: [{"click": "text=..."}, {"wait": 1000}, {"key": "Space"}, ...]
import { createRequire } from "node:module";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")("playwright");
import fs from "node:fs";
const [url, out, w = "1920", h = "1080", steps] = process.argv.slice(2);
const exe = process.env.CHROME || undefined;
const browser = await chromium.launch({ executablePath: exe, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);
for (const s of steps ? JSON.parse(fs.readFileSync(steps, "utf8")) : []) {
  if (s.click) await page.click(s.click, { timeout: 10000 });
  if (s.wait) await page.waitForTimeout(s.wait);
  if (s.key) await page.keyboard.press(s.key);
  if (s.shot) await page.screenshot({ path: s.shot });
}
await page.screenshot({ path: out });
console.log(JSON.stringify({ out, errors }));
await browser.close();
