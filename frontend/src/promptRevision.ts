export interface PromptIdentity {
  project_id: string;
  frame_id: string;
  session_id: string;
  revision: number;
}
export function isLatestPrompt(
  current: PromptIdentity,
  result: PromptIdentity,
): boolean {
  return (
    current.project_id === result.project_id &&
    current.frame_id === result.frame_id &&
    current.session_id === result.session_id &&
    current.revision === result.revision
  );
}

interface StoredPrompt {
  reference?: string;
  points?: number[][];
  labels?: number[];
}
export function restorePromptPoints(
  frame: string,
  live?: StoredPrompt,
  confirmed?: StoredPrompt,
) {
  const valid = (p?: StoredPrompt) =>
    p?.reference === frame &&
    Array.isArray(p.points) &&
    Array.isArray(p.labels) &&
    p.points.length === p.labels.length &&
    p.points.every(
      (xy, i) =>
        Array.isArray(xy) &&
        xy.length === 2 &&
        xy.every(Number.isFinite) &&
        [0, 1].includes(p.labels![i]),
    );
  const p = valid(live) ? live : valid(confirmed) ? confirmed : undefined;
  return (
    p?.points?.map((xy, i) => ({ x: xy[0], y: xy[1], label: p.labels![i] })) ||
    []
  );
}
