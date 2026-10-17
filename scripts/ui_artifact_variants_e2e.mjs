// Actual file imports + native CUDA rendering. No mock results or global input.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const { chromium } = createRequire((process.env.PW_DIR || process.cwd()) + "/")(
  "playwright",
);
const [origin, fixtureRoot, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME || undefined,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const report = {
  checks: [],
  errors: [],
  projects: [],
  scope:
    "actual standalone Gaussian-only, GLB-only, multiple same-size native Gaussian selection and matched-training fallback",
};
const check = (name, ok, detail) => {
  report.checks.push({ name, ok: !!ok, detail });
  if (!ok) throw Error(name);
};
page.on("pageerror", (e) => report.errors.push(String(e)));
await page.goto(origin);
const api = async (route, method = "GET", body) =>
  page.evaluate(
    async ({ route, method, body }) => {
      const { token } = await (await fetch("/api/session")).json();
      const r = await fetch("/api" + route, {
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
    { route, method, body },
  );
const frame = async () => {
  await page.waitForSelector('.live-frame[data-state="rendering"]', {
    timeout: 120000,
  });
  await page.waitForFunction(
    () => Number(document.querySelector(".live-surface")?.dataset.frames) > 0,
    {},
    { timeout: 60000 },
  );
};
const goto = async (p) => {
  report.projects.push(p.id);
  await page.goto(origin + "/?project=" + p.id, {
    waitUntil: "domcontentloaded",
  });
};
try {
  let opened = await api("/projects/from-folder", "POST", {
    path: path.join(fixtureRoot, "gaussian-only"),
  });
  let p = opened.project;
  await goto(p);
  await frame();
  check("Gaussian-only actual CUDA frame", true);
  check(
    "Gaussian-only does not fabricate training",
    p.stages.train !== "completed" && !p.training,
  );
  await api("/projects/" + p.id + "/live-render/stop", "POST", {});
  opened = await api("/projects/from-folder", "POST", {
    path: path.join(fixtureRoot, "glb-only"),
  });
  p = opened.project;
  await goto(p);
  await page.waitForSelector(".three-host[data-color-meshes]", {
    timeout: 60000,
  });
  check(
    "GLB-only actual colored mesh displayed",
    Number(
      await page.locator(".three-host").getAttribute("data-color-meshes"),
    ) > 0,
  );
  opened = await api("/projects/from-folder", "POST", {
    path: path.join(fixtureRoot, "multiple-results"),
    artifacts: ["first.ply", "second.ply", "surface.ply"],
  });
  p = opened.project;
  await goto(p);
  await page.waitForSelector(".three-host[data-color-meshes]", {
    timeout: 60000,
  });
  const gaussians = p.result_artifacts.filter((a) => a.kind === "gaussian");
  const selector = page.getByLabel("가져온 결과 선택");
  await selector.selectOption(gaussians[0].id);
  await frame();
  const first = (await api("/projects/" + p.id + "/live-render")).session.pid;
  await selector.selectOption(gaussians[1].id);
  await page.waitForFunction(
    () => document.querySelector(".live-frame")?.dataset.state === "rendering",
    {},
    { timeout: 120000 },
  );
  let second;
  for (let i = 0; i < 100; i++) {
    second = (await api("/projects/" + p.id + "/live-render")).session?.pid;
    if (second && second !== first) break;
    await page.waitForTimeout(100);
  }
  await frame();
  check(
    "same-size Gaussian selection restarts native renderer",
    second && second !== first,
    { first, second },
  );
  await selector.selectOption(
    p.result_artifacts.find((a) => a.kind === "mesh").id,
  );
  await page.waitForSelector(".three-host[data-color-meshes]", {
    timeout: 60000,
  });
  check("selecting mesh opens correct viewer", true);
  const mixed = path.join(fixtureRoot, "mixed-dataset-results");
  const scan = await api("/scan-folder", "POST", { path: mixed });
  check(
    "real matching training metadata and payload recognised",
    scan.training.some((t) => t.valid && t.dataset_match === "yes"),
    scan.training,
  );
  opened = await api("/projects/from-folder", "POST", {
    path: mixed,
    artifacts: ["external.ply"],
  });
  p = opened.project;
  check(
    "matched training reused with independent external result",
    p.stages.train === "completed" &&
      !!p.training &&
      p.active_gaussian_artifact,
  );
  await goto(p);
  await frame();
  const external = (await api("/projects/" + p.id + "/live-render")).model
    .gaussians;
  await page.getByLabel("가져온 결과 선택").selectOption("training");
  let current;
  for (let i = 0; i < 100; i++) {
    current = await api("/projects/" + p.id + "/live-render");
    if (!current.artifact && current.session?.state === "rendering") break;
    await page.waitForTimeout(100);
  }
  await frame();
  check(
    "can return from independent Gaussian to project training",
    !current.artifact && current.model.gaussians !== external,
    { external, current: current.model.gaussians },
  );
  await page.screenshot({ path: out + "/artifact-variants.png" });
  check("no browser exceptions", report.errors.length === 0, report.errors);
  report.passed = true;
} catch (e) {
  report.error = String(e);
  await page.screenshot({ path: out + "/failure.png" }).catch(() => {});
} finally {
  for (const id of report.projects)
    await api("/projects/" + id + "/live-render/stop", "POST", {}).catch(
      () => {},
    );
  await browser.close();
  fs.writeFileSync(out + "/result.json", JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.passed ? 0 : 1;
