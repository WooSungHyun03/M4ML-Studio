import * as THREE from "three";

export interface RecordedCamera {
  rotation: number[][];
  position: number[];
  height: number;
  fy: number;
}

// Mesh and Gaussian workspaces orbit about world +Y. COLMAP's image-up is not a
// navigation axis: using it reverses mouse motion for cameras with up≈−Y.
export function navigationUp(camera: THREE.Camera) {
  camera.up.set(0, 1, 0);
}

export function applyFreeView(camera: THREE.PerspectiveCamera, target: THREE.Vector3,
  sceneTarget: THREE.Vector3, radius: number) {
  navigationUp(camera);
  target.copy(sceneTarget);
  camera.position.copy(sceneTarget).add(new THREE.Vector3(.75, .42, .75).multiplyScalar(radius * 2.5));
  camera.lookAt(target);
  camera.updateMatrixWorld();
}

export function applyRecordedView(
  camera: THREE.PerspectiveCamera,
  target: THREE.Vector3,
  record: RecordedCamera,
  sceneTarget: THREE.Vector3,
) {
  const r = record.rotation;
  const forward = new THREE.Vector3(r[0][2], r[1][2], r[2][2]).normalize();
  camera.position.fromArray(record.position);
  target
    .copy(camera.position)
    .addScaledVector(
      forward,
      Math.max(sceneTarget.clone().sub(camera.position).dot(forward), 0.1),
    );
  navigationUp(camera);
  camera.fov = THREE.MathUtils.radToDeg(
    2 * Math.atan(record.height / (2 * record.fy)),
  );
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
}
