"""Real archive reproducibility and preservation; no GPU/install simulation."""
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.package_release import write_bundle


class BundleTests(unittest.TestCase):
    def test_reproducible_bytes_and_exclusive_publish(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            app = root / "M4ML-테스트"
            app.mkdir()
            source = app / "공백 이름.txt"
            source.write_text("보존되는 실제 파일\n")
            source.chmod(0o644)
            one, two = root / "one.tar.gz", root / "two.tar.gz"
            write_bundle(app, one, 1700000000)
            os.utime(source, (1800000000, 1800000000))
            write_bundle(app, two, 1700000000)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(one.stat().st_mode & 0o777, 0o644)
            before = one.read_bytes()
            source.write_text("changed")
            with self.assertRaises(FileExistsError):
                write_bundle(app, one, 1700000000)
            self.assertEqual(one.read_bytes(), before)
            with tarfile.open(one) as archive:
                member = archive.getmember("M4ML-테스트/공백 이름.txt")
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 1700000000))
                self.assertEqual(archive.extractfile(member).read().decode(), "보존되는 실제 파일\n")
