import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** Editor layout: panel sizes/visibility, persisted per user (localStorage in the app profile). */
export interface Layout {
  explorer: boolean;
  inspector: boolean;
  bottom: boolean;
  explorerW: number;
  inspectorW: number;
  bottomH: number;
  bottomTab: "content" | "tasks" | "console" | "gpu";
}
export const DEFAULT_LAYOUT: Layout = {
  explorer: true,
  inspector: true,
  bottom: true,
  explorerW: 248,
  inspectorW: 300,
  bottomH: 190,
  bottomTab: "tasks",
};
const KEY = "m4ml-layout-v1";
const SAVED = "m4ml-layout-saved-v1";

function read(key: string): Layout | null {
  try {
    const v = localStorage.getItem(key);
    return v ? { ...DEFAULT_LAYOUT, ...JSON.parse(v) } : null;
  } catch {
    return null;
  }
}

export function useLayout() {
  const [layout, setLayout] = useState<Layout>(() => read(KEY) || DEFAULT_LAYOUT);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(layout));
    } catch {
      /* storage unavailable: layout simply isn't remembered */
    }
  }, [layout]);
  const update = useCallback((patch: Partial<Layout>) => setLayout((l) => ({ ...l, ...patch })), []);
  return {
    layout,
    update,
    reset: () => setLayout(DEFAULT_LAYOUT),
    save: () => {
      try {
        localStorage.setItem(SAVED, JSON.stringify(layout));
        return true;
      } catch {
        return false;
      }
    },
    restoreSaved: () => {
      const saved = read(SAVED);
      if (saved) setLayout(saved);
      return !!saved;
    },
  };
}

/** Vertical/horizontal drag handle between panels. */
export function Splitter({ axis, onDrag, onDouble }: { axis: "x" | "y"; onDrag: (delta: number) => void; onDouble?: () => void }) {
  const last = useRef<number | null>(null);
  return (
    <div
      className={"splitter " + axis}
      role="separator"
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      onDoubleClick={onDouble}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        last.current = axis === "x" ? e.clientX : e.clientY;
      }}
      onPointerMove={(e) => {
        if (last.current == null) return;
        const now = axis === "x" ? e.clientX : e.clientY;
        onDrag(now - last.current);
        last.current = now;
      }}
      onPointerUp={() => (last.current = null)}
      onPointerCancel={() => (last.current = null)}
    />
  );
}

export const DockContext = createContext<{ inspector: HTMLElement | null }>({ inspector: null });

/** Stage screens render their properties into the global Inspector dock. */
export function InspectorPortal({ children }: { children: React.ReactNode }) {
  const { inspector } = useContext(DockContext);
  return inspector ? createPortal(<div className="insp-stage">{children}</div>, inspector) : null;
}
