from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

CHECKER = REPO_ROOT / "scripts" / "check_inventories.py"
REDACTED = "<redacted>"

CHANGED = "value changes under redaction"
CREDENTIAL = "value looks like a credential"
CREDENTIAL_NAME = "member name looks like a credential"


def openai_key() -> str:
    # Credential-shaped fixtures are built at runtime so this file stays clean
    # for gitleaks.
    return "sk-" + "Q" * 40


def github_token() -> str:
    return "ghp" + "_" + "R" * 36


def pem_block(kind: str = "") -> str:
    label = f"{kind} PRIVATE KEY" if kind else "PRIVATE KEY"
    dashes = "-" * 5
    return f"{dashes}BEGIN {label}{dashes}\nAAAA\n{dashes}END {label}{dashes}\n"


def bearer() -> str:
    return "Bearer " + "T" * 30


class CheckInventoriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name: str, document: object) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def run_checker(
        self, *arguments: str, checker: Path = CHECKER, cwd: Path | None = None
    ) -> tuple[int, list[dict[str, str]], str, str]:
        completed = subprocess.run(
            [sys.executable, str(checker), *arguments],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=str(cwd or self.dir),
        )
        findings = json.loads(completed.stdout)
        for item in findings:
            self.assertEqual(set(item), {"file", "pointer", "reason"})
        return completed.returncode, findings, completed.stdout, completed.stderr

    def assertNoLeak(self, secret: str, *streams: str) -> None:
        for stream in streams:
            self.assertNotIn(secret, stream)

    def locations(self, findings: list[dict[str, str]]) -> set[tuple[str, str]]:
        return {(item["pointer"], item["reason"]) for item in findings}

    def test_clean_file_passes_and_input_is_unchanged(self) -> None:
        path = self.write(
            "clean.json",
            {
                "security": {"plaintext_secret_count": 0, "secrets_audit_status": "clean"},
                "providers": {"openai": {"credential_configured": True}},
                "usage": {"input_tokens": 12, "output_tokens": 3},
                "token": REDACTED,
                "note": "plain text without credential shapes",
            },
        )
        before = path.read_bytes()
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual((code, findings), (0, []))
        self.assertEqual(stderr, "")
        self.assertEqual(path.read_bytes(), before)

    def test_unredacted_private_key(self) -> None:
        secret = "plain-material-" + "z" * 20
        path = self.write("leak.json", {"device": {"private_key": secret}})
        before = path.read_bytes()
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(findings, [{"file": str(path), "pointer": "/device/private_key", "reason": CHANGED}])
        self.assertNoLeak(secret, stdout, stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_nested_bearer_and_token_prefixes(self) -> None:
        secrets = {"bearer": bearer(), "openai": openai_key(), "github": github_token()}
        path = self.write(
            "nested.json",
            {
                "a": [{"header": secrets["bearer"]}, "fine"],
                "b": {"c": {"d": "prefix " + secrets["openai"]}},
                "e": secrets["github"],
                "f": "bearer\t" + "x",
                "g": "key=" + secrets["openai"],
                "h": "(" + secrets["github"] + ")",
            },
        )
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(
            self.locations(findings),
            {("/a/0/header", CREDENTIAL), ("/b/c/d", CREDENTIAL), ("/e", CREDENTIAL), ("/f", CREDENTIAL),
             ("/g", CREDENTIAL), ("/h", CREDENTIAL)},
        )
        self.assertNoLeak(secrets["bearer"].split()[1], stdout, stderr)
        self.assertNoLeak(secrets["openai"], stdout, stderr)
        self.assertNoLeak(secrets["github"], stdout, stderr)

    def test_value_prefixes_need_a_boundary_and_a_key_body(self) -> None:
        sys.path.insert(0, str(CHECKER.parent))
        self.addCleanup(sys.path.remove, str(CHECKER.parent))
        from check_inventories import looks_like_credential, mask_component

        body = "Q" * 20
        flagged = [
            "sk-" + body,
            "sk-proj-" + body,
            "key=sk-" + body,
            "x_sk-" + body,
            "see (sk-" + body + ")",
            "token:ghp" + "_" + body,
            "line one\nsk-" + body,
        ]
        for text in flagged:
            with self.subTest(text=text):
                self.assertTrue(looks_like_credential(text))
        ignored = [
            "task-list",
            "ask-for-help",
            "desk-" + body,
            "reportsk-" + body,
            "sk-" + "Q" * 19,
            "sk-short",
            "ghp" + "_" + "Q" * 19,
            "maskghp" + "_" + body,
        ]
        for text in ignored:
            with self.subTest(text=text):
                self.assertFalse(looks_like_credential(text))
        # Display masking stays greedy so a glued key is never printed.
        for text in ("reportsk-" + body, "maskghp" + "_" + body, "dirsk-x"):
            with self.subTest(mask=text):
                self.assertEqual(mask_component(text), REDACTED)
        path = self.write("prose.json", {"steps": ["task-list", "ask-for-help", "risk-free"]})
        self.assertEqual(self.run_checker(str(path))[:2], (0, []))

    def test_private_key_blocks(self) -> None:
        kinds = ["", "RSA", "EC", "ENCRYPTED", "OPENSSH"]
        path = self.write("pem.json", {"blocks": [pem_block(kind) for kind in kinds]})
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(self.locations(findings), {(f"/blocks/{i}", CREDENTIAL) for i in range(len(kinds))})
        self.assertNotIn("AAAA", stdout + stderr)

    def test_sensitive_container_strings_are_reported_twice(self) -> None:
        secret = openai_key()
        path = self.write("container.json", {"tokens": ["ok", {"inner": secret}]})
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(
            self.locations(findings),
            {("/tokens", CHANGED), ("/tokens/1/inner", CREDENTIAL)},
        )
        self.assertNoLeak(secret, stdout, stderr)

    def test_root_string_document(self) -> None:
        secret = openai_key()
        path = self.write("root.json", secret)
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual((code, self.locations(findings)), (1, {("", CREDENTIAL)}))
        self.assertNoLeak(secret, stdout, stderr)

    def test_escaped_pointers(self) -> None:
        path = self.write("escape.json", {"a/b": {"c~d": {"token": "v"}}, "": {"secret": "w"}})
        code, findings, _, _ = self.run_checker(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(
            self.locations(findings),
            {("/a~1b/c~0d/token", CHANGED), ("//secret", CHANGED)},
        )

    def test_multiple_findings_and_files_continue_after_failure(self) -> None:
        broken = self.dir / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        good = self.write("good.json", {"ok": True})
        bad = self.write("bad.json", {"password": "x", "list": [bearer()]})
        code, findings, _, _ = self.run_checker(str(broken), str(good), str(bad))
        self.assertEqual(code, 1)
        self.assertEqual(
            [(item["file"], item["pointer"], item["reason"]) for item in findings],
            [
                (str(broken), "", "invalid JSON"),
                (str(bad), "/password", CHANGED),
                (str(bad), "/list/0", CREDENTIAL),
            ],
        )

    def test_invalid_json_with_credential_does_not_echo_input(self) -> None:
        secret = openai_key()
        path = self.dir / "invalid.json"
        path.write_text('{"token": "' + secret + '", broken', encoding="utf-8")
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual((code, findings), (1, [{"file": str(path), "pointer": "", "reason": "invalid JSON"}]))
        self.assertNoLeak(secret, stdout, stderr)
        self.assertNotIn("Traceback", stderr)

    def test_duplicate_members_and_nonstandard_constants_fail(self) -> None:
        secret = bearer()
        duplicate = self.dir / "duplicate.json"
        duplicate.write_text('{"a": {"auth": ' + json.dumps(secret) + ', "auth": "safe"}}', encoding="utf-8")
        files = [str(duplicate)]
        for constant in ("NaN", "Infinity", "-Infinity"):
            path = self.dir / f"constant{constant}.json"
            path.write_text('{"ok": ' + constant + "}", encoding="utf-8")
            files.append(str(path))
        code, findings, stdout, stderr = self.run_checker(*files)
        self.assertEqual(code, 1)
        self.assertEqual(
            [(item["file"], item["pointer"], item["reason"]) for item in findings],
            [(files[0], "", "duplicate object member")] + [(name, "", "invalid JSON") for name in files[1:]],
        )
        self.assertNoLeak(secret.split()[1], stdout, stderr)

    def test_credential_shaped_member_names_are_reported_and_masked(self) -> None:
        secret = openai_key()
        token = github_token()
        path = self.write("names.json", {secret: "safe", "outer": [{f"x-{token}": 1}], "fine": {"name": "v"}})
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(
            self.locations(findings),
            {(f"/{REDACTED}", CREDENTIAL_NAME), (f"/outer/0/{REDACTED}", CREDENTIAL_NAME)},
        )
        self.assertNoLeak(secret, stdout, stderr)
        self.assertNoLeak(token, stdout, stderr)

    def test_invalid_utf8_and_missing_file(self) -> None:
        bad_bytes = self.dir / "latin.json"
        bad_bytes.write_bytes(b'{"name": "\xff\xfe"}')
        missing = self.dir / "missing.json"
        code, findings, stdout, stderr = self.run_checker(str(bad_bytes), str(missing))
        self.assertEqual(code, 1)
        self.assertEqual(
            findings,
            [
                {"file": str(bad_bytes), "pointer": "", "reason": "invalid UTF-8"},
                {"file": str(missing), "pointer": "", "reason": "unreadable file"},
            ],
        )
        self.assertEqual(stderr, "")

    def test_relative_paths_resolve_against_working_directory(self) -> None:
        self.write("sub/one.json", {"token": "v"})
        self.write("sub/two.json", {"ok": 1})
        code, findings, _, _ = self.run_checker("sub/two.json", cwd=self.dir)
        self.assertEqual((code, findings), (0, []))
        code, findings, _, _ = self.run_checker("sub/one.json", cwd=self.dir)
        self.assertEqual(findings, [{"file": "sub/one.json", "pointer": "/token", "reason": CHANGED}])

    def test_metadata_suffix_values(self) -> None:
        cases = {
            "token_count": [0, 3, 1.5],
            "input_tokens": [10],
            "secret_status": [True, False, None],
            "api_key_configured": [True, None],
            "private_key_present": [False],
            "PRIVATEKEYPRESENT": [True, None],
            "secretcount": [2],
            "secrets_audit_status": ["clean", True, None],
        }
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    path = self.write("meta.json", {key: value})
                    code, findings, _, _ = self.run_checker(str(path))
                    self.assertEqual((code, findings), (0, []))
        rejected = {
            "token_count": ["3", True, [1], {"n": 1}],
            "input_tokens": ["opaque", None],
            "secret_status": ["opaque", 1, ["x"], {"k": "v"}],
            "api_key_configured": ["yes", [], {}],
            "private_key_present": ["opaque", 0],
            "PRIVATEKEYPRESENT": ["opaque", 1],
            "secretcount": ["2", True],
            "secrets_audit_status": ["dirty", "clean ", "CLEAN", "Clean", "", ["clean"], {"clean": True}, 1],
        }
        for key, values in rejected.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    path = self.write("meta.json", {"wrap": {key: value}})
                    code, findings, _, _ = self.run_checker(str(path))
                    self.assertEqual(code, 1)
                    self.assertEqual(self.locations(findings), {(f"/wrap/{key}", CHANGED)})

    def test_credentials_in_names_and_pointers_are_masked(self) -> None:
        secret = openai_key()
        token = github_token()
        # Parsed file: credentials in the directory name, file name and a key.
        directory = f"dir{secret}"
        name = f"evidence{token}.json"
        path = self.write(f"{directory}/{name}", {f"id-{secret}": {"password": "v"}, "x": [secret]})
        code, findings, stdout, stderr = self.run_checker(str(path))
        self.assertEqual(code, 1)
        masked_file = str(self.dir / REDACTED / REDACTED)
        self.assertEqual({item["file"] for item in findings}, {masked_file})
        self.assertEqual(
            self.locations(findings),
            {(f"/{REDACTED}", CREDENTIAL_NAME), (f"/{REDACTED}/password", CHANGED), ("/x/0", CREDENTIAL)},
        )
        for value in (secret, token, bearer()):
            self.assertNoLeak(value, stdout, stderr)

        # Error path: unreadable, invalid UTF-8 and invalid JSON files with credential names.
        missing = self.dir / f"gone{secret}.json"
        undecodable = self.dir / f"raw{token}.json"
        undecodable.write_bytes(b"\xff")
        unparsable = self.dir / f"{secret}" / "x.json"
        unparsable.parent.mkdir()
        unparsable.write_text("{", encoding="utf-8")
        code, findings, stdout, stderr = self.run_checker(str(missing), str(undecodable), str(unparsable))
        self.assertEqual(code, 1)
        self.assertEqual(
            [item["file"] for item in findings],
            [str(self.dir / REDACTED), str(self.dir / REDACTED), str(self.dir / REDACTED / "x.json")],
        )
        for value in (secret, token):
            self.assertNoLeak(value, stdout, stderr)

    def test_default_discovery_in_disposable_repository(self) -> None:
        repo = self.dir / "repo"
        shutil.copytree(REPO_ROOT / "src" / "agent_platform", repo / "src" / "agent_platform",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (repo / "scripts").mkdir(parents=True)
        shutil.copy2(CHECKER, repo / "scripts" / "check_inventories.py")
        inventories = repo / "inventories"
        (inventories / "deep" / "deeper").mkdir(parents=True)
        (inventories / "a.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        (inventories / "deep" / "deeper" / "b.json").write_text(json.dumps({"token": "v"}), encoding="utf-8")
        (inventories / "deep" / "c.json").write_text(json.dumps({"tokens": [openai_key()]}), encoding="utf-8")
        (inventories / "notes.txt").write_text("sk-ignored", encoding="utf-8")
        (repo / "outside.json").write_text(json.dumps({"token": "v"}), encoding="utf-8")
        before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}

        code, findings, stdout, stderr = self.run_checker(checker=repo / "scripts" / "check_inventories.py", cwd=self.dir)
        self.assertEqual(code, 1)
        self.assertEqual(
            [(item["file"], item["pointer"], item["reason"]) for item in findings],
            [
                ("inventories/deep/c.json", "/tokens", CHANGED),
                ("inventories/deep/c.json", "/tokens/0", CREDENTIAL),
                ("inventories/deep/deeper/b.json", "/token", CHANGED),
            ],
        )
        self.assertNoLeak(openai_key(), stdout, stderr)
        after = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
        self.assertEqual({k: v for k, v in before.items()}, after)

    def test_committed_inventories_are_clean(self) -> None:
        before = {path: path.read_bytes() for path in (REPO_ROOT / "inventories").rglob("*.json")}
        code, findings, _, stderr = self.run_checker(cwd=REPO_ROOT)
        self.assertEqual((code, findings, stderr), (0, [], ""))
        after = {path: path.read_bytes() for path in (REPO_ROOT / "inventories").rglob("*.json")}
        self.assertEqual(before, after)

    def test_agents_md_documents_the_checker(self) -> None:
        text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for phrase in (
            "python3 -m unittest discover -s tests -v",
            "python3 scripts/check_inventories.py",
            "python3 scripts/check_inventories.py inventories/latest.json",
            "JSON Pointer",
            "secrets_audit_status",
            "_count",
            "_status",
            "TMPDIR",
            "MIGRATION_SPEC.md",
            "section 7",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(phrase in text, f"AGENTS.md does not mention {phrase!r}")


if __name__ == "__main__":
    unittest.main()
