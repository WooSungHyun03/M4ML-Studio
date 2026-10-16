import { lazy, Suspense, useState } from "react";
import { Box, CircleCheck, Download, Info, RotateCcw } from "lucide-react";
import { asset, post } from "../api";
import type { StageCtx } from "../context";
import { fmt } from "../context";

const MeshViewer = lazy(() => import("../MeshViewer"));

export function ModelStage({ ctx, toolbar }: { ctx: StageCtx; toolbar: (n: React.ReactNode) => React.ReactNode }) {
  const { project, base, blocked, active } = ctx;
  const mesh = project.mesh;
  const [stats, setStats] = useState<{ colored: boolean; vertices: number; triangles: number } | null>(null);
  const ready = project.stages.mesh === "completed" && mesh;
  const preview = mesh ? mesh.path + "/" + (mesh.preview_name || "preview.glb") : "";
  const ply = mesh ? mesh.path + "/fuse_post.ply" : "";
  const fileBase = project.name.replace(/[^\p{L}\p{N}_-]+/gu, "_").slice(0, 60) || "model";
  const running = active?.stage === "mesh";
  return (
    <>
      {toolbar(
        ready ? (
          <>
            <span className="row t3" style={{ fontSize: 12 }}><CircleCheck size={14} className="ok" />{project.input_mode === "mesh" ? "가져온 3D 모델" : "3D 모델 생성 완료"}</span>
            <span className="sp" />
            <a className="btn" href={asset(project.id, preview)} download={fileBase + ".glb"}><Download size={14} />GLB 내보내기</a>
            <a className="btn primary" href={asset(project.id, ply)} download={fileBase + ".ply"}><Download size={14} />PLY 내보내기</a>
          </>
        ) : null,
      )}
      {!ready ? (
        <div className="empty">
          {running ? <span className="spinner" style={{ width: 36, height: 36 }} /> : <Box size={44} className="ill" />}
          <h2>{running ? "3D 모델을 만들고 있습니다" : "아직 3D 모델이 없습니다"}</h2>
          <p>{running ? active?.message : "3D 재구성 학습이 끝나면 색상이 입혀진 3D 모델을 자동으로 만듭니다."}</p>
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
      ) : (
        <div className="workspace">
          <Suspense fallback={<div className="mesh-frame"><p className="viewer-message">3D 뷰어를 준비하고 있습니다…</p></div>}>
            <MeshViewer url={asset(project.id, preview)} legacyColors={!mesh!.color} onStats={setStats} />
          </Suspense>
          <aside className="panel insp" style={{ width: 300, flex: "none" }}>
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
          </aside>
        </div>
      )}
    </>
  );
}
