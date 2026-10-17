import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { applyFreeView, applyRecordedView, navigationUp, sceneUpFromCameras, uprightQuaternion } from "../src/viewerCamera.ts";
import { engineRows, diagnosticSummary } from "../src/engineInfo.ts";

function element() {
  const listeners = new Map();
  return {
    style: {},
    clientWidth: 900,
    clientHeight: 600,
    addEventListener(k, fn) {
      listeners.set(k, fn);
    },
    removeEventListener(k) {
      listeners.delete(k);
    },
    getRootNode() {
      return this;
    },
    setPointerCapture() {},
    releasePointerCapture() {},
    fire(k, e) {
      listeners.get(k)?.({
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
        preventDefault() {},
        ...e,
      });
    },
  };
}
const R180X = new THREE.Matrix4().makeRotationX(Math.PI);
// A COLMAP camera looking along +Z with image-up -Y_cam (i.e. world up = -Y here).
const photo = (rotation, position) => ({ rotation, position, height: 600, fy: 640 });

test("scene up is the training cameras' mean image-up; none -> +Y", () => {
  const down = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]; // COLMAP y down => image-up is world -Y
  assert.ok(sceneUpFromCameras([photo(down, [0, 0, -5])]).distanceTo(new THREE.Vector3(0, -1, 0)) < 1e-12);
  assert.deepEqual(sceneUpFromCameras([]).toArray(), [0, 1, 0]);
  const q = uprightQuaternion(new THREE.Vector3(0, -1, 0));
  assert.ok(new THREE.Vector3(0, -1, 0).applyQuaternion(q).distanceTo(new THREE.Vector3(0, 1, 0)) < 1e-9);
});

test("photo view reproduces the training camera exactly (position, direction, roll, FOV)", () => {
  const rot = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const up = sceneUpFromCameras([photo(rot, [0, 0, -5])]);
  const c = new THREE.PerspectiveCamera(), target = new THREE.Vector3();
  applyRecordedView(c, target, photo(rot, [0, 0, -5]), new THREE.Vector3(), up);
  // OpenGL view of a COLMAP camera = diag(1,-1,-1) * W2C; here W2C = [I | (0,0,5)].
  const expected = new THREE.Matrix4().set(1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, -5, 0, 0, 0, 1);
  c.matrixWorldInverse.elements.forEach((v, i) => assert.ok(Math.abs(v - expected.elements[i]) < 1e-9, `${i}`));
  assert.ok(Math.abs(c.fov - THREE.MathUtils.radToDeg(2 * Math.atan(600 / 1280))) < 1e-9);
});

test("orbiting a -Y-up scene responds to the screen exactly like the same +Y-up scene", () => {
  for (const [dx, dy] of [[80, 0], [-80, 0], [0, 80], [0, -80], [60, 60], [-60, -60]]) {
    const views = [];
    for (const flipped of [false, true]) {
      const camera = new THREE.PerspectiveCamera(50, 1.5, 0.01, 1000), el = element();
      const up = new THREE.Vector3(0, flipped ? -1 : 1, 0);
      const pos = new THREE.Vector3(3, 2, 5), tgt = new THREE.Vector3(0.5, 0.2, -0.3);
      if (flipped) { pos.applyMatrix4(R180X); tgt.applyMatrix4(R180X); }
      navigationUp(camera, up);
      camera.position.copy(pos);
      const controls = new OrbitControls(camera, el);
      controls.target.copy(tgt);
      controls.update();
      el.fire("pointerdown", { clientX: 450, clientY: 300 });
      el.fire("pointermove", { clientX: 450 + dx, clientY: 300 + dy });
      el.fire("pointerup", { clientX: 450 + dx, clientY: 300 + dy });
      camera.updateMatrixWorld();
      views.push(flipped ? camera.matrixWorldInverse.clone().multiply(R180X) : camera.matrixWorldInverse.clone());
      controls.dispose();
    }
    views[0].elements.forEach((v, i) => assert.ok(Math.abs(v - views[1].elements[i]) < 1e-9, `drag ${dx},${dy} element ${i}`));
  }
});

test("free view and fit keep the scene's up", () => {
  const camera = new THREE.PerspectiveCamera(), target = new THREE.Vector3();
  const up = new THREE.Vector3(0, -1, 0);
  applyFreeView(camera, target, new THREE.Vector3(1, 2, 3), 2, up);
  assert.ok(camera.up.distanceTo(up) < 1e-12);
  // camera sits on the scene's "upper" side: positive component along up
  assert.ok(camera.position.clone().sub(target).dot(up) > 0);
});
test("advanced info excludes tensors and bounds unknown nested values", () => {
  const e = {
    version: "3.1",
    checkpoint_tensors: { secret_tensor: [1, 2] },
    unexpected: { dump: "large" },
  };
  assert.deepEqual(engineRows(e), [
    { key: "version", label: "버전", value: "3.1" },
  ]);
  assert.equal(diagnosticSummary(e.checkpoint_tensors), "1개 항목");
  assert.ok(diagnosticSummary("x".repeat(100000)).length <= 1024);
});

test("a standalone Gaussian with no recorded cameras can reset its orbit", () => {
  const camera=new THREE.PerspectiveCamera(),target=new THREE.Vector3(),center=new THREE.Vector3(4,5,6);
  applyFreeView(camera,target,center,3);const original=camera.matrixWorldInverse.clone();
  camera.position.set(-20,30,10);camera.up.set(0,-1,0);target.set(10,0,5);
  applyFreeView(camera,target,center,3);
  assert.deepEqual(camera.matrixWorldInverse.elements,original.elements);
  assert.deepEqual(target.toArray(),center.toArray());
});
