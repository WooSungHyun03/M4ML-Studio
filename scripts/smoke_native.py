"""Real CUDA forward/backward through unchanged original Object-Aware renderer.

Small mathematical fixture; NOT a COLMAP reconstruction or end-to-end training run.
"""

from argparse import ArgumentParser
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from arguments import OptimizationParams
from gaussian_renderer import render
from scene.cameras import Camera
from scene.gaussian_model import GaussianModel
from utils.graphics_utils import BasicPointCloud
from utils.loss_utils import masked_l1_loss, polarization_loss


def main():
    print("Runtime", sys.executable, torch.__version__, torch.version.cuda, flush=True)
    assert torch.__version__.split("+")[0] == "2.5.1" and torch.version.cuda == "11.8"
    assert torch.cuda.is_available()
    print(
        "Device",
        torch.cuda.get_device_name(0),
        torch.cuda.get_device_properties(0),
        flush=True,
    )
    torch.manual_seed(42)
    xyz = np.array(
        [
            [x, y, 2.0 + 0.1 * x * y]
            for x in np.linspace(-0.6, 0.6, 8)
            for y in np.linspace(-0.6, 0.6, 8)
        ],
        dtype=np.float32,
    )
    g = GaussianModel(3)
    g.create_from_pcd(
        BasicPointCloud(xyz, np.full_like(xyz, 0.7), np.zeros_like(xyz)), 1.0
    )
    options = OptimizationParams(ArgumentParser())
    g.training_setup(options)
    camera = Camera(
        colmap_id=1,
        R=np.eye(3),
        T=np.zeros(3),
        FoVx=1.0,
        FoVy=1.0,
        image=torch.ones(3, 64, 64) * 0.7,
        gt_alpha_mask=torch.ones(1, 64, 64),
        image_name="native_fixture",
        uid=0,
        data_device="cuda",
    )
    pipe = SimpleNamespace(
        compute_cov3D_python=False, convert_SHs_python=False, depth_ratio=0.0
    )
    result = render(
        camera, g, pipe, torch.zeros(3, device="cuda"), need_objectmark=True
    )
    mask = torch.zeros(1, 64, 64, device="cuda")
    mask[:, 12:52, 12:52] = 1
    l1 = masked_l1_loss(result["render"], camera.original_image.cuda(), mask)
    pa = polarization_loss(result["rend_alpha"], mask)
    po = polarization_loss(result["rend_object_mark"], mask)
    total = l1 + options.lambda_pa * pa + options.lambda_po * po
    total.backward()
    for parameter in (g._xyz, g._opacity, g._objectmark_score):
        assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
        assert torch.count_nonzero(parameter.grad).item() > 0
    assert result["render"].shape == (3, 64, 64)
    assert torch.count_nonzero(result["radii"]).item() > 0
    g.optimizer.step()
    torch.cuda.synchronize()
    print(
        "PASS CUDA native render + masked L1 + alpha/ObjectMark polarization backward + optimizer",
        {"l1": l1.item(), "pa": pa.item(), "po": po.item(), "loss": total.item()},
        flush=True,
    )


if __name__ == "__main__":
    main()
