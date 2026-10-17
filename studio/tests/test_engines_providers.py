"""CPU-only tests for engine configuration, provider contracts and live latest-wins.

These do NOT prove GPU inference; real GPU checks are scripts/e2e_gpu.py,
scripts/verify_gpu_colmap.py and scripts/v1_gpu_qa.py (run on a GPU workstation).
"""

import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest import mock


def fake_colmap(directory: Path, help_text: str, banner: str):
    path = directory / "colmap"
    path.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = help ]; then echo '{banner}' >&2; exit 0; fi\n"
        f"echo '{help_text}' >&2\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class ConfigMigration(unittest.TestCase):
    def test_v1_checkpoint_moves_into_engines_and_backup_is_kept(self):
        from studio import config

        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            path = config.config_path()
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"checkpoint": "/models/a.pt", "other": 1}))
            data = config.settings()
            self.assertEqual(data["schema_version"], config.SETTINGS_SCHEMA)
            self.assertEqual(data["engines"]["segmentation"]["options"]["checkpoint"], "/models/a.pt")
            self.assertEqual(data["other"], 1)
            self.assertTrue(path.with_name("settings.v1.json").is_file())
            self.assertEqual(json.loads(path.with_name("settings.v1.json").read_text())["checkpoint"], "/models/a.pt")

    def test_save_settings_deep_merges(self):
        from studio import config

        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            config.save_settings({"engines": {"camera": {"options": {"use_gpu": False}}}})
            config.save_settings({"engines": {"camera": {"options": {"num_threads": 2}}}})
            opts = config.settings()["engines"]["camera"]["options"]
            self.assertEqual(opts, {"use_gpu": False, "num_threads": 2})


class Registry(unittest.TestCase):
    def test_alternative_providers_use_existing_capability_contract_without_ui_change(self):
        from studio import engines
        from studio.providers.base import SegmentationProvider, ExportProvider

        class ContractSegmentation(SegmentationProvider):
            key = "contract_only"

            def session_command(self):
                return ["contract-test-session"]

        class ContractExport(ExportProvider):
            key = "contract_export"

            def validate_and_preview(self, mesh, output=None):
                return {"path": str(mesh), "output": str(output), "fixture": True}

        classes = engines.registry()
        classes["segmentation"][ContractSegmentation.key] = ContractSegmentation
        classes["export"][ContractExport.key] = ContractExport
        cfg = engines._merge(engines.DEFAULTS, {
            "segmentation": {"provider": ContractSegmentation.key, "options": {"sentinel": 7}},
            "export": {"provider": ContractExport.key},
        })
        with mock.patch.object(engines, "registry", return_value=classes), mock.patch.object(engines, "config", return_value=cfg):
            segmentation, exporter = engines.provider("segmentation"), engines.provider("export")
            self.assertEqual(segmentation.options["sentinel"], 7)
            self.assertEqual(segmentation.session_command(), ["contract-test-session"])
            self.assertFalse(exporter.requires_gpu({}))
            self.assertTrue(exporter.validate_and_preview(Path("fixture.ply"))["fixture"])

    def test_every_capability_resolves_to_a_provider(self):
        from studio import engines

        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            for cap, base in (("camera", "CameraProvider"), ("segmentation", "SegmentationProvider"),
                              ("training", "TrainingProvider"), ("mesh", "MeshProvider"), ("export", "ExportProvider")):
                p = engines.provider(cap)
                self.assertEqual(p.capability, cap)
                self.assertIn(base, [c.__name__ for c in type(p).__mro__])

    def test_unknown_engine_is_a_clear_error(self):
        from studio import config, engines

        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            config.save_settings({"engines": {"training": {"provider": "does-not-exist"}}})
            with self.assertRaisesRegex(ValueError, "처리 엔진"):
                engines.provider("training")


class ColmapOptions(unittest.TestCase):
    def test_option_names_come_from_the_binary_not_guesses(self):
        from studio import engines

        with tempfile.TemporaryDirectory() as d:
            new = fake_colmap(Path(d), "--FeatureExtraction.use_gpu arg (=1)\\n--FeatureExtraction.gpu_index arg", "COLMAP 4.2.1 (Commit abc with CUDA)")
            self.assertEqual(engines.pick_option(new, "feature_extractor", "FeatureExtraction.use_gpu", "SiftExtraction.use_gpu"), "--FeatureExtraction.use_gpu")
        with tempfile.TemporaryDirectory() as d:
            old = fake_colmap(Path(d), "--SiftExtraction.use_gpu arg (=1)", "COLMAP 3.9.1 (Commit Unknown without CUDA)")
            self.assertEqual(engines.pick_option(old, "feature_extractor", "FeatureExtraction.use_gpu", "SiftExtraction.use_gpu"), "--SiftExtraction.use_gpu")
            probe = engines._probe(str(old), old.stat().st_mtime)
            self.assertEqual(probe["version"], "3.9.1")
            self.assertFalse(probe["cuda"])

    def test_gpu_switch_missing_fails_loudly(self):
        from studio.providers.camera_colmap import ColmapCameraProvider

        with tempfile.TemporaryDirectory() as d:
            binary = fake_colmap(Path(d), "--something_else arg", "COLMAP 9.9 (with CUDA)")
            with self.assertRaisesRegex(RuntimeError, "GPU/CPU"):
                ColmapCameraProvider()._feature_args(binary, True, 4)

    def test_cpu_fallback_requires_explicit_confirmation(self):
        from studio.providers.camera_colmap import ColmapCameraProvider

        with self.assertRaisesRegex(ValueError, "확인"):
            ColmapCameraProvider()._plan({"cpu_fallback": True})

    def test_bundled_build_preferred_over_path(self):
        from studio import engines

        with tempfile.TemporaryDirectory() as d:
            system = fake_colmap(Path(d), "", "COLMAP 3.9.1 (Commit Unknown without CUDA)")
            with mock.patch("shutil.which", return_value=str(system)), mock.patch.object(engines, "ROOT", Path(d) / "nope"), \
                    mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
                path, probe, origin = engines.colmap_binary()
                self.assertEqual(origin, "system")
                with self.assertRaisesRegex(RuntimeError, "GPU"):
                    engines.colmap_binary(require_cuda=True)


class TrainingProvider(unittest.TestCase):
    def test_progress_parsing_matches_trainer_output(self):
        from studio.providers.training_object_aware import ObjectAwareTrainingProvider

        line = "Training progress:  61%|######| 18400/30000 [14:52<09:20, 20.6it/s, Loss=0.01808, distort=0.00000, normal=0.04180, Points=437838]"
        p = ObjectAwareTrainingProvider().parse_progress(line)
        self.assertEqual((p.iteration, p.total), (18400, 30000))
        self.assertAlmostEqual(p.loss, 0.01808)

    def test_checkpoint_listing(self):
        from studio.providers.training_object_aware import list_checkpoints

        with tempfile.TemporaryDirectory() as d:
            for n in (2500, 5000, 30000):
                Path(d, f"chkpnt{n}.pth").write_bytes(b"x")
            Path(d, "chkpntX.pth").write_bytes(b"x")
            self.assertEqual(list_checkpoints(Path(d)), [2500, 5000, 30000])

    def test_resume_needs_existing_checkpoint(self):
        from studio.providers.training_object_aware import ObjectAwareTrainingProvider

        class Ctx:
            def python(self, *a, **k):
                raise AssertionError("must not start training")

        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "저장 지점"):
                ObjectAwareTrainingProvider().train(Ctx(), Path(d), Path(d), {"iterations": 1000, "resume_iteration": 500})


class LiveLatestWins(unittest.TestCase):
    def test_only_the_newest_revision_is_published(self):
        from studio import live_prompt
        from studio.store import Store

        class FakeSession:
            def predict(self, image, points, labels, output):
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_bytes(b"png")
                return {"ok": True, "result": {"seconds": 0.1, "area": 1, "coverage": 0.1}}

        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            pid = store.create("t")["id"]
            store.update(pid, lambda doc: doc.update(live_prompt={"session_id": "s", "reference": "a.png", "prompt_revision": 3,
                                                                  "points": [[1, 1]], "labels": [1], "status": "pending"}))
            stale = {"session_id": "s", "reference": "a.png", "prompt_revision": 2, "points": [[1, 1]], "labels": [1]}
            fresh = dict(stale, prompt_revision=3)
            prepare = lambda project_id, request: (Path(d) / "a.png", "GPU-0")  # noqa: E731
            with mock.patch("studio.segmentation_session.get", return_value=FakeSession()):
                self.assertFalse(live_prompt.run_live(store, pid, stale, prepare))
                self.assertNotIn("preview", store.get(pid))
                self.assertTrue(live_prompt.run_live(store, pid, fresh, prepare))
            doc = store.get(pid)
            self.assertEqual(doc["preview"]["prompt_revision"], 3)
            self.assertEqual(doc["live_prompt"]["status"], "ready")


class SessionRelease(unittest.TestCase):
    def test_release_cancels_a_session_that_is_still_starting(self):
        from studio import segmentation_session as ss

        started = threading.Event()
        closed = []

        class Slow:
            def __init__(self, device, log, idle):
                started.set()
                threading.Event().wait(0.3)
                self.info = {}

            def close(self):
                closed.append(True)

            def alive(self):
                return True

        with mock.patch.object(ss, "_Session", Slow):
            result = {}
            t = threading.Thread(target=lambda: result.setdefault("r", self._get(ss)))
            t.start()
            started.wait(2)
            ss.release("GPU-X")
            t.join(5)
        self.assertIsInstance(result["r"], ss.SessionError)
        self.assertEqual(closed, [True])
        self.assertNotIn("GPU-X", ss._sessions)

    @staticmethod
    def _get(ss):
        try:
            return ss.get("GPU-X", Path(tempfile.gettempdir()) / "x.log")
        except ss.SessionError as exc:
            return exc


if __name__ == "__main__":
    unittest.main()

class PersistentFailureRecovery(unittest.TestCase):
    def test_oom_reason_is_current_launch_only_and_dead_lock_is_released(self):
        from studio import segmentation_session as sessions
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'session.log'
            log.write_text('torch.OutOfMemoryError: CUDA out of memory\n')
            previous = log.stat().st_size
            self.assertIn('GPU 메모리', sessions.failure_description('engine exited', log))
            self.assertEqual(sessions.failure_description('new engine exited', log, previous), 'new engine exited')
            dead = mock.Mock(); dead.alive.return_value = False
            replacement = mock.Mock()
            def construct(*args):
                dead.close.assert_called_once()
                return replacement
            with mock.patch.dict(sessions._sessions, {'test-gpu': dead}, clear=True), mock.patch.dict(sessions._starting, {}, clear=True), mock.patch.object(sessions, '_Session', side_effect=construct), mock.patch.object(sessions, '_ensure_reaper'):
                self.assertIs(sessions.get('test-gpu', log), replacement)
