import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleCheck,
  Eraser,
  Info,
  Layers,
  Pencil,
  SkipForward,
  TriangleAlert,
  X,
} from "lucide-react";
import { api, asset, post } from "../api";
import type { MaskData } from "../api";
import type { StageCtx } from "../context";
import { InspectorPortal } from "../dock";
import { reviewed } from "../context";
import { setting, useSettingSaver } from "../TaskSettings";
import { MaskEditor } from "../MaskEditor";
import { useLivePrompt } from "../useLivePrompt";

const STATUS: Record<string, [string, string]> = {
  generated: ["미확인", "t3"],
  imported: ["불러옴 · 미확인", "t3"],
  approved: ["확인", "ok"],
  manual: ["수정", "acc"],
  skipped: ["건너뜀", "skipc"],
  invalid: ["수정 필요", "err"],
};

function statusIcon(m?: MaskData) {
  if (!m) return null;
  if (m.status === "approved") return <Check size={12} className="ok" />;
  if (m.status === "manual") return <Pencil size={11} className="acc" />;
  if (m.status === "skipped") return <SkipForward size={11} className="skipc" />;
  if (m.status === "invalid") return <X size={12} className="err" />;
  if (m.warnings?.length) return <TriangleAlert size={11} className="warn" />;
  return (
    <span className="t3" style={{ fontSize: 9 }}>
      ●
    </span>
  );
}

async function pngBase64(url: string) {
  const blob = await (await fetch(url)).blob();
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export function MaskStage({
  ctx,
  mode,
  toolbar,
}: {
  ctx: StageCtx;
  mode: "sam" | "review";
  toolbar: (n: React.ReactNode) => React.ReactNode;
}) {
  const { project, base, blocked, active } = ctx;
  const saveReview=useSettingSaver(base,"review",ctx.refresh,ctx.setError);
  const rows = useMemo(
    () =>
      [
        ...(project.colmap_report?.images.filter((i) => i.registered) || []),
      ].sort((a, b) =>
        setting(ctx.settings, "review", "warnings_first", false)
          ? Number(!!project.masks[b.name]?.warnings?.length) -
            Number(!!project.masks[a.name]?.warnings?.length)
          : 0,
      ),
    [project.colmap_report, project.masks, ctx.settings],
  );
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (!rows.find((r) => r.name === selected)) {
      const firstOpen =
        mode === "review"
          ? rows.find((r) => !reviewed(project.masks[r.name]?.status || ""))
          : undefined;
      setSelected((firstOpen || rows[0])?.name || "");
    }
  }, [rows, mode]);
  useEffect(() => {
    if (project.scene && project.stages.colmap === "completed")
      void post(`${base}/selection/warmup`, { gpu: ctx.gpu }).catch(() => {});
  }, [project.id, project.scene]);
  // Explorer ⇄ viewport selection sync
  useEffect(() => {
    const sel = ctx.selection;
    if (
      sel &&
      (sel.kind === "mask" || sel.kind === "image" || sel.kind === "camera") &&
      sel.name !== selected &&
      rows.some((r) => r.name === sel.name)
    ) {
      if (ctx.guard()) {
        ctx.setDirty(false);
        setSelected(sel.name);
      }
    }
  }, [ctx.selection]);
  useEffect(() => {
    if (
      selected &&
      !(
        ctx.selection &&
        "name" in ctx.selection &&
        ctx.selection.name === selected
      )
    )
      ctx.select({ kind: "mask", name: selected });
  }, [selected]);
  const filter=setting(ctx.settings,'review','review_filter','all');
  const visibleRows=rows.filter(r=>filter==='all'||filter==='warnings'&&!!project.masks[r.name]?.warnings?.length||filter==='reviewed'&&reviewed(project.masks[r.name]?.status||'')||filter==='unreviewed'&&!reviewed(project.masks[r.name]?.status||''));
  const index = rows.findIndex((r) => r.name === selected);
  const live = useLivePrompt(project, selected, ctx.gpu, true);
  const mask = project.masks[selected];
  const preview = live.previewPath;
  const editingBlocked = ctx.busy || (!!active && active.stage !== "preview");
  const masks = Object.values(project.masks);
  const counts = {
    approved: masks.filter((m) => m.status === "approved").length,
    manual: masks.filter((m) => m.status === "manual").length,
    skipped: masks.filter((m) => m.status === "skipped").length,
    open: masks.filter((m) => !reviewed(m.status)).length,
  };
  const total = rows.length || 1;

  function select(name: string) {
    if (!ctx.guard()) return;
    ctx.setDirty(false);
    setSelected(name);
  }
  function move(delta: number) {
    const next = rows[Math.max(0, Math.min(rows.length - 1, index + delta))];
    if (next) select(next.name);
  }
  async function confirmAndNext() {
    await ctx.action(async () => {
      const usePreview = live.points.length > 0 && preview && live.displayMatches;
      const body = usePreview
        ? { png: await pngBase64(asset(project.id, preview!)), approve: true }
        : { approve: true };
      await api(base + "/masks/" + encodeURIComponent(selected), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      move(1);
    });
  }
  function skipRest() {
    const n = counts.open;
    if (!n) return;
    if (window.confirm(`남은 ${n}장의 검토를 건너뛸까요?\n\n건너뛴 사진은 자동으로 만든 마스크 그대로 학습에 사용되며 '건너뜀'으로 표시됩니다. 비어 있거나 잘못된 마스크는 계속 학습을 막습니다.`))
      void ctx.action(() => post(base + "/skip-review", { confirmed: true }));
  }
  useEffect(() => {
    if (mode !== "review") return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input,select,textarea")) return;
      if (e.key === " " && !e.repeat) {
        e.preventDefault();
        if (!blocked && !live.pending && (mask?.valid || preview)) void confirmAndNext();
      }
      if (e.key === "S" && e.shiftKey) skipRest();
      if (t.tagName !== "CANVAS" && (e.key === "a" || e.key === "ArrowLeft")) move(-1);
      if (t.tagName !== "CANVAS" && (e.key === "d" || e.key === "ArrowRight")) move(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (project.stages.colmap !== "completed" || !selected)
    return (
      <>
        {toolbar(null)}
        <div className="empty">
          <Layers size={44} className="ill" />
          <h2>아직 마스크가 없습니다</h2>
          <p>
            카메라 정합을 먼저 완료하면, 대표 사진 한 장에서 객체를 클릭해
            마스크를 만들고 등록된 모든 사진으로 전파할 수 있습니다.
          </p>
          <div className="row">
            <button className="btn" onClick={() => ctx.setStage("colmap")}>
              카메라 정합으로 이동
            </button>
          </div>
        </div>
      </>
    );

  const canPropagate =
    !blocked &&
    !live.pending &&
    live.displayMatches &&
    !!preview &&
    live.points.length > 0;
  const liveStatus = live.pending ? (
    <>
      <span className="spinner" />
      <b>객체 선택</b>
      <span>최신 클릭을 계산하고 있습니다</span>
    </>
  ) : live.error ? (
    <>
      <TriangleAlert size={13} className="warn" />
      <span>{live.error}</span>
    </>
  ) : preview && live.displayMatches ? (
    <>
      <CircleCheck size={13} className="ok" />
      <b>최신 클릭 반영됨</b>
      {project.live_prompt?.seconds != null && (
        <span>{project.live_prompt.seconds.toFixed(2)}초</span>
      )}
    </>
  ) : (
    <>
      <Info size={13} />
      <span>클릭할 때마다 마스크가 자동으로 갱신됩니다</span>
    </>
  );

  return (
    <>
      {toolbar(
        mode === "sam" ? (
          <>
            <button
              className="btn ghost s"
              disabled={!live.points.length || editingBlocked}
              onClick={() => live.change([])}
            >
              <Eraser size={14} />
              클릭 모두 지우기
            </button>
            <span className="sp" />
            <span className="t3" style={{ fontSize: 12 }}>
              대표 사진 <b className="mono t2">{selected}</b>
            </span>
            <button
              className="btn"
              disabled={
                !canPropagate ||
                !masks.length ||
                !masks.some((m) => !reviewed(m.status))
              }
              onClick={() => {
                if (
                  window.confirm(
                    `현재 클릭으로 앞뒤 ${setting(ctx.settings, "segmentation", "propagation_radius", 2)}장씩, 아직 확인하지 않은 사진만 다시 전파할까요? 확인·수정된 마스크는 보존합니다.`,
                  )
                )
                  void ctx.action(() =>
                    post(base + "/jobs/sam", {
                      gpu: ctx.gpu,
                      reference: selected,
                      points: live.points.map((p) => [p.x, p.y]),
                      labels: live.points.map((p) => p.label),
                      confirmed: true,
                      radius: setting(
                        ctx.settings,
                        "segmentation",
                        "propagation_radius",
                        2,
                      ),
                    }),
                  );
              }}
            >
              주변만 다시 전파
            </button>
            <button
              className="btn primary"
              disabled={!canPropagate}
              onClick={() => {
                if (
                  window.confirm(
                    `미리보기의 객체가 맞나요? 이 객체로 등록된 ${rows.length}장의 마스크를 만듭니다.`,
                  )
                )
                  void ctx.action(() =>
                    post(base + "/jobs/sam", {
                      gpu: ctx.gpu,
                      reference: selected,
                      points: live.points.map((p) => [p.x, p.y]),
                      labels: live.points.map((p) => p.label),
                      confirmed: true,
                    }),
                  );
              }}
            >
              <Layers size={15} />
              등록된 {rows.length}장에 전파
            </button>
          </>
        ) : (
          <>
            <span className="cnt">
              <CircleCheck size={14} className="ok" />
              확인 <b>{counts.approved}</b>
            </span>
            <span className="cnt">
              <Pencil size={13} className="acc" />
              수정 <b>{counts.manual}</b>
            </span>
            <span className="cnt">
              <SkipForward size={13} className="skipc" />
              건너뜀 <b>{counts.skipped}</b>
            </span>
            <span className="cnt">
              <span className="t3">○</span>미확인 <b>{counts.open}</b>
            </span>
            <div className="stack" aria-hidden>
              <i
                style={{
                  width: `${(counts.approved / total) * 100}%`,
                  background: "var(--ok)",
                }}
              />
              <i
                style={{
                  width: `${(counts.manual / total) * 100}%`,
                  background: "var(--accent)",
                }}
              />
              <i
                style={{
                  width: `${(counts.skipped / total) * 100}%`,
                  background: "var(--skip)",
                }}
              />
            </div>
            <span className="sp" />
            <button
              className="btn"
              disabled={blocked || !counts.open}
              onClick={skipRest}
            >
              <SkipForward size={14} />
              남은 검토 건너뛰기 <span className="kbd">Shift+S</span>
            </button>
            <button
              className="btn primary"
              disabled={blocked || project.stages.review !== "completed"}
              onClick={() => ctx.setStage("train")}
            >
              3D 재구성으로
              <ArrowRight size={15} />
            </button>
          </>
        ),
      )}
      <div className="mask-shell">
        <div className="mask-main">
          <MaskEditor
            settings={ctx.settings}
            onDisplayChange={saveReview}
            key={selected}
            image={asset(project.id, project.scene + "/images/" + selected)}
            mask={
              preview
                ? asset(project.id, preview)
                : mask?.valid
                  ? asset(project.id, mask.path) + "?v=" + mask.sha256
                  : undefined
            }
            resetMask={
              mask?.valid
                ? asset(project.id, mask.generated_path || mask.path)
                : undefined
            }
            points={live.points}
            onPoints={live.change}
            disabled={editingBlocked}
            pending={live.pending}
            pointUndo={live.undo}
            pointRedo={live.redo}
            canPointUndo={live.canUndo}
            canPointRedo={live.canRedo}
            allowSave={Boolean(mask)}
            onDirty={ctx.setDirty}
            onPreview={live.retry}
            onPrevious={() => move(-1)}
            onNext={() => move(1)}
            status={liveStatus}
            label={
              <>
                <span className="mono" style={{ color: "#ececef" }}>
                  {selected}
                </span>
                {mask && (
                  <span className={STATUS[mask.status]?.[1]}>
                    {STATUS[mask.status]?.[0]}
                  </span>
                )}
              </>
            }
            saveLabel="수정 저장"
            onSave={async (png) => {
              await api(base + "/masks/" + encodeURIComponent(selected), {
                method: "PUT",
                body: JSON.stringify({ png, approve: true }),
              });
              await ctx.refresh();
              if (setting(ctx.settings, "review", "auto_next", false)) move(1);
            }}
          />
          {mode === "review" && (
            <div className="action-bar">
              <button
                className="btn l"
                onClick={() => move(-1)}
                disabled={index <= 0}
              >
                <ArrowLeft size={15} />
                이전 <span className="kbd">A</span>
              </button>
              <div className="pos">
                <b>{index + 1}</b>
                <span>/ {rows.length}</span>
              </div>
              <button
                className="btn l"
                onClick={() => move(1)}
                disabled={index >= rows.length - 1}
              >
                다음 <span className="kbd">D</span>
                <ArrowRight size={15} />
              </button>
              <span className="vsep" />
              <button
                className="btn primary l"
                style={{ minWidth: 200 }}
                disabled={
                  blocked ||
                  live.pending ||
                  !(mask?.valid || (preview && live.displayMatches))
                }
                onClick={() => void confirmAndNext()}
              >
                <Check size={16} />
                {live.points.length && preview
                  ? "수정 완료 · 다음"
                  : "확인 · 다음"}{" "}
                <span className="kbd">Space</span>
              </button>
              <span className="sp" />
              {mask?.warnings?.length ? (
                <span className="badge warn">
                  <TriangleAlert size={12} />
                  검토 권장
                </span>
              ) : null}
            </div>
          )}
          <div className="film">
            <div className="film-h">
              <b className="t2">등록된 사진</b>
              <span className="num">{rows.length}장</span>
              <span className="t4">·</span>
              <span>카메라 위치 순서</span>
              <span className="sp" />
              {mode === "sam" && !masks.length && (
                <span>대표 사진에서 객체를 지정한 뒤 전파하세요</span>
              )}
            </div>
            <div className="film-row">
              {!visibleRows.length&&<p className="hint" style={{padding:12}}>필터에 맞는 사진이 없습니다.</p>}
              {visibleRows.map((r, n) => {
                const m = project.masks[r.name];
                return (
                  <button
                    key={r.name}
                    className="cell"
                    aria-pressed={r.name === selected}
                    onClick={() => select(r.name)}
                    title={r.name}
                  >
                    <div
                      className={
                        "thumb" +
                        (m && !reviewed(m.status) && mode === "review"
                          ? " dim"
                          : "")
                      }
                    >
                      <img
                        src={asset(
                          project.id,
                          project.images.find((p) => p.name === r.name)
                            ?.thumbnail || project.scene + "/images/" + r.name,
                        )}
                        alt=""
                        loading="lazy"
                      />
                      <span className="idx">{n + 1}</span>
                      {m && <span className="flag b">{statusIcon(m)}</span>}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <InspectorPortal>
          {mode === "sam" ? (
            <>
              <div className="sec">
                <div className="sec-h">
                  <b>클릭 프롬프트</b>
                  <span>
                    포함 {live.points.filter((p) => p.label).length} · 제외{" "}
                    {live.points.filter((p) => !p.label).length}
                  </span>
                </div>
                {!live.points.length && (
                  <p className="hint">
                    객체 안쪽을 클릭하세요. 배경이나 다른 물체는 Alt+클릭 또는
                    오른쪽 클릭으로 제외합니다.
                  </p>
                )}
                <div className="col" style={{ gap: 2 }}>
                  {live.points.map((p, i) => (
                    <div className="prompt-row" key={i}>
                      <span className={"pdot " + (p.label ? "p-pos" : "p-neg")}>
                        {p.label ? "+" : "−"}
                      </span>
                      <span>
                        {p.label ? "포함" : "제외"} #{i + 1}
                        {i === live.points.length - 1 && live.pending && (
                          <span className="spinner" style={{ marginLeft: 6, width: 10, height: 10 }} />
                        )}
                      </span>
                      <span className="mono t3">
                        {Math.round(p.x)}, {Math.round(p.y)}
                      </span>
                      <button
                        className="icon-btn"
                        style={{ width: 22, height: 22 }}
                        aria-label={`${i + 1}번 클릭 삭제`}
                        onClick={() =>
                          live.change(live.points.filter((_, k) => k !== i))
                        }
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
              <div className="sec">
                <div className="sec-h">
                  <b>현재 마스크</b>
                </div>
                <div className="kv">
                  <span>객체 영역</span>
                  <span>
                    {project.preview?.coverage != null && live.displayMatches
                      ? (project.preview.coverage * 100).toFixed(1) + "%"
                      : mask?.coverage != null
                        ? (mask.coverage * 100).toFixed(1) + "%"
                        : "—"}
                  </span>
                  <span>상태</span>
                  <span>
                    {live.pending
                      ? "계산 중"
                      : preview && live.displayMatches
                        ? "최신 클릭 반영"
                        : mask
                          ? STATUS[mask.status]?.[0]
                          : "클릭 대기"}
                  </span>
                </div>
              </div>
              <div className="sec">
                <div className="sec-h">
                  <b>실시간 계산</b>
                  <span>최신 클릭 우선</span>
                </div>
                {live.error && (
                  <div className="callout err" role="alert">
                    <span>
                      {live.error}
                      <button
                        className="btn s"
                        style={{ marginTop: 8 }}
                        disabled={
                          editingBlocked ||
                          !live.points.some((p) => p.label === 1)
                        }
                        onClick={live.retry}
                      >
                        같은 클릭으로 다시 계산
                      </button>
                    </span>
                  </div>
                )}
                <p className="hint">
                  계산 중에 새로 클릭하면 이전 클릭의 결과는 화면에 반영하지
                  않습니다. 첫 클릭은 모델을 불러오느라 조금 더 걸립니다.
                </p>
              </div>
              <div className="sec">
                <div className="callout info">
                  <Info size={15} />
                  <span>
                    전파는 카메라 위치가 가까운 순서로 진행합니다. 시점 간격이
                    큰 사진은 다음 단계에서 꼭 확인하세요.
                  </span>
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="sec">
                <div className="sec-h">
                  <b>사진 정보</b>
                  {mask && (
                    <span
                      className={
                        "badge " +
                        (mask.status === "manual"
                          ? "acc"
                          : mask.status === "approved"
                            ? "ok"
                            : mask.status === "skipped"
                              ? "skip"
                              : "neu")
                      }
                    >
                      {STATUS[mask.status]?.[0]}
                    </span>
                  )}
                </div>
                <div className="kv">
                  <span>파일</span>
                  <span className="mono">{selected}</span>
                  <span>순서</span>
                  <span>
                    {index + 1} / {rows.length}
                  </span>
                  <span>객체 영역</span>
                  <span>
                    {mask?.coverage != null
                      ? (mask.coverage * 100).toFixed(1) + "%"
                      : "—"}
                  </span>
                  <span>출처</span>
                  <span>
                    {mask?.source === "imported"
                      ? "가져온 마스크"
                      : "자동 전파"}
                  </span>
                </div>
              </div>
              <div className="sec">
                <div className="sec-h">
                  <b>자동 점검</b>
                </div>
                {mask?.warnings?.length ? (
                  mask.warnings.map((w) => (
                    <div
                      className="callout warn"
                      key={w}
                      style={{ marginBottom: 6 }}
                    >
                      <TriangleAlert size={14} />
                      {w}
                    </div>
                  ))
                ) : mask?.error ? (
                  <div className="callout err">
                    <X size={14} />
                    {mask.error}
                  </div>
                ) : (
                  <p className="row t2" style={{ fontSize: 12 }}>
                    <CircleCheck size={14} className="ok" />
                    특이 사항 없음
                  </p>
                )}
              </div>
              <div className="sec">
                <div className="sec-h">
                  <b>클릭으로 수정</b>
                </div>
                <p className="hint">
                  빠진 부분은 클릭, 잘못 포함된 부분은 Alt+클릭하면 이 사진의
                  마스크를 바로 다시 계산합니다. 붓·지우개로 직접 고칠 수도
                  있습니다.
                </p>
                {live.points.length > 0 && (
                  <button
                    className="btn s ghost"
                    style={{ marginTop: 8 }}
                    onClick={() => live.change([])}
                  >
                    <Eraser size={13} />
                    클릭 지우기
                  </button>
                )}
              </div>
              <div className="sec">
                <div className="sec-h">
                  <b>단축키</b>
                </div>
                <div className="kv" style={{ gridTemplateColumns: "auto 1fr" }}>
                  <span className="kbd">A / D</span>
                  <span style={{ textAlign: "left" }}>이전 · 다음 사진</span>
                  <span className="kbd">Space</span>
                  <span style={{ textAlign: "left" }}>
                    확인(수정 완료) 후 다음
                  </span>
                  <span className="kbd">1 / 2</span>
                  <span style={{ textAlign: "left" }}>포함 · 제외 클릭</span>
                  <span className="kbd">Tab</span>
                  <span style={{ textAlign: "left" }}>원본 ↔ 마스크</span>
                  <span className="kbd">Shift+S</span>
                  <span style={{ textAlign: "left" }}>남은 검토 건너뛰기</span>
                </div>
              </div>
            </>
          )}
        </InspectorPortal>
      </div>
    </>
  );
}
