import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Box, Hand, Orbit, RotateCcw, Scan } from "lucide-react";

export type ViewMode = "color" | "shaded" | "wire" | "colorwire";
const BACKGROUNDS: [string, string | null][] = [
  ["그래파이트", null],
  ["검정", "#000000"],
  ["회색", "#7a7a80"],
  ["흰색", "#f2f2f2"],
];

/** Real triangle-mesh viewer. Default = the mesh's own vertex colours (unlit), so the
 *  colours the user sees are exactly the colours stored in the exported file. */
export default function MeshViewer({
  url,
  legacyColors = false,
  onStats,
}: {
  url: string;
  legacyColors?: boolean;
  onStats?: (s: { colored: boolean; vertices: number; triangles: number }) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef({
    fit: () => {},
    mode: (_m: ViewMode) => {},
    projection: (_ortho: boolean) => {},
    background: (_c: string | null) => {},
    pan: (_v: boolean) => {},
    grid: (_v: boolean) => {},
  });
  const [mode, setMode] = useState<ViewMode>("color"),
    [ortho, setOrtho] = useState(false),
    [bg, setBg] = useState(0),
    [pan, setPan] = useState(false),
    [grid, setGrid] = useState(true),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false),
    [hasColor, setHasColor] = useState(false);
  const modeRef = useRef<ViewMode>("color");

  useEffect(() => {
    const node = host.current!;
    let alive = true,
      object: THREE.Group | undefined,
      renderer: THREE.WebGLRenderer;
    setLoaded(false);
    setError("");
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setError("3D 화면을 열 수 없습니다. 브라우저의 하드웨어 가속을 확인하세요.");
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
    let camera: THREE.Camera = persp;
    const controls = new OrbitControls(persp, renderer.domElement);
    const hemi = new THREE.HemisphereLight(0xffffff, 0x3a3a40, 1.1),
      key = new THREE.DirectionalLight(0xfff6ec, 1.8),
      rim = new THREE.DirectionalLight(0xdfe8ff, 0.8);
    key.position.set(-3, 5, 4);
    rim.position.set(4, 3, -4);
    scene.add(hemi, key, rim);
    const helpers = new THREE.Group();
    scene.add(helpers);
    let span = 1;
    const center = new THREE.Vector3();

    function resize() {
      const w = node.clientWidth,
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
    function fit() {
      if (!object) return;
      const box = new THREE.Box3().setFromObject(object);
      box.getCenter(center);
      span = box.getSize(new THREE.Vector3()).length();
      persp.near = Math.max(span / 10000, 0.00001);
      persp.far = span * 100;
      persp.position.copy(center).add(new THREE.Vector3(span * 0.75, span * 0.42, span * 0.75));
      persp.updateProjectionMatrix();
      orthoCam.position.copy(persp.position);
      orthoCam.zoom = 1;
      controls.target.copy(center);
      controls.update();
      resize();
    }
    function setMaterials(value: ViewMode) {
      object?.traverse((child) => {
        if (!(child instanceof THREE.Mesh) || child.userData.wireOverlay) return;
        (Array.isArray(child.material) ? child.material : [child.material]).forEach((m) => m.dispose());
        const colors = !!child.geometry.getAttribute("color");
        child.material =
          (value === "color" || value === "colorwire") && colors
            ? new THREE.MeshBasicMaterial({ color: 0xffffff, vertexColors: true, side: THREE.DoubleSide })
            : new THREE.MeshStandardMaterial({
                color: 0xb9b8bd,
                metalness: 0,
                roughness: 0.6,
                wireframe: value === "wire",
                side: THREE.DoubleSide,
              });
        let overlay = child.children.find((c) => c.userData.wireOverlay) as THREE.Mesh | undefined;
        if (value === "colorwire") {
          if (!overlay) {
            overlay = new THREE.Mesh(
              child.geometry,
              new THREE.MeshBasicMaterial({ color: 0x0d0d0f, wireframe: true, transparent: true, opacity: 0.25 }),
            );
            overlay.userData.wireOverlay = true;
            child.add(overlay);
          }
        } else if (overlay) {
          child.remove(overlay);
          (overlay.material as THREE.Material).dispose();
        }
      });
    }
    api.current = {
      fit,
      mode: setMaterials,
      projection: (o) => {
        camera = o ? orthoCam : persp;
        controls.object = camera;
        orthoCam.position.copy(persp.position);
        orthoCam.lookAt(controls.target);
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
        helpers.visible = v;
      },
    };
    new GLTFLoader().load(
      url,
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
        setHasColor(colored > 0);
        onStats?.({ colored: colored > 0, vertices, triangles: Math.round(triangles) });
        node.dataset.colorMeshes = String(colored);
        scene.add(object);
        const box = new THREE.Box3().setFromObject(object);
        const size = box.getSize(new THREE.Vector3()).length();
        const c = box.getCenter(new THREE.Vector3());
        const gridHelper = new THREE.GridHelper(size * 2, 24, 0x70707a, 0x44444c);
        (gridHelper.material as THREE.Material).transparent = true;
        (gridHelper.material as THREE.Material).opacity = 0.8;
        gridHelper.position.set(c.x, box.min.y, c.z);
        helpers.add(gridHelper);
        setMaterials(modeRef.current);
        fit();
        setLoaded(true);
      },
      undefined,
      () => alive && setError("3D 모델 미리보기를 읽지 못했습니다. 원본 PLY와 로그를 확인하세요."),
    );
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    renderer.setAnimationLoop(() => renderer.render(scene, camera));
    return () => {
      alive = false;
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      scene.traverse((c) => {
        if (c instanceof THREE.Mesh || c instanceof THREE.LineSegments) {
          if (!c.userData.wireOverlay) c.geometry.dispose();
          (Array.isArray(c.material) ? c.material : [c.material]).forEach((m) => m.dispose());
        }
      });
      renderer.dispose();
      node.replaceChildren();
    };
  }, [url, legacyColors]);

  return (
    <div className="mesh-frame">
      <div ref={host} className="three-host" aria-label="3D 모델 화면" />
      <div className="hud" style={{ left: 16, top: 14, gap: 4, padding: 3 }} role="group" aria-label="보기 모드">
        {(
          [
            ["color", "정점 색상"],
            ["shaded", "형상"],
            ["wire", "와이어프레임"],
            ["colorwire", "색상 + 선"],
          ] as [ViewMode, string][]
        ).map(([key, text]) => (
          <button
            key={key}
            className="btn s ghost"
            style={mode === key ? { background: "rgba(240,165,58,.16)", color: "#f0a53a" } : { color: "#c9c8ce" }}
            aria-pressed={mode === key}
            disabled={key.startsWith("color") && loaded && !hasColor}
            onClick={() => {
              modeRef.current = key;
              setMode(key);
              api.current.mode(key);
            }}
          >
            {text}
          </button>
        ))}
        <span style={{ width: 1, height: 18, background: "#3a3a41", margin: "0 4px" }} />
        <button className="btn s ghost" style={{ color: "#c9c8ce" }} aria-pressed={!ortho} onClick={() => { setOrtho(false); api.current.projection(false); }}>
          {!ortho ? <b>원근</b> : "원근"}
        </button>
        <button className="btn s ghost" style={{ color: "#c9c8ce" }} aria-pressed={ortho} onClick={() => { setOrtho(true); api.current.projection(true); }}>
          {ortho ? <b>직교</b> : "직교"}
        </button>
      </div>
      <div className="tool-col" style={{ left: 16, top: 56 }}>
        <button className="icon-btn" title="회전" aria-pressed={!pan} onClick={() => { setPan(false); api.current.pan(false); }}><Orbit size={18} /></button>
        <button className="icon-btn" title="이동" aria-pressed={pan} onClick={() => { setPan(true); api.current.pan(true); }}><Hand size={18} /></button>
        <button className="icon-btn" title="객체에 맞춤 (F)" onClick={() => api.current.fit()}><Scan size={18} /></button>
        <button className="icon-btn" title="카메라 초기화" onClick={() => { setOrtho(false); api.current.projection(false); api.current.fit(); }}><RotateCcw size={17} /></button>
        <button className="icon-btn" title="바닥 그리드" aria-pressed={grid} onClick={() => { setGrid(!grid); api.current.grid(!grid); }}><Box size={17} /></button>
      </div>
      <div className="hud" style={{ left: "50%", transform: "translateX(-50%)", bottom: 14, gap: 12 }}>
        <span className="row" style={{ gap: 5 }}><span className="kbd">좌 드래그</span>회전</span>
        <span className="row" style={{ gap: 5 }}><span className="kbd">휠</span>확대/축소</span>
        <span className="row" style={{ gap: 5 }}><span className="kbd">우 드래그</span>이동</span>
      </div>
      <div className="hud" style={{ right: 16, bottom: 14, gap: 8 }}>
        배경
        {BACKGROUNDS.map(([name, colour], i) => (
          <button
            key={name}
            className="sw"
            title={name}
            aria-label={`배경 ${name}`}
            aria-pressed={bg === i}
            style={{ width: 16, height: 16, background: colour || "#26262b" }}
            onClick={() => {
              setBg(i);
              api.current.background(colour);
            }}
          />
        ))}
      </div>
      {!loaded && !error && <p className="viewer-message">3D 모델을 불러오는 중입니다…</p>}
      {loaded && !hasColor && (
        <div className="hud" style={{ right: 16, top: 14 }}>
          <span className="warn">이 파일에는 정점 색상이 없어 형상만 표시합니다.</span>
        </div>
      )}
      {error && <p role="alert" className="viewer-message error">{error}</p>}
    </div>
  );
}
