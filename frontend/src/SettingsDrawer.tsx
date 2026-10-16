import { Fragment, useEffect, useState } from "react";
import { CircleCheck, CircleX, Moon, Power, Sun, X } from "lucide-react";
import { api, post } from "./api";
import type { Health } from "./api";

type Engines = {
  engines: Record<string, Record<string, unknown>>;
  runtime: Record<string, unknown>;
  runtime_path: string;
  gpus: Health["gpus"];
  live_sessions: Record<string, Record<string, unknown>>;
  licenses: { component: string; license: string; commercial: boolean | null }[];
};
const CAPABILITY: Record<string, string> = {
  camera: "카메라 정합",
  segmentation: "객체 선택 · 마스크 생성",
  training: "3D 재구성",
  mesh: "3D 모델 생성",
  export: "3D 모델 보기 · 내보내기",
};

function Value({ v }: { v: unknown }) {
  if (v == null) return <span className="t4">—</span>;
  if (typeof v === "boolean") return v ? <span className="ok">예</span> : <span className="t3">아니요</span>;
  if (Array.isArray(v)) return <span>{v.join(", ")}</span>;
  if (typeof v === "object") return <code style={{ fontSize: 11 }}>{JSON.stringify(v)}</code>;
  return <span>{String(v)}</span>;
}

export function SettingsDrawer({
  health,
  onClose,
  onRefresh,
  theme,
  setTheme,
  onShutdown,
}: {
  health: Health | null;
  onClose: () => void;
  onRefresh: () => void;
  theme: string;
  setTheme: (t: string) => void;
  onShutdown: () => void;
}) {
  const [tab, setTab] = useState<"device" | "engines" | "model" | "license">("device"),
    [info, setInfo] = useState<Engines | null>(null),
    [path, setPath] = useState(""),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    if (tab === "engines" || tab === "license") api<Engines>("/engines").then(setInfo).catch((e) => setError(e.message));
  }, [tab]);
  async function saveCheckpoint() {
    setError("");
    try {
      await api("/settings/checkpoint", { method: "PUT", body: JSON.stringify({ path }) });
      setMessage("경로를 저장했습니다. 실제 모델 구조는 처음 사용할 때 다시 검사합니다.");
      onRefresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function diagnostics() {
    const report = await api("/diagnostics");
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "M4ML-Studio-diagnostics.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="drawer settings" role="dialog" aria-label="설정">
      <div className="drawer-h">
        <h2>설정</h2>
        <span className="sp" />
        <button className="icon-btn" aria-label={theme === "light" ? "어두운 테마" : "밝은 테마"} title="테마 전환" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? <Moon size={16} /> : <Sun size={16} />}</button>
        <button className="icon-btn" aria-label="닫기" onClick={onClose}><X size={16} /></button>
      </div>
      <div className="tabs" role="tablist">
        {([
          ["device", "처리 장치"],
          ["engines", "고급 정보"],
          ["model", "모델 파일"],
          ["license", "라이선스"],
        ] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      <div className="scroll" style={{ flex: 1 }}>
        {tab === "device" && (
          <>
            <div className="sec">
              <div className="sec-h"><b>GPU</b></div>
              {health?.gpus.length ? health.gpus.map((g) => (
                <div key={g.index} className="kv" style={{ marginBottom: 10 }}>
                  <span>장치 {g.index}</span><span>{g.name}</span>
                  <span>GPU 메모리</span><span>{((g.total_mb - g.free_mb) / 1024).toFixed(1)} / {(g.total_mb / 1024).toFixed(1)} GB 사용</span>
                  <span>드라이버</span><span>{g.driver || "—"}</span>
                </div>
              )) : <p className="hint">NVIDIA GPU를 찾지 못했습니다. {health?.gpu_error || ""}</p>}
            </div>
            <div className="sec">
              <div className="sec-h"><b>처리 준비 상태</b></div>
              <div className="kv">
                <span>3D 재구성 · 객체 선택</span><span>{health?.runtime_status?.available ? <span className="ok">GPU 사용 가능</span> : <span className="err">사용 불가</span>}</span>
                <span>카메라 정합</span><span>{health?.colmap?.available ? (health.colmap.gpu ? <span className="ok">GPU 가속</span> : <span className="warn">CPU 전용</span>) : <span className="err">엔진 없음</span>}</span>
                <span>객체 선택 모델 파일</span><span>{health?.checkpoint_exists ? <span className="ok">확인됨</span> : <span className="err">없음</span>}</span>
                <span>저장 공간</span><span>{health ? Math.floor(health.disk_free / 1024 ** 3) + " GB 여유" : "—"}</span>
              </div>
            </div>
            <div className="sec">
              <div className="row">
                <button className="btn" onClick={() => void diagnostics()}>진단 파일 저장</button>
                <span className="hint">프로젝트 경로·사진·로그 원문은 넣지 않으며 외부로 전송하지 않습니다.</span>
              </div>
            </div>
            <div className="sec">
              <button className="btn danger" onClick={onShutdown}><Power size={14} />M4ML Studio 종료</button>
            </div>
          </>
        )}
        {tab === "engines" && (
          <div className="sec col" style={{ gap: 12 }}>
            <p className="hint">각 기능을 처리하는 엔진의 이름·버전·경로·검증 정보입니다. 엔진은 설정 파일에서 교체할 수 있으며 기본 화면은 엔진 이름에 의존하지 않습니다.</p>
            {!info && !error && <span className="spinner" />}
            {info && Object.entries(info.engines).map(([cap, e]) => (
              <div className="engine-card" key={cap}>
                <h4>{e.error ? <CircleX size={14} className="err" /> : <CircleCheck size={14} className="ok" />}{CAPABILITY[cap] || cap}<span className="t3" style={{ fontWeight: 400 }}>· {String(e.name || e.key || "")}</span></h4>
                <div className="kv">
                  {Object.entries(e).filter(([k]) => !["capability", "name"].includes(k)).map(([k, v]) => (
                    <Fragment key={k}><span className="mono">{k}</span><Value v={v} /></Fragment>
                  ))}
                </div>
              </div>
            ))}
            {info && (
              <div className="engine-card">
                <h4>GPU 처리 런타임</h4>
                <div className="kv">
                  {Object.entries(info.runtime || {}).map(([k, v]) => (<Fragment key={k}><span className="mono">{k}</span><Value v={v} /></Fragment>))}
                  <span className="mono">python</span><span>{info.runtime_path}</span>
                  <span className="mono">live_sessions</span><Value v={Object.keys(info.live_sessions).length ? info.live_sessions : null} />
                </div>
              </div>
            )}
          </div>
        )}
        {tab === "model" && (
          <div className="sec col">
            <div className="sec-h"><b>객체 선택 모델 파일</b></div>
            <p className="hint">공식 모델 가중치는 이용 조건에 따라 직접 받아야 합니다. 앱은 가중치를 배포하거나 자동으로 내려받지 않습니다.</p>
            <label className="field">
              모델 파일(.pt) 경로
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="~/models/sam3.1_multiplex.pt" />
            </label>
            <div className="row"><button className="btn" disabled={!path.trim()} onClick={() => void saveCheckpoint()}>경로 저장</button></div>
            {message && <p className="ok" role="status">{message}</p>}
          </div>
        )}
        {tab === "license" && (
          <div className="sec col">
            <p className="hint">M4ML Studio는 아래 구성 요소를 포함하거나 사용합니다. 비상업 조건이 있는 구성 요소 때문에 전체 소프트웨어를 자유롭게 상업 배포할 수 없습니다.</p>
            <table>
              <thead><tr><th>구성 요소</th><th>조건</th><th>상업 이용</th></tr></thead>
              <tbody>
                {info?.licenses.map((l) => (
                  <tr key={l.component}><td>{l.component}</td><td>{l.license}</td><td>{l.commercial === false ? <span className="err">불가</span> : l.commercial ? <span className="ok">가능</span> : <span className="warn">확인 필요</span>}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="hint">원문은 설치 폴더의 licenses/ 와 docs/GPU_COLMAP_BUILD.md 에 있습니다.</p>
          </div>
        )}
        {error && <p className="error" style={{ padding: 16 }}>{error}</p>}
      </div>
    </div>
  );
}
