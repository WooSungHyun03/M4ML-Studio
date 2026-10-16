import { useEffect, useRef, useState } from "react";
import {
  Brush,
  Eraser,
  Plus,
  Minus,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Scan,
} from "lucide-react";
import type { Point } from "./api";
import { screenToImage } from "./geometry";

type Tool = "positive" | "negative" | "brush" | "erase";
interface Props {
  image: string;
  mask?: string;
  points: Point[];
  onPoints: (p: Point[]) => void;
  onSave: (png: string) => Promise<void>;
  onPreview: () => void;
  disabled: boolean;
  allowSave: boolean;
  onPrevious: () => void;
  onNext: () => void;
  resetMask?: string;
  onDirty: (dirty: boolean) => void;
}

export function MaskEditor({
  image,
  mask,
  points,
  onPoints,
  onSave,
  onPreview,
  disabled,
  allowSave,
  onPrevious,
  onNext,
  resetMask,
  onDirty,
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null),
    binary = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const imageRef = useRef<HTMLImageElement>(null),
    viewport = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<Tool>("positive"),
    [zoom, setZoom] = useState(1),
    [opacity, setOpacity] = useState(0.45),
    [radius, setRadius] = useState(18);
  const [size, setSize] = useState([1, 1]),
    [fit, setFit] = useState(1),
    [dirty, setDirty] = useState(false),
    [history, setHistory] = useState<ImageData[]>([]),
    [future, setFuture] = useState<ImageData[]>([]),
    [version, setVersion] = useState(0),
    [error, setError] = useState("");
  const drawing = useRef(false),
    pan = useRef<{ x: number; y: number; sx: number; sy: number } | null>(null),
    last = useRef<{ x: number; y: number } | null>(null);
  const current = useRef({ points, opacity });
  current.current = { points, opacity };
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
  function paint() {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    const bw = binary.current.getContext("2d")!;
    const data = bw.getImageData(0, 0, ...(size as [number, number]));
    for (let i = 0; i < data.data.length; i += 4) {
      const inside = data.data[i] > 127;
      data.data[i] = 42;
      data.data[i + 1] = 202;
      data.data[i + 2] = 173;
      data.data[i + 3] = inside ? Math.round(current.current.opacity * 255) : 0;
    }
    ctx.putImageData(data, 0, 0);
    for (const p of current.current.points) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 6 / Math.max(fit * zoom, 0.1), 0, Math.PI * 2);
      ctx.fillStyle = p.label ? "#1a946a" : "#d5444b";
      ctx.fill();
      ctx.strokeStyle = "white";
      ctx.lineWidth = 2 / Math.max(fit * zoom, 0.1);
      ctx.stroke();
    }
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
      const ctx = binary.current.getContext("2d")!;
      ctx.fillStyle = "black";
      ctx.fillRect(0, 0, w, h);
      setSize([w, h]);
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
            "마스크를 불러오지 못했습니다. 대상 클릭으로 다시 추론하거나 자동 마스크 복원·붓으로 수정하세요.",
          );
        }
      }
      setSize([w, h]);
      setDirty(false);
      setHistory([]);
      setFuture([]);
      setZoom(1);
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
          1,
          (node.clientWidth - 32) / size[0],
          (node.clientHeight - 32) / size[1],
        ),
      ),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [size]);
  useEffect(() => {
    paint();
  }, [points, opacity, size, fit, zoom, version]);
  function location(e: React.PointerEvent) {
    return screenToImage(
      e.clientX,
      e.clientY,
      canvas.current!.getBoundingClientRect(),
      size[0],
      size[1],
    );
  }
  const historyLimit = Math.max(
    1,
    Math.min(15, Math.floor((128 * 1024 * 1024) / (size[0] * size[1] * 4))),
  );
  function remember(h: ImageData[]) {
    return [
      ...(historyLimit > 1 ? h.slice(-(historyLimit - 1)) : []),
      snapshot(),
    ];
  }
  function snapshot() {
    return binary.current
      .getContext("2d")!
      .getImageData(0, 0, ...(size as [number, number]));
  }
  function stroke(p: { x: number; y: number }) {
    const ctx = binary.current.getContext("2d")!;
    ctx.strokeStyle = tool === "erase" ? "black" : "white";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = radius * 2;
    if (last.current) {
      ctx.beginPath();
      ctx.moveTo(last.current.x, last.current.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    last.current = p;
    setDirty(true);
    paint();
  }
  function down(e: React.PointerEvent<HTMLCanvasElement>) {
    if (disabled) return;
    if (!allowSave && (tool === "brush" || tool === "erase")) {
      setTool("positive");
      return;
    }
    canvas.current!.focus();
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
  return (
    <div className="mask-editor">
      <div className="editor-tools" aria-label="마스크 편집 도구">
        {(
          [
            ["positive", "대상 추가", Plus],
            ["negative", "배경 제외", Minus],
            ["brush", "붓", Brush],
            ["erase", "지우개", Eraser],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            disabled={
              disabled || (!allowSave && (key === "brush" || key === "erase"))
            }
            aria-pressed={tool === key}
            onClick={() => setTool(key)}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
        <button
          title="실행 취소 (Ctrl+Z)"
          aria-label="실행 취소"
          disabled={!history.length || disabled}
          onClick={undo}
        >
          <Undo2 size={17} />
        </button>
        <button
          title="다시 실행 (Ctrl+Y)"
          aria-label="다시 실행"
          disabled={!future.length || disabled}
          onClick={redo}
        >
          <Redo2 size={17} />
        </button>
        <label>
          붓 크기
          <input
            aria-label="붓 반지름"
            type="range"
            min="2"
            max="100"
            value={radius}
            onChange={(e) => setRadius(+e.target.value)}
          />
        </label>
        <button
          aria-label="축소"
          onClick={() => setZoom((z) => Math.max(0.25, z / 1.3))}
        >
          <ZoomOut size={17} />
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button
          aria-label="확대"
          onClick={() => setZoom((z) => Math.min(8, z * 1.3))}
        >
          <ZoomIn size={17} />
        </button>
        <button aria-label="사진 맞춤" onClick={() => setZoom(1)}>
          <Scan size={17} />
        </button>
      </div>
      <div className="image-viewport" ref={viewport}>
        <div
          className="image-sheet"
          style={{ width: size[0] * fit * zoom, height: size[1] * fit * zoom }}
        >
          <img
            ref={imageRef}
            src={image}
            alt="선택한 등록 사진"
            draggable={false}
          />
          <canvas
            ref={canvas}
            width={size[0]}
            height={size[1]}
            aria-label="마스크 편집 영역. 클릭으로 대상을 추가하고 Alt 클릭으로 배경을 제외합니다."
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
              drawing.current = false;
              last.current = null;
              pan.current = null;
            }}
            onPointerCancel={() => {
              drawing.current = false;
              pan.current = null;
            }}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "z") {
                e.preventDefault();
                e.shiftKey ? redo() : undo();
              }
              if ((e.ctrlKey || e.metaKey) && e.key === "y") {
                e.preventDefault();
                redo();
              }
              if (e.key === "ArrowLeft") onPrevious();
              if (e.key === "ArrowRight") onNext();
            }}
          />
        </div>
      </div>
      <div className="editor-footer">
        <label>
          마스크 투명도
          <input
            type="range"
            min="0"
            max="0.9"
            step="0.05"
            value={opacity}
            onChange={(e) => setOpacity(+e.target.value)}
          />
        </label>
        <span>
          Shift+드래그: 이동 · 방향키: 이전/다음{" "}
          {dirty ? "· 저장하지 않은 수정 있음" : ""}
        </span>
        <button disabled={disabled || !resetMask} onClick={() => void reset()}>
          자동 마스크로 복원
        </button>
        <button disabled={disabled || !points.length} onClick={onPreview}>
          클릭으로 다시 추론
        </button>
        <button
          className="primary"
          disabled={disabled || !mask || !allowSave}
          onClick={() => void save()}
        >
          저장·승인
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
