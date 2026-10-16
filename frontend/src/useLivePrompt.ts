import { useCallback, useEffect, useRef, useState } from "react";
import { post } from "./api";
import { isLatestPrompt, restorePromptPoints } from "./promptRevision";
import type { Point, Project } from "./api";
export function useLivePrompt(
  project: Project | null,
  frame: string,
  gpu: number,
  enabled: boolean,
) {
  const [points, setPoints] = useState<Point[]>([]),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const [previewPath, setPreviewPath] = useState<string | undefined>(undefined);
  const context = useRef<{
      id: string;
      frame: string;
      session: string;
      revision: number;
      ready: Promise<unknown>;
    } | null>(null),
    timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const past = useRef<Point[][]>([]),
    future = useRef<Point[][]>([]),
    pointsRef = useRef<Point[]>([]);
  const [historyTick, setHistoryTick] = useState(0);
  useEffect(() => {
    clearTimeout(timer.current);
    setError("");
    setPending(false);
    past.current = [];
    future.current = [];
    if (!project || !frame || !enabled) {
      context.current = null;
      return;
    }
    const initial = restorePromptPoints(
      frame,
      project.live_prompt,
      project.prompt,
    );
    setPreviewPath(
      project.preview?.reference === frame ? project.preview.path : undefined,
    );
    pointsRef.current = initial;
    setPoints(initial);
    const session = crypto.randomUUID();
    const ready = post(`/projects/${project.id}/prompt-session`, {
      reference: frame,
      session_id: session,
    });
    context.current = { id: project.id, frame, session, revision: 0, ready };
    ready.catch((e) => setError(e.message));
    return () => {
      clearTimeout(timer.current);
      context.current = null;
    };
  }, [project?.id, frame, enabled]);
  const submit = useCallback(
    (next: Point[]) => {
      const c = context.current;
      if (!c) return;
      c.revision++;
      const revision = c.revision;
      clearTimeout(timer.current);
      setError("");
      setPending(next.some((p) => p.label === 1));
      if (!next.some((p) => p.label === 1)) setPreviewPath(undefined);
      timer.current = setTimeout(() => {
        void c.ready
          .then(() =>
            post(`/projects/${c.id}/prompt`, {
              gpu,
              reference: c.frame,
              session_id: c.session,
              prompt_revision: revision,
              points: next.map((p) => [p.x, p.y]),
              labels: next.map((p) => p.label),
            }),
          )
          .catch((e) => {
            if (context.current === c && c.revision === revision) {
              setError(e.message);
              setPending(false);
            }
          });
      }, 180);
    },
    [gpu],
  );
  const change = useCallback(
    (next: Point[]) => {
      past.current.push(pointsRef.current);
      future.current = [];
      pointsRef.current = next;
      setPoints(next);
      setHistoryTick((v) => v + 1);
      submit(next);
    },
    [submit],
  );
  const undo = () => {
    const prev = past.current.pop();
    if (prev) {
      future.current.push(pointsRef.current);
      pointsRef.current = prev;
      setPoints(prev);
      setHistoryTick((v) => v + 1);
      submit(prev);
    }
  };
  const redo = () => {
    const next = future.current.pop();
    if (next) {
      past.current.push(pointsRef.current);
      pointsRef.current = next;
      setPoints(next);
      setHistoryTick((v) => v + 1);
      submit(next);
    }
  };
  const c = context.current,
    live = project?.live_prompt;
  const isCurrent =
    !!c &&
    live?.session_id === c.session &&
    live.prompt_revision === c.revision;
  const display = project?.preview;
  const displayMatches =
    !!c &&
    !!display &&
    isLatestPrompt(
      {
        project_id: c.id,
        frame_id: frame,
        session_id: c.session,
        revision: c.revision,
      },
      {
        project_id: display.project_id || project!.id,
        frame_id: display.frame_id || display.reference,
        session_id: display.session_id || "",
        revision: display.prompt_revision ?? -1,
      },
    );
  useEffect(() => {
    if (displayMatches) setPreviewPath(display!.path);
  }, [displayMatches, display?.path]);
  useEffect(() => {
    if (
      isCurrent &&
      ["ready", "failed", "empty", "cancelled"].includes(live!.status)
    ) {
      setPending(false);
      if (live!.status === "failed")
        setError(live!.error || "추론에 실패했습니다.");
    }
  }, [isCurrent, live?.status]);
  void historyTick;
  return {
    points,
    change,
    undo,
    redo,
    canUndo: past.current.length > 0,
    canRedo: future.current.length > 0,
    pending,
    error,
    retry: () => submit(pointsRef.current),
    displayMatches,
    previewPath,
  };
}
