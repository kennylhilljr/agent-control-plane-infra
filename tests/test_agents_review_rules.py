from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "AGENTS.md"
TODO = REPO_ROOT / "TODO.md"


def section(text: str, heading: str) -> str:
    """The body of a level-2 section, up to the next level-2 heading."""
    marker = "## " + heading + "\n"
    if marker not in text:
        raise AssertionError(f"AGENTS.md has no {heading!r} section")
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


class AgentsReviewRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = AGENTS.read_text(encoding="utf-8")
        self.rules = section(self.text, "Review rules")
        self.bullets = [line for line in self.rules.splitlines() if line.startswith("- ")]

    def bullet(self, *needles: str) -> str:
        """The single rule bullet that mentions every needle."""
        found = [b for b in self.bullets if all(n in b for n in needles)]
        self.assertEqual(len(found), 1, f"expected one rule mentioning {needles!r}, got {found!r}")
        return found[0]

    def test_section_comes_after_code_conventions_and_before_safety_rules(self) -> None:
        headings = re.findall(r"^## (.+)$", self.text, re.M)
        self.assertIn("Review rules", headings)
        index = headings.index("Review rules")
        self.assertEqual(headings[index - 1], "Code conventions")
        self.assertEqual(headings[index + 1], "Safety rules")

    def test_section_says_rules_must_hold(self) -> None:
        self.assertIn("treat a broken rule as a defect", self.rules)
        self.assertIn("same PR", self.rules)

    def test_subprocess_rule(self) -> None:
        rule = self.bullet("run_command")
        for needle in ("argument tuple", "timeout", "shell=True", "src/agent_platform/"):
            self.assertIn(needle, rule)

    def test_collector_rule(self) -> None:
        rule = self.bullet("InventoryCollector")
        for needle in ("`locate`", "`run`", "`home`", "fakes"):
            self.assertIn(needle, rule)

    def test_test_isolation_rule(self) -> None:
        rule = self.bullet("tempfile")
        for needle in ("home folder", "~/.openclaw", "network", "inventories/latest.json", "TMPDIR"):
            self.assertIn(needle, rule)

    def test_redaction_rule(self) -> None:
        rule = self.bullet("redaction test")
        self.assertIn("every new inventory field", rule)
        self.assertIn("`redact`", rule)

    def test_envelope_rule_lists_all_seven_keys(self) -> None:
        rule = self.bullet("build_envelope")
        self.assertIn("MIGRATION_SPEC.md` section 7", rule)
        for key in ("ok", "operation", "changed", "checks", "warnings",
                    "required_user_actions", "rollback_checkpoint"):
            self.assertIn(f"`{key}`", rule)
        self.assertIn("safe_error_message", rule)
        self.assertIn("--json", rule)

    def test_backup_symlink_rule(self) -> None:
        rule = self.bullet("symlink", "source root")
        for needle in ("do not follow symlinks", "resolved", "left out of the archive", "`symlinks`"):
            self.assertIn(needle, rule)

    def test_verify_archive_rule(self) -> None:
        rule = self.bullet("verify_archive")
        for needle in ("absolute", "`..`", "symlink", "hard link", "device"):
            self.assertIn(needle, rule)

    def test_json_rule(self) -> None:
        rule = self.bullet("indent=2")
        self.assertIn("sort_keys=True", rule)

    def test_rules_moved_out_of_code_conventions(self) -> None:
        conventions = section(self.text, "Code conventions")
        for needle in ("run_command", "InventoryCollector", "indent=2", "redaction test"):
            self.assertNotIn(needle, conventions)

    def test_tests_and_checks_names_the_check_script(self) -> None:
        checks = section(self.text, "Tests and checks")
        self.assertIn("`scripts/check.sh` is the single check command", checks)
        self.assertIn("git config core.hooksPath githooks", checks)
        self.assertIn("docs/ci.md", checks)

    def test_no_en_or_em_dashes(self) -> None:
        self.assertNotIn(chr(0x2013), self.text)
        self.assertNotIn(chr(0x2014), self.text)


class TodoPhase8NoteTests(unittest.TestCase):
    def test_ci_line_has_dated_note_and_stays_open(self) -> None:
        text = TODO.read_text(encoding="utf-8")
        line = "- [ ] **AUTO** Add CI, coverage, lint, type, security, secret, and SBOM gates.\n"
        self.assertIn(line, text)
        note = text.split(line, 1)[1].split("\n- [", 1)[0]
        self.assertRegex(note, r"^  \d{4}-\d{2}-\d{2}: ")
        self.assertIn("scripts/check.sh", note)
        self.assertIn("pre-push hook", note)


if __name__ == "__main__":
    unittest.main()
