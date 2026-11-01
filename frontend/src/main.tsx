import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import { ensureWebSession, redeemRecovery, TurnstileRequired } from "./api";
import { platform } from "./platform";
import { Consent, WaitingRoom } from "./WebSession";
import "./style.css";

document.documentElement.dataset.platform = platform(); // lets CSS adapt the web service only
const root = createRoot(document.getElementById("root")!);
const app = () =>
  root.render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  );

async function start() {
  if (platform() !== "web") return app();
  try {
    if (location.pathname === "/recover") {
      // The secret is in the fragment (never sent to servers or logged); remove it from the
      // address bar and history before doing anything else.
      const token = location.hash.slice(1);
      history.replaceState(null, "", "/");
      if (token) await redeemRecovery(token);
    }
    await admit();
  } catch (e) {
    if (e instanceof TurnstileRequired) return consent();
    root.render(<div className="boot-error" role="alert">{(e as Error).message}</div>);
  }
}
async function admit(turnstile?: string) {
  const admission = await ensureWebSession(turnstile);
  if (admission.slot === "active") return app();
  root.render(<WaitingRoom initial={admission} onAdmitted={app} />);
}
function consent(error?: string) {
  root.render(
    <Consent
      error={error}
      onToken={(token) => void admit(token).catch((e) => consent((e as Error).message))}
    />,
  );
}
void start();
