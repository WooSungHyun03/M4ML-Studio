import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Axis3d, BarChart3, Camera, Grid3x3, Hand, Orbit, RefreshCw, RotateCcw, Scan, SlidersHorizontal, Sun } from "lucide-react";

/** Display modes that really exist in this viewer.
 *  color   — the stored vertex colours, unlit (exactly the colours in the exported file)
 *  vertex  — the stored vertex colours, lit by the scene lights
 *  shaded  — neutral grey lit surface (geometry only)
 *  wire    — triangle wireframe
 *  normals — surface normal directions as RGB
 *  points  — the mesh vertices drawn as a point cloud */
export type ViewMode = "color" | "vertex" | "shaded" | "wire" | "normals" | "points";
export type ViewName = "front" | "back" | "left" | "right" | "top" | "bottom";

const MODES: [ViewMode, string, boolean][] = [
  ["color", "색상 메시", true],
  ["vertex", "정점 색상", true],
  ["shaded", "셰이딩", false],
  ["wire", "와이어프레임", false],
  ["normals", "법선", false],
  ["points", "포인트 클라우드", false],
];
const VIEWS: [ViewName, string, string][] = [
  ["front", "앞", "+Z 축에서 보기 (Numpad 1)"],
  ["back", "뒤", "−Z 축에서 보기 (Ctrl+Numpad 1)"],
  ["left", "왼쪽", "−X 축에서 보기 (Ctrl+Numpad 3)"],
  ["right", "오른쪽", "+X 축에서 보기 (Numpad 3)"],
  ["top", "위", "+Y 축에서 보기 (Numpad 7)"],
  ["bottom", "아래", "−Y 축에서 보기 (Ctrl+Numpad 7)"],
];
const DIRS: Record<ViewName, [number, number, number]> = {
  front: [0, 0, 1],
  back: [0, 0, -1],
  left: [-1, 0, 0],
  right: [1, 0, 0],
  top: [0, 1, 0],
  bottom: [0, -1, 0],
};
const BACKGROUNDS: [string, string | null][] = [
  ["그래파이트", null],
  ["검정", "#000000"],
  ["회색", "#7a7a80"],
  ["흰색", "#f2f2f2"],
];

export interface MeshStats {
  colored: boolean;
  vertices: number;
  triangles: number;
  size: [number, number, number];
}

/** Real triangle-mesh viewer. Default = the mesh's own vertex colours (unlit), so the
 *  colours the user sees are exactly the colours stored in the exported file. */
export default function MeshViewer({
  url,
  legacyColors = false,
  onStats,
  fileBase = "model",
}: {
  url: string;
  legacyColors?: boolean;
  onStats?: (s: MeshStats) => void;
  fileBase?: string;
}) {
  const host = useRef<HTMLDivElement>(null),
    gizmo = useRef<HTMLDivElement>(null);
  const api = useRef({
    fit: () => {},
    view: (_v: ViewName) => {},
    mode: (_m: ViewMode) => {},
    projection: (_ortho: boolean) => {},
    background: (_c: string | null) => {},
    pan: (_v: boolean) => {},
    grid: (_v: boolean) => {},
    axes: (_v: boolean) => {},
    light: (_intensity: number, _azimuth: number) => {},
    pointSize: (_s: number) => {},
    screenshot: () => {},
  });
  const [mode, setMode] = useState<ViewMode>("color"),
    [ortho, setOrtho] = useState(false),
    [bg, setBg] = useState(0),
    [pan, setPan] = useState(false),
    [grid, setGrid] = useState(true),
    [axes, setAxes] = useState(false),
    [showStats, setShowStats] = useState(true),
    [panel, setPanel] = useState(false),
    [light, setLight] = useState(1),
    [azimuth, setAzimuth] = useState(-35),
    [pointSize, setPointSize] = useState(2),
    [reload, setReload] = useState(0),
    [stats, setStats] = useState<MeshStats | null>(null),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false),
    [hasColor, setHasColor] = useState(false);
  // Settings survive a reload of the same mesh: the effect reads them through this ref.
  const settings = useRef({ mode, ortho, bg, grid, axes, light, azimuth, pointSize });
  settings.current = { mode, ortho, bg, grid, axes, light, azimuth, pointSize };

  useEffect(() => {
    const open = () => setPanel(true);
    window.addEventListener("m4ml:viewport-settings", open);
    return () => window.removeEventListener("m4ml:viewport-settings", open);
  }, []);

  useEffect(() => {
    const node = host.current!,
      gizmoNode = gizmo.current!;
    let alive = true,
      object: THREE.Group | undefined,
      points: THREE.Points | undefined,
      renderer: THREE.WebGLRenderer;
    setLoaded(false);
    setError("");
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch {
      setError("3D 화면을 열 수 없습니다. 그래픽 하드웨어 가속을 확인하세요.");
      return;
    }
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    node.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const persp = new THREE.PerspectiveCamera(35, 1, 0.001, 100000);
    const orthoCam = new THREE.OrthographicCamera(-1, 1, 1, -1, -100000, 100000);
    let camera: THREE.PerspectiveCamera | THREE.OrthographicCamera = persp;
    const controls = new OrbitControls(persp, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    const hemi = new THREE.HemisphereLight(0xffffff, 0x3a3a40, 1.1),
      key = new THREE.DirectionalLight(0xfff6ec, 1.8),
      rim = new THREE.DirectionalLight(0xdfe8ff, 0.8);
    rim.position.set(4, 3, -4);
    scene.add(hemi, key, key.target, rim);
    const gridGroup = new THREE.Group(),
      axesGroup = new THREE.Group();
    scene.add(gridGroup, axesGroup);
    let span = 1;
    const center = new THREE.Vector3();

    function placeKey(az: number) {
      const r = (az * Math.PI) / 180;
      key.position.set(center.x + Math.sin(r) * span, center.y + span * 0.9, center.z + Math.cos(r) * span);
      key.target.position.copy(center);
    }
    function lighting(intensity: number, az: number) {
      hemi.intensity = 1.1 * intensity;
      key.intensity = 1.8 * intensity;
      rim.intensity = 0.8 * intensity;
      placeKey(az);
    }
    function resize() {
      const w = Math.max(node.clientWidth, 1),
        h = Math.max(node.clientHeight, 1);
      renderer.setSize(w, h);
      persp.aspect = w / h;
      persp.updateProjectionMatrix();
      const half = span * 0.6;
      orthoCam.left = (-half * w) / h;
      orthoCam.right = (half * w) / h;
      orthoCam.top = half;
      orthoCam.bottom = -half;
      orthoCam.updateProjectionMatrix();
    }
    function look(dir: THREE.Vector3, up = new THREE.Vector3(0, 1, 0)) {
      const distance = span * 1.15;
      for (const cam of [persp, orthoCam]) {
        cam.up.copy(up);
        cam.position.copy(center).addScaledVector(dir.clone().normalize(), distance);
        cam.lookAt(center);
      }
      orthoCam.zoom = 1;
      orthoCam.updateProjectionMatrix();
      controls.target.copy(center);
      controls.update();
    }
    function fit() {
      if (!object) return;
      const box = new THREE.Box3().setFromObject(object);
      box.getCenter(center);
      span = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-6);
      persp.near = Math.max(span / 10000, 0.00001);
      persp.far = span * 100;
      persp.updateProjectionMatrix();
      resize();
      look(new THREE.Vector3(0.75, 0.42, 0.75));
      placeKey(settings.current.azimuth);
    }
    function view(name: ViewName) {
      const d = new THREE.Vector3(...DIRS[name]);
      // Looking straight down/up the Y axis needs a different "up" so the camera has a defined roll.
      look(d, name === "top" ? new THREE.Vector3(0, 0, -1) : name === "bottom" ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0));
    }
    function disposeMaterial(m: THREE.Material | THREE.Material[]) {
      (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
    }
    function setMaterials(value: ViewMode) {
      if (!object) return;
      object.visible = value !== "points";
      if (points) points.visible = value === "points";
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        disposeMaterial(child.material);
        const colors = !!child.geometry.getAttribute("color");
        child.material =
          value === "color" && colors
            ? new THREE.MeshBasicMaterial({ color: 0xffffff, vertexColors: true, side: THREE.DoubleSide })
            : value === "vertex" && colors
              ? new THREE.MeshStandardMaterial({ color: 0xffffff, vertexColors: true, metalness: 0, roughness: 0.75, side: THREE.DoubleSide })
              : value === "normals"
                ? new THREE.MeshNormalMaterial({ side: THREE.DoubleSide })
                : new THREE.MeshStandardMaterial({
                    color: 0xb9b8bd,
                    metalness: 0,
                    roughness: 0.6,
                    wireframe: value === "wire",
                    side: THREE.DoubleSide,
                  });
      });
    }
    function buildPoints() {
      // One point per mesh vertex (world space), keeping the stored vertex colours when present.
      if (!object) return;
      const positions: number[] = [],
        colors: number[] = [];
      let colored = true;
      object.updateMatrixWorld(true);
      const v = new THREE.Vector3();
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        const g = child.geometry as THREE.BufferGeometry,
          p = g.getAttribute("position"),
          c = g.getAttribute("color");
        if (!c) colored = false;
        for (let i = 0; i < p.count; i++) {
          v.fromBufferAttribute(p, i).applyMatrix4(child.matrixWorld);
          positions.push(v.x, v.y, v.z);
          if (c) colors.push(c.getX(i), c.getY(i), c.getZ(i));
        }
      });
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      if (colored && colors.length) geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      points = new THREE.Points(
        geometry,
        new THREE.PointsMaterial({ size: settings.current.pointSize, sizeAttenuation: false, vertexColors: colored, color: colored ? 0xffffff : 0xc9c8ce }),
      );
      points.visible = false;
      scene.add(points);
    }
    function screenshot() {
      renderer.render(scene, camera);
      renderer.domElement.toBlob((blob) => {
        if (!blob) return;
        const a = document.createElement("a"),
          href = URL.createObjectURL(blob);
        a.href = href;
        a.download = `${fileBase}-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(href), 5000);
      }, "image/png");
    }
    api.current = {
      fit,
      view,
      mode: setMaterials,
      projection: (o) => {
        const from = camera;
        camera = o ? orthoCam : persp;
        camera.position.copy(from.position);
        camera.up.copy(from.up);
        camera.lookAt(controls.target);
        // The orthographic frustum is sized to the whole bounding box (see resize), so zoom 1 frames it.
        if (o) orthoCam.zoom = 1;
        controls.object = camera;
        controls.update();
        resize();
      },
      background: (c) => {
        scene.background = c ? new THREE.Color(c) : null;
      },
      pan: (v) => {
        controls.mouseButtons.LEFT = v ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
        node.style.cursor = v ? "move" : "grab";
      },
      grid: (v) => {
        gridGroup.visible = v;
      },
      axes: (v) => {
        axesGroup.visible = v;
      },
      light: lighting,
      pointSize: (s) => {
        if (points) (points.material as THREE.PointsMaterial).size = s;
      },
      screenshot,
    };

    // Orientation gizmo: projects the world axes with the current camera rotation every frame.
    const labels = Array.from(gizmoNode.querySelectorAll<HTMLElement>("[data-axis]"));
    const lines = Array.from(gizmoNode.querySelectorAll<SVGLineElement>("line[data-axis]"));
    const axisVec: Record<string, THREE.Vector3> = {
      "+x": new THREE.Vector3(1, 0, 0),
      "-x": new THREE.Vector3(-1, 0, 0),
      "+y": new THREE.Vector3(0, 1, 0),
      "-y": new THREE.Vector3(0, -1, 0),
      "+z": new THREE.Vector3(0, 0, 1),
      "-z": new THREE.Vector3(0, 0, -1),
    };
    const inv = new THREE.Quaternion(),
      tmp = new THREE.Vector3();
    function drawGizmo() {
      inv.copy(camera.quaternion).invert();
      for (const el of labels) {
        if (el.tagName.toLowerCase() === "line") continue;
        tmp.copy(axisVec[el.dataset.axis!]).applyQuaternion(inv);
        el.style.transform = `translate(${tmp.x * 30}px, ${-tmp.y * 30}px)`;
        el.style.zIndex = String(Math.round(tmp.z * 10) + 20);
        el.style.opacity = tmp.z < -0.2 ? "0.55" : "1";
      }
      for (const ln of lines) {
        tmp.copy(axisVec[ln.dataset.axis!]).applyQuaternion(inv);
        ln.setAttribute("x2", String(40 + tmp.x * 30));
        ln.setAttribute("y2", String(40 - tmp.y * 30));
      }
    }

    new GLTFLoader().load(
      url + (reload ? (url.includes("?") ? "&" : "?") + "reload=" + reload : ""),
      (gltf) => {
        if (!alive) return;
        object = gltf.scene;
        let colored = 0,
          vertices = 0,
          triangles = 0;
        object.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            const g = child.geometry as THREE.BufferGeometry;
            vertices += g.getAttribute("position").count;
            triangles += (g.index ? g.index.count : g.getAttribute("position").count) / 3;
            if (!g.getAttribute("normal")) g.computeVertexNormals();
            const attr = g.getAttribute("color");
            if (attr) {
              colored++;
              if (legacyColors) {
                const c = new THREE.Color();
                for (let i = 0; i < attr.count; i++) {
                  c.setRGB(attr.getX(i), attr.getY(i), attr.getZ(i)).convertSRGBToLinear();
                  attr.setXYZ(i, c.r, c.g, c.b);
                }
                attr.needsUpdate = true;
              }
            }
          }
        });
        scene.add(object);
        const box = new THREE.Box3().setFromObject(object);
        const sizeV = box.getSize(new THREE.Vector3());
        const size = sizeV.length();
        const c = box.getCenter(new THREE.Vector3());
        const s: MeshStats = { colored: colored > 0, vertices, triangles: Math.round(triangles), size: [sizeV.x, sizeV.y, sizeV.z] };
        setHasColor(colored > 0);
        setStats(s);
        onStats?.(s);
        node.dataset.colorMeshes = String(colored);
        const gridHelper = new THREE.GridHelper(size * 2, 24, 0x70707a, 0x44444c);
        (gridHelper.material as THREE.Material).transparent = true;
        (gridHelper.material as THREE.Material).opacity = 0.8;
        gridHelper.position.set(c.x, box.min.y, c.z);
        gridGroup.add(gridHelper);
        const axesHelper = new THREE.AxesHelper(size * 0.6);
        axesHelper.position.copy(c);
        axesGroup.add(axesHelper);
        buildPoints();
        const st = settings.current;
        // A mesh without colours cannot show colour modes: fall back to shaded and say so in the UI.
        const startMode = !colored && (st.mode === "color" || st.mode === "vertex") ? "shaded" : st.mode;
        if (startMode !== st.mode) setMode(startMode);
        setMaterials(startMode);
        gridGroup.visible = st.grid;
        axesGroup.visible = st.axes;
        scene.background = BACKGROUNDS[st.bg][1] ? new THREE.Color(BACKGROUNDS[st.bg][1]!) : null;
        fit();
        lighting(st.light, st.azimuth);
        if (st.ortho) api.current.projection(true);
        setLoaded(true);
      },
      undefined,
      () => alive && setError("3D 모델 미리보기를 읽지 못했습니다. 원본 PLY와 로그를 확인하세요."),
    );
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
      drawGizmo();
    });
    return () => {
      alive = false;
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      scene.traverse((c) => {
        if (c instanceof THREE.Mesh || c instanceof THREE.LineSegments || c instanceof THREE.Points) {
          c.geometry.dispose();
          disposeMaterial(c.material);
        }
      });
      renderer.dispose();
      node.replaceChildren();
    };
  }, [url, legacyColors, reload]);

  function onKey(e: React.KeyboardEvent) {
    const target = e.target as HTMLElement;
    if (target.tagName === "INPUT") return;
    const k = e.key.toLowerCase();
    const numpad = e.code.startsWith("Numpad");
    if (k === "f") api.current.fit();
    else if (numpad && e.code === "Numpad1") api.current.view(e.ctrlKey ? "back" : "front");
    else if (numpad && e.code === "Numpad3") api.current.view(e.ctrlKey ? "left" : "right");
    else if (numpad && e.code === "Numpad7") api.current.view(e.ctrlKey ? "bottom" : "top");
    else if (numpad && e.code === "Numpad5") {
      setOrtho(!ortho);
      api.current.projection(!ortho);
    } else return;
    e.preventDefault();
  }
  const chooseMode = (m: ViewMode) => {
    setMode(m);
    api.current.mode(m);
  };
  const fmtN = (n: number) => n.toLocaleString("ko-KR");

  return (
    <div className="mesh-frame" tabIndex={0} onKeyDown={onKey} aria-label="3D 뷰포트 — F 맞춤, Numpad 1/3/7 시점, Numpad 5 투영 전환">
      <div ref={host} className="three-host" aria-label="3D 모델 화면" />
      <div className="hud vp-modes" role="group" aria-label="표시 모드">
        {MODES.map(([key, text, needsColor]) => (
          <button
            key={key}
            className="btn s ghost"
            aria-pressed={mode === key}
            disabled={needsColor && loaded && !hasColor}
            title={needsColor && loaded && !hasColor ? "이 파일에는 정점 색상이 없습니다" : undefined}
            onClick={() => chooseMode(key)}
          >
            {text}
          </button>
        ))}
      </div>
      <div className="tool-col" style={{ left: 16, top: 56 }}>
        <button className="icon-btn" title="회전" aria-label="회전" aria-pressed={!pan} onClick={() => { setPan(false); api.current.pan(false); }}><Orbit size={18} /></button>
        <button className="icon-btn" title="이동" aria-label="이동" aria-pressed={pan} onClick={() => { setPan(true); api.current.pan(true); }}><Hand size={18} /></button>
        <button className="icon-btn" title="객체에 맞춤 (F)" aria-label="객체에 맞춤" onClick={() => api.current.fit()}><Scan size={18} /></button>
        <button className="icon-btn" title="카메라 초기화" aria-label="카메라 초기화" onClick={() => { setOrtho(false); api.current.projection(false); api.current.fit(); }}><RotateCcw size={17} /></button>
        <span className="tool-sep" />
        <button className="icon-btn" title="바닥 그리드" aria-label="바닥 그리드" aria-pressed={grid} onClick={() => { setGrid(!grid); api.current.grid(!grid); }}><Grid3x3 size={17} /></button>
        <button className="icon-btn" title="좌표축 (빨강 X · 초록 Y · 파랑 Z)" aria-label="좌표축" aria-pressed={axes} onClick={() => { setAxes(!axes); api.current.axes(!axes); }}><Axis3d size={17} /></button>
        <button className="icon-btn" title="메시 통계" aria-label="메시 통계" aria-pressed={showStats} onClick={() => setShowStats(!showStats)}><BarChart3 size={17} /></button>
        <button className="icon-btn" title="조명·배경·점 크기" aria-label="뷰포트 표시 설정" aria-pressed={panel} onClick={() => setPanel(!panel)}><SlidersHorizontal size={17} /></button>
        <span className="tool-sep" />
        <button className="icon-btn" title="스크린샷 저장 (PNG)" aria-label="스크린샷 저장" disabled={!loaded} onClick={() => api.current.screenshot()}><Camera size={17} /></button>
        <button className="icon-btn" title="3D 모델 다시 불러오기" aria-label="3D 모델 다시 불러오기" onClick={() => setReload((r) => r + 1)}><RefreshCw size={16} /></button>
      </div>

      <div className="vp-gizmo" ref={gizmo}>
        <svg width="80" height="80" aria-hidden>
          <line data-axis="+x" x1="40" y1="40" x2="70" y2="40" stroke="#ef5e52" strokeWidth="2" />
          <line data-axis="+y" x1="40" y1="40" x2="40" y2="10" stroke="#5fc27e" strokeWidth="2" />
          <line data-axis="+z" x1="40" y1="40" x2="40" y2="40" stroke="#5b9cf0" strokeWidth="2" />
        </svg>
        {(
          [
            ["+x", "X", "right", "x"],
            ["-x", "", "left", "x"],
            ["+y", "Y", "top", "y"],
            ["-y", "", "bottom", "y"],
            ["+z", "Z", "front", "z"],
            ["-z", "", "back", "z"],
          ] as [string, string, ViewName, string][]
        ).map(([axis, text, v, c]) => (
          <button key={axis} data-axis={axis} className={"gz " + c + (text ? "" : " neg")} title={VIEWS.find((x) => x[0] === v)![2]} aria-label={`${VIEWS.find((x) => x[0] === v)![1]} 시점`} onClick={() => api.current.view(v)}>
            {text}
          </button>
        ))}
      </div>
      <div className="hud vp-views" role="group" aria-label="카메라 시점">
        {VIEWS.map(([v, text, title]) => (
          <button key={v} className="btn s ghost" title={title} onClick={() => api.current.view(v)}>{text}</button>
        ))}
        <span className="vsep" />
        <button className="btn s ghost" aria-pressed={!ortho} title="원근 투영 (Numpad 5)" onClick={() => { setOrtho(false); api.current.projection(false); }}>원근</button>
        <button className="btn s ghost" aria-pressed={ortho} title="직교 투영 (Numpad 5)" onClick={() => { setOrtho(true); api.current.projection(true); }}>직교</button>
      </div>

      {showStats && stats && (
        <div className="hud vp-stats" aria-label="메시 통계">
          <span>정점 <b className="num">{fmtN(stats.vertices)}</b></span>
          <span>삼각형 <b className="num">{fmtN(stats.triangles)}</b></span>
          <span>크기 <b className="num">{stats.size.map((x) => x.toFixed(2)).join(" × ")}</b></span>
          <span>{stats.colored ? "정점 색상 있음" : "정점 색상 없음"}</span>
        </div>
      )}

      {panel && (
        <div className="hud vp-panel" role="dialog" aria-label="뷰포트 표시 설정">
          <div className="row"><b className="grow">뷰포트 표시 설정</b><button className="btn s ghost" onClick={() => setPanel(false)}>닫기</button></div>
          <label className="vp-field">
            <span className="row"><Sun size={13} />밝기 <span className="sp" /><span className="num">{Math.round(light * 100)}%</span></span>
            <input type="range" min={0.2} max={2.5} step={0.05} value={light} onChange={(e) => { const v = +e.target.value; setLight(v); api.current.light(v, azimuth); }} />
          </label>
          <label className="vp-field">
            <span className="row">주 조명 방향 <span className="sp" /><span className="num">{azimuth}°</span></span>
            <input type="range" min={-180} max={180} step={5} value={azimuth} onChange={(e) => { const v = +e.target.value; setAzimuth(v); api.current.light(light, v); }} />
          </label>
          <p className="hint">조명은 셰이딩·정점 색상·와이어프레임 모드에 적용됩니다. 색상 메시 모드는 파일의 색을 그대로 보여 줍니다.</p>
          <label className="vp-field">
            <span className="row">포인트 크기 <span className="sp" /><span className="num">{pointSize}px</span></span>
            <input type="range" min={1} max={8} step={1} value={pointSize} onChange={(e) => { const v = +e.target.value; setPointSize(v); api.current.pointSize(v); }} />
          </label>
          <div className="vp-field">
            <span>배경</span>
            <div className="row" style={{ gap: 8 }}>
              {BACKGROUNDS.map(([name, colour], i) => (
                <button key={name} className="sw" title={name} aria-label={`배경 ${name}`} aria-pressed={bg === i} style={{ width: 18, height: 18, background: colour || "#26262b" }} onClick={() => { setBg(i); api.current.background(colour); }} />
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="hud vp-help">
        <span className="row" style={{ gap: 5 }}><span className="kbd">좌 드래그</span>회전</span>
        <span className="row" style={{ gap: 5 }}><span className="kbd">휠</span>확대/축소</span>
        <span className="row" style={{ gap: 5 }}><span className="kbd">우 드래그</span>이동</span>
        <span className="row" style={{ gap: 5 }}><span className="kbd">F</span>맞춤</span>
      </div>
      {!loaded && !error && <p className="viewer-message">3D 모델을 불러오는 중입니다…</p>}
      {loaded && !hasColor && (
        <div className="hud" style={{ right: 16, bottom: 14 }}>
          <span className="warn">이 파일에는 정점 색상이 없어 형상만 표시합니다.</span>
        </div>
      )}
      {error && <p role="alert" className="viewer-message error">{error}</p>}
    </div>
  );
}
