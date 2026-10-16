"""Untrusted loopback protocol input must be rejected before CUDA work."""

import copy
import json
import socket
import struct
import unittest

import numpy as np

from studio.gaussian_protocol import MAX_JSON_BYTES, camera_message, receive_json, validate_camera_message


class RenderInputTests(unittest.TestCase):
    def setUp(self):
        self.good = camera_message(np.eye(4), 640, 480, 0.8, 0.01, 1000)

    def test_valid_sibr_packet_and_zero_size_heartbeat_keep_wire_format(self):
        for message in (self.good, {"resolution_x": 0, "resolution_y": 0}):
            self.assertIs(validate_camera_message(message), message)
            raw = json.dumps(message).encode()
            a, b = socket.socketpair()
            with a, b:
                a.sendall(struct.pack("<I", len(raw)) + raw)
                self.assertEqual(receive_json(b), message)

    def test_declared_packet_size_rejected_without_waiting_for_body(self):
        for length in (0, MAX_JSON_BYTES + 1, 2**32 - 1):
            with self.subTest(length=length):
                a, b = socket.socketpair()
                with a, b:
                    b.settimeout(0.2)
                    a.sendall(struct.pack("<I", length))  # deliberately no body
                    with self.assertRaises(ValueError):
                        receive_json(b)

    def test_bad_camera_values_cannot_reach_native_renderer(self):
        for updates in (
            {"resolution_x": 100000}, {"resolution_y": -1}, {"resolution_x": True},
            {"resolution_x": 0}, {"view_matrix": [0] * 15}, {"view_projection_matrix": None},
            {"view_matrix": [float("nan")] * 16}, {"view_matrix": [1e40] * 16},
            {"view_matrix": [10**1000] * 16}, {"fov_y": 0}, {"fov_x": float("inf")},
            {"z_far": 0.001}, {"z_near": 1000}, {"scaling_modifier": float("nan")},
            {"scaling_modifier": -1}, {"render_mode": -1}, {"render_mode": 7},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_camera_message({**copy.deepcopy(self.good), **updates})
        for message in ([], None, "camera"):
            with self.assertRaises(ValueError):
                validate_camera_message(message)

    def test_partial_or_malformed_packet_closes_cleanly(self):
        for payload in (b"\x01\0", struct.pack("<I", 8) + b"{", struct.pack("<I", 1) + b"{"):
            a, b = socket.socketpair()
            with a, b:
                a.sendall(payload)
                a.shutdown(socket.SHUT_WR)
                with self.assertRaises((ValueError, ConnectionError)):
                    receive_json(b)


if __name__ == "__main__":
    unittest.main()
