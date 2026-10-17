import { setting, type SettingsBundle, type Values } from "./TaskSettings";
import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  Camera,
  ChevronLeft,
  ChevronRight,
  Hand,
  Maximize,
  Orbit,
  RefreshCw,
  RotateCcw,
  Scan,
} from "lucide-react";
import { LiveError, post, postBlob } from "./api";
import { applyFreeView, applyRecordedView, navigationUp } from "./viewerCamera";

/** What GET /live-render returns for the project (see studio/api.py). */
export interface LiveInfo {
  artifact?: boolean;
  radius?: number;
  available: boolean;
  reason?: string;
  training_running?: boolean;
  external_viewer?: boolean;
  model?: {
    iterations: number[];
    iteration: number;
    gaussians: number;
    ply_bytes: number;
    target: number[];
    cameras: {
      name: string;
      position: number[];
      rotation: number[][];
      width: number;
      height: number;
      fx: number;
      fy: number;
    }[];
  };
  session?: LiveStatus | null;
}
export interface LiveStatus {
  state: string;
  iteration: number;
  gaussians: number;
  load_seconds: number;
  renderer_vram_mb: number;
  frames: number;
  modes: { key: string; label: string; index: number }[];
  external_viewer: boolean;
}
type State = "starting" | "loading" | "rendering" | "disconnected" | "out_of_memory" | "busy" | "failed";
export interface LiveStats {
  state: State;
  message: string;
  status: LiveStatus | null;
  fps: number | null;
  latencyMs: number | null;
  renderMs: number | null;
  firstFrameMs: number | null;
  size: [number, number] | null;
}

// Closing the viewer stops the renderer (VRAM back); a reopen waits for that stop first.
let pendingStop: Promise<unknown> = Promise.resolve();

const STATE_LABEL: Record<State, string> = {
  starting: "준비 중",
  loading: "불러오는 중",
  rendering: "렌더링 중",
  disconnected: "연결 끊김",
  out_of_memory: "메모리 부족",
  busy: "GPU 사용 중",
  failed: "렌더링 실패",
};

/** Live view of the trained Gaussians. Frames are rendered by the project's real renderer
 *  process (backend `live-render`), one request in flight, newest camera wins: moving camera →
 *  JPEG at CSS resolution; still camera → lossless PNG at device resolution. */
export default function GaussianViewer({
  projectId,
  displaySettings,
  onDisplayChange,
  gpu,
  info,
  iteration,
  onStats,
}: {
  projectId: string;
  displaySettings?: SettingsBundle;
  onDisplayChange?: (v: Values) => void;
  gpu: number;
  info: LiveInfo;
  iteration?: number;
  onStats?: (s: LiveStats) => void;
}) {
  const display = useRef(displaySettings);
  display.current = displaySettings;
  const frame = useRef<HTMLDivElement>(null),
    img = useRef<HTMLImageElement>(null);
  const [state, setState] = useState<State>("starting"),
    [message, setMessage] = useState(""),
    [status, setStatus] = useState<LiveStatus | null>(null),
    [mode, setMode] = useState("rgb"),
    [pan, setPan] = useState(false),
    [camIndex, setCamIndex] = useState(0),
    [perf, setPerf] = useState<{
      fps: number | null;
      latencyMs: number | null;
      renderMs: number | null;
      firstFrameMs: number | null;
      size: [number, number] | null;
    }>({
      fps: null,
      latencyMs: null,
      renderMs: null,
      firstFrameMs: null,
      size: null,
    }),
    [attempt, setAttempt] = useState(0);
  const ctl = useRef({
    configure: () => {},
    request: () => {},
    toCamera: (_i: number) => {},
    fit: () => {},
    pan: (_v: boolean) => {},
    still: async (): Promise<Blob | null> => null,
  });
  const ready = useRef(false);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const cameras = info.model?.cameras || [];

  // Start (or reuse) the renderer for this project/model.
  useEffect(() => {
    let live = true;
    ready.current = false;
    setState("loading");
    setMessage("");
    const t0 = performance.now();
    pendingStop
      .catch(() => {})
      .then(() =>
        post<LiveStatus>(`/projects/${projectId}/live-render/start`, {
          gpu,
          iteration: iteration ?? null,
        }),
      )
      .then((s) => {
        if (!live) return;
        setStatus(s);
        ready.current = true;
        setState("rendering");
        setPerf((p) => ({ ...p, firstFrameMs: null }));
        (ctl.current as any).t0 = t0;
        ctl.current.request();
      })
      .catch((e: Error) => {
        if (!live) return;
        const m = e.message;
        setMessage(m);
        setState(
          /메모리/.test(m)
            ? "out_of_memory"
            : /GPU 작업|사용할 수 있는 NVIDIA/.test(m)
              ? "busy"
              : "failed",
        );
      });
    return () => {
      live = false;
      ready.current = false;
      pendingStop = post(`/projects/${projectId}/live-render/stop`).catch(() => {});
    };
  }, [projectId, gpu, iteration, attempt]);

  // Camera + frame loop.
  useEffect(() => {
    const node = frame.current!;
    const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 1000);
    const controls = new OrbitControls(camera, node);
    controls.enableDamping = true;
    controls.dampingFactor = 0.15;
    controls.zoomSpeed = 1.2;
    let alive = true,
      inflight = false,
      dirty = true,
      moving = false,
      idleTimer = 0,
      stillDone = false,
      url = "",
      times: number[] = [];
    const target = new THREE.Vector3(...((info.model?.target as [number, number, number]) || [0, 0, 0]));
    let scale = (info.radius || 1) * 2.5;
    camera.position
      .copy(target)
      .add(new THREE.Vector3(scale * 0.75, scale * 0.42, scale * 0.75));
    camera.lookAt(target);
    controls.target.copy(target);
    controls.update();

    function setFromTrainingCamera(i: number) {
      // Flush residual drag inertia before applying an exact reset/photo pose.
      const damping = controls.enableDamping;
      controls.enableDamping = false;
      controls.update();
      controls.enableDamping = damping;
      const c = cameras[i];
      if (!c) {
        applyFreeView(camera, controls.target, target, info.radius || 1);
        scale = (info.radius || 1) * 2.5;
        controls.update();
        dirty = true;
        kick();
        return;
      }
      // Keep the recorded position/forward/FOV, normalize roll for Mesh parity.
      applyRecordedView(camera, controls.target, c, target);
      scale = camera.position.distanceTo(target);
      camera.near = Math.max(scale / 1000, 0.001);
      camera.far = scale * 200;
      camera.updateProjectionMatrix();
      controls.update();
      dirty = true;
      kick();
    }
    function fit() {
      // Look at the scene centre from the current direction, at the training-camera distance.
      const dir = camera.position.clone().sub(controls.target).normalize();
      controls.target.copy(target);
      navigationUp(camera);
      camera.position.copy(target).addScaledVector(dir, scale || 1);
      camera.lookAt(target);
      controls.update();
      dirty = true;
      kick();
    }
    function size(dpr: number): [number, number] {
      const r = node.getBoundingClientRect();
      let w = Math.max(16, Math.round(r.width * dpr)),
        h = Math.max(16, Math.round(r.height * dpr));
      const m = Math.max(w, h);
      if (m > 4096) {
        w = Math.round((w * 4096) / m);
        h = Math.round((h * 4096) / m);
      }
      return [w, h];
    }
    function body(w: number, h: number, still: boolean) {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld();
      return {
        background: [1, 3, 5].map(
          (i) =>
            parseInt(
              setting(display.current, "view", "background", "#1c1c20").slice(
                i,
                i + 2,
              ),
              16,
            ) / 255,
        ),
        view: Array.from(camera.matrixWorldInverse.elements), // column-major OpenGL view (= SIBR)
        fovy: THREE.MathUtils.degToRad(camera.fov),
        width: w,
        height: h,
        znear: camera.near,
        zfar: camera.far,
        mode: modeRef.current,
        encoding: still ? "png" : "jpeg",
        quality: 85,
      };
    }
    async function render(still: boolean) {
      const dpr = still ? Math.min(window.devicePixelRatio || 1, 2) : 1;
      const [w, h] = size(
        dpr * setting(display.current, "view", "render_scale", 1),
      );
      const t = performance.now();
      const { blob, headers } = await postBlob(`/projects/${projectId}/live-render/frame`, body(w, h, still));
      const latency = performance.now() - t;
      if (!alive) return;
      const next = URL.createObjectURL(blob);
      img.current!.src = next;
      if (url) URL.revokeObjectURL(url);
      url = next;
      const now = performance.now();
      times = [...times.filter((x) => now - x < 1000), now];
      const t0 = (ctl.current as any).t0 as number | undefined;
      setPerf((p) => ({
        fps: times.length,
        latencyMs: Math.round(latency),
        renderMs: Number(headers.get("X-Render-render-ms")) || null,
        firstFrameMs: p.firstFrameMs ?? (t0 ? Math.round(now - t0) : null),
        size: [w, h],
      }));
      node.dataset.frames = String(Number(node.dataset.frames || 0) + 1);
      node.dataset.lastSize = `${w}x${h}`;
    }
    async function pump() {
      if (inflight || !alive || !ready.current) return;
      inflight = true;
      try {
        while (alive && (dirty || (!moving && !stillDone))) {
          const still = !dirty && !moving;
          dirty = false;
          await render(still);
          if (still) stillDone = true;
        }
      } catch (e) {
        if (alive) {
          const err = e as LiveError;
          setMessage(err.message);
          ready.current = false;
          setState(
            (err.state as State) === "out_of_memory"
              ? "out_of_memory"
              : err.state === "disconnected"
                ? "disconnected"
                : "failed",
          );
        }
      } finally {
        inflight = false;
      }
    }
    function kick() {
      stillDone = false;
      void pump();
    }
    controls.addEventListener("start", () => {
      moving = true;
      window.clearTimeout(idleTimer);
    });
    controls.addEventListener("change", () => {
      dirty = true;
      kick();
    });
    controls.addEventListener("end", () => {
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        moving = false;
        kick();
      }, 180);
    });
    let raf = 0;
    const tick = () => {
      controls.update(); // damping keeps emitting "change" while it settles
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const ro = new ResizeObserver(() => {
      dirty = true;
      kick();
    });
    ro.observe(node);
    ctl.current = {
      ...ctl.current,
      configure: () => {
        camera.fov = setting(display.current, "view", "fov", 35);
        camera.near = setting(display.current, "view", "near", 0.001);
        camera.far = setting(display.current, "view", "far", 100000);
        controls.rotateSpeed = setting(
          display.current,
          "view",
          "rotate_speed",
          1,
        );
        controls.zoomSpeed = setting(display.current, "view", "zoom_speed", 1);
        controls.panSpeed = setting(display.current, "view", "pan_speed", 1);
        camera.updateProjectionMatrix();
        dirty = true;
        kick();
      },
      request: () => {
        dirty = true;
        kick();
      },
      toCamera: setFromTrainingCamera,
      fit,
      pan: (v) => {
        controls.mouseButtons.LEFT = v ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
        node.style.cursor = v ? "move" : "grab";
      },
      still: async () => {
        const [w, h] = size(
          Math.min(window.devicePixelRatio || 1, 2) *
            setting(display.current, "view", "screenshot_scale", 1),
        );
        const { blob } = await postBlob(`/projects/${projectId}/live-render/frame`, body(w, h, true));
        return blob;
      },
    };
    setFromTrainingCamera(0);
    ctl.current.configure();
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      window.clearTimeout(idleTimer);
      ro.disconnect();
      controls.dispose();
      if (url) URL.revokeObjectURL(url);
    };
  }, [projectId, info.model?.ply_bytes, info.model?.iteration]);

  useEffect(() => {
    setMode(setting(displaySettings, "view", "gaussian_mode", "rgb"));
    ctl.current.configure();
  }, [displaySettings]);
  useEffect(() => {
    ctl.current.request();
  }, [mode]);
  useEffect(() => {
    onStats?.({ state, message, status, ...perf });
  }, [state, message, status, perf]);

  const screenshot = useCallback(async () => {
    const blob = await ctl.current.still();
    if (!blob) return;
    const a = document.createElement("a"),
      href = URL.createObjectURL(blob);
    a.href = href;
    a.download = `live-render-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 5000);
  }, []);
  const go = (i: number) => {
    const n = (i + cameras.length) % Math.max(cameras.length, 1);
    setCamIndex(n);
    ctl.current.toCamera(n);
  };
  const modes = status?.modes || [];
  const showOverlay = state !== "rendering";

  return (
    <div
      className="mesh-frame live-frame"
      data-state={state}
      tabIndex={0}
      onKeyDown={(e) => {
        if ((e.target as HTMLElement).tagName === "INPUT") return;
        if (e.key === "f" || e.key === "F") ctl.current.fit();
        else if (e.key === "Home") go(0);
        else return;
        e.preventDefault();
      }}
    >
      <div ref={frame} className="live-surface" aria-label="실시간 렌더 화면">
        <img ref={img} alt="" draggable={false} />
      </div>
      {modes.length > 0 && (
        <div className="hud vp-modes" role="group" aria-label="렌더 모드">
          {modes.map((m) => (
            <button
              key={m.key}
              className="btn s ghost"
              aria-pressed={mode === m.key}
              onClick={() => {
                setMode(m.key);
                onDisplayChange?.({ gaussian_mode: m.key });
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
      )}
      <div className="tool-col" style={{ left: 16, top: 56 }}>
        <button
          className="icon-btn"
          title="회전"
          aria-label="회전"
          aria-pressed={!pan}
          onClick={() => {
            setPan(false);
            ctl.current.pan(false);
          }}
        >
          <Orbit size={18} />
        </button>
        <button
          className="icon-btn"
          title="이동"
          aria-label="이동"
          aria-pressed={pan}
          onClick={() => {
            setPan(true);
            ctl.current.pan(true);
          }}
        >
          <Hand size={18} />
        </button>
        <button
          className="icon-btn"
          title="화면 맞춤 (F)"
          aria-label="화면 맞춤"
          onClick={() => ctl.current.fit()}
        >
          <Scan size={18} />
        </button>
        <button
          className="icon-btn"
          title="시점 초기화 (Home)"
          aria-label="시점 초기화"
          onClick={() => go(0)}
        >
          <RotateCcw size={17} />
        </button>
        <span className="tool-sep" />
        <button
          className="icon-btn"
          title="스크린샷 저장 (PNG)"
          aria-label="스크린샷 저장"
          disabled={state !== "rendering"}
          onClick={() => void screenshot()}
        >
          <Camera size={17} />
        </button>
        <button
          className="icon-btn"
          title="전체 화면"
          aria-label="전체 화면"
          onClick={() =>
            document.fullscreenElement
              ? void document.exitFullscreen()
              : void frame.current?.parentElement?.requestFullscreen()
          }
        >
          <Maximize size={16} />
        </button>
      </div>
      {cameras.length > 1 && (
        <div className="hud vp-views" role="group" aria-label="학습 시점">
          <button
            className="btn s ghost"
            aria-label="이전 학습 시점"
            onClick={() => go(camIndex - 1)}
          >
            <ChevronLeft size={13} />
          </button>
          <span className="num" title={cameras[camIndex]?.name}>
            학습 시점 {camIndex + 1} / {cameras.length}
          </span>
          <button
            className="btn s ghost"
            aria-label="다음 학습 시점"
            onClick={() => go(camIndex + 1)}
          >
            <ChevronRight size={13} />
          </button>
        </div>
      )}
      <div className="hud vp-stats" aria-label="렌더 상태">
        <span
          className={
            state === "rendering" ? "ok" : state === "loading" ? "acc" : "warn"
          }
        >
          {STATE_LABEL[state]}
        </span>
        {perf.size && (
          <span className="num">
            {perf.size[0]} × {perf.size[1]}
          </span>
        )}
        {perf.fps != null && state === "rendering" && (
          <span>
            프레임 <b className="num">{perf.fps}</b>/s
          </span>
        )}
        {perf.latencyMs != null && (
          <span>
            응답 <b className="num">{perf.latencyMs}</b> ms
          </span>
        )}
      </div>
      <div className="hud vp-help">
        <span className="row" style={{ gap: 5 }}>
          <span className="kbd">좌 드래그</span>회전
        </span>
        <span className="row" style={{ gap: 5 }}>
          <span className="kbd">휠</span>확대/축소
        </span>
        <span className="row" style={{ gap: 5 }}>
          <span className="kbd">우 드래그</span>이동
        </span>
        <span className="row" style={{ gap: 5 }}>
          <span className="kbd">F</span>맞춤
        </span>
      </div>
      {showOverlay && (
        <div
          className="viewer-message live-overlay"
          role={state === "loading" ? "status" : "alert"}
        >
          {state === "loading" || state === "starting" ? (
            <>학습된 결과를 불러오는 중입니다…</>
          ) : (
            <span className="col" style={{ alignItems: "center", gap: 10 }}>
              <b>{STATE_LABEL[state]}</b>
              <span>{message}</span>
              <button className="btn" onClick={() => setAttempt((a) => a + 1)}>
                <RefreshCw size={14} />
                다시 연결
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
