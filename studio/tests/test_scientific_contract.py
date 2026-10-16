from argparse import ArgumentParser
import unittest
import torch

from arguments import OptimizationParams
from utils.loss_utils import masked_l1_loss, polarization_loss


class ScientificContractTests(unittest.TestCase):
    def test_original_default_loss_and_pruning_configuration(self):
        opt = OptimizationParams(ArgumentParser())
        actual = {
            key: getattr(opt, key)
            for key in (
                "iterations",
                "lambda_pa",
                "lambda_po",
                "lambda_normal",
                "lambda_dist",
                "objectmark_prune_from_iter",
                "objectmark_prune_interval",
                "objectmark_prune_threshold",
            )
        }
        self.assertEqual(
            actual,
            {
                "iterations": 30000,
                "lambda_pa": 0.1,
                "lambda_po": 1.0,
                "lambda_normal": 0.05,
                "lambda_dist": 0.0,
                "objectmark_prune_from_iter": 2500,
                "objectmark_prune_interval": 500,
                "objectmark_prune_threshold": 0.5,
            },
        )

    def test_background_has_no_masked_l1_gradient(self):
        pred = torch.tensor([[[0.8, 0.9]]] * 3, requires_grad=True)
        target = torch.zeros_like(pred)
        mask = torch.tensor([[[1.0, 0.0]]])
        loss = masked_l1_loss(pred, target, mask)
        loss.backward()
        self.assertAlmostEqual(loss.item(), 0.8, places=5)
        self.assertTrue(torch.all(pred.grad[:, :, 1] == 0))
        self.assertTrue(torch.all(pred.grad[:, :, 0] > 0))

    def test_both_polarizations_are_zero_only_for_correct_binary_target(self):
        mask = torch.tensor([[[1.0, 0.0]]])
        self.assertEqual(polarization_loss(mask, mask).item(), 0)
        self.assertEqual(polarization_loss(1 - mask, mask).item(), 1)
        score = torch.tensor([[[0.2, 0.8]]], requires_grad=True)
        polarization_loss(score, mask).backward()
        self.assertLess(score.grad[0, 0, 0].item(), 0)
        self.assertGreater(score.grad[0, 0, 1].item(), 0)
