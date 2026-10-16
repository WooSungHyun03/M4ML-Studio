"""Live renderer process for a trained Object-Aware 2DGS model (GPU runtime).

Speaks the 2DGS / Gaussian-Splatting-Monitor remote-viewer protocol of
``gaussian_renderer/network_gui.py`` byte for byte, so both the M4ML editor viewport
(``studio.gaussian_protocol``) and ``SIBR_remoteGaussian_app`` can connect to it.

Differences from the original ``view.py`` (which it otherwise mirrors) are operational only:

* loads the Gaussians with the original ``GaussianModel.load_ply`` instead of building a
  ``Scene`` (no training images are read onto the GPU, nothing is written to the model);
* blocking ``accept`` instead of a 100 % CPU spin, a thread per client, renders serialised
  by one lock, and a disconnect no longer kills the process (``view.py`` raises);
* one extra render item, ``ObjectMark``, taken from the original renderer's own
  ``render(..., need_objectmark=True)["rend_object_mark"]`` output;
* exits when its owner (the M4ML backend) dies or closes stdin.

Rendering itself is the unchanged original ``gaussian_renderer.render`` +
``utils.image_utils.render_net_image`` (CUDA ``diff_surfel_rasterization``).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio.gaussian_protocol import receive_json, validate_camera_message

EXTRA_ITEMS = ["ObjectMark"]


def _say(**payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _owner_watch():
    pid, start = os.environ.get("STUDIO_OWNER_PID"), os.environ.get("STUDIO_OWNER_START")

    def stdin_eof():
        try:
            while sys.stdin.readline():
                pass
        finally:
            os._exit(0)

    threading.Thread(target=stdin_eof, daemon=True).start()
    if not pid:
        return

    def loop():
        while True:
            time.sleep(1)
            try:
                if Path(f"/proc/{pid}/stat").read_text().split()[21] != start:
                    os._exit(0)
            except (OSError, IndexError):
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


def read_cfg(model: Path) -> dict:
    """``cfg_args`` written by train.py (a ``Namespace(...)`` repr); only literals are read."""
    try:
        text = (model / "cfg_args").read_text()
        node = ast.parse(text, mode="eval").body
        return {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
    except (OSError, SyntaxError, ValueError, AttributeError):
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("loopback only")
    _owner_watch()
    t0 = time.monotonic()
    try:
        import torch
        from arguments import ModelParams, PipelineParams
        from gaussian_renderer import render
        from scene import GaussianModel
        from scene.cameras import MiniCam
        from utils.image_utils import render_net_image, colormap

        model = Path(args.model)
        ply = model / "point_cloud" / f"iteration_{args.iteration}" / "point_cloud.ply"
        if not ply.is_file():
            raise FileNotFoundError(f"학습 결과 파일이 없습니다: iteration_{args.iteration}")
        cfg = read_cfg(model)
        parser = argparse.ArgumentParser()
        lp, pp = ModelParams(parser), PipelineParams(parser)
        defaults = parser.parse_args([])
        pipe = pp.extract(defaults)
        render_items = list(lp.extract(defaults).render_items) + EXTRA_ITEMS
        white = bool(cfg.get("white_background", False))
        gaussians = GaussianModel(int(cfg.get("sh_degree", 3)))
        gaussians.load_ply(str(ply))
        background = torch.tensor([1, 1, 1] if white else [0, 0, 0], dtype=torch.float32, device="cuda")
        torch.cuda.synchronize()
    except Exception as exc:  # reported to the backend, which shows a Korean message
        _say(ready=False, error=str(exc), oom="out of memory" in str(exc).lower())
        return 1

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(4)
    port = listener.getsockname()[1]
    count = int(gaussians.get_opacity.shape[0])
    gpu_lock = threading.Lock()
    client_slots = threading.BoundedSemaphore(4)
    verify = str(args.source)

    def send_json(conn, data):
        raw = json.dumps(data).encode("utf-8")
        conn.sendall(struct.pack("<I", len(raw)) + raw)

    def frame(message):
        """Same camera conversion as network_gui.receive(), then the original renderer."""
        width, height = message["resolution_x"], message["resolution_y"]
        if not (width and height):
            return None, 0.0
        view = torch.reshape(torch.tensor(message["view_matrix"]), (4, 4)).cuda()
        view[:, 1] = -view[:, 1]
        view[:, 2] = -view[:, 2]
        proj = torch.reshape(torch.tensor(message["view_projection_matrix"]), (4, 4)).cuda()
        proj[:, 1] = -proj[:, 1]
        cam = MiniCam(width, height, message["fov_y"], message["fov_x"], message["z_near"], message["z_far"], view, proj)
        mode = int(message.get("render_mode", 0))
        item = render_items[mode] if 0 <= mode < len(render_items) else "RGB"
        scaling = float(message.get("scaling_modifier", 1.0))
        with gpu_lock, torch.no_grad():
            start = time.perf_counter()
            if item == "ObjectMark":
                pkg = render(cam, gaussians, pipe, background, scaling, need_objectmark=True)
                image = colormap(pkg["rend_object_mark"])
            else:
                pkg = render(cam, gaussians, pipe, background, scaling)
                image = render_net_image(pkg, render_items, mode, cam)
            data = (torch.clamp(image, 0, 1.0) * 255).byte().permute(1, 2, 0).contiguous().cpu().numpy()
            return memoryview(data), (time.perf_counter() - start) * 1000

    def serve(conn):
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(300)  # same default as the API's idle renderer lifetime
            send_json(conn, render_items)
            while True:
                message = validate_camera_message(receive_json(conn), len(render_items))
                image, ms = frame(message)
                if image is not None:
                    conn.sendall(image)
                conn.sendall(struct.pack("<I", len(verify)) + verify.encode("ascii", "replace"))
                send_json(conn, {"#": count, "render ms": round(ms, 2)})
        except (ConnectionError, OSError, ValueError, KeyError):
            pass
        except Exception as exc:  # keep serving other clients; report once
            _say(event="render_error", error=str(exc), oom="out of memory" in str(exc).lower())
        finally:
            conn.close()
            client_slots.release()

    _say(ready=True, port=port, gaussians=count, render_items=render_items, iteration=args.iteration,
         load_seconds=round(time.monotonic() - t0, 2), vram_mb=round(torch.cuda.memory_allocated() / 2**20))
    while True:
        conn, _ = listener.accept()
        if not client_slots.acquire(blocking=False):
            conn.close()
            continue
        threading.Thread(target=serve, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
