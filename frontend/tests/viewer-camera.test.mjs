import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { applyFreeView, applyRecordedView, navigationUp } from "../src/viewerCamera.ts";
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
test("COLMAP image-up must not reverse real OrbitControls pointer axes", () => {
  for (const [dx, dy] of [
    [80, 0],
    [-80, 0],
    [0, 80],
    [0, -80],
    [60, 60],
    [-60, -60],
  ]) {
    const result = [];
    for (const recorded of [false, true]) {
      const camera = new THREE.PerspectiveCamera(50, 1.5, 0.01, 1000),
        el = element();
      camera.position.set(3, 2, 5);
      const target = new THREE.Vector3();
      if (recorded)
        applyRecordedView(
          camera,
          target,
          {
            rotation: [
              [1, 0, 0],
              [0, 1, 0],
              [0, 0, 1],
            ],
            position: [3, 2, -5],
            height: 600,
            fy: 640,
          },
          new THREE.Vector3(3, 2, 0),
        );
      // Compare from the same view pose; training selection's +Y must survive.
      camera.position.set(3, 2, 5);
      target.set(0, 0, 0);
      const controls = new OrbitControls(camera, el);
      controls.target.copy(target);
      controls.update();
      el.fire("pointerdown", { clientX: 450, clientY: 300 });
      el.fire("pointermove", { clientX: 450 + dx, clientY: 300 + dy });
      el.fire("pointerup", { clientX: 450 + dx, clientY: 300 + dy });
      result.push(camera.matrixWorldInverse.clone());
      controls.dispose();
    }
    result[0].elements.forEach((v, i) =>
      assert.ok(Math.abs(v - result[1].elements[i]) < 1e-9),
    );
  }
});
test("recorded position, direction and FOV retained; fit restores stable up", () => {
  const c = new THREE.PerspectiveCamera(),
    target = new THREE.Vector3();
  applyRecordedView(
    c,
    target,
    {
      rotation: [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ],
      position: [0, 0, -5],
      height: 600,
      fy: 600,
    },
    new THREE.Vector3(),
  );
  assert.deepEqual(c.up.toArray(), [0, 1, 0]);
  assert.deepEqual(c.position.toArray(), [0, 0, -5]);
  assert.ok(
    c
      .getWorldDirection(new THREE.Vector3())
      .distanceTo(new THREE.Vector3(0, 0, 1)) < 1e-9,
  );
  c.up.set(0, -1, 0);
  navigationUp(c);
  assert.deepEqual(c.up.toArray(), [0, 1, 0]);
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
