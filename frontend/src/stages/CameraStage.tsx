import { lazy, Suspense, useState } from "react";
import {
  ArrowRight,
  Cpu,
  Gauge,
  Info,
  Play,
  RotateCcw,
  CircleCheck,
  CircleX,
} from "lucide-react";
import { setting } from "../TaskSettings";
import { asset, post } from "../api";
import type { StageCtx } from "../context";
import { InspectorPortal } from "../dock";
import { fmt } from "../context";

const SparseViewer = lazy(() => import("../SparseViewer"));

const STEP_LABEL: Record<string, string> = {
  feature_extraction: "특징점 추출",
  feature_matching: "특징점 매칭",
  mapper: "카메라 자세 추정",
  undistortion: "왜곡 보정",
};

export function CameraStage({
  ctx,
  toolbar,
}: {
  ctx: StageCtx;
  toolbar: (n: React.ReactNode) => React.ReactNode;
}) {
  const { project, base, blocked, health, active } = ctx;
  const matching = setting(ctx.settings, "camera", "matching", "exhaustive");
  const [tab, setTab] = useState<"ok" | "fail" | "all">("ok"),
    [view, setView] = useState<"photos" | "points">("photos");
  const picked =
    ctx.selection?.kind === "camera" || ctx.selection?.kind === "image"
      ? ctx.selection.name
      : undefined;
  const report = project.colmap_report;
  const running = active?.stage === "colmap";
  const gpuEngine = health?.colmap?.gpu;
  const canRun = !blocked && project.stages.import === "completed";

  async function start(cpu = false) {
    cpu = cpu || !setting(ctx.settings, "camera", "use_gpu", true);
    if (
      cpu &&
      !window.confirm(
        "GPU 가속 없이 CPU로 카메라 정합을 실행할까요? 사진이 많으면 매우 오래 걸릴 수 있습니다.",
      )
    )
      return;
    await ctx.action(() =>
      post(base + "/jobs/colmap", {
        gpu: ctx.gpu,
        matching,
        cpu_fallback: cpu,
        confirmed: cpu,
      }),
    );
  }

  const rows = report?.images || [];
  const okRows = rows.filter((r) => r.registered),
    failRows = rows.filter((r) => !r.registered);
  const list = tab === "ok" ? okRows : tab === "fail" ? failRows : rows;
  const engine = report?.engine;
  const steps = [
    "feature_extraction",
    "feature_matching",
    "mapper",
    "undistortion",
  ];
  const done = new Set(engine?.steps?.map((s) => s.step));
  const thumb = (name: string) =>
    project.images.find((p) => p.name === name)?.thumbnail ||
    (project.scene ? project.scene + "/images/" + name : "");

  return (
    <>
      {toolbar(
        <>
          {running && (
            <span className="badge acc">
              <span className="spinner" />
              {active?.message}
            </span>
          )}
          <span className="sp" />
          <span className="t3">
            {matching === "exhaustive" ? "전체 비교" : "인접 비교"}
          </span>
          {gpuEngine === false && (
            <button
              className="btn"
              disabled={!canRun}
              onClick={() => void start(true)}
              title="GPU 가속 엔진이 없을 때만 사용"
            >
              <Cpu size={15} />
              CPU로 실행
            </button>
          )}
          <button className="btn" disabled={!canRun || gpuEngine === false} onClick={() => void start(false)}>
            {report ? <RotateCcw size={15} /> : <Play size={14} />}
            {report ? "다시 실행" : "카메라 정합 실행"}
          </button>
          <button
            className="btn primary"
            disabled={blocked || project.stages.colmap !== "completed"}
            onClick={() => ctx.setStage("sam")}
          >
            다음: 마스크 생성
            <ArrowRight size={15} />
          </button>
        </>,
      )}
      {gpuEngine === false && (
        <div className="callout warn" style={{ margin: "10px 12px 0" }}>
          <Gauge size={15} />
          <span>
            GPU 가속 카메라 정합 엔진을 찾지 못했습니다. 설치 폴더에서{" "}
            <code>./scripts/build_colmap.sh</code>로 엔진을 설치하거나, 시간이
            오래 걸리는 CPU 실행을 직접 선택하세요.
          </span>
        </div>
      )}
      {!report && !running ? (
        <div className="empty">
          <Gauge size={44} className="ill" />
          <h2>카메라 위치를 추정할 준비가 되었습니다</h2>
          <p>
            사진의 특징점을 찾아 서로 연결하고, 각 사진을 찍은 카메라의 위치와
            자세를 계산합니다. 등록에 성공한 사진만 다음 단계로 넘어갑니다.
          </p>
          <div className="row">
            <button
              className="btn primary l"
              disabled={!canRun || gpuEngine === false}
              onClick={() => void start(false)}
            >
              <Play size={15} />
              카메라 정합 실행
            </button>
          </div>
          {project.stages.import !== "completed" && (
            <p className="hint">먼저 이미지 단계에서 불러오기를 완료하세요.</p>
          )}
        </div>
      ) : (
        <div className="workspace">
          <aside className="panel left" style={{ width: 320, flex: "none" }}>
            <div className="sec">
              <div className="sec-h">
                <b>카메라 등록</b>
                {report && <span>재구성 그룹 {report.selected_component}</span>}
              </div>
              <div className="row" style={{ alignItems: "baseline" }}>
                <span className="big-n">{fmt(report?.registered)}</span>
                <span className="t3" style={{ fontSize: 15 }}>
                  / {fmt(report?.total)}장
                </span>
                <span className="sp" />
                {report && (
                  <span className="badge ok">
                    {(
                      (report.registered / Math.max(report.total, 1)) *
                      100
                    ).toFixed(1)}
                    %
                  </span>
                )}
              </div>
              {report && (
                <>
                  <div className="bar" style={{ marginTop: 10, height: 8 }}>
                    <i
                      style={{
                        width: `${(report.registered / report.total) * 100}%`,
                        background: "var(--ok)",
                      }}
                    />
                    <i
                      style={{
                        width: `${(1 - report.registered / report.total) * 100}%`,
                        background: "var(--err)",
                      }}
                    />
                  </div>
                  <div className="funnel">
                    <div className="fn">
                      <span className="t2">특징점 추출</span>
                      <span className="num">
                        {rows.filter((r) => r.features_extracted).length}
                      </span>
                      <div className="bar thin">
                        <i
                          style={{
                            width: `${(rows.filter((r) => r.features_extracted).length / report.total) * 100}%`,
                            background: "var(--tx-3)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="fn">
                      <span className="t2">특징점 매칭 성공</span>
                      <span className="num">{report.matched ?? "—"}</span>
                      <div className="bar thin">
                        <i
                          style={{
                            width: `${((report.matched ?? 0) / report.total) * 100}%`,
                            background: "var(--tx-3)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="fn">
                      <b>최종 카메라 등록</b>
                      <b className="num">{report.registered}</b>
                      <div className="bar thin">
                        <i
                          style={{
                            width: `${(report.registered / report.total) * 100}%`,
                            background: "var(--ok)",
                          }}
                        />
                      </div>
                    </div>
                  </div>
                  <div
                    className="callout"
                    style={{ marginTop: 12, fontSize: 11.5 }}
                  >
                    <Info size={14} />
                    <span>
                      매칭에 성공해도 카메라 자세가 등록되지 않을 수 있습니다.
                      이후 단계에는 <b>등록된 {report.registered}장</b>만
                      사용됩니다.
                    </span>
                  </div>
                </>
              )}
            </div>
            <div className="tabs" role="tablist">
              <button
                role="tab"
                aria-selected={tab === "ok"}
                onClick={() => setTab("ok")}
              >
                등록 성공 <span className="count">{okRows.length}</span>
              </button>
              <button
                role="tab"
                aria-selected={tab === "fail"}
                onClick={() => setTab("fail")}
              >
                등록 실패{" "}
                <span
                  className="count"
                  style={
                    failRows.length
                      ? { background: "var(--err-soft)", color: "var(--err)" }
                      : undefined
                  }
                >
                  {failRows.length}
                </span>
              </button>
              <button
                role="tab"
                aria-selected={tab === "all"}
                onClick={() => setTab("all")}
              >
                전체 <span className="count">{rows.length}</span>
              </button>
            </div>
            <div className="scroll" style={{ flex: 1 }}>
              <table>
                <thead>
                  <tr>
                    <th>사진</th>
                    <th>특징점</th>
                    <th>상태</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((r) => (
                    <tr
                      key={r.name}
                      aria-selected={picked === r.name}
                      onClick={() =>
                        ctx.select({ kind: "camera", name: r.name })
                      }
                    >
                      <td
                        className="name ellip"
                        style={{ maxWidth: 120 }}
                        title={r.name}
                      >
                        {r.name}
                      </td>
                      <td className="num">{fmt(r.feature_count)}</td>
                      <td>
                        <span className="row" style={{ gap: 5 }}>
                          {r.registered ? (
                            <CircleCheck size={13} className="ok" />
                          ) : (
                            <CircleX size={13} className="err" />
                          )}
                          {r.reason}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {tab === "fail" && failRows.length > 0 && (
                <p className="hint" style={{ padding: 12 }}>
                  흐리거나 다른 사진과 겹치는 부분이 적은 사진은 등록되지
                  않습니다. 같은 위치를 다시 촬영해 추가하면 가장 효과적입니다.
                  제외해도 다음 단계는 진행할 수 있습니다.
                </p>
              )}
            </div>
          </aside>
          <div className="col grow" style={{ gap: 0, minWidth: 0 }}>
            <div className="pipe">
              {steps.map((s) => {
                const rec = engine?.steps?.find((x) => x.step === s);
                const isRunning =
                  running &&
                  !done.has(s) &&
                  steps.filter((x) => !done.has(x))[0] === s;
                return (
                  <div key={s} className={isRunning ? "run" : ""}>
                    {rec || (report && !engine && !running) ? (
                      <CircleCheck size={16} className="ok" />
                    ) : isRunning ? (
                      <span className="spinner" />
                    ) : (
                      <span className="t4">○</span>
                    )}
                    <b>{STEP_LABEL[s]}</b>
                    <span className="d">
                      {rec
                        ? rec.gpu_requested
                          ? rec.gpu_observed
                            ? `GPU 가속 확인 · 최대 ${fmt(rec.gpu_peak_mb)} MB`
                            : "GPU 요청 · 사용 기록 없음"
                          : "CPU 처리"
                        : isRunning
                          ? active?.message
                          : report && !engine
                            ? project.stage_provenance?.colmap?.stage_source ===
                              "imported"
                              ? "가져온 결과"
                              : "완료 · 처리 장치 기록 없음"
                            : "대기"}
                    </span>
                  </div>
                );
              })}
            </div>
            {report && project.scene && (
              <div className="subbar">
                <div
                  className="seg"
                  style={{ height: 26 }}
                  role="group"
                  aria-label="결과 보기 방식"
                >
                  <button
                    aria-pressed={view === "photos"}
                    onClick={() => setView("photos")}
                  >
                    등록된 사진
                  </button>
                  <button
                    aria-pressed={view === "points"}
                    onClick={() => setView("points")}
                  >
                    3D 포인트 · 카메라
                  </button>
                </div>
              </div>
            )}
            {report && project.scene && view === "points" ? (
              <Suspense
                fallback={
                  <div className="mesh-frame">
                    <p className="viewer-message">
                      3D 뷰어를 준비하고 있습니다…
                    </p>
                  </div>
                }
              >
                <SparseViewer projectId={project.id} selected={picked} onPick={(name) => ctx.select({ kind: "camera", name })} />
              </Suspense>
            ) : (
              <div className="scroll grow">
                {report && project.scene ? (
                  <div className="reg-grid">
                    {okRows.map((r, i) => (
                      <button
                        className="cell"
                        key={r.name}
                        aria-pressed={picked === r.name}
                        onClick={() =>
                          ctx.select({ kind: "camera", name: r.name })
                        }
                      >
                        <div className="thumb">
                          <img src={asset(project.id, thumb(r.name))} alt={r.name} loading="lazy" />
                          <span className="idx">{i + 1}</span>
                        </div>
                        <div className="cap">
                          <span className="ellip">{r.name}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="empty">
                    <span className="spinner" style={{ width: 28, height: 28 }} />
                    <p>
                      {active?.message || "카메라 정합을 실행하고 있습니다."}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
          {report && (
            <InspectorPortal>
              <div className="sec">
                <div className="sec-h">
                  <b>재구성 정보</b>
                </div>
                <div className="kv">
                  <span>재구성 그룹</span>
                  <span>{Object.keys(report.components).length}개</span>
                  <span>사용 그룹</span>
                  <span>
                    {report.selected_component} · {report.registered}장
                  </span>
                  <span>검증된 사진 쌍</span>
                  <span className="num">{fmt(report.verified_pairs)}</span>
                  <span>처리 장치</span>
                  <span>
                    {engine?.gpu_requested
                      ? "GPU 가속"
                      : engine
                        ? "CPU"
                        : project.stage_provenance?.colmap?.stage_source ===
                            "imported"
                          ? "가져온 결과"
                          : "기록 없음 (이전 버전)"}
                  </span>
                </div>
              </div>
              {Object.keys(report.components).length > 1 && (
                <div className="sec">
                  <div className="sec-h">
                    <b>재구성 그룹 선택</b>
                  </div>
                  <p className="hint" style={{ marginBottom: 8 }}>
                    사진이 서로 연결되지 않아 여러 그룹으로 나뉘었습니다.
                    좌표계가 다른 그룹은 합치지 않습니다.
                  </p>
                  <select
                    style={{ width: "100%" }}
                    disabled={blocked}
                    value={report.selected_component}
                    onChange={(e) =>
                      void ctx.action(() =>
                        post(base + "/jobs/colmap", {
                          component: e.target.value,
                          gpu: ctx.gpu,
                        }),
                      )
                    }
                  >
                    {Object.entries(report.components).map(([key, names]) => (
                      <option key={key} value={key}>
                        그룹 {key} · 등록 사진 {names.length}장
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div className="sec">
                <div className="sec-h">
                  <b>다음 단계</b>
                </div>
                <p className="hint">
                  등록된 {report.registered}장으로 객체 마스크를 만듭니다.
                  마스크와 클릭 좌표는 왜곡 보정된 사진 기준으로 관리됩니다.
                </p>
              </div>
            </InspectorPortal>
          )}
        </div>
      )}
    </>
  );
}
