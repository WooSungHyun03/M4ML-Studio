import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export default function MeshViewer({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null),
    wire = useRef(false),
    fitAction = useRef<() => void>(() => {}),
    toggle = useRef<(value: boolean) => void>(() => {});
  const colorAction = useRef<(value: boolean) => void>(() => {}),
    lighting = useRef<(value: number) => void>(() => {});
  const colorRef = useRef(true);
  const [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false),
    [wireframe, setWireframe] = useState(false),
    [colored, setColored] = useState(true),
    [lightLevel, setLightLevel] = useState(2);
  useEffect(() => {
    const node = host.current!;
    let alive = true,
      object: THREE.Group | undefined,
      renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError(
        "3D 화면을 열 수 없습니다. 브라우저의 하드웨어 가속을 확인하세요.",
      );
      return;
    }
    setLoaded(false);
    setError("");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    node.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#e7eef2");
    const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 100000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const ambient = new THREE.HemisphereLight(0xffffff, 0x738493, 2);
    scene.add(ambient);
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(3, 5, 3);
    scene.add(light);
    lighting.current = (value) => {
      light.intensity = value;
      ambient.intensity = Math.max(value * 0.7, 0.25);
    };
    function fit() {
      if (!object) return;
      const box = new THREE.Box3().setFromObject(object),
        center = box.getCenter(new THREE.Vector3()),
        size = box.getSize(new THREE.Vector3()).length();
      camera.near = Math.max(size / 10000, 0.00001);
      camera.far = size * 100;
      camera.updateProjectionMatrix();
      camera.position
        .copy(center)
        .add(new THREE.Vector3(size * 0.8, size * 0.45, size * 0.8));
      controls.target.copy(center);
      controls.update();
    }
    fitAction.current = fit;
    toggle.current = (value) => {
      object?.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          const materials = Array.isArray(child.material)
            ? child.material
            : [child.material];
          for (const m of materials) {
            if ("wireframe" in m) m.wireframe = value;
          }
        }
      });
    };
    colorAction.current = (value) => {
      object?.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          for (const m of Array.isArray(child.material)
            ? child.material
            : [child.material]) {
            if (m instanceof THREE.MeshStandardMaterial) {
              m.vertexColors = value && !!child.geometry.getAttribute("color");
              m.color.set(value ? "#ffffff" : "#a8bbc6");
              m.needsUpdate = true;
            }
          }
        }
      });
    };
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (!alive) return;
        object = gltf.scene;
        scene.add(object);
        toggle.current(wire.current);
        colorAction.current(colorRef.current);
        fit();
        setLoaded(true);
      },
      undefined,
      () =>
        alive &&
        setError(
          "메시 미리보기를 읽지 못했습니다. 원본 PLY와 추출 로그를 확인하세요.",
        ),
    );
    const observer = new ResizeObserver(() => {
      const w = node.clientWidth,
        h = node.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    });
    observer.observe(node);
    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });
    return () => {
      alive = false;
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      scene.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose();
          for (const m of Array.isArray(child.material)
            ? child.material
            : [child.material])
            m.dispose();
        }
      });
      renderer.dispose();
      node.replaceChildren();
    };
  }, [url]);
  return (
    <div className="mesh-frame">
      <div
        ref={host}
        className="three-host"
        aria-label="실제 삼각형 메시 3D 화면"
      />
      <div className="mesh-controls">
        <button onClick={() => fitAction.current()}>전체 맞춤</button>
        <label>
          <input
            type="checkbox"
            checked={wireframe}
            onChange={(e) => {
              setWireframe(e.target.checked);
              wire.current = e.target.checked;
              toggle.current(e.target.checked);
            }}
          />
          와이어프레임
        </label>
        <label>
          <input
            type="checkbox"
            checked={colored}
            onChange={(e) => {
              setColored(e.target.checked);
              colorRef.current = e.target.checked;
              colorAction.current(e.target.checked);
            }}
          />
          정점 색상
        </label>
        <label>
          조명
          <input
            type="range"
            min="0.2"
            max="4"
            step="0.2"
            value={lightLevel}
            onChange={(e) => {
              setLightLevel(+e.target.value);
              lighting.current(+e.target.value);
            }}
          />
        </label>
        <span>드래그: 회전 · 오른쪽 드래그: 이동 · 휠: 확대</span>
      </div>
      {!loaded && !error && (
        <p className="viewer-message">실제 메시를 불러오는 중입니다…</p>
      )}
      {error && (
        <p role="alert" className="viewer-message error">
          {error}
        </p>
      )}
    </div>
  );
}
