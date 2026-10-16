export interface TrainingSample {
  it: number;
  total: number;
  loss: number;
  distort?: number;
  normal?: number;
  points?: number;
}
export interface TrainingStatus {
  samples: TrainingSample[];
  last?: TrainingSample;
  rate?: number;
  elapsed?: string;
  remaining?: string;
}

/** Parse the real tqdm progress lines written by the reconstruction trainer. */
export function parseTraining(log: string): TrainingStatus {
  const byIt = new Map<number, TrainingSample>();
  let rate: number | undefined, elapsed: string | undefined, remaining: string | undefined;
  for (const m of log.matchAll(
    /(\d+)\/(\d+)\s*\[([\d:]+)<([\d:?]+),\s*([\d.]+)it\/s,\s*Loss=([\d.eE+-]+)(?:,\s*distort=([\d.eE+-]+))?(?:,\s*normal=([\d.eE+-]+))?(?:,\s*Points=(\d+))?/g,
  )) {
    const s: TrainingSample = {
      it: +m[1],
      total: +m[2],
      loss: +m[6],
      distort: m[7] ? +m[7] : undefined,
      normal: m[8] ? +m[8] : undefined,
      points: m[9] ? +m[9] : undefined,
    };
    if (Number.isFinite(s.loss)) byIt.set(s.it, s);
    elapsed = m[3];
    remaining = m[4];
    rate = +m[5];
  }
  // Fallback for logs without the tqdm timing block.
  if (!byIt.size)
    for (const m of log.matchAll(/(\d+)\/(\d+).*?Loss=([\d.eE+-]+)/g))
      byIt.set(+m[1], { it: +m[1], total: +m[2], loss: +m[3] });
  const samples = [...byIt.values()].sort((a, b) => a.it - b.it);
  return { samples, last: samples[samples.length - 1], rate, elapsed, remaining };
}

const SERIES: [keyof TrainingSample, string, string][] = [
  ["loss", "전체 손실", "var(--tx-1)"],
  ["distort", "깊이 왜곡", "var(--info)"],
  ["normal", "법선 일관성", "var(--ok)"],
];

export function LossPlot({ status }: { status: TrainingStatus }) {
  const data = status.samples.length > 600
    ? status.samples.filter((_, i) => i % Math.ceil(status.samples.length / 600) === 0 || i === status.samples.length - 1)
    : status.samples;
  if (!data.length)
    return <p className="muted" style={{ padding: 16 }}>학습이 시작되면 실제 로그의 손실 값을 그립니다.</p>;
  const W = 900, H = 260, L = 58, R = 16, T = 14, B = 28;
  const total = data[data.length - 1].total;
  const values = data.flatMap((d) => SERIES.map(([k]) => d[k] as number | undefined)).filter((v): v is number => !!v && v > 0);
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...values)))),
    hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...values))));
  const x = (it: number) => L + ((W - L - R) * it) / Math.max(total, 1);
  const y = (v: number) => T + (H - T - B) * (1 - (Math.log10(v) - Math.log10(lo)) / Math.max(Math.log10(hi) - Math.log10(lo), 1e-6));
  const ticks: number[] = [];
  for (let v = lo; v <= hi * 1.0001; v *= 10) ticks.push(v);
  const last = data[data.length - 1];
  return (
    <div className="loss-plot">
      <div className="row" style={{ gap: 14, fontSize: 11.5, color: "var(--tx-2)", marginBottom: 6 }}>
        {SERIES.filter(([k]) => last[k] != null).map(([k, name, colour]) => (
          <span key={k} className="row" style={{ gap: 6 }}>
            <i style={{ width: 14, height: 3, borderRadius: 2, background: colour, display: "inline-block" }} />
            {name} <b className="num" style={{ color: "var(--tx-1)" }}>{(last[k] as number).toFixed(5)}</b>
          </span>
        ))}
        <span className="sp" />
        <span className="t3">로그 스케일 · 지수 이동 평균(원본 학습 로그)</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`반복 ${last.it}회, 전체 손실 ${last.loss}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={L - 8} y={y(v) + 4} textAnchor="end">{v >= 1 ? v.toFixed(0) : v.toExponential(0)}</text>
          </g>
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={x(total * f)} x2={x(total * f)} y1={T} y2={H - B} stroke="var(--line)" strokeDasharray={f ? "2 4" : undefined} />
            <text x={x(total * f)} y={H - 8} textAnchor="middle">{Math.round((total * f) / 1000)}k</text>
          </g>
        ))}
        {SERIES.map(([k, , colour]) => {
          const pts = data.filter((d) => (d[k] as number) > 0);
          if (!pts.length) return null;
          return <polyline key={k} points={pts.map((d) => `${x(d.it).toFixed(1)},${y(d[k] as number).toFixed(1)}`).join(" ")} fill="none" stroke={colour} strokeWidth={k === "loss" ? 2 : 1.4} vectorEffect="non-scaling-stroke" />;
        })}
        <line x1={x(last.it)} x2={x(last.it)} y1={T} y2={H - B} stroke="var(--accent)" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}
