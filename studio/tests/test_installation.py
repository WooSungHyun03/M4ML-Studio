import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from studio.doctor import ROOT


class InstallSafetyTests(unittest.TestCase):
    def test_cross_device_retirement_verifies_copy_before_removing_original(self):
        import errno
        from unittest.mock import patch
        from scripts.install import retire_app, tree_contents
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            app, retired = root / 'app', root / 'retired'
            (app / 'read only').mkdir(parents=True)
            (app / 'read only/원본.txt').write_bytes(b'actual source bytes')
            (app / 'link').symlink_to('read only/원본.txt')
            (app / 'read only').chmod(0o555)
            expected = tree_contents(app)
            real_rename = Path.rename
            def cross_device(path, dest):
                if path == app:
                    raise OSError(errno.EXDEV, 'overlay lower layer')
                return real_rename(path, dest)
            with patch.object(Path, 'rename', cross_device):
                retire_app(app, retired)
            self.assertFalse(app.exists())
            self.assertEqual(tree_contents(retired), expected)
            (retired / 'read only').chmod(0o755)

    def test_failed_cross_device_copy_preserves_original(self):
        import errno
        from unittest.mock import patch
        from scripts.install import retire_app
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            app = root / 'app'
            app.mkdir()
            (app / 'keep').write_text('never discard')
            with patch.object(Path, 'rename', side_effect=OSError(errno.EXDEV, 'overlay')), \
                    patch('scripts.install.shutil.copytree', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    retire_app(app, root / 'retired')
            self.assertEqual((app / 'keep').read_text(), 'never discard')
            self.assertFalse((root / 'retired').exists())

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

    def test_only_manifest_files_are_installed_and_extraction_extras_remain_private(self):
        import hashlib, shutil
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'extracted bundle'
            (source / 'scripts').mkdir(parents=True)
            shutil.copyfile(ROOT / 'scripts/install.py', source / 'scripts/install.py')
            (source / 'README.md').write_text('verified release')
            secret = source / '.env.private'
            secret.write_text('keep in source only')
            entries = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in ('scripts/install.py', 'README.md')}
            manifest = {'version':'0.3.0','files_sha256':entries}
            (source / 'release-manifest.json').write_text(json.dumps(manifest))
            env = {**os.environ, 'XDG_DATA_HOME':str(root / 'data'), 'XDG_CONFIG_HOME':str(root / 'config'), 'XDG_CACHE_HOME':str(root / 'cache')}
            r = subprocess.run([sys.executable,str(source/'scripts/install.py'),'--no-setup'],env=env,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            app=root/'data/m4ml-studio/apps/0.3.0'
            self.assertEqual((app/'README.md').read_text(),'verified release')
            self.assertFalse((app/'.env.private').exists())
            self.assertEqual(secret.read_text(),'keep in source only')
            manifest['files_sha256']['../escape'] = '0'*64
            (source/'release-manifest.json').write_text(json.dumps(manifest))
            r=subprocess.run([sys.executable,str(source/'scripts/install.py'),'--no-setup'],env=env,capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('설치 파일 경로',r.stderr)
            self.assertEqual((app/'README.md').read_text(),'verified release')
