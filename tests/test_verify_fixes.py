#!/usr/bin/env python3
"""Regression tests for verify.py: detection, compression, encoding, timeouts, --run.

Each test is written against a defect in the old implementation, so the suite
fails on the pre-fix script. Standard library only.

Run:  python tests/test_verify_fixes.py
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "skills" / "lean-context" / "scripts" / "verify.py"


def load_verify():
    spec = importlib.util.spec_from_file_location("verify_under_test", VERIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_cmd(directory: Path, name: str, body: list[str]) -> None:
    """Write a <name>.cmd shim so shutil.which() finds it on Windows."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (name + ".cmd")).write_text(
        "@echo off\r\n" + "\r\n".join(body) + "\r\n", encoding="utf-8"
    )


def python_shim(directory: Path, name: str, script: Path, *fixed_args: str) -> None:
    quoted = " ".join('"%s"' % item for item in (sys.executable, str(script)) + fixed_args)
    write_cmd(directory, name, [quoted + " %*", "exit /b %ERRORLEVEL%"])


def env_with_path(*directories: Path) -> dict:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(d) for d in directories] + [env.get("PATH", "")])
    env.pop("PYTHONIOENCODING", None)
    return env


def run_verify(root: Path, *args: str, env: dict = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(root)] + list(args),
        capture_output=True, timeout=timeout, env=env,
    )


def out_text(proc: subprocess.CompletedProcess, encoding: str = "utf-8") -> str:
    return proc.stdout.decode(encoding, errors="replace")


def err_text(proc: subprocess.CompletedProcess, encoding: str = "utf-8") -> str:
    return proc.stderr.decode(encoding, errors="replace")


class VerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-fixes-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def capture_main(self, verify, root: Path, *args: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", [str(VERIFY), "--root", str(root)] + list(args)), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = verify.main()
        return stdout.getvalue(), stderr.getvalue(), code

    # ------------------------------------------------------- npx local binaries
    def test_npx_local_bins_detect_eslint_and_tsc(self) -> None:
        repo = self.tmp / "npm-repo"
        write(repo / "package.json", '{"name": "demo", "scripts": {"test": "node -e 0"}}')
        write(repo / "node_modules" / ".bin" / "eslint.cmd", "echo eslint\n")
        write(repo / "node_modules" / ".bin" / "tsc.cmd", "echo tsc\n")
        verify = load_verify()
        which = lambda name: "C:/fake/npx" if name == "npx" else None
        with mock.patch.object(verify.shutil, "which", which), \
                mock.patch.object(importlib.util, "find_spec", lambda name: None):
            found = verify.detect(repo)
        self.assertEqual(["eslint", "tsc"], [label for _stage, _cmd, label in found])

    def test_dotfile_in_bin_does_not_detect_eslint(self) -> None:
        repo = self.tmp / "dotfile-repo"
        write(repo / "package.json", '{"name": "demo"}')
        write(repo / "node_modules" / ".bin" / ".dummy", "")
        verify = load_verify()
        which = lambda name: "C:/fake/npx" if name == "npx" else None
        with mock.patch.object(verify.shutil, "which", which), \
                mock.patch.object(importlib.util, "find_spec", lambda name: None):
            found = verify.detect(repo)
        # old code globbed like "." and found .dummy, inventing an eslint stage
        self.assertEqual([], found)

    # ------------------------------------------------------ python project detect
    def test_plain_python_project_with_tests_dir_detects_pytest(self) -> None:
        repo = self.tmp / "plain-python"
        write(repo / "tests" / "test_a.py", "def test_a():\n    assert True\n")
        bin_dir = self.tmp / "bin"
        write_cmd(bin_dir, "pytest", ["exit /b 0"])
        proc = run_verify(repo, "--dry-run", env=env_with_path(bin_dir))
        self.assertEqual(0, proc.returncode, err_text(proc))
        self.assertIn("pytest", out_text(proc))

    def test_root_test_file_marks_project_as_python(self) -> None:
        repo = self.tmp / "root-test-file"
        write(repo / "test_smoke.py", "def test_smoke():\n    pass\n")
        bin_dir = self.tmp / "bin2"
        write_cmd(bin_dir, "pytest", ["exit /b 0"])
        proc = run_verify(repo, "--dry-run", env=env_with_path(bin_dir))
        self.assertEqual(0, proc.returncode, err_text(proc))
        self.assertIn("pytest", out_text(proc))

    def test_python_m_fallback_when_tool_not_on_path(self) -> None:
        repo = self.tmp / "venv-project"
        write(repo / "pyproject.toml", "[project]\nname = 'demo'\n")
        module_dir = self.tmp / "fakemod"
        write(
            module_dir / "pytest.py",
            "import sys\nprint('AssertionError: fallback ran')\nsys.exit(1)\n",
        )
        empty_bin = self.tmp / "empty-bin"
        empty_bin.mkdir()
        env = dict(os.environ)
        env["PATH"] = str(empty_bin)  # no pytest/ruff/mypy reachable via PATH
        env["PYTHONPATH"] = str(module_dir)
        env.pop("PYTHONIOENCODING", None)
        proc = run_verify(repo, env=env)  # actually executes: the -m fallback
        self.assertEqual(1, proc.returncode, out_text(proc) + err_text(proc))
        self.assertIn("fallback ran", out_text(proc))

    def test_no_checker_message_differs_from_no_marker_message(self) -> None:
        verify = load_verify()
        marker_root = self.tmp / "has-markers"
        write(marker_root / "pyproject.toml", "[project]\nname = 'demo'\n")
        empty_root = self.tmp / "no-markers"
        empty_root.mkdir()
        with mock.patch.object(verify.shutil, "which", lambda name: None), \
                mock.patch.object(importlib.util, "find_spec", lambda name: None):
            _out, marker_msg, marker_code = self.capture_main(verify, marker_root, "--dry-run")
            _out, empty_msg, empty_code = self.capture_main(verify, empty_root, "--dry-run")
            _out, only_msg, only_code = self.capture_main(
                verify, marker_root, "--dry-run", "--only", "test"
            )
        self.assertEqual(2, marker_code)
        self.assertEqual(2, empty_code)
        self.assertEqual(2, only_code)
        self.assertNotEqual(marker_msg, empty_msg)
        self.assertIn("markers", marker_msg.lower())
        self.assertIn("installed", marker_msg)
        self.assertNotIn("No project markers", marker_msg)
        self.assertIn("No project markers", empty_msg)
        self.assertIn("test", only_msg)

    # ----------------------------------------------------------- .NET detection
    def test_csproj_inside_git_is_ignored(self) -> None:
        repo = self.tmp / "dotnet-repo"
        write(repo / ".git" / "deep" / "app.csproj", "<Project />")
        verify = load_verify()
        which = lambda name: "C:/fake/dotnet" if name == "dotnet" else None
        with mock.patch.object(verify.shutil, "which", which), \
                mock.patch.object(importlib.util, "find_spec", lambda name: None):
            found = verify.detect(repo)
        # old code did root.glob("**/*.csproj") and walked .git
        self.assertEqual([], found)
        write(repo / "app.csproj", "<Project />")
        with mock.patch.object(verify.shutil, "which", which), \
                mock.patch.object(importlib.util, "find_spec", lambda name: None):
            found = verify.detect(repo)
        self.assertEqual(["dotnet-test"], [label for _stage, _cmd, label in found])

    # ------------------------------------------------------------- compression
    def test_compress_strips_ansi_escapes(self) -> None:
        verify = load_verify()
        picked, total = verify.compress("\x1b[31mError: red\x1b[0m\n", 5)
        self.assertEqual(1, total)
        self.assertEqual(["Error: red"], picked)

    def test_compress_clips_long_lines(self) -> None:
        verify = load_verify()
        picked, total = verify.compress("Error: " + "x" * 10000 + "\nsecond Error: ok\n", 10)
        self.assertEqual(2, total)
        self.assertEqual(2, len(picked))
        self.assertGreater(len(picked[0]), 300)  # clipped to a 300-char budget
        self.assertLessEqual(len(picked[0]), 320)
        self.assertIn("\u2026 (+", picked[0])
        self.assertEqual("second Error: ok", picked[1])

    def test_max_lines_zero_returns_no_lines(self) -> None:
        verify = load_verify()
        output = "\n".join("error number %d" % i for i in range(30))
        picked, total = verify.compress(output, 0)
        # old code sliced [-0:], which returns everything
        self.assertEqual([], picked)
        self.assertEqual(30, total)

    def test_max_lines_zero_end_to_end(self) -> None:
        repo = self.tmp / "zero-repo"
        write(repo / "pyproject.toml", "[project]\nname = 'demo'\n")
        script = self.tmp / "many_errors.py"
        write(script, "import sys\nfor i in range(30):\n    print('error number %d' % i)\nsys.exit(1)\n")
        bin_dir = self.tmp / "zero-bin"
        python_shim(bin_dir, "pytest", script)
        proc = run_verify(repo, "--max-lines", "0", env=env_with_path(bin_dir))
        self.assertEqual(1, proc.returncode, out_text(proc))
        self.assertNotIn("error number", out_text(proc))

    # ----------------------------------------------------------------- encoding
    def test_utf8_child_output_survives(self) -> None:
        repo = self.tmp / "utf8-repo"
        write(repo / "pyproject.toml", "[project]\nname = 'demo'\n")
        script = self.tmp / "emit_utf8.py"
        write(
            script,
            "import sys\n"
            "sys.stdout.buffer.write('AssertionError: \\u5931\\u8d25\\n'.encode('utf-8'))\n"
            "sys.stdout.buffer.flush()\n"
            "sys.exit(1)\n",
        )
        bin_dir = self.tmp / "utf8-bin"
        python_shim(bin_dir, "pytest", script)
        env = env_with_path(bin_dir)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = run_verify(repo, "--json", env=env)
        self.assertEqual(1, proc.returncode, out_text(proc) + err_text(proc))
        text = proc.stdout.decode("utf-8", errors="replace")
        data = json.loads(text)
        lines = data[0]["lines"]
        self.assertTrue(any("\u5931\u8d25" in line for line in lines), lines)
        self.assertFalse(any("\u6f36\u8f89\u89e6" in line for line in lines), lines)

    def test_undecodable_child_output_does_not_crash_report(self) -> None:
        repo = self.tmp / "bad-bytes-repo"
        write(repo / "pyproject.toml", "[project]\nname = 'demo'\n")
        script = self.tmp / "emit_bad_bytes.py"
        write(
            script,
            "import sys\n"
            "sys.stdout.buffer.write(b'bad byte \\xff\\xfe here Error\\n')\n"
            "sys.stdout.buffer.flush()\n"
            "sys.exit(1)\n",
        )
        bin_dir = self.tmp / "bad-bytes-bin"
        python_shim(bin_dir, "pytest", script)
        # no PYTHONIOENCODING: the report itself must survive a cp936 stdout
        proc = run_verify(repo, env=env_with_path(bin_dir))
        self.assertEqual(1, proc.returncode, out_text(proc))
        self.assertNotIn("Traceback", err_text(proc))
        self.assertNotIn("UnicodeEncodeError", err_text(proc))

    # ------------------------------------------------------------------ timeouts
    def test_timeout_kills_process_tree(self) -> None:
        repo = self.tmp / "timeout-repo"
        write(repo / "pyproject.toml", "[project]\nname = 'demo'\n")
        marker = self.tmp / "grandchild-marker.txt"
        sleeper = self.tmp / "sleeper.py"
        write(
            sleeper,
            "import pathlib, sys, time\n"
            "time.sleep(4)\n"
            "pathlib.Path(sys.argv[1]).write_text('grandchild survived', encoding='utf-8')\n",
        )
        bin_dir = self.tmp / "timeout-bin"
        python_shim(bin_dir, "pytest", sleeper, str(marker))
        started = time.monotonic()
        proc = run_verify(repo, "--timeout", "2", env=env_with_path(bin_dir), timeout=30)
        elapsed = time.monotonic() - started
        self.assertEqual(1, proc.returncode, out_text(proc))
        self.assertIn("timeout after 2s", out_text(proc))
        self.assertLess(elapsed, 4, "timeout 2s but the call took %.2fs" % elapsed)
        time.sleep(2.2)  # the grandchild would write the marker at t=4s if it survived
        self.assertFalse(marker.exists(), "process tree survived the timeout")

    # -------------------------------------------------------------------- --run
    def test_run_flag_runs_and_compresses_command(self) -> None:
        script = self.tmp / "fail.py"
        write(script, "import sys\nfor i in range(30):\n    print('error number %d' % i)\nsys.exit(1)\n")
        command = '"%s" "%s"' % (sys.executable, script)
        proc = run_verify(self.tmp, "--run", command, "--max-lines", "3")
        out = out_text(proc)
        self.assertEqual(1, proc.returncode, out + err_text(proc))
        self.assertIn("30 problems, first 3:", out)
        self.assertEqual(3, sum(1 for line in out.splitlines() if "error number" in line))

    def test_run_flag_json_matches_normal_schema(self) -> None:
        script = self.tmp / "fail_json.py"
        write(script, "import sys\nfor i in range(30):\n    print('error number %d' % i)\nsys.exit(1)\n")
        command = '"%s" "%s"' % (sys.executable, script)
        proc = run_verify(self.tmp, "--json", "--run", command)
        self.assertEqual(1, proc.returncode, out_text(proc) + err_text(proc))
        data = json.loads(out_text(proc))
        self.assertEqual(1, len(data))
        item = data[0]
        self.assertEqual(
            {"stage", "label", "command", "exit", "error_count", "lines"}, set(item)
        )
        self.assertEqual("run", item["stage"])
        self.assertEqual("run", item["label"])
        self.assertEqual(" ".join([sys.executable, str(script)]), item["command"])
        self.assertEqual(1, item["exit"])
        self.assertEqual(30, item["error_count"])
        self.assertEqual(10, len(item["lines"]))
        self.assertNotIn("\x1b", "".join(item["lines"]))

    # -------------------------------------------------------------- --root check
    def test_missing_or_file_root_exits_2_with_clear_error(self) -> None:
        missing = self.tmp / "no-such-directory"
        proc = run_verify(missing)
        self.assertEqual(2, proc.returncode)
        self.assertIn("is not a directory", err_text(proc))
        self.assertNotIn("Traceback", err_text(proc))

        file_path = self.tmp / "not-a-dir.py"
        write(file_path, "x = 1\n")
        proc = run_verify(file_path)
        self.assertEqual(2, proc.returncode)
        self.assertIn("is not a directory", err_text(proc))
        self.assertNotIn("Traceback", err_text(proc))


if __name__ == "__main__":
    unittest.main(verbosity=2)
