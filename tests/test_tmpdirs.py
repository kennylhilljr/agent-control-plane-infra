from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

# Set only in the child suites this module launches. Its value is the
# temporary directory the child must be using; its presence stops the child
# from launching suites of its own.
CHILD_MARKER = "AGENT_PLATFORM_TMPDIR_CHILD"
SUITE_TIMEOUT_SECONDS = 600


def _child_environment(tmpdir: Path, home: Path | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["TMPDIR"] = str(tmpdir)
    environment[CHILD_MARKER] = str(tmpdir)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if home is not None:
        environment["HOME"] = str(home)
    return environment


class TemporaryDirectoryTests(unittest.TestCase):
    def test_child_uses_requested_tmpdir(self) -> None:
        expected = os.environ.get(CHILD_MARKER)
        if expected is None:
            return  # Parent run: the child suites below perform this check.
        # In a child suite, tempfile must honor TMPDIR instead of silently
        # falling back to another directory.
        self.assertEqual(Path(tempfile.gettempdir()).resolve(), Path(expected).resolve())
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(Path(directory).resolve().parent, Path(expected).resolve())

    def run_suite(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(REPO_ROOT),
            env=environment,
            capture_output=True,
            text=True,
            timeout=SUITE_TIMEOUT_SECONDS,
            check=False,
        )

    def assertSuitePassed(self, completed: subprocess.CompletedProcess[str]) -> None:
        tail = "\n".join(completed.stderr.splitlines()[-40:])
        self.assertEqual(completed.returncode, 0, f"child suite failed:\n{tail}")
        self.assertRegex(completed.stderr, r"\nOK")
        # The child must have actually verified its temporary directory.
        self.assertIn("test_child_uses_requested_tmpdir", completed.stderr)
        self.assertRegex(completed.stderr, r"test_child_uses_requested_tmpdir \([^)]*\) \.\.\. ok")

    def test_full_suite_with_system_tmp(self) -> None:
        if CHILD_MARKER in os.environ:
            return
        before = dict(os.environ)
        completed = self.run_suite(_child_environment(Path("/tmp")))
        self.assertEqual(dict(os.environ), before)
        self.assertSuitePassed(completed)

    def test_full_suite_with_openclaw_tmp_under_disposable_home(self) -> None:
        if CHILD_MARKER in os.environ:
            return
        before = dict(os.environ)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            tmpdir = home / ".openclaw" / "tmp"
            tmpdir.mkdir(parents=True)
            completed = self.run_suite(_child_environment(tmpdir, home=home))
        self.assertEqual(dict(os.environ), before)
        self.assertSuitePassed(completed)


if __name__ == "__main__":
    unittest.main()
