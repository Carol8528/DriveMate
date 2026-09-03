import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from components.vehicle_gateway import VehicleGateway
from start_demo import _free_local_port, _wait_for_authenticated_health


class SimulatorAuthStartupTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.port = _free_local_port()
        self.token = "test-runtime-token"
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="drivemate-simulator-test-"
        )
        env = os.environ.copy()
        env["DRIVEMATE_SIMULATOR_TOKEN"] = self.token
        self.proc = subprocess.Popen(
            [
                sys.executable,
                os.path.join(self.root, "simulator_server.py"),
                "--port",
                str(self.port),
                "--token",
                self.token,
                "--db",
                os.path.join(self.temp_dir.name, "simulator.db"),
            ],
            cwd=self.root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_authenticated_health(self.base_url, self.token, self.proc, timeout_s=5.0)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self.temp_dir.cleanup()

    def test_matching_token_is_authenticated(self):
        health = VehicleGateway(base_url=self.base_url, token=self.token).health()
        self.assertTrue(health.get("ok"))
        self.assertEqual(health.get("reason"), "authenticated")

    def test_wrong_token_is_explicit_unauthorized(self):
        health = VehicleGateway(base_url=self.base_url, token="wrong-token").health()
        self.assertFalse(health.get("ok"))
        self.assertEqual(health.get("reason"), "unauthorized")
        self.assertEqual(health.get("status_code"), 401)

    def test_missing_token_is_explicit(self):
        health = VehicleGateway(base_url=self.base_url, token="").health()
        self.assertFalse(health.get("ok"))
        self.assertEqual(health.get("reason"), "token_missing")


if __name__ == "__main__":
    unittest.main()
