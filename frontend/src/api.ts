export type Stage = "import" | "colmap" | "sam" | "review" | "train" | "mesh";
export const stages: Stage[] = [
  "import",
  "colmap",
  "sam",
  "review",
  "train",
  "mesh",
];
export const titles: Record<Stage, string> = {
  import: "이미지 불러오기",
  colmap: "COLMAP 재구성",
  sam: "SAM 3.1 마스크 생성",
  review: "마스크 확인·수정",
  train: "Object-Aware 학습",
  mesh: "Object Mesh 확인",
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
  sha256: string;
  coverage?: number;
  warnings?: string[];
  error?: string;
}
export interface Job {
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
  project_path?: string;
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
  preview?: { reference: string; path: string };
  prompt?: { reference: string; points: number[][]; labels: number[] };
  colmap_report?: {
    registered: number;
    total: number;
    matched: number;
    verified_pairs: number;
    selected_component: string;
    components: Record<string, string[]>;
    images: {
      name: string;
      features_extracted: boolean;
      feature_count: number;
      has_verified_match: boolean;
      registered: boolean;
      reason: string;
    }[];
  };
  training?: { iterations: number; gaussians: number; path: string };
  mesh?: { path: string; vertices: number; triangles: number };
}
export interface Health {
  gpus: { index: number; name: string; total_mb: number; free_mb: number }[];
  gpu_error: string | null;
  colmap: boolean;
  disk_free: number;
  checkpoint_exists: boolean;
}
let token = "";
async function auth() {
  if (!token) token = (await (await fetch("/api/session")).json()).token;
  return token;
}
export async function api<T = Project>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (options.method && !["GET", "HEAD"].includes(options.method))
    headers.set("x-studio-token", await auth());
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
  return response.json();
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
