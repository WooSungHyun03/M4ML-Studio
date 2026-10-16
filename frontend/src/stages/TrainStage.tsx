import { useEffect, useState } from "react";
import { Check, Cpu, Info, Pause, Play, RotateCcw, Settings2, TriangleAlert } from "lucide-react";
import { api, post } from "../api";
import type { StageCtx } from "../context";
import { InspectorPortal } from "../dock";
import { fmt } from "../context";
import { LossPlot, parseTraining } from "../LossPlot";
import type { TrainingStatus } from "../LossPlot";

export function TrainStage({ ctx, toolbar }: { ctx: StageCtx; toolbar: (n: React.ReactNode) => React.ReactNode }) {
  const { project, base, blocked, active, health } = ctx;
  const [iterations, setIterations] = useState(30000),
    [resolution, setResolution] = useState(-1),
    [meshRes, setMeshRes] = useState(1024),
    [log, setLog] = useState(""),
    [metrics, setMetrics] = useState<TrainingStatus | null>(null),
    [preflight, setPreflight] = useState<{ valid: boolean; images: number; failures: { name: string; reason: string }[] } | null>(null);
  const trainingJob = project.jobs?.find((j) => j.stage === "train");
  const running = active?.stage === "train";
  const meshRunning = active?.stage === "mesh";
  useEffect(() => {
    api<typeof preflight>(`${base}/preflight`).then(setPreflight).catch(() => setPreflight(null));
  }, [base, project.revision]);
  useEffect(() => {
    if (!trainingJob) return setLog("");
    let live = true;
    const load = () => {
      void api<{ text: string }>(`${base}/logs/${trainingJob.id}`).then((r) => live && setLog(r.text)).catch(() => {});
      void api<{ samples: (number | null)[][]; status: { elapsed?: string; remaining?: string; rate?: number } }>(`${base}/training-metrics/${trainingJob.id}`)
        .then((r) => {
          if (!live) return;
          const samples = r.samples.map(([it, total, loss, distort, normal, points]) => ({
            it: it!, total: total!, loss: loss!, distort: distort ?? undefined, normal: normal ?? undefined, points: points ?? undefined,
          }));
          setMetrics({ samples, last: samples[samples.length - 1], ...r.status });
        })
        .catch(() => {});
    };
    load();
    const timer = setInterval(load, running ? 2000 : 15000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [base, trainingJob?.id, running]);
  const tail = parseTraining(log);
  const status: TrainingStatus = metrics && metrics.samples.length ? { ...metrics, rate: tail.rate ?? metrics.rate, elapsed: tail.elapsed ?? metrics.elapsed, remaining: tail.remaining ?? metrics.remaining } : tail;
  const current = running ? active?.current ?? status.last?.it ?? 0 : project.training?.iterations ?? status.last?.it ?? 0;
  const target = running ? active?.total ?? status.last?.total ?? iterations : project.training?.iterations ?? status.last?.total ?? iterations;
  const pct = target ? Math.min(100, (current / target) * 100) : 0;
  const partial = project.training_partial;
  const gpu = health?.gpus.find((g) => g.index === ctx.gpu) || health?.gpus[0];
  const usedGb = gpu ? (gpu.total_mb - gpu.free_mb) / 1024 : 0;
  const densifyEnd = Math.min(15000, target);
  const phase = (from: number, to: number) => (current >= to ? 100 : current <= from ? 0 : ((current - from) / Math.max(to - from, 1)) * 100);
  const reviewDone = project.stages.review === "completed";

  async function start(resume = false) {
    const msg = resume
      ? `저장된 지점(${fmt(partial?.checkpoint)}회)부터 ${fmt(partial?.iterations)}회까지 이어서 학습할까요?`
      : `${fmt(iterations)}회 3D 재구성을 ${gpu?.name || "GPU"}에서 시작할까요? 학습이 끝나면 3D 모델을 자동으로 만듭니다.`;
    if (!window.confirm(msg)) return;
    await ctx.action(() =>
      post(base + "/jobs/train", { gpu: ctx.gpu, confirmed: true, iterations, resolution, mesh_res: meshRes, resume }),
    );
  }

  return (
    <>
      {toolbar(
        <>
          {running && <span className="badge acc"><span className="spinner" />학습 중</span>}
          {meshRunning && <span className="badge acc"><span className="spinner" />3D 모델 생성 중</span>}
          {project.stages.train === "completed" && !running && <span className="badge ok"><Check size={12} />학습 완료</span>}
          <span className="sp" />
          {running ? (
            <button className="btn" onClick={() => { if (window.confirm("학습을 일시정지할까요? 마지막 저장 지점까지의 결과를 보존하며, 나중에 이어서 학습할 수 있습니다.")) void ctx.action(() => post(base + "/cancel")); }}>
              <Pause size={15} />일시정지
            </button>
          ) : partial && !blocked ? (
            <button className="btn primary" disabled={!reviewDone || !preflight?.valid} onClick={() => void start(true)}>
              <RotateCcw size={15} />{fmt(partial.checkpoint)}회부터 이어서 학습
            </button>
          ) : null}
          {!running && (
            <button className={"btn" + (partial ? "" : " primary")} disabled={blocked || !preflight?.valid || !reviewDone || !health?.gpus.length} onClick={() => void start(false)}>
              <Play size={14} />{project.training ? "새로 학습" : "학습 시작"}
            </button>
          )}
        </>,
      )}
      <div className="workspace">
        <div className="train-body">
          {!reviewDone && (
            <div className="callout warn"><TriangleAlert size={15} /><span>마스크 검토를 마치거나 남은 검토를 건너뛰어야 학습을 시작할 수 있습니다.</span></div>
          )}
          {preflight && !preflight.valid && preflight.failures.length > 0 && (
            <div className="callout err"><TriangleAlert size={15} /><span>{preflight.failures.slice(0, 4).map((f) => `${f.name}: ${f.reason}`).join(" · ")}</span></div>
          )}
          <div className="blk prog">
            <div>
              <div className="t3" style={{ fontSize: 11 }}>반복 횟수</div>
              <div className="iter">{fmt(current)} <span>/ {fmt(target)}</span></div>
              <div className="bar" style={{ marginTop: 10 }}><i style={{ width: pct + "%", background: project.stages.train === "completed" && !running ? "var(--ok)" : undefined }} /></div>
              <div className="metrics">
                <div><span>진행률</span><b>{pct.toFixed(1)}%</b></div>
                <div><span>경과</span><b>{running ? status.elapsed || "—" : "—"}</b></div>
                <div><span>남은 시간</span><b>{running ? status.remaining || "계산 중" : "—"}</b></div>
                <div><span>속도</span><b>{running && status.rate ? status.rate.toFixed(1) + " it/s" : "—"}</b></div>
              </div>
            </div>
            <div>
              <div className="t3" style={{ fontSize: 11, marginBottom: 10 }}>현재 학습 단계</div>
              <div className="phases">
                <div className={"ph" + (running && current < 1 ? " run" : "")}><div className="pb"><i style={{ width: (current > 0 ? 100 : 0) + "%" }} /></div><b>{current > 0 && <Check size={12} className="ok" />}준비</b>사진·마스크 검사</div>
                <div className={"ph" + (running && current < densifyEnd ? " run" : "")}><div className="pb"><i style={{ width: phase(0, densifyEnd) + "%" }} /></div><b>{phase(0, densifyEnd) >= 100 && <Check size={12} className="ok" />}형상 확장</b>0 – {fmt(densifyEnd)}회</div>
                <div className={"ph" + (running && current >= densifyEnd ? " run" : "")}><div className="pb"><i style={{ width: phase(densifyEnd, target) + "%" }} /></div><b>{phase(densifyEnd, target) >= 100 && <Check size={12} className="ok" />}정제</b>{fmt(densifyEnd)} – {fmt(target)}회 · 객체 외부 정리</div>
                <div className={"ph" + (meshRunning ? " run" : "")}><div className="pb"><i style={{ width: project.stages.mesh === "completed" ? "100%" : "0%" }} /></div><b>{project.stages.mesh === "completed" && <Check size={12} className="ok" />}3D 모델 생성</b>학습 후 자동</div>
              </div>
            </div>
          </div>
          <div className="blk">
            <div className="blk-h"><b>손실</b><span className="t3">학습 로그에서 실제로 기록된 값</span><span className="sp" />{status.last?.points != null && <span className="t3">현재 가우시안 <b className="num" style={{ color: "var(--tx-1)" }}>{fmt(status.last.points)}</b>개</span>}</div>
            <LossPlot status={status} />
          </div>
          <div className="blk" style={{ minHeight: 180 }}>
            <div className="blk-h"><b>학습 로그</b><span className="t3">최근 기록</span></div>
            <pre className="log-text" style={{ maxHeight: 220 }}>{log.replace(/\x1b\[[0-9;]*m/g, "").split(/\r|\n/).filter((l) => l.trim()).slice(-18).join("\n") || "학습을 시작하면 실제 실행 기록이 표시됩니다."}</pre>
          </div>
        </div>
        <InspectorPortal>
          <div className="sec">
            <div className="sec-h"><b>처리 장치</b>{gpu ? <span className="badge ok">사용 가능</span> : <span className="badge err">없음</span>}</div>
            {gpu ? (
              <>
                <div style={{ fontWeight: 600 }}>{gpu.name}</div>
                <div className="row" style={{ marginTop: 12, fontSize: 12.5 }}><span className="t3 grow">GPU 메모리</span><b className="num">{usedGb.toFixed(1)}</b><span className="t3">/ {(gpu.total_mb / 1024).toFixed(1)} GB</span></div>
                <div className="bar" style={{ marginTop: 6, height: 8 }}><i style={{ width: `${(usedGb / (gpu.total_mb / 1024)) * 100}%` }} /></div>
                {(health?.gpus.length || 0) > 1 && (
                  <label className="field" style={{ marginTop: 12 }}>
                    사용할 GPU
                    <select value={ctx.gpu} disabled={blocked} onChange={(e) => ctx.setGpu(+e.target.value)}>
                      {health!.gpus.map((g) => <option key={g.index} value={g.index}>{g.index}: {g.name}</option>)}
                    </select>
                  </label>
                )}
              </>
            ) : (
              <p className="hint">NVIDIA GPU를 찾을 수 없습니다. 3D 재구성에는 CUDA를 지원하는 GPU가 필요합니다.</p>
            )}
          </div>
          <div className="sec">
            <div className="sec-h"><b>학습 데이터</b></div>
            <div className="kv">
              <span>등록 사진</span><span>{fmt(preflight?.images)}장</span>
              <span>마스크 검증</span><span className={preflight?.valid ? "ok" : "warn"}>{preflight?.valid ? "통과" : "확인 필요"}</span>
              {project.training && <><span>저장된 결과</span><span>{fmt(project.training.iterations)}회 · 가우시안 {fmt(project.training.gaussians)}</span></>}
              {partial && <><span>이어서 학습</span><span>{fmt(partial.checkpoint)}회 저장됨</span></>}
            </div>
          </div>
          <div className="sec">
            <details>
              <summary className="row" style={{ cursor: "pointer" }}><Settings2 size={14} />고급 설정 <span className="badge neu" style={{ marginLeft: "auto" }}>기본값</span></summary>
              <div className="col" style={{ marginTop: 12 }}>
                <label className="field">
                  학습 반복 횟수
                  <input type="number" min={100} max={100000} step={100} value={iterations} disabled={blocked} onChange={(e) => setIterations(+e.target.value)} />
                  <small>기본 30,000회. 짧은 실행은 동작 확인용이며 최종 품질을 보장하지 않습니다.</small>
                </label>
                <label className="field">
                  학습 사진 해상도
                  <select value={resolution} disabled={blocked} onChange={(e) => setResolution(+e.target.value)}>
                    <option value={-1}>자동 (가로 최대 1600px)</option>
                    <option value={1}>원본 크기</option>
                    <option value={800}>가로 800px (메모리 절약)</option>
                  </select>
                </label>
                <label className="field">
                  3D 모델 해상도
                  <select value={meshRes} disabled={blocked} onChange={(e) => setMeshRes(+e.target.value)}>
                    <option value={1024}>1024 (기본)</option>
                    <option value={512}>512</option>
                    <option value={256}>256 (빠른 확인)</option>
                  </select>
                </label>
              </div>
            </details>
          </div>
          <div className="sec">
            <div className="callout"><Info size={15} /><span>일시정지하면 마지막 저장 지점(2,500회마다)까지 보존합니다. 앱을 다시 시작해도 이어서 학습할 수 있습니다.</span></div>
          </div>
          <div className="sec">
            <div className="row hint"><Cpu size={13} />처리 엔진과 라이선스는 설정 › 고급 정보에서 확인할 수 있습니다.</div>
          </div>
        </InspectorPortal>
      </div>
    </>
  );
}
