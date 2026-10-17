"""Camera reconstruction provider backed by a (bundled, CUDA-enabled) COLMAP binary.

GPU vs CPU per step (COLMAP 4.x):
  feature extraction  : GPU (SiftGPU/CUDA) when use_gpu=1
  feature matching    : GPU (SiftGPU/CUDA) when use_gpu=1
  mapper (SfM + BA)   : CPU (Ceres) — COLMAP has no GPU incremental mapper
  image undistortion  : CPU
GPU use is not inferred from flags: while a GPU step runs, the provider samples
``nvidia-smi --query-compute-apps`` and records whether the COLMAP process actually
held GPU memory (``engine.steps[*].gpu_observed``).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import threading

from studio import colmap as colmap_io
from studio import engines
from studio.doctor import atomic_json
from studio.providers.base import CameraProvider


class _GpuWatcher:
    """Sample compute apps on the visible GPU; remember peak memory of COLMAP processes."""

    def __init__(self, binary: Path):
        self.binary = str(binary.resolve())
        self.peak_mb = 0
        self.samples = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.wait(0.5):
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                ).stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
            for line in out.splitlines():
                try:
                    pid, used = (int(v) for v in line.split(","))
                    exe = Path(f"/proc/{pid}/exe").resolve()
                except (ValueError, OSError):
                    continue
                if str(exe) == self.binary:
                    self.samples += 1
                    self.peak_mb = max(self.peak_mb, used)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=6)


class ColmapCameraProvider(CameraProvider):
    key = "colmap"
    display_name = "COLMAP"

    # ------------------------------------------------------------------ discovery
    def binary(self, require_cuda=False):
        return engines.colmap_binary(self.options.get("binary"), require_cuda=require_cuda)

    def info(self):
        base = super().info()
        try:
            path, probe, origin = self.binary()
            build = engines.read_build_info(path) or {}
            base.update(
                version=probe.get("version"),
                commit=build.get("commit") or probe.get("commit"),
                cuda=probe.get("cuda"),
                origin=origin,
                path=str(path),
                cuda_architectures=build.get("cuda_architectures"),
                cuda_toolkit=build.get("cuda_toolkit"),
                build_profile=build.get("profile"),
                license="BSD-3-Clause",
                source="https://github.com/colmap/colmap",
                gpu_steps=["특징점 추출", "특징점 매칭"],
                cpu_steps=["카메라 자세 추정(Mapper)", "왜곡 보정"],
            )
        except RuntimeError as exc:
            base["error"] = str(exc)
        return base

    def requires_gpu(self, request):
        return bool(
            request.get("parameters", {}).get(
                "use_gpu", self.options.get("use_gpu", True)
            )
        ) and not request.get("cpu_fallback")

    def validate_scene(self, scene):
        return colmap_io.validate_scene(scene)

    # ------------------------------------------------------------------ pipeline
    def _plan(self, request):
        use_gpu = bool(
            request.get("parameters", {}).get(
                "use_gpu", self.options.get("use_gpu", True)
            )
        ) and not request.get("cpu_fallback")
        if (
            request.get("cpu_fallback")
            and not self.options.get("allow_cpu_fallback")
            and not request.get("cpu_fallback_confirmed")
        ):
            raise ValueError("CPU 실행은 사용자 확인 후에만 진행할 수 있습니다.")
        path, probe, origin = self.binary(require_cuda=use_gpu)
        return path, probe, origin, use_gpu

    def _step(self, ctx, binary, argv, name, gpu, lines):
        record = {"step": name, "gpu_requested": gpu}
        if gpu:
            with _GpuWatcher(binary) as watcher:
                ctx.run([binary, *argv], on_line=lines, timeout=7200)
            record.update(gpu_observed=watcher.samples > 0, gpu_peak_mb=watcher.peak_mb)
            if not watcher.samples:
                # Very short runs can finish between samples; the log line is the second witness.
                text = ctx.log.read_text(errors="replace")[-200000:]
                record["gpu_log_evidence"] = bool(re.search(r"(SiftGPU|CUDA|GPU)", text))
        else:
            ctx.run([binary, *argv], on_line=lines, timeout=7200)
        return record

    def _feature_args(self, binary, use_gpu, threads):
        args = []
        gpu = engines.pick_option(binary, "feature_extractor", "FeatureExtraction.use_gpu", "SiftExtraction.use_gpu")
        index = engines.pick_option(binary, "feature_extractor", "FeatureExtraction.gpu_index", "SiftExtraction.gpu_index")
        thr = engines.pick_option(binary, "feature_extractor", "FeatureExtraction.num_threads", "SiftExtraction.num_threads")
        if not gpu:
            raise RuntimeError("카메라 정합 엔진의 GPU/CPU 선택 옵션을 확인할 수 없습니다. 엔진 버전을 확인하세요.")
        args += [gpu, "1" if use_gpu else "0"]
        if index and use_gpu:
            args += [index, "0"]  # CUDA_VISIBLE_DEVICES exposes exactly the selected GPU
        if thr:
            args += [thr, str(threads)]
        return args

    def _matcher_args(self, binary, command, use_gpu, threads):
        args = []
        gpu = engines.pick_option(binary, command, "FeatureMatching.use_gpu", "SiftMatching.use_gpu")
        index = engines.pick_option(binary, command, "FeatureMatching.gpu_index", "SiftMatching.gpu_index")
        thr = engines.pick_option(binary, command, "FeatureMatching.num_threads", "SiftMatching.num_threads")
        if not gpu:
            raise RuntimeError("카메라 정합 엔진의 GPU/CPU 선택 옵션을 확인할 수 없습니다. 엔진 버전을 확인하세요.")
        args += [gpu, "1" if use_gpu else "0"]
        if index and use_gpu:
            args += [index, "0"]
        if thr:
            args += [thr, str(threads)]
        return args

    def reconstruct(self, ctx, images, work, request):
        images, work = Path(images).resolve(), Path(work).resolve()
        matching = request.get("matching", "exhaustive")
        if matching not in {"exhaustive", "sequential"}:
            raise ValueError("지원하지 않는 매칭 방식입니다.")
        binary, probe, origin, use_gpu = self._plan(request)
        import os

        params = request.get("parameters", {})
        threads = int(
            params.get(
                "threads",
                self.options.get("num_threads") or min(os.cpu_count() or 4, 16),
            )
        )

        def options(command, names):
            result = []
            for name in names:
                if name not in params:
                    continue
                flag = engines.pick_option(binary, command, name)
                if not flag:
                    raise ValueError(
                        "현재 COLMAP에서 지원하지 않는 설정입니다: " + name
                    )
                value = params[name]
                result += [flag, str(int(value)) if type(value) is bool else str(value)]
            return result

        work.mkdir(parents=True, exist_ok=False)
        sparse = work / "sparse"
        sparse.mkdir()
        database = work / "database.db"
        steps = []

        def lines(line):
            found = re.search(r"Processed file \[(\d+)/(\d+)\]", line) or re.search(r"Processing image \[(\d+)/(\d+)\]", line)
            if found:
                ctx.progress(f"특징점 추출 {found[1]}/{found[2]}장", int(found[1]), int(found[2]))
            found = re.search(r"Matching block \[(\d+)/(\d+)", line)
            if found:
                ctx.progress(f"사진 쌍 매칭 {found[1]}/{found[2]}", int(found[1]), int(found[2]))
            found = re.search(r"Registering image #\d+ \((\d+)\)", line)
            if found:
                ctx.progress(f"카메라 등록 {found[1]}장째", None, None)

        ctx.progress("사진의 특징점을 추출하고 있습니다.")
        steps.append(
            self._step(
                ctx,
                binary,
                [
                    "feature_extractor",
                    "--database_path",
                    database,
                    "--image_path",
                    images,
                    *self._feature_args(binary, use_gpu, threads),
                    *options(
                        "feature_extractor",
                        [
                            "FeatureExtraction.max_image_size",
                            "ImageReader.camera_model",
                            "ImageReader.single_camera",
                            "SiftExtraction.max_num_features",
                        ],
                    ),
                ],
                "feature_extraction",
                use_gpu,
                lines,
            )
        )
        ctx.progress("사진 쌍의 특징점을 매칭하고 기하 관계를 검증하고 있습니다.")
        command = f"{matching}_matcher"
        steps.append(
            self._step(
                ctx,
                binary,
                [
                    command,
                    "--database_path",
                    database,
                    *self._matcher_args(binary, command, use_gpu, threads),
                    *options(command, ["TwoViewGeometry.max_error"]),
                ],
                "feature_matching",
                use_gpu,
                lines,
            )
        )
        ctx.progress("카메라 위치를 등록하고 재구성 그룹을 찾고 있습니다.")
        mapper_threads = engines.pick_option(binary, "mapper", "Mapper.num_threads")
        steps.append(
            self._step(
                ctx,
                binary,
                [
                    "mapper",
                    "--database_path",
                    database,
                    "--image_path",
                    images,
                    "--output_path",
                    sparse,
                    *([mapper_threads, str(threads)] if mapper_threads else []),
                    *options(
                        "mapper",
                        [
                            "Mapper.min_num_matches",
                            "Mapper.ba_refine_focal_length",
                            "Mapper.ba_refine_principal_point",
                        ],
                    ),
                ],
                "mapper",
                False,
                lines,
            )
        )
        components = {}
        for model in sorted(sparse.iterdir()):
            if model.is_dir() and (model / "images.bin").is_file():
                _, poses = colmap_io.read_model(model)
                components[model.name] = {pose.name for pose in poses.values()}
        engine = self._engine_record(binary, probe, origin, use_gpu, steps)
        if not components:
            report = colmap_io.database_report(database, set(), {})
            report["engine"] = engine
            atomic_json(work / "report.json", report)
            raise ValueError(
                "카메라가 등록되지 않았습니다. 서로 충분히 겹치는 사진을 추가하세요."
            )
        selected = request.get("component") or max(
            components, key=lambda key: len(components[key])
        )
        if selected not in components or len(components[selected]) < 2:
            raise ValueError("선택한 재구성 그룹의 등록 사진이 부족합니다.")
        report = colmap_io.database_report(database, components[selected], components)
        report.update(
            selected_component=selected,
            components={k: sorted(v) for k, v in components.items()},
            engine=engine,
        )
        atomic_json(work / "report.json", report)
        ctx.progress("선택한 등록 사진의 렌즈 왜곡을 보정하고 있습니다.")
        steps.append(
            self._undistort(ctx, binary, images, sparse / selected, work / "scene")
        )
        names = colmap_io.validate_scene(work / "scene")
        report = colmap_io.database_report(database, names, components)
        report.update(
            selected_component=selected,
            components={k: sorted(v) for k, v in components.items()},
            engine=self._engine_record(binary, probe, origin, use_gpu, steps),
        )
        atomic_json(work / "report.json", report)
        return report

    def _undistort(self, ctx, binary, images, model, scene):
        record = self._step(ctx, binary, [
            "image_undistorter", "--image_path", images, "--input_path", model,
            "--output_path", scene, "--output_type", "COLMAP",
        ], "undistortion", False, None)
        target = scene / "sparse/0"
        target.mkdir()
        # COLMAP ≥3.12 also writes rigs.bin/frames.bin; the training loader only needs
        # the classic three files, extra files stay beside them untouched.
        for item in list((scene / "sparse").iterdir()):
            if item.is_file():
                shutil.move(item, target / item.name)
        return record

    def _engine_record(self, binary, probe, origin, use_gpu, steps):
        return {
            "name": self.display_name,
            "version": probe.get("version"),
            "cuda_build": probe.get("cuda"),
            "origin": origin,
            "gpu_requested": use_gpu,
            "steps": steps,
        }

    def select_component(self, ctx, images, previous, work, component):
        previous, work = Path(previous), Path(work)
        old = json.loads((previous / "report.json").read_text())
        if component not in old["components"] or len(old["components"][component]) < 2:
            raise ValueError("유효한 재구성 그룹을 선택하세요.")
        binary, probe, origin = self.binary()
        work.mkdir(parents=True, exist_ok=False)
        shutil.copytree(previous / "sparse", work / "sparse")
        shutil.copyfile(previous / "database.db", work / "database.db")
        step = self._undistort(ctx, binary, Path(images), work / "sparse" / component, work / "scene")
        names = colmap_io.validate_scene(work / "scene")
        report = colmap_io.database_report(work / "database.db", names, {k: set(v) for k, v in old["components"].items()})
        engine = dict(old.get("engine") or {})
        engine.setdefault("steps", []).append(step)
        report.update(selected_component=component, components=old["components"], engine=engine)
        atomic_json(work / "report.json", report)
        return report
