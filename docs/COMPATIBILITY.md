# Verified upstream facts, unknowns, compatibility gates

> Checked against the remote repositories on 2026-10-15. **Re-inspect the exact local checkout** and record commit SHAs before adapting anything. Repository code may move; statements below describe the inspected versions and not the workstation.

## Primary sources

- Object-Aware Loss source: https://github.com/WooSungHyun03/object-aware-loss
- Publication: https://www.mdpi.com/2227-7390/14/17/3221
- SAM3 official source: https://github.com/facebookresearch/sam3
- SAM 3.1 release notes: https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md
- SAM image+video examples: https://github.com/facebookresearch/sam3/tree/main/examples
- COLMAP docs: https://colmap.github.io/format.html and https://colmap.github.io/tutorial.html

## Object-Aware — observed repository contracts

- `README.md`: expected scene is `<scene>/images`, `<scene>/mask` and `<scene>/sparse/0`; object white, background black; alpha channel fallback supported. CLI `python train.py -s <scene> -m <output>` and `python render.py -s <scene> -m <output>`.
- `environment.yml`: `python=3.10`, `pytorch=2.5.1`, `pytorch-cuda=11.8`, `torchvision=0.20.1`, `numpy==1.24.4`, `open3d==0.18.0`, and editable native extensions in `submodules/`.
- `utils/camera_utils.py`: for normal COLMAP images, the loader matches images and masks by **stem** in `mask/`, grayscale threshold `>127` and nearest-neighbor resize; if masks are absent and `dataset.require_masks` is true, training raises `FileNotFoundError`. `--resolution -1` can automatically downsize wide images to 1600px. Therefore masks must align to **undistorted training photos**, and filenames must be unambiguous.
- `scene/dataset_readers.py`: requires supported undistorted PINHOLE / SIMPLE_PINHOLE camera model; `sparse/0/images.bin` (or txt) defines registered cameras. COLMAP distortion must be handled before training.
- `arguments/__init__.py`: iterations 30,000; alpha polarization weight 0.1; ObjectMark polarization weight 1.0; ObjectMark pruning start 2500, interval 500, threshold 0.5. Training sets mask required in `train.py`.
- `render.py`: `GaussianExtractor` + Open3D TSDF mesh, `fuse.ply`, `fuse_post.ply`; `--skip_train --skip_test`, `--mesh_res`, `--num_cluster`, `--unbounded` switches; check valid mesh output rather than assuming success from exit code.
- `convert.py`: COLMAP feature extraction/matching/mapper/undistorter logic exists but uses shell-string `os.system`; execute equivalent commands via safe subprocess argument lists, retaining semantics.
- `train.py`, `render.py`, `scene/cameras.py` contain hardcoded `.cuda()`/`device="cuda"`; selected physical GPU should be provided via per-job `CUDA_VISIBLE_DEVICES`, with verification inside worker and on GPU. Avoid changing the method accidentally.
- License: inherited Gaussian-Splatting License restricts rights to **noncommercial research and evaluation**; verify redistribution conditions before packaging.

## SAM 3.1 — observed release / incompatibility

- Official **SAM 3.1** released 2026-03-27 with Object Multiplex and new model checkpoints (not just SAM3 old checkpoint with a filename change). See `RELEASE_SAM3p1.md`.
- Official README installation currently documents Python >=3.12, PyTorch >=2.7, CUDA >=12.6; example uses Torch 2.10 wheel. Source `pyproject.toml` metadata says `requires-python >=3.8`; **that metadata is not a runtime compatibility proof**. Trust inference tests over packaging markers.
- Official SAM 3.1 notebook `examples/sam3.1_video_predictor_example.ipynb` demonstrates multiplex video tracking and point prompting. Check its exact current function names, request schema and checkpoint loader, including `build_sam3_multiplex_video_predictor`. Do not blindly copy SAM 3.0 sample calls.
- SAM upstream has documented multiplex bugs/changes in 2026; first reproduce minimal image click inference and short propagation, disable unsupported accelerators, then write a tight compatibility patch with regression tests. Upstream APIs may change.

## Required ONE-environment compatibility decision (hard gate)

User preference: **Object-Aware's Python / PyTorch / CUDA runtime remains the primary environment, and SAM code is adapted into it**. Do not install SAM3.1's recommended newer Torch into the Object-Aware runtime and hope native GS extensions still work. Do not auto-switch to two conda environments or another segmentation model.

1. Inspect actual OS, driver, CUDA driver capability, `nvcc`, GPU compute capability, conda env, Torch version / `torch.version.cuda`, compiled GS rasterizers, checkpoint file list/type/size/hash and weight keys (safe loading, no untrusted pickle execution). Check disk and permissions.
2. Reproduce **original Object-Aware** native import/render/training mini-smoke on its intended environment **before** SAM patching.
3. On same pinned runtime, load **actual SAM 3.1** weights; run positive click + negative click on an image, inspect output logits/mask, propagate between at least 3 contiguous views with upstream's proper API. Do not bypass missing kernels with random placeholder tensors.
4. For any incompatibility, document exact traceback, library API mismatch and smallest source-level/local-vendor fix. First disable optional FlashAttention3, `torch.compile`, Triton-specific fast paths if not essential; fall back to equivalent mathematically faithful kernels only when proven by a numerical/visual regression. Pin local SAM source SHA, maintain patches in a documented patch/vendor directory rather than editing files in installed site-packages without source control.
5. Re-run original GS smoke **after** SAM compatibility changes. Prove both SAM and Object-Aware import/use CUDA **in the same environment and target GPU**, sequentially without leak/VRAM conflict. Save log in `docs/STATUS.md`.
6. If impossible after adequate evidence, mark **BLOCKED: incompatible runtimes**, document blockers/strategies and preserve functioning upstream; do not fabricate working end-to-end capability or silently violate the environment policy. Ask for an explicit decision on a fallback only then.

## SAM 3.1 checkpoint inventory checklist

- [x] Source and exact git SHA recorded
- [x] Files under `/home/m4ml/Desktop/Object-Aware/models/sam3.1` enumerated
- [x] Checkpoint names + SHA256 and tensor layouts identified, safe file metadata inspection
- [x] Verified SAM 3.1 vs SAM 3 checkpoint identity
- [x] Official initializer and inferred supported checkpoint combination used
- [x] Positive and negative clicks both produce non-empty genuine masks
- [x] 3+ view propagation produces per-frame masks with stable ID metadata
- [x] No runtime replacement silently made

## Licensing and provenance

Preserve upstream LICENSE/NOTICE texts, mention noncommercial GS conditions, SAM3 license and checkpoint terms, plus license attributions for frontend/mesh libraries. Avoid downloading gated checkpoints automatically or embedding restricted weights into distributable packages. Do not commit local checkpoint files or sample image datasets.

## Actual local verification — 2026-10-15

The initial remote facts above have now been checked locally. See `SOURCES.json` for exact source/checkpoint/patch identities and `STATUS.md` for append-only experiments. Verified runtime is private `.runtime`: Python3.10.22, Torch2.5.1+cu118, torchvision0.20.1+cu118, NumPy1.24.4, CUDA11.8.89 compiler/GCC11; RTX4080 16GB, driver580.173.02. COLMAP3.9.1 is CPU-only and genuine CPU SfM succeeds.

Both original CUDA extensions compile/import and perform actual original renderer forward/backward. Official SAM3.1 merged checkpoint matches all1623 final model keys/shapes and produces real +/− and3-/16-frame masks. Three minimal retained patches fix session argument dispatch, uncached first-point output merging and tested NumPy metadata; optional FA3/compile are disabled via official switches. No alternative segmentation model, second GPU runtime or Torch upgrade was used.

Unchanged original train.py completed default30K; unchanged render.py completed default1024 TSDF. Fresh private reinstall reproduced source builds, native GPU smoke, SAM click/propagation and original100 training. Trusted self-generated original checkpoint100→110 resume passed; arbitrary external pickles are not accepted through the GUI.

This proves the exercised paths on this host, not every SAM training/text feature, other compute capabilities/drivers or arbitrary-view accuracy. A backup environment is retained solely as a cold-install rollback artifact, not as a divergent production backend.
