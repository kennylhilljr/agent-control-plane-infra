from __future__ import annotations

import errno
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from agent_platform import cli
from agent_platform.backup import BackupManager, BackupResult


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORIES = REPO_ROOT / "inventories"
COMMON_KEYS = {
    "ok",
    "operation",
    "changed",
    "checks",
    "warnings",
    "required_user_actions",
    "rollback_checkpoint",
}
CHECKSUM_ERROR = "Disposable restore checksums do not match source snapshot"
CONTENT_MARKER = "SYNTHETIC-CONTENT-MARKER-7f3a"
_INVENTORY_SNAPSHOT: dict[str, bytes] = {}


def _snapshot_inventories() -> dict[str, bytes]:
    return {
        str(path.relative_to(INVENTORIES)): path.read_bytes()
        for path in sorted(INVENTORIES.rglob("*"))
        if path.is_file()
    }


def setUpModule() -> None:
    _INVENTORY_SNAPSHOT.update(_snapshot_inventories())


def tearDownModule() -> None:
    if _snapshot_inventories() != _INVENTORY_SNAPSHOT:
        raise AssertionError("CLI tests changed files under inventories/")
    status = subprocess.run(
        ("git", "status", "--porcelain", "inventories/"),
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    if status.returncode != 0 or status.stdout:
        raise AssertionError("git status --porcelain inventories/ is not clean")


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


@contextmanager
def fixture_root() -> Iterator[Path]:
    """A disposable folder under /tmp, never the operator's home."""
    with tempfile.TemporaryDirectory(prefix="acp-cli-test-", dir="/tmp") as directory:
        yield Path(directory).resolve()


def make_source(root: Path) -> Path:
    source = root / "source"
    (source / "cron").mkdir(parents=True)
    (source / "openclaw.json").write_text('{"mode":"test"}')
    (source / "cron" / "jobs.json").write_text('{"jobs":[]}')
    return source


def partial_write(path: Path, *args: Any, **kwargs: Any) -> int:
    """Stands in for Path.write_text: writes a fragment, then fails."""
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("{")
    raise OSError(errno.ENOSPC, "No space left on device", str(path))


class FakeCollector:
    data: dict[str, Any] = {"schema_version": "1.0", "tools": {"git": {"present": True}}}
    error: BaseException | None = None
    calls: list[list[Path]] = []

    def __init__(self, *, repositories: list[Path]) -> None:
        FakeCollector.calls.append(list(repositories))

    def collect(self) -> dict[str, Any]:
        if FakeCollector.error is not None:
            raise FakeCollector.error
        return dict(FakeCollector.data)


class CliTestCase(unittest.TestCase):
    def assert_envelope(self, envelope: dict[str, Any], operation: str) -> None:
        self.assertTrue(COMMON_KEYS <= set(envelope), envelope)
        self.assertEqual(envelope["operation"], operation)
        self.assertIsInstance(envelope["checks"], list)
        self.assertIsInstance(envelope["warnings"], list)
        self.assertEqual(envelope["required_user_actions"], [])

    def assert_json_failure(self, result: tuple[int, str, str], operation: str, *,
                            changed: bool) -> dict[str, Any]:
        code, stdout, stderr = result
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertNotIn("Traceback", stdout)
        envelope = json.loads(stdout)
        self.assert_envelope(envelope, operation)
        self.assertIs(envelope["ok"], False)
        self.assertIs(envelope["changed"], changed)
        self.assertEqual(envelope["checks"], [{"name": "command-execution", "status": "failed"}])
        self.assertIsNone(envelope["rollback_checkpoint"])
        self.assertIsInstance(envelope["error"], str)
        self.assertNotIn("\n", envelope["error"])
        return envelope

    def assert_text_failure(self, result: tuple[int, str, str]) -> str:
        code, stdout, stderr = result
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(stderr.count("\n"), 1)
        self.assertTrue(stderr.endswith("\n"))
        return stderr


class BackupCliTests(CliTestCase):
    def test_dry_run_json_success_has_all_envelope_keys(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            code, stdout, stderr = run_cli(["backup", "--source", str(source), "--backup-dir",
                                            str(destination), "--dry-run", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            envelope = json.loads(stdout)
            self.assert_envelope(envelope, "backup")
            self.assertIs(envelope["ok"], True)
            self.assertIs(envelope["changed"], False)
            self.assertFalse(destination.exists())

    def test_missing_source_json(self) -> None:
        with fixture_root() as root:
            missing = root / "does-not-exist"
            destination = root / "backups"
            envelope = self.assert_json_failure(
                run_cli(["backup", "--source", str(missing), "--backup-dir", str(destination),
                         "--dry-run", "--json"]),
                "backup", changed=False,
            )
            self.assertIn("OpenClaw state directory not found", envelope["error"])
            self.assertIn(str(missing), envelope["error"])
            self.assertEqual(envelope["warnings"], [])
            self.assertFalse(destination.exists())

    def test_missing_source_text(self) -> None:
        with fixture_root() as root:
            missing = root / "does-not-exist"
            stderr = self.assert_text_failure(
                run_cli(["backup", "--source", str(missing), "--backup-dir",
                         str(root / "backups")])
            )
            self.assertIn("OpenClaw state directory not found", stderr)

    def test_group_readable_destination_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            destination.mkdir()
            destination.chmod(0o755)
            argv = ["backup", "--source", str(source), "--backup-dir", str(destination)]
            envelope = self.assert_json_failure(run_cli([*argv, "--json"]), "backup",
                                                changed=False)
            self.assertIn("Backup root must not grant group/other access", envelope["error"])
            self.assertEqual(list(destination.iterdir()), [])
            stderr = self.assert_text_failure(run_cli(argv))
            self.assertIn("Backup root must not grant group/other access", stderr)

    def test_regular_file_destination_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            destination.write_text("not a directory")
            envelope = self.assert_json_failure(
                run_cli(["backup", "--source", str(source), "--backup-dir", str(destination),
                         "--json"]),
                "backup", changed=False,
            )
            self.assertIn(str(destination), envelope["error"])
            self.assertIn("Not a directory", envelope["error"])

    def _controlled_result(self, root: Path) -> BackupResult:
        checkpoint = root / "backups" / "openclaw-20260101T000000.000000Z"
        return BackupResult(True, True, 2, checkpoint, checkpoint / "openclaw-state.tar.gz",
                            checkpoint / "manifest.json", 1)

    def test_success_output_is_unchanged_in_both_modes(self) -> None:
        with fixture_root() as root:
            result = self._controlled_result(root)
            expected = json.dumps({
                "ok": True,
                "operation": "backup",
                "changed": True,
                "checks": [
                    {"name": "file-enumeration", "status": "passed", "count": 2},
                    {"name": "symlinks-recorded-not-followed", "status": "passed", "count": 1},
                    {"name": "disposable-restore", "status": "passed"},
                ],
                "warnings": ["Live logs are intentionally excluded from rollback state."],
                "required_user_actions": [],
                "rollback_checkpoint": str(result.checkpoint_dir),
                "archive": str(result.archive),
                "manifest": str(result.manifest),
            }, indent=2, sort_keys=True) + "\n"
            manager = mock.Mock()
            manager.return_value.create.return_value = result
            with mock.patch.object(cli, "BackupManager", manager):
                for extra in ([], ["--json"]):
                    code, stdout, stderr = run_cli(["backup", "--backup-dir",
                                                    str(root / "backups"), *extra])
                    self.assertEqual((code, stdout, stderr), (0, expected, ""))

    def test_unexpected_exceptions_propagate(self) -> None:
        with fixture_root() as root:
            manager = mock.Mock()
            manager.return_value.create.side_effect = RuntimeError("unexpected")
            with mock.patch.object(cli, "BackupManager", manager):
                with self.assertRaises(RuntimeError):
                    run_cli(["backup", "--backup-dir", str(root / "backups"), "--json"])

    def _checksum_failure(self, root: Path, destination: Path) -> dict[str, Any]:
        source = make_source(root)
        argv = ["backup", "--source", str(source), "--backup-dir", str(destination), "--json"]
        preflight = run_cli([*argv, "--dry-run"])
        self.assertEqual(preflight[0], 0)
        with mock.patch.object(BackupManager, "verify_archive",
                               side_effect=ValueError(CHECKSUM_ERROR)):
            envelope = self.assert_json_failure(run_cli(argv), "backup", changed=True)
        self.assertEqual(envelope["error"], CHECKSUM_ERROR)
        return envelope

    def _leftover_checkpoints(self, destination: Path, known: set[str]) -> list[Path]:
        return [path for path in sorted(destination.iterdir()) if path.name not in known]

    def test_checksum_failure_reports_change_and_leftover_checkpoint(self) -> None:
        with fixture_root() as root:
            destination = root / "new-root" / "backups"
            envelope = self._checksum_failure(root, destination)
            leftovers = self._leftover_checkpoints(destination, set())
            self.assertEqual(len(leftovers), 1)
            self.assertTrue((leftovers[0] / "openclaw-state.tar.gz").is_file())
            self.assertEqual(len(envelope["warnings"]), 1)
            self.assertIn(str(leftovers[0]), envelope["warnings"][0])
            self.assertIn("not a verified rollback checkpoint", envelope["warnings"][0])

    def test_checksum_failure_in_existing_root_names_only_new_checkpoint(self) -> None:
        with fixture_root() as root:
            destination = root / "backups"
            destination.mkdir(mode=0o700)
            destination.chmod(0o700)
            older = destination / "openclaw-20200101T000000.000000Z"
            older.mkdir(mode=0o700)
            envelope = self._checksum_failure(root, destination)
            leftovers = self._leftover_checkpoints(destination, {older.name})
            self.assertEqual(len(leftovers), 1)
            self.assertTrue((leftovers[0] / "openclaw-state.tar.gz").is_file())
            self.assertEqual(len(envelope["warnings"]), 1)
            self.assertIn(str(leftovers[0]), envelope["warnings"][0])
            self.assertNotIn(str(older), envelope["warnings"][0])

    def test_checksum_failure_text_mode_mentions_leftover(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            with mock.patch.object(BackupManager, "verify_archive",
                                   side_effect=ValueError(CHECKSUM_ERROR)):
                stderr = self.assert_text_failure(
                    run_cli(["backup", "--source", str(source), "--backup-dir",
                             str(destination)])
                )
            self.assertIn(CHECKSUM_ERROR, stderr)
            self.assertIn("not a verified rollback checkpoint", stderr)

    def test_unsafe_archive_message_is_one_line(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            error = ValueError("Unsafe archive member: openclaw/evil\nsecond line")
            with mock.patch.object(BackupManager, "verify_archive", side_effect=error):
                envelope = self.assert_json_failure(
                    run_cli(["backup", "--source", str(source), "--backup-dir",
                             str(root / "backups"), "--json"]),
                    "backup", changed=True,
                )
            self.assertEqual(envelope["error"], "Unsafe archive member: openclaw/evil second line")

    def test_unknown_value_error_does_not_disclose_contents(self) -> None:
        errors = [
            ValueError(f"invalid literal for int() with base 10: '{CONTENT_MARKER}'"),
            json.JSONDecodeError("Expecting value", f"{CONTENT_MARKER} payload", 0),
            UnicodeDecodeError("utf-8", CONTENT_MARKER.encode(), 0, 1, CONTENT_MARKER),
        ]
        with fixture_root() as root:
            for error in errors:
                manager = mock.Mock()
                manager.return_value.create.side_effect = error
                with mock.patch.object(cli, "BackupManager", manager):
                    argv = ["backup", "--backup-dir", str(root / "backups")]
                    for result in (run_cli(argv), run_cli([*argv, "--json"])):
                        self.assertEqual(result[0], 1)
                        self.assertNotIn(CONTENT_MARKER, result[1] + result[2])
                        self.assertNotIn("Traceback", result[1] + result[2])

    def test_os_error_text_does_not_disclose_contents(self) -> None:
        errors = [
            OSError(CONTENT_MARKER),
            PermissionError(f"Permission denied: {CONTENT_MARKER}"),
            OSError(errno.EIO, CONTENT_MARKER),
            OSError(errno.EIO, CONTENT_MARKER, "/tmp/acp-file"),
        ]
        with fixture_root() as root:
            for error in errors:
                manager = mock.Mock()
                manager.return_value.create.side_effect = error
                with mock.patch.object(cli, "BackupManager", manager):
                    argv = ["backup", "--backup-dir", str(root / "backups")]
                    envelope = self.assert_json_failure(run_cli([*argv, "--json"]), "backup",
                                                        changed=False)
                    self.assertNotIn(CONTENT_MARKER, json.dumps(envelope))
                    stderr = self.assert_text_failure(run_cli(argv))
                    self.assertNotIn(CONTENT_MARKER, stderr)
            manager = mock.Mock()
            manager.return_value.create.side_effect = errors[-1]
            with mock.patch.object(cli, "BackupManager", manager):
                envelope = self.assert_json_failure(
                    run_cli(["backup", "--backup-dir", str(root / "backups"), "--json"]),
                    "backup", changed=False,
                )
            self.assertEqual(envelope["error"], f"{os.strerror(errno.EIO)}: /tmp/acp-file")

    def test_inspection_failure_warns_without_claiming_a_change(self) -> None:
        with fixture_root() as root:
            destination = root / "backups"
            denied = PermissionError(errno.EACCES, "Permission denied", str(destination))
            with mock.patch.object(cli, "_missing_ancestors", side_effect=denied):
                envelope = self.assert_json_failure(
                    run_cli(["backup", "--source", str(root / "missing"), "--backup-dir",
                             str(destination), "--json"]),
                    "backup", changed=False,
                )
            self.assertIn("OpenClaw state directory not found", envelope["error"])
            self.assertEqual(len(envelope["warnings"]), 1)
            self.assertIn(f"Could not inspect {destination}", envelope["warnings"][0])


class InventoryCliTests(CliTestCase):
    def setUp(self) -> None:
        FakeCollector.error = None
        FakeCollector.calls = []
        patcher = mock.patch.object(cli, "InventoryCollector", FakeCollector)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = self.enterContext(fixture_root())
        self.repository = self.root / "repo"
        self.repository.mkdir()

    def argv(self, output: Path, *extra: str) -> list[str]:
        return ["inventory", "--output", str(output), "--repository", str(self.repository),
                *extra]

    def test_json_success_writes_output_and_envelope(self) -> None:
        output = self.root / "out.json"
        code, stdout, stderr = run_cli(self.argv(output, "--json"))
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(output.read_text()), FakeCollector.data)
        self.assertEqual(output.read_text(),
                         json.dumps(FakeCollector.data, indent=2, sort_keys=True) + "\n")
        envelope = json.loads(stdout)
        self.assert_envelope(envelope, "inventory")
        self.assertEqual(envelope, {
            "ok": True,
            "operation": "inventory",
            "changed": True,
            "checks": [{"name": "sanitized-inventory", "status": "passed"}],
            "warnings": [],
            "required_user_actions": [],
            "rollback_checkpoint": None,
            "output": str(output.resolve()),
        })
        self.assertEqual(FakeCollector.calls, [[self.repository]])

    def test_text_success_prints_inventory_data(self) -> None:
        output = self.root / "out.json"
        code, stdout, stderr = run_cli(self.argv(output))
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(stdout, json.dumps(FakeCollector.data, indent=2, sort_keys=True) + "\n")
        self.assertEqual(json.loads(output.read_text()), FakeCollector.data)

    def test_failure_before_mutation(self) -> None:
        output = self.root / "nested" / "out.json"
        FakeCollector.error = PermissionError(errno.EACCES, "Permission denied",
                                              str(self.repository))
        envelope = self.assert_json_failure(run_cli(self.argv(output, "--json")), "inventory",
                                            changed=False)
        self.assertEqual(envelope["error"], f"Permission denied: {self.repository}")
        self.assertFalse(output.parent.exists())
        stderr = self.assert_text_failure(run_cli(self.argv(output)))
        self.assertIn(f"Permission denied: {self.repository}", stderr)

    def test_failure_after_output_parent_created(self) -> None:
        output = self.root / "nested" / "out.json"

        def refuse(path: Path, *args: Any, **kwargs: Any) -> int:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))

        with mock.patch.object(Path, "write_text", refuse):
            envelope = self.assert_json_failure(run_cli(self.argv(output, "--json")),
                                                "inventory", changed=True)
        self.assertEqual(envelope["error"], f"Permission denied: {output}")
        self.assertTrue(output.parent.is_dir())
        self.assertFalse(output.exists())

    def test_failure_after_partial_nested_directory_creation(self) -> None:
        output = self.root / "a" / "b" / "out.json"

        def partial_mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
            os.mkdir(self.root / "a")
            raise PermissionError(errno.EACCES, "Permission denied", str(path))

        with mock.patch.object(Path, "mkdir", partial_mkdir):
            self.assert_json_failure(run_cli(self.argv(output, "--json")), "inventory",
                                     changed=True)
        self.assertTrue((self.root / "a").is_dir())
        self.assertFalse((self.root / "a" / "b").exists())

    def test_partial_write_to_new_file(self) -> None:
        output = self.root / "out.json"
        with mock.patch.object(Path, "write_text", partial_write):
            envelope = self.assert_json_failure(run_cli(self.argv(output, "--json")),
                                                "inventory", changed=True)
        self.assertEqual(envelope["error"], f"No space left on device: {output}")

    def test_partial_write_to_existing_file(self) -> None:
        output = self.root / "out.json"
        output.write_text("previous inventory\n")
        with mock.patch.object(Path, "write_text", partial_write):
            envelope = self.assert_json_failure(run_cli(self.argv(output, "--json")),
                                                "inventory", changed=True)
            stderr = self.assert_text_failure(run_cli(self.argv(output)))
        self.assertNotIn("previous inventory", json.dumps(envelope) + stderr)
        self.assertIn("No space left on device", stderr)

    def test_conversion_errors_do_not_disclose_contents(self) -> None:
        output = self.root / "out.json"
        for error in (
            ValueError(f"could not convert string to float: '{CONTENT_MARKER}'"),
            UnicodeDecodeError("utf-8", CONTENT_MARKER.encode(), 0, 1, "invalid start byte"),
        ):
            FakeCollector.error = error
            for argv in (self.argv(output), self.argv(output, "--json")):
                code, stdout, stderr = run_cli(argv)
                self.assertEqual(code, 1)
                self.assertNotIn(CONTENT_MARKER, stdout + stderr)
                self.assertNotIn("Traceback", stdout + stderr)
        self.assertFalse(output.exists())


class TemporaryDirectoryVariantTests(CliTestCase):
    """The suite must pass with TMPDIR=/tmp and TMPDIR=$HOME/.openclaw/tmp.
    The second case uses a disposable home under /tmp, not the real one."""

    @contextmanager
    def tmpdir(self, path: Path) -> Iterator[None]:
        path.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(tempfile, "tempdir", str(path)), \
                mock.patch.dict(os.environ, {"TMPDIR": str(path)}):
            yield

    def _exercise(self, root: Path) -> None:
        source = make_source(root)
        destination = root / "backups"
        code, stdout, stderr = run_cli(["backup", "--source", str(source), "--backup-dir",
                                        str(destination), "--json"])
        self.assertEqual((code, stderr), (0, ""))
        envelope = json.loads(stdout)
        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["checks"][2], {"name": "disposable-restore", "status": "passed"})
        self.assert_json_failure(
            run_cli(["backup", "--source", str(root / "missing"), "--backup-dir",
                     str(root / "other"), "--json"]),
            "backup", changed=False,
        )

    def test_tmpdir_under_tmp(self) -> None:
        with fixture_root() as root:
            with self.tmpdir(root / "tmp"):
                self._exercise(root)
                self.assertEqual(tempfile.gettempdir(), str(root / "tmp"))

    def test_tmpdir_under_disposable_home_openclaw_tmp(self) -> None:
        with fixture_root() as root:
            home = root / "home"
            with self.tmpdir(home / ".openclaw" / "tmp"), \
                    mock.patch.dict(os.environ, {"HOME": str(home)}):
                self._exercise(root)
                self.assertEqual(tempfile.gettempdir(), str(home / ".openclaw" / "tmp"))


if __name__ == "__main__":
    unittest.main()
