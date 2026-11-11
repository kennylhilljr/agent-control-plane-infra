from __future__ import annotations

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "ci.md"
RT = chr(34) + "$RUNNER_TEMP/gitleaks" + chr(34)
SHA = "5bc41815076e6ed6ef8fbecc9d9b75bcae31f39029ceb55da08086315316e3ba"
URL = (
    "https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/"
    "gitleaks_8.21.2_linux_x64.tar.gz"
)


class DocsCiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")
        self.fences = re.findall(r"^```yaml\n(.*?)^```$", self.text, re.S | re.M)

    def yaml(self) -> str:
        self.assertEqual(len(self.fences), 1)
        return self.fences[0]

    def test_doc_has_exactly_one_yaml_fence(self) -> None:
        """DOCS-CI-01: docs/ci.md holds exactly one yaml fence."""
        self.assertEqual(len(self.fences), 1)

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

    def test_doc_has_no_en_or_em_dash(self) -> None:
        """DOCS-CI-09: the doc has no en or em dash."""
        self.assertNotIn(chr(0x2013), self.text)
        self.assertNotIn(chr(0x2014), self.text)


if __name__ == "__main__":
    unittest.main()
