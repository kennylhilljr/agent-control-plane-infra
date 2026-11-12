from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .backup import BackupManager, SourceChangedDuringBackup
from .inventory import InventoryCollector


DEFAULT_REPOSITORIES = (
    "~/Documents/GitHub/agent-engineers",
    "~/Documents/GitHub/my-research-mcp-server",
    "~/Documents/GitHub/agent-control-plane-infra",
    "~/Documents/GitHub/openclaw-ecc-orchestrator",
)
DEFAULT_INVENTORY_OUTPUT = Path("inventories/latest.json")

# ValueError messages raised by this package that carry only fixed text and
# archive member names. Any other ValueError (decoding, conversion, JSON
# parsing) can quote input data, so its text is never shown.
KNOWN_VALUE_ERROR_PREFIXES = (
    "Backup destination must not overlap the source: ",
    "Disposable restore checksums do not match source snapshot",
    "Unsafe archive path: ",
    "Unsafe archive member: ",
)
# OSError messages raised by this package with a path and fixed text.
KNOWN_OS_ERROR_PREFIXES = (
    "OpenClaw state directory not found: ",
    "Backup root must not grant group/other access: ",
)
GENERIC_VALUE_ERROR = "Validation failed; details are withheld so no file contents are shown"
_LINE_BREAKS = re.compile(r"[\r\n\v\f\x1c-\x1e\x85  ]+")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agent-platform")
    commands = root.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="Collect sanitized local state")
    inventory.add_argument("--json", action="store_true", help="Print the result envelope")
    inventory.add_argument("--output", type=Path, help="Write inventory JSON to this path")
    inventory.add_argument("--repository", action="append", default=[])
    backup = commands.add_parser("backup", help="Create and verify an OpenClaw state backup")
    backup.add_argument("--backup-dir", required=True, type=Path)
    backup.add_argument("--source", type=Path, default=Path("~/.openclaw"))
    backup.add_argument("--dry-run", action="store_true")
    backup.add_argument("--json", action="store_true")
    return root


def build_envelope(
    operation: str,
    *,
    ok: bool,
    changed: bool,
    checks: Sequence[dict[str, Any]],
    warnings: Sequence[str] = (),
    required_user_actions: Sequence[str] = (),
    rollback_checkpoint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """The result envelope from MIGRATION_SPEC.md section 7. Every envelope,
    success or failure, carries the seven common fields."""
    envelope: dict[str, Any] = {
        "ok": ok,
        "operation": operation,
        "changed": changed,
        "checks": list(checks),
        "warnings": list(warnings),
        "required_user_actions": list(required_user_actions),
        "rollback_checkpoint": rollback_checkpoint,
    }
    envelope.update(extra)
    return envelope


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def safe_error_message(error: BaseException) -> str:
    """A one-line diagnostic that names paths but never file contents.

    Only fixed text is shown: the package's own messages, the operating
    system's description of an errno and the file names the error carries.
    Free-form exception text is withheld because it can quote input data."""
    if isinstance(error, SourceChangedDuringBackup):
        # Fixed text plus a relative path inside the source; no contents.
        return _one_line(str(error))
    if isinstance(error, ValueError):
        text = str(error)
        if text.startswith(KNOWN_VALUE_ERROR_PREFIXES):
            return _one_line(text)
        return GENERIC_VALUE_ERROR
    if isinstance(error, OSError):
        filenames = [os.fspath(name) for name in (error.filename, error.filename2)
                     if isinstance(name, (str, os.PathLike))]
        if len(error.args) == 1 and isinstance(error.args[0], os.PathLike):
            filenames = [os.fspath(error.args[0])]
        if isinstance(error.errno, int):
            text = os.strerror(error.errno)
        elif len(error.args) == 1 and isinstance(error.args[0], str) \
                and error.args[0].startswith(KNOWN_OS_ERROR_PREFIXES):
            return _one_line(error.args[0])
        elif isinstance(error, NotADirectoryError) and filenames:
            text = "Not a directory"
        else:
            text = f"{type(error).__name__} while running the command"
        if filenames:
            text = f"{text}: {' -> '.join(filenames)}"
        return _one_line(text)
    return f"{type(error).__name__} while running the command"


def _one_line(text: str) -> str:
    return _LINE_BREAKS.sub(" ", text).strip()


def _missing_ancestors(path: Path) -> list[Path]:
    """The path and its parents that do not exist yet, nearest first."""
    missing: list[Path] = []
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            break
        missing.append(candidate)
    return missing


def _absolute(path: Path) -> Path:
    """Best-effort absolute path. Never raises, so tracking cannot turn an
    operational error into a traceback."""
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        pass
    try:
        return Path(os.path.abspath(os.path.expanduser(path)))
    except (OSError, RuntimeError, ValueError):
        return path


@dataclass
class _Tracker:
    """Records what exists before a command runs, so a failure can report
    whether anything on disk changed. Only metadata is read, never file
    contents, and inspection errors never replace the original diagnostic.
    When the state cannot be inspected, the failure says so in a warning
    instead of guessing that something changed."""

    missing: list[Path]
    root: Path | None = None
    children: set[str] | None = None
    output: Path | None = None
    output_stat: tuple[int, ...] | None = None
    inspect_failed: bool = False

    @classmethod
    def for_backup(cls, destination: Path) -> _Tracker:
        root = _absolute(destination)
        tracker = cls(missing=[], root=root)
        try:
            tracker.missing = _missing_ancestors(root)
            if root.is_dir():
                tracker.children = {entry.name for entry in root.iterdir()}
        except (OSError, ValueError):
            tracker.inspect_failed = True
        return tracker

    @classmethod
    def for_output(cls, output: Path) -> _Tracker:
        path = _absolute(output)
        tracker = cls(missing=[], output=path)
        try:
            tracker.missing = _missing_ancestors(path)
            tracker.output_stat = _stat_key(path)
        except (OSError, ValueError):
            tracker.inspect_failed = True
        return tracker

    def changes(self) -> tuple[bool, list[str]]:
        """Return (changed, warnings) after a failure."""
        changed = False
        warnings: list[str] = []
        try:
            changed = any(path.exists() or path.is_symlink() for path in self.missing)
            if (self.output is not None and not self.inspect_failed
                    and _stat_key(self.output) != self.output_stat):
                changed = True
            if (self.root is not None and not self.inspect_failed
                    and self.root.is_dir()):
                before = self.children or set()
                for name in sorted({entry.name for entry in self.root.iterdir()} - before):
                    changed = True
                    leftover = self.root / name
                    if leftover.is_dir() and not leftover.is_symlink():
                        warnings.append(
                            f"Unverified checkpoint left at {leftover}; it is not a "
                            "verified rollback checkpoint."
                        )
        except (OSError, ValueError):
            self.inspect_failed = True
        if self.inspect_failed:
            target = self.root or self.output
            warnings.append(f"Could not inspect {target} for changes; check it for "
                            "partial writes.")
        return changed, warnings


def _stat_key(path: Path) -> tuple[int, ...] | None:
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode)


def _run_inventory(args: argparse.Namespace) -> int:
    repositories = args.repository or list(DEFAULT_REPOSITORIES)
    data = InventoryCollector(
        repositories=[Path(item).expanduser() for item in repositories]
    ).collect()
    output = args.output or DEFAULT_INVENTORY_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    envelope = build_envelope(
        "inventory",
        ok=True,
        changed=True,
        checks=[{"name": "sanitized-inventory", "status": "passed"}],
        output=str(output.resolve()),
    )
    _print_json(envelope if args.json else data)
    return 0


def _run_backup(args: argparse.Namespace) -> int:
    result = BackupManager(args.source, args.backup_dir).create(dry_run=args.dry_run)
    envelope = build_envelope(
        "backup",
        ok=True,
        changed=result.changed,
        checks=[
            {"name": "file-enumeration", "status": "passed", "count": result.file_count},
            {"name": "symlinks-recorded-not-followed", "status": "passed",
             "count": result.link_count},
            {
                "name": "disposable-restore",
                "status": "passed" if result.verified else "not-run",
            },
        ],
        warnings=["Live logs and the tmp/ scratch directory are intentionally excluded from rollback state."],
        rollback_checkpoint=str(result.checkpoint_dir),
        archive=str(result.archive),
        manifest=str(result.manifest),
    )
    _print_json(envelope)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "inventory":
        tracker = _Tracker.for_output(args.output or DEFAULT_INVENTORY_OUTPUT)
        run = _run_inventory
    elif args.command == "backup":
        tracker = _Tracker.for_backup(args.backup_dir)
        run = _run_backup
    else:
        return 2
    try:
        return run(args)
    except (OSError, ValueError, SourceChangedDuringBackup) as error:
        message = safe_error_message(error)
        changed, warnings = tracker.changes()
    if args.json:
        _print_json(build_envelope(
            args.command,
            ok=False,
            changed=changed,
            checks=[{"name": "command-execution", "status": "failed"}],
            warnings=warnings,
            error=message,
        ))
    else:
        line = f"agent-platform {args.command}: error: {message}"
        if warnings:
            line += " Warning: " + " ".join(warnings)
        print(_one_line(line), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
