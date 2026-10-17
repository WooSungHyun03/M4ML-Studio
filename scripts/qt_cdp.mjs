// Test-only, page-scoped DevTools client for real QtWebEngine windows.
export async function connectQt(base) {
  const targets = await (await fetch(base + "/json")).json();
  const target = targets.find((t) => t.type === "page");
  if (!target)
    throw new Error("No Qt page on the requested test DevTools endpoint");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve) =>
    ws.addEventListener("open", resolve, { once: true }),
  );
  let seq = 0;
  const pending = new Map();
  const errors = [];
  const listeners = [];
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      clearTimeout(p.timeout);
      pending.delete(msg.id);
      msg.error
        ? p.reject(new Error(msg.error.message))
        : p.resolve(msg.result);
    }
    if (msg.method === "Runtime.exceptionThrown")
      errors.push(msg.params.exceptionDetails.text);
    if (
      msg.method === "Runtime.consoleAPICalled" &&
      msg.params.type === "error"
    )
      errors.push(
        msg.params.args.map((a) => a.value ?? a.description).join(" "),
      );
    for (const listener of listeners) listener(msg);
  });
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(new Error("CDP timeout: " + method));
      }, 15000);
      pending.set(id, { resolve, reject, timeout });
      ws.send(JSON.stringify({ id, method, params }));
    });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (expression, timeout = 30000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      if (await evaluate(expression)) return;
      await sleep(200);
    }
    throw new Error("Qt UI wait timed out: " + expression.slice(0, 160));
  };
  const click = async (selector, text = "") => {
    const box = await evaluate(`(() => {
      const e = [...document.querySelectorAll(${JSON.stringify(selector)})].find(e => e.textContent.includes(${JSON.stringify(text)}));
      if (!e || e.disabled) return null;
      e.scrollIntoView({block:"center"});
      const b = e.getBoundingClientRect(); return {x:b.x+b.width/2, y:b.y+b.height/2};
    })()`);
    if (!box)
      throw new Error(
        "Qt UI control missing or disabled: " + selector + " / " + text,
      );
    await send("Input.dispatchMouseEvent", {
      type: "mousePressed",
      ...box,
      button: "left",
      buttons: 1,
      clickCount: 1,
    });
    await send("Input.dispatchMouseEvent", {
      type: "mouseReleased",
      ...box,
      button: "left",
      buttons: 0,
      clickCount: 1,
    });
  };
  await send("Runtime.enable");
  await send("Page.enable");
  const navigate = async (url, selector, timeout = 60000) => {
    const target = new URL(url, await evaluate('location.href')).href;
    const marker = `${Date.now()}-${Math.random()}`;
    await evaluate(`window.__M4ML_QA_NAV__=${JSON.stringify(marker)};setTimeout(()=>location.assign(${JSON.stringify(target)}),50);true`);
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      try {
        if (await evaluate(`window.__M4ML_QA_NAV__!==${JSON.stringify(marker)} && location.href===${JSON.stringify(target)} && !!document.querySelector(${JSON.stringify(selector)})`)) return;
      } catch (error) {
        if (!/context|navigat/i.test(String(error))) throw error;
      }
      await sleep(100);
    }
    throw Error('New native document did not become ready: '+target);
  };
  return {
    send,
    evaluate,
    sleep,
    waitFor,
    click,
    navigate,
    errors,
    onEvent: (listener) => listeners.push(listener),
    close: () => ws.close(),
  };
}
