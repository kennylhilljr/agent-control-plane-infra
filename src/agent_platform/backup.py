from __future__ import annotations

import hashlib
import json
import os
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
            except OSError as error:
                raise _source_changed(relative_posix) from error
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
                    raise _source_changed(relative_posix) from error
                self._after_tarfile_add(path, PurePosixPath(*relative.parts))
                post_add_snap = _checked_snapshot(path, relative_posix)
                if post_add_snap != pre_add_snap:
                    raise _source_changed(relative_posix)
        archive_path.chmod(0o600)
        self.verify_archive(archive_path, expected)
        manifest = {
            "schema_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "source": str(self.source),
            "excluded_top_level": sorted(self.EXCLUDED_TOP_LEVEL),
            "archive": archive_path.name,
            "archive_sha256": _sha256(archive_path),
            "file_count": len(expected),
            "files": expected,
            # Symbolic links are recorded with their targets, never followed
            # and never archived, so nothing outside the source is copied.
            "symlinks": links,
            "symlink_policy": "recorded-not-followed",
            "restore_verified": True,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_path.chmod(0o600)
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
        files: list[Path] = []
        enum_stats: dict[Path, tuple[int, int, int, int]] = {}
        links: dict[str, str] = {}
        for path in self.source.rglob("*"):
            relative = path.relative_to(self.source)
            if relative.parts and relative.parts[0] in self.EXCLUDED_TOP_LEVEL:
                continue
            if path.is_symlink():
                links[str(PurePosixPath(*relative.parts))] = os.readlink(path)
                continue
            if path.is_file():
                enum_stats[path] = _checked_snapshot(path, str(PurePosixPath(*relative.parts)))
                files.append(path)
        self._after_enumeration()
        return sorted(files), enum_stats, dict(sorted(links.items()))

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
    def verify_archive(archive_path: Path, expected: dict[str, str]) -> None:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts:
                    raise ValueError(f"Unsafe archive path: {member.name}")
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError(f"Unsafe archive member: {member.name}")
            with tempfile.TemporaryDirectory(prefix="agent-platform-restore-") as directory:
                restore = Path(directory)
                archive.extractall(restore, filter="data")
                restored_root = restore / "openclaw"
                actual = {
                    str(path.relative_to(restored_root)): _sha256(path)
                    for path in sorted(restored_root.rglob("*"))
                    if path.is_file()
                }
        if actual != expected:
            raise ValueError("Disposable restore checksums do not match source snapshot")


def _stat_snapshot(path: Path) -> tuple[int, int, int, int]:
    stat = os.lstat(path)
    return (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_mode)


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

