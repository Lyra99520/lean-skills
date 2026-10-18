#!/usr/bin/env python3
"""Baseline self-tests for the bundled scripts and the skill structure.

Bug-specific regression tests live in test_atlas_fixes.py, test_verify_fixes.py
and test_measure_fixes.py; this file keeps the happy paths and the packaging
checks. Standard library only.

Run:  python tests/test_scripts.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATLAS = ROOT / "skills" / "lean-context" / "scripts" / "atlas.py"
VERIFY = ROOT / "skills" / "lean-context" / "scripts" / "verify.py"
MEASURE = ROOT / "skills" / "lean-stats" / "scripts" / "measure.py"
PY = sys.executable


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class AtlasCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lean-atlas-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_small_repo_gets_a_file_level_map(self) -> None:
        write(self.tmp / "app" / "service.py", '''
            """User service."""


            class UserService:
                pass
            ''')
        result = run(ATLAS, "--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.tmp / ".ai" / "atlas.md").read_text(encoding="utf-8")
        self.assertIn("file level", text)
        self.assertIn("UserService", text)

    def test_large_repo_degrades_to_directory_level(self) -> None:
        for index in range(160):
            write(self.tmp / "big" / f"m{index}.py", f'"""Module {index}."""\n\n\ndef fn_{index}():\n    pass\n')
        result = run(ATLAS, "--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.tmp / ".ai" / "atlas.md").read_text(encoding="utf-8")
        self.assertIn("dir level", text)
        self.assertIn("`big/` — 160 files", text)
        self.assertLess(len(text.splitlines()), 40)

    def test_stats_prints_counts(self) -> None:
        for index in range(3):
            write(self.tmp / "pkg" / f"m{index}.py", '"""M."""\n')
        result = run(ATLAS, "--root", str(self.tmp), "--stats")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pkg", result.stdout)
        self.assertIn("3  total", result.stdout)

    def test_missing_root_exits_two(self) -> None:
        result = run(ATLAS, "--root", str(self.tmp / "nope"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a directory", result.stderr)


class VerifyCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lean-verify-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_markers_exits_two(self) -> None:
        result = run(VERIFY, "--root", str(self.tmp), "--dry-run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("No project markers", result.stderr)

    @unittest.skipUnless(shutil.which("npm"), "npm not installed")
    def test_detects_test_stage(self) -> None:
        write(self.tmp / "package.json", '{"name":"demo","scripts":{"test":"node -e 0"}}')
        result = run(VERIFY, "--root", str(self.tmp), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("npm-test", result.stdout)

    def test_run_compresses_an_arbitrary_command(self) -> None:
        script = self.tmp / "fail.py"
        write(script, '''
            print("setup ok")
            print("Error: the one line that matters")
            print("noise " * 50)
            raise SystemExit(1)
            ''')
        command = f'"{PY}" "{script}"'
        result = run(VERIFY, "--root", str(self.tmp), "--run", command, "--max-lines", "1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Error: the one line that matters", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


class MeasureCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lean-measure-"))
        for index in range(20):
            write(self.tmp / "src" / f"m{index}.py", f'"""Mod {index}."""\n' + "x = 1\n" * 60)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_requires_atlas(self) -> None:
        result = run(MEASURE, "--root", str(self.tmp))
        self.assertEqual(result.returncode, 1)
        self.assertIn("atlas.py", result.stdout + result.stderr)

    def test_json_report_reports_net_and_sensitivity(self) -> None:
        self.assertEqual(run(ATLAS, "--root", str(self.tmp)).returncode, 0)
        result = run(MEASURE, "--root", str(self.tmp), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["files"], 20)
        self.assertGreater(data["source_tokens"], 0)
        self.assertGreater(data["atlas_tokens"], 0)
        self.assertLess(data["atlas_tokens"], data["source_tokens"])
        self.assertIn("breakeven_tasks", data)
        self.assertIn("net_first_task", data)
        self.assertIn("sensitivity", data)


class StructureTests(unittest.TestCase):
    def test_manifests_validate(self) -> None:
        result = subprocess.run([PY, str(ROOT / "tests" / "validate_manifests.py")],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_skill_frontmatter_and_size(self) -> None:
        skills_dir = ROOT / "skills"
        names = sorted(path.name for path in skills_dir.iterdir() if path.is_dir())
        self.assertGreaterEqual(len(names), 4)
        for name in names:
            path = skills_dir / name / "SKILL.md"
            self.assertTrue(path.exists(), f"{name} has no SKILL.md")
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"{name} has no frontmatter")
            head = text.split("---", 2)[1]
            self.assertIn("name:", head)
            self.assertIn("description:", head)
            self.assertIn(f"name: {name}", head)
            self.assertLess(len(text.splitlines()), 120, f"{name} SKILL.md is too long")

    def test_skill_commands_use_plugin_paths(self) -> None:
        for path in (ROOT / "skills").glob("*/SKILL.md"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("python scripts/", text, f"{path} uses a CWD-relative script path")
            self.assertNotIn('"**Does**"', text)

    def test_skill_files_do_not_duplicate_the_description(self) -> None:
        # 0.2.0 removed the Does/Used when/Improves trio: the frontmatter
        # description already carries that text into every session.
        for path in (ROOT / "skills").glob("*/SKILL.md"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("**Does** —", text, path)
            self.assertNotIn("**Used when** —", text, path)
            self.assertNotIn("**Improves** —", text, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
