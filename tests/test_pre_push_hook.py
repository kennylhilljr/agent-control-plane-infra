from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
HOOK = REPO / "githooks" / "pre-push"
TIMEOUT = 30


def has_sh() -> bool:
    return os.path.exists("/bin/sh")


class PrePushHookTest(unittest.TestCase):
    def make_fixture(self, check_body: str | None) -> pathlib.Path:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        tmp = pathlib.Path(tmp_dir.name)
        (tmp / "githooks").mkdir()
        (tmp / "scripts").mkdir()
        hook = tmp / "githooks" / "pre-push"
        shutil.copy(HOOK, hook)
        hook.chmod(0o755)
        if check_body is not None:
            check = tmp / "scripts" / "check.sh"
            check.write_text(check_body)
            check.chmod(0o755)
        return tmp

    def run_hook(self, tmp: pathlib.Path, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/sh", str(tmp / "githooks" / "pre-push")],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )

    def test_exists_and_executable(self) -> None:
        self.assertTrue(os.path.isfile(HOOK))
        self.assertTrue(os.access(HOOK, os.X_OK))

    def test_shebang_is_sh(self) -> None:
        first_line = HOOK.read_text().splitlines()[0]
        self.assertEqual(first_line, "#!/bin/sh")

    def test_hook_sh_n_passes(self) -> None:
        if not has_sh():
            self.skipTest("/bin/sh is not available")
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                ["/bin/sh", "-n", str(HOOK)],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runs_check_script_and_returns_zero(self) -> None:
        if not has_sh():
            self.skipTest("/bin/sh is not available")
        tmp = self.make_fixture("#!/bin/sh\nexit 0\n")
        result = self.run_hook(tmp, cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_propagates_exit_code(self) -> None:
        if not has_sh():
            self.skipTest("/bin/sh is not available")
        tmp = self.make_fixture("#!/bin/sh\nexit 3\n")
        result = self.run_hook(tmp, cwd=tmp)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)

    def test_missing_check_script_fails_with_message(self) -> None:
        if not has_sh():
            self.skipTest("/bin/sh is not available")
        tmp = self.make_fixture(None)
        result = self.run_hook(tmp, cwd=tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scripts/check.sh", result.stderr)

    def test_hook_cds_to_repo_root(self) -> None:
        if not has_sh():
            self.skipTest("/bin/sh is not available")
        tmp = self.make_fixture('#!/bin/sh\npwd -P > "$(dirname -- "$0")/../cwd.out"\nexit 0\n')
        with tempfile.TemporaryDirectory() as sibling:
            result = self.run_hook(tmp, cwd=pathlib.Path(sibling))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((tmp / "cwd.out").read_text().strip(), str(tmp.resolve()))


if __name__ == "__main__":
    unittest.main()
