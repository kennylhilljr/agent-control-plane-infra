from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ci.md"
WORKFLOW = ROOT / ".github" / "workflows" / "check.yml"
RT = chr(34) + "$RUNNER_TEMP/gitleaks" + chr(34)
SHA = "5bc41815076e6ed6ef8fbecc9d9b75bcae31f39029ceb55da08086315316e3ba"
URL = (
    "https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/"
    "gitleaks_8.21.2_linux_x64.tar.gz"
)


class DocsCiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def yaml(self) -> str:
        return self.workflow

    def test_doc_has_no_workflow_copy(self) -> None:
        """DOCS-CI-01: docs/ci.md points at the committed workflow instead of a copy that can drift."""
        self.assertNotIn("```yaml", self.text)
        self.assertIn(".github/workflows/check.yml", self.text)

    def test_workflow_token_is_read_only(self) -> None:
        """DOCS-CI-11: the workflow sets a top-level read-only token and no job widens it."""
        y = self.yaml()

        self.assertIsNotNone(re.search(r"^permissions:\n  contents: read\n(?!  \S)", y, re.M))
        self.assertEqual(len(re.findall(r"^\s*permissions:", y, re.M)), 1)
        self.assertNotIn("write", y)
        self.assertNotIn("secrets.", y)
        self.assertNotIn("pull_request_target", y)

    def test_actions_are_pinned_to_commit_shas(self) -> None:
        """DOCS-CI-12: every uses: line names a full 40-hex commit SHA with a version comment."""
        uses = re.findall(r"^\s*-?\s*uses:\s*(.+)$", self.yaml(), re.M)

        self.assertGreaterEqual(len(uses), 2)
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")

    def test_checkout_does_not_persist_token(self) -> None:
        """DOCS-CI-13: checkout leaves the token out of the clone that gitleaks scans."""
        self.assertIsNotNone(
            re.search(r"uses: actions/checkout@\S+.*\n\s+with:\n\s+persist-credentials: false\n", self.yaml())
        )

    def test_workflow_contains_required_pieces(self) -> None:
        """DOCS-CI-02: the workflow names triggers, matrix, actions and the pinned gitleaks download."""
        y = self.yaml()

        for needle in (
            "push:",
            "pull_request:",
            "ubuntu-latest",
            "'3.11'",
            "'3.13'",
            "actions/checkout@",
            "actions/setup-python@",
            "${{ matrix.python-version }}",
            URL,
            SHA + "  gitleaks_8.21.2_linux_x64.tar.gz",
            "sha256sum -c ",
            "-C " + RT,
            RT + ' >> "$GITHUB_PATH"',
        ):
            self.assertIn(needle, y)

    def test_triggers_are_nested_under_on(self) -> None:
        """DOCS-CI-03: push and pull_request are indented under on:."""
        y = self.yaml()

        self.assertIsNotNone(re.search(r"^on:\n(?:[ ]+.*\n)*?[ ]+push:", y, re.M))
        self.assertIsNotNone(re.search(r"^on:\n(?:[ ]+.*\n)*?[ ]+pull_request:", y, re.M))

    def test_setup_python_uses_matrix_version(self) -> None:
        """DOCS-CI-04: setup-python reads the matrix Python version."""
        y = self.yaml()

        self.assertIsNotNone(
            re.search(r"^\s*python-version: \$\{\{ matrix\.python-version \}\}\s*$", y, re.M)
        )

    def test_gitleaks_url_versions_agree(self) -> None:
        """DOCS-CI-05: every gitleaks URL uses v8.21.2 in both the tag and the file name."""
        y = self.yaml()

        urls = re.findall(
            r"https://github\.com/gitleaks/gitleaks/releases/download/v([0-9.]+)"
            r"/gitleaks_([0-9.]+)_linux_x64\.tar\.gz",
            y,
        )

        self.assertTrue(urls)
        for pair in urls:
            self.assertEqual(pair, ("8.21.2", "8.21.2"))

    def test_checksum_failure_stops_before_extraction(self) -> None:
        """DOCS-CI-06: sha256sum -c reads the generated file and runs before tar extracts under RUNNER_TEMP."""
        y = self.yaml()

        self.assertNotIn("|| true", y)
        self.assertNotIn("continue-on-error", y)
        self.assertNotIn("set +e", y)

        ck = re.search(r"sha256sum -c (\S+)", y)
        self.assertIsNotNone(ck)
        assert ck is not None
        self.assertIsNotNone(re.search(r"> " + re.escape(ck.group(1)) + r"\b", y))

        i_s = y.find("sha256sum -c ")
        i_t = y.find("tar -xzf ")
        self.assertNotEqual(i_s, -1)
        self.assertNotEqual(i_t, -1)
        self.assertLess(i_s, i_t)

        self.assertIsNotNone(
            re.search(
                r"^\s*tar -xzf gitleaks_8\.21\.2_linux_x64\.tar\.gz -C " + re.escape(RT) + r"\s*$",
                y,
                re.M,
            )
        )

    def test_workflow_ends_with_check_script(self) -> None:
        """DOCS-CI-07: the last workflow line runs sh scripts/check.sh."""
        y = self.yaml()

        self.assertIsNotNone(re.search(r"run: sh scripts/check\.sh\s*\Z", y))

    def test_doc_names_install_path_hook_and_later_gates(self) -> None:
        """DOCS-CI-08: the doc names the install path, the hook command and the deferred gates."""
        for needle in (
            ".github/workflows/check.yml",
            "git config core.hooksPath githooks",
            "dependency vulnerability scanning",
            "SBOM generation",
            "80% diff coverage",
            "formatter",
            "lint",
            "type checking",
        ):
            self.assertIn(needle, self.text)

    def test_doc_describes_optional_check_steps(self) -> None:
        """DOCS-CI-10: the doc says ShellCheck and the inventory validator are skipped when absent."""
        self.assertIn("shellcheck not installed; skipping", self.text)
        self.assertIn("scripts/check_inventories.py", self.text)
        self.assertIn("ALLOW_NO_GITLEAKS=1", self.text)
        self.assertNotIn("inventories/latest.json", self.text)

    def test_doc_has_no_en_or_em_dash(self) -> None:
        """DOCS-CI-09: the doc and the workflow have no en or em dash."""
        for text in (self.text, self.workflow):
            self.assertNotIn(chr(0x2013), text)
            self.assertNotIn(chr(0x2014), text)


if __name__ == "__main__":
    unittest.main()
