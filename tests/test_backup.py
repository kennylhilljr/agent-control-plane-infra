from __future__ import annotations

import errno
import hashlib
import inspect
import json
import os
import tarfile
import tempfile
import sys
import unittest
import unittest.mock as mock
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent_platform.backup as backup
from agent_platform.backup import BackupManager

TARGET = "cron/jobs.json"


def _make_source(root: Path) -> Path:
    source = root / ".openclaw"
    (source / "cron").mkdir(parents=True)
    (source / "openclaw.json").write_text('{"mode":"test"}')
    (source / "cron" / "jobs.json").write_text('{"jobs":[]}')
    return source


def _rewrite(path: Path) -> None:
    stat = path.stat()
    path.write_text('{"jobs":["changed during backup"]}')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


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

    def test_symlinks_are_recorded_not_followed(self) -> None:
        """OpenClaw 2026.9 keeps symlinks such as plugin-skills/canvas. The
        backup records each link and its target in the manifest, never follows
        it, and never copies what it points to."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            (outside / "elsewhere.txt").write_text("OUTSIDE-CONTENT")
            source = root / ".openclaw"
            (source / "plugin-skills").mkdir(parents=True)
            (source / "openclaw.json").write_text("{}")
            (source / "plugin-skills" / "canvas").symlink_to(outside)
            (source / "link-file").symlink_to(outside / "elsewhere.txt")
            destination = root / "backups"

            dry = BackupManager(source, destination).create(dry_run=True)
            self.assertEqual((dry.file_count, dry.link_count), (1, 2))
            self.assertFalse(destination.exists())

            result = BackupManager(source, destination).create()
            self.assertTrue(result.verified)
            self.assertEqual((result.file_count, result.link_count), (1, 2))
            manifest = json.loads(result.manifest.read_text())
            self.assertEqual(manifest["symlinks"], {
                "link-file": str(outside / "elsewhere.txt"),
                "plugin-skills/canvas": str(outside),
            })
            self.assertEqual(sorted(manifest["files"]), ["openclaw.json"])
            with tarfile.open(result.archive, "r:gz") as archive:
                members = archive.getmembers()
                self.assertFalse(any(m.issym() or m.islnk() for m in members))
                for member in members:
                    if member.isfile():
                        data = archive.extractfile(member).read()
                        self.assertNotIn(b"OUTSIDE-CONTENT", data)

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

    def _assert_overlap_refused(self, source: Path, destination: Path) -> None:
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaisesRegex(ValueError, "source") as caught:
                    BackupManager(source, destination).create(dry_run=dry_run)
                message = str(caught.exception)
                self.assertIn(str(source.resolve()), message)
                self.assertIn(str(destination.resolve()), message)

    def test_destination_equal_to_source_is_refused(self) -> None:
        """test_destination_equal_to_source_is_refused: normal and dry-run
        backups refuse a destination equal to the source."""
        with tempfile.TemporaryDirectory() as directory:
            source = _make_source(Path(directory))
            self._assert_overlap_refused(source, source)

    def test_destination_inside_source_is_refused(self) -> None:
        """test_destination_inside_source_is_refused: normal and dry-run
        backups refuse a destination inside the source."""
        with tempfile.TemporaryDirectory() as directory:
            source = _make_source(Path(directory))
            self._assert_overlap_refused(source, source / "nested-backups")
            self.assertFalse((source / "nested-backups").exists())

    def test_destination_contains_source_is_refused(self) -> None:
        """test_destination_contains_source_is_refused: normal and dry-run
        backups refuse a destination that contains the source."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "wrapper"
            parent.mkdir()
            source = _make_source(parent)
            self._assert_overlap_refused(source, parent)

    def test_tmp_excluded_from_manifest(self) -> None:
        """test_tmp_excluded_from_manifest: the top-level tmp/ directory is
        left out of the manifest and the archive."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ".openclaw"
            (source / "tmp").mkdir(parents=True)
            (source / "openclaw.json").write_text("{}")
            (source / "tmp" / "scratch.bin").write_bytes(b"scratch")

            result = BackupManager(source, root / "backups").create()

            manifest = json.loads(result.manifest.read_text())
            self.assertNotIn("tmp/scratch.bin", manifest["files"])
            self.assertIn("tmp", manifest["excluded_top_level"])
            with tarfile.open(result.archive, "r:gz") as archive:
                self.assertNotIn("openclaw/tmp/scratch.bin", archive.getnames())

    def test_source_changed_exception_is_runtime_error_subclass(self) -> None:
        """test_source_changed_exception_is_runtime_error_subclass:
        SourceChangedDuringBackup exists and subclasses RuntimeError."""
        self.assertTrue(hasattr(backup, "SourceChangedDuringBackup"))
        self.assertTrue(issubclass(backup.SourceChangedDuringBackup, RuntimeError))

    def _run_race(self, patcher_factory, state: dict[str, bool]) -> None:
        exc_cls = getattr(backup, "SourceChangedDuringBackup", None)
        self.assertIsNotNone(exc_cls, "SourceChangedDuringBackup missing")
        self.assertTrue(issubclass(exc_cls, RuntimeError))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_source(root)
            target = (source / "cron" / "jobs.json").resolve()
            with patcher_factory(target):
                try:
                    BackupManager(source, root / "backups").create()
                except Exception as exc:  # the type is asserted below
                    caught = exc
                else:
                    self.fail("create() did not detect the source change")
        self.assertTrue(state["ran"], "injection did not fire")
        self.assertIsInstance(caught, exc_cls)
        self.assertIn(TARGET, str(caught))
        self.assertIn("Stop the Gateway and retry.", str(caught))

    def _sha256_failing_with(self, error: type[OSError]) -> None:
        state = {"ran": False}
        real_sha256 = backup._sha256

        def factory(target: Path):
            def side_effect(path: Path) -> str:
                if path == target:
                    state["ran"] = True
                    if error is FileNotFoundError:
                        target.unlink()
                    else:
                        _rewrite(target)
                    raise error("injected")
                return real_sha256(path)
            return mock.patch.object(backup, "_sha256", side_effect=side_effect)

        self._run_race(factory, state)

    def test_sha256_filenotfound_raises_source_changed(self) -> None:
        """test_sha256_filenotfound_raises_source_changed: a FileNotFoundError
        while hashing becomes SourceChangedDuringBackup."""
        self._sha256_failing_with(FileNotFoundError)

    def test_sha256_oserror_raises_source_changed(self) -> None:
        """test_sha256_oserror_raises_source_changed: an OSError while
        hashing becomes SourceChangedDuringBackup."""
        self._sha256_failing_with(OSError)

    def test_sha256_oserror_on_unchanged_file_keeps_its_error(self) -> None:
        """An unreadable but unchanged file keeps its own OSError, since
        stopping the Gateway would not fix it."""
        real_sha256 = backup._sha256

        def side_effect(path: Path) -> str:
            if path.name == "jobs.json":
                raise OSError(errno.EIO, "Input/output error")
            return real_sha256(path)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_source(root)
            with mock.patch.object(backup, "_sha256", side_effect=side_effect):
                with self.assertRaises(OSError) as raised:
                    BackupManager(source, root / "backups").create()
        self.assertNotIsInstance(raised.exception, backup.SourceChangedDuringBackup)
        self.assertEqual(raised.exception.errno, errno.EIO)

    def _created_after_enumeration(self, make) -> None:
        exc_cls = backup.SourceChangedDuringBackup
        state = {"ran": False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_source(root)

            def hook(manager: BackupManager, path: Path, relative: PurePosixPath) -> None:
                if not state["ran"]:
                    state["ran"] = True
                    make(source)

            with mock.patch.object(backup.BackupManager, "_after_tarfile_add",
                                   autospec=True, side_effect=hook):
                with self.assertRaises(exc_cls) as raised:
                    BackupManager(source, root / "backups").create()
        self.assertTrue(state["ran"])
        self.assertIn("cron/new", str(raised.exception))
        self.assertIn("Stop the Gateway and retry.", str(raised.exception))

    def test_file_created_after_enumeration_raises(self) -> None:
        self._created_after_enumeration(
            lambda source: (source / "cron" / "new-job.json").write_text("{}"))

    def test_symlink_created_after_enumeration_raises(self) -> None:
        self._created_after_enumeration(
            lambda source: (source / "cron" / "new-link").symlink_to("jobs.json"))

    def test_file_changed_after_enumeration_before_hashing_raises(self) -> None:
        """test_file_changed_after_enumeration_before_hashing_raises: a
        rewrite between enumeration and hashing fails the pre-hash check."""
        state = {"ran": False}

        def factory(target: Path):
            def side_effect(manager: BackupManager) -> None:
                state["ran"] = True
                _rewrite(target)
            return mock.patch.object(backup.BackupManager, "_after_enumeration",
                                     autospec=True, side_effect=side_effect)

        self._run_race(factory, state)

    def _archive_opened_hook(self, action) -> None:
        state = {"ran": False}

        def factory(target: Path):
            def side_effect(manager: BackupManager, archive: tarfile.TarFile) -> None:
                state["ran"] = True
                action(target)
            return mock.patch.object(backup.BackupManager, "_after_archive_opened",
                                     autospec=True, side_effect=side_effect)

        self._run_race(factory, state)

    def test_file_changed_after_archive_opened_before_add_raises(self) -> None:
        """test_file_changed_after_archive_opened_before_add_raises: a
        rewrite after hashing and before tarfile.add fails the pre-add
        check."""
        self._archive_opened_hook(_rewrite)

    def test_pre_add_lstat_oserror_after_archive_opened_raises(self) -> None:
        """test_pre_add_lstat_oserror_after_archive_opened_raises: deleting
        the file before tarfile.add makes the pre-add lstat fail, and the
        error is translated."""
        self._archive_opened_hook(lambda target: target.unlink())

    def _tarfile_add_hook(self, action: Callable[[Path], None],
                          trigger: str = TARGET) -> None:
        state = {"ran": False}

        def factory(target: Path) -> AbstractContextManager[object]:
            def side_effect(manager: BackupManager, path: Path,
                            relative: PurePosixPath) -> None:
                if str(relative) == trigger:
                    state["ran"] = True
                    action(target)
            return mock.patch.object(backup.BackupManager, "_after_tarfile_add",
                                     autospec=True, side_effect=side_effect)

        self._run_race(factory, state)

    def test_file_deleted_after_tarfile_add_raises(self) -> None:
        """test_file_deleted_after_tarfile_add_raises: deleting the file
        right after tarfile.add fails the post-add check."""
        self._tarfile_add_hook(lambda target: target.unlink())

    def test_file_modified_after_tarfile_add_raises(self) -> None:
        """test_file_modified_after_tarfile_add_raises: rewriting the file
        right after tarfile.add fails the post-add check."""
        self._tarfile_add_hook(_rewrite)

    def test_file_mode_changed_after_tarfile_add_raises(self) -> None:
        """test_file_mode_changed_after_tarfile_add_raises: a mode-only
        change after tarfile.add fails the four-field post-add check."""
        def chmod_only(target: Path) -> None:
            before = target.stat()
            os.chmod(target, (before.st_mode & 0o777) ^ 0o100)
            after = target.stat()
            self.assertEqual((before.st_size, before.st_mtime_ns),
                             (after.st_size, after.st_mtime_ns))
            self.assertNotEqual(before.st_mode, after.st_mode)

        self._tarfile_add_hook(chmod_only)

    def test_post_add_lstat_oserror_raises(self) -> None:
        """test_post_add_lstat_oserror_raises: deleting the file after
        tarfile.add makes the post-add lstat fail, and the error is
        translated."""
        self._tarfile_add_hook(lambda target: target.unlink())

    def test_earlier_file_modified_while_later_file_added_raises(self) -> None:
        """test_earlier_file_modified_while_later_file_added_raises: rewriting
        an already archived file while a later file is added fails the final
        check over every file."""
        self._tarfile_add_hook(_rewrite, trigger="openclaw.json")

    def test_earlier_file_deleted_while_later_file_added_raises(self) -> None:
        """test_earlier_file_deleted_while_later_file_added_raises: deleting
        an already archived file while a later file is added fails the final
        check, and the lstat error is translated."""
        self._tarfile_add_hook(lambda target: target.unlink(),
                               trigger="openclaw.json")

    def test_archive_write_enospc_is_not_reported_as_source_change(self) -> None:
        """test_archive_write_enospc_is_not_reported_as_source_change: a full
        destination while tarfile.add writes the archive keeps its ENOSPC
        error instead of blaming the unchanged source."""
        state = {"ran": False}
        real_add = tarfile.TarFile.add

        def add(archive: tarfile.TarFile, name: Path, *args, **kwargs) -> None:
            if Path(name).name == "jobs.json":
                state["ran"] = True
                raise OSError(errno.ENOSPC, "No space left on device")
            real_add(archive, name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_source(root)
            with mock.patch.object(tarfile.TarFile, "add", autospec=True, side_effect=add):
                with self.assertRaises(OSError) as raised:
                    BackupManager(source, root / "backups").create()
        self.assertTrue(state["ran"], "injection did not fire")
        self.assertNotIsInstance(raised.exception, backup.SourceChangedDuringBackup)
        self.assertEqual(raised.exception.errno, errno.ENOSPC)

    def test_tarfile_add_oserror_after_source_change_raises(self) -> None:
        """test_tarfile_add_oserror_after_source_change_raises: an OSError
        from tarfile.add when the source file did change is still reported
        as a source change."""
        state = {"ran": False}

        def factory(target: Path) -> AbstractContextManager[object]:
            real_add = tarfile.TarFile.add

            def add(archive: tarfile.TarFile, name: Path, *args, **kwargs) -> None:
                if Path(name) == target:
                    state["ran"] = True
                    _rewrite(target)
                    raise OSError("injected read failure")
                real_add(archive, name, *args, **kwargs)
            return mock.patch.object(tarfile.TarFile, "add", autospec=True, side_effect=add)

        self._run_race(factory, state)



class _CheckpointAssertions:
    """Checks for the in-checkpoint restore, the .sha256 file and the 1.1
    manifest. Subclasses choose where TMPDIR and HOME point."""

    def _environment(self, root: Path) -> dict[str, str]:
        raise NotImplementedError

    def _temp_root(self, root: Path) -> Path:
        raise NotImplementedError

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.watched = self._temp_root(self.root)
        self.watched.mkdir(parents=True, exist_ok=True)
        env = mock.patch.dict(os.environ, self._environment(self.root))
        env.start()
        self.addCleanup(env.stop)
        tempdir = mock.patch.object(tempfile, "tempdir", str(self.watched))
        tempdir.start()
        self.addCleanup(tempdir.stop)
        self.source = _make_source(self.root / "state")
        (self.source / "cron" / "jobs.json").chmod(0o640)
        (self.source / "openclaw.json").chmod(0o600)
        self.destination = self.root / "backups"

    def _watched_entries(self) -> list[str]:
        return sorted(path.name for path in self.watched.iterdir())

    def test_restore_runs_inside_checkpoint_and_is_removed(self) -> None:
        self.assertEqual(tempfile.gettempdir(), str(self.watched))
        seen: dict[str, object] = {}
        real_sha256 = backup._sha256

        def spy(path: Path) -> str:
            path = Path(path)
            for parent in path.parents:
                if parent.name.startswith(".restore-check-"):
                    seen["restore"] = parent
                    seen["mode"] = parent.stat().st_mode & 0o777
            return real_sha256(path)

        with mock.patch.object(backup, "_sha256", side_effect=spy):
            result = BackupManager(self.source, self.destination).create()
        self.assertIn("restore", seen, "restore did not run inside the checkpoint")
        self.assertEqual(Path(seen["restore"]).parent, result.checkpoint_dir)
        self.assertEqual(seen["mode"], 0o700)
        self.assertEqual(
            sorted(path.name for path in result.checkpoint_dir.iterdir()),
            ["manifest.json", "openclaw-state.tar.gz", "openclaw-state.tar.gz.sha256"],
        )
        self.assertEqual(self._watched_entries(), [])

    def test_failed_verification_removes_restore_folder(self) -> None:
        self.assertIn("restore_root", inspect.signature(BackupManager.verify_archive).parameters)
        result = BackupManager(self.source, self.destination).create()
        with self.assertRaisesRegex(ValueError, "checksums do not match"):
            BackupManager.verify_archive(result.archive, {"openclaw.json": "0" * 64})
        with self.assertRaises(ValueError):
            BackupManager.verify_archive(result.archive, {}, restore_root=self.root)
        leftovers = [path.name for path in result.checkpoint_dir.iterdir()
                     if path.name.startswith(".restore-check-")]
        leftovers += [path.name for path in self.root.iterdir()
                      if path.name.startswith(".restore-check-")]
        self.assertEqual(leftovers, [])
        self.assertEqual(self._watched_entries(), [])

    def test_checksum_file_matches_archive(self) -> None:
        result = BackupManager(self.source, self.destination).create()
        checksum = result.archive.with_name("openclaw-state.tar.gz.sha256")
        self.assertTrue(checksum.is_file(), "openclaw-state.tar.gz.sha256 missing")
        self.assertEqual(checksum.stat().st_mode & 0o777, 0o600)
        digest = hashlib.sha256(result.archive.read_bytes()).hexdigest()
        self.assertEqual(checksum.read_text(), f"{digest}  openclaw-state.tar.gz\n")
        manifest = json.loads(result.manifest.read_text())
        self.assertEqual(manifest["archive_sha256"], digest)
        self.assertEqual(manifest["checksum_file"], "openclaw-state.tar.gz.sha256")

    def test_corrupted_archive_fails_verification(self) -> None:
        result = BackupManager(self.source, self.destination).create()
        manifest = json.loads(result.manifest.read_text())
        data = bytearray(result.archive.read_bytes())
        data[len(data) // 2] ^= 0xFF
        result.archive.write_bytes(bytes(data))
        self.assertNotEqual(hashlib.sha256(bytes(data)).hexdigest(),
                            manifest["archive_sha256"])
        with self.assertRaises((ValueError, tarfile.TarError, OSError, EOFError)):
            BackupManager.verify_archive(result.archive, manifest["files"])
        self.assertEqual(
            [path.name for path in result.checkpoint_dir.iterdir()
             if path.name.startswith(".restore-check-")], [])

    def test_manifest_records_size_and_mode(self) -> None:
        result = BackupManager(self.source, self.destination).create()
        manifest = json.loads(result.manifest.read_text())
        self.assertEqual(manifest["schema_version"], "1.1")
        self.assertEqual(manifest["file_metadata"], {
            "cron/jobs.json": {"size": len('{"jobs":[]}'), "mode": "0640"},
            "openclaw.json": {"size": len('{"mode":"test"}'), "mode": "0600"},
        })
        self.assertEqual(sorted(manifest["files"]), sorted(manifest["file_metadata"]))


class CheckpointWithTmpdirInFakeHomeTests(_CheckpointAssertions, unittest.TestCase):
    def _temp_root(self, root: Path) -> Path:
        return root / "home" / ".openclaw" / "tmp"

    def _environment(self, root: Path) -> dict[str, str]:
        return {"HOME": str(root / "home"), "TMPDIR": str(self._temp_root(root))}


class CheckpointWithTmpdirUnderTmpTests(_CheckpointAssertions, unittest.TestCase):
    """TMPDIR is a fresh folder under /tmp, so it can be watched for leftovers."""

    def _temp_root(self, root: Path) -> Path:
        return root / "tmp"

    def _environment(self, root: Path) -> dict[str, str]:
        return {"HOME": str(root / "home"), "TMPDIR": str(self._temp_root(root))}


if __name__ == "__main__":
    unittest.main()
