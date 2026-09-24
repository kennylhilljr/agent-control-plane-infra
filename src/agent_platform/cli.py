from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backup import BackupManager
from .inventory import InventoryCollector


DEFAULT_REPOSITORIES = (
    "~/Documents/GitHub/agent-engineers",
    "~/Documents/GitHub/my-research-mcp-server",
    "~/Documents/GitHub/agent-control-plane-infra",
    "~/Documents/GitHub/openclaw-ecc-orchestrator",
)


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


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "inventory":
        repositories = args.repository or list(DEFAULT_REPOSITORIES)
        data = InventoryCollector(
            repositories=[Path(item).expanduser() for item in repositories]
        ).collect()
        output = args.output or Path("inventories/latest.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        envelope = {
            "ok": True,
            "operation": "inventory",
            "changed": True,
            "checks": [{"name": "sanitized-inventory", "status": "passed"}],
            "warnings": [],
            "required_user_actions": [],
            "rollback_checkpoint": None,
            "output": str(output.resolve()),
        }
        print(json.dumps(envelope if args.json else data, indent=2, sort_keys=True))
        return 0
    if args.command == "backup":
        result = BackupManager(args.source, args.backup_dir).create(dry_run=args.dry_run)
        envelope = {
            "ok": True,
            "operation": "backup",
            "changed": result.changed,
            "checks": [
                {"name": "file-enumeration", "status": "passed", "count": result.file_count},
                {
                    "name": "disposable-restore",
                    "status": "passed" if result.verified else "not-run",
                },
            ],
            "warnings": ["Live logs are intentionally excluded from rollback state."],
            "required_user_actions": [],
            "rollback_checkpoint": str(result.checkpoint_dir),
            "archive": str(result.archive),
            "manifest": str(result.manifest),
        }
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
