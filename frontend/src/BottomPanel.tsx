import { useEffect, useRef, useState } from "react";
import { ChevronDown, CircleCheck, CircleX, Copy, FolderOpen, Gauge, Image as ImageIcon, ListChecks, RotateCcw, Square, Terminal, SkipForward } from "lucide-react";
import { api, asset, states, titles } from "./api";
import type { Job, Project, Stage } from "./api";
import type { Layout } from "./dock";
import type { Selection } from "./context";
import { fmt } from "./context";
import { logFolder, openPath } from "./desktop";

type Tab = Layout["bottomTab"];
const stageName = (s: string) => titles[(s === "preview" ? "sam" : s) as Stage] || s;

function duration(job: Job) {
  if (!job.created) return "";
  const end = job.ended ? new Date(job.ended).getTime() : Date.now();
  const s = Math.max(0, Math.round((end - new Date(job.created).getTime()) / 1000));
  return s >= 3600 ? `${Math.floor(s / 3600)}시간 ${Math.floor((s % 3600) / 60)}분` : s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
}

function Sparkline({ values, max, color }: { values: number[]; max: number; color: string }) {
  if (values.length < 2) return <svg className="spark" />;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${30 - (v / Math.max(max, 1e-9)) * 28}`).join(" ");
  return (
    <svg className="spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function BottomPanel({
  project,
  tab,
  setTab,
  onHide,
  onCancel,
  onRetry,
  selection,
  onSelect,
}: {
  project: Project | null;
  tab: Tab;
  setTab: (t: Tab) => void;
  onHide: () => void;
  onCancel: () => void;
  onRetry: (stage: string) => void;
  selection: Selection;
  onSelect: (s: Selection) => void;
}) {
  const jobs = project?.jobs || [];
  const [jobId, setJobId] = useState<string | null>(null),
    [log, setLog] = useState(""),
    [contentKind, setContentKind] = useState<"images" | "masks">("images"),
    [gpu, setGpu] = useState<{ gpus: { name: string; total_mb: number; used_mb: number; util: number; temp: number; power: number; power_limit: number }[]; apps: { pid: number; used_mb: number; role: string }[] } | null>(null);
  const history = useRef<{ used: number[]; util: number[] }>({ used: [], util: [] });
  const logJob = jobs.find((j) => j.id === jobId) || jobs.find((j) => j.state === "running") || jobs[0];
  useEffect(() => {
    if (tab !== "console" || !project || !logJob) return;
    let live = true;
    const load = () => api<{ text: string }>(`/projects/${project.id}/logs/${logJob.id}`).then((r) => live && setLog(r.text)).catch(() => {});
    void load();
    const t = setInterval(load, 2000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [tab, project?.id, logJob?.id]);
  useEffect(() => {
    if (tab !== "gpu") return;
    let live = true;
    const load = () =>
      api<NonNullable<typeof gpu>>("/gpu-monitor")
        .then((r) => {
          if (!live) return;
          setGpu(r);
          const g = r.gpus[0];
          if (g) {
            history.current.used = [...history.current.used, g.used_mb].slice(-150);
            history.current.util = [...history.current.util, g.util || 0].slice(-150);
          }
        })
        .catch(() => {});
    void load();
    const t = setInterval(load, 2000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [tab]);
  const tabs: [Tab, string, React.ReactNode][] = [
    ["content", "콘텐츠", <ImageIcon size={13} key="c" />],
    ["tasks", "작업 관리자", <ListChecks size={13} key="t" />],
    ["console", "Console", <Terminal size={13} key="o" />],
    ["gpu", "GPU Monitor", <Gauge size={13} key="g" />],
  ];
  return (
    <div className="bottom-panel">
      <div className="dock-tabs" role="tablist">
        {tabs.map(([k, label, icon]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
            {icon}
            {label}
            {k === "tasks" && jobs.some((j) => j.state === "running") && <span className="spinner" style={{ width: 9, height: 9 }} />}
          </button>
        ))}
        <span className="sp" />
        <button className="icon-btn" title="아래 패널 숨기기 (Ctrl+J)" aria-label="아래 패널 숨기기" onClick={onHide}>
          <ChevronDown size={15} />
        </button>
      </div>
      <div className="dock-body">
        {tab === "content" &&
          (project ? (
            <div className="col" style={{ gap: 6, height: "100%" }}>
              <div className="seg" style={{ height: 24, alignSelf: "flex-start" }}>
                <button aria-pressed={contentKind === "images"} onClick={() => setContentKind("images")}>이미지 {project.images.length}</button>
                <button aria-pressed={contentKind === "masks"} onClick={() => setContentKind("masks")}>마스크 {Object.keys(project.masks).length}</button>
              </div>
              <div className="content-strip">
                {contentKind === "images"
                  ? project.images.map((i) => (
                      <button key={i.name} className="cell" aria-pressed={selection?.kind === "image" && selection.name === i.name} onClick={() => onSelect({ kind: "image", name: i.name })} title={i.source_name}>
                        <div className="thumb"><img src={asset(project.id, i.thumbnail)} alt="" loading="lazy" /></div>
                        <div className="cap"><span className="ellip">{i.source_name}</span></div>
                      </button>
                    ))
                  : Object.entries(project.masks).map(([n, m]) => (
                      <button key={n} className="cell" aria-pressed={selection?.kind === "mask" && selection.name === n} onClick={() => onSelect({ kind: "mask", name: n })} title={n}>
                        <div className="thumb" style={{ background: "#000" }}>{m.valid && <img src={asset(project.id, m.path) + "?v=" + m.sha256} alt="" loading="lazy" style={{ objectFit: "contain" }} />}</div>
                        <div className="cap"><span className="ellip">{n}</span></div>
                      </button>
                    ))}
              </div>
            </div>
          ) : (
            <p className="hint">프로젝트를 열면 이미지와 마스크가 여기에 표시됩니다.</p>
          ))}
        {tab === "tasks" &&
          (jobs.length ? (
            <table className="tasks">
              <thead>
                <tr><th>작업</th><th>상태</th><th>진행</th><th>내용</th><th>소요</th><th /></tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} aria-selected={j.id === logJob?.id} onClick={() => setJobId(j.id)}>
                    <td>{stageName(j.stage)}</td>
                    <td>
                      <span className="row" style={{ gap: 5 }}>
                        {j.state === "running" ? <span className="spinner" /> : j.state === "completed" ? <CircleCheck size={13} className="ok" /> : j.state === "failed" ? <CircleX size={13} className="err" /> : <SkipForward size={12} className="warn" />}
                        {states[j.state] || j.state}
                      </span>
                    </td>
                    <td className="num">
                      {j.total ? (
                        <span className="row" style={{ gap: 6 }}>
                          <span className="bar thin" style={{ width: 70 }}><i style={{ width: `${((j.current || 0) / j.total) * 100}%`, background: j.state === "completed" ? "var(--ok)" : undefined }} /></span>
                          {fmt(j.current)} / {fmt(j.total)}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="ellip" style={{ maxWidth: 520 }} title={j.message}>{j.message}</td>
                    <td className="num t3">{duration(j)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {j.state === "running" && <button className="btn s danger" onClick={(e) => { e.stopPropagation(); onCancel(); }}><Square size={10} />중지</button>}
                      {(j.state === "failed" || j.state === "cancelled") && j.id === jobs.find((x) => x.stage === j.stage)?.id && !jobs.some((x) => x.state === "running") && ["colmap", "mesh", "train"].includes(j.stage) && (
                        <button className="btn s" onClick={(e) => { e.stopPropagation(); onRetry(j.stage); }}><RotateCcw size={11} />다시 시도</button>
                      )}
                      <button className="btn s ghost" onClick={(e) => { e.stopPropagation(); setJobId(j.id); setTab("console"); }}>기록</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="hint">아직 실행한 작업이 없습니다. 작업을 시작하면 진행률과 기록이 여기에 표시됩니다.</p>
          ))}
        {tab === "console" && (
          <div className="col" style={{ gap: 6, height: "100%" }}>
            <div className="row" style={{ gap: 8, fontSize: 12 }}>
              <span className="t2">{logJob ? `${stageName(logJob.stage)} · ${states[logJob.state] || logJob.state}` : "작업 없음"}</span>
              <span className="sp" />
              <button className="btn s ghost" disabled={!log} onClick={() => void navigator.clipboard?.writeText(log)}><Copy size={12} />복사</button>
              {project?.project_path && <button className="btn s ghost" onClick={() => void openPath(project.project_path + "/logs")}><FolderOpen size={12} />프로젝트 로그 폴더</button>}
              <button className="btn s ghost" onClick={() => void logFolder().then((p) => { if (p) void openPath(p); })}><FolderOpen size={12} />앱 로그 폴더</button>
            </div>
            <pre className="log-text console">{log.replace(/\x1b\[[0-9;]*m/g, "").split("\r").join("\n").slice(-30000) || "작업을 선택하면 실제 실행 기록이 표시됩니다."}</pre>
          </div>
        )}
        {tab === "gpu" &&
          (gpu?.gpus.length ? (
            <div className="gpu-grid">
              {gpu.gpus.map((g, i) => (
                <div key={i} className="gpu-card">
                  <b>{g.name}</b>
                  <div className="row" style={{ fontSize: 12 }}><span className="t3 grow">GPU 메모리</span><span className="num">{(g.used_mb / 1024).toFixed(1)} / {(g.total_mb / 1024).toFixed(1)} GB</span></div>
                  {i === 0 && <Sparkline values={history.current.used} max={g.total_mb} color="var(--accent)" />}
                  <div className="row" style={{ fontSize: 12 }}><span className="t3 grow">사용률</span><span className="num">{g.util ?? "—"}%</span></div>
                  {i === 0 && <Sparkline values={history.current.util} max={100} color="var(--info)" />}
                  <div className="row" style={{ fontSize: 12, gap: 14 }}><span className="t3">온도 <b className="t2 num">{g.temp ?? "—"}°C</b></span><span className="t3">전력 <b className="t2 num">{g.power?.toFixed(0) ?? "—"} / {g.power_limit?.toFixed(0) ?? "—"} W</b></span></div>
                </div>
              ))}
              <div className="gpu-card">
                <b>M4ML Studio GPU 작업</b>
                {gpu.apps.length ? gpu.apps.map((a) => (
                  <div key={a.pid} className="row" style={{ fontSize: 12 }}><span className="grow">{a.role}</span><span className="num t2">{(a.used_mb / 1024).toFixed(2)} GB</span><span className="t4 mono">pid {a.pid}</span></div>
                )) : <span className="hint">현재 GPU를 사용하는 작업이 없습니다.</span>}
              </div>
            </div>
          ) : (
            <p className="hint">{gpu ? "NVIDIA GPU를 찾을 수 없습니다." : "GPU 정보를 불러오고 있습니다…"}</p>
          ))}
      </div>
    </div>
  );
}
