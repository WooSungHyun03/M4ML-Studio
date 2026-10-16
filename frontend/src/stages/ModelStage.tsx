import { lazy, Suspense, useEffect, useState } from "react";
import { Box, CircleCheck, Download, ExternalLink, Info, RotateCcw, Sparkles } from "lucide-react";
import { api, asset, post } from "../api";
import type { StageCtx } from "../context";
import { InspectorPortal } from "../dock";
import { fmt, mb } from "../context";
import type { LiveInfo, LiveStats } from "../GaussianViewer";

const MeshViewer = lazy(() => import("../MeshViewer"));
const GaussianViewer = lazy(() => import("../GaussianViewer"));
type View = "live" | "mesh";
const VIEW_KEY = "m4ml-model-view";
const LIVE_STATE: Record<string, string> = {
  starting: "준비 중",
  loading: "불러오는 중",
  rendering: "렌더링 중",
  disconnected: "연결 끊김",
  out_of_memory: "메모리 부족",
  busy: "GPU 사용 중",
  failed: "렌더링 실패",
};

function savedView(): View | null {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return v === "live" || v === "mesh" ? v : null;
  } catch {
    return null;
  }
}

export function ModelStage({ ctx, toolbar }: { ctx: StageCtx; toolbar: (n: React.ReactNode) => React.ReactNode }) {
  const { project, base, blocked, active } = ctx;
  const mesh = project.mesh;
  const [stats, setStats] = useState<{ colored: boolean; vertices: number; triangles: number } | null>(null);
  const [live, setLive] = useState<LiveInfo | null>(null),
    [liveStats, setLiveStats] = useState<LiveStats | null>(null),
    [iteration, setIteration] = useState<number | undefined>(undefined),
    [view, setView] = useState<View | null>(savedView());
  const meshReady = project.stages.mesh === "completed" && !!mesh;
  const preview = mesh ? mesh.path + "/" + (mesh.preview_name || "preview.glb") : "";
  const ply = mesh ? mesh.path + "/fuse_post.ply" : "";
  const fileBase = project.name.replace(/[^\p{L}\p{N}_-]+/gu, "_").slice(0, 60) || "model";
  const running = active?.stage === "mesh";
  const gpuJob = !!active && ["train", "mesh", "colmap", "sam"].includes(active.stage);
  const trainKey = `${project.training?.path}|${project.training?.iterations}|${project.stages.train}`;

  // The trained Gaussian result is recognised automatically whenever the project's training changes.
  useEffect(() => {
    let alive = true;
    api<LiveInfo>(`/projects/${project.id}/live-render`)
      .then((r) => alive && setLive(r))
      .catch(() => alive && setLive({ available: false, reason: "학습 결과를 확인하지 못했습니다." }));
    return () => {
      alive = false;
    };
  }, [project.id, trainKey]);

  const liveReady = !!live?.available && project.stages.train === "completed";
  const current: View | null =
    view === "live" && liveReady ? "live" : view === "mesh" && meshReady ? "mesh" : meshReady ? "mesh" : liveReady ? "live" : null;
  const choose = (v: View) => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* choice simply not remembered */
    }
  };
  const switcher = (
    <div className="seg" role="group" aria-label="3D 표시 방식" style={{ height: 28 }}>
      <button aria-pressed={current === "live"} disabled={!liveReady} title={liveReady ? "학습된 결과를 자유 시점에서 실시간 렌더링" : live?.reason} onClick={() => choose("live")}>
        <Sparkles size={13} />실시간 렌더
      </button>
      <button aria-pressed={current === "mesh"} disabled={!meshReady} title={meshReady ? "색상 메시" : "아직 3D 메시가 없습니다"} onClick={() => choose("mesh")}>
        <Box size={13} />메시
      </button>
    </div>
  );

  return (
    <>
      {toolbar(
        current ? (
          <>
            {switcher}
            <span className="row t3" style={{ fontSize: 12 }}>
              <CircleCheck size={14} className="ok" />
              {current === "live" ? `학습 결과 · ${fmt(live?.model?.iteration)}회` : project.input_mode === "mesh" ? "가져온 3D 모델" : "3D 모델 생성 완료"}
            </span>
            <span className="sp" />
            {current === "mesh" && (
              <>
                <a className="btn" href={asset(project.id, preview)} download={fileBase + ".glb"}><Download size={14} />GLB 내보내기</a>
                <a className="btn primary" href={asset(project.id, ply)} download={fileBase + ".ply"}><Download size={14} />PLY 내보내기</a>
              </>
            )}
          </>
        ) : null,
      )}
      {!current ? (
        <div className="empty">
          {running ? <span className="spinner" style={{ width: 36, height: 36 }} /> : <Box size={44} className="ill" />}
          <h2>{running ? "3D 모델을 만들고 있습니다" : "아직 3D 모델이 없습니다"}</h2>
          <p>{running ? active?.message : "3D 재구성 학습이 끝나면 학습 결과를 실시간 렌더로 볼 수 있고, 색상이 입혀진 3D 메시를 자동으로 만듭니다."}</p>
          <div className="row">
            {project.stages.train === "completed" && !running ? (
              <button className="btn" disabled={blocked} onClick={() => void ctx.action(() => post(base + "/jobs/mesh", { gpu: ctx.gpu }))}>
                <RotateCcw size={14} />3D 모델 다시 만들기
              </button>
            ) : !running ? (
              <button className="btn" onClick={() => ctx.setStage("train")}>3D 재구성으로 이동</button>
            ) : null}
          </div>
        </div>
      ) : current === "live" && live?.model ? (
        <div className="workspace">
          {gpuJob ? (
            <div className="empty">
              <span className="spinner" style={{ width: 32, height: 32 }} />
              <h2>GPU 작업이 실행 중입니다</h2>
              <p>{active?.message} · 작업이 끝나면 실시간 렌더를 다시 시작할 수 있습니다.</p>
            </div>
          ) : (
            <Suspense fallback={<div className="mesh-frame"><p className="viewer-message">실시간 렌더를 준비하고 있습니다…</p></div>}>
              <GaussianViewer projectId={project.id} gpu={ctx.gpu} info={live} iteration={iteration} onStats={setLiveStats} />
            </Suspense>
          )}
          <InspectorPortal>
            <div className="sec">
              <div className="sec-h">
                <b>학습 결과</b>
                <span className={"badge " + (liveStats?.state === "rendering" ? "ok" : liveStats && liveStats.state !== "loading" ? "warn" : "")}>{LIVE_STATE[liveStats?.state || "starting"]}</span>
              </div>
              <div className="stat2">
                <div><div className="l">Gaussian</div><div className="big-n" style={{ fontSize: 20 }}>{fmt(live.model.gaussians)}</div></div>
                <div><div className="l">학습 반복</div><div className="big-n" style={{ fontSize: 20 }}>{fmt(iteration ?? live.model.iteration)}</div></div>
              </div>
              <div className="kv" style={{ marginTop: 12 }}>
                <span>파일 크기</span><span>{mb(live.model.ply_bytes)}</span>
                <span>학습 시점</span><span>{live.model.cameras.length}개</span>
                {liveStats?.status && <><span>모델 로딩</span><span className="num">{liveStats.status.load_seconds.toFixed(1)}초</span></>}
                {liveStats?.firstFrameMs != null && <><span>첫 화면까지</span><span className="num">{(liveStats.firstFrameMs / 1000).toFixed(1)}초</span></>}
                {liveStats?.size && <><span>렌더 해상도</span><span className="num">{liveStats.size[0]} × {liveStats.size[1]}</span></>}
                {liveStats?.renderMs != null && <><span>렌더 시간</span><span className="num">{liveStats.renderMs.toFixed(1)} ms</span></>}
                {liveStats?.latencyMs != null && <><span>응답 지연</span><span className="num">{liveStats.latencyMs} ms</span></>}
              </div>
              {liveStats?.message && liveStats.state !== "rendering" && <div className="callout warn" style={{ marginTop: 10 }}><Info size={14} />{liveStats.message}</div>}
              {live.model.iterations.length > 1 && (
                <label className="field" style={{ marginTop: 10 }}>
                  표시할 학습 반복
                  <select value={iteration ?? live.model.iteration} onChange={(e) => setIteration(Number(e.target.value))}>
                    {live.model.iterations.map((it, i, all) => <option key={it} value={it}>{fmt(it)}회{i === all.length - 1 ? " (최신)" : ""}</option>)}
                  </select>
                </label>
              )}
              <p className="hint" style={{ marginTop: 8 }}>메시로 변환하기 전, 학습된 결과 자체를 렌더링한 화면입니다. 다른 화면으로 이동하면 GPU 메모리를 반환합니다.</p>
            </div>
            {live.external_viewer && (
              <div className="sec">
                <details className="advanced">
                  <summary>고급</summary>
                  <p className="hint">같은 렌더러에 연결된 연구용 외부 뷰어 창을 엽니다. 엔진 정보는 설정 › 고급 정보에 있습니다.</p>
                  <button className="btn s" disabled={liveStats?.state !== "rendering"} onClick={() => void ctx.action(() => post(`/projects/${project.id}/live-render/external`))}>
                    <ExternalLink size={13} />외부 뷰어 열기
                  </button>
                </details>
              </div>
            )}
          </InspectorPortal>
        </div>
      ) : (
        <div className="workspace">
          <Suspense fallback={<div className="mesh-frame"><p className="viewer-message">3D 뷰어를 준비하고 있습니다…</p></div>}>
            <MeshViewer url={asset(project.id, preview)} legacyColors={!mesh!.color} onStats={setStats} fileBase={fileBase} />
          </Suspense>
          <InspectorPortal>
            <div className="sec">
              <div className="sec-h"><b>3D 모델 정보</b>{mesh!.colors !== false ? <span className="badge ok"><CircleCheck size={11} />색상 포함</span> : <span className="badge warn">색상 없음</span>}</div>
              <div className="stat2">
                <div><div className="l">정점</div><div className="big-n" style={{ fontSize: 20 }}>{fmt(mesh!.vertices)}</div></div>
                <div><div className="l">삼각형</div><div className="big-n" style={{ fontSize: 20 }}>{fmt(mesh!.triangles)}</div></div>
              </div>
              <div className="kv" style={{ marginTop: 12 }}>
                <span>색상</span><span>{mesh!.colors !== false ? "정점 RGB" : "없음 (형상만)"}</span>
                <span>뷰어 확인</span><span>{stats ? (stats.colored ? "색상 표시 중" : "형상만 표시") : "불러오는 중"}</span>
                {mesh!.bytes ? <><span>파일 크기</span><span>{(mesh!.bytes / 1024 ** 2).toFixed(1)} MB</span></> : null}
                {mesh!.iterations ? <><span>학습</span><span>{fmt(mesh!.iterations)}회</span></> : null}
                {mesh!.mesh_res ? <><span>모델 해상도</span><span>{mesh!.mesh_res}</span></> : null}
              </div>
              <p className="hint" style={{ marginTop: 8 }}>크기는 카메라 정합 좌표 단위이며 실제 치수가 아닙니다.</p>
            </div>
            <div className="sec">
              <div className="sec-h"><b>내보내기</b></div>
              <div className="col">
                <a className="btn primary block" href={asset(project.id, ply)} download={fileBase + ".ply"}><Download size={15} />PLY 내보내기 (원본 정점 색상)</a>
                <a className="btn block" href={asset(project.id, preview)} download={fileBase + ".glb"}><Download size={15} />GLB 내보내기 (웹·3D 도구용)</a>
              </div>
              <p className="hint" style={{ marginTop: 8 }}>PLY는 생성된 색상을 그대로 담은 원본입니다. GLB는 다른 3D 도구에서 같은 색이 보이도록 변환한 사본입니다.</p>
            </div>
            <div className="sec">
              <div className="callout"><Info size={15} /><span>가려지거나 촬영되지 않은 부분은 구멍이 있거나 매끄럽지 않을 수 있습니다.</span></div>
            </div>
          </InspectorPortal>
        </div>
      )}
    </>
  );
}
