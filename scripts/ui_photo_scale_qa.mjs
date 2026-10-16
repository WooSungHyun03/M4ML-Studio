// Genuine 100-photo UI/search/sort/theme checks, using an already imported owned project.
import fs from "node:fs";
import { createRequire } from "node:module";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")(
  "playwright",
);
const [base, project, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: false });
const report = {
  scope:
    "100 real photographs; browser UI responsiveness; no GPU reconstruction or external user study",
  checks: [],
  search_ms: [],
};
const browser = await chromium.launch({
  executablePath: process.env.CHROME || undefined,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
const check = (name, ok) => {
  report.checks.push({ name, ok: !!ok });
  if (!ok) throw Error(name);
};
try {
  const p = await (await fetch(base + "/api/projects/" + project)).json();
  check("100 actual project photos", p.images.length === 100);
  report.bytes = p.images.reduce((s, i) => s + (i.bytes || 0), 0);
  const t = Date.now();
  await page.goto(base + "/?project=" + project);
  await page.waitForFunction(
    () => document.querySelectorAll(".grid .cell").length === 100,
  );
  report.ready_ms = Date.now() - t;
  await page.waitForFunction(() => {
    const e = document.querySelector(".grid .cell img");
    return e?.complete && e.naturalWidth > 0;
  });
  check("initial visible thumbnails decoded", true);
  await page.locator(".grid").evaluate((e) => (e.scrollTop = e.scrollHeight));
  await page.waitForTimeout(300);
  await page.locator(".grid").evaluate((e) => (e.scrollTop = 0));
  const query = p.images[0].source_name;
  for (let i = 0; i < 5; i++) {
    const t = Date.now();
    await page.getByRole("textbox", { name: "사진 이름 검색" }).fill(query);
    await page.waitForFunction(
      () => document.querySelectorAll(".grid .cell").length === 1,
    );
    report.search_ms.push(Date.now() - t);
    await page.getByRole("textbox", { name: "사진 이름 검색" }).fill("");
    await page.waitForFunction(
      () => document.querySelectorAll(".grid .cell").length === 100,
    );
  }
  await page
    .getByRole("combobox", { name: "정렬", exact: true })
    .selectOption("name");
  check(
    "sort selection updates",
    (await page
      .getByRole("combobox", { name: "정렬", exact: true })
      .inputValue()) === "name",
  );
  await page.screenshot({ path: out + "/dark.png" });
  await page.click('.menu-top:has-text("보기")');
  await page.click('.menu-item:has-text("밝은 테마")');
  check(
    "light theme applied",
    (await page.locator("html").getAttribute("data-theme")) === "light",
  );
  await page.screenshot({ path: out + "/light.png" });
  await page.reload();
  await page.waitForSelector(".grid");
  check(
    "light theme and project persist on reload",
    (await page.locator("html").getAttribute("data-theme")) === "light" &&
      (await page.locator(".grid .cell").count()) === 100,
  );
  await page.click('.menu-top:has-text("보기")');
  await page.click('.menu-item:has-text("어두운 테마")');
  check(
    "dark theme restored",
    (await page.locator("html").getAttribute("data-theme")) === "dark",
  );
  check("console errors absent", errors.length === 0);
  report.pass = true;
} catch (e) {
  report.error = String(e);
} finally {
  report.errors = errors;
  await browser.close();
  fs.writeFileSync(out + "/result.json", JSON.stringify(report, null, 2));
}
console.log(report);
process.exitCode = report.pass ? 0 : 1;
