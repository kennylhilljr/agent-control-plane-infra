from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Sequence

from .inventory import CommandResult, run_command

# age writes this header first; anything else in the output is not ciphertext.
AGE_HEADER = b"age-encryption.org/v1\n"
# Encrypting a large state folder can take a while. age does not prompt for
# native or SSH recipients; a plugin may wait on a device, which this bounds.
AGE_TIMEOUT_SECONDS = 600.0
# Public recipients only: a native age X25519 key, another Bech32 age recipient
# (age1pq1, age1tag1, or a plugin recipient such as age1yubikey1), or an
# OpenSSH public key line (its comment may contain spaces). Every form starts
# with age1 or ssh-, so a recipient cannot be read as an age option. Only the
# character set is checked; age itself verifies the Bech32 checksum.
_AGE_RECIPIENT = re.compile(
    r"age1[02-9ac-hj-np-z]{58}"
    r"|age1[a-z0-9-]{1,32}1[02-9ac-hj-np-z]{20,4000}"
    r"|(ssh-ed25519|ssh-rsa) [A-Za-z0-9+/]+={0,2}( [\x20-\x7e]*)?"
)
# Folder names that sync clients create. Matching is a heuristic: it catches
# the common clients' default locations, not every synchronized folder.
_SYNCED_PART_PREFIXES = ("dropbox", "onedrive", "google drive", "googledrive", "icloud",
                         "box sync", "pcloud", "nextcloud", "owncloud", "syncthing")
_SYNCED_PARTS = {"mobile documents", "cloudstorage", "my drive", "box"}
# Linux file system types that live on this host. Anything else (nfs, cifs,
# smb3, fuse.sshfs, davfs, 9p and unknown types) counts as not local, so an
# unlisted type fails closed.
_LINUX_LOCAL_FSTYPES = frozenset({
    "apfs", "bcachefs", "btrfs", "erofs", "exfat", "ext2", "ext3", "ext4", "f2fs",
    "fuseblk", "hfs", "hfsplus", "iso9660", "jfs", "msdos", "nilfs2", "ntfs", "ntfs3",
    "overlay", "ramfs", "reiserfs", "squashfs", "tmpfs", "udf", "vfat", "xfs", "zfs",
})
# `mount` output lines: macOS "DEVICE on POINT (FSTYPE, OPTION, ...)" with a
# "local" option for local volumes; Linux "DEVICE on POINT type FSTYPE (OPTIONS)".
_DARWIN_MOUNT_LINE = re.compile(r"^.*? on (?P<point>/.*) \((?P<options>[^()]*)\)$")
_LINUX_MOUNT_LINE = re.compile(r"^.*? on (?P<point>/.*) type (?P<fstype>\S+) \([^()]*\)$")
# Linux `mount` may print a space, tab, newline or backslash in a mount point
# as an octal escape (\040, \011, \012, \134), as /proc/mounts does.
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")
MOUNT_TIMEOUT_SECONDS = 5.0


def _mount_table_supported(platform: str) -> bool:
    """True for the platforms whose `mount` output local_mount_points reads."""
    return platform == "darwin" or platform.startswith("linux")

CORRUPT_ARCHIVE_MESSAGE = (
    "Archive compressed stream is corrupt: gzip header, CRC, length or deflate data check failed"
)


@dataclass(frozen=True)
class BackupResult:
    changed: bool
    verified: bool
    file_count: int
    checkpoint_dir: Path
    archive: Path
    manifest: Path
    link_count: int = 0
    encrypted: bool = False


class SourceChangedDuringBackup(RuntimeError):
    pass


def _identity(path: Path) -> tuple[int, int] | None:
    """Return (st_dev, st_ino) for an existing path, following links, or None."""
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return info.st_dev, info.st_ino


def _contains_by_identity(outer: Path, inner: Path) -> bool:
    """True when ``inner`` or one of its existing ancestors is ``outer`` itself.

    Compares file identity, not path text, so a case-variant spelling on a
    case-insensitive volume, or a link to the same folder, still matches.
    """
    outer_id = _identity(outer)
    if outer_id is None:
        return False
    for candidate in (inner, *inner.parents):
        if _identity(candidate) == outer_id:
            return True
    return False


def _paths_overlap(source: Path, destination: Path) -> bool:
    """True when the two folders are the same or one lies inside the other."""
    return (_contains_by_identity(source, destination)
            or _contains_by_identity(destination, source))


def looks_synchronized(path: Path) -> bool:
    """True when a folder name in ``path`` matches a common sync client's
    default location (iCloud Drive, Dropbox, OneDrive, Google Drive and so
    on). A heuristic: an unlisted synchronized folder is not detected."""
    for part in path.parts:
        lowered = part.lower()
        if lowered in _SYNCED_PARTS or lowered.startswith(_SYNCED_PART_PREFIXES):
            return True
    return False


def local_mount_points(mount_output: str, platform: str) -> list[Path] | None:
    """Mount points that `mount` lists as local file systems, or None when
    the platform's output format is not supported. On macOS an entry is
    local when its options include "local"; on Linux when its type is in
    _LINUX_LOCAL_FSTYPES. Lines that do not parse are skipped."""
    if not _mount_table_supported(platform):
        return None
    points: list[Path] = []
    for line in mount_output.splitlines():
        if platform == "darwin":
            match = _DARWIN_MOUNT_LINE.match(line)
            if match is None:
                continue
            options = {option.strip() for option in match.group("options").split(",")}
            if "local" in options:
                points.append(Path(match.group("point")))
        else:
            match = _LINUX_MOUNT_LINE.match(line)
            if match is not None and match.group("fstype") in _LINUX_LOCAL_FSTYPES:
                point = _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), match.group("point"))
                points.append(Path(point))
    return points


def _nearest_existing_device(path: Path) -> int | None:
    """st_dev of path or of its nearest existing ancestor, following links."""
    for candidate in (path, *path.parents):
        try:
            return os.stat(candidate).st_dev
        except (FileNotFoundError, NotADirectoryError):
            continue
    return None


def is_on_local_filesystem(
    path: Path,
    run: Callable[..., CommandResult],
    platform: str = sys.platform,
) -> bool:
    """True only when path (or, if it does not exist yet, its nearest existing
    ancestor) is on a file system that `mount` lists as local. The match uses
    the device number (st_dev) of the local mount points, not path text, so
    case variants, symbolic links and macOS firmlinks resolve correctly, and
    only local mount points are examined, so a hung network mount is never
    touched. Any failure (unsupported platform, `mount` missing, failing or
    timing out, no matching local mount) returns False: fail closed."""
    if not _mount_table_supported(platform):
        return False
    device = _nearest_existing_device(path)
    if device is None:
        return False
    try:
        result = run(("mount",), timeout=MOUNT_TIMEOUT_SECONDS)
    except OSError:
        # run_command reports OSError in its result; a runner that raises
        # it instead still fails closed. Other exceptions propagate, as
        # unexpected errors do everywhere in the CLI.
        return False
    if result.timed_out or result.returncode != 0:
        return False
    points = local_mount_points(result.stdout, platform)
    if not points:
        return False
    for point in points:
        try:
            if os.stat(point).st_dev == device:
                return True
        except OSError:
            continue
    return False


class BackupManager:
    EXCLUDED_TOP_LEVEL = {"logs", "tmp"}

    def __init__(
        self,
        source: Path,
        destination: Path,
        *,
        encrypt_to: Sequence[str] = (),
        allow_unencrypted: bool = False,
        locate: Callable[[str], str | None] = shutil.which,
        run: Callable[..., CommandResult] = run_command,
        staging_root: Path | None = None,
        platform: str = sys.platform,
    ) -> None:
        self.source = source.expanduser().resolve()
        self.destination = destination.expanduser().resolve()
        self.encrypt_to = tuple(encrypt_to)
        self.allow_unencrypted = allow_unencrypted
        self.locate = locate
        self.run = run
        self.staging_root = staging_root
        self.platform = platform

    def create(self, *, dry_run: bool = False) -> BackupResult:
        if not self.source.is_dir():
            raise FileNotFoundError(f"OpenClaw state directory not found: {self.source}")
        if _paths_overlap(self.source, self.destination):
            raise ValueError(
                f"Backup destination must not overlap the source: "
                f"source={self.source} destination={self.destination}"
            )
        age = self._encryption_preflight()
        staging_root = self._staging_root() if age is not None else None
        files, enum_stats, links = self._source_entries()
        checkpoint_name = datetime.now(UTC).strftime("openclaw-%Y%m%dT%H%M%S.%fZ")
        checkpoint = self.destination / checkpoint_name
        plain_name = "openclaw-state.tar.gz"
        archive_name = plain_name + ".age" if age else plain_name
        archive_path = checkpoint / archive_name
        manifest_path = checkpoint / "manifest.json"
        if dry_run:
            return BackupResult(False, False, len(files), checkpoint, archive_path, manifest_path,
                                len(links), encrypted=age is not None)

        staging: Path | None = None
        if staging_root is not None:
            # mkdtemp creates the folder with mode 0700.
            staging = Path(tempfile.mkdtemp(prefix="agent-platform-backup-", dir=staging_root))
        try:
            result = self._create(files, enum_stats, links, checkpoint, archive_path,
                                  manifest_path, age, staging)
        except BaseException as error:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
                if staging.exists() or staging.is_symlink():
                    # Plaintext left behind matters more than the first
                    # error, which stays attached as the cause.
                    raise OSError(
                        f"Could not remove encryption staging folder: {staging}"
                    ) from error
            raise
        if staging is not None:
            # The plaintext archive lives only here, so a success that cannot
            # remove it is reported as a failure rather than left silently.
            shutil.rmtree(staging, ignore_errors=True)
            if staging.exists() or staging.is_symlink():
                raise OSError(f"Could not remove encryption staging folder: {staging}")
        return result

    def _encryption_preflight(self) -> str | None:
        """Check the encryption options and return the age executable, or
        None for an unencrypted backup."""
        if not self.encrypt_to:
            if self.allow_unencrypted:
                return None
            if looks_synchronized(self.destination):
                raise ValueError(
                    f"Unencrypted backup refused for a synchronized destination: "
                    f"{self.destination}. Pass --encrypt-to or --allow-unencrypted."
                )
            if not is_on_local_filesystem(self.destination, self.run, self.platform):
                # A network mount (SMB, NFS, AFP, WebDAV, sshfs) leaves the
                # host; so may anything the mount table cannot confirm.
                raise ValueError(
                    f"Unencrypted backup refused for a destination not confirmed local: "
                    f"{self.destination}. Its file system is a network mount or could not "
                    f"be identified. Pass --encrypt-to or --allow-unencrypted."
                )
            return None
        for recipient in self.encrypt_to:
            if not _AGE_RECIPIENT.fullmatch(recipient):
                raise ValueError(
                    "Invalid age recipient: use an age1... recipient or an "
                    "ssh-ed25519/ssh-rsa public key line"
                )
        age = self.locate("age")
        if not age:
            raise ValueError("age is required for --encrypt-to but was not found on PATH")
        return age

    def _staging_root(self) -> Path:
        """Check and return the folder that will hold a new 0700 staging
        folder for the plaintext archive and its restore check: staging_root
        (default: the system temporary directory). It must not overlap the
        destination or look synchronized, so plaintext never reaches a folder
        that may be uploaded, and inside the source it must sit under an
        excluded top-level folder. Dry runs check it too."""
        root = Path(self.staging_root or tempfile.gettempdir()).expanduser().resolve()
        if _paths_overlap(root, self.destination):
            raise ValueError(
                f"Encryption staging folder must not overlap the backup destination: {root}"
            )
        if looks_synchronized(root):
            raise ValueError(
                f"Encryption staging folder must not look synchronized: {root}"
            )
        if _paths_overlap(root, self.source) and not any(
            _contains_by_identity(self.source / name, root) for name in self.EXCLUDED_TOP_LEVEL
        ):
            raise ValueError(
                f"Encryption staging folder must not overlap the source: {root}"
            )
        if not root.is_dir():
            raise NotADirectoryError(root)
        return root

    def _create(
        self,
        files: list[Path],
        enum_stats: dict[Path, tuple[int, int, int, int]],
        links: dict[str, str],
        checkpoint: Path,
        archive_path: Path,
        manifest_path: Path,
        age: str | None,
        staging: Path | None,
    ) -> BackupResult:
        self._prepare_destination(checkpoint)
        plain_path = (staging or checkpoint) / "openclaw-state.tar.gz"
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
        with tarfile.open(plain_path, "w:gz") as archive:
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
        plain_path.chmod(0o600)
        self.verify_archive(plain_path, expected)
        encryption: dict[str, Any] | None = None
        if age is not None and staging is not None:
            encryption = {
                "tool": "age",
                "recipients": list(self.encrypt_to),
                "plaintext_archive": plain_path.name,
                "plaintext_archive_sha256": _sha256(plain_path),
            }
            self._encrypt(age, plain_path, staging, archive_path)
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
            "schema_version": "1.2",
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
            # The restore check ran on the plaintext archive before it was
            # encrypted; the plaintext was then removed from staging.
            "encryption": encryption,
        }
        _write_private(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return BackupResult(True, True, len(files), checkpoint, archive_path, manifest_path,
                            len(links), encrypted=encryption is not None)

    def _encrypt(self, age: str, plain_path: Path, staging: Path, archive_path: Path) -> None:
        """Encrypt plain_path to the recipients inside staging, check the age
        header, then copy the ciphertext into a new 0600 file at archive_path."""
        staged = staging / (archive_path.name)
        command: list[str] = [age, "--encrypt"]
        for recipient in self.encrypt_to:
            command += ["--recipient", recipient]
        command += ["--output", str(staged), "--", str(plain_path)]
        result = self.run(tuple(command), timeout=AGE_TIMEOUT_SECONDS)
        if result.timed_out:
            raise ValueError("age encryption failed: timed out")
        if result.returncode != 0:
            raise ValueError(f"age encryption failed: exit status {result.returncode}")
        try:
            with staged.open("rb") as stream:
                header = stream.read(len(AGE_HEADER))
        except FileNotFoundError:
            header = b""
        if header != AGE_HEADER:
            raise ValueError("age encryption failed: output is not an age file")
        _copy_private(staged, archive_path)

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
        """First validate the gzip header strictly and decompress the whole
        gzip stream so the gzip CRC and length are checked, raising
        ValueError when that fails. Then restore the
        archive into a new 0700 folder under restore_root (default: the
        archive's folder) and compare checksums. The folder is removed when
        verification ends, pass or fail; nothing is created under
        tempfile.gettempdir()."""
        if restore_root is None:
            restore_root = archive_path.parent
        _check_gzip_stream(archive_path)
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


def _copy_private(source: Path, target: Path) -> None:
    """Copy source to a new file at target created with mode 0600."""
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output, source.open("rb") as stream:
        shutil.copyfileobj(stream, output, 1024 * 1024)
    target.chmod(0o600)


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


class _CorruptGzip(Exception):
    """Internal marker for a malformed gzip stream."""


_GZIP_FHCRC = 0x02
_GZIP_FEXTRA = 0x04
_GZIP_FNAME = 0x08
_GZIP_FCOMMENT = 0x10
_GZIP_RESERVED = 0xE0
_CHUNK = 1024 * 1024
_FIELD_CHUNK = 64 * 1024


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise _CorruptGzip("truncated")
    return data


def _skip_zero_terminated(stream: BinaryIO, crc: int) -> int:
    """Skip an FNAME or FCOMMENT field and return the header CRC updated with
    it. The field is scanned in _FIELD_CHUNK pieces and never kept whole, so
    a long or unterminated field costs bounded memory."""
    while True:
        data = stream.read(_FIELD_CHUNK)
        if not data:
            raise _CorruptGzip("truncated")
        end = data.find(b"\x00")
        if end < 0:
            crc = zlib.crc32(data, crc)
            continue
        crc = zlib.crc32(data[:end + 1], crc)
        stream.seek(end + 1 - len(data), os.SEEK_CUR)
        return crc


def _check_gzip_stream(path: Path) -> None:
    """Validate the archive as exactly one strict RFC 1952 gzip member.

    The header must have the gzip magic, the deflate method and no reserved
    FLG bits (Python's gzip reader ignores them), an FHCRC header checksum
    must match, the whole deflate stream is decompressed so the CRC32 and
    ISIZE trailer are checked (tarfile stops at the tar end marker), and no
    bytes may follow the trailer."""
    with path.open("rb") as stream:
        try:
            _check_gzip_member(stream)
        except (_CorruptGzip, zlib.error) as error:
            raise ValueError(CORRUPT_ARCHIVE_MESSAGE) from error


def _check_gzip_member(stream: BinaryIO) -> None:
    header = _read_exact(stream, 10)
    if header[:3] != b"\x1f\x8b\x08":
        raise _CorruptGzip("bad magic or method")
    flags = header[3]
    if flags & _GZIP_RESERVED:
        raise _CorruptGzip("reserved flag bits set")
    header_crc = zlib.crc32(header)
    if flags & _GZIP_FEXTRA:
        length_bytes = _read_exact(stream, 2)
        header_crc = zlib.crc32(length_bytes, header_crc)
        # XLEN is at most 65535, so reading the field whole stays bounded.
        extra = _read_exact(stream, int.from_bytes(length_bytes, "little"))
        header_crc = zlib.crc32(extra, header_crc)
    if flags & _GZIP_FNAME:
        header_crc = _skip_zero_terminated(stream, header_crc)
    if flags & _GZIP_FCOMMENT:
        header_crc = _skip_zero_terminated(stream, header_crc)
    if flags & _GZIP_FHCRC:
        expected_header_crc = int.from_bytes(_read_exact(stream, 2), "little")
        if header_crc & 0xFFFF != expected_header_crc:
            raise _CorruptGzip("header CRC mismatch")

    # Each decompress call returns at most _CHUNK bytes; input it did not
    # consume waits in unconsumed_tail, so memory stays bounded however
    # compressible the archive is.
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    crc = 0
    size = 0
    while not inflater.eof:
        chunk = inflater.unconsumed_tail or stream.read(_CHUNK)
        data = inflater.decompress(chunk, _CHUNK)
        if not chunk and not data and not inflater.eof:
            raise _CorruptGzip("truncated deflate stream")
        crc = zlib.crc32(data, crc)
        size += len(data)
    # No flush(): at eof all output has been returned, and flush() would feed
    # unconsumed_tail (which still holds the bytes after the deflate end) in
    # again and append them to unused_data a second time.

    tail = inflater.unused_data
    if len(tail) < 8:
        tail += _read_exact(stream, 8 - len(tail))
    if int.from_bytes(tail[:4], "little") != crc:
        raise _CorruptGzip("CRC32 mismatch")
    if int.from_bytes(tail[4:8], "little") != size & 0xFFFFFFFF:
        raise _CorruptGzip("ISIZE mismatch")
    if tail[8:] or stream.read(1):
        raise _CorruptGzip("trailing data after gzip member")

