from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "<redacted>"

# Key names fail closed: a key is normalized by lowercasing it and removing
# "_", "-" and ".", and is sensitive when any of these tokens appears anywhere
# in the result. Compact or oddly cased names such as "PRIVATEKEYPRESENT" or
# "x-Auth.Token" therefore match. Words that merely contain a token, such as
# "tokenizer" or "secretary", are redacted too; that is the accepted cost.
_KEY_STRIP = re.compile(r"[_.\-]")
SENSITIVE_KEY_TOKENS: tuple[str, ...] = (
    "apikey",
    "privatekey",
    "token",
    "secret",
    "password",
    "passphrase",
    "cookie",
    "bearer",
    "credential",
    "authorization",
)

# Splits used only to find a metadata suffix: separators, then camelCase words.
_KEY_SEPARATOR = re.compile(r"[^A-Za-z0-9]+")
_KEY_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

# Suffix words that mark a sensitive key as metadata about a secret rather
# than the secret itself. Numeric suffixes keep int/float values only; status
# suffixes keep bool/None only. Everything else under the key is redacted.
_NUMERIC_METADATA_SUFFIXES = frozenset({"count", "tokens"})
_STATUS_METADATA_SUFFIXES = frozenset({"status", "configured", "present"})

# Owner-approved exception: the committed OpenClaw validation evidence records
# the result of a secrets audit as the literal string "clean". Only this exact
# key and exact value are kept; any other string under the key is redacted.
AUDIT_STATUS_ALLOWLIST: dict[str, frozenset[str]] = {
    "secrets_audit_status": frozenset({"clean"}),
}


def normalize_key(key: str) -> str:
    return _KEY_STRIP.sub("", key.lower())


def _has_sensitive_token(normalized: str) -> bool:
    return any(token in normalized for token in SENSITIVE_KEY_TOKENS)


def is_sensitive_key(key: str) -> bool:
    return _has_sensitive_token(normalize_key(key))


def _key_segments(key: str) -> list[str]:
    return [segment.lower() for segment in _KEY_SEPARATOR.split(key) if segment]


def _key_words(key: str) -> list[str]:
    return [word.lower() for word in _KEY_WORD.findall(key)]


def _metadata_suffix(key: str) -> str:
    suffixes = _NUMERIC_METADATA_SUFFIXES | _STATUS_METADATA_SUFFIXES
    segments = _key_segments(key)
    if len(segments) > 1 and segments[-1] in suffixes:
        return segments[-1]
    words = _key_words(key)
    if len(words) > 1 and words[-1] in suffixes:
        return words[-1]
    # Compact or oddly cased names ("PRIVATEKEYPRESENT", "sEcReTcOuNt") carry
    # the suffix inline. It only counts when what precedes it still names a
    # secret.
    normalized = normalize_key(key)
    for suffix in suffixes:
        if normalized.endswith(suffix) and _has_sensitive_token(normalized[: -len(suffix)]):
            return suffix
    return ""


def _keep_sensitive_value(key: str, value: Any) -> bool:
    # An unrecognised suffix only ever falls through to redaction.
    suffix = _metadata_suffix(key)
    if suffix in _NUMERIC_METADATA_SUFFIXES:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if suffix in _STATUS_METADATA_SUFFIXES:
        if value is None or isinstance(value, bool):
            return True
        allowed = AUDIT_STATUS_ALLOWLIST.get(key)
        return isinstance(value, str) and allowed is not None and value in allowed
    return isinstance(value, bool)


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
    if is_sensitive_key(key):
        return value if _keep_sensitive_value(key, value) else REDACTED
    if isinstance(value, dict):
        return {name: redact(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str) and "://" in value:
        return _redact_url(value)
    return value


def home_relative(value: Any, homes: tuple[str, ...]) -> Any:
    """Rewrite every occurrence of a home folder path in string values to "~".

    A home path only matches at a path boundary, so "/Users/al" does not
    rewrite "/Users/alice", and case is ignored. After a URL authority the
    path keeps its leading slash: "ssh://host/home/al/x" becomes
    "ssh://host/~/x" and "file:///home/al/x" becomes "file:///~/x", which
    redact still treats as a URL; run redact next and then shorten_file_urls.
    Percent-encoded home paths are not rewritten; nothing is decoded, so the
    rewrite never changes how redact parses a URL, and
    scripts/check_inventories.py, which decodes when it checks, fails
    committed evidence that still holds one. Member names are left alone; inventory keys are fixed
    identifiers, not paths.
    """
    patterns: list[tuple[re.Pattern[str], str]] = []
    for home in homes:
        home = home.rstrip("/")
        if not home:
            continue
        plain = re.escape(home)
        patterns.append((re.compile(r"(?<=://)([^/\s?#\"']*)" + plain + _PATH_END, re.IGNORECASE), r"\1/~"))
        patterns.append((re.compile(r"(?<![\w.-])" + plain + _PATH_END, re.IGNORECASE), "~"))
    return _map_strings(value, lambda text: _substitute(text, patterns))


# A home path ends at "/", the end of the string, or a character that cannot
# continue a user name.
_PATH_END = r"(?=/|$|[^\w.-])"
_FILE_URL_HOME = re.compile(r"(?<![\w+.-])file://[^/\s?#\"']*/~(?=/|\?|#|$)", re.IGNORECASE)


def shorten_file_urls(value: Any) -> Any:
    """Turn the "file:///~/x" URLs left by home_relative into plain "~/x" paths."""
    return _map_strings(value, lambda text: _FILE_URL_HOME.sub("~", text))


def _substitute(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> str:
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def _map_strings(value: Any, change: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return change(value)
    if isinstance(value, dict):
        return {name: _map_strings(item, change) for name, item in value.items()}
    if isinstance(value, list):
        return [_map_strings(item, change) for item in value]
    if isinstance(value, tuple):
        return tuple(_map_strings(item, change) for item in value)
    return value


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<redacted-url>"
    query = [
        (name, REDACTED if is_sensitive_key(name) else item)
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
        given_home = home or Path.home()
        self.home = given_home.resolve()
        # Both spellings of the home folder (as given and resolved, e.g.
        # /var/... and /private/var/... on macOS) are rewritten to "~".
        self._home_spellings = tuple(
            sorted({str(given_home), str(self.home)}, key=len, reverse=True)
        )
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
        # Home paths are rewritten before redaction, which percent-encodes
        # URL query values; file:// URLs are shortened only after redaction,
        # so their query values are still redacted as URL parameters.
        sanitized: dict[str, Any] = shorten_file_urls(redact(home_relative(inventory, self._home_spellings)))
        return sanitized

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
