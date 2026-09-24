from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_platform.inventory import CommandResult, InventoryCollector, redact


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


if __name__ == "__main__":
    unittest.main()
