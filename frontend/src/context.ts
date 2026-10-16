import type { Health, Job, Project, Stage } from "./api";

/** What the user selected in the Project Explorer / viewport; drives the Inspector. */
export type Selection =
  | { kind: "image"; name: string }
  | { kind: "camera"; name: string }
  | { kind: "mask"; name: string }
  | { kind: "training" }
  | { kind: "checkpoint"; name: string; iteration: number; bytes: number; path: string; resumable: boolean }
  | { kind: "mesh"; name: string; bytes: number; path: string }
  | null;

/** Everything a stage screen needs from the application shell. */
export interface StageCtx {
  project: Project;
  health: Health | null;
  base: string;
  /** a request is in flight or a job is running */
  blocked: boolean;
  busy: boolean;
  active?: Job;
  gpu: number;
  setGpu: (g: number) => void;
  action: (fn: () => Promise<unknown>) => Promise<void>;
  refresh: () => Promise<void>;
  setStage: (s: Stage) => void;
  setError: (e: string) => void;
  setDirty: (d: boolean) => void;
  guard: () => boolean;
  selection: Selection;
  select: (s: Selection) => void;
}

export const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("ko-KR"));
export const gb = (bytes: number) => (bytes / 1024 ** 3).toFixed(1) + " GB";
export const mb = (bytes: number) => (bytes >= 1024 ** 3 ? gb(bytes) : (bytes / 1024 ** 2).toFixed(1) + " MB");
export const reviewed = (status: string) => ["approved", "manual", "skipped"].includes(status);
