import os
from pathlib import Path
from unittest import mock
import unittest

from start_demo import _env_flag, _validated_bind_host


ROOT = Path(__file__).resolve().parents[1]


class ContainerDeploymentTests(unittest.TestCase):
    def test_public_frontend_bind_host_is_supported(self):
        self.assertEqual(
            _validated_bind_host(
                "0.0.0.0",
                default_host="127.0.0.1",
                label="web frontend",
            ),
            "0.0.0.0",
        )

    def test_invalid_bind_host_is_rejected(self):
        with self.assertRaises(SystemExit):
            _validated_bind_host(
                "public.example.com",
                default_host="127.0.0.1",
                label="web frontend",
            )

    def test_environment_flags_are_strict(self):
        with mock.patch.dict(os.environ, {"DRIVEMATE_TEST_FLAG": "true"}):
            self.assertTrue(_env_flag("DRIVEMATE_TEST_FLAG"))
        with mock.patch.dict(os.environ, {"DRIVEMATE_TEST_FLAG": "invalid"}):
            with self.assertRaises(SystemExit):
                _env_flag("DRIVEMATE_TEST_FLAG")

    def test_dockerfile_exposes_modelscope_port(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("DRIVEMATE_FRONTEND_HOST=0.0.0.0", dockerfile)
        self.assertIn(
            "DRIVEMATE_FRONTEND_URL=http://127.0.0.1:7860",
            dockerfile,
        )
        self.assertIn("EXPOSE 7860", dockerfile)
        self.assertIn('CMD ["python", "start_demo.py"]', dockerfile)

    def test_generated_tokens_are_passed_as_single_arguments(self):
        startup = (ROOT / "start_demo.py").read_text(encoding="utf-8")
        self.assertIn('f"--token={simulator_token}"', startup)
        self.assertIn('f"--token={api_token}"', startup)


if __name__ == "__main__":
    unittest.main()
