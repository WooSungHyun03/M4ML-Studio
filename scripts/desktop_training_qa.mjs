// Actual original GPU training -> automatic color TSDF in the REAL Qt editor.
// Use ONLY a copied/disposable test project, never an existing user project.
// node scripts/desktop_training_qa.mjs CDP_BASE PROJECT_ID OUTPUT_DIR
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { connectQt } from "./qt_cdp.mjs";
const [cdp, project, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const q = await connectQt(cdp);
const resumeFile = process.env.STUDIO_QA_RESUME_RESULT;
const saved = resumeFile
  ? JSON.parse(fs.readFileSync(resumeFile, "utf8"))
  : null;
if (
  saved &&
  (saved.project !== project ||
    saved.training?.iterations !== 100 ||
    !saved.mesh?.path ||
    !saved.checks.every((c) => c.pass))
)
  throw new Error(
    "Only a completed, verified100/256 training+mesh smoke can resume at the viewer check",
  );
const report = saved
  ? {
      ...saved,
      pass: false,
      resumedFrom: resumeFile,
      checks: [...saved.checks],
    }
  : {
      pass: false,
      project,
      scope:
        "original GPU100 / TSDF256 smoke, not convergence or new camera/SAM",
      checks: [],
    };
delete report.error;
const check = (name, pass, detail) => {
  report.checks.push({ name, pass: !!pass, detail });
  if (!pass) throw new Error(name);
};
const shot = async (name) => {
  const { data } = await q.send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(`${out}/${name}.png`, Buffer.from(data, "base64"));
};
let confirmSeen = false;
q.onEvent((event) => {
  if (event.method === "Page.javascriptDialogOpening" && !confirmSeen) {
    confirmSeen =
      event.params.type === "confirm" && event.params.message.includes("100회");
    // Accept the actual confirmation dialog only for this explicit smoke configuration.
    q.send("Page.handleJavaScriptDialog", { accept: confirmSeen }).catch(
      (e) => {
        report.dialogError = String(e);
      },
    );
  }
});
try {
  check(
    "actual native desktop",
    await q.evaluate("!!window.__M4ML_DESKTOP__ && !!window.m4mlReady"),
  );
  await q.navigate('/?project='+project,'.stage-tabs');
  let doc;
  if (saved) {
    doc = await q.evaluate(
      `fetch("/api/projects/${project}").then(r => r.json())`,
    );
    check(
      "resume uses identical completed training and mesh",
      doc.training?.path === saved.training.path &&
        doc.mesh?.path === saved.mesh.path &&
        doc.stages.mesh === "completed",
    );
  } else {
    await q.click(".stage-tab", "3D 재구성");
    await q.click('.toolbar button','세부 설정');
    await q.waitFor('!!document.querySelector(".task-settings input[type=number]")');
    async function fillSetting(label,text){
      const selector=await q.evaluate(`(()=>{const e=[...document.querySelectorAll('.task-settings label')].find(e=>e.textContent.includes(${JSON.stringify(label)}));if(!e)return null;const i=e.querySelector('input');i.setAttribute('data-native-test-input','true');return '[data-native-test-input=true]'})()`);
      if(!selector)throw Error('Setting missing: '+label);
      await q.click(selector);await q.send('Input.dispatchKeyEvent',{type:'keyDown',key:'a',code:'KeyA',modifiers:2,windowsVirtualKeyCode:65});await q.send('Input.dispatchKeyEvent',{type:'keyUp',key:'a',code:'KeyA',modifiers:2,windowsVirtualKeyCode:65});await q.send('Input.insertText',{text});
      await q.evaluate(`document.querySelector(${JSON.stringify(selector)}).removeAttribute('data-native-test-input');true`);
    }
    await fillSetting('학습 횟수','100');await fillSetting('알파 Polarization 가중치','0.45');await q.click('.task-settings button','저장');
    await q.waitFor(`fetch('/api/projects/${project}/task-settings').then(r=>r.json()).then(s=>s.training.values.iterations===100)`);
    await q.click('.task-settings nav button','3D 모델 생성');await fillSetting('생성 해상도','256');await q.click('.task-settings button','저장');
    await q.waitFor(`fetch('/api/projects/${project}/task-settings').then(r=>r.json()).then(s=>s.mesh.values.mesh_res===256)`);
    check('test-only persisted schema settings',true);
    await q.click('.task-settings button[aria-label="세부 설정 닫기"]');
    await q.waitFor(
      '[...document.querySelectorAll(".toolbar button")].some(b => b.textContent.includes("새로 학습") && !b.disabled)',
      60000,
    );
    const previous = await q.evaluate(
      `fetch("/api/projects/${project}").then(r => r.json())`,
    );
    const previousJob = previous.jobs?.find((j) => j.stage === "train")?.id;
    await shot("01-explicit-smoke-settings");
    await q.click(".toolbar button", "새로 학습");
    await q.waitFor('!!document.querySelector(".badge.acc")', 30000);
    check("actual100-iteration approval dialog observed", confirmSeen);
    const observations = [];
    const end = Date.now() + 240000;
    do {
      doc = await q.evaluate(
        `fetch("/api/projects/${project}").then(r => r.json())`,
      );
      observations.push({
        time: Date.now(),
        train: doc.stages.train,
        mesh: doc.stages.mesh,
        active: doc.jobs
          ?.filter((j) => j.state === "running")
          .map((j) => ({ stage: j.stage, current: j.current, total: j.total })),
        cuda: execFileSync(
          "nvidia-smi",
          ["--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
          { encoding: "utf8" },
        ).trim(),
      });
      const failed = doc.jobs?.find(
        (j) =>
          j.state === "failed" &&
          j.created > new Date(end - 240000).toISOString(),
      );
      if (failed) throw new Error(JSON.stringify(failed));
      if (
        doc.jobs?.find((j) => j.stage === "train")?.id !== previousJob &&
        doc.training?.iterations === 100 &&
        doc.stages.mesh === "completed"
      )
        break;
      await q.sleep(500);
    } while (Date.now() < end);
    report.observations = observations;
    report.training = doc.training;
    report.mesh = doc.mesh;
    report.jobs = doc.jobs?.slice(0, 3);
    const trainJob = doc.jobs?.find((j) => j.stage === "train");
    const request = JSON.parse(trainJob?.request || "{}");
    // Qt can acknowledge the native dialog itself before DevTools' reply. Test
    // the actual approval contract, not a Chromium-only acknowledgement detail.
    check(
      "confirmed100 request actually submitted by UI",
      request.confirmed === true &&
        request.iterations === 100 &&
        request.parameters?.lambda_pa === 0.45 &&
        request.mesh_request?.parameters?.mesh_res === 256,
    );
    check(
      "new training job, not previous completed result",
      trainJob?.id !== previousJob,
    );
    check(
      "original100 training completed",
      doc.training?.iterations === 100 && doc.stages.train === "completed",
    );
    check(
      "automatic color TSDF mesh completed",
      doc.stages.mesh === "completed" &&
        doc.mesh?.colors &&
        doc.mesh?.vertices > 0 &&
        doc.mesh?.triangles > 0,
    );
    check(
      "verified color conversion",
      doc.mesh.color_roundtrip_max_error < 1 / 255,
    );
  }
  await q.click(".stage-tab", "3D 모델");
  await q.waitFor(
    '[...document.querySelectorAll(".toolbar .seg button")].some(b => b.textContent.includes("메시") && !b.disabled)',
    60000,
  );
  await q.click('[aria-label="3D 표시 방식"] button', "메시");
  await q.waitFor(
    'Number(document.querySelector(".three-host")?.dataset.colorMeshes || 0) > 0',
    60000,
  );
  await q.sleep(1500);
  await shot("02-actual-color-mesh");
  check("actual color mesh displayed", true);
  check("no console exceptions", q.errors.length === 0, q.errors);
  report.pass = true;
} catch (error) {
  report.error = String(error);
  await shot("failure").catch(() => {});
} finally {
  fs.writeFileSync(
    `${out}/result.json`,
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      pass: report.pass,
      error: report.error,
      checks: report.checks,
    }),
  );
  q.close();
}
process.exitCode = report.pass ? 0 : 1;
