import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from studio.doctor import ROOT


class InstallSafetyTests(unittest.TestCase):
    def test_read_only_app_uninstall_keeps_projects_runtime_and_prior_retired_copies(
        self,
    ):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            data = home / "data"
            config = home / "config"
            app = data / "m4ml-studio/apps/0.3.0"
            app.mkdir(parents=True)
            (app / "release-manifest.json").write_text("{}")
            (app / "science.py").write_text("preserve scientific source")
            for p in app.iterdir():
                p.chmod(0o444)
            app.chmod(0o555)
            old = data / "m4ml-studio/retired-apps/0.2.0-7"
            old.mkdir(parents=True)
            (old / "unchanged").write_text("old app")
            project = data / "m4ml-studio/projects/userdata"
            project.mkdir(parents=True)
            (project / "original.txt").write_text("user images are immutable")
            runtime = data / "m4ml-studio/runtime"
            runtime.mkdir()
            (runtime / "keep").write_text("GPU runtime")
            registry = config / "m4ml-studio/install.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({"version": "0.3.0", "app": str(app), "runtime": str(runtime)}))
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(data),
                "XDG_CONFIG_HOME": str(config),
            }
            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts/install.py"), "--uninstall"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(app.exists())
            self.assertEqual(
                (project / "original.txt").read_text(), "user images are immutable"
            )
            self.assertEqual((runtime / "keep").read_text(), "GPU runtime")
            self.assertEqual((old / "unchanged").read_text(), "old app")
            copies = [p for p in old.parent.iterdir() if p != old]
            self.assertEqual(len(copies), 1)
            self.assertEqual(
                (copies[0] / "science.py").read_text(), "preserve scientific source"
            )
            for p in copies[0].rglob("*"):
                p.chmod(0o700)
            copies[0].chmod(0o700)
