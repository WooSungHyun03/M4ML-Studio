// Real browser + native CUDA backend. Source artifact hashes are checked before/after.
// PW_DIR=<directory containing playwright> node scripts/ui_settings_artifacts_e2e.mjs URL FOLDER OUT
import { createRequire } from "node:module";
import fs from "node:fs";
import crypto from "node:crypto";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")(
  "playwright",
);
const [origin, folder, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME || undefined,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({
  viewport: { width: 1600, height: 1000 },
  acceptDownloads: true,
});
const report = {
  checks: [],
  errors: [],
  scope:
    "real standalone native 2DGS/Mesh files, browser UI settings and CUDA frame sizes",
};
const check = (name, ok, detail) => {
  report.checks.push({ name, ok: !!ok, detail });
  if (!ok) throw Error(name + ": " + JSON.stringify(detail));
};
page.on("pageerror", (e) => report.errors.push(String(e)));
const hashes = () =>
  Object.fromEntries(
    fs
      .readdirSync(folder)
      .filter((f) => fs.statSync(folder + "/" + f).isFile())
      .map((f) => [
        f,
        crypto
          .createHash("sha256")
          .update(fs.readFileSync(folder + "/" + f))
          .digest("hex"),
      ]),
  );
const before = hashes();
const api = async (path, method = "GET", body) =>
  page.evaluate(
    async ({ path, method, body }) => {
      const { token } = await (await fetch("/api/session")).json();
      const r = await fetch("/api" + path, {
        method,
        headers: {
          "x-studio-token": token,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!r.ok) throw Error(await r.text());
      return r.json();
    },
    { path, method, body },
  );
let pid;
try {
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.getByText("새 프로젝트 · 폴더 선택", { exact: false }).waitFor();
  page.once("dialog", (d) => d.accept(folder));
  await page.getByRole("button", { name: "새 프로젝트 · 폴더 선택" }).click();
  await page
    .getByText("폴더 분석 결과", { exact: true })
    .waitFor({ timeout: 60000 });
  check(
    "folder UI recognises native Gaussian",
    (await page.getByText("Object-Aware Gaussian", { exact: true }).count()) ===
      1,
  );
  await page.screenshot({ path: out + "/01-scan.png" });
  await page.locator(".analysis button.primary").click();
  await page.waitForSelector(".three-host[data-color-meshes]", {
    timeout: 120000,
  });
  pid = new URL(page.url()).searchParams.get("project");
  check("opened independent project", !!pid);
  const p = await api("/projects/" + pid);
  report.project = pid;
  check(
    "two independent artifacts, no fake training",
    p.result_artifacts?.length === 2 &&
      p.stages.train !== "completed" &&
      !p.training,
  );
  check(
    "actual colored Mesh loaded",
    Number(
      await page.locator(".three-host").getAttribute("data-color-meshes"),
    ) > 0,
  );
  await page.getByRole("button", { name: "표시 설정", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "표시 설정", exact: true });
  await panel.waitFor();
  const scale = panel
    .getByText("표시 해상도 배율", { exact: true })
    .locator("..")
    .locator("..")
    .locator("input");
  await scale.fill("0.5");
  await panel.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector(".three-host")?.dataset.renderScale === "0.5",
  );
  const small = await page
    .locator(".three-host canvas")
    .evaluate((c) => [c.width, c.height]);
  await scale.fill("1");
  await panel.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector(".three-host")?.dataset.renderScale === "1",
  );
  const full = await page
    .locator(".three-host canvas")
    .evaluate((c) => [c.width, c.height]);
  check(
    "Mesh framebuffer resolution changes",
    full[0] === small[0] * 2 && Math.abs(full[1] - small[1] * 2) <= 1,
    { small, full },
  );
  const background = panel
    .getByText("뷰포트 배경", { exact: true })
    .locator("..")
    .locator("..")
    .locator("input");
  await background.fill("#334455");
  await panel.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForFunction(
    () =>
      document.querySelector(".three-host")?.dataset.background === "#334455",
  );
  await page.screenshot({ path: out + "/02-settings.png" });
  await panel.getByRole("button", { name: "세부 설정 닫기" }).click();
  await page.reload();
  await page.waitForSelector('.three-host[data-background="#334455"]', {
    timeout: 60000,
  });
  check("project settings survive browser restart", true);
  await page.getByRole("button", { name: "실시간 렌더", exact: true }).click();
  await page.waitForSelector('.live-frame[data-state="rendering"]', {
    timeout: 120000,
  });
  await page.waitForFunction(
    () => Number(document.querySelector(".live-surface")?.dataset.frames) > 0,
    {},
    { timeout: 60000 },
  );
  const live = await api("/projects/" + pid + "/live-render");
  check(
    "standalone native Gaussian actually on GPU",
    live.session?.state === "rendering",
    live.session,
  );
  await page.getByRole("button", { name: "표시 설정", exact: true }).click();
  const vp = page.getByRole("dialog", { name: "표시 설정", exact: true });
  await vp.waitFor();
  const vs = vp
    .getByText("표시 해상도 배율", { exact: true })
    .locator("..")
    .locator("..")
    .locator("input");
  await vs.fill("0.5");
  await vp.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForTimeout(1200);
  const gSmall = await page
    .locator(".live-surface img")
    .evaluate((i) => [i.naturalWidth, i.naturalHeight]);
  await vs.fill("1");
  await vp.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForTimeout(1200);
  const gFull = await page
    .locator(".live-surface img")
    .evaluate((i) => [i.naturalWidth, i.naturalHeight]);
  check(
    "CUDA Gaussian actual frame size changes",
    Math.abs(gFull[0] - 2 * gSmall[0]) <= 1 &&
      Math.abs(gFull[1] - 2 * gSmall[1]) <= 1,
    { gSmall, gFull },
  );
  await vp.getByRole("button", { name: "현재 그룹 기본값 복원" }).click();
  check(
    "reset is reviewable draft",
    (await vp
      .getByText(
        "현재 그룹의 기본값을 미리 보고 있습니다. 저장 또는 취소하세요.",
      )
      .count()) === 1,
  );
  await vp.getByRole("button", { name: "저장", exact: true }).click();
  await page.screenshot({ path: out + "/03-gaussian.png" });
  await vp.getByRole("button", { name: "세부 설정 닫기" }).click();
  await page.getByRole("button", { name: "메시", exact: true }).click();
  await page.waitForTimeout(600);
  check(
    "reset persists backend default",
    (await api("/projects/" + pid + "/task-settings")).view.values
      .background === "#1c1c20",
  );
  check(
    "source artifacts unchanged",
    JSON.stringify(before) === JSON.stringify(hashes()),
  );
  check("no page exceptions", report.errors.length === 0, report.errors);
  report.passed = true;
} catch (e) {
  report.error = String(e);
  await page.screenshot({ path: out + "/failure.png" }).catch(() => {});
} finally {
  if (pid)
    await api("/projects/" + pid + "/live-render/stop", "POST", {}).catch(
      () => {},
    );
  await browser.close();
  fs.writeFileSync(out + "/result.json", JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.passed ? 0 : 1;
