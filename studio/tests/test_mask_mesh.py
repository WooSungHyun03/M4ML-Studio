from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import trimesh
from studio.sam31 import validate_mask
from studio.mesh import validate_mesh


class ArtifactValidationTests(unittest.TestCase):
    def test_empty_wrong_sized_or_nonbinary_masks_are_not_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mask.png"
            for value in (0, 127):
                Image.new("L", (8, 8), value).save(path)
                with self.assertRaises(ValueError):
                    validate_mask(path, (8, 8))
            Image.new("L", (8, 8), 255).save(path)
            with self.assertRaises(ValueError):
                validate_mask(path, (9, 8))
            self.assertEqual(validate_mask(path, (8, 8))["area"], 64)

    def test_fixture_mesh_export_loadback_and_point_cloud_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.ply"
            mesh = trimesh.creation.box()
            mesh.export(source)
            report = validate_mesh(source, root / "export")
            self.assertEqual(report["triangles"], 12)
            self.assertEqual(report["vertices"], 8)
            cloud = trimesh.points.PointCloud(
                np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]])
            )
            cloud.export(root / "points.ply")
            with self.assertRaises(ValueError):
                validate_mesh(root / "points.ply")
