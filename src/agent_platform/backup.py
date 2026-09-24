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


class BackupManager:
    EXCLUDED_TOP_LEVEL = {"logs"}

    def __init__(self, source: Path, destination: Path) -> None:
        self.source = source.expanduser().resolve()
        self.destination = destination.expanduser().resolve()

    def create(self, *, dry_run: bool = False) -> BackupResult:
        if not self.source.is_dir():
            raise FileNotFoundError(f"OpenClaw state directory not found: {self.source}")
        files = self._source_files()
        checkpoint_name = datetime.now(UTC).strftime("openclaw-%Y%m%dT%H%M%S.%fZ")
        checkpoint = self.destination / checkpoint_name
        archive_path = checkpoint / "openclaw-state.tar.gz"
        manifest_path = checkpoint / "manifest.json"
        if dry_run:
            return BackupResult(False, False, len(files), checkpoint, archive_path, manifest_path)

        self._prepare_destination(checkpoint)
        expected = {str(path.relative_to(self.source)): _sha256(path) for path in files}
        with tarfile.open(archive_path, "w:gz") as archive:
            for path in files:
                relative = path.relative_to(self.source)
                archive.add(path, arcname=str(PurePosixPath("openclaw", *relative.parts)), recursive=False)
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
            "restore_verified": True,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_path.chmod(0o600)
        return BackupResult(True, True, len(files), checkpoint, archive_path, manifest_path)

    def _source_files(self) -> list[Path]:
        files = []
        for path in self.source.rglob("*"):
            relative = path.relative_to(self.source)
            if relative.parts and relative.parts[0] in self.EXCLUDED_TOP_LEVEL:
                continue
            if path.is_symlink():
                raise ValueError(f"Refusing to back up symbolic link: {relative}")
            if path.is_file():
                files.append(path)
        return sorted(files)

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

