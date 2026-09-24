from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from agent_platform.backup import BackupManager


class BackupTests(unittest.TestCase):
    def test_dry_run_does_not_create_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "openclaw.json").write_text("{}")
            destination = root / "backups"

            result = BackupManager(source, destination).create(dry_run=True)

            self.assertFalse(destination.exists())
            self.assertFalse(result.changed)
            self.assertEqual(result.file_count, 1)

    def test_backup_excludes_logs_and_verifies_disposable_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ".openclaw"
            (source / "cron").mkdir(parents=True)
            (source / "logs").mkdir()
            (source / "openclaw.json").write_text('{"mode":"test"}')
            (source / "cron" / "jobs.json").write_text('{"jobs":[]}')
            (source / "logs" / "gateway.log").write_text("private live log")
            destination = root / "backups"

            result = BackupManager(source, destination).create()

            self.assertTrue(result.changed)
            self.assertTrue(result.verified)
            self.assertEqual(result.file_count, 2)
            self.assertEqual(result.checkpoint_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(result.archive.stat().st_mode & 0o777, 0o600)
            manifest = json.loads(result.manifest.read_text())
            self.assertEqual(sorted(manifest["files"]), ["cron/jobs.json", "openclaw.json"])
            with tarfile.open(result.archive, "r:gz") as archive:
                names = archive.getnames()
            self.assertNotIn("openclaw/logs/gateway.log", names)

    def test_verify_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "unsafe.tar.gz"
            payload = root / "payload"
            payload.write_text("bad")
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(payload, arcname="../escape")

            with self.assertRaises(ValueError):
                BackupManager.verify_archive(archive_path, {})


if __name__ == "__main__":
    unittest.main()
