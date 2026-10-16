import { CircleCheck, CircleX, Download, X } from "lucide-react";
import { asset } from "./api";
import type { Project } from "./api";
import type { Selection } from "./context";
import { fmt, mb } from "./context";

const MASK_STATUS: Record<string, string> = {
  generated: "자동 생성 · 미확인",
  imported: "가져온 마스크 · 미확인",
  approved: "확인됨",
  manual: "직접 수정됨",
  skipped: "검토 건너뜀",
  invalid: "수정 필요",
};

/** Details of the current Explorer selection (top of the Inspector dock). */
export function SelectionInspector({ project, selection, onClear }: { project: Project; selection: Selection; onClear: () => void }) {
  if (!selection) return null;
  const head = (title: string) => (
    <div className="sec-h">
      <b>{title}</b>
      <button className="icon-btn" style={{ width: 22, height: 22 }} aria-label="선택 해제" title="선택 해제 (Esc)" onClick={onClear}>
        <X size={13} />
      </button>
    </div>
  );
  if (selection.kind === "image" || selection.kind === "camera") {
    const img = project.images.find((i) => i.name === selection.name);
    const cam = project.colmap_report?.images.find((i) => i.name === selection.name);
    return (
      <div className="sec">
        {head(selection.kind === "image" ? "이미지" : "카메라")}
        {img && (
          <div className="preview-box" style={{ marginBottom: 10 }}>
            <img src={asset(project.id, img.thumbnail)} alt={img.source_name} />
          </div>
        )}
        <div className="kv">
          <span>파일</span>
          <span className="mono">{img?.source_name || selection.name}</span>
          {img && (
            <>
              <span>해상도</span>
              <span className="num">{img.size.join(" × ")}</span>
              <span>화소</span>
              <span className="num">{((img.size[0] * img.size[1]) / 1e6).toFixed(1)} MP</span>
              <span>저장 이름</span>
              <span className="mono">{img.name}</span>
            </>
          )}
          <span>카메라 등록</span>
          <span>
            {cam ? (
              cam.registered ? (
                <span className="ok row" style={{ justifyContent: "flex-end", gap: 4 }}><CircleCheck size={12} />등록됨</span>
              ) : (
                <span className="err row" style={{ justifyContent: "flex-end", gap: 4 }}><CircleX size={12} />{cam.reason}</span>
              )
            ) : (
              <span className="t3">정합 전</span>
            )}
          </span>
          {cam && cam.feature_count > 0 && (
            <>
              <span>특징점</span>
              <span className="num">{fmt(cam.feature_count)}</span>
            </>
          )}
        </div>
        {img?.advisories?.map((a) => (
          <p key={a} className="advisory" style={{ marginTop: 8 }}>{a}</p>
        ))}
      </div>
    );
  }
  if (selection.kind === "mask") {
    const m = project.masks[selection.name];
    if (!m) return null;
    return (
      <div className="sec">
        {head("마스크")}
        {m.valid && (
          <div className="preview-box" style={{ marginBottom: 10, background: "#000" }}>
            <img src={asset(project.id, m.path) + "?v=" + m.sha256} alt="" />
          </div>
        )}
        <div className="kv">
          <span>사진</span>
          <span className="mono">{selection.name}</span>
          <span>크기</span>
          <span className="num">{project.images.find((i) => i.name === selection.name)?.size.join(" × ") || "—"}</span>
          <span>객체 영역</span>
          <span>{m.coverage != null ? (m.coverage * 100).toFixed(1) + "%" : "—"}</span>
          <span>검토 상태</span>
          <span>{MASK_STATUS[m.status] || m.status}</span>
          <span>수정 기록</span>
          <span>{m.status === "manual" ? "직접 수정본 저장" : m.source === "imported" ? "가져온 원본" : "자동 생성 원본"}{m.generated_path && m.generated_path !== m.path ? " · 원본 보존" : ""}</span>
        </div>
        {m.warnings?.map((w) => (
          <p key={w} className="advisory" style={{ marginTop: 8 }}>{w}</p>
        ))}
        {m.error && <p className="error" style={{ marginTop: 8 }}>{m.error}</p>}
      </div>
    );
  }
  if (selection.kind === "training") {
    const t = project.training,
      p = project.training_partial;
    return (
      <div className="sec">
        {head("학습 결과")}
        <div className="kv">
          {t && (
            <>
              <span>반복 횟수</span>
              <span>{fmt(t.iterations)}</span>
              <span>가우시안</span>
              <span>{fmt(t.gaussians)}</span>
              {t.resumed_from ? (
                <>
                  <span>이어서 학습</span>
                  <span>{fmt(t.resumed_from)}회부터</span>
                </>
              ) : null}
            </>
          )}
          {p && (
            <>
              <span>중단 지점</span>
              <span>{fmt(p.checkpoint)} / {fmt(p.iterations)}회</span>
            </>
          )}
        </div>
      </div>
    );
  }
  if (selection.kind === "checkpoint") {
    return (
      <div className="sec">
        {head("체크포인트")}
        <div className="kv">
          <span>파일</span>
          <span className="mono">{selection.name}</span>
          <span>반복 횟수</span>
          <span>{fmt(selection.iteration)}</span>
          <span>크기</span>
          <span>{mb(selection.bytes)}</span>
          <span>이어서 학습</span>
          <span>{selection.resumable ? <span className="acc">가능</span> : "—"}</span>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>{selection.path}</p>
      </div>
    );
  }
  if (selection.kind === "mesh") {
    const mesh = project.mesh;
    return (
      <div className="sec">
        {head("3D 모델 파일")}
        <div className="kv">
          <span>파일</span>
          <span className="mono">{selection.name}</span>
          <span>파일 크기</span>
          <span>{mb(selection.bytes)}</span>
          {mesh && (
            <>
              <span>정점</span>
              <span>{fmt(mesh.vertices)}</span>
              <span>삼각형</span>
              <span>{fmt(mesh.triangles)}</span>
              <span>정점 색상</span>
              <span>{mesh.colors !== false ? <span className="ok">있음 (RGB)</span> : <span className="warn">없음</span>}</span>
            </>
          )}
        </div>
        <a className="btn block" style={{ marginTop: 10 }} href={asset(project.id, selection.path)} download={selection.name.split("/").pop()}>
          <Download size={14} />내보내기
        </a>
      </div>
    );
  }
  return null;
}
