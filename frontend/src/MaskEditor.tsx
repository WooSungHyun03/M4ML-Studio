import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Brush,
  CirclePlus,
  CircleMinus,
  Eraser,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Scan,
} from "lucide-react";
import { setting, type Values, type SettingsBundle } from "./TaskSettings";
import type { Point } from "./api";
import { screenToImage } from "./geometry";

type Tool = "positive" | "negative" | "brush" | "erase";
interface Props {
  settings?: SettingsBundle;
  onDisplayChange?:(v:Values)=>void;
  image: string;
  mask?: string;
  points: Point[];
  onPoints: (p: Point[]) => void;
  onSave: (png: string) => Promise<void>;
  onPreview: () => void;
  disabled: boolean;
  allowSave: boolean;
  pending?: boolean;
  pointUndo: () => void;
  pointRedo: () => void;
  canPointUndo: boolean;
  canPointRedo: boolean;
  onPrevious: () => void;
  onNext: () => void;
  resetMask?: string;
  onDirty: (dirty: boolean) => void;
  /** HUD content rendered over the canvas (top-left), e.g. live inference state. */
  status?: ReactNode;
  /** HUD content rendered over the canvas (top-right), e.g. file name. */
  label?: ReactNode;
  /** Extra region overlay (e.g. removed area), URL of a binary mask. */
  saveLabel?: string;
}

const EDGE_RGB = [255, 196, 110];

/** Interactive mask canvas: click prompts (+/−), brush/erase correction, compare view.
 *  Pixel coordinates are always those of the displayed (undistorted, registered) image. */
export function MaskEditor({
  image,
  settings,
  onDisplayChange,
  mask,
  points,
  onPoints,
  onSave,
  disabled,
  allowSave,
  pending,
  pointUndo,
  pointRedo,
  canPointUndo,
  canPointRedo,
  onPrevious,
  onNext,
  resetMask,
  onDirty,
  status,
  label,
  saveLabel = "저장·승인",
}: Props) {
  const overlay = useRef<HTMLCanvasElement>(null),
    binary = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const viewport = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<Tool>("positive"),
    [zoom, setZoom] = useState(1),
    [opacity, setOpacity] = useState(0.4),
    [radius, setRadius] = useState(18);
  const [viewMode, setViewMode] = useState("overlay"),
    [compare, setCompare] = useState(0);
  const [size, setSize] = useState([1, 1]),
    [fit, setFit] = useState(1),
    [dirty, setDirty] = useState(false),
    [history, setHistory] = useState<ImageData[]>([]),
    [future, setFuture] = useState<ImageData[]>([]),
    [version, setVersion] = useState(0),
    [error, setError] = useState("");
  useEffect(() => {
    setOpacity(setting(settings, "review", "overlay_opacity", 0.4));
    setRadius(setting(settings, "review", "brush_size", 18));
    setViewMode(
      setting(settings, "review", "mask_only", false)
        ? "binary"
        : setting(settings, "review", "show_boundary", false)
          ? "outline"
          : "overlay",
    );
  }, [settings]);
  const maskColor = setting(settings, "review", "overlay_color", "#f0a53a");
  const maskRGB = [1, 3, 5].map((i) => parseInt(maskColor.slice(i, i + 2), 16));
  const lastImage = useRef(image);
  const [loadedImage, setLoadedImage] = useState("");
  const [loadedMask, setLoadedMask] = useState<string | undefined>(undefined);
  const editorReady = loadedImage === image && loadedMask === mask;
  const drawing = useRef(false),
    pan = useRef<{ x: number; y: number; sx: number; sy: number } | null>(null),
    last = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => {
    onDirty(dirty);
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty, onDirty]);

  /** Recompute the coloured overlay from the binary mask (once per mask change). */
  function paint() {
    const ctx = overlay.current?.getContext("2d");
    if (!ctx) return;
    const [w, h] = size;
    const src = binary.current.getContext("2d")!.getImageData(0, 0, w, h).data;
    const out = ctx.createImageData(w, h);
    const d = out.data;
    for (let i = 0, p = 0; i < src.length; i += 4, p++) {
      const inside = src[i] > 127;
      if (viewMode === "binary") {
        d[i] = d[i + 1] = d[i + 2] = inside ? 255 : 0;
        d[i + 3] = 255;
        continue;
      }
      if (!inside) continue;
      const x = p % w;
      const edge =
        x === 0 ||
        x === w - 1 ||
        p < w ||
        p >= w * (h - 1) ||
        src[i - 4] < 128 ||
        src[i + 4] < 128 ||
        src[i - w * 4] < 128 ||
        src[i + w * 4] < 128;
      if (viewMode === "outline" && !edge) continue;
      const c = edge ? EDGE_RGB : maskRGB;
      d[i] = c[0];
      d[i + 1] = c[1];
      d[i + 2] = c[2];
      d[i + 3] = edge ? 255 : 150;
    }
    ctx.putImageData(out, 0, 0);
  }
  useEffect(() => {
    let live = true;
    const load = async () => {
      setError("");
      const img = new Image();
      img.src = image;
      await img.decode();
      if (!live) return;
      const [w, h] = [img.naturalWidth, img.naturalHeight];
      binary.current.width = w;
      binary.current.height = h;
      const ctx = binary.current.getContext("2d", {
        willReadFrequently: true,
      })!;
      ctx.fillStyle = "black";
      ctx.fillRect(0, 0, w, h);
      if (mask) {
        try {
          const m = new Image();
          m.src = mask;
          await m.decode();
          if (!live) return;
          if (m.naturalWidth !== w || m.naturalHeight !== h)
            throw new Error("마스크 크기가 사진과 다릅니다.");
          ctx.drawImage(m, 0, 0);
        } catch {
          if (!live) return;
          setError(
            "마스크를 불러오지 못했습니다. 객체를 다시 클릭하거나 붓으로 수정하세요.",
          );
        }
      }
      setSize([w, h]);
      setLoadedImage(image);
      setLoadedMask(mask);
      setDirty(false);
      setHistory([]);
      setFuture([]);
      if (lastImage.current !== image) {
        setZoom(1);
        lastImage.current = image;
      }
      setVersion((v) => v + 1);
    };
    load().catch((e) => live && setError(String(e.message)));
    return () => {
      live = false;
    };
  }, [image, mask]);
  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const observer = new ResizeObserver(() =>
      setFit(
        Math.min(
          4,
          (node.clientWidth - 32) / size[0],
          (node.clientHeight - 32) / size[1],
        ),
      ),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [size]);
  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const wheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) return;
      e.preventDefault();
      setZoom((z) =>
        Math.max(0.5, Math.min(8, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15))),
      );
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, []);
  useEffect(() => {
    paint();
  }, [maskColor, viewMode, size, version]);

  function location(e: React.PointerEvent) {
    return screenToImage(
      e.clientX,
      e.clientY,
      overlay.current!.getBoundingClientRect(),
      size[0],
      size[1],
    );
  }
  const historyLimit = Math.max(
    1,
    Math.min(15, Math.floor((128 * 1024 * 1024) / (size[0] * size[1] * 4))),
  );
  function snapshot() {
    return binary.current
      .getContext("2d")!
      .getImageData(0, 0, ...(size as [number, number]));
  }
  function remember(h: ImageData[]) {
    return [
      ...(historyLimit > 1 ? h.slice(-(historyLimit - 1)) : []),
      snapshot(),
    ];
  }
  function stroke(p: { x: number; y: number }) {
    // Draw into the binary mask and, for responsiveness, directly onto the overlay.
    for (const [ctx, colour] of [
      [binary.current.getContext("2d")!, tool === "erase" ? "black" : "white"],
      [overlay.current!.getContext("2d")!, `rgb(${maskRGB.join(",")})`],
    ] as const) {
      ctx.save();
      if (ctx.canvas === overlay.current && tool === "erase")
        ctx.globalCompositeOperation = "destination-out";
      ctx.strokeStyle = ctx.fillStyle = colour;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.lineWidth = radius * 2;
      ctx.beginPath();
      if (last.current) {
        ctx.moveTo(last.current.x, last.current.y);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
      } else {
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
    last.current = p;
    setDirty(true);
  }
  function down(e: React.PointerEvent<HTMLCanvasElement>) {
    if (disabled || loadedImage !== image || size[0] <= 1 || size[1] <= 1) return;
    if (
      (!allowSave || !editorReady) &&
      (tool === "brush" || tool === "erase")
    ) {
      setTool("positive");
      return;
    }
    // Focusing an oversized canvas otherwise scrolls its viewport BEFORE mapping
    // this pointer event, shifting the clicked physical pixel after zooming.
    overlay.current!.focus({ preventScroll: true });
    e.currentTarget.setPointerCapture(e.pointerId);
    if (e.button === 1 || e.shiftKey) {
      e.preventDefault();
      pan.current = {
        x: e.clientX,
        y: e.clientY,
        sx: viewport.current!.scrollLeft,
        sy: viewport.current!.scrollTop,
      };
      return;
    }
    const p = location(e);
    if (tool === "positive" || tool === "negative") {
      if (
        dirty &&
        !window.confirm("저장하지 않은 붓 수정을 버리고 클릭으로 다시 계산할까요?")
      )
        return;
      setDirty(false);
      onPoints([
        ...points,
        {
          ...p,
          label: e.button === 2 || e.altKey || tool === "negative" ? 0 : 1,
        },
      ]);
    } else {
      setHistory(remember);
      setFuture([]);
      drawing.current = true;
      last.current = null;
      stroke(p);
    }
  }
  function undo() {
    if (tool === "positive" || tool === "negative") {
      pointUndo();
      return;
    }
    if (!history.length) return;
    setFuture((f) => [...f, snapshot()]);
    binary.current
      .getContext("2d")!
      .putImageData(history[history.length - 1], 0, 0);
    setHistory((h) => h.slice(0, -1));
    setDirty(true);
    setVersion((v) => v + 1);
  }
  function redo() {
    if (tool === "positive" || tool === "negative") {
      pointRedo();
      return;
    }
    if (!future.length) return;
    setHistory(remember);
    binary.current
      .getContext("2d")!
      .putImageData(future[future.length - 1], 0, 0);
    setFuture((f) => f.slice(0, -1));
    setDirty(true);
    setVersion((v) => v + 1);
  }
  async function save() {
    if (!editorReady || disabled || pending || !allowSave) return;
    const ctx = binary.current.getContext("2d")!,
      data = snapshot();
    for (let i = 0; i < data.data.length; i += 4) {
      const v = data.data[i] > 127 ? 255 : 0;
      data.data[i] = data.data[i + 1] = data.data[i + 2] = v;
      data.data[i + 3] = 255;
    }
    ctx.putImageData(data, 0, 0);
    try {
      await onSave(binary.current.toDataURL("image/png").split(",")[1]);
      setDirty(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function reset() {
    if (!resetMask) return;
    const m = new Image();
    m.src = resetMask;
    await m.decode();
    setHistory(remember);
    binary.current.getContext("2d")!.drawImage(m, 0, 0);
    setDirty(true);
    setVersion((v) => v + 1);
  }
  // Edit menu / Ctrl+S from the application shell
  useEffect(() => {
    const u = () => undo(),
      r = () => redo(),
      sv = () => {
        if (dirty && allowSave && !pending) void save();
      };
    window.addEventListener("m4ml:undo", u);
    window.addEventListener("m4ml:redo", r);
    window.addEventListener("m4ml:save", sv);
    return () => {
      window.removeEventListener("m4ml:undo", u);
      window.removeEventListener("m4ml:redo", r);
      window.removeEventListener("m4ml:save", sv);
    };
  });
  const scale = fit * zoom;
  const pointR = 9 / Math.max(scale, 0.05);
  const pointStroke = 2 / Math.max(scale, 0.05);
  return (
    <div className="mask-editor">
      <div className="editor-canvas">
        <div className="image-viewport" ref={viewport}>
          <div
            className="image-sheet"
            style={{ width: size[0] * scale, height: size[1] * scale }}
          >
            <img src={image} alt="선택한 등록 사진" draggable={false} />
            <canvas
              ref={overlay}
              className="edit"
              width={size[0]}
              height={size[1]}
              style={{
                opacity:
                  viewMode === "original"
                    ? 0
                    : viewMode === "binary"
                      ? 1
                      : opacity,
                clipPath: compare ? `inset(0 0 0 ${compare}%)` : undefined,
              }}
              aria-label="마스크 편집 영역. 클릭하면 객체에 포함하고 Alt 클릭이나 오른쪽 클릭은 제외합니다."
              tabIndex={0}
              onContextMenu={(e) => e.preventDefault()}
              onPointerDown={down}
              onPointerMove={(e) => {
                if (pan.current) {
                  viewport.current!.scrollLeft =
                    pan.current.sx + pan.current.x - e.clientX;
                  viewport.current!.scrollTop =
                    pan.current.sy + pan.current.y - e.clientY;
                } else if (drawing.current) stroke(location(e));
              }}
              onPointerUp={() => {
                if (drawing.current) setVersion((v) => v + 1);
                drawing.current = false;
                last.current = null;
                pan.current = null;
              }}
              onPointerCancel={() => {
                drawing.current = false;
                pan.current = null;
              }}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
                  e.preventDefault();
                  e.shiftKey ? redo() : undo();
                }
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
                  e.preventDefault();
                  redo();
                }
                if (e.key === "1" || e.key === "+" || e.key === "=") setTool("positive");
                if (e.key === "2" || e.key === "-") setTool("negative");
                if (e.key === "Tab") {
                  e.preventDefault();
                  setViewMode((m) =>
                    m === "original" ? "overlay" : "original",
                  );
                }
                if (e.key === "Enter" && !pending && allowSave && editorReady) {
                  e.preventDefault();
                  void save();
                }
                if (e.key === "ArrowLeft" || e.key === "a") onPrevious();
                if (e.key === "ArrowRight" || e.key === "d") onNext();
              }}
            />
            {compare > 0 && (
              <div
                aria-hidden
                style={{
                  position: "absolute",
                  top: -8,
                  bottom: -8,
                  left: `${compare}%`,
                  width: 2,
                  marginLeft: -1,
                  background: "#fff",
                  boxShadow: "0 0 0 1px rgba(0,0,0,.35)",
                  pointerEvents: "none",
                }}
              />
            )}
            <svg viewBox={`0 0 ${size[0]} ${size[1]}`} aria-hidden>
              {points.map((p, i) => {
                const newest = i === points.length - 1;
                return (
                  <g key={i} transform={`translate(${p.x} ${p.y})`}>
                    {newest && pending && (
                      <circle r={pointR * 1.9} fill="none" stroke="#fff" strokeOpacity=".85" strokeWidth={pointStroke} strokeDasharray={`${pointR * 2} ${pointR * 1.2}`}>
                        <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="1s" repeatCount="indefinite" />
                      </circle>
                    )}
                    <circle r={pointR} fill={p.label ? "#4cc98a" : "#ff5d52"} stroke="#fff" strokeWidth={pointStroke} />
                    <path
                      d={
                        p.label
                          ? `M${-pointR * 0.45} 0H${pointR * 0.45}M0 ${-pointR * 0.45}V${pointR * 0.45}`
                          : `M${-pointR * 0.45} 0H${pointR * 0.45}`
                      }
                      stroke="#fff"
                      strokeWidth={pointStroke * 1.1}
                      strokeLinecap="round"
                    />
                    <text x={pointR * 1.4} y={-pointR * 0.9} fontSize={pointR * 1.15} fill="#fff" stroke="rgba(0,0,0,.7)" strokeWidth={pointStroke * 1.5} paintOrder="stroke" fontFamily="var(--font-mono)">
                      {i + 1}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
        <div
          className="tool-col"
          style={{ left: 12, top: 12 }}
          aria-label="마스크 편집 도구"
        >
          {(
            [
              ["positive", "포함 클릭 (1)", CirclePlus],
              ["negative", "제외 클릭 (2 · Alt+클릭)", CircleMinus],
              ["brush", "붓으로 칠하기", Brush],
              ["erase", "지우개", Eraser],
            ] as const
          ).map(([key, title, Icon]) => (
            <button
              key={key}
              className="icon-btn"
              title={title}
              aria-label={title}
              disabled={
                disabled ||
                ((!allowSave || pending || !editorReady) &&
                  (key === "brush" || key === "erase"))
              }
              aria-pressed={tool === key}
              onClick={() => setTool(key)}
            >
              <Icon size={18} />
            </button>
          ))}
          <button
            className="icon-btn"
            title="실행 취소 (Ctrl+Z)"
            aria-label="실행 취소"
            disabled={
              disabled ||
              (tool === "positive" || tool === "negative"
                ? !canPointUndo
                : !history.length)
            }
            onClick={undo}
          >
            <Undo2 size={17} />
          </button>
          <button
            className="icon-btn"
            title="다시 실행 (Ctrl+Shift+Z)"
            aria-label="다시 실행"
            disabled={
              disabled ||
              (tool === "positive" || tool === "negative"
                ? !canPointRedo
                : !future.length)
            }
            onClick={redo}
          >
            <Redo2 size={17} />
          </button>
        </div>
        {status && (
          <div
            className="hud"
            style={{ left: 60, top: 12, pointerEvents: "none" }}
          >
            {status}
          </div>
        )}
        {label && (
          <div
            className="hud"
            style={{ right: 12, top: 12, pointerEvents: "none" }}
          >
            {label}
          </div>
        )}
        <div
          className="hud"
          style={{ left: 12, bottom: 12, gap: 12, pointerEvents: "none" }}
        >
          <span className="row" style={{ gap: 5 }}>
            <span className="kbd">클릭</span>포함
          </span>
          <span className="row" style={{ gap: 5 }}>
            <span className="kbd">Alt</span>+<span className="kbd">클릭</span>
            제외
          </span>
          <span className="row" style={{ gap: 5 }}>
            <span className="kbd">Shift</span>+드래그 이동
          </span>
          <span className="row" style={{ gap: 5 }}>
            <span className="kbd">Ctrl+Z</span>되돌리기
          </span>
        </div>
        <div
          className="hud"
          style={{ right: 12, bottom: 12, padding: "3px 4px", gap: 2 }}
        >
          <button
            className="icon-btn"
            aria-label="축소"
            onClick={() => setZoom((z) => Math.max(0.25, z / 1.3))}
          >
            <ZoomOut size={15} />
          </button>
          <span
            className="num"
            style={{ width: 44, textAlign: "center", color: "#ececef" }}
          >
            {Math.round(scale * 100)}%
          </span>
          <button
            className="icon-btn"
            aria-label="확대"
            onClick={() => setZoom((z) => Math.min(8, z * 1.3))}
          >
            <ZoomIn size={15} />
          </button>
          <button
            className="icon-btn"
            aria-label="화면 맞춤"
            onClick={() => setZoom(1)}
          >
            <Scan size={15} />
          </button>
        </div>
      </div>
      <div className="editor-footer">
        <div className="seg" role="group" aria-label="마스크 표시 방식">
          {[
            ["overlay", "오버레이"],
            ["outline", "경계"],
            ["binary", "마스크만"],
            ["original", "원본"],
          ].map(([key, text]) => (
            <button key={key} aria-pressed={viewMode === key} onClick={() => {setViewMode(key);onDisplayChange?.({mask_only:key==='binary',show_boundary:key==='outline'})}}>
              {text}
            </button>
          ))}
        </div>
        <label>
          비교
          <input type="range" min="0" max="100" value={compare} onChange={(e) => setCompare(+e.target.value)} aria-label="원본 비교 위치" style={{ width: 90 }} />
        </label>
        <label>
          투명도
          <input type="range" min="0" max="1" step="0.05" value={opacity} onChange={(e) => {setOpacity(+e.target.value);onDisplayChange?.({overlay_opacity:+e.target.value})}} aria-label="마스크 투명도" style={{ width: 90 }} />
          <span className="num t2">{Math.round(opacity * 100)}%</span>
        </label>
        {(tool === "brush" || tool === "erase") && (
          <label>
            붓 크기
            <input aria-label="붓 반지름" type="range" min="2" max="100" value={radius} onChange={(e) => {setRadius(+e.target.value);onDisplayChange?.({brush_size:+e.target.value})}} style={{ width: 80 }} />
          </label>
        )}
        <span className="sp" />
        {dirty && <span className="warn">저장하지 않은 수정 있음</span>}
        <button className="btn ghost s" disabled={disabled || !editorReady || !resetMask} onClick={() => void reset()}>
          자동 마스크로 복원
        </button>
        <button className="btn s primary" disabled={disabled || pending || !editorReady || !mask || !allowSave} onClick={() => void save()}>
          {saveLabel} <span className="kbd">Enter</span>
        </button>
      </div>
      {error && (
        <p role="alert" className="error" style={{ padding: "6px 12px", background: "var(--bg-1)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
