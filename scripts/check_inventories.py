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
from urllib.parse import unquote

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
REASON_HOME_PATH = "value contains an absolute home folder path"
REASON_HOME_PATH_NAME = "member name contains an absolute home folder path"

# Committed evidence uses home-relative paths ("~/.openclaw"), so an absolute
# home folder path such as /Users/<name> or /home/<name> leaks a user name.
# The match starts at the start of the string, a character that is not a
# letter, digit, "_", "." or "-", or a URL authority ("ssh://host/home/al"),
# ignores case, and needs a user name component, so a bare "/Users" or "/home"
# is not flagged. "/srv/home/x" is flagged too: a nested home folder can name
# a user just as well. Percent-encoded forms are checked after decoding.
HOME_PATH_PATTERN = re.compile(
    r"(?:^|[^\w.-]|://[^/\s\"']*)/(?:Users|home)/[^/\s\"'?#&]+",
    re.IGNORECASE,
)

# The PEM marker is assembled from pieces so this file does not itself look
# like a private key block to secret scanners.
_PEM_DASHES = "-" * 5
# Value prefixes stay precise: a prefix must start at a token boundary (the
# start of the string or a character that is not a Unicode letter or digit)
# and be followed by at least 20 key characters. Embedded keys such as "key=sk-..." or "(ghp_...)"
# are found, while prose such as "task-list" or "ask-for-help" is not.
_KEY_BODY_MIN = 20
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![^\W_])sk-[A-Za-z0-9_-]{%d,}" % _KEY_BODY_MIN),
    re.compile(r"(?<![^\W_])ghp_[A-Za-z0-9_-]{%d,}" % _KEY_BODY_MIN),
    re.compile(
        _PEM_DASHES
        + r"BEGIN (?:(?:RSA|EC|DSA|ENCRYPTED|OPENSSH) )?PRIVATE KEY"
        + _PEM_DASHES
    ),
    re.compile(r"bearer\s+\S+", re.IGNORECASE),
)


def looks_like_credential(text: str) -> bool:
    if text == REDACTED:
        return False
    return any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS)


# Display masking stays greedy: a file name, directory name or pointer
# component that contains a prefix anywhere is shown as <redacted>, so a key
# glued to other text ("dirsk-...") is never printed even though it is not
# reported as a finding on its own.
_MASK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"ghp_[A-Za-z0-9_-]+"),
)


def mask_component(component: str) -> str:
    if looks_like_credential(component) or any(pattern.search(component) for pattern in _MASK_PATTERNS):
        return REDACTED
    if has_home_path(component):
        return REDACTED
    return component


def _escape(component: str) -> str:
    return component.replace("~", "~0").replace("/", "~1")


def pointer(components: tuple[str, ...]) -> str:
    return "".join("/" + _escape(mask_component(part)) for part in components)


# Path components that name the user when they follow one of these
# (compared case-insensitively).
_HOME_PARENTS = frozenset({"users", "home"})


def display_path(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return mask_component(path)
    masked = [
        REDACTED if index > 0 and parts[index - 1].lower() in _HOME_PARENTS else mask_component(part)
        for index, part in enumerate(parts)
    ]
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
        for index, (item, other) in enumerate(zip(original, redacted, strict=True)):
            yield from redaction_changes(item, other, (*path, str(index)))
        return
    if not _same_leaf(original, redacted):
        yield path


def has_home_path(text: str) -> bool:
    form = text
    for _ in range(4):
        if HOME_PATH_PATTERN.search(form):
            return True
        decoded = unquote(form)
        if decoded == form:
            return False
        form = decoded
    return False


def credential_strings(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, str):
        if looks_like_credential(value):
            yield path, REASON_CREDENTIAL
        if has_home_path(value):
            yield path, REASON_HOME_PATH
        return
    for name, item in _children(value):
        if isinstance(value, dict) and looks_like_credential(name):
            yield (*path, name), REASON_CREDENTIAL_NAME
        if isinstance(value, dict) and has_home_path(name):
            yield (*path, name), REASON_HOME_PATH_NAME
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
