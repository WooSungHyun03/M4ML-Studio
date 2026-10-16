// Repeated real Qt starts, large colored-mesh loads and panel responsiveness.
// All state belongs to the selected output tree; no global input or cache flush.
import fs from "node:fs";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { connectQt } from "./qt_cdp.mjs";
const [
  output = "evidence/quality-harness/continuous/qt-benchmark",
  count = "3",
  project = "9ca165c0-24c7-490d-ac06-2e3f5107ae31",
  data = "evidence/quality-harness/continuous/benchmark-data",
] = process.argv.slice(2);
const out = path.resolve(output);
fs.mkdirSync(out, { recursive: false });
const samples = [];
const report = {
  scope:
    "first/new-profile process start and warm repeats, not OS cold boot; GPU pipeline may run concurrently",
  samples,
};
function memoryTree(parent) {
  const rows = execFileSync("ps", ["-eo", "pid=,ppid=,rss="], {
    encoding: "utf8",
  })
    .trim()
    .split("\n")
    .map((l) => l.trim().split(/\s+/).map(Number));
  const pids = new Set([parent]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const [pid, ppid] of rows)
      if (pids.has(ppid) && !pids.has(pid)) {
        pids.add(pid);
        changed = true;
      }
  }
  return {
    pids: [...pids],
    rss_mb:
      rows
        .filter(([pid]) => pids.has(pid))
        .reduce((sum, row) => sum + row[2], 0) / 1024,
  };
}
for (let i = 0; i < Number(count); i++) {
  const log = fs.openSync(`${out}/start-${i}.log`, "w");
  const start = Date.now();
  const child = spawn(
    path.resolve(".runtime/bin/python"),
    ["-m", "studio.desktop"],
    {
      env: {
        ...process.env,
        STUDIO_PORT: "8774",
        STUDIO_DATA: path.resolve(data),
        XDG_CONFIG_HOME: `${out}/config`,
        XDG_DATA_HOME: `${out}/data`,
        XDG_CACHE_HOME: `${out}/cache`,
        QTWEBENGINE_REMOTE_DEBUGGING: "127.0.0.1:9333",
      },
      stdio: ["ignore", log, log],
    },
  );
  let q;
  const sample = { trial: i, pid: child.pid };
  samples.push(sample);
  try {
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        q = await connectQt("http://127.0.0.1:9333");
        break;
      } catch {
        await new Promise((r) => setTimeout(r, 200));
      }
    }
    if (!q) throw new Error("Qt DevTools unavailable");
    await q.waitFor('!!document.querySelector(".menubar")');
    sample.start_ms = Date.now() - start;
    await q.sleep(2000);
    sample.home = memoryTree(child.pid);
    const t = Date.now();
    await q.evaluate(
      `setTimeout(() => location.assign(location.origin + "/?project=${encodeURIComponent(project)}"), 50); true`,
    );
    await q.waitFor('!!document.querySelector(".stage-tabs")');
    await q.click(".stage-tab", "3D 모델");
    await q.waitFor(
      'Number(document.querySelector(".three-host")?.dataset.colorMeshes || 0) > 0',
      60000,
    );
    sample.mesh_load_ms = Date.now() - t;
    sample.model = await q.evaluate(
      `fetch('/api/projects/${encodeURIComponent(project)}').then(r=>r.json()).then(p=>({vertices:p.mesh.vertices,triangles:p.mesh.triangles}))`,
    );
    sample.webgl = await q.evaluate(
      '(() => {const g=document.querySelector(".three-host canvas").getContext("webgl2");const e=g.getExtension("WEBGL_debug_renderer_info");return e?g.getParameter(e.UNMASKED_RENDERER_WEBGL):g.getParameter(g.RENDERER)})()',
    );
    sample.mesh = memoryTree(child.pid);
    sample.panel_ms = [];
    for (let n = 0; n < 4; n++) {
      const before = await q.evaluate(
        '!!document.querySelector("aside.dock.right")',
      );
      const t = Date.now();
      await q.click('button[title="속성 패널 (Ctrl+I)"]');
      await q.waitFor(
        `!!document.querySelector("aside.dock.right") !== ${before}`,
      );
      sample.panel_ms.push(Date.now() - t);
    }
    sample.gpu = execFileSync(
      "nvidia-smi",
      ["--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader"],
      { encoding: "utf8" },
    ).trim();
    if (i === 0) {
      const { data } = await q.send("Page.captureScreenshot", {
        format: "png",
      });
      fs.writeFileSync(
        `${out}/actual-large-mesh.png`,
        Buffer.from(data, "base64"),
      );
    }
    sample.errors = q.errors;
    if (q.errors.length) throw new Error("Qt console errors");
    await q.evaluate(
      "setTimeout(() => window.m4mlReady.then(b => b.quit()), 100); true",
    );
    q.close();
    q = null;
    for (let n = 0; n < 100 && child.exitCode == null; n++)
      await new Promise((r) => setTimeout(r, 200));
    if (child.exitCode !== 0) throw new Error("Qt did not stop cleanly");
    sample.exit = child.exitCode;
    sample.profile_release_warning = fs
      .readFileSync(`${out}/start-${i}.log`, "utf8")
      .includes("WebEnginePage still not deleted");
    if (sample.profile_release_warning)
      throw new Error("Qt profile destroyed before its page");
  } catch (error) {
    sample.error = String(error);
  } finally {
    q?.close();
    if (child.exitCode == null) {
      child.kill("SIGTERM");
      await new Promise((r) => setTimeout(r, 1000));
    }
    fs.closeSync(log);
    fs.writeFileSync(`${out}/result.json`, JSON.stringify(report, null, 2));
  }
  if (sample.error) break;
}
report.pass =
  samples.length === Number(count) &&
  samples.every((s) => !s.error && s.exit === 0);
const values = (key) =>
  samples
    .map((s) => s[key])
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
report.summary = {
  start_ms: values("start_ms"),
  mesh_load_ms: values("mesh_load_ms"),
  panel_ms: samples.flatMap((s) => s.panel_ms || []).sort((a, b) => a - b),
};
fs.writeFileSync(`${out}/result.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
process.exitCode = report.pass ? 0 : 1;
