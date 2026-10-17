import copy
import unittest
from unittest.mock import patch
import test_state_api as fixtures
from studio.task_settings import (
    argument_defaults,
    bundle,
    effective,
    execution,
    save,
    validate,
)
from studio.providers.base import Provider


class TaskSettingsTests(unittest.TestCase):
    def test_original_defaults_validation_and_provider_namespace(self):
        p = {}
        defaults = argument_defaults()
        self.assertEqual(
            effective(p, "training")["alpha_weight"], defaults["lambda_pa"]
        )
        for bad in [
            {"alpha_weight": True},
            {"alpha_weight": float("nan")},
            {"iterations": 1},
            {"image_resolution": 0},
            {"missing": 1},
        ]:
            with self.assertRaises(ValueError):
                validate("training", bad)
        save(p, "training", {"alpha_weight": 0.37})
        self.assertEqual(effective(p, "training")["alpha_weight"], 0.37)
        self.assertEqual(effective({}, "training")["alpha_weight"], 0.1)

        class Other(Provider):
            key = "other"
            capability = "training"

            def task_settings_schema(self):
                return [
                    dict(
                        id="gain",
                        label="다른 모델",
                        default=2,
                        type="integer",
                        min=1,
                        max=4,
                        native="gain",
                    )
                ]

        with patch("studio.engines.provider", return_value=Other()):
            self.assertEqual(effective(p, "training"), {"gain": 2})
            with self.assertRaises(ValueError):
                validate("training", {"alpha_weight": 0.2})
        self.assertEqual(effective(p, "training")["alpha_weight"], 0.37)

    def test_snapshots_and_legacy_overrides_are_independent(self):
        p = {}
        save(p, "training", {"iterations": 400, "alpha_weight": 0.3})
        save(p, "mesh", {"mesh_res": 128})
        r = execution(p, "train", {"iterations": 30000, "resolution": -1}, set())
        self.assertEqual(r["iterations"], 400)
        self.assertEqual(r["parameters"]["lambda_pa"], 0.3)
        self.assertEqual(r["mesh_request"]["parameters"]["mesh_res"], 128)
        original = copy.deepcopy(r)
        save(p, "training", {})
        self.assertEqual(r, original)
        self.assertEqual(execution(p, "train", {"iterations": 100})["iterations"], 100)

    def test_unknown_version_and_cross_field_validation(self):
        for g, v in [
            ("view", {"far": 1, "near": 2}),
            ("mesh", {"voxel_size": 0}),
            ("camera", {"max_image_size": 0}),
        ]:
            with self.assertRaises(ValueError):
                validate(g, v)
        with self.assertRaises(ValueError):
            effective({"task_settings": {"schema_version": 99}}, "training")


class SettingsAPITests(unittest.TestCase):
    setUp = fixtures.StateAndAPITests.setUp
    tearDown = fixtures.StateAndAPITests.tearDown

    def test_ui_entry_is_not_cached_across_upgrades(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_license_catalog_serves_only_packaged_original_texts(self):
        from studio.config import ROOT
        import json
        entries = json.loads((ROOT / "licenses/catalog.json").read_text())
        for entry in entries:
            response = self.client.get("/api/license-text/" + entry["id"])
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["text"], (ROOT / entry["text"]).read_text(errors="replace"))
        self.assertEqual(self.client.get("/api/license-text/not-a-component").status_code, 404)

    def test_pending_prompt_freezes_segmentation_settings_and_preserves_masks(self):
        fixtures.StateAndAPITests.seed_review(self)
        original = copy.deepcopy(self.store.get(self.id)["masks"])
        self.client.patch(
            self.url + "/task-settings/segmentation",
            headers=self.headers,
            json={"values": {"fill_hole_area": 42}},
        ).raise_for_status()
        self.client.post(
            self.url + "/prompt-session",
            headers=self.headers,
            json={"reference": "000001.png", "session_id": "settings-test"},
        ).raise_for_status()
        with patch("studio.live_prompt.schedule"):
            response = self.client.post(
                self.url + "/prompt",
                headers=self.headers,
                json={
                    "reference": "000001.png",
                    "session_id": "settings-test",
                    "prompt_revision": 1,
                    "points": [[4.0, 4.0]],
                    "labels": [1],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.store.get(self.id)["live_prompt"]["settings_snapshot"]["parameters"][
                "fill_hole_area"
            ],
            42,
        )
        self.assertEqual(
            self.client.patch(
                self.url + "/task-settings/segmentation",
                headers=self.headers,
                json={"values": {}},
            ).status_code,
            409,
        )
        self.assertEqual(self.store.get(self.id)["masks"], original)

    def test_save_restart_reset_active_and_preserve_data(self):
        endpoint = self.url + "/task-settings"
        self.root.joinpath("user.txt").write_text("keep")
        response = self.client.patch(
            endpoint + "/training",
            headers=self.headers,
            json={"values": {"alpha_weight": 0.29}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        from studio.store import Store

        self.assertEqual(
            effective(Store(self.store.root).get(self.id), "training")["alpha_weight"],
            0.29,
        )
        self.assertEqual(
            self.client.patch(
                endpoint + "/training",
                headers=self.headers,
                json={"values": {"alpha_weight": -1}},
            ).status_code,
            422,
        )
        job = self.store.new_job(self.id, "train", {})
        self.assertEqual(
            self.client.patch(
                endpoint + "/training", headers=self.headers, json={"values": {}}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.patch(
                endpoint + "/view",
                headers=self.headers,
                json={"values": {"render_scale": 0.5}},
            ).status_code,
            200,
        )
        self.store.job_update(job, state="completed")
        self.assertEqual(
            self.client.patch(
                endpoint + "/training", headers=self.headers, json={"values": {}}
            ).json()["values"]["alpha_weight"],
            0.1,
        )
        self.assertEqual(self.root.joinpath("user.txt").read_text(), "keep")


class SettingsMigrationAndSafety(unittest.TestCase):
    def test_other_settings_do_not_discard_legacy_training_iterations(self):
        project = {"settings": {"iterations": 12000}}
        save(project, "review", {"overlay_opacity": 0.6})
        save(project, "view", {"render_scale": 0.5})
        self.assertEqual(effective(project, "training")["iterations"], 12000)
        # Explicit training reset must materialize the new namespace and defaults.
        save(project, "training", {})
        self.assertEqual(effective(project, "training")["iterations"], 30000)

    def test_legacy_iterations_and_resume_identity(self):
        from studio.task_settings import require_resume_settings

        self.assertEqual(
            effective({"settings": {"iterations": 12000}}, "training")["iterations"],
            12000,
        )
        request = execution({}, "train", {})
        previous = {
            "fingerprint": {"settings": copy.deepcopy(request["settings_snapshot"])}
        }
        require_resume_settings(previous, request)
        changed = execution({}, "train", {"iterations": 100})
        with self.assertRaises(ValueError):
            require_resume_settings(previous, changed)
        with self.assertRaises(ValueError):
            require_resume_settings({"fingerprint": {}}, request)

    def test_imported_cfg_never_executes_and_native_defaults_are_retained(self):
        import tempfile
        from pathlib import Path
        from studio.result_artifacts import safe_model_config
        from studio.gaussian_render_server import read_cfg

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = root / "cfg_args"
            marker = root / "executed"
            cfg.write_text(
                "Namespace(sh_degree=__import__('pathlib').Path("
                + repr(str(marker))
                + ").touch())"
            )
            with self.assertRaises(ValueError):
                safe_model_config(root)
            self.assertFalse(marker.exists())
            cfg.write_text("Namespace(sh_degree=2, white_background=True)")
            cfg.write_text(safe_model_config(root, source=root / "scene", target=root))
            data = read_cfg(root)
            self.assertEqual(data["sh_degree"], 2)
            self.assertEqual(data["images"], "images")
            self.assertEqual(data["resolution"], -1)
