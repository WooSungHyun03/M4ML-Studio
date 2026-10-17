// Curated display contract; raw engine diagnostics must not become UI fields.
const LABELS: Record<string, string> = {
  key: "엔진 ID",
  version: "버전",
  commit: "소스 버전",
  path: "실행 파일",
  checkpoint: "모델 파일",
  checkpoint_present: "모델 파일 준비",
  checkpoint_bytes: "모델 파일 크기 (byte)",
  runtime: "처리 환경",
  license: "이용 조건",
  renderer: "렌더러",
  protocol: "연결 방식",
  cuda: "CUDA 지원",
  cuda_toolkit: "빌드 CUDA",
  origin: "설치 방식",
  error: "문제 원인",
  external_viewer: "외부 뷰어",
  external_viewer_missing_libraries: "부족한 뷰어 라이브러리",
  gpu_steps: "GPU 처리",
  cpu_steps: "CPU 처리",
  upstream: "공식 소스",
};
export function engineRows(engine: Record<string, unknown>) {
  return Object.entries(engine)
    .filter(([key]) => Object.hasOwn(LABELS, key))
    .map(([key, value]) => ({ key, label: LABELS[key], value }));
}
export function diagnosticSummary(value: unknown): string {
  if (Array.isArray(value))
    return value
      .slice(0, 12)
      .map((v) =>
        typeof v === "object" ? "상세 항목" : String(v).slice(0, 200),
      )
      .join(", ");
  if (value && typeof value === "object")
    return `${Object.keys(value).length}개 항목`;
  return String(value ?? "—").slice(0, 1024);
}
