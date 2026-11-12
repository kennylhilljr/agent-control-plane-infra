from __future__ import annotations

import json
import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_platform.inventory import AUDIT_STATUS_ALLOWLIST, CommandResult, InventoryCollector, redact

REDACTED = "<redacted>"


def fake_secret(prefix: str = "sk-") -> str:
    # Built at runtime so the test file never contains a credential-shaped literal.
    return prefix + "x" * 40


class InventoryTests(unittest.TestCase):
    def test_redact_removes_secret_values_and_sensitive_environment_keys(self) -> None:
        source = {
            "OPENAI_API_KEY": "sk-secret",
            "nested": {"token": "bearer-value", "status": "configured"},
            "url": "https://example.test/path?api_key=secret&safe=yes",
        }

        sanitized = redact(source)

        self.assertEqual(sanitized["OPENAI_API_KEY"], "<redacted>")
        self.assertEqual(sanitized["nested"]["token"], "<redacted>")
        self.assertNotIn("secret", json.dumps(sanitized))
        self.assertIn("safe=yes", sanitized["url"])

    def test_collector_records_missing_hanging_and_ready_runners(self) -> None:
        results = {
            ("openclaw", "--version"): CommandResult(0, "2026.2.3-1", "", False),
            ("claude", "--version"): CommandResult(0, "2.1.39", "", False),
            ("codex", "--version"): CommandResult(None, "", "", True),
        }

        def locate(command: str) -> str | None:
            return None if command == "kimi" else f"/usr/local/bin/{command}"

        def run(command: tuple[str, ...], timeout: float) -> CommandResult:
            return results.get(command, CommandResult(0, "1.0.0", "", False))

        with tempfile.TemporaryDirectory() as directory:
            collector = InventoryCollector(
                locate=locate,
                run=run,
                home=Path(directory),
                repositories=[],
            )
            inventory = collector.collect()

        runners = inventory["runners"]
        self.assertEqual(runners["openclaw"]["status"], "ready")
        self.assertEqual(runners["codex"]["status"], "timeout")
        self.assertEqual(runners["kimi"]["status"], "missing")
        self.assertEqual(inventory["schema_version"], "1.0")

    def test_repository_inventory_does_not_include_diff_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()

            def run(command: tuple[str, ...], timeout: float) -> CommandResult:
                if command[-2:] == ("status", "--porcelain=v1"):
                    return CommandResult(0, " M secret.txt\n?? new.txt", "", False)
                if command[-2:] == ("rev-parse", "--show-toplevel"):
                    return CommandResult(0, str(repo), "", False)
                if command[-3:] == ("rev-parse", "--abbrev-ref", "HEAD"):
                    return CommandResult(0, "main", "", False)
                if command[-2:] == ("rev-parse", "HEAD"):
                    return CommandResult(0, "abc123", "", False)
                return CommandResult(1, "", "not available", False)

            collector = InventoryCollector(
                locate=lambda _: None,
                run=run,
                home=Path(directory),
                repositories=[repo],
            )
            repository = collector.collect()["repositories"][0]

        self.assertTrue(repository["dirty"])
        self.assertEqual(repository["changed_files"], ["secret.txt", "new.txt"])
        self.assertNotIn("contents", repository)

    def test_configured_boolean_is_not_redacted(self) -> None:
        self.assertEqual(redact({"credential_configured": True}), {"credential_configured": True})

    def test_ecc_inventory_checks_known_installation_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude" / "skills" / "everything-claude-code").mkdir(parents=True)
            inventory = InventoryCollector(
                locate=lambda _: None,
                run=lambda command, timeout: CommandResult(1, "", "", False),
                home=home,
                repositories=[],
            ).collect()

        self.assertTrue(inventory["ecc"]["claude"]["present"])
        self.assertFalse(inventory["ecc"]["codex"]["present"])
        self.assertFalse(inventory["ecc"]["kimi"]["present"])

    def test_openclaw_inventory_keeps_metadata_but_drops_device_tokens(self) -> None:
        payloads = {
            ("openclaw", "agents", "list", "--bindings", "--json"): [
                {"id": "main", "isDefault": True, "bindings": 2, "routes": ["private-route"]}
            ],
            ("openclaw", "plugins", "list", "--json"): {
                "plugins": [{"id": "memory", "enabled": True, "status": "loaded", "configJsonSchema": {"secret": "x"}}]
            },
            ("openclaw", "cron", "list", "--all", "--json", "--timeout", "3000"): {
                "jobs": [{"id": "job-1", "enabled": True, "prompt": "do not save me"}]
            },
            ("openclaw", "devices", "list", "--json", "--timeout", "3000"): {
                "paired": [{"role": "operator", "tokens": ["secret"], "publicKey": "secret"}],
                "pending": [],
            },
            ("openclaw", "models", "list", "--json"): {
                "models": [{"key": "provider/model", "available": True, "contextWindow": 42}]
            },
        }

        def run(command: tuple[str, ...], timeout: float) -> CommandResult:
            if command == ("openclaw", "--version"):
                return CommandResult(0, "2026.2.3-1", "", False)
            if command in payloads:
                return CommandResult(0, json.dumps(payloads[command]), "", False)
            return CommandResult(1, "", "missing", False)

        with tempfile.TemporaryDirectory() as directory:
            inventory = InventoryCollector(
                locate=lambda command: "/bin/openclaw" if command == "openclaw" else None,
                run=run,
                home=Path(directory),
                repositories=[],
            ).collect()

        openclaw = inventory["openclaw"]
        self.assertEqual(openclaw["devices"], {"paired_count": 1, "pending_count": 0, "roles": ["operator"]})
        self.assertEqual(openclaw["cron"], {"job_count": 1, "enabled_count": 1})
        self.assertNotIn("secret", json.dumps(openclaw))
        self.assertNotIn("private-route", json.dumps(openclaw))

    def test_sensitive_key_matrix(self) -> None:
        secret = fake_secret()
        sensitive = [
            # Existing names.
            "api_key", "apikey", "api-key", "OPENAI_API_KEY", "token", "TOKEN", "github_token",
            "x-auth-token", "secret", "client_secret", "password", "db_password", "credential",
            "aws_credential", "authorization", "Authorization",
            # Requested names and their case/separator variants.
            "private_key", "PRIVATE_KEY", "private-key", "privateKey", "PrivateKey", "privatekey",
            "accessToken", "access_token", "ACCESS_TOKEN", "accesstoken",
            "refreshToken", "refresh_token", "REFRESH-TOKEN", "refreshtoken",
            "clientSecret", "ClientSecret", "clientsecret",
            "passphrase", "PASSPHRASE", "key_passphrase", "keyPassphrase",
            "cookie", "Cookie", "session_cookie", "cookies",
            "bearer", "BEARER", "bearer_value",
            "api_keys", "apiKeys", "API_KEYS",
            "tokens", "TOKENS", "Tokens",
            "secrets", "SECRETS", "client_secrets",
            "passwords", "PASSWORDS", "user_passwords",
            # Irregular casing that a camelCase split alone would break apart.
            "PaSsWoRd", "tOkEn", "pRiVaTe_KeY", "aPi_kEy", "SeCrEtS", "cLiEnTsEcReT", "pAsSpHrAsE",
        ]
        for key in sensitive:
            with self.subTest(key=key):
                self.assertEqual(redact({key: secret}), {key: REDACTED})
                self.assertEqual(redact({key: "opaque"}), {key: REDACTED})
                self.assertEqual(redact({key: [secret]}), {key: REDACTED})
                self.assertEqual(redact({key: {"inner": secret}}), {key: REDACTED})

        unrelated = [
            "tokenizer", "Tokenizer", "monkey", "keyboard", "key", "public_key_id", "name",
            "status", "secretary", "passage", "cookbook", "auth_policy", "auth_status",
            "credentials_method", "path", "turnkey",
        ]
        for key in unrelated:
            with self.subTest(key=key):
                self.assertEqual(redact({key: "opaque"}), {key: "opaque"})

    def test_requested_examples(self) -> None:
        secret = "sk-" + "live-1"
        self.assertNotIn(secret, json.dumps(redact({"tokens": [secret]})))
        self.assertEqual(redact({"tokens": ["a", {"secrets": [secret]}]}), {"tokens": REDACTED})
        self.assertEqual(redact({"private_key": "x"}), {"private_key": REDACTED})
        self.assertEqual(redact({"passphrase": "x"}), {"passphrase": REDACTED})
        self.assertEqual(redact({"plaintext_secret_count": 0}), {"plaintext_secret_count": 0})

    def test_secret_metadata_matrix(self) -> None:
        numeric_keys = [
            "plaintext_secret_count", "unresolved_secret_ref_count", "token_count", "api_key_count",
            "input_tokens", "output_tokens", "projected_always_on_tokens", "secretCount",
        ]
        for key in numeric_keys:
            for value in (0, 7, 1.5):
                with self.subTest(key=key, value=value):
                    self.assertEqual(redact({key: value}), {key: value})
            for value in (True, False, None, "0", fake_secret(), [1], {"n": 1}):
                with self.subTest(key=key, value=value):
                    self.assertEqual(redact({key: value}), {key: REDACTED})

        # Non-sensitive counts are untouched in any type; a sensitive key without a
        # metadata suffix is redacted even when its value is a number.
        self.assertEqual(redact({"job_count": "3", "enabled_count": 2}), {"job_count": "3", "enabled_count": 2})
        self.assertEqual(redact({"tokens_total": 4, "tokens": 4}), {"tokens_total": REDACTED, "tokens": REDACTED})

        status_keys = [
            "token_status", "secret_configured", "credential_configured", "api_key_present",
            "private_key_present", "password-status", "cookieConfigured",
        ]
        for key in status_keys:
            for value in (True, False, None):
                with self.subTest(key=key, value=value):
                    self.assertEqual(redact({key: value}), {key: value})
            for value in ("clean", "configured", fake_secret(), 0, 1, 2.5, [True], {"ok": True}, []):
                with self.subTest(key=key, value=value):
                    self.assertEqual(redact({key: value}), {key: REDACTED})

        # Opaque strings without credential prefixes are still redacted under sensitive keys.
        for key in ("tokens", "api_keys", "secret", "bearer"):
            with self.subTest(key=key):
                self.assertEqual(redact({key: "abc123"}), {key: REDACTED})

        # Other sensitive keys keep their existing boolean behavior.
        self.assertEqual(redact({"token": True, "secret": False}), {"token": True, "secret": False})
        self.assertEqual(redact({"token": None}), {"token": REDACTED})

    def test_audit_status_allowlist(self) -> None:
        self.assertEqual(AUDIT_STATUS_ALLOWLIST, {"secrets_audit_status": frozenset({"clean"})})
        key = "secrets_audit_status"
        for value in ("clean", True, False, None):
            with self.subTest(value=value):
                self.assertEqual(redact({key: value}), {key: value})
        for value in ("dirty", "clean ", " clean", "CLEAN", "Clean", "", fake_secret(), fake_secret("ghp_"),
                      ["clean"], {"clean": True}, 0, 1.0):
            with self.subTest(value=value):
                self.assertEqual(redact({key: value}), {key: REDACTED})
        # The exception is exact: normalized or neighbouring keys get no allowance.
        for other in ("SECRETS_AUDIT_STATUS", "secretsAuditStatus", "secret_audit_status", "secrets-audit-status"):
            with self.subTest(key=other):
                self.assertEqual(redact({other: "clean"}), {other: REDACTED})

    def test_redaction_urls_nesting_idempotence_and_nonmutation(self) -> None:
        secret = fake_secret()
        source = {
            "outer": [
                {"endpoint": f"https://user:{secret}@example.test/p?accessToken={secret}&token_count=3&safe=yes"},
                ({"clientSecret": secret, "label": "kept"},),
                {"deep": {"private_key": secret, "plaintext_secret_count": 0, "secrets_audit_status": "clean"}},
            ],
            "tokenizer": "kept",
        }
        snapshot = json.dumps(source, sort_keys=True)
        sanitized = redact(source)
        self.assertEqual(json.dumps(source, sort_keys=True), snapshot)
        self.assertNotIn(secret, repr(sanitized))
        url = sanitized["outer"][0]["endpoint"]
        self.assertIn("safe=yes", url)
        # URL query values get no metadata or allowlist exemptions.
        self.assertIn("token_count=%3Credacted%3E", url)
        self.assertEqual(sanitized["outer"][1][0], {"clientSecret": REDACTED, "label": "kept"})
        self.assertEqual(
            sanitized["outer"][2]["deep"],
            {"private_key": REDACTED, "plaintext_secret_count": 0, "secrets_audit_status": "clean"},
        )
        self.assertEqual(sanitized["tokenizer"], "kept")
        self.assertEqual(redact(sanitized), sanitized)
        self.assertEqual(redact({"tokens": REDACTED}), {"tokens": REDACTED})

    def test_committed_inventories_are_stable_under_redaction(self) -> None:
        root = Path(__file__).resolve().parents[1] / "inventories"
        for path in sorted(root.glob("**/*.json")):
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(redact(document), document)


if __name__ == "__main__":
    unittest.main()
