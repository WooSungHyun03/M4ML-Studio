# Gaussian Viewer Integration (실시간 렌더)

The 3D 모델 workspace now has two views: **실시간 렌더**, which shows the trained 2D Gaussians themselves from a free camera, and **메시**, the existing Colored Mesh Viewer (unchanged). This document records the source, build, integration design, process/GPU policy, measured results and known limits. Everything below was run on Ubuntu 24.04.4 (kernel 7.0), RTX 4080 16 GB, driver 580.173.02, X11 session, in the project's single Python 3.10 / Torch 2.5.1+cu118 runtime.

## 1. What the 2DGS "SIBR viewer" actually is (verified in source)

The 2DGS README points to **Gaussian-Splatting-Monitor**, whose SIBR fork contains `projects/remote` and builds `SIBR_remoteGaussian_app`. The `_rwdi` suffix in `SIBR_remoteGaussian_app_rwdi` is just SIBR's naming for RelWithDebInfo builds; a Release build produces `SIBR_remoteGaussian_app` from the same source.

Reading `src/projects/remote/renderer/RemotePointView.cpp` shows the app is a **remote display client**, not a Gaussian rasterizer:

1. It connects over TCP to a Python process (`view.py` or `train.py`) on port **6009** by default (`network_gui.py`, `RemoteAppArgs.port`).
2. It reads `uint32 length + JSON list` of render items. This handshake is Monitor-specific and is why the plain 3DGS SIBR remote viewer is not compatible with Object-Aware.
3. Every frame it sends `uint32 length + JSON` containing:
   - resolution, `fov_x`/`fov_y`, `z_near`/`z_far`, `train`, `keep_alive`, `scaling_modifier`, `render_mode`;
   - the OpenGL `view_matrix` and `view_projection_matrix` as 16 column-major floats.
4. It receives `W*H*3` raw RGB bytes, `uint32 + ascii` scene path, then `uint32 + JSON` metrics.
5. It uploads the RGB to a GL texture and blits it.

Its only own GL drawing is the SfM point cloud (`PointBasedRenderer`, before the first frame or in "Show Input Points"). **Every Gaussian pixel comes from the Python side:** the original `gaussian_renderer.render` with CUDA `diff_surfel_rasterization`, followed by `utils.image_utils.render_net_image`.

## 2. Integration decision

The three options from the brief:

| Option | Assessment |
|---|---|
| 1. Embed SIBR's rendering core in a Qt viewport | SIBR's core is a GLFW/ImGui OpenGL application, and the remote project has no rendering of its own to embed. A port would duplicate the client while adding nothing to image quality. |
| 2. Native SIBR surface inside Qt | Needs X11 window reparenting (explicitly forbidden, and impossible on Wayland) or a GL-context share between GLFW and QtWebEngine's Chromium compositor (fragile). |
| 3. Keep the renderer as a separate process; connect its real frames and camera control to the in-editor viewport | **Chosen.** |

How option 3 is implemented:
- The editor viewport (`frontend/src/GaussianViewer.tsx`) speaks **the same SIBR remote protocol**, through the backend (`studio/gaussian_protocol.py`).
- It talks to a renderer process that serves exactly what `view.py` serves.
- The real SIBR app is built and bundled as an optional external viewer and **attaches to the same renderer process** (고급 → 외부 뷰어 열기).

Why not stream SIBR's own window? Its window content is the same frame the renderer already sends. Capturing it would add a GL readback plus re-encode on top of the identical image, and would require either reparenting or patching SIBR into a frame server. Nothing about the rendering would improve.

The in-editor viewport does **not** run SIBR code. It reuses SIBR's protocol and camera conventions, and the original Object-Aware renderer that SIBR displays. That is stated here so no one mistakes it for an embedded SIBR window.

The decision is recorded as ADR-021 in `docs/DECISIONS.md`.

## 3. Renderer process (`studio/gaussian_render_server.py`)

The original `view.py` was run unmodified on a real 30K model and connected to both SIBR and the M4ML protocol client. It cannot back an editor viewport, for these verified reasons:

- **It crashes when the client disconnects.** The `raise e` in its loop surfaced as `JSONDecodeError`, and after SIBR closed as `BrokenPipeError`, both with exit 1. Reconnecting and switching modes or projects is therefore impossible.
- **It spins at 100% CPU while idle.** `listener.settimeout(0)` plus `while True: try_connect()`.
- **It builds a full `Scene`**, which reads every training image onto the GPU just to load the Gaussians. With a missing `--iteration`, `Scene` would also write `input.ply` and `cameras.json` into the model folder.
- **It serves one client only.**

The M4ML renderer process keeps the rendering identical and changes only operations:

| | `view.py` | `gaussian_render_server.py` |
|---|---|---|
| Gaussians | `Scene(..., load_iteration)` → `GaussianModel.load_ply` | `GaussianModel.load_ply` directly (same file, same code) |
| Render | `render(...)` + `render_net_image(...)` | same functions, same arguments |
| Camera | `network_gui.receive()` conversion | same conversion (copied byte for byte) |
| Extra mode | — | `ObjectMark` = original `render(..., need_objectmark=True)["rend_object_mark"]`, turbo colormap (the same `colormap` `render_net_image` uses) |
| Clients | one, crash on disconnect | thread per client, renders serialized by a lock, survives disconnect |
| Idle CPU | 100% spin | blocking `accept` |
| Model folder | written when iteration missing | never written (verified: SHA256 of all model files unchanged) |
| Lifetime | manual | exits on stdin EOF or owner (backend) death |

**Pixel-identity proof.** The same camera (training camera 000001) and the same model went through both `view.py` and the renderer process. For RGB, Alpha, Normal, Depth, Edge and Curvature the **maximum absolute pixel difference is 0**. The RGB frame reproduces training photo 000001's viewpoint, with the background pruned by the ObjectMark training (`evidence/gaussian-viewer/03-http-render-modes.png`).

## 4. Data flow

```text
GaussianViewer.tsx (QtWebEngine page)
  three.js PerspectiveCamera + OrbitControls (same controls as the mesh viewer)
  camera.matrixWorldInverse (OpenGL view, column-major) + fovy + viewport size + mode
      │  POST /api/projects/{id}/live-render/frame   (token header, Host/Origin checks)
      │  one request in flight, newest camera wins
FastAPI backend ── studio/live_render.py (session per GPU) ── RenderingProvider
      │  studio/gaussian_protocol.py: camera_message() → SIBR wire format over loopback TCP
gaussian_render_server.py (GPU child) ── original render()/render_net_image() ── RGB bytes
      │  backend: JPEG (camera moving, CSS resolution) / PNG (camera still, device pixels ≤ 4096)
<img> in the viewport (object-fit fill, aspect = requested width/height)
```

Transport was chosen by measurement. PIL (libjpeg-turbo) encodes a 1009×753 JPEG in about 2 ms, against about 12 ms for OpenCV. A plain HTTP request per frame avoids a new WebSocket dependency and reuses the existing token/Origin middleware.

**Camera conventions.** `cameras.json` stores the camera-to-world rotation in COLMAP axes. The viewport starts exactly at training camera 1, with matching fovy and up = −Y_cam. 시점 초기화 / Home returns there, and 화면 맞춤 / F re-targets the orbit centre to the median of the sparse SfM points. A unit test proves that `network_gui.receive()` applied to our message yields the 3DGS `W2C^T` exactly.

## 5. Provider architecture

`studio/providers/base.py::RenderingProvider` (capability `rendering`, configurable in `engines.rendering`) defines these methods:

- `locate_model(root, project, iteration)`: initialize/model lookup. It validates:
  - the PLY header has Gaussian properties (`opacity`, `scale_*`, `rot_*`, `f_dc_*`, `objectmark_score`) and **no `face` element**, so a mesh PLY is rejected;
  - the `cameras.json` image names belong to this project's scene;
  - the path stays inside the project.
  It chooses the latest `point_cloud/iteration_*` by default and returns camera metadata plus the orbit target.
- `server_command(model)`: load_model (GPU child argv).
- `connect(port)`: open the protocol client.
- `render(client, camera)`: update_camera + resize + render in one request.
- `modes(server_items)`: only the outputs the renderer really produces: 색상, 불투명도, 깊이, 법선, 객체 점수. Edge and Curvature are not offered in the UI.
- `external_viewer_command(port, model)`: optional SIBR attach.

Lifecycle is owned by `studio/live_render.py` (get_status, capture via a PNG frame, unload/shutdown via stdin EOF → terminate → kill). `studio/providers/render_gaussian_remote.py` is the only module that knows about SIBR, the protocol or the server script; the UI sees `/live-render` endpoints and Korean mode labels. Replacing the renderer means a new provider class plus a config entry.

## 6. GPU and process policy

- **One renderer per GPU.** It holds the same per-GPU `fcntl` lock as training, mesh and COLMAP jobs and the object-selection session. The lock is shared across app instances, and a second instance reports "GPU 사용 중" (verified).
- **Training/mesh/COLMAP/propagation jobs take priority.** `POST /jobs/*` releases the renderer first (verified: the session became `None` right after a training job started). `/live-render/start` returns 409 while a GPU job runs (verified with a mesh job). The viewport shows "GPU 작업이 실행 중입니다" and reconnects afterwards.
- **Object selection evicts the viewer.** It calls `live_render.release(device)` before taking the GPU. Live start releases a selection session of the same instance, and the lock order is safe.
- **Project/model switch** stops the old renderer before loading the new one (verified: the first project's session is gone and the second renders 92,004 Gaussians).
- **Closing the viewer** (메시 view, another stage, another project) stops the renderer and returns VRAM. A reopen waits for that stop.
- **Idle timeout:** `rendering.options.idle_seconds` (default 300 s) covers a browser tab closed without unmount.
- **Crash safety.** The renderer exits on stdin EOF and watches the backend PID and start time.
  - Backend SIGKILL → renderer gone after **147 ms** (measured).
  - Desktop window close → backend graceful stop (up to uvicorn's 10 s keep-alive window) → renderer gone; VRAM went 5193 → 1873 MiB.
- **Loopback only.** The renderer binds `127.0.0.1` on an OS-assigned port (`--port 0`), never 6009. The protocol has no authentication; it is the original wire format, and any local process of the same user could connect while the renderer runs. HTTP access from the UI goes through the backend's token/Origin checks.
- **States shown to the user:** 준비 중, 불러오는 중, 렌더링 중, 연결 끊김 (with 다시 연결), 메모리 부족 (CUDA OOM detected in renderer output or log), GPU 사용 중, 렌더링 실패. No fake progress is shown; loading shows a status line until the real first frame.

## 7. Building SIBR (`scripts/build_sibr.sh`)

- **Source:** https://github.com/RongLiu-Leo/Gaussian-Splatting-Monitor @ `2b6190c5c1c35b477a70da09dc9b720395ea6293` (2026-01-07). SIBR's extlibs are pinned by commit in its own CMake (imgui `741fb3a`, nativefiledialog `ae2fab7`, mrf `30c3c94`, nanoflann `7a20a9a`, picojson `7cf8fee`, rapidxml `069e87f`, xatlas `0fbe06a`).
- **Patch** `patches/sibr/0001-ubuntu24-embree4-ffmpeg6.patch` (sha256 `e3cf44b1…`) makes it build on Ubuntu 24.04:
  - Embree 3 → 4 API (`rtcIntersect1/8`, `rtcOccluded1/8` without `RTCIntersectContext`; `find_package(embree 4.0)`);
  - FFmpeg ≥ 5 encoder API (`avcodec_alloc_context3`, `avcodec_parameters_from_context`, send/receive; `av_register_all` removed);
  - one structured binding over a `std::vector` that GCC 13 rejects.
  These touch only the raycaster and video-recording utilities, not the remote viewer path.
- **Toolchain:** GCC 13.3, CMake + Ninja, Release, `BUILD_IBR_REMOTE=ON`, `BUILD_IBR_BASIC=ON` (remote links `sibr_basic`). No CUDA is needed for the remote viewer. No sudo; nothing is installed system-wide.
- **Output** `runtime/sibr/` (5.4 MB stripped):
  - `bin/SIBR_remoteGaussian_app` plus SIBR's own `libsibr_*.so` and `libxatlas` (RUNPATH `$ORIGIN`);
  - shaders, resources, `ibr_resources.ini`;
  - licences;
  - `BUILD_INFO.json` (commit, patch hash, per-file SHA256, compiler, OS, system libraries).
- **Not bundled, required from Ubuntu 24.04:** libGL/GLX/OpenGL, GLEW 2.2, GLFW 3, Boost 1.83, OpenCV 4.6 (with its GDAL/Qt5 dependencies), assimp 5, Embree 4, TBB, FFmpeg 6 (libav*60), GTK 3. `ldd` reports **0 missing** on this machine. `python -m studio.live_render --check-external` and Settings › 고급 정보 (`external_viewer_missing_libraries`) report any that are missing. The in-editor viewport does not depend on SIBR at all, so it keeps working if these packages are absent.
- **Packaging:** `scripts/package_release.py` copies `runtime/sibr` only after verifying every bundled file against `BUILD_INFO.json`. `SOURCES.json` records the pin.

Verification of the build:
- SIBR from the source tree connected to the original `view.py`: received the six Object-Aware render items, displayed real Gaussian frames, metric `#: 437838` (`evidence/gaussian-viewer/01-sibr-remote-connected.png`).
- The same SIBR connected to the M4ML renderer process: it lists the extra `ObjectMark` item and the server's `render ms` metric, and the server survived SIBR closing (`02-sibr-connected-to-m4ml-renderer.png`).
- The staged `runtime/sibr` binary launched from the app's 고급 → 외부 뷰어 열기 connected to the running session's renderer and closed together with the session (`08-external-sibr-from-app.png`).

## 8. Test results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | SIBR runs on Ubuntu 24.04 | PASS | 01, 02, 08 |
| 2 | SIBR ↔ Object-Aware `view.py` | PASS | 01, `/tmp` log: `Connected!`, items |
| 3 | Trained 2D Gaussians rendered | PASS; identical to `view.py` (max diff 0) | 03-http-render-modes.png |
| 4 | Gaussians, not mesh | PASS; PLY with Gaussian props, mesh PLY rejected (unit test) | test_live_render |
| 5 | Rotate | PASS (frame hash changes) | e2e/02, desktop/02 |
| 6 | Zoom / pan | PASS | e2e/03, desktop/03 |
| 7 | Immediate response | PASS; 81 frames during a 0.68 s drag (browser), 62 fps sustained (desktop) | result.json |
| 8 | Inside the M4ML viewport | PASS; desktop window, `__M4ML_TOKEN__` present, no browser | desktop/result.json |
| 9 | Resize | PASS; re-render at new aspect (browser 1050×639 → 730×539; desktop panels hidden 1304×650 → 1605×841 CSS) | e2e, desktop/04 |
| 10 | Other project → its model | PASS; 92,004-Gaussian 3K model, previous session stopped | e2e/07 |
| 11 | VRAM freed after renderer stop | PASS; 5.5 GiB peak → 1815 MiB, process gone | perf.jsonl |
| 12 | No processes after app exit | PASS; window close and backend SIGKILL both leave no renderer | §6 |
| 13 | Mesh viewer works | PASS; editor E2E 28/28 incl. 6 mesh modes | editor-e2e |
| 14 | GPU training/export regression | PASS; real 3000-iteration training (58 s) + mesh (6 s), PLY/GLB HTTP 200 | §9 |
| 15 | Dark/light themes | PASS | 09-light-theme-live.png, 10-light-theme-mesh.png |
| 16 | Release package | PASS; 0.5.0 package installed to a scratch XDG home (`--no-setup`, existing runtime), folder opened, renderer ran from the installed folder, frames identical to dev (max diff 0) | installed/ |

Automated suites:
- `python -m unittest discover -s studio/tests`: 76/76 PASS, including 10 new live-render tests (protocol round trip vs. `network_gui`, wire format, model location, mesh rejection, foreign cameras, path escape, API contract).
- `scripts/ui_live_render_e2e.mjs`: 21/21 PASS.
- `scripts/desktop_live_render_qa.mjs` (real desktop window): 9/9 PASS.
- `scripts/ui_editor_e2e.mjs`: 28/28 PASS.

Desktop input note: the first desktop attempt used global XTest pointer events, but the M4ML window was behind another application's window, so the events went to that window (a text selection appeared there). The XTest drag/wheel path was removed. Desktop QA now sends input only to the M4ML page through QtWebEngine DevTools `Input.dispatchMouseEvent`, which goes through Chromium's real input pipeline but cannot reach other windows. The DevTools port is enabled only for that test run, with `QTWEBENGINE_REMOTE_DEBUGGING`.

## 9. Performance (measured)

Model: 437,838 Gaussians, 30K iterations (103.6 MB PLY). RTX 4080.

| Metric | Value |
|---|---|
| Renderer start (model load) | 1.7 s warm; 5.9 s first start of the freshly installed package |
| Click → first frame (UI) | 1.9–2.6 s (browser), 2.0 s (desktop) |
| Render time per frame (server) | RGB 5–9 ms at 1009×753 steady state; 13–19 ms at 2608×1300 |
| HTTP round trip, JPEG | 12.1 ms median 1009×753; 12.1 ms 1280×720 (78 fps sustained); 17.5 ms 1920×1080 (54.5 fps) |
| Still frame PNG (lossless) | 34 ms at 1009×753; ~135–190 ms at 2608×1300 (desktop HiDPI) |
| Desktop sustained drag | 62 fps delivered, 16 ms response (1304×650 CSS frames) |
| CPU during sustained loop | renderer 55–61%, backend 38–48% (of one core) |
| VRAM | 99 MiB allocated after load; renderer process 448 MiB at start, grows with resolution through PyTorch's caching allocator (GPU total peak 3.3 GiB at 720p, 5.5 GiB at 1080p loop) |
| Project switch | 5.3 s to the other project's first frame (stop + load + first frame) |
| After stop | process gone; GPU back to 1815 MiB |

## 10. Troubleshooting

- **"GPU 사용 중" / "다른 GPU 작업이 실행 중":** a training/mesh/COLMAP job, an object-selection session, or another M4ML instance holds the GPU. Wait for the job, or leave the 객체 선택 screen; selection sessions also close after 10 idle minutes.
- **"메모리 부족":** close other GPU programs or make the viewport smaller (frames are rendered at viewport size × devicePixelRatio, capped at 4096).
- **"연결 끊김":** the renderer stopped (idle timeout, a GPU job started, or a crash). Press 다시 연결. Details are in `<project>/logs/live-render.log`.
- **외부 뷰어 button missing:** `runtime/sibr` is not built, or system libraries are missing (Settings › 고급 정보 → 실시간 렌더 → `external_viewer_missing_libraries`). Build with `./scripts/build_sibr.sh`. The in-editor viewport does not need it.

## 11. Licences

- **SIBR core** (Inria, `runtime/sibr/licenses/SIBR-LICENSE.md`) and **Gaussian-Splatting-Monitor** (Inria/GRAPHDECO Gaussian-Splatting licence) are free for **non-commercial research and evaluation only**, like the Object-Aware / 2DGS code the renderer runs.
- SIBR's extlibs carry their own permissive licences.
- The not-bundled Ubuntu libraries keep their distribution licences. FFmpeg and Qt5 are LGPL/GPL depending on the build; they are not redistributed by M4ML.
- Public or commercial redistribution remains **not approved**; see `docs/M4ML_STUDIO_LICENSES.md`. Nothing here changes that.

## 12. Files

- Backend:
  - `studio/gaussian_protocol.py`
  - `studio/gaussian_render_server.py`
  - `studio/live_render.py`
  - `studio/providers/render_gaussian_remote.py`
  - `studio/providers/base.py` (`RenderingProvider`)
  - `studio/engines.py` (`rendering`)
  - `studio/api.py` (`/live-render*`, GPU-job release)
  - `studio/segmentation_session.py` (evicts the viewer)
- Frontend:
  - `frontend/src/GaussianViewer.tsx`
  - `frontend/src/stages/ModelStage.tsx` (실시간 렌더 | 메시 switch, Inspector)
  - `frontend/src/api.ts` (`postBlob`, `LiveError`)
  - `style.css`
  - `SettingsDrawer.tsx` (고급 정보 label)
- Build and packaging: `scripts/build_sibr.sh`, `patches/sibr/`, `SOURCES.json`, `scripts/package_release.py`.
- Tests and QA:
  - `studio/tests/test_live_render.py`
  - `scripts/ui_live_render_e2e.mjs`
  - `scripts/desktop_live_render_qa.mjs`
  - `scripts/x11_input.py` (window-targeted resize only)

## 13. For the follow-up quality harness

Audit targets:
- Every state in §6 and the HTTP contract (`/live-render`, `/start`, `/frame`, `/stop`, `/external`).
- The provider methods in §5.
- The E2E scripts in §8.

Known limits to review:
- Moving frames are JPEG (q85). Still frames are lossless.
- High-DPI still frames take ~150 ms.
- No WebSocket streaming.
- The renderer protocol is unauthenticated on loopback (original format).
- SIBR requires Ubuntu system libraries.
- Only one renderer per GPU.
- Wayland was not tested; the design needs no window embedding, so nothing in it is X11-specific except the optional SIBR window (GLFW).
