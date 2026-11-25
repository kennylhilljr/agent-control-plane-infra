from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_platform import cli
from agent_platform.backup import (
    MOUNT_TIMEOUT_SECONDS,
    BackupManager,
    is_on_local_filesystem,
    local_mount_points,
)
from agent_platform.inventory import CommandResult

REFUSED = "Unencrypted backup refused for a destination not confirmed local: "


class FakeMount:
    """Stands in for run_command running `mount`: returns fixed output and
    records each call. Any other command fails the test."""

    def __init__(self, stdout: str = "", *, returncode: int | None = 0,
                 timed_out: bool = False) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.timed_out = timed_out
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(self, command: tuple[str, ...], timeout: float = 5.0) -> CommandResult:
        if command != ("mount",):
            raise AssertionError(f"unexpected command: {command!r}")
        self.calls.append((command, timeout))
        return CommandResult(self.returncode, self.stdout, "", self.timed_out)


@contextmanager
def fixture_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="acp-mount-test-", dir="/tmp") as directory:
        yield Path(directory).resolve()


def make_source(root: Path) -> Path:
    source = root / "source"
    source.mkdir()
    (source / "openclaw.json").write_text('{"mode":"test"}')
    return source


def darwin_line(point: Path, options: str) -> str:
    return f"//user@nas.example/share on {point} ({options})"


def linux_line(point: Path, fstype: str) -> str:
    return f"server.example:/export on {point} type {fstype} (rw,relatime)"


class LocalMountPointsTests(unittest.TestCase):
    def test_darwin_uses_the_local_flag(self) -> None:
        output = "\n".join([
            "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)",
            "/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse)",
            "//user@nas.example/share on /Volumes/share (smbfs, nodev, nosuid, mounted by u)",
            "server.example:/export on /Volumes/nfs (nfs, asynchronous)",
            "map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)",
            "/Applications/A B.app/Wrapper on /private/var/x y (nullfs, local, read-only)",
            "not a mount line",
        ])
        self.assertEqual(local_mount_points(output, "darwin"), [
            Path("/"), Path("/System/Volumes/Data"), Path("/private/var/x y"),
        ])

    def test_local_flag_must_be_a_whole_option(self) -> None:
        output = "//u@h/s on /Volumes/s (smbfs, nolocal, localhost)"
        self.assertEqual(local_mount_points(output, "darwin"), [])

    def test_linux_allows_only_listed_local_types(self) -> None:
        output = "\n".join([
            "/dev/sda1 on / type ext4 (rw,relatime)",
            "tmpfs on /tmp type tmpfs (rw,nosuid)",
            "overlay on /var/lib/x type overlay (rw)",
            "server:/export on /mnt/nfs type nfs4 (rw)",
            "//nas/share on /mnt/smb type cifs (rw)",
            "u@h:/ on /mnt/ssh dir type fuse.sshfs (rw)",
            "drvfs on /mnt/c type 9p (rw)",
            "x on /mnt/unknown type somethingnew (rw)",
        ])
        self.assertEqual(local_mount_points(output, "linux"), [
            Path("/"), Path("/tmp"), Path("/var/lib/x"),
        ])

    def test_unsupported_platform_returns_none(self) -> None:
        self.assertIsNone(local_mount_points("/dev/x on / (ufs, local)", "freebsd14"))
        self.assertIsNone(local_mount_points("C: on / type ntfs (rw)", "win32"))


class IsOnLocalFilesystemTests(unittest.TestCase):
    def test_local_destination_is_confirmed(self) -> None:
        with fixture_root() as root:
            fake = FakeMount(darwin_line(root, "apfs, local, journaled"))
            self.assertTrue(is_on_local_filesystem(root, fake, "darwin"))
            self.assertEqual(fake.calls, [(("mount",), MOUNT_TIMEOUT_SECONDS)])

    def test_linux_local_destination_is_confirmed(self) -> None:
        with fixture_root() as root:
            self.assertTrue(is_on_local_filesystem(root, FakeMount(linux_line(root, "ext4")),
                                                   "linux"))

    def test_network_mount_is_not_local(self) -> None:
        with fixture_root() as root:
            for platform, output in (
                ("darwin", darwin_line(root, "smbfs, nodev, nosuid, mounted by u")),
                ("darwin", darwin_line(root, "nfs, asynchronous")),
                ("darwin", darwin_line(root, "webdav, nodev")),
                ("linux", linux_line(root, "nfs4")),
                ("linux", linux_line(root, "cifs")),
                ("linux", linux_line(root, "fuse.sshfs")),
            ):
                self.assertFalse(is_on_local_filesystem(root, FakeMount(output), platform),
                                 output)

    def test_missing_destination_uses_nearest_existing_ancestor(self) -> None:
        with fixture_root() as root:
            destination = root / "not" / "yet" / "created"
            local = FakeMount(darwin_line(root, "apfs, local"))
            remote = FakeMount(darwin_line(root, "smbfs"))
            self.assertTrue(is_on_local_filesystem(destination, local, "darwin"))
            self.assertFalse(is_on_local_filesystem(destination, remote, "darwin"))

    def test_match_uses_device_not_path_text(self) -> None:
        with fixture_root() as root:
            # A path through a symlink still matches the folder it points to.
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real")
            fake = FakeMount(darwin_line(root / "real", "apfs, local"))
            self.assertTrue(is_on_local_filesystem(root / "link" / "new", fake, "darwin"))
            # A local entry whose mount point does not exist confirms nothing.
            gone = FakeMount(darwin_line(root / "missing", "apfs, local"))
            self.assertFalse(is_on_local_filesystem(root, gone, "darwin"))

    def test_failures_are_not_local(self) -> None:
        with fixture_root() as root:
            line = darwin_line(root, "apfs, local")
            for fake in (FakeMount(line, returncode=1), FakeMount(line, returncode=None),
                         FakeMount(line, returncode=None, timed_out=True), FakeMount("")):
                self.assertFalse(is_on_local_filesystem(root, fake, "darwin"))

    def test_unsupported_platform_is_not_local_and_runs_nothing(self) -> None:
        with fixture_root() as root:
            fake = FakeMount(darwin_line(root, "apfs, local"))
            self.assertFalse(is_on_local_filesystem(root, fake, "win32"))
            self.assertEqual(fake.calls, [])


class BackupMountRefusalTests(unittest.TestCase):
    def test_unencrypted_backup_to_network_mount_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            fake = FakeMount(darwin_line(root, "smbfs, nodev, nosuid"))
            for dry_run in (True, False):
                manager = BackupManager(source, destination, run=fake, platform="darwin")
                with self.assertRaises(ValueError) as caught:
                    manager.create(dry_run=dry_run)
                self.assertTrue(str(caught.exception).startswith(REFUSED))
            self.assertFalse(destination.exists())

    def test_unencrypted_backup_with_unknown_mount_is_refused(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            manager = BackupManager(source, root / "backups", run=FakeMount(returncode=1),
                                    platform="darwin")
            with self.assertRaisesRegex(ValueError, REFUSED):
                manager.create(dry_run=True)

    def test_unencrypted_backup_to_local_mount_succeeds(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            fake = FakeMount(darwin_line(root, "apfs, local"))
            result = BackupManager(source, root / "backups", run=fake,
                                   platform="darwin").create()
            self.assertTrue(result.verified)
            self.assertFalse(result.encrypted)
            self.assertEqual(len(fake.calls), 1)

    def test_allow_unencrypted_skips_the_mount_check(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            fake = FakeMount(darwin_line(root, "smbfs"))
            result = BackupManager(source, root / "backups", run=fake, platform="darwin",
                                   allow_unencrypted=True).create()
            self.assertTrue(result.verified)
            self.assertEqual(fake.calls, [])

    def test_cli_reports_the_refusal(self) -> None:
        with fixture_root() as root:
            source = make_source(root)
            destination = root / "backups"
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch("agent_platform.backup.is_on_local_filesystem",
                            return_value=False), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(["backup", "--source", str(source), "--backup-dir",
                                 str(destination), "--dry-run", "--json"])
            self.assertEqual(code, 1)
            envelope = json.loads(stdout.getvalue())
            self.assertFalse(envelope["ok"])
            self.assertTrue(envelope["error"].startswith(REFUSED))
            self.assertIn("--allow-unencrypted", envelope["error"])
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
