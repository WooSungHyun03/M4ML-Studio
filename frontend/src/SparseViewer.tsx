import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Scan } from "lucide-react";
import { api } from "./api";

interface Sparse {
  count: number;
  xyz: string;
  rgb: string;
  cameras: { name: string; center: number[]; rotation: number[][] }[];
}

const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

/** Real COLMAP sparse reconstruction viewer: the selected model's 3D points with their colours and
 *  one frustum per registered camera (COLMAP camera looks along +Z, image y points down). */
export default function SparseViewer({ projectId, selected, onPick }: { projectId: string; selected?: string; onPick?: (name: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [info, setInfo] = useState<{ points: number; cameras: number } | null>(null),
    [error, setError] = useState(""),
    [showCams, setShowCams] = useState(true),
    [size, setSize] = useState(3);
  const ctl = useRef({ fit: () => {}, cams: (_v: boolean) => {}, size: (_s: number) => {}, select: (_n?: string) => {} });

  useEffect(() => {
    const node = host.current!;
    let alive = true,
      renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setError("3D 화면을 열 수 없습니다. 그래픽 하드웨어 가속을 확인하세요.");
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    node.appendChild(renderer.domElement);
    const scene = new THREE.Scene(),
      camera = new THREE.PerspectiveCamera(45, 1, 0.001, 1e5),
      controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const frusta = new THREE.Group();
    scene.add(frusta);
    const camLines: Record<string, THREE.LineSegments> = {};
    let pointsMat: THREE.PointsMaterial | null = null,
      box = new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
    const resize = () => {
      const w = Math.max(node.clientWidth, 1),
        h = Math.max(node.clientHeight, 1);
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const fit = () => {
      const c = box.getCenter(new THREE.Vector3()),
        span = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-6);
      camera.near = span / 1e4;
      camera.far = span * 100;
      camera.up.set(0, -1, 0); // COLMAP world: y points down in most captures
      camera.position.copy(c).add(new THREE.Vector3(0, -span * 0.3, -span * 0.7));
      camera.updateProjectionMatrix();
      controls.target.copy(c);
      controls.update();
    };
    ctl.current = {
      fit,
      cams: (v) => (frusta.visible = v),
      size: (s) => pointsMat && (pointsMat.size = s),
      select: (name) => {
        for (const [n, l] of Object.entries(camLines)) (l.material as THREE.LineBasicMaterial).color.set(n === name ? 0xf0a53a : 0x5b9cf0);
      },
    };
    api<Sparse>(`/projects/${projectId}/sparse-points`)
      .then((d) => {
        if (!alive) return;
        const xyz = new Float32Array(bytes(d.xyz).buffer),
          rgb = bytes(d.rgb),
          col = new Float32Array(rgb.length);
        for (let i = 0; i < rgb.length; i++) col[i] = rgb[i] / 255;
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(xyz, 3));
        g.setAttribute("color", new THREE.BufferAttribute(col, 3));
        // Robust bounds: ignore the farthest 10 % of points so stray outliers don't shrink the view.
        g.computeBoundingBox();
        const pts = Array.from({ length: d.count }, (_, i) => i);
        const med = new THREE.Vector3();
        for (const axis of [0, 1, 2]) {
          const s = pts.map((i) => xyz[i * 3 + axis]).sort((a, b) => a - b);
          med.setComponent(axis, s[Math.floor(s.length / 2)] ?? 0);
        }
        const dist = pts.map((i) => Math.hypot(xyz[i * 3] - med.x, xyz[i * 3 + 1] - med.y, xyz[i * 3 + 2] - med.z)).sort((a, b) => a - b);
        const r = dist[Math.floor(dist.length * 0.9)] || 1;
        box = new THREE.Box3(med.clone().subScalar(r), med.clone().addScalar(r));
        pointsMat = new THREE.PointsMaterial({ size, sizeAttenuation: false, vertexColors: true });
        scene.add(new THREE.Points(g, pointsMat));
        const s = r * 0.06;
        for (const cam of d.cameras) {
          const R = new THREE.Matrix3().set(...(cam.rotation.flat() as [number, number, number, number, number, number, number, number, number]));
          const c = new THREE.Vector3(...cam.center);
          const corner = (x: number, y: number) => new THREE.Vector3(x * s * 0.75, y * s * 0.5, s).applyMatrix3(R).add(c);
          const [a, b, e, f] = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)];
          const v = [c, a, c, b, c, e, c, f, a, b, b, e, e, f, f, a].flatMap((p) => [p.x, p.y, p.z]);
          const lg = new THREE.BufferGeometry();
          lg.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
          const line = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x5b9cf0 }));
          line.userData.name = cam.name;
          camLines[cam.name] = line;
          frusta.add(line);
          box.expandByPoint(c);
        }
        ctl.current.select(selected);
        setInfo({ points: d.count, cameras: d.cameras.length });
        resize();
        fit();
      })
      .catch((e) => alive && setError((e as Error).message));
    // Click a camera frustum to select that photo.
    const ray = new THREE.Raycaster();
    let down = [0, 0];
    const onDown = (e: PointerEvent) => (down = [e.clientX, e.clientY]);
    const onUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !frusta.visible) return;
      const rect = renderer.domElement.getBoundingClientRect();
      ray.params.Line = { threshold: box.getSize(new THREE.Vector3()).length() * 0.01 };
      ray.setFromCamera(new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1), camera);
      const hit = ray.intersectObjects(frusta.children, false)[0];
      if (hit) onPick?.(hit.object.userData.name);
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    const obs = new ResizeObserver(resize);
    obs.observe(node);
    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });
    return () => {
      alive = false;
      obs.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      scene.traverse((o) => {
        if (o instanceof THREE.Points || o instanceof THREE.LineSegments) {
          o.geometry.dispose();
          (o.material as THREE.Material).dispose();
        }
      });
      renderer.dispose();
      node.replaceChildren();
    };
  }, [projectId]);
  useEffect(() => ctl.current.select(selected), [selected]);

  return (
    <div className="mesh-frame sparse-frame">
      <div ref={host} className="three-host" aria-label="희소 포인트 클라우드" />
      <div className="hud" style={{ left: 12, top: 12, gap: 10 }}>
        {info ? <span>포인트 <b className="num">{info.points.toLocaleString("ko-KR")}</b> · 카메라 <b className="num">{info.cameras}</b></span> : !error && <span>포인트 클라우드를 불러오는 중…</span>}
        <label className="row" style={{ gap: 5 }}><input type="checkbox" checked={showCams} onChange={(e) => { setShowCams(e.target.checked); ctl.current.cams(e.target.checked); }} />카메라 표시</label>
        <label className="row" style={{ gap: 5 }}>점 크기<input type="range" min={1} max={6} value={size} onChange={(e) => { setSize(+e.target.value); ctl.current.size(+e.target.value); }} style={{ width: 70, accentColor: "var(--accent)" }} /></label>
        <button className="btn s ghost" style={{ color: "#c9c8ce" }} onClick={() => ctl.current.fit()}><Scan size={13} />맞춤</button>
      </div>
      <div className="hud" style={{ left: 12, bottom: 12 }}>카메라 사각뿔을 클릭하면 해당 사진을 선택합니다 · 주황색 = 선택된 사진</div>
      {error && <p role="alert" className="viewer-message error">{error}</p>}
    </div>
  );
}
