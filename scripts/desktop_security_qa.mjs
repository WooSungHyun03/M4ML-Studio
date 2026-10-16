// Run against an isolated REAL Qt window with test-only DevTools enabled.
// node scripts/desktop_security_qa.mjs CDP_BASE FOREIGN_URL OUTPUT.json
// Reports only credential/bridge presence booleans; never records the credential.
import fs from "node:fs";
const [cdp, foreign, output] = process.argv.slice(2);
const targets = await (await fetch(cdp + "/json")).json();
const target = targets.find((t) => t.type === "page");
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));
let seq = 0;
const pending = new Map();
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, timeout } = pending.get(msg.id);
    clearTimeout(timeout);
    pending.delete(msg.id);
    resolve(msg);
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  const timeout = setTimeout(() => { pending.delete(id); reject(new Error("CDP timeout: " + method)); }, 15000);
  pending.set(id, { resolve, timeout });
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.error || r.result?.exceptionDetails) throw new Error("CDP evaluation failed");
  return r.result.result.value;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const inspect = () => evaluate(`(async () => ({
  url: location.href,
  token: typeof window.__M4ML_TOKEN__ === "string",
  bridge: !!window.m4mlReady && typeof (await window.m4mlReady).pickFolder === "function",
  editor: !!document.querySelector(".menubar")
}))()`);
const before = await inspect();
const trustedOrigin = new URL(before.url).origin;
const checks = [{ name: "trusted Qt UI has credential and native bridge", pass: before.token && before.bridge }];
const observations = [];
try {
  for (const url of [foreign, "data:text/html,<title>isolated-data-fixture</title>"]) {
    await evaluate(`setTimeout(() => location.assign(${JSON.stringify(url)}), 50); true`);
    await sleep(1800);
    const after = await inspect();
    observations.push(after);
    const blocked = new URL(after.url).origin === trustedOrigin;
    checks.push({ name: "foreign navigation blocked: " + new URL(url).protocol, pass: blocked });
    checks.push({ name: "trusted UI retained after attempted navigation", pass: blocked && after.token && after.bridge });
    if (!blocked) break; // preserve observed failure; don't navigate a second time
  }
  const pass = checks.every((c) => c.pass);
  fs.writeFileSync(output, JSON.stringify({ pass, before, observations, checks }, null, 2) + "\n");
  console.log(JSON.stringify({ pass, checks }));
  process.exitCode = pass ? 0 : 1;
} finally {
  ws.close();
}
