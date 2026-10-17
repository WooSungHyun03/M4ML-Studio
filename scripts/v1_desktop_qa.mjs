// Real Qt page input, native window resizing through its isolated QA host.
import fs from "node:fs";
import path from "node:path";
import { connectQt } from "./qt_cdp.mjs";
const [debug, project, out, commands] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const q = await connectQt(debug);
const report = {
  checks: [],
  screens: [],
  scope: "actual Qt native input on specified real trained project; not new training",
};
const check = (name, ok, detail) => {
  report.checks.push({ name, ok: !!ok, detail });
  if (!ok) throw Error(name);
};
async function shot(name) {
  if (process.env.STUDIO_QA_NATIVE_CAPTURE === "1") {
    const sequence = Date.now();
    fs.writeFileSync(commands, JSON.stringify({sequence, capture:path.relative(path.dirname(commands),path.join(out,name+'.png'))}));
    const ackPath = commands.replace(/\.[^.]+$/, '') + '.capture.json';
    let ack;
    for(let i=0;i<50;i++) {
      if(fs.existsSync(ackPath)) {
        ack=JSON.parse(fs.readFileSync(ackPath));
        if(ack.sequence===sequence)break;
      }
      await q.sleep(100);
    }
    if(ack?.sequence!==sequence || !ack.captured)throw Error('Native window capture failed: '+name);
    report.captureMethod=ack.method;
    report.screens.push(name);
    return;
  }
  let s;
  for (let attempt = 0; attempt < 3; attempt++) {
    try { s = await q.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false }); break; }
    catch (error) {
      (report.captureRetries ??= []).push({name, attempt, error: String(error)});
      if (attempt === 2) throw error;
      await q.sleep(250);
    }
  }
  fs.writeFileSync(out + "/" + name + ".png", Buffer.from(s.data, "base64"));
  report.screens.push(name);
}
async function resize(width, height) {
  const sequence = Date.now();
  fs.writeFileSync(
    commands,
    JSON.stringify({ size: [width, height], sequence }),
  );
  await q.sleep(700);
  const ack = JSON.parse(fs.readFileSync(commands.replace(/\.[^.]+$/, '') + '.ack.json'));
  check(`native window ${width}x${height}`, ack.request.sequence===sequence && ack.size[0]===width && ack.size[1]===height, ack);
  check('native bundled font supports Korean', ack.korean_glyphs, ack.font_family);
}
const requests = [];
const resourceUrls = new Map();
report.networkFailures = [];
await q.send("Network.enable");
q.onEvent((e) => {
  if (e.method === 'Network.requestWillBeSent') resourceUrls.set(e.params.requestId, e.params.request.url);
  if (e.method === 'Network.loadingFailed') report.networkFailures.push({url:resourceUrls.get(e.params.requestId),...e.params});
  if (
    e.method === "Network.requestWillBeSent" &&
    e.params.request.url.endsWith("/live-render/frame")
  )
    requests.push(JSON.parse(e.params.request.postData));
});
async function drag(selector, dx, dy) {
  const b = await q.evaluate(
    `(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width*.55,y:r.y+r.height*.5}})()`,
  );
  await q.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    ...b,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  for (let i = 1; i <= 6; i++)
    await q.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: b.x + (dx * i) / 6,
      y: b.y + (dy * i) / 6,
      button: "left",
      buttons: 1,
    });
  await q.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: b.x + dx,
    y: b.y + dy,
    button: "left",
    buttons: 0,
  });
  await q.sleep(800);
}
try {
  await q.waitFor("!!window.m4mlReady");
  check("native bridge active", await q.evaluate("!!window.__M4ML_DESKTOP__"));
  await q.waitFor('[...document.fonts].some(f=>f.family.includes("Noto Sans KR") && f.status==="loaded")',30000);
  check('bundled Korean web font loaded', await q.evaluate('[...document.fonts].some(f=>f.family.includes("Noto Sans KR") && f.status==="loaded")'));
  await q.evaluate(`setTimeout(()=>location.assign('/'),50);true`);
  await q.sleep(700);
  await q.waitFor('!!document.querySelector(".ptag")');
  check(
    "short Korean product promise",
    await q.evaluate(
      'document.querySelector(".ptag").innerText==="사진으로 3D 모델 만들기"',
    ),
  );
  await shot("01-welcome-dark");
  await q.click('[aria-label="환경 설정"]');
  for (const tab of ["처리 장치", "고급 정보", "모델 파일", "라이선스"]) {
    await q.click('[role="tab"]', tab);
    await q.sleep(600);
    await shot("settings-" + tab);
    if (tab === "고급 정보") {
      await q.waitFor('!!document.querySelector(".engine-card")');
      const text = await q.evaluate(
        'document.querySelector(".drawer.settings").innerText',
      );
      check(
        "advanced fields curated without tensor dump",
        !text.includes("checkpoint_tensors") &&
          !text.includes("tracker.backbone") &&
          text.length < 12000,
        { characters: text.length },
      );
    }
    if (tab === "라이선스") {
      await q.click(".drawer.settings button", "원문 보기");
      await q.waitFor(
        `!!document.querySelector('[aria-label="라이선스 원문"] pre')`,
      );
      check(
        "packaged original licence readable",
        await q.evaluate(
          `document.querySelector('[aria-label="라이선스 원문"] pre').textContent.length>1000`,
        ),
      );
    }
  }
  await q.click('.drawer.settings button[title="테마 전환"]');
  await q.click('.drawer.settings [aria-label="닫기"]');
  await shot("02-welcome-light");
  await q.evaluate(
    `setTimeout(()=>location.assign('/?project=${project}'),50);true`,
  );
  await q.waitFor('!!document.querySelector(".stage-tabs")', 60000);
  for (const menu of ["파일", "편집", "보기", "작업", "창", "도움말"]) {
    await q.click(".menubar button", menu);
    await shot("menu-" + menu);
    await q.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Escape",
      code: "Escape",
      windowsVirtualKeyCode: 27,
    });
  }
  check("six native page menus opened", true);
  for (const name of [
    "사진",
    "카메라 정합",
    "객체 선택",
    "마스크 검토",
    "3D 재구성",
    "3D 모델",
  ]) {
    await q.click(".stage-tab", name);
    await q.sleep(800);
    await shot("stage-" + name);
    check(
      "stage reachable " + name,
      await q.evaluate(
        `!![...document.querySelectorAll('.stage-tab')].find(x=>x.textContent.includes(${JSON.stringify(name)})&&x.getAttribute('aria-current')==='step')`,
      ),
    );
  }
  await q.click(".toolbar button", "표시 설정");
  await q.waitFor('!!document.querySelector(".task-settings")');
  for (const group of [
    "카메라 정합",
    "객체 선택",
    "마스크 검토",
    "3D 재구성",
    "3D 모델 생성",
    "표시",
  ]) {
    await q.click(".task-settings nav button", group);
    await shot("parameters-" + group);
  }
  check("all provider settings reachable", true);
  await q.click('.task-settings [aria-label="세부 설정 닫기"]');
  await q.click('[aria-label="환경 설정"]');
  await q.click('.drawer.settings button[title="테마 전환"]');
  await q.click('.drawer.settings [aria-label="닫기"]');
  await q.click('[aria-label="3D 표시 방식"] button', "메시");
  await q.waitFor(
    'Number(document.querySelector(".three-host")?.dataset.colorMeshes)>0',
    60000,
  );
  await shot("mesh-dark");
  await resize(1024, 640);
  await drag(".splitter.y", 0, -270);
  const boxes = await q.evaluate(
    `(()=>{const f=document.querySelector('.mesh-frame').getBoundingClientRect(),t=document.querySelector('.tool-col').getBoundingClientRect();return {frame:[f.top,f.bottom],tools:[t.top,t.bottom],scroll:document.querySelector('.tool-col').scrollHeight,client:document.querySelector('.tool-col').clientHeight}})()`,
  );
  check(
    "short native viewport contains scrollable tools",
    boxes.tools[0] >= boxes.frame[0] && boxes.tools[1] <= boxes.frame[1] + 1,
    boxes,
  );
  await shot("mesh-minimum-window");
  await resize(1600, 1000);
  await q.send("Network.enable");
  await q.click('[aria-label="3D 표시 방식"] button', "실시간 렌더");
  await q.waitFor(
    'document.querySelector(".live-frame")?.dataset.state==="rendering" && Number(document.querySelector(".live-surface")?.dataset.frames)>0',
    180000,
  );
  for (let i = 0; i < 100 && !requests.length; i++) await q.sleep(200);
  await q.sleep(1000);
  check("native trained project camera is upright", requests.at(-1)?.view[5] > 0, {
    upY: requests.at(-1)?.view[5],
  });
  for (const [dx, dy] of [
    [80, 0],
    [-80, 0],
    [0, 70],
    [0, -70],
    [60, 50],
    [-60, -50],
  ]) {
    await q.click('[aria-label="시점 초기화"]');
    await q.sleep(800);
    const before = requests.at(-1);
    await drag(".live-surface", dx, dy);
    const after = requests.at(-1);
    check(
      `actual orbit ${dx},${dy}`,
      after &&
        before &&
        JSON.stringify(after.view) !== JSON.stringify(before.view) &&
        after.view[5] > 0,
      { upY: after?.view[5] },
    );
  }
  await q.click('[aria-label="이동"]');
  const before = requests.at(-1);
  await drag(".live-surface", 50, 25);
  check(
    "pan changes actual camera",
    JSON.stringify(before.view) !== JSON.stringify(requests.at(-1).view),
  );
  const b = await q.evaluate(
    '(()=>{const r=document.querySelector(".live-surface").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()',
  );
  const pre = requests.at(-1);
  await q.send("Input.dispatchMouseEvent", {
    type: "mouseWheel",
    ...b,
    deltaX: 0,
    deltaY: -180,
  });
  await q.sleep(1000);
  check(
    "zoom changes actual camera",
    JSON.stringify(pre.view) !== JSON.stringify(requests.at(-1).view),
  );
  await q.click('[aria-label="화면 맞춤"]');
  await q.sleep(700);
  check("fit retains upright navigation", requests.at(-1).view[5] > 0);
  await shot("gaussian-six-direction-verified");
  await q.click('[aria-label="3D 표시 방식"] button', "메시");
  await q.waitFor(
    'Number(document.querySelector(".three-host")?.dataset.colorMeshes)>0',
  );
  check("return to actual color mesh", true);
  check("no Qt JS exceptions", q.errors.length === 0, q.errors);
  report.passed = true;
} catch (e) {
  report.error = String(e);
  await shot("failure").catch(() => {});
} finally {
  report.requests = requests;
  report.errors = q.errors;
  q.close();
  fs.writeFileSync(out + "/result.json", JSON.stringify(report, null, 2));
}
console.log(
  JSON.stringify({ ...report, requests: report.requests.length }, null, 2),
);
process.exitCode = report.passed ? 0 : 1;
