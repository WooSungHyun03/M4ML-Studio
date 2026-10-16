import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Check,
  CircleCheck,
  CircleX,
  Folder,
  HardDrive,
  Lock,
  MonitorCog,
  Settings,
  SkipForward,
  Square,
  Target,
  Terminal,
  TriangleAlert,
  X,
  Box,
  Circle,
} from "lucide-react";
import { api, post, stages, states, subtitles, titles } from "./api";
import type { Health, Project, Stage } from "./api";
import type { StageCtx } from "./context";
import { Welcome } from "./Welcome";
import { SettingsDrawer } from "./SettingsDrawer";
import { ImagesStage } from "./stages/ImagesStage";
import { CameraStage } from "./stages/CameraStage";
import { MaskStage } from "./stages/MaskStage";
import { TrainStage } from "./stages/TrainStage";
import { ModelStage } from "./stages/ModelStage";

function stageIcon(state: string, provenance?: string) {
  if (state === "completed") return <CircleCheck size={16} className={provenance === "imported" ? "info" : "ok"} />;
  if (state === "running") return <span className="spinner" />;
  if (state === "failed") return <CircleX size={16} className="err" />;
  if (state === "cancelled") return <TriangleAlert size={15} className="warn" />;
  if (state === "waiting_for_user" || state === "review_required") return <Target size={15} className="acc" />;
  if (state === "blocked") return <Lock size={14} className="t4" />;
  return <Circle size={15} className="t4" strokeDasharray="2.6 2.6" />;
}

function stageMeta(p: Project, s: Stage) {
  const st = p.stages[s];
  if (p.stage_provenance?.[s]?.stage_source === "imported" && st === "completed") return "가져옴";
  if (s === "import" && p.images.length) return String(p.images.length);
  if (s === "colmap" && p.colmap_report && st === "completed") return `${p.colmap_report.registered}/${p.colmap_report.total}`;
  if (s === "review" && Object.keys(p.masks).length) {
    const masks = Object.values(p.masks);
    const skipped = masks.filter((m) => m.status === "skipped").length;
    if (st === "completed" && skipped) return `건너뜀 ${skipped}`;
    return `${masks.filter((m) => ["approved", "manual", "skipped"].includes(m.status)).length}/${masks.length}`;
  }
  if (s === "train" && p.training && st === "completed") return Math.round(p.training.iterations / 1000) + "k";
  return st === "pending" ? "" : states[st];
}

export default function App() {
  const closed = useRef(false);
  const [appClosed, setAppClosed] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]),
    [id, setId] = useState<string | null>(new URLSearchParams(location.search).get("project")),
    [project, setProject] = useState<Project | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [stage, setStage] = useState<Stage>("import"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [gpu, setGpu] = useState(0),
    [showSettings, setShowSettings] = useState(false),
    [showLog, setShowLog] = useState(false),
    [log, setLog] = useState(""),
    [theme, setThemeState] = useState(() => {
      try {
        return localStorage.getItem("m4ml-theme") || "dark";
      } catch {
        return "dark";
      }
    });
  const dirty = useRef(false),
    currentID = useRef(id),
    initialStage = useRef<string | null>(null);
  currentID.current = id;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  function setTheme(t: string) {
    setThemeState(t);
    try {
      localStorage.setItem("m4ml-theme", t);
    } catch {
      /* private mode: theme just isn't remembered */
    }
  }
  const refresh = useCallback(async () => {
    if (closed.current) return;
    try {
      setProjects(await api<Project[]>("/projects"));
      if (currentID.current) {
        const p = await api<Project>("/projects/" + currentID.current);
        if (p.id === currentID.current)
          setProject((prev) => (prev?.id === p.id && prev.updated && p.updated && prev.updated > p.updated ? prev : p));
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    let alive = true;
    const load = () => !closed.current && api<Health>("/health").then((h) => alive && setHealth(h)).catch(() => {});
    void load();
    const timer = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!id) return;
    const events = new EventSource("/api/projects/" + id + "/events");
    events.onmessage = () => void refresh();
    return () => events.close();
  }, [id, refresh]);
  useEffect(() => {
    if (project && initialStage.current !== project.id) {
      initialStage.current = project.id;
      setStage(project.input_mode === "mesh" ? "mesh" : stages.find((s) => project.stages[s] !== "completed") || "mesh");
    }
  }, [project?.id]);
  const active = project?.jobs?.find((j) => j.state === "running");
  const lastJob = active || project?.jobs?.[0];
  useEffect(() => {
    if (!id || !lastJob || !showLog) return;
    let alive = true;
    const load = () => api<{ text: string }>(`/projects/${id}/logs/${lastJob.id}`).then((r) => alive && setLog(r.text)).catch(() => {});
    void load();
    const timer = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id, lastJob?.id, showLog]);

  const guard = useCallback(
    () => !dirty.current || window.confirm("저장하지 않은 마스크 수정이 있습니다. 저장하지 않고 이동할까요?"),
    [],
  );
  function open(p: Project | null) {
    if (!guard()) return;
    dirty.current = false;
    setError("");
    setId(p?.id || null);
    setProject(p);
    initialStage.current = null;
    history.replaceState(null, "", p ? "?project=" + p.id : "/");
  }
  async function action(fn: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function shutdown() {
    if (!window.confirm("실행 중인 작업을 중지하고 M4ML Studio를 종료할까요? 파일과 기록은 보존합니다.")) return;
    void post("/shutdown").then(() => {
      closed.current = true;
      setAppClosed(true);
    });
  }

  if (appClosed)
    return (
      <div className="empty" style={{ height: "100vh", justifyContent: "center" }}>
        <div className="plate" style={{ width: 300 }}><img src="/m4ml-logo.png" alt="M4ML" /></div>
        <h2>M4ML Studio를 종료했습니다.</h2>
        <p>프로젝트와 결과는 보존했습니다. 실행 아이콘으로 다시 열 수 있습니다.</p>
      </div>
    );

  const base = "/projects/" + id;
  const gpuInfo = health?.gpus[gpu] || health?.gpus[0];
  const vramPct = gpuInfo ? ((gpuInfo.total_mb - gpuInfo.free_mb) / gpuInfo.total_mb) * 100 : 0;
  const ctx: StageCtx | null = project
    ? {
        project,
        health,
        base,
        blocked: busy || !!active,
        busy,
        active,
        gpu,
        setGpu,
        action,
        refresh,
        setStage: (s) => {
          if (guard()) {
            dirty.current = false;
            setStage(s);
          }
        },
        setError,
        setDirty: (d) => {
          dirty.current = d;
        },
        guard,
      }
    : null;
  const no = stages.indexOf(stage) + 1;
  const toolbar = (children: React.ReactNode) => (
    <div className="toolbar">
      <div className="stage-title">
        {project?.input_mode !== "mesh" && <span className="no">{String(no).padStart(2, "0")}</span>}
        <h1>{titles[stage]}</h1>
        <span className="sub">{subtitles[stage]}</span>
      </div>
      {children && <span className="vsep" />}
      {children}
    </div>
  );

  return (
    <div className={"app" + (project ? "" : " nonav")}>
      <a className="skip-link" href="#main-content">작업 영역으로 건너뛰기</a>
      <header className="topbar">
        <button className="brand" onClick={() => open(null)} title="처음 화면">
          <span className="logo-plate"><img src="/m4ml-icon.png" alt="" /></span>
          <span className="brand-name">M4ML Studio</span>
        </button>
        <div className="top-center">
          {project ? (
            <>
              <Folder size={14} className="t3" />
              <span className="proj-name ellip">{project.name}</span>
              <span className="t4">·</span>
              <span className="save-state">
                {dirty.current ? <><TriangleAlert size={13} className="warn" />저장하지 않은 수정</> : <><Check size={13} className="ok" />모든 변경 사항 저장됨</>}
              </span>
            </>
          ) : (
            <span className="t3">열린 프로젝트 없음</span>
          )}
        </div>
        <div className="top-right">
          <button className="device-pill" onClick={() => setShowSettings(true)} title="처리 장치">
            <MonitorCog size={15} className={gpuInfo ? (active ? "acc" : "ok") : "err"} />
            <b>{gpuInfo ? gpuInfo.name.replace(/^NVIDIA (GeForce )?/, "") : "GPU 없음"}</b>
            {gpuInfo && <span className="num">{((gpuInfo.total_mb - gpuInfo.free_mb) / 1024).toFixed(1)} / {(gpuInfo.total_mb / 1024).toFixed(0)} GB</span>}
            {gpuInfo && <span className={"meter" + (active ? " busy" : "")}><i style={{ width: vramPct + "%" }} /></span>}
          </button>
          {project && (
            <button
              className="icon-btn"
              title={project.archived ? "프로젝트 복원" : "프로젝트 보관"}
              disabled={busy || !!active}
              onClick={() => void action(() => api(base + (project.archived ? "/restore" : ""), { method: project.archived ? "POST" : "DELETE" }))}
            >
              {project.archived ? <ArchiveRestore size={16} /> : <Archive size={16} />}
            </button>
          )}
          <button className="icon-btn" title="설정" aria-label="설정" aria-pressed={showSettings} onClick={() => setShowSettings((v) => !v)}><Settings size={16} /></button>
        </div>
      </header>

      {project && (
        <aside className="nav" aria-label="작업 단계">
          <button className="nav-item project" onClick={() => open(null)}>
            <span className="st"><Box size={16} className="t2" /></span>
            <span>프로젝트</span>
            <span className="meta">{project.input_mode === "colmap" ? "방식 B" : project.input_mode === "colmap_masks" ? "방식 C" : project.input_mode === "mesh" ? "모델" : "방식 A"}</span>
          </button>
          <div className="nav-label">작업 단계</div>
          {stages.map((s, i) =>
            project.input_mode === "mesh" && s !== "mesh" ? null : (
              <button key={s} className="nav-item" aria-current={stage === s ? "step" : undefined} onClick={() => ctx!.setStage(s)}>
                <span className="st">{stageIcon(project.stages[s], project.stage_provenance?.[s]?.stage_source)}</span>
                <span className="no">{String(i + 1).padStart(2, "0")}</span>
                <span className="ellip">{titles[s]}</span>
                <span className="meta">{stageMeta(project, s)}</span>
              </button>
            ),
          )}
          <div className="nav-label" style={{ marginTop: 10 }}>최근 프로젝트</div>
          {projects.filter((p) => !p.archived).slice(0, 6).map((p) => (
            <button key={p.id} className={"nav-item recent" + (p.id === id ? " chosen" : "")} onClick={() => open(p)}>
              <span className="ellip">{p.name}</span>
            </button>
          ))}
          <div className="nav-foot">
            <div className="row"><HardDrive size={13} /><span className="grow">저장 공간</span><span className="t2 num">{health ? Math.floor(health.disk_free / 1024 ** 3) + " GB" : "—"}</span></div>
            {project.project_path && <div className="row" title={project.project_path}><Folder size={13} /><span className="grow ellip">{project.project_path}</span></div>}
          </div>
        </aside>
      )}

      <main className="main" id="main-content" tabIndex={-1}>
        {error && (
          <div className="error-banner" role="alert">
            <TriangleAlert size={16} />
            <span className="grow">{error}</span>
            <button className="icon-btn" aria-label="닫기" onClick={() => setError("")}><X size={14} /></button>
          </div>
        )}
        {!project || !ctx ? (
          <Welcome health={health} projects={projects} onOpen={(p) => { open(p); void refresh(); }} setError={setError} />
        ) : stage === "import" ? (
          <ImagesStage ctx={ctx} toolbar={toolbar} />
        ) : stage === "colmap" ? (
          <CameraStage ctx={ctx} toolbar={toolbar} />
        ) : stage === "sam" || stage === "review" ? (
          <MaskStage key={stage} ctx={ctx} mode={stage} toolbar={toolbar} />
        ) : stage === "train" ? (
          <TrainStage ctx={ctx} toolbar={toolbar} />
        ) : (
          <ModelStage ctx={ctx} toolbar={toolbar} />
        )}
      </main>

      <footer className="statusbar" role="status" aria-live="polite">
        <div className="it grow">
          {active ? <span className="spinner" /> : lastJob?.state === "failed" ? <CircleX size={13} className="err" /> : lastJob?.state === "cancelled" ? <SkipForward size={13} className="warn" /> : <CircleCheck size={13} className="ok" />}
          <span className="ellip t2">
            {active ? `${titles[(active.stage === "preview" ? "sam" : active.stage) as Stage] || ""} · ${active.message}` : lastJob ? `${states[lastJob.state] || lastJob.state} · ${lastJob.message}` : project ? "대기 중" : "준비됨"}
          </span>
        </div>
        {active?.total ? (
          <div className="it">
            <div className="bar"><i style={{ width: `${((active.current || 0) / active.total) * 100}%` }} /></div>
            <span className="num t2">{(active.current || 0).toLocaleString()} / {active.total.toLocaleString()}</span>
          </div>
        ) : null}
        {active && (
          <button className="stop" onClick={() => { if (window.confirm("실행 중인 작업을 중지할까요? 중간 결과와 기록은 보존합니다.")) void action(() => post(base + "/cancel")); }}>
            <Square size={11} />중지
          </button>
        )}
        {project && <button onClick={() => setShowLog((v) => !v)} aria-pressed={showLog}><Terminal size={13} />로그 {showLog ? "닫기" : "열기"}</button>}
        <span className="it t4">v{health?.version || ""}</span>
      </footer>

      {showLog && project && (
        <div className="drawer log" role="region" aria-label="실행 기록">
          <div className="drawer-h">
            <Terminal size={14} /><h2>실행 기록</h2>
            <span className="t3 ellip">{lastJob ? `${titles[(lastJob.stage === "preview" ? "sam" : lastJob.stage) as Stage] || lastJob.stage} · ${states[lastJob.state] || lastJob.state}` : "작업 없음"}</span>
            <span className="sp" />
            {project.project_path && <code className="t3 ellip" style={{ maxWidth: 420 }}>{project.project_path}</code>}
            <button className="icon-btn" aria-label="닫기" onClick={() => setShowLog(false)}><X size={14} /></button>
          </div>
          <pre className="log-text">{log.replace(/\x1b\[[0-9;]*m/g, "").split("\r").join("\n").slice(-20000) || "작업을 시작하면 실제 실행 기록이 표시됩니다."}</pre>
        </div>
      )}
      {showSettings && (
        <SettingsDrawer
          health={health}
          theme={theme}
          setTheme={setTheme}
          onClose={() => setShowSettings(false)}
          onRefresh={() => void api<Health>("/health").then(setHealth)}
          onShutdown={shutdown}
        />
      )}
    </div>
  );
}
