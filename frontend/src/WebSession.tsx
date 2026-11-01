// Web service only: waiting room and the "continue in another browser" link.
import { useEffect, useState } from "react";
import { Copy, Hourglass, Link2 } from "lucide-react";
import { csrfToken, turnstileSiteKey } from "./platform";

export interface Admission {
  slot: "active" | "queued" | "full";
  position?: number;
}

/** Shown while all active workspaces are taken. Polling keeps this browser's place. */
export function WaitingRoom({ initial, onAdmitted }: { initial: Admission; onAdmitted: () => void }) {
  const [state, setState] = useState(initial);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const r = await fetch("/api/web/queue");
        if (!r.ok) return;
        const next = (await r.json()) as Admission;
        if (!alive) return;
        if (next.slot === "active") onAdmitted();
        else setState(next);
      } catch {}
    };
    const t = setInterval(poll, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [onAdmitted]);
  return (
    <div className="boot-error" role="status" aria-live="polite">
      <p style={{ display: "flex", gap: 8, alignItems: "center", margin: 0 }}>
        <Hourglass size={18} />
        <b>{state.slot === "full" ? "지금은 이용자가 많습니다" : `대기 중 · ${state.position ?? "-"}번째`}</b>
      </p>
      <p style={{ marginBottom: 0 }}>
        {state.slot === "full"
          ? "대기 자리도 모두 찼습니다. 잠시 뒤 다시 시도하세요."
          : "앞선 작업 공간이 비면 자동으로 들어갑니다. 이 창을 닫으면 순서를 잃습니다."}
      </p>
    </div>
  );
}

/** One-time link that moves this workspace to another browser (rotates the session). */
export function RecoveryLink() {
  const [link, setLink] = useState(""),
    [error, setError] = useState(""),
    [copied, setCopied] = useState(false);
  async function create() {
    setError("");
    try {
      const r = await fetch("/api/web/session/recovery", { method: "POST", headers: { "x-csrf-token": csrfToken() } });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "링크를 만들지 못했습니다.");
      setLink(`${location.origin}/recover#${body.token}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="callout" style={{ marginTop: 16, display: "block" }}>
      <b style={{ display: "flex", gap: 6, alignItems: "center" }}><Link2 size={14} />다른 브라우저에서 이어하기</b>
      <p className="hint" style={{ margin: "6px 0" }}>
        이 작업 공간은 이 브라우저에만 연결되어 있습니다. 링크를 가진 사람은 누구나 작업 공간을 열 수 있으니 다른 사람에게 보내지 마세요.
        링크는 한 번만 쓸 수 있고, 사용하면 이 브라우저의 연결은 끊깁니다.
      </p>
      {link ? (
        <div className="row" style={{ gap: 6 }}>
          <input className="input" readOnly value={link} aria-label="이어하기 링크" style={{ flex: 1 }} onFocus={(e) => e.target.select()} />
          <button className="btn s" onClick={() => void navigator.clipboard?.writeText(link).then(() => setCopied(true))}>
            <Copy size={12} />{copied ? "복사됨" : "복사"}
          </button>
        </div>
      ) : (
        <button className="btn s" onClick={() => void create()}>링크 만들기</button>
      )}
      {error && <p className="err" style={{ margin: "6px 0 0" }}>{error}</p>}
    </div>
  );
}


/** Delete this browser's whole workspace now (otherwise it expires after 7 days). */
export function DeleteWorkspace() {
  const [error, setError] = useState("");
  async function remove() {
    if (!window.confirm("이 작업 공간의 모든 프로젝트와 사진, 결과를 서버에서 지울까요?\n\n바로 지워지며 되돌릴 수 없습니다. 실행 중인 작업도 중지됩니다.")) return;
    try {
      const r = await fetch("/api/web/session", { method: "DELETE", headers: { "x-csrf-token": csrfToken() } });
      if (!r.ok) throw new Error((await r.json()).detail || "지우지 못했습니다.");
      location.replace("/");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <p className="hint" style={{ marginTop: 12 }}>
      올린 사진과 결과는 작업 공간을 처음 만든 날로부터 7일이 지나면 자동으로 지워집니다.{" "}
      <button className="btn s danger" onClick={() => void remove()}>지금 작업 공간 지우기</button>
      {error && <span className="err"> {error}</span>}
    </p>
  );
}


declare global {
  interface Window {
    turnstile?: { render: (el: HTMLElement, options: Record<string, unknown>) => string };
  }
}

/** First visit (web service with Turnstile): usage notice, consent, then the bot check. */
export function Consent({ onToken, error }: { onToken: (token: string) => void; error?: string }) {
  const [agreed, setAgreed] = useState(false);
  useEffect(() => {
    if (!agreed) return;
    const sitekey = turnstileSiteKey();
    const box = document.getElementById("m4ml-turnstile");
    if (!sitekey || !box) return;
    const draw = () => window.turnstile?.render(box, { sitekey, action: "session", callback: onToken });
    if (window.turnstile) return void draw();
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.onload = draw;
    document.head.append(script);
  }, [agreed, onToken]);
  return (
    <div className="boot-error" role="dialog" aria-label="이용 안내">
      <h2 style={{ marginTop: 0 }}>M4ML Studio 웹 이용 안내</h2>
      <ul style={{ paddingLeft: 18, lineHeight: 1.7 }}>
        <li>비상업적 연구·평가 목적으로만 쓸 수 있습니다. 결과물도 상업적으로 쓸 수 없습니다.</li>
        <li>올린 사진과 결과는 이 서버에 저장되며 작업 공간을 만든 날로부터 7일 뒤 자동으로 지워집니다. 언제든 직접 지울 수 있습니다.</li>
        <li>다른 사람의 얼굴이나 개인정보, 권리가 있는 사진은 올리지 마세요.</li>
        <li>자동 등록을 막기 위해 Cloudflare 확인을 거칩니다.</li>
      </ul>
      <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        위 내용을 확인했습니다
      </label>
      <div id="m4ml-turnstile" style={{ marginTop: 14, minHeight: agreed ? 70 : 0 }} />
      {error && <p className="err">{error}</p>}
    </div>
  );
}
