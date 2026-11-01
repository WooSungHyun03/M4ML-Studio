import { csrfToken, platform } from "./platform";
export type Stage = "import" | "colmap" | "sam" | "review" | "train" | "mesh";
export const stages: Stage[] = [
  "import",
  "colmap",
  "sam",
  "review",
  "train",
  "mesh",
];
// User-facing capability names. Engine/model names (COLMAP, SAM, Object-Aware…)
// appear only in Settings › 고급 정보, so engines can be replaced without UI changes.
export const titles: Record<Stage, string> = {
  import: "사진",
  colmap: "카메라 정합",
  sam: "객체 선택",
  review: "마스크 검토",
  train: "3D 재구성",
  mesh: "3D 모델",
};
export const subtitles: Record<Stage, string> = {
  import: "여러 시점에서 촬영한 사진",
  colmap: "카메라 위치와 자세 추정",
  sam: "대표 사진에서 객체를 클릭하세요",
  review: "마스크를 확인하고 필요하면 클릭으로 수정",
  train: "객체 중심 3D 재구성 학습",
  mesh: "색상 메시와 학습 결과",
};
export const states: Record<string, string> = {
  pending: "대기",
  running: "실행 중",
  waiting_for_user: "사용자 작업 필요",
  review_required: "검토 필요",
  completed: "완료",
  failed: "실패",
  cancelled: "취소됨",
  blocked: "진행 불가",
};
export type Point = { x: number; y: number; label: number };
export interface MaskData {
  path: string;
  generated_path?: string;
  valid: boolean;
  status: string;
  source?: string;
  sha256: string;
  coverage?: number;
  warnings?: string[];
  error?: string;
}
export interface Job {
  created?: string;
  ended?: string | null;
  id: string;
  stage: string;
  state: string;
  message: string;
  current: number | null;
  total: number | null;
}
export interface Photo {
  advisories?: string[];
  name: string;
  source_name: string;
  size: number[];
  duplicate_of: string | null;
  thumbnail: string;
  path: string;
}
export interface Project {
  execution_device?: { index: number; uuid?: string };
  result_artifacts?: {
    id: string;
    kind: string;
    path: string;
    source_path: string;
    dataset_link: string;
  }[];
  active_gaussian_artifact?: string;
  task_settings?: {
    schema_version: number;
    values: Record<string, Record<string, string | number | boolean>>;
  };
  input_mode?: "images" | "colmap" | "colmap_masks" | "mesh";
  stage_provenance?: Partial<
    Record<
      Stage,
      { stage_source: string; stage_state: string; skip_reason: string }
    >
  >;
  updated?: string;
  project_path?: string;
  source_folder?: string;
  folder_import?: {
    reused: string[];
    skipped: string[];
    recommendation: { stage: string | null; label: string | null };
  };
  archived?: boolean;
  id: string;
  name: string;
  revision: number;
  created: string;
  stages: Record<Stage, string>;
  images: Photo[];
  masks: Record<string, MaskData>;
  jobs?: Job[];
  scene?: string;
  import_errors: { name: string; error: string }[];
  live_prompt?: {
    reference: string;
    session_id: string;
    prompt_revision: number;
    status: string;
    error?: string;
    seconds?: number;
    points: number[][];
    labels: number[];
  };
  preview?: {
    reference: string;
    path: string;
    session_id?: string;
    prompt_revision?: number;
    project_id?: string;
    frame_id?: string;
    coverage?: number;
    area?: number;
  };
  prompt?: { reference: string; points: number[][]; labels: number[] };
  colmap_report?: {
    registered: number;
    total: number;
    matched: number;
    verified_pairs: number;
    selected_component: string;
    components: Record<string, string[]>;
    engine?: {
      version?: string;
      cuda_build?: boolean;
      gpu_requested?: boolean;
      steps?: {
        step: string;
        gpu_requested: boolean;
        gpu_observed?: boolean;
        gpu_peak_mb?: number;
      }[];
    };
    images: {
      name: string;
      features_extracted: boolean;
      feature_count: number;
      has_verified_match: boolean;
      registered: boolean;
      reason: string;
    }[];
  };
  training?: {
    iterations: number;
    gaussians: number;
    path: string;
    resumed_from?: number | null;
  };
  training_partial?: {
    path: string;
    checkpoint: number;
    iterations: number;
    time: string;
  };
  mesh?: {
    path: string;
    vertices: number;
    triangles: number;
    iterations?: number;
    mesh_res?: number;
    source_name?: string;
    preview_name?: string;
    colors?: boolean;
    color?: { present: boolean };
    bytes?: number;
  };
}
export interface Health {
  gpus: {
    index: number;
    name: string;
    total_mb: number;
    free_mb: number;
    driver?: string;
    uuid?: string;
  }[];
  gpu_error: string | null;
  colmap: { available: boolean; gpu: boolean; origin?: string; error?: string };
  disk_free: number;
  version?: string;
  checkpoint_exists: boolean;
  runtime_status?: {
    torch?: string;
    cuda?: string;
    available?: boolean;
    error?: string;
    anchor_ok?: boolean;
  };
}
let token = "";
declare global {
  interface Window {
    __M4ML_TOKEN__?: string;
  }
}
async function auth() {
  // Desktop shell injects the token; the browser developer mode asks the local API.
  if (!token && window.__M4ML_TOKEN__) token = window.__M4ML_TOKEN__;
  if (!token) token = (await (await fetch("/api/session")).json()).token;
  return token;
}
/** Web service: reuse this browser's anonymous workspace or open a new one. The gateway
 *  sets the HttpOnly session cookie and the readable CSRF cookie. */
export class TurnstileRequired extends Error {}
export async function ensureWebSession(turnstile?: string): Promise<{ slot: "active" | "queued" | "full"; position?: number }> {
  return webSessionPost("/api/web/session", turnstile ? { turnstile } : undefined, "작업 공간을 열지 못했습니다. 잠시 뒤 다시 시도하세요.");
}
/** Use a one-time "continue in another browser" link (the gateway rotates the session). */
export async function redeemRecovery(token: string) {
  return webSessionPost("/api/web/session/recover", { token }, "이어하기 링크가 올바르지 않거나 이미 사용되었습니다.");
}
async function webSessionPost(url: string, body: unknown, fallback: string) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-csrf-token": csrfToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: { detail?: string; slot?: "active" | "queued" | "full"; position?: number } = {};
  try {
    data = await response.json();
  } catch {}
  if (response.status === 403 && response.headers.get("x-turnstile") === "required")
    throw new TurnstileRequired(typeof data.detail === "string" ? data.detail : fallback);
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : fallback);
  return { slot: data.slot || "active", position: data.position };
}
/** Headers that authorise a state-changing request. The web gateway authenticates the
 *  browser by its session cookie and adds the backend token itself; the browser never
 *  sees a backend token there, and /api/session is never called. */
export async function writeHeaders(): Promise<Record<string, string>> {
  if (platform() === "web") return { "x-csrf-token": csrfToken() };
  return { "x-studio-token": await auth() };
}
export async function api<T = Project>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (options.method && !["GET", "HEAD"].includes(options.method))
    for (const [name, value] of Object.entries(await writeHeaders())) headers.set(name, value);
  const response = await fetch("/api" + url, { ...options, headers });
  if (!response.ok) {
    let detail = "요청에 실패했습니다.";
    try {
      const error = await response.json();
      detail =
        typeof error.detail === "string"
          ? error.detail
          : "입력 내용을 확인하세요.";
    } catch {}
    throw new Error(detail);
  }
  const body = await response.json();
  // Web service: GPU work queued behind another workspace (202). Tell the user; the job
  // starts by itself when the GPU frees up and shows up in the normal progress display.
  if (response.status === 202 && body?.queued && typeof window !== "undefined")
    window.dispatchEvent(new CustomEvent("m4ml:notice", { detail: body.detail }));
  return body;
}
/** Binary POST (live render frames). Errors carry the server's live-render state. */
export class LiveError extends Error {
  constructor(message: string, public state: string) {
    super(message);
  }
}
export async function postBlob(
  url: string,
  body: unknown,
  signal?: AbortSignal,
) {
  const response = await fetch("/api" + url, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(await writeHeaders()),
    },
  });
  if (!response.ok) {
    let detail = "렌더링에 실패했습니다.";
    try {
      const error = await response.json();
      if (typeof error.detail === "string") detail = error.detail;
    } catch {}
    throw new LiveError(detail, response.headers.get("X-Live-State") || "failed");
  }
  return { blob: await response.blob(), headers: response.headers };
}
export function asset(id: string, path: string) {
  return (
    "/api/projects/" +
    id +
    "/files/" +
    path.split("/").map(encodeURIComponent).join("/")
  );
}
export function post<T = Project>(url: string, body: unknown = {}) {
  return api<T>(url, { method: "POST", body: JSON.stringify(body) });
}
