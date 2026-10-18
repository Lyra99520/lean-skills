#!/usr/bin/env python3
"""verify.py - run a project's own checks and return only the useful part.

Why it exists:
    Test and lint output is the largest uncontrolled blob in most sessions. A
    single failing run can be a thousand lines, of which two matter. This script
    runs the gates the project already has and returns the first error, a count,
    and a verdict.

Usage:
    python verify.py --root .              # lint, then types, then tests
    python verify.py --root . --only lint
    python verify.py --root . --dry-run    # print the commands it would run
    python verify.py --root . --max-lines 8 --timeout 300
    python verify.py --root . --run "pytest tests/test_x.py -x"

Exit codes: 0 all passed / 1 something failed / 2 no checks detected or bad --root
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ERROR_HINTS = re.compile(
    r"(error|Error|ERROR|FAIL|fail|✗|✖|×|Traceback|AssertionError|"
    r"undefined|Unused|unused|expected|Expected|E\d{3,4}|TS\d{4})"
)

NOISE_HINTS = re.compile(
    r"(^\s*$|^>|^npm |^yarn |^pnpm |^Downloading|^Collecting|"
    r"^Installing|^\s+at\s+|^%\s|^✓|^PASSED|^\.+$)"
)

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MAX_LINE = 300

COMMAND_SETS = {
    "lint": [
        (["ruff", "check", "."], "ruff"),
        (["npx", "--no-install", "eslint", ".", "-f", "compact"], "eslint"),
        (["go", "vet", "./..."], "go-vet"),
        (["cargo", "clippy", "--quiet", "--", "-D", "warnings"], "clippy"),
    ],
    "type": [
        (["mypy", ".", "--no-error-summary", "--pretty=false"], "mypy"),
        (["npx", "--no-install", "tsc", "--noEmit"], "tsc"),
        (["cargo", "check", "--quiet"], "cargo-check"),
    ],
    "test": [
        (["pytest", "-q", "--maxfail=1", "-p", "no:cacheprovider"], "pytest"),
        (["npm", "test", "--silent"], "npm-test"),
        (["go", "test", "./...", "-count=1"], "go-test"),
        (["cargo", "test", "--quiet"], "cargo-test"),
        (["dotnet", "test", "--nologo", "-v", "q"], "dotnet-test"),
    ],
}

PY_MARKERS = {"pyproject.toml", "setup.py", "requirements.txt", "pytest.ini", "tox.ini", "setup.cfg"}
MODULE_FALLBACK = {"pytest", "ruff", "mypy"}
BIN_SUFFIXES = ("", ".cmd", ".exe", ".ps1")


def which_first(cmd: list[str], root: Path) -> str | None:
    exe = cmd[0]
    if exe == "npx":
        # argv is ["npx", "--no-install", <tool>, ...]: the tool is cmd[2], not cmd[3]
        tool = cmd[2] if len(cmd) > 2 else ""
        local_bin = root / "node_modules" / ".bin"
        # exact names only: a dotfile in .bin must not fake an installed tool
        installed = tool and any((local_bin / (tool + suffix)).exists() for suffix in BIN_SUFFIXES)
        if not installed:
            return None
        return shutil.which("npx")
    return shutil.which(exe)


def resolve(cmd: list[str]) -> list[str] | None:
    """Return an executable argv for cmd, or None when nothing is installed."""
    if shutil.which(cmd[0]):
        return cmd
    # venv/uv/poetry projects often have the tool importable but not on PATH
    if cmd[0] in MODULE_FALLBACK and importlib.util.find_spec(cmd[0]) is not None:
        return [sys.executable, "-m", cmd[0]] + cmd[1:]
    return None


def detect(root: Path) -> list[tuple[str, list[str], str]]:
    markers = {p.name for p in root.iterdir()} if root.is_dir() else set()
    has_npm = "package.json" in markers
    has_py = bool(markers & PY_MARKERS) or (root / "tests").is_dir() or any(root.glob("test_*.py"))
    has_go = "go.mod" in markers
    has_rs = "Cargo.toml" in markers
    # root-only probes: a recursive **/*.csproj walk would read .git/node_modules on every run
    has_cs = "global.json" in markers or any(root.glob("*.sln")) or any(root.glob("*.csproj"))

    found: list[tuple[str, list[str], str]] = []
    for stage in ("lint", "type", "test"):
        for cmd, label in COMMAND_SETS[stage]:
            if label.startswith(("eslint", "tsc", "npm")) and not has_npm:
                continue
            if label in {"ruff", "mypy", "pytest"} and not has_py:
                continue
            if label.startswith("go") and not has_go:
                continue
            if label.startswith(("clippy", "cargo")) and not has_rs:
                continue
            if label.startswith("dotnet") and not has_cs:
                continue
            if cmd[0] == "npx":
                if not which_first(cmd, root):
                    continue
                resolved = cmd
            else:
                resolved = resolve(cmd)
                if resolved is None:
                    continue
            found.append((stage, resolved, label))
            break
    return found


def markers_present(root: Path) -> bool:
    """True when the root looks like a project, even if no checker is installed."""
    markers = {p.name for p in root.iterdir()} if root.is_dir() else set()
    if markers & (PY_MARKERS | {"package.json", "go.mod", "Cargo.toml", "global.json"}):
        return True
    return (
        (root / "tests").is_dir()
        or any(root.glob("test_*.py"))
        or any(root.glob("*.sln"))
        or any(root.glob("*.csproj"))
    )


def _clip(line: str) -> str:
    if len(line) <= MAX_LINE:
        return line
    return line[:MAX_LINE] + f"… (+{len(line) - MAX_LINE} chars)"


def compress(output: str, max_lines: int) -> tuple[list[str], int]:
    raw = [ANSI.sub("", ln).rstrip() for ln in output.splitlines()]
    hits = [ln for ln in raw if ERROR_HINTS.search(ln) and not NOISE_HINTS.search(ln)]
    total = len(hits)
    if max_lines <= 0:
        return [], total
    picked = hits[:max_lines]
    if not picked:
        picked = [ln for ln in raw if ln.strip() and not NOISE_HINTS.search(ln)][-max_lines:]
    return [_clip(ln) for ln in picked], total


def split_command(text: str) -> list[str]:
    """shlex-split a --run string; Windows shlex keeps backslashes, so strip outer quotes."""
    argv = shlex.split(text, posix=(os.name != "nt"))
    if os.name == "nt":
        argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in ('"', "'") else a for a in argv]
    return argv


def _new_job():
    """Windows job that kills its tree when closed: taskkill can be denied by policy."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("per_process_us", ctypes.c_int64), ("per_job_us", ctypes.c_int64),
            ("limit_flags", ctypes.c_uint32),
            ("min_working_set", ctypes.c_size_t), ("max_working_set", ctypes.c_size_t),
            ("active_processes", ctypes.c_uint32), ("affinity", ctypes.c_size_t),
            ("priority_class", ctypes.c_uint32), ("scheduling_class", ctypes.c_uint32),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", _BasicLimits), ("io", _IoCounters),
            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _ExtendedLimits()
    info.basic.limit_flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)  # 9 = JobObjectExtendedLimitInformation
    ):
        kernel32.CloseHandle(job)
        return None
    return kernel32, job


def _assign_job(job, proc: subprocess.Popen) -> bool:
    return bool(job is not None and job[0].AssignProcessToJobObject(job[1], int(proc._handle)))


def _close_job(job) -> None:
    if job is not None:
        job[0].CloseHandle(job[1])


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child and its descendants: a plain kill leaves grandchildren running."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        pass
    if proc.poll() is None:
        proc.kill()


def run(cmd: list[str], root: Path, timeout: int) -> tuple[int, str]:
    argv = list(resolve(cmd) or cmd)
    exe = shutil.which(argv[0]) or argv[0]
    if exe.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", exe] + argv[1:]
    else:
        argv[0] = exe
    kwargs = {} if os.name == "nt" else {"start_new_session": True}
    job = _new_job() if os.name == "nt" else None
    try:
        proc = subprocess.Popen(
            argv, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
        )
    except OSError as exc:
        _close_job(job)
        return 127, str(exc)
    if not _assign_job(job, proc):
        _close_job(job)
        job = None
    try:
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        _close_job(job)  # job kill-on-close takes the whole tree if taskkill was denied
        job = None
        out, err = proc.communicate()
        code = 124
        err = (err or b"") + b"timeout after " + str(timeout).encode() + b"s\n"
    _close_job(job)  # nothing outlives a check: the job also reaps stray daemons
    # tools emit UTF-8 (or nothing sane): decode it as UTF-8, never as the locale
    text = ((out or b"") + (err or b"")).decode("utf-8", errors="replace")
    return code, text


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # non-GBK paths/text must not crash the report

    parser = argparse.ArgumentParser(description="Run project checks, compressed")
    parser.add_argument("--root", default=".")
    parser.add_argument("--only", choices=["lint", "type", "test"], default=None)
    parser.add_argument("--max-lines", type=int, default=10, help="error lines returned per command")
    parser.add_argument("--timeout", type=int, default=300, help="per-command timeout in seconds")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--run", default=None,
        help='run one command and compress it, e.g. --run "pytest tests/test_x.py -x"',
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    results = []
    if args.run:
        argv = split_command(args.run)
        if not argv:
            print("error: --run command is empty", file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"run   {' '.join(argv)}")
            return 0
        code, output = run(argv, root, args.timeout)
        lines, total = compress(output, args.max_lines)
        results.append({
            "stage": "run", "label": "run", "command": " ".join(argv),
            "exit": code, "error_count": total, "lines": lines,
        })
    else:
        commands = detect(root)
        if args.only:
            commands = [c for c in commands if c[0] == args.only]

        if not commands:
            stage = f"{args.only} " if args.only else ""
            if markers_present(root):
                print(
                    f"Project markers found, but no installed {stage}checkers were detected "
                    "(ruff/eslint/mypy/tsc/pytest/npm/go/cargo/dotnet).",
                    file=sys.stderr,
                )
            else:
                print(
                    "No project markers found (package.json, pyproject.toml, go.mod, Cargo.toml).",
                    file=sys.stderr,
                )
            return 2

        if args.dry_run:
            for stage, cmd, label in commands:
                print(f"{stage:5s} {label:12s} {' '.join(cmd)}")
            return 0

        for stage, cmd, label in commands:
            code, output = run(cmd, root, args.timeout)
            lines, total = compress(output, args.max_lines)
            results.append({
                "stage": stage, "label": label, "command": " ".join(cmd),
                "exit": code, "error_count": total, "lines": lines,
            })

    failed = sum(1 for item in results if item["exit"] != 0)

    if args.json:
        # ensure_ascii: a downstream console/locale can never fail to encode the report
        print(json.dumps(results, ensure_ascii=True, indent=1))
        return 1 if failed else 0

    for item in results:
        status = "PASS" if item["exit"] == 0 else "FAIL"
        print(f"[{item['stage']}] {item['label']} -> {status} (exit {item['exit']})")
        if item["exit"] != 0:
            if item["error_count"]:
                print(f"  {item['error_count']} problems, first {len(item['lines'])}:")
            for line in item["lines"]:
                print(f"  {line}")
        print()

    print(f"Result: {len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
