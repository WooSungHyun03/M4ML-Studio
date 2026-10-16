import tempfile, unittest
from pathlib import Path
import numpy as np
import trimesh
from studio.mesh import validate_mesh, glb_colors, linear_to_srgb


class ColorTests(unittest.TestCase):
    def test_actual_srgb_samples_survive_linear_glb(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            m = trimesh.creation.box()
            colors = np.array(
                [
                    [255, 0, 0, 255],
                    [0, 255, 0, 255],
                    [0, 0, 255, 255],
                    [128, 64, 32, 255],
                ]
                * 2,
                np.uint8,
            )
            m.visual.vertex_colors = colors
            m.export(root / "rgb.ply")
            report = validate_mesh(root / "rgb.ply", root / "out")
            self.assertTrue(report["color"]["present"])
            self.assertLess(report["color_roundtrip_max_error"], 1 / 255)
            import json, struct

            raw = (root / "out/preview.glb").read_bytes()
            length = struct.unpack_from("<I", raw, 12)[0]
            tree = json.loads(raw[20 : 20 + length])
            primitive = tree["meshes"][0]["primitives"][0]
            material = tree["materials"][primitive["material"]]
            self.assertEqual(
                material["pbrMetallicRoughness"]["baseColorFactor"], [1, 1, 1, 1]
            )
            self.assertEqual(material["pbrMetallicRoughness"]["metallicFactor"], 0)
            self.assertIn("KHR_materials_unlit", material["extensions"])
            c = glb_colors(root / "out/preview.glb")
            np.testing.assert_allclose(
                linear_to_srgb(c), colors[:, :3] / 255, atol=1e-6
            )

    def test_colorless_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plain.ply"
            trimesh.creation.box().export(p)
            self.assertFalse(validate_mesh(p)["colors"])
