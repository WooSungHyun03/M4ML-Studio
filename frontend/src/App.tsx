import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  CircleCheck,
  CircleX,
  Lock,
  MonitorCog,
  Play,
  Settings,
  SkipForward,
  Square,
  Target,
  TriangleAlert,
  X,
  Circle,
  PanelLeft,
  PanelRight,
  PanelBottom,
  Folder,
} from "lucide-react";
import { api, asset, post, stages, states, subtitles, titles } from "./api";
import type { Health, Project, Stage } from "./api";
import type { Selection, StageCtx } from "./context";
import { Welcome } from "./Welcome";
import { SettingsDrawer } from "./SettingsDrawer";
import { MenuBar } from "./MenuBar";
import type { Menu } from "./MenuBar";
import { ProjectExplorer } from "./ProjectExplorer";
import type { Assets } from "./ProjectExplorer";
import { SelectionInspector } from "./Inspector";
import { BottomPanel } from "./BottomPanel";
import { Dialog } from "./Dialogs";
import type { DialogKind } from "./Dialogs";
import { DockContext, Splitter, useLayout } from "./dock";
import { isDesktop, logFolder, openPath, quitApp, setTitle, toggleFullScreen } from "./desktop";
import { ImagesStage } from "./stages/ImagesStage";
import { CameraStage } from "./stages/CameraStage";
import { MaskStage } from "./stages/MaskStage";
import { TrainStage } from "./stages/TrainStage";
import { ModelStage } from "./stages/ModelStage";

function stageIcon(state: string, provenance?: string) {
  if (state === "completed") return <CircleCheck size={14} className={provenance === "imported" ? "info" : "ok"} />;
  if (state === "running") return <span className="spinner" style={{ width: 11, height: 11 }} />;
  if (state === "failed") return <CircleX size={14} className="err" />;
  if (state === "cancelled") return <TriangleAlert size={13} className="warn" />;
  if (state === "waiting_for_user" || state === "review_required") return <Target size={13} className="acc" />;
  if (state === "blocked") return <Lock size={12} className="t4" />;
  return <Circle size={13} className="t4" strokeDasharray="2.6 2.6" />;
}

function stageMeta(p: Project, s: Stage) {
  const st = p.stages[s];
  if (p.stage_provenance?.[s]?.stage_source === "imported" && st === "completed") return "가져옴";
  if (s === "import" && p.images.length) return String(p.images.length);
  if (s === "colmap" && p.colmap_report && st === "completed") return `${p.colmap_report.registered}/${p.colmap_report.total}`;
  if (s === "review" && Object.keys(p.masks).length) {
    const masks = Object.values(p.masks);
    return `${masks.filter((m) => ["approved", "manual", "skipped"].includes(m.status)).length}/${masks.length}`;
  }
  if (s === "train" && p.training && st === "completed") return Math.round(p.training.iterations / 1000) + "k";
  if (s === "train" && p.training_partial && st !== "running") return "중단됨";
  return st === "pending" ? "" : states[st];
}

const TAB_LABEL: Record<Stage, string> = { import: "이미지", colmap: "카메라 정합", sam: "객체 선택", review: "마스크 검토", train: "3D 재구성", mesh: "3D 모델" };
const emit = (name: string) => window.dispatchEvent(new CustomEvent("m4ml:" + name));

export default function App() {
  const closed = useRef(false);
  const [appClosed, setAppClosed] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]),
    [id, setId] = useState<string | null>(new URLSearchParams(location.search).get("project")),
    [project, setProject] = useState<Project | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [stage, setStage] = useState<Stage>("import"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [gpu, setGpu] = useState(0),
    [showSettings, setShowSettings] = useState<false | "device" | "engines" | "license">(false),
    [dialog, setDialog] = useState<DialogKind>(null),
    [selection, setSelection] = useState<Selection>(null),
    [assets, setAssets] = useState<Assets | null>(null),
    [width, setWidth] = useState(window.innerWidth),
    [inspectorNode, setInspectorNode] = useState<HTMLElement | null>(null),
    [theme, setThemeState] = useState(() => {
      try {
        return localStorage.getItem("m4ml-theme") || "dark";
      } catch {
        return "dark";
      }
    });
  const { layout, update, reset, save, restoreSaved } = useLayout();
  const dirty = useRef(false),
    currentID = useRef(id),
    initialStage = useRef<string | null>(null),
    imageInput = useRef<HTMLInputElement>(null),
    meshInput = useRef<HTMLInputElement>(null);
  currentID.current = id;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    const r = () => setWidth(window.innerWidth);
    window.addEventListener("resize", r);
    return () => window.removeEventListener("resize", r);
  }, []);
  function setTheme(t: string) {
    setThemeState(t);
    try {
      localStorage.setItem("m4ml-theme", t);
    } catch {
      /* not remembered */
    }
  }
  const refresh = useCallback(async () => {
    if (closed.current) return;
    try {
      setProjects(await api<Project[]>("/projects"));
      if (currentID.current) {
        const p = await api<Project>("/projects/" + currentID.current);
        if (p.id === currentID.current) setProject((prev) => (prev?.id === p.id && prev.updated && p.updated && prev.updated > p.updated ? prev : p));
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => {
    let alive = true;
    const load = () => !closed.current && api<Health>("/health").then((h) => alive && setHealth(h)).catch(() => {});
    void load();
    const t = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(t);
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
      setStage(
        project.input_mode === "mesh" || project.stages.mesh === "completed"
          ? "mesh"
          : project.training_partial
            ? "train"
            : stages.find((s) => project.stages[s] !== "completed") || "mesh",
      );
    }
  }, [project?.id]);
  // assets (checkpoints, model files) refresh when stages change
  const stageKey = project ? JSON.stringify(project.stages) + (project.training_partial?.checkpoint ?? "") : "";
  useEffect(() => {
    if (!project) return setAssets(null);
    api<Assets>(`/projects/${project.id}/assets`).then(setAssets).catch(() => setAssets(null));
  }, [project?.id, stageKey]);
  useEffect(() => {
    void setTitle(project?.name || "");
  }, [project?.name]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(t);
  }, [notice]);
  const active = project?.jobs?.find((j) => j.state === "running");
  const lastJob = active || project?.jobs?.[0];
  const guard = useCallback(() => !dirty.current || window.confirm("저장하지 않은 마스크 수정이 있습니다. 저장하지 않고 이동할까요?"), []);
  function open(p: Project | null) {
    if (!guard()) return;
    dirty.current = false;
    setError("");
    setSelection(null);
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
  const base = "/projects/" + id;
  function goStage(s: Stage) {
    if (guard()) {
      dirty.current = false;
      setStage(s);
    }
  }
  async function shutdown() {
    if (!window.confirm("M4ML Studio를 종료할까요? 실행 중인 작업은 중지하며 파일과 기록은 보존합니다.")) return;
    if (await quitApp()) return; // desktop: the window close handler stops the backend
    await post("/shutdown");
    closed.current = true;
    setAppClosed(true);
  }
  const cancel = () => {
    if (window.confirm("실행 중인 작업을 중지할까요? 중간 결과와 기록은 보존합니다.")) void action(() => post(base + "/cancel"));
  };
  /** 현재 단계 다시 실행 / 실패 작업 다시 시도 — only stages that can be started without new input. */
  function rerun(s: string) {
    if (!project) return;
    if (s === "colmap") {
      if (window.confirm("카메라 정합을 다시 실행할까요? 이후 단계 결과는 다시 만들어야 합니다.")) void action(() => post(base + "/jobs/colmap", { gpu, matching: "exhaustive" }));
    } else if (s === "mesh") {
      void action(() => post(base + "/jobs/mesh", { gpu }));
    } else if (s === "train") {
      const resume = !!project.training_partial;
      if (window.confirm(resume ? `저장 지점 ${project.training_partial!.checkpoint.toLocaleString()}회부터 이어서 학습할까요?` : "기본 설정(30,000회)으로 3D 재구성 학습을 시작할까요?"))
        void action(() => post(base + "/jobs/train", { gpu, confirmed: true, resume }));
    }
  }
  const rerunnable = (s: Stage) =>
    !!project && !active && ((s === "colmap" && project.stages.import === "completed" && project.input_mode === "images") || (s === "mesh" && project.stages.train === "completed") || (s === "train" && project.stages.review === "completed"));
  async function uploadImages(files: FileList | null) {
    if (!files || !project) return;
    if (project.stages.import === "completed") return setError("카메라 정합을 시작한 프로젝트에는 사진을 추가할 수 없습니다. 새 프로젝트를 만드세요.");
    goStage("import");
    for (const f of Array.from(files)) {
      const data = new FormData();
      data.append("file", f, f.name);
      try {
        await api(base + "/images", { method: "POST", body: data });
      } catch (e) {
        setError(f.name + ": " + (e as Error).message);
      }
    }
    await refresh();
  }
  async function importMesh(file: File | undefined) {
    if (!file) return;
    await action(async () => {
      const p = await post<Project>("/projects", { name: file.name, input_mode: "mesh" });
      const data = new FormData();
      data.append("file", file);
      open(await api<Project>(`/projects/${p.id}/mesh-file`, { method: "POST", body: data }));
    });
  }
  function exportModel() {
    if (!project?.mesh) return setError("내보낼 3D 모델이 없습니다.");
    const a = document.createElement("a");
    a.href = asset(project.id, project.mesh.path + "/fuse_post.ply");
    a.download = (project.name.replace(/[^\p{L}\p{N}_-]+/gu, "_") || "model") + ".ply";
    a.click();
  }
  const newProject = () => {
    open(null);
    setTimeout(() => emit("new-project"), 0);
  };
  const openProject = () => {
    open(null);
    setTimeout(() => emit("open-project"), 0);
  };
  const masking = stage === "sam" || stage === "review";
  const effective = {
    // narrow windows: side docks collapse automatically (toggle buttons still work at ≥ 760px)
    explorer: !!project && layout.explorer && width >= 1080,
    inspector: !!project && layout.inspector && width >= 900,
    bottom: layout.bottom,
  };
  const menus: Menu[] = useMemo(
    () => [
      {
        label: "파일",
        items: [
          { label: "새 프로젝트…", shortcut: "Ctrl+N", action: newProject },
          { label: "프로젝트 열기…", shortcut: "Ctrl+O", action: openProject },
          {
            label: "최근 프로젝트",
            submenu: projects.filter((p) => !p.archived).slice(0, 10).map((p) => ({ label: p.name, action: () => open(p), checked: p.id === id })),
          },
          { separator: true },
          { label: "프로젝트 저장", shortcut: "Ctrl+S", disabled: !project, action: () => (dirty.current ? emit("save") : setNotice("모든 변경 사항이 자동으로 저장되어 있습니다.")) },
          { label: "다른 이름으로 저장…", shortcut: "Ctrl+Shift+S", disabled: !project || !!active, action: () => setDialog("saveas") },
          { separator: true },
          { label: "이미지 가져오기…", disabled: !project || project.stages.import === "completed", hint: "카메라 정합 전 프로젝트에만 사진을 추가할 수 있습니다", action: () => imageInput.current?.click() },
          { label: "외부 데이터 가져오기 (폴더)…", action: newProject },
          { label: "3D 모델 가져오기…", action: () => meshInput.current?.click() },
          { label: "3D 모델 내보내기 (PLY)", shortcut: "Ctrl+E", disabled: !project?.mesh, action: exportModel },
          { separator: true },
          { label: "프로젝트 폴더 열기", disabled: !project?.project_path, action: () => void openPath(project!.project_path!) },
          { label: "종료", shortcut: "Ctrl+Q", action: () => void shutdown() },
        ],
      },
      {
        label: "편집",
        items: [
          { label: "실행 취소", shortcut: "Ctrl+Z", disabled: !masking, hint: "마스크 생성·검토 화면에서 사용할 수 있습니다", action: () => emit("undo") },
          { label: "다시 실행", shortcut: "Ctrl+Shift+Z", disabled: !masking, action: () => emit("redo") },
          { separator: true },
          { label: "선택 해제", shortcut: "Esc", disabled: !selection, action: () => setSelection(null) },
          { label: "모두 선택", shortcut: "Ctrl+A", disabled: stage !== "import" || !project?.images.length, hint: "이미지 화면에서 모든 사진을 선택합니다", action: () => emit("select-all") },
          { separator: true },
          { label: "환경 설정…", shortcut: "Ctrl+,", action: () => setShowSettings("device") },
          { label: "단축키…", action: () => setDialog("shortcuts"), hint: "현재 버전은 단축키 목록 보기만 지원합니다" },
        ],
      },
      {
        label: "보기",
        items: [
          { label: "전체 화면", shortcut: "F11", action: () => void toggleFullScreen() },
          { separator: true },
          { label: "프로젝트 탐색기", shortcut: "Ctrl+B", checked: layout.explorer, disabled: !project, action: () => update({ explorer: !layout.explorer }) },
          { label: "속성 패널 (Inspector)", shortcut: "Ctrl+I", checked: layout.inspector, disabled: !project, action: () => update({ inspector: !layout.inspector }) },
          { label: "작업 패널", shortcut: "Ctrl+J", checked: layout.bottom && layout.bottomTab === "tasks", action: () => update({ bottom: !(layout.bottom && layout.bottomTab === "tasks"), bottomTab: "tasks" }) },
          { label: "로그 패널", checked: layout.bottom && layout.bottomTab === "console", action: () => update({ bottom: !(layout.bottom && layout.bottomTab === "console"), bottomTab: "console" }) },
          { separator: true },
          { label: "기본 레이아웃 복원", action: () => { reset(); setNotice("기본 레이아웃으로 되돌렸습니다."); } },
          { label: "어두운 테마", checked: theme === "dark", action: () => setTheme("dark") },
          { label: "밝은 테마", checked: theme === "light", action: () => setTheme("light") },
          { separator: true },
          { label: "뷰포트 표시 설정…", disabled: stage !== "mesh" || !project?.mesh, hint: "3D 모델 화면에서 사용할 수 있습니다", action: () => emit("viewport-settings") },
        ],
      },
      {
        label: "작업",
        items: [
          ...stages.map((s, i) => ({
            label: `${String(i + 1).padStart(2, "0")}  ${TAB_LABEL[s]}`,
            shortcut: `Ctrl+${i + 1}`,
            checked: project ? stage === s : false,
            disabled: !project || (project.input_mode === "mesh" && s !== "mesh"),
            action: () => goStage(s),
          })),
          { separator: true },
          { label: "현재 단계 다시 실행", shortcut: "Ctrl+R", disabled: !rerunnable(stage), hint: "카메라 정합 · 3D 재구성 · 3D 모델 생성 단계에서 사용할 수 있습니다", action: () => rerun(stage) },
          { label: "작업 취소", disabled: !active, action: cancel },
          { label: "작업 기록", action: () => update({ bottom: true, bottomTab: "tasks" }) },
        ],
      },
      {
        label: "창",
        items: [
          { label: "프로젝트 탐색기", checked: layout.explorer, disabled: !project, action: () => update({ explorer: !layout.explorer }) },
          { label: "Inspector", checked: layout.inspector, disabled: !project, action: () => update({ inspector: !layout.inspector }) },
          { label: "3D Viewport", disabled: !project, action: () => goStage("mesh") },
          { label: "Image Viewer", disabled: !project, action: () => goStage(project?.stages.colmap === "completed" ? "review" : "import") },
          { separator: true },
          { label: "작업 관리자", action: () => update({ bottom: true, bottomTab: "tasks" }) },
          { label: "Console", action: () => update({ bottom: true, bottomTab: "console" }) },
          { label: "GPU Monitor", action: () => update({ bottom: true, bottomTab: "gpu" }) },
          { separator: true },
          { label: "레이아웃 저장", action: () => setNotice(save() ? "현재 레이아웃을 저장했습니다. ‘저장한 레이아웃 불러오기’로 되돌릴 수 있습니다." : "레이아웃을 저장하지 못했습니다.") },
          { label: "저장한 레이아웃 불러오기", action: () => setNotice(restoreSaved() ? "저장한 레이아웃을 불러왔습니다." : "저장한 레이아웃이 없습니다.") },
          { label: "레이아웃 초기화", action: () => reset() },
        ],
      },
      {
        label: "도움말",
        items: [
          { label: "시작 가이드", shortcut: "F1", action: () => setDialog("guide") },
          { label: "사용 설명서", action: () => setDialog("manual") },
          { label: "단축키 목록", action: () => setDialog("shortcuts") },
          { label: "오류 해결 가이드", action: () => setDialog("troubleshooting") },
          { separator: true },
          { label: "로그 폴더 열기", action: () => void logFolder().then((p) => { if (p) void openPath(p); else if (project?.project_path) void openPath(project.project_path + "/logs"); else setNotice("로그 폴더는 데스크톱 앱에서 열 수 있습니다."); }) },
          { label: "환경 진단", action: () => setShowSettings("device") },
          { label: "업데이트 확인", action: () => setDialog("update") },
          { label: "라이선스", action: () => setShowSettings("license") },
          { label: "M4ML Studio 정보", action: () => setDialog("about") },
        ],
      },
    ],
    [projects, project, id, active, layout, theme, stage, selection, masking],
  );
  // global keyboard shortcuts (menu accelerators)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = !!t.closest("input,textarea,select");
      const ctrl = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (ctrl && k === "n") { e.preventDefault(); newProject(); }
      else if (ctrl && k === "o") { e.preventDefault(); openProject(); }
      else if (ctrl && e.shiftKey && k === "s") { e.preventDefault(); if (project && !active) setDialog("saveas"); }
      else if (ctrl && k === "s") { e.preventDefault(); if (dirty.current) emit("save"); else if (project) setNotice("모든 변경 사항이 자동으로 저장되어 있습니다."); }
      else if (ctrl && k === "a" && !typing && stage === "import" && project?.images.length) { e.preventDefault(); emit("select-all"); }
      else if (ctrl && k === "e" && project?.mesh) { e.preventDefault(); exportModel(); }
      else if (ctrl && k === "b") { e.preventDefault(); update({ explorer: !layout.explorer }); }
      else if (ctrl && k === "i") { e.preventDefault(); update({ inspector: !layout.inspector }); }
      else if (ctrl && k === "j") { e.preventDefault(); update({ bottom: !layout.bottom }); }
      else if (ctrl && k === ",") { e.preventDefault(); setShowSettings("device"); }
      else if (ctrl && k === "r" && rerunnable(stage)) { e.preventDefault(); rerun(stage); }
      else if (ctrl && k === "q") { e.preventDefault(); void shutdown(); }
      else if (ctrl && /^[1-6]$/.test(e.key) && project) { e.preventDefault(); goStage(stages[+e.key - 1]); }
      else if (e.key === "F1") { e.preventDefault(); setDialog("guide"); }
      else if (e.key === "F11") { e.preventDefault(); void toggleFullScreen(); }
      else if (e.key === "Escape" && !typing && selection && !dialog) setSelection(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (appClosed)
    return (
      <div className="empty" style={{ height: "100vh", justifyContent: "center" }}>
        <div className="plate" style={{ width: 300 }}><img src="/m4ml-logo.png" alt="M4ML" /></div>
        <h2>M4ML Studio를 종료했습니다.</h2>
        <p>프로젝트와 결과는 보존했습니다. 실행 아이콘으로 다시 열 수 있습니다.</p>
      </div>
    );

  const gpuInfo = health?.gpus[gpu] || health?.gpus[0];
  const vramPct = gpuInfo ? ((gpuInfo.total_mb - gpuInfo.free_mb) / gpuInfo.total_mb) * 100 : 0;
  const ctx: StageCtx | null = project
    ? { project, health, base, blocked: busy || !!active, busy, active, gpu, setGpu, action, refresh, setStage: goStage, setError, setDirty: (d) => (dirty.current = d), guard, selection, select: setSelection }
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
    <DockContext.Provider value={{ inspector: inspectorNode }}>
      <div className="editor">
        <a className="skip-link" href="#main-content">작업 영역으로 건너뛰기</a>
        <input ref={imageInput} type="file" multiple accept="image/jpeg,image/png,image/tiff" hidden onChange={(e) => { void uploadImages(e.target.files); e.target.value = ""; }} />
        <input ref={meshInput} type="file" accept=".ply,.glb" hidden onChange={(e) => { void importMesh(e.target.files?.[0]); e.target.value = ""; }} />
        <header className="menubar-row">
          <button className="brand" onClick={() => open(null)} title="시작 화면">
            <span className="logo-plate"><img src="/m4ml-icon.png" alt="" /></span>
            <span className="brand-name">M4ML Studio</span>
          </button>
          <MenuBar menus={menus} />
          <span className="sp" />
          <button className="device-pill" onClick={() => update({ bottom: true, bottomTab: "gpu" })} title="GPU Monitor 열기">
            <MonitorCog size={14} className={gpuInfo ? (active ? "acc" : "ok") : "err"} />
            <b>{gpuInfo ? gpuInfo.name.replace(/^NVIDIA (GeForce )?/, "") : "GPU 없음"}</b>
            {gpuInfo && <span className="num">{((gpuInfo.total_mb - gpuInfo.free_mb) / 1024).toFixed(1)} / {(gpuInfo.total_mb / 1024).toFixed(0)} GB</span>}
            {gpuInfo && <span className={"meter" + (active ? " busy" : "")}><i style={{ width: vramPct + "%" }} /></span>}
          </button>
          <button className="icon-btn" title="환경 설정 (Ctrl+,)" aria-label="환경 설정" onClick={() => setShowSettings(showSettings ? false : "device")}><Settings size={15} /></button>
        </header>
        {project && (
          <>
            <div className="projectbar">
              <Folder size={14} className="t3" />
              <b className="ellip" style={{ maxWidth: 360 }} title={project.name}>{project.name}</b>
              <span className="save-state">{dirty.current ? <><TriangleAlert size={12} className="warn" />저장하지 않은 수정</> : <><Check size={12} className="ok" />저장됨</>}</span>
              <span className="vsep" />
              {active ? (
                <>
                  <span className="row t2" style={{ gap: 6, fontSize: 12 }}><span className="spinner" />{TAB_LABEL[(active.stage === "preview" ? "sam" : active.stage) as Stage]} 실행 중</span>
                  <button className="btn s danger" onClick={cancel}><Square size={10} />중지</button>
                </>
              ) : (
                <button className="btn s" disabled={!rerunnable(stage)} title={rerunnable(stage) ? "현재 단계를 다시 실행합니다 (Ctrl+R)" : "이 단계는 화면의 버튼으로 시작합니다"} onClick={() => rerun(stage)}>
                  <Play size={11} />현재 단계 실행
                </button>
              )}
              <span className="sp" />
              <span className="t3" style={{ fontSize: 11.5 }}>{project.folder_import ? "폴더에서 시작" : ""}</span>
              <button className="icon-btn" aria-pressed={layout.explorer} title="프로젝트 탐색기 (Ctrl+B)" onClick={() => update({ explorer: !layout.explorer })}><PanelLeft size={15} /></button>
              <button className="icon-btn" aria-pressed={layout.bottom} title="아래 패널 (Ctrl+J)" onClick={() => update({ bottom: !layout.bottom })}><PanelBottom size={15} /></button>
              <button className="icon-btn" aria-pressed={layout.inspector} title="Inspector (Ctrl+I)" onClick={() => update({ inspector: !layout.inspector })}><PanelRight size={15} /></button>
            </div>
            <nav className="stage-tabs" aria-label="작업 단계">
              {stages.map((s, i) =>
                project.input_mode === "mesh" && s !== "mesh" ? null : (
                  <button key={s} className="stage-tab" aria-current={stage === s ? "step" : undefined} onClick={() => goStage(s)} title={`${titles[s]} (Ctrl+${i + 1})`}>
                    {stageIcon(project.stages[s], project.stage_provenance?.[s]?.stage_source)}
                    <span>{TAB_LABEL[s]}</span>
                    {stageMeta(project, s) && <span className="meta">{stageMeta(project, s)}</span>}
                  </button>
                ),
              )}
            </nav>
          </>
        )}
        <div className="editor-body">
          {effective.explorer && project && (
            <>
              <aside className="dock left" style={{ width: layout.explorerW }}>
                <ProjectExplorer
                  project={project}
                  assets={assets}
                  selection={selection}
                  onSelect={setSelection}
                  onOpen={(sel, s) => {
                    setSelection(sel);
                    if (!s) return;
                    if (sel?.kind === "image" && project.stages.colmap === "completed" && project.masks[sel.name]) goStage("review");
                    else goStage(s);
                  }}
                />
              </aside>
              <Splitter axis="x" onDrag={(d) => update({ explorerW: Math.max(180, Math.min(480, layout.explorerW + d)) })} onDouble={() => update({ explorer: false })} />
            </>
          )}
          <main className="main" id="main-content" tabIndex={-1}>
            {error && (
              <div className="error-banner" role="alert">
                <TriangleAlert size={16} />
                <span className="grow">{error}</span>
                <button className="icon-btn" aria-label="닫기" onClick={() => setError("")}><X size={14} /></button>
              </div>
            )}
            {notice && <div className="notice" role="status"><CircleCheck size={14} className="ok" />{notice}</div>}
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
          {effective.inspector && project && (
            <>
              <Splitter axis="x" onDrag={(d) => update({ inspectorW: Math.max(240, Math.min(520, layout.inspectorW - d)) })} onDouble={() => update({ inspector: false })} />
              <aside className="dock right" style={{ width: layout.inspectorW }} aria-label="Inspector">
                <div className="dock-h"><b>Inspector</b><span className="t3" style={{ fontSize: 11 }}>{selection ? "선택 항목" : titles[stage]}</span></div>
                <div className="dock-scroll">
                  <SelectionInspector project={project} selection={selection} onClear={() => setSelection(null)} />
                  <div ref={setInspectorNode} />
                </div>
              </aside>
            </>
          )}
        </div>
        {effective.bottom && (
          <>
            <Splitter axis="y" onDrag={(d) => update({ bottomH: Math.max(110, Math.min(window.innerHeight * 0.6, layout.bottomH - d)) })} onDouble={() => update({ bottom: false })} />
            <div className="dock bottom" style={{ height: layout.bottomH }}>
              <BottomPanel
                project={project}
                tab={layout.bottomTab}
                setTab={(t) => update({ bottomTab: t })}
                onHide={() => update({ bottom: false })}
                onCancel={cancel}
                onRetry={rerun}
                selection={selection}
                onSelect={setSelection}
              />
            </div>
          </>
        )}
        <footer className="statusbar" role="status" aria-live="polite">
          <div className="it">{project ? (dirty.current ? <><TriangleAlert size={12} className="warn" />수정 중</> : <><Check size={12} className="ok" />저장됨</>) : <><CircleCheck size={12} className="ok" />준비됨</>}</div>
          <div className="it grow">
            {active ? <span className="spinner" style={{ width: 10, height: 10 }} /> : lastJob?.state === "failed" ? <CircleX size={12} className="err" /> : lastJob?.state === "cancelled" ? <SkipForward size={12} className="warn" /> : null}
            <span className="ellip t2">{active ? `${TAB_LABEL[(active.stage === "preview" ? "sam" : active.stage) as Stage] || ""} · ${active.message}` : lastJob ? `${states[lastJob.state] || lastJob.state} · ${lastJob.message}` : project ? "대기 중" : ""}</span>
          </div>
          {active?.total ? (
            <div className="it">
              <div className="bar"><i style={{ width: `${((active.current || 0) / active.total) * 100}%` }} /></div>
              <span className="num t2">{Math.round(((active.current || 0) / active.total) * 100)}%</span>
            </div>
          ) : null}
          {!effective.bottom && <button onClick={() => update({ bottom: true })}><PanelBottom size={12} />패널 열기</button>}
          <span className="it">{gpuInfo ? <><MonitorCog size={12} className="ok" />{gpuInfo.name}</> : <><MonitorCog size={12} className="err" />GPU 없음</>}</span>
          <span className="it t4">{isDesktop() ? "" : "개발 모드 · "}v{health?.version || ""}</span>
        </footer>
        {showSettings && (
          <SettingsDrawer
            health={health}
            theme={theme}
            setTheme={setTheme}
            initialTab={showSettings}
            onClose={() => setShowSettings(false)}
            onRefresh={() => void api<Health>("/health").then(setHealth)}
            onShutdown={() => void shutdown()}
          />
        )}
        <Dialog
          kind={dialog}
          projectName={project?.name}
          onClose={() => setDialog(null)}
          onSaveAs={(name) => {
            setDialog(null);
            void action(async () => {
              const copy = await post<Project>(base + "/duplicate", { name });
              setNotice(`‘${name}’(으)로 저장했습니다.`);
              open(copy);
            });
          }}
        />
      </div>
    </DockContext.Provider>
  );
}
