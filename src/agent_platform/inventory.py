from __future__ import annotations

import os
import platform
import re
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_KEY = re.compile(
    r"(^|[_-])(api[_-]?key|token|secret|password|credential|authorization)($|[_-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


def run_command(command: tuple[str, ...], timeout: float = 5.0) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        return CommandResult(
            None,
            _text(error.stdout),
            _text(error.stderr),
            True,
        )
    except OSError as error:
        return CommandResult(None, "", str(error), False)
    return CommandResult(
        completed.returncode,
        completed.stdout.rstrip("\r\n"),
        completed.stderr.rstrip("\r\n"),
        False,
    )


def redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key) and not isinstance(value, bool):
        return "<redacted>"
    if isinstance(value, dict):
        return {name: redact(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str) and "://" in value:
        return _redact_url(value)
    return value


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<redacted-url>"
    query = [
        (name, "<redacted>" if SENSITIVE_KEY.search(name) else item)
        for name, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


class InventoryCollector:
    RUNNERS = ("openclaw", "claude", "codex", "gemini", "kimi", "groq", "node", "python3", "git")

    def __init__(
        self,
        *,
        locate: Callable[[str], str | None] = shutil.which,
        run: Callable[[tuple[str, ...], float], CommandResult] = run_command,
        home: Path | None = None,
        repositories: list[Path] | None = None,
    ) -> None:
        self.locate = locate
        self.run = run
        self.home = (home or Path.home()).resolve()
        self.repositories = repositories or []

    def collect(self) -> dict[str, Any]:
        inventory = {
            "schema_version": "1.0",
            "collected_at": datetime.now(UTC).isoformat(),
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "runners": {name: self._runner(name) for name in self.RUNNERS},
            "providers": self._providers(),
            "installations": self._installations(),
            "ecc": self._ecc_installations(),
            "openclaw": self._openclaw(),
            "repositories": [self._repository(path) for path in self.repositories],
        }
        return redact(inventory)

    def _runner(self, name: str) -> dict[str, Any]:
        executable = self.locate(name)
        if executable is None:
            return {"status": "missing", "executable": None, "version": None}
        result = self.run((name, "--version"), 5.0)
        if result.timed_out:
            status = "timeout"
        elif result.returncode == 0:
            status = "ready"
        else:
            status = "error"
        version = (result.stdout or result.stderr).splitlines()
        return {
            "status": status,
            "executable": executable,
            "version": version[0][:200] if version else None,
            "exit_code": result.returncode,
        }

    def _providers(self) -> dict[str, dict[str, bool]]:
        variables = {
            "anthropic": ("ANTHROPIC_API_KEY",),
            "openai": ("OPENAI_API_KEY",),
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "groq": ("GROQ_API_KEY",),
            "kimi": ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
            "openrouter": ("OPENROUTER_API_KEY",),
        }
        return {
            provider: {"credential_configured": any(os.environ.get(name) for name in names)}
            for provider, names in variables.items()
        }

    def _installations(self) -> dict[str, Any]:
        candidates = {
            "openclaw_state": self.home / ".openclaw",
            "claude_config": self.home / ".claude",
            "codex_config": self.home / ".codex",
            "gemini_config": self.home / ".gemini",
        }
        return {
            name: {"present": path.exists(), "path": str(path)}
            for name, path in candidates.items()
        }

    def _openclaw(self) -> dict[str, Any]:
        if self.locate("openclaw") is None:
            return {"status": "missing"}
        agents = self._json_command(("openclaw", "agents", "list", "--bindings", "--json"))
        plugins = self._json_command(("openclaw", "plugins", "list", "--json"))
        cron = self._json_command(
            ("openclaw", "cron", "list", "--all", "--json", "--timeout", "3000")
        )
        devices = self._json_command(
            ("openclaw", "devices", "list", "--json", "--timeout", "3000")
        )
        models = self._json_command(("openclaw", "models", "list", "--json"))
        return {
            "status": "ready",
            "agents": [
                {
                    "id": item.get("id"),
                    "default": bool(item.get("isDefault")),
                    "binding_count": int(item.get("bindings", 0)),
                }
                for item in agents if isinstance(item, dict)
            ] if isinstance(agents, list) else [],
            "plugins": [
                {
                    "id": item.get("id"),
                    "enabled": bool(item.get("enabled")),
                    "status": item.get("status"),
                    "version": item.get("version"),
                }
                for item in plugins.get("plugins", []) if isinstance(item, dict)
            ] if isinstance(plugins, dict) else [],
            "cron": _cron_summary(cron),
            "devices": _device_summary(devices),
            "models": [
                {
                    "key": item.get("key"),
                    "available": bool(item.get("available")),
                    "context_window": item.get("contextWindow"),
                    "local": bool(item.get("local")),
                }
                for item in models.get("models", []) if isinstance(item, dict)
            ] if isinstance(models, dict) else [],
        }

    def _ecc_installations(self) -> dict[str, dict[str, Any]]:
        candidates = {
            "claude": self.home / ".claude" / "skills" / "everything-claude-code",
            "codex": self.home / ".codex" / "skills" / "everything-claude-code",
            "kimi": self.home / ".kimi" / "skills" / "everything-claude-code",
        }
        return {
            harness: {
                "present": path.is_dir(),
                "surface": "skill-directory" if path.is_dir() else None,
                "path": str(path),
            }
            for harness, path in candidates.items()
        }

    def _json_command(self, command: tuple[str, ...]) -> Any:
        result = self.run(command, 8.0)
        if result.timed_out or result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

    def _repository(self, path: Path) -> dict[str, Any]:
        resolved = path.expanduser().resolve()
        base = ("git", "-C", str(resolved))
        top = self.run((*base, "rev-parse", "--show-toplevel"), 5.0)
        if top.returncode != 0:
            return {"path": str(resolved), "status": "not-a-repository"}
        branch = self.run((*base, "rev-parse", "--abbrev-ref", "HEAD"), 5.0)
        head = self.run((*base, "rev-parse", "HEAD"), 5.0)
        status = self.run((*base, "status", "--porcelain=v1"), 5.0)
        lines = [line for line in status.stdout.splitlines() if line]
        return {
            "path": str(resolved),
            "status": "ready",
            "branch": branch.stdout if branch.returncode == 0 else None,
            "head": head.stdout if head.returncode == 0 else None,
            "dirty": bool(lines),
            "changed_files": [_status_path(line) for line in lines],
        }


def _status_path(line: str) -> str:
    path = line[3:] if len(line) > 3 else line
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path


def _cron_summary(payload: Any) -> dict[str, int]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    return {
        "job_count": len(jobs),
        "enabled_count": sum(bool(job.get("enabled")) for job in jobs if isinstance(job, dict)),
    }


def _device_summary(payload: Any) -> dict[str, Any]:
    paired = payload.get("paired", []) if isinstance(payload, dict) else []
    pending = payload.get("pending", []) if isinstance(payload, dict) else []
    return {
        "paired_count": len(paired),
        "pending_count": len(pending),
        "roles": sorted({item.get("role") for item in paired if isinstance(item, dict) and item.get("role")}),
    }
