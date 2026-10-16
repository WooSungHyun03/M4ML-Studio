"""Triangle geometry and explicit sRGB PLY -> linear-color glTF validation."""

from pathlib import Path
import json
import struct
import numpy as np
from studio.doctor import atomic_json, sha256


def srgb_to_linear(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(
        rgb <= 0.0031308, rgb * 12.92, 1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055
    )


def check_glb_resources(path):
    raw = Path(path).read_bytes()
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise ValueError("GLB 파일 헤더가 유효하지 않습니다.")
    length, kind = struct.unpack_from("<II", raw, 12)
    if kind != 0x4E4F534A or length > len(raw) - 20:
        raise ValueError("GLB JSON 영역이 유효하지 않습니다.")
    tree = json.loads(raw[20 : 20 + length])
    for entry in tree.get("buffers", []) + tree.get("images", []):
        uri = entry.get("uri")
        if uri and not uri.startswith("data:"):
            raise ValueError(
                "외부 파일/URL을 참조하는 GLB는 지원하지 않습니다. 모든 리소스를 내장해 다시 내보내세요."
            )


def glb_colors(path):
    """Read actual glTF color accessors, including normalized uint8 and float32."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"glTF":
        raise ValueError("GLB 파일 헤더가 유효하지 않습니다.")
    length, kind = struct.unpack_from("<II", raw, 12)
    tree = json.loads(raw[20 : 20 + length])
    start = 20 + length
    binary = raw[start + 8 :]
    colors = []
    for mesh in tree.get("meshes", []):
        for primitive in mesh["primitives"]:
            index = primitive.get("attributes", {}).get("COLOR_0")
            if index is None:
                continue
            a = tree["accessors"][index]
            view = tree["bufferViews"][a["bufferView"]]
            dtype = {5121: np.uint8, 5123: np.dtype("<u2"), 5126: np.dtype("<f4")}[
                a["componentType"]
            ]
            n = int(a["type"][-1])
            offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
            c = (
                np.frombuffer(binary, dtype=dtype, count=a["count"] * n, offset=offset)
                .reshape(-1, n)
                .astype(np.float32)
            )
            if a.get("normalized"):
                c /= np.iinfo(dtype).max
            colors.append(c[:, :3])
    return np.concatenate(colors) if colors else None


def color_stats(rgb):
    if rgb is None:
        return {"present": False, "space": "sRGB"}
    rgb = np.asarray(rgb, dtype=np.float32)
    if not np.isfinite(rgb).all() or np.any(rgb < 0) or np.any(rgb > 1.00001):
        raise ValueError("정점 색상에 유효하지 않은 값이 있습니다.")
    return {
        "present": True,
        "space": "sRGB",
        "min": rgb.min(0).tolist(),
        "max": rgb.max(0).tolist(),
        "mean": rgb.mean(0).tolist(),
        "std": rgb.std(0).tolist(),
        "mean_chroma": float(np.ptp(rgb, axis=1).mean()),
    }


def validate_mesh(path, output=None):
    import trimesh
    from trimesh.exchange.gltf import export_glb

    path = Path(path)
    if path.suffix.lower() == ".glb":
        check_glb_resources(path)
    mesh = trimesh.load(str(path), force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(
            "점 구름은 삼각형 3D 모델이 아닙니다. 3D 모델 생성 결과(메시)를 선택하세요."
        )
    if (
        not len(mesh.vertices)
        or not len(mesh.faces)
        or not np.isfinite(mesh.vertices).all()
    ):
        raise ValueError(
            "유효한 삼각형 메시가 없습니다. 학습 결과와 추출 설정을 확인하세요."
        )
    if (
        mesh.faces.shape[1] != 3
        or np.any(mesh.faces < 0)
        or np.any(mesh.faces >= len(mesh.vertices))
    ):
        raise ValueError("메시의 삼각형 인덱스가 유효하지 않습니다.")
    present = mesh.visual.kind in ("vertex", "face") and mesh.visual.defined
    rgb = (
        np.asarray(mesh.visual.vertex_colors[:, :3], dtype=np.float32) / 255
        if present
        else None
    )
    if path.suffix.lower() == ".glb":
        linear = glb_colors(path)
        rgb = linear_to_srgb(linear) if linear is not None else None
        if rgb is not None:
            mesh.visual.vertex_colors = np.column_stack(
                [
                    np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8),
                    np.full(len(rgb), 255, np.uint8),
                ]
            )
    report = {
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.faces),
        "bounds": mesh.bounds.tolist(),
        "sha256": sha256(path),
        "colors": rgb is not None,
        "color": color_stats(rgb),
        "bytes": path.stat().st_size,
        "exporter_version": 3,
    }
    if output:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)

        # Trimesh4.3.2 writes sRGB byte colors directly. glTF COLOR_0 is linear.
        def colors_linear(buffers, tree):
            accessors = list(tree["accessors"].values())
            keys = list(buffers)
            done = set()
            for geometry in tree["meshes"]:
                for primitive in geometry["primitives"]:
                    i = primitive["attributes"].get("COLOR_0")
                    if i is None or i in done:
                        continue
                    done.add(i)
                    a = accessors[i]
                    key = keys[a["bufferView"]]
                    rgba = (
                        np.frombuffer(buffers[key], np.uint8, count=a["count"] * 4)
                        .reshape(-1, 4)
                        .astype(np.float32)
                        / 255
                    )
                    rgba[:, :3] = srgb_to_linear(rgba[:, :3])
                    buffers[key] = rgba.astype("<f4").tobytes()
                    a["componentType"] = 5126
                    a.pop("normalized", None)
                    a["min"] = rgba.min(0).tolist()
                    a["max"] = rgba.max(0).tolist()

        def material(tree):
            tree["asset"][
                "generator"
            ] = "M4ML Studio / trimesh (linear vertex colors, unlit)"
            if rgb is not None:
                materials = tree.setdefault("materials", [])
                index = len(materials)
                materials.append(
                    {
                        "name": "Original vertex colors",
                        "doubleSided": True,
                        "pbrMetallicRoughness": {
                            "baseColorFactor": [1, 1, 1, 1],
                            "metallicFactor": 0,
                            "roughnessFactor": 0.85,
                        },
                        "extensions": {"KHR_materials_unlit": {}},
                    }
                )
                tree["extensionsUsed"] = sorted(
                    set(tree.get("extensionsUsed", [])) | {"KHR_materials_unlit"}
                )
                for geometry in tree["meshes"]:
                    for primitive in geometry["primitives"]:
                        if "COLOR_0" in primitive["attributes"]:
                            primitive["material"] = index

        from studio.importer import atomic_bytes

        atomic_bytes(
            output / "preview.glb",
            export_glb(
                mesh, buffer_postprocessor=colors_linear, tree_postprocessor=material
            ),
        )
        preview = trimesh.load(output / "preview.glb", force="mesh", process=False)
        if (
            len(preview.faces) != len(mesh.faces)
            or not np.isfinite(preview.vertices).all()
        ):
            raise ValueError("미리보기 메시 변환을 검증하지 못했습니다.")
        restored = glb_colors(output / "preview.glb")
        if rgb is not None:
            if restored is None or restored.shape != rgb.shape:
                raise ValueError("GLB 변환 중 정점 색상이 누락되었습니다.")
            error = float(np.max(np.abs(linear_to_srgb(restored) - rgb)))
            if error > 1 / 255:
                raise ValueError("GLB 변환 중 정점 색상이 변경되었습니다.")
            report["color_roundtrip_max_error"] = error
        report["preview_sha256"] = sha256(output / "preview.glb")
        atomic_json(output / "mesh_report.json", report)
    return report
