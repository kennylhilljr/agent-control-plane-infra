from __future__ import annotations

import hashlib
import io
import json
import shutil
import stat
import sys
import tempfile
import unittest
import unittest.mock
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_platform import cli
from agent_platform.backup import AGE_HEADER, BackupManager, looks_synchronized
from agent_platform.inventory import CommandResult



def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()

RECIPIENT = "age1" + "q" * 58
SSH_RECIPIENT = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl op"
MARKER = "SYNTHETIC-PLAINTEXT-MARKER-39"


@contextmanager
def fixture_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="acp-enc-test-", dir="/tmp") as directory:
        root = Path(directory).resolve()
        (root / "staging").mkdir(mode=0o700)
        yield root


def make_source(root: Path) -> Path:
    source = root / "source"
    (source / "credentials").mkdir(parents=True)
    (source / "openclaw.json").write_text('{"mode":"test"}')
    (source / "credentials" / "auth.json").write_text(json.dumps({"value": MARKER}))
    return source


class FakeAge:
    """Stands in for run_command running age: writes an age header plus a
    transformed copy of the input to --output and records each call."""

    def __init__(self, *, returncode: int = 0, header: bytes = AGE_HEADER,
                 timed_out: bool = False) -> None:
        self.calls: list[tuple[tuple[str, ...], float]] = []
        self.returncode = returncode
        self.header = header
        self.timed_out = timed_out
        self.saw_plaintext_at: Path | None = None

    def __call__(self, command: tuple[str, ...], timeout: float = 5.0) -> CommandResult:
        self.calls.append((command, timeout))
        output = Path(command[command.index("--output") + 1])
        plain = Path(command[-1])
        self.saw_plaintext_at = plain
        if self.timed_out:
            return CommandResult(None, "", "", True)
        if self.returncode == 0:
            output.write_bytes(self.header + bytes(b ^ 0x5A for b in plain.read_bytes()))
        return CommandResult(self.returncode, "", "", False)


def locate_age(name: str) -> str | None:
    return "/opt/fake/bin/age" if name == "age" else None


def manager(root: Path, source: Path, destination: Path, run: FakeAge, **kwargs: object
            ) -> BackupManager:
    kwargs.setdefault("encrypt_to", (RECIPIENT,))
    return BackupManager(source, destination, locate=locate_age, run=run,
                         staging_root=root / "staging", **kwargs)  # type: ignore[arg-type]


class SynchronizedDestinationTests(unittest.TestCase):
    def test_common_sync_folders_are_detected(self) -> None:
        for path in ("/Users/x/Library/Mobile Documents/com~apple~CloudDocs/b",
                     "/Users/x/Library/CloudStorage/GoogleDrive-a/My Drive/b",
                     "/Users/x/Dropbox (Personal)/b", "/Users/x/OneDrive - Corp/b",
                     "/Users/x/iCloud Drive/b", "/Users/x/Google Drive/b"):
            self.assertTrue(looks_synchronized(Path(path)), path)
        for path in ("/Users/x/AgentPlatformBackups", "/Volumes/Backup/openclaw",
                     "/Users/x/boxes"):
            self.assertFalse(looks_synchronized(Path(path)), path)

    def test_unencrypted_backup_to_synced_folder_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "Dropbox" / "backups"
            for dry_run in (True, False):
                with self.assertRaisesRegex(ValueError, "Unencrypted backup refused"):
                    BackupManager(source, destination).create(dry_run=dry_run)
            self.assertFalse(destination.exists())

    def test_allow_unencrypted_overrides_refusal(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "Dropbox" / "backups"
            result = BackupManager(source, destination, allow_unencrypted=True).create()
            self.assertFalse(result.encrypted)
            self.assertEqual(result.archive.name, "openclaw-state.tar.gz")

    def test_encrypted_backup_to_synced_folder_is_allowed(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            result = manager(root, source, root / "Dropbox" / "backups", FakeAge()).create()
            self.assertTrue(result.encrypted)


class EncryptedBackupTests(unittest.TestCase):
    def test_checkpoint_holds_only_ciphertext(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            fake = FakeAge()
            result = manager(root, source, root / "backups", fake).create()

            checkpoint = result.checkpoint_dir
            self.assertTrue(result.encrypted and result.verified and result.changed)
            self.assertEqual(sorted(p.name for p in checkpoint.iterdir()), [
                "manifest.json", "openclaw-state.tar.gz.age",
                "openclaw-state.tar.gz.age.sha256",
            ])
            self.assertEqual(result.archive, checkpoint / "openclaw-state.tar.gz.age")
            for path in checkpoint.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
                self.assertNotIn(MARKER.encode(), path.read_bytes())
            ciphertext = result.archive.read_bytes()
            self.assertTrue(ciphertext.startswith(AGE_HEADER))
            # The plaintext was staged outside the destination and removed.
            assert fake.saw_plaintext_at is not None
            self.assertFalse(fake.saw_plaintext_at.is_relative_to(root / "backups"))
            self.assertEqual(list((root / "staging").iterdir()), [])

            manifest = json.loads(result.manifest.read_text())
            self.assertEqual(manifest["archive"], "openclaw-state.tar.gz.age")
            self.assertEqual(manifest["archive_sha256"], hashlib.sha256(ciphertext).hexdigest())
            self.assertEqual(manifest["encryption"]["tool"], "age")
            self.assertEqual(manifest["encryption"]["recipients"], [RECIPIENT])
            self.assertEqual(manifest["encryption"]["plaintext_archive"], "openclaw-state.tar.gz")
            self.assertEqual(len(manifest["encryption"]["plaintext_archive_sha256"]), 64)
            self.assertTrue(manifest["restore_verified"])
            checksum = (checkpoint / "openclaw-state.tar.gz.age.sha256").read_text()
            self.assertEqual(checksum, f"{manifest['archive_sha256']}  openclaw-state.tar.gz.age\n")

    def test_age_command_is_an_argument_tuple_with_recipients(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            fake = FakeAge()
            manager(root, source, root / "backups", fake,
                    encrypt_to=(RECIPIENT, SSH_RECIPIENT)).create()
            [(command, timeout)] = fake.calls
            self.assertIsInstance(command, tuple)
            self.assertEqual(command[:6], ("/opt/fake/bin/age", "--encrypt", "--recipient",
                                           RECIPIENT, "--recipient", SSH_RECIPIENT))
            self.assertEqual(command[-2], "--")
            self.assertGreater(timeout, 5.0)

    def test_unencrypted_manifest_records_no_encryption(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            result = BackupManager(source, root / "backups").create()
            self.assertIsNone(json.loads(result.manifest.read_text())["encryption"])

    def test_dry_run_runs_preflight_but_not_age(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            fake = FakeAge()
            result = manager(root, source, root / "backups", fake).create(dry_run=True)
            self.assertEqual(fake.calls, [])
            self.assertTrue(result.encrypted)
            self.assertEqual(result.archive.name, "openclaw-state.tar.gz.age")
            self.assertFalse((root / "backups").exists())
            self.assertEqual(list((root / "staging").iterdir()), [])

    def test_invalid_recipients_are_refused_before_anything_runs(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            for recipient in ("--output=/etc/passwd", "age1short", "AGE-SECRET-KEY-1ABC",
                              RECIPIENT + "\n", "ssh-ed25519 AAAA\nx"):
                fake = FakeAge()
                with self.assertRaisesRegex(ValueError, "^Invalid age recipient"):
                    manager(root, source, root / "backups", fake,
                            encrypt_to=(recipient,)).create()
                self.assertEqual(fake.calls, [])
            self.assertFalse((root / "backups").exists())

    def test_missing_age_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            with self.assertRaisesRegex(ValueError, "age is required"):
                BackupManager(source, root / "backups", encrypt_to=(RECIPIENT,),
                              locate=lambda name: None).create(dry_run=True)

    def _assert_failure_cleans_staging(self, fake: FakeAge, pattern: str) -> None:
        with fixture_root() as root:
            source = make_source(root)
            with self.assertRaisesRegex(ValueError, pattern):
                manager(root, source, root / "backups", fake).create()
            self.assertEqual(list((root / "staging").iterdir()), [])
            [checkpoint] = (root / "backups").iterdir()
            self.assertEqual(list(checkpoint.iterdir()), [])

    def test_age_failure_removes_plaintext(self) -> None:
        self._assert_failure_cleans_staging(FakeAge(returncode=1), "exit status 1")

    def test_age_timeout_removes_plaintext(self) -> None:
        self._assert_failure_cleans_staging(FakeAge(timed_out=True), "timed out")

    def test_output_without_age_header_is_rejected(self) -> None:
        self._assert_failure_cleans_staging(FakeAge(header=b"PK\x03\x04"), "not an age file")

    def test_staging_inside_destination_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            destination.mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, "staging folder must not overlap the backup"):
                BackupManager(source, destination, encrypt_to=(RECIPIENT,), locate=locate_age,
                              run=FakeAge(), staging_root=destination / "s").create()

    def test_staging_inside_source_is_refused_unless_excluded(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            (source / "work").mkdir()
            (source / "tmp").mkdir()
            with self.assertRaisesRegex(ValueError, "staging folder must not overlap the source"):
                BackupManager(source, root / "backups", encrypt_to=(RECIPIENT,),
                              locate=locate_age, run=FakeAge(),
                              staging_root=source / "work").create()
            result = BackupManager(source, root / "backups", encrypt_to=(RECIPIENT,),
                                   locate=locate_age, run=FakeAge(),
                                   staging_root=source / "tmp").create()
            self.assertTrue(result.encrypted)
            self.assertEqual(list((source / "tmp").iterdir()), [])


class StagingSafetyTests(unittest.TestCase):
    def test_synchronized_staging_root_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            staging = root / "Dropbox" / "tmp"
            staging.mkdir(parents=True)
            fake = FakeAge()
            with self.assertRaisesRegex(ValueError, "staging folder must not look synchronized"):
                BackupManager(source, root / "backups", encrypt_to=(RECIPIENT,),
                              locate=locate_age, run=fake, staging_root=staging).create()
            self.assertEqual(fake.calls, [])
            self.assertEqual(list(staging.iterdir()), [])

    def test_success_fails_when_staging_cannot_be_removed(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            real_rmtree = shutil.rmtree
            with unittest.mock.patch("agent_platform.backup.shutil.rmtree",
                                     lambda *a, **k: None):
                with self.assertRaisesRegex(OSError,
                                            "^Could not remove encryption staging folder: "):
                    manager(root, source, root / "backups", FakeAge()).create()
            for leftover in (root / "staging").iterdir():
                real_rmtree(leftover)

    def test_cli_reports_staging_cleanup_failure_as_handled(self) -> None:
        error = OSError("Could not remove encryption staging folder: /tmp/x")
        self.assertEqual(cli.safe_error_message(error),
                         "Could not remove encryption staging folder: /tmp/x")


class EncryptionCliTests(unittest.TestCase):
    def test_cli_reports_encryption_check(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            fake = FakeAge()
            real = BackupManager

            def build(*args: object, **kwargs: object) -> BackupManager:
                return real(*args, locate=locate_age, run=fake,  # type: ignore[arg-type]
                            staging_root=root / "staging", **kwargs)

            with unittest.mock.patch.object(cli, "BackupManager", build):
                code, stdout, stderr = run_cli([
                    "backup", "--source", str(source), "--backup-dir", str(root / "backups"),
                    "--encrypt-to", RECIPIENT, "--json"])
            self.assertEqual((code, stderr), (0, ""))
            envelope = json.loads(stdout)
            self.assertIn({"name": "age-encryption", "status": "passed"}, envelope["checks"])
            self.assertTrue(envelope["archive"].endswith("openclaw-state.tar.gz.age"))
            self.assertFalse(any("not encrypted" in w for w in envelope["warnings"]))

    def test_cli_synced_refusal_is_a_handled_failure(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            code, stdout, stderr = run_cli([
                "backup", "--source", str(source), "--backup-dir",
                str(root / "OneDrive" / "b"), "--dry-run", "--json"])
            self.assertEqual((code, stderr), (1, ""))
            envelope = json.loads(stdout)
            self.assertFalse(envelope["ok"])
            self.assertIn("Unencrypted backup refused", envelope["error"])
            self.assertIn("--allow-unencrypted", envelope["error"])

    def test_cli_unencrypted_warns(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            code, stdout, _ = run_cli([
                "backup", "--source", str(source), "--backup-dir", str(root / "b"),
                "--dry-run", "--json"])
            self.assertEqual(code, 0)
            envelope = json.loads(stdout)
            self.assertIn({"name": "age-encryption", "status": "skipped"}, envelope["checks"])
            self.assertTrue(any("not encrypted" in w for w in envelope["warnings"]))

    def test_cli_handled_messages_name_no_recipient(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            code, stdout, _ = run_cli([
                "backup", "--source", str(source), "--backup-dir", str(root / "b"),
                "--encrypt-to", "not-a-key-" + MARKER, "--dry-run", "--json"])
            self.assertEqual(code, 1)
            self.assertNotIn(MARKER, stdout)
            self.assertIn("Invalid age recipient", json.loads(stdout)["error"])



if __name__ == "__main__":
    unittest.main()
