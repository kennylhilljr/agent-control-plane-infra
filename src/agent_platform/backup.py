from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class BackupResult:
    changed: bool
    verified: bool
    file_count: int
    checkpoint_dir: Path
    archive: Path
    manifest: Path
    link_count: int = 0


class SourceChangedDuringBackup(RuntimeError):
    pass


class BackupManager:
    EXCLUDED_TOP_LEVEL = {"logs", "tmp"}

    def __init__(self, source: Path, destination: Path) -> None:
        self.source = source.expanduser().resolve()
        self.destination = destination.expanduser().resolve()

    def create(self, *, dry_run: bool = False) -> BackupResult:
        if not self.source.is_dir():
            raise FileNotFoundError(f"OpenClaw state directory not found: {self.source}")
        if (
            self.destination == self.source
            or self.destination.is_relative_to(self.source)
            or self.source.is_relative_to(self.destination)
        ):
            raise ValueError(
                f"Backup destination must not overlap the source: "
                f"source={self.source} destination={self.destination}"
            )
        files, enum_stats, links = self._source_entries()
        checkpoint_name = datetime.now(UTC).strftime("openclaw-%Y%m%dT%H%M%S.%fZ")
        checkpoint = self.destination / checkpoint_name
        archive_path = checkpoint / "openclaw-state.tar.gz"
        manifest_path = checkpoint / "manifest.json"
        if dry_run:
            return BackupResult(False, False, len(files), checkpoint, archive_path, manifest_path,
                                len(links))

        self._prepare_destination(checkpoint)
        expected: dict[str, str] = {}
        post_hash_stats: dict[Path, tuple[int, int, int, int]] = {}
        for path in files:
            relative_posix = str(PurePosixPath(*path.relative_to(self.source).parts))
            pre_hash_snap = _checked_snapshot(path, relative_posix)
            if pre_hash_snap != enum_stats[path]:
                raise _source_changed(relative_posix)
            try:
                digest = _sha256(path)
            except FileNotFoundError as error:
                raise _source_changed(relative_posix) from error
            except OSError as error:
                # An unreadable but unchanged file (EACCES, EIO, EMFILE) keeps
                # its own error: stopping the Gateway would not fix it.
                if _checked_snapshot(path, relative_posix) != pre_hash_snap:
                    raise _source_changed(relative_posix) from error
                raise
            post_hash_snap = _checked_snapshot(path, relative_posix)
            if post_hash_snap != pre_hash_snap:
                raise _source_changed(relative_posix)
            post_hash_stats[path] = post_hash_snap
            expected[relative_posix] = digest
        with tarfile.open(archive_path, "w:gz") as archive:
            self._after_archive_opened(archive)
            for path in files:
                relative = path.relative_to(self.source)
                relative_posix = str(PurePosixPath(*relative.parts))
                pre_add_snap = _checked_snapshot(path, relative_posix)
                if pre_add_snap != post_hash_stats[path]:
                    raise _source_changed(relative_posix)
                try:
                    archive.add(path, arcname=str(PurePosixPath("openclaw", *relative.parts)),
                                recursive=False)
                except OSError as error:
                    # The error may come from writing the archive (a full
                    # disk, say), so only blame the source if it changed.
                    if _checked_snapshot(path, relative_posix) != pre_add_snap:
                        raise _source_changed(relative_posix) from error
                    raise
                self._after_tarfile_add(path, PurePosixPath(*relative.parts))
                post_add_snap = _checked_snapshot(path, relative_posix)
                if post_add_snap != pre_add_snap:
                    raise _source_changed(relative_posix)
            # A file that passed its own post-add check can still be rewritten
            # while later files are archived, so check every file once more.
            for path in files:
                relative_posix = str(PurePosixPath(*path.relative_to(self.source).parts))
                if _checked_snapshot(path, relative_posix) != post_hash_stats[path]:
                    raise _source_changed(relative_posix)
            # A file or link created or removed after enumeration would be
            # missing from (or stale in) the checkpoint, so walk the tree again.
            now_files, now_links = self._scan()
            added_or_removed = sorted(
                {_relative_posix(self.source, path) for path in set(now_files) ^ set(files)}
                | {name for name in set(now_links) ^ set(links)}
                | {name for name in set(now_links) & set(links)
                   if now_links[name] != links[name]}
            )
            if added_or_removed:
                raise _source_changed(added_or_removed[0])
        archive_path.chmod(0o600)
        self.verify_archive(archive_path, expected)
        archive_sha256 = _sha256(archive_path)
        checksum_path = archive_path.with_name(archive_path.name + ".sha256")
        _write_private(checksum_path, f"{archive_sha256}  {archive_path.name}\n")
        file_metadata = {
            str(PurePosixPath(*path.relative_to(self.source).parts)): {
                "size": post_hash_stats[path][0],
                "mode": f"{stat.S_IMODE(post_hash_stats[path][3]):04o}",
            }
            for path in files
        }
        manifest = {
            "schema_version": "1.1",
            "created_at": datetime.now(UTC).isoformat(),
            "source": str(self.source),
            "excluded_top_level": sorted(self.EXCLUDED_TOP_LEVEL),
            "archive": archive_path.name,
            "archive_sha256": archive_sha256,
            "checksum_file": checksum_path.name,
            "file_count": len(expected),
            "files": expected,
            # Per-file size in bytes and permission bits as a 4-digit octal
            # string, taken from the snapshot that was hashed and archived.
            "file_metadata": file_metadata,
            # Symbolic links are recorded with their targets, never followed
            # and never archived, so nothing outside the source is copied.
            "symlinks": links,
            "symlink_policy": "recorded-not-followed",
            "restore_verified": True,
        }
        _write_private(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return BackupResult(True, True, len(files), checkpoint, archive_path, manifest_path,
                            len(links))

    def _source_files(self) -> list[Path]:
        return self._source_entries()[0]

    def _source_entries(
        self,
    ) -> tuple[list[Path], dict[Path, tuple[int, int, int, int]], dict[str, str]]:
        """Regular files to archive with their enumeration-time lstat
        snapshots, and symbolic links (relative path to target) to record.
        Links are never followed: rglob does not descend into symlinked
        directories, and a link's target is read, not opened."""
        files, links = self._scan()
        enum_stats = {
            path: _checked_snapshot(path, _relative_posix(self.source, path)) for path in files
        }
        self._after_enumeration()
        return files, enum_stats, links

    def _scan(self) -> tuple[list[Path], dict[str, str]]:
        """Walk the source once: sorted regular files and sorted links."""
        files: list[Path] = []
        links: dict[str, str] = {}
        for path in self.source.rglob("*"):
            relative = path.relative_to(self.source)
            if relative.parts and relative.parts[0] in self.EXCLUDED_TOP_LEVEL:
                continue
            relative_posix = str(PurePosixPath(*relative.parts))
            try:
                if path.is_symlink():
                    links[relative_posix] = os.readlink(path)
                    continue
            except FileNotFoundError as error:
                raise _source_changed(relative_posix) from error
            if path.is_file():
                files.append(path)
        return sorted(files), dict(sorted(links.items()))

    # Phase hooks. They do nothing in production; tests patch them to change
    # the source tree between backup phases.
    def _after_enumeration(self) -> None:
        pass

    def _after_archive_opened(self, archive: tarfile.TarFile) -> None:
        pass

    def _after_tarfile_add(self, path: Path, relative: PurePosixPath) -> None:
        pass

    def _prepare_destination(self, checkpoint: Path) -> None:
        if self.destination.exists():
            if not self.destination.is_dir():
                raise NotADirectoryError(self.destination)
            if self.destination.stat().st_mode & 0o077:
                raise PermissionError(
                    f"Backup root must not grant group/other access: {self.destination}"
                )
        else:
            self.destination.mkdir(parents=True, mode=0o700)
        checkpoint.mkdir(mode=0o700)

    @staticmethod
    def verify_archive(archive_path: Path, expected: dict[str, str], *,
                       restore_root: Path | None = None) -> None:
        """Restore the archive into a new 0700 folder under restore_root
        (default: the archive's folder) and compare checksums. The folder is
        removed when verification ends, pass or fail; nothing is created
        under tempfile.gettempdir()."""
        if restore_root is None:
            restore_root = archive_path.parent
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts:
                    raise ValueError(f"Unsafe archive path: {member.name}")
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError(f"Unsafe archive member: {member.name}")
            # mkdtemp creates the folder with mode 0700.
            restore = Path(tempfile.mkdtemp(prefix=".restore-check-", dir=restore_root))
            try:
                archive.extractall(restore, filter="data")
                restored_root = restore / "openclaw"
                actual = {
                    str(path.relative_to(restored_root)): _sha256(path)
                    for path in sorted(restored_root.rglob("*"))
                    if path.is_file()
                }
            except BaseException:
                # Keep the error that explains the failure; cleanup is best effort.
                shutil.rmtree(restore, ignore_errors=True)
                raise
            shutil.rmtree(restore)
        if actual != expected:
            raise ValueError("Disposable restore checksums do not match source snapshot")


def _write_private(path: Path, text: str) -> None:
    """Create path with mode 0600 from the start, never wider."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
    path.chmod(0o600)


def _stat_snapshot(path: Path) -> tuple[int, int, int, int]:
    result = os.lstat(path)
    return (result.st_size, result.st_mtime_ns, result.st_ino, result.st_mode)


def _relative_posix(source: Path, path: Path) -> str:
    return str(PurePosixPath(*path.relative_to(source).parts))


def _source_changed(relative_posix: str) -> SourceChangedDuringBackup:
    return SourceChangedDuringBackup(
        f"Source file changed during backup: {relative_posix}. Stop the Gateway and retry."
    )


def _checked_snapshot(path: Path, relative_posix: str) -> tuple[int, int, int, int]:
    try:
        return _stat_snapshot(path)
    except OSError as error:
        raise _source_changed(relative_posix) from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

