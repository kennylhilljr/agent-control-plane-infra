from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO / "scripts" / "check.sh"

GOOD_TEST = (
    "import unittest\n"
    "\n"
    "import fixmod\n"
    "\n"
    "\n"
    "class FixtureTest(unittest.TestCase):\n"
    "    def test_value(self):\n"
    "        self.assertEqual(fixmod.VALUE, 1)\n"
)

FAILING_TEST = (
    "import unittest\n"
    "\n"
    "\n"
    "class FixtureTest(unittest.TestCase):\n"
    "    def test_value(self):\n"
    "        self.fail('deliberate failure')\n"
)

INVENTORY_BANNER = "==> inventory"
INVENTORY_SKIP = "scripts/check_inventories.py not present; skipping"


def _write_exec(path: pathlib.Path, content: str) -> None:
    path.write_text(content)
    os.chmod(path, 0o755)


@unittest.skipUnless(
    os.path.exists("/bin/sh") and os.path.exists("/usr/bin/dirname"),
    "requires /bin/sh and /usr/bin/dirname",
)
class CheckScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = pathlib.Path(self._tmp.name)
        self.fixture = root / "repo"
        self.tools = root / "tools"
        self.home = root / "home"
        self.tmpdir = root / "tmp"
        self.record = root / "record.txt"
        for directory in (
            self.fixture / "scripts",
            self.fixture / "bin",
            self.fixture / "src" / "fixmod",
            self.fixture / "tests",
            self.tools,
            self.home,
            self.tmpdir,
        ):
            directory.mkdir(parents=True)

        shutil.copyfile(CHECK_SCRIPT, self.fixture / "scripts" / "check.sh")
        os.chmod(self.fixture / "scripts" / "check.sh", 0o755)
        _write_exec(self.fixture / "bin" / "agent-platform", "#!/bin/sh\nexit 0\n")
        (self.fixture / "src" / "fixmod" / "__init__.py").write_text("VALUE = 1\n")
        (self.fixture / "tests" / "__init__.py").write_text("")
        (self.fixture / "tests" / "test_fixture.py").write_text(GOOD_TEST)
        (self.fixture / ".gitignore").write_text("__pycache__/\n*.pyc\n")

        os.symlink(sys.executable, self.tools / "python3")

    def add_shim(self, name: str, exit_code: int = 0, record: bool = False) -> None:
        lines = ["#!/bin/sh"]
        if record:
            lines.append("printf '%s\\n%s\\n' \"$PWD\" \"$*\" >> \"$SHIM_RECORD\"")
        lines.append("exit %d" % exit_code)
        _write_exec(self.tools / name, "\n".join(lines) + "\n")

    def run_check(
        self,
        extra_env: dict[str, str] | None = None,
        cwd: pathlib.Path | None = None,
        script: str = "scripts/check.sh",
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.pathsep.join([str(self.tools), "/usr/bin", "/bin"]),
            "HOME": str(self.home),
            "TMPDIR": str(self.tmpdir),
            "SHIM_RECORD": str(self.record),
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["/bin/sh", script],
            cwd=cwd or self.fixture,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def record_entries(self) -> list[tuple[str, str]]:
        lines = self.record.read_text().splitlines()
        return [(lines[i], lines[i + 1]) for i in range(0, len(lines), 2)]

    def assert_in_order(self, text: str, needles: list[str]) -> None:
        positions = []
        for needle in needles:
            self.assertIn(needle, text)
            positions.append(text.index(needle))
        self.assertEqual(positions, sorted(positions), text)

    def test_script_mode_and_shebang(self) -> None:
        self.assertEqual(CHECK_SCRIPT.stat().st_mode & 0o777, 0o755)
        self.assertEqual(CHECK_SCRIPT.read_text().splitlines()[0], "#!/bin/sh")

    def test_script_sh_n_passes(self) -> None:
        result = subprocess.run(["/bin/sh", "-n", str(CHECK_SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_real_shellcheck_accepts_repo_scripts(self) -> None:
        # The shims below cannot catch real shellcheck findings such as SC1007.
        for argv in (
            ["shellcheck", "--exclude=SC1007", "bin/agent-platform"],
            ["shellcheck", "scripts/check.sh"],
        ):
            result = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clean_fixture_passes(self) -> None:
        self.add_shim("gitleaks")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_in_order(
            result.stdout,
            ["==> unit tests", "==> shell syntax", INVENTORY_SKIP, "==> secret scan"],
        )

    def test_missing_pythonpath_would_fail(self) -> None:
        self.add_shim("gitleaks")
        shutil.rmtree(self.fixture / "src" / "fixmod")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unit tests", result.stderr)

    def test_failing_unit_test_stops_before_later_stages(self) -> None:
        self.add_shim("gitleaks")
        (self.fixture / "tests" / "test_fixture.py").write_text(FAILING_TEST)
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unit tests", result.stderr)
        self.assertNotIn("==> shell syntax", result.stdout)
        self.assertNotIn("==> secret scan", result.stdout)

    def test_same_size_edit_is_not_masked_by_stale_bytecode(self) -> None:
        self.add_shim("gitleaks")
        test_file = self.fixture / "tests" / "test_fixture.py"
        self.assertEqual(self.run_check().returncode, 0)
        stat = test_file.stat()
        test_file.write_text(GOOD_TEST.replace("VALUE, 1", "VALUE, 2"))
        os.utime(test_file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unit tests", result.stderr)

    def test_malformed_bin_agent_platform_fails(self) -> None:
        self.add_shim("gitleaks")
        with (self.fixture / "bin" / "agent-platform").open("a") as handle:
            handle.write("if then fi\n")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shell syntax", result.stderr)
        self.assertNotIn(INVENTORY_BANNER, result.stdout)
        self.assertNotIn("==> secret scan", result.stdout)

    def test_malformed_scripts_sh_fails(self) -> None:
        self.add_shim("gitleaks")
        (self.fixture / "scripts" / "broken.sh").write_text("if then\n")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shell syntax", result.stderr)
        self.assertNotIn("==> secret scan", result.stdout)

    def test_shellcheck_absent_skipped(self) -> None:
        self.add_shim("gitleaks")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("shellcheck not installed", result.stdout)

    def test_shellcheck_covers_wrapper_and_every_script(self) -> None:
        self.add_shim("gitleaks")
        self.add_shim("shellcheck", record=True)
        _write_exec(self.fixture / "scripts" / "alpha.sh", "#!/bin/sh\n:\n")
        _write_exec(self.fixture / "scripts" / "beta.sh", "#!/bin/sh\n:\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv_lines = [argv for _, argv in self.record_entries()]
        for suffix in ("bin/agent-platform", "scripts/alpha.sh", "scripts/beta.sh"):
            self.assertTrue(
                any(line.endswith(suffix) for line in argv_lines),
                "%s not checked: %r" % (suffix, argv_lines),
            )

    def test_shellcheck_failure_stops_before_secret_scan(self) -> None:
        self.add_shim("gitleaks")
        self.add_shim("shellcheck", exit_code=1)
        _write_exec(self.fixture / "scripts" / "sample.sh", "#!/bin/sh\n:\n")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shell syntax", result.stderr)
        self.assertNotIn("==> secret scan", result.stdout)

    def test_inventory_validator_absent_skipped(self) -> None:
        self.add_shim("gitleaks")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("scripts/check_inventories.py not present", result.stdout)

    def test_inventory_validator_present_and_passing_allows_secret_scan(self) -> None:
        self.add_shim("gitleaks")
        _write_exec(
            self.fixture / "scripts" / "check_inventories.py",
            "#!/usr/bin/env python3\nraise SystemExit(0)\n",
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_in_order(result.stdout, [INVENTORY_BANNER, "==> secret scan"])

    def test_inventory_validator_present_and_failing_stops(self) -> None:
        self.add_shim("gitleaks")
        _write_exec(
            self.fixture / "scripts" / "check_inventories.py",
            "#!/usr/bin/env python3\nraise SystemExit(2)\n",
        )
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inventory", result.stderr)
        self.assertNotIn("==> secret scan", result.stdout)

    def test_gitleaks_exact_args_and_cwd(self) -> None:
        self.add_shim("gitleaks", record=True)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entries = self.record_entries()
        self.assertEqual(len(entries), 1, entries)
        cwd, argv = entries[0]
        self.assertEqual(argv.rstrip(), "dir . --no-banner --redact --exit-code 1")
        self.assertEqual(cwd, str(self.fixture.resolve()))

    def test_gitleaks_failure_fails(self) -> None:
        self.add_shim("gitleaks", exit_code=1)
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("==> secret scan", result.stdout)
        self.assertIn("secret scan", result.stderr)

    def test_missing_gitleaks_without_opt_in_fails(self) -> None:
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gitleaks", result.stderr)
        self.assertIn("ALLOW_NO_GITLEAKS", result.stderr)

    def test_missing_gitleaks_with_opt_in_passes(self) -> None:
        result = self.run_check({"ALLOW_NO_GITLEAKS": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skipped by ALLOW_NO_GITLEAKS=1", result.stdout)

    def test_opt_in_does_not_suppress_installed_failure(self) -> None:
        self.add_shim("gitleaks", exit_code=1)
        result = self.run_check({"ALLOW_NO_GITLEAKS": "1"})
        self.assertNotEqual(result.returncode, 0)

    def test_runs_from_non_root_cwd(self) -> None:
        self.add_shim("gitleaks")
        result = self.run_check(
            cwd=self.fixture / "bin",
            script=str(self.fixture / "scripts" / "check.sh"),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
