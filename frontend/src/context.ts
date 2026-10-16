import type { Health, Job, Project, Stage } from "./api";

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
}

export const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("ko-KR"));
export const gb = (bytes: number) => (bytes / 1024 ** 3).toFixed(1) + " GB";
export const reviewed = (status: string) => ["approved", "manual", "skipped"].includes(status);
