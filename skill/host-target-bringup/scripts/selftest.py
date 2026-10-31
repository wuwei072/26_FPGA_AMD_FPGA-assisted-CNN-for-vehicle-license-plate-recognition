"""Synthetic, offline tests. No service, camera, board or network is opened."""
import tempfile
import unittest
from pathlib import Path

from check_deployment import inspect, sha256


class DeploymentChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.plan = {"roles": {"target": {
            "os": "linux", "files": ["device_server.py"],
            "artifact_pairs": [{"stem": "accelerator", "suffixes": [".bit", ".hwh"]}]}}}
        for name in ("device_server.py", "accelerator.bit", "accelerator.hwh"):
            (self.root / name).write_bytes(b"synthetic fixture")

    def test_correct_role_and_files(self):
        result = inspect(self.plan, "target", self.root, system="Linux")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["files"]), 3)
        self.assertTrue(result["warnings"])

    def test_board_command_in_windows_environment(self):
        result = inspect(self.plan, "target", self.root, system="Windows")
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"][0]["ok"])

    def test_wrong_upload_directory(self):
        result = inspect(self.plan, "target", self.root / "old_upload", system="Linux")
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"], {})

    def test_missing_paired_file(self):
        (self.root / "accelerator.hwh").unlink()
        self.assertFalse(inspect(self.plan, "target", self.root, system="Linux")["ok"])

    def test_trusted_build_hashes(self):
        config = self.plan["roles"]["target"]
        config["sha256"] = {name: sha256(self.root / name)
                            for name in ("accelerator.bit", "accelerator.hwh")}
        self.assertTrue(inspect(self.plan, "target", self.root, system="Linux")["ok"])
        (self.root / "accelerator.bit").write_bytes(b"another build")
        self.assertFalse(inspect(self.plan, "target", self.root, system="Linux")["ok"])


if __name__ == "__main__":
    unittest.main()
