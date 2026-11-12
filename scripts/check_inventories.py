#!/usr/bin/env python3
"""Check committed inventory evidence for unredacted or credential-shaped values.

Usage:
    python3 scripts/check_inventories.py            # every inventories/**/*.json
    python3 scripts/check_inventories.py FILE ...   # only the named files

The checker never modifies its inputs. It prints a JSON array of findings,
each an object with only ``file``, ``pointer`` (an RFC 6901 JSON Pointer) and
a fixed ``reason``. Values, exception text and input excerpts are never
printed, and any file name, directory name or pointer component that itself
looks like a credential is replaced with ``<redacted>``. Exit status is 0 when
every file is clean and 1 when anything fails.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = str(REPO_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent_platform.inventory import REDACTED, redact  # noqa: E402

REASON_UNREADABLE = "unreadable file"
REASON_INVALID_UTF8 = "invalid UTF-8"
REASON_INVALID_JSON = "invalid JSON"
REASON_DUPLICATE_MEMBER = "duplicate object member"
REASON_REDACTION_FAILED = "redaction failed"
REASON_REDACTION_CHANGED = "value changes under redaction"
REASON_CREDENTIAL = "value looks like a credential"
REASON_CREDENTIAL_NAME = "member name looks like a credential"

# The PEM marker is assembled from pieces so this file does not itself look
# like a private key block to secret scanners.
_PEM_DASHES = "-" * 5
# "sk-" must not follow a letter or digit, so ordinary words such as
# "task-list" or "disk-usage" are not reported; a key after a separator
# ("report-sk-...", "a_sk-...") or at the start is. "ghp_" is matched anywhere.
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]+"),
    re.compile(r"ghp_[A-Za-z0-9_-]+"),
    re.compile(
        _PEM_DASHES
        + r"BEGIN (?:(?:RSA|EC|DSA|ENCRYPTED|OPENSSH) )?PRIVATE KEY"
        + _PEM_DASHES
    ),
    re.compile(r"(?<![A-Za-z0-9])bearer\s+\S+", re.IGNORECASE),
)


def looks_like_credential(text: str) -> bool:
    if text == REDACTED:
        return False
    return any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS)


def mask_component(component: str) -> str:
    return REDACTED if looks_like_credential(component) else component


def _escape(component: str) -> str:
    return component.replace("~", "~0").replace("/", "~1")


def pointer(components: tuple[str, ...]) -> str:
    return "".join("/" + _escape(mask_component(part)) for part in components)


def display_path(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return mask_component(path)
    masked = [mask_component(part) for part in parts]
    if Path(path).is_absolute():
        return masked[0] + "/".join(masked[1:])
    return "/".join(masked)


def _children(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield str(index), item


def _same_leaf(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def redaction_changes(original: Any, redacted: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    if isinstance(original, dict) and isinstance(redacted, dict):
        if list(original) != list(redacted):
            yield path
            return
        for key, item in original.items():
            yield from redaction_changes(item, redacted[key], (*path, str(key)))
        return
    if isinstance(original, (list, tuple)) and isinstance(redacted, (list, tuple)):
        if len(original) != len(redacted):
            yield path
            return
        for index, (item, other) in enumerate(zip(original, redacted)):
            yield from redaction_changes(item, other, (*path, str(index)))
        return
    if not _same_leaf(original, redacted):
        yield path


def credential_strings(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, str):
        if looks_like_credential(value):
            yield path, REASON_CREDENTIAL
        return
    for name, item in _children(value):
        if isinstance(value, dict) and looks_like_credential(name):
            yield (*path, name), REASON_CREDENTIAL_NAME
        yield from credential_strings(item, (*path, name))


class _DuplicateMember(ValueError):
    pass


class _NonStandardConstant(ValueError):
    pass


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateMember
        document[key] = value
    return document


def _reject_constant(_: str) -> Any:
    raise _NonStandardConstant


def parse_json(text: str) -> Any:
    """Parse strict RFC 8259 JSON: no NaN/Infinity and no duplicate member names.

    A duplicate name would let a credential hide behind a later clean value,
    because only the last one survives parsing.
    """
    return json.loads(text, object_pairs_hook=_unique_members, parse_constant=_reject_constant)


def check_file(path: Path, shown: str) -> list[dict[str, str]]:
    def finding(location: tuple[str, ...], reason: str) -> dict[str, str]:
        return {"file": shown, "pointer": pointer(location), "reason": reason}

    try:
        raw = path.read_bytes()
    except Exception:
        return [finding((), REASON_UNREADABLE)]
    try:
        text = raw.decode("utf-8")
    except Exception:
        return [finding((), REASON_INVALID_UTF8)]
    try:
        document = parse_json(text)
    except _DuplicateMember:
        return [finding((), REASON_DUPLICATE_MEMBER)]
    except Exception:
        return [finding((), REASON_INVALID_JSON)]

    findings: list[dict[str, str]] = []
    try:
        sanitized = redact(document)
    except Exception:
        findings.append(finding((), REASON_REDACTION_FAILED))
    else:
        try:
            findings.extend(finding(location, REASON_REDACTION_CHANGED) for location in redaction_changes(document, sanitized))
        except Exception:
            findings.append(finding((), REASON_REDACTION_FAILED))
    try:
        findings.extend(finding(location, reason) for location, reason in credential_strings(document))
    except Exception:
        findings.append(finding((), REASON_REDACTION_FAILED))
    return findings


def _targets(arguments: list[str]) -> list[tuple[Path, str]]:
    if arguments:
        return [(Path(argument), display_path(argument)) for argument in arguments]
    found = sorted((REPO_ROOT / "inventories").glob("**/*.json"))
    return [(path, display_path(path.relative_to(REPO_ROOT).as_posix())) for path in found]


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    findings: list[dict[str, str]] = []
    for path, shown in _targets(arguments):
        findings.extend(check_file(path, shown))
    print(json.dumps(findings, indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
