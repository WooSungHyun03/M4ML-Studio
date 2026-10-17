import * as THREE from "three";

export interface RecordedCamera {
  rotation: number[][];
  position: number[];
  height: number;
  fy: number;
}

const Y = new THREE.Vector3(0, 1, 0);

/** The scene's real "up": the mean world-space image-up (−Y_cam) of the training cameras.
 *  COLMAP worlds have no fixed up axis; many captures have up ≈ −Y. Orbiting about this
 *  axis keeps photo views upright on screen, so mouse motion follows the screen; orbiting
 *  about a fixed +Y showed such scenes upside down. Without cameras, +Y. */
export function sceneUpFromCameras(cameras?: RecordedCamera[] | null): THREE.Vector3 {
  const v = new THREE.Vector3();
  for (const c of cameras || []) {
    const r = c.rotation;
    v.add(new THREE.Vector3(-r[0][1], -r[1][1], -r[2][1]));
  }
  return v.lengthSq() > 1e-12 ? v.normalize() : Y.clone();
}

/** Rotation that maps the scene's up onto +Y (used to display meshes upright). */
export function uprightQuaternion(sceneUp: THREE.Vector3): THREE.Quaternion {
  return new THREE.Quaternion().setFromUnitVectors(sceneUp.clone().normalize(), Y);
}

export function navigationUp(camera: THREE.Camera, sceneUp: THREE.Vector3 = Y) {
  camera.up.copy(sceneUp).normalize();
}

export function applyFreeView(camera: THREE.PerspectiveCamera, target: THREE.Vector3,
  sceneTarget: THREE.Vector3, radius: number, sceneUp: THREE.Vector3 = Y) {
  navigationUp(camera, sceneUp);
  target.copy(sceneTarget);
  const offset = new THREE.Vector3(.75, .42, .75).multiplyScalar(radius * 2.5)
    .applyQuaternion(uprightQuaternion(sceneUp).invert());
  camera.position.copy(sceneTarget).add(offset);
  camera.lookAt(target);
  camera.updateMatrixWorld();
}

export function applyRecordedView(
  camera: THREE.PerspectiveCamera,
  target: THREE.Vector3,
  record: RecordedCamera,
  sceneTarget: THREE.Vector3,
  sceneUp: THREE.Vector3 = Y,
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
  navigationUp(camera, sceneUp);
  camera.fov = THREE.MathUtils.radToDeg(
    2 * Math.atan(record.height / (2 * record.fy)),
  );
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
}
