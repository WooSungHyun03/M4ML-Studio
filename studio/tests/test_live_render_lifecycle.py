"""Failure-path ownership tests with real CPU children and real file locks.

These fixtures deliberately fail the provider handshake; they are not GPU rendering proof.
"""

import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import gpu_lock, live_render
from studio.gaussian_protocol import RemoteRendererClient


class LifecycleTests(unittest.TestCase):
    def test_spawn_and_log_failures_release_lock_with_traceback_retained(self):
        class MissingExecutable:
            def server_command(self, model):
                return [str(root / "missing-renderer")]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for log in (root / "renderer.log", root):  # valid log then an actual directory
                with self.subTest(log=log), \
                        patch("studio.engines.provider", return_value=MissingExecutable()), \
                        patch("studio.gpu_lock.lock_path", return_value=root / "gpu.lock"):
                    with self.assertRaises(live_render.LiveRenderError) as raised:
                        live_render._Session("fixture-gpu", "fixture", {}, log, 300)
                    self.assertIsInstance(raised.exception.__cause__, OSError)
                    # Keep the failure traceback alive: cleanup must not depend on GC.
                    lock = gpu_lock.try_acquire("fixture-gpu")
                    self.assertIsNotNone(lock)
                    lock.close()

    def test_failed_connection_stops_started_child_and_releases_lock(self):
        class BrokenConnection:
            def server_command(self, model):
                return [sys.executable, "-u", "-c",
                        'import sys; print(\'{"ready":true,"port":1}\', flush=True); sys.stdin.read()']

            def connect(self, port):
                raise ConnectionRefusedError("fixture connection failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            children = []
            popen = subprocess.Popen

            def spawn(*args, **kwargs):
                child = popen(*args, **kwargs)
                children.append(child)
                return child

            with patch("studio.engines.provider", return_value=BrokenConnection()), \
                    patch("studio.gpu_lock.lock_path", return_value=root / "gpu.lock"), \
                    patch("studio.live_render.subprocess.Popen", side_effect=spawn):
                try:
                    with self.assertRaises(live_render.LiveRenderError):
                        live_render._Session("fixture-gpu", "fixture", {}, root / "renderer.log", 300)
                    self.assertEqual(len(children), 1)
                    self.assertIsNotNone(children[0].poll(), "failed startup left its child running")
                    lock = gpu_lock.try_acquire("fixture-gpu")
                    self.assertIsNotNone(lock, "failed startup retained the GPU reservation")
                    lock.close()
                finally:
                    print("connection failure child still running:", bool(children and children[0].poll() is None))
                    for child in children:
                        if child.poll() is None:
                            child.terminate()
                            child.wait(timeout=5)
                        for stream in (child.stdin, child.stdout):
                            if stream and not stream.closed:
                                stream.close()

    def test_mode_negotiation_failure_closes_connected_client(self):
        class Client:
            render_items = []
            closed = False

            def close(self):
                self.closed = True

        client = Client()

        class BrokenModes:
            def server_command(self, model):
                return [sys.executable, "-u", "-c",
                        'import sys; print(\'{"ready":true,"port":1}\', flush=True); sys.stdin.read()']

            def connect(self, port):
                return client

            def modes(self, items):
                raise ValueError("fixture unsupported modes")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("studio.engines.provider", return_value=BrokenModes()), \
                    patch("studio.gpu_lock.lock_path", return_value=root / "gpu.lock"):
                with self.assertRaises(live_render.LiveRenderError):
                    live_render._Session("fixture-gpu", "fixture", {}, root / "renderer.log", 300)
                self.assertTrue(client.closed)
                lock = gpu_lock.try_acquire("fixture-gpu")
                self.assertIsNotNone(lock)
                lock.close()

    def test_malformed_handshake_closes_real_socket(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            eof = threading.Event()

            def serve():
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(3)
                    conn.sendall(struct.pack("<I", 1) + b"{")
                    if conn.recv(1) == b"":
                        eof.set()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            with self.assertRaises(ValueError) as raised:
                RemoteRendererClient("127.0.0.1", server.getsockname()[1])
            self.assertTrue(eof.wait(3), "bad handshake leaked its socket")
            self.assertIsNotNone(raised.exception)
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
