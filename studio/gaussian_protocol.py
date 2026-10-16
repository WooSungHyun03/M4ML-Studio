"""Client side of the 2DGS / Gaussian-Splatting-Monitor remote-viewer wire protocol.

This is the exact protocol `SIBR_remoteGaussian_app_rwdi` speaks to `view.py`
(`gaussian_renderer/network_gui.py`), re-implemented so the M4ML backend can drive the
same renderer process and stream its frames into the editor viewport:

* on connect the server sends ``uint32 length + JSON list`` of render-item names;
* per frame the client sends ``uint32 length + JSON`` with ``resolution_x/y``, ``fov_x/y``,
  ``z_near/far``, ``train``, ``keep_alive``, ``scaling_modifier``, ``render_mode`` and the
  OpenGL (SIBR) ``view_matrix`` / ``view_projection_matrix`` as 16 column-major floats;
* the server answers ``W*H*3`` raw RGB bytes (when W*H > 0), ``uint32 length + ascii`` scene
  path, then ``uint32 length + JSON`` metrics.

Lengths are native little-endian uint32, as in both the C++ client and the Python server.
Camera conventions follow SIBR: OpenGL view (camera looks down −Z, +Y up) and a standard
OpenGL perspective; ``network_gui.receive`` converts them to the 3DGS convention.
"""

from __future__ import annotations

import json
import math
import socket
import struct

import numpy as np

MAX_JSON_BYTES = 64 * 1024
MAX_FRAME_SIDE = 4096
MAX_CAMERA_VALUE = float(np.finfo(np.float32).max)


def receive_json(conn):
    """Read one original wire-format packet, rejecting its length before allocation."""
    def exact(n):
        data = bytearray(n)
        view = memoryview(data)
        used = 0
        while used < n:
            count = conn.recv_into(view[used:])
            if not count:
                raise ConnectionError("렌더러 연결이 끊겼습니다.")
            used += count
        return data

    (length,) = struct.unpack("<I", exact(4))
    if not 0 < length <= MAX_JSON_BYTES:
        raise ValueError("렌더 요청 크기 제한을 초과했습니다.")
    return json.loads(exact(length).decode("utf-8"))


def validate_camera_message(message, mode_count=7):
    """Validate direct SIBR clients too; the HTTP API is not the sole CUDA boundary.

    The zero-size SIBR heartbeat needs no camera. Valid packets retain their exact
    wire representation; no camera, model or rendering algorithm is transformed.
    """
    if not isinstance(message, dict):
        raise ValueError("카메라 요청 형식이 올바르지 않습니다.")
    dims = [message.get(k) for k in ("resolution_x", "resolution_y")]
    if any(type(n) is not int or not 0 <= n <= MAX_FRAME_SIDE for n in dims):
        raise ValueError("렌더 해상도는 0~4096 범위의 정수여야 합니다.")
    if 0 in dims:
        if dims != [0, 0]:
            raise ValueError("렌더 해상도의 가로와 세로를 함께 지정하세요.")
        return message

    def finite(value):
        # Native camera tensors use float32; reject finite Python floats that
        # would become infinity when converted by the original renderer.
        return type(value) in (int, float) and -MAX_CAMERA_VALUE <= value <= MAX_CAMERA_VALUE and math.isfinite(value)

    for name in ("view_matrix", "view_projection_matrix"):
        values = message.get(name)
        if not isinstance(values, list) or len(values) != 16 or not all(finite(v) for v in values):
            raise ValueError("카메라 행렬은 유한한 값 16개여야 합니다.")
    for name in ("fov_x", "fov_y"):
        value = message.get(name)
        if not finite(value) or not 0 < value < math.pi:
            raise ValueError("카메라 시야각이 올바르지 않습니다.")
    near, far = message.get("z_near"), message.get("z_far")
    if not finite(near) or not finite(far) or not 0 < near < far:
        raise ValueError("카메라 원거리 절단면은 근거리 절단면보다 커야 합니다.")
    scaling = message.get("scaling_modifier", 1.0)
    mode = message.get("render_mode", 0)
    if not finite(scaling) or not 0 <= scaling <= 10:
        raise ValueError("렌더 크기 배율이 올바르지 않습니다.")
    if type(mode) is not int or not 0 <= mode < mode_count:
        raise ValueError("지원하지 않는 렌더 모드입니다.")
    return message


def perspective(fovy: float, aspect: float, znear: float, zfar: float) -> np.ndarray:
    """Standard OpenGL projection (what sibr::Camera::proj() returns)."""
    f = 1.0 / math.tan(fovy / 2)
    p = np.zeros((4, 4))
    p[0, 0] = f / aspect
    p[1, 1] = f
    p[2, 2] = (zfar + znear) / (znear - zfar)
    p[2, 3] = 2 * zfar * znear / (znear - zfar)
    p[3, 2] = -1.0
    return p


def gl_view_from_colmap(w2c: np.ndarray) -> np.ndarray:
    """COLMAP/OpenCV world→camera (x right, y down, z forward) → OpenGL view matrix."""
    return np.diag([1.0, -1.0, -1.0, 1.0]) @ w2c


def camera_message(view: np.ndarray, width: int, height: int, fovy: float, znear: float, zfar: float,
                   render_mode: int = 0, scaling_modifier: float = 1.0) -> dict:
    aspect = width / max(height, 1)
    proj = perspective(fovy, aspect, znear, zfar)
    fovx = 2 * math.atan(math.tan(fovy * 0.5) * aspect)
    col = lambda m: [float(x) for x in np.asarray(m, dtype=np.float64).T.reshape(-1)]  # noqa: E731
    return {
        "train": 0,
        "scaling_modifier": float(scaling_modifier),
        "resolution_x": int(width),
        "resolution_y": int(height),
        "fov_y": float(fovy),
        "fov_x": float(fovx),
        "z_far": float(zfar),
        "z_near": float(znear),
        "keep_alive": 1,
        "view_matrix": col(view),
        "view_projection_matrix": col(proj @ view),
        "render_mode": int(render_mode),
    }


class RemoteRendererClient:
    """Blocking socket client; one request → one frame. Not thread-safe (use one per session)."""

    def __init__(self, host: str, port: int, timeout: float = 30.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.render_items: list[str] = self._read_json()
        except BaseException:
            self.close()
            raise

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray(n)
        view = memoryview(buf)
        got = 0
        while got < n:
            k = self.sock.recv_into(view[got:], n - got)
            if not k:
                raise ConnectionError("렌더러 연결이 끊겼습니다.")
            got += k
        return bytes(buf)

    def _read_json(self):
        return receive_json(self.sock)

    def request(self, message: dict) -> tuple[bytes | None, str, dict]:
        data = json.dumps(message).encode("utf-8")
        self.sock.sendall(struct.pack("<I", len(data)) + data)
        w, h = message["resolution_x"], message["resolution_y"]
        rgb = self._read_exact(w * h * 3) if w and h else None
        (n,) = struct.unpack("<I", self._read_exact(4))
        scene = self._read_exact(n).decode("ascii", "replace")
        metrics = self._read_json()
        return rgb, scene, metrics

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
