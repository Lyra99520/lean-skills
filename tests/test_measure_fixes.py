#!/usr/bin/env python3
"""Regression tests for the honest measure.py model. Standard library only.

Covers the fixes requested for measure.py: one source of truth for file
selection (atlas.py), a net-of-skill-overhead cost model, the sensitivity table,
argument validation, truncation warnings, and exit code 1 on a missing map.

Run:  python tests/test_measure_fixes.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATLAS = ROOT / "skills" / "lean-context" / "scripts" / "atlas.py"
MEASURE = ROOT / "skills" / "lean-stats" / "scripts" / "measure.py"


def run(script: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *[str(item) for item in args]],
        capture_output=True, text=True, timeout=180,
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class MeasureFixesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def seed_repo(self, count: int = 12, repeats: int = 40) -> None:
        for index in range(count):
            write(self.tmp / "src" / f"m{index}.py",
                  f'"""Module {index}."""\n' + "x = 1\n" * repeats)

    def build_atlas(self, root: Path = None) -> None:
        target = root or self.tmp
        result = run(ATLAS, "--root", target)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def measure_json(self, *extra) -> tuple:
        result = run(MEASURE, "--root", self.tmp, "--json", *extra)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout), result

    def test_json_exposes_net_sensitivity_and_always_on(self) -> None:
        self.seed_repo()
        self.build_atlas()
        data, result = self.measure_json()

        self.assertEqual(data["files"], 12)
        for key in ("net", "net_first_task", "sensitivity", "always_on",
                    "triggered_tokens", "gross_saving", "saving_per_task"):
            self.assertIn(key, data)
        self.assertGreater(data["always_on"], 0, "SKILL.md descriptions must be measured")
        self.assertGreater(data["triggered_tokens"], 0, "triggered bodies must be measured")
        self.assertGreater(data["gross_saving"], 0)

        rereads = [row["rereads"] for row in data["sensitivity"]]
        self.assertEqual(rereads, [0, 1, 2, 5])
        for row in data["sensitivity"]:
            self.assertIn("saving", row)
            self.assertIn("saving_pct", row)
            self.assertIn("negative", row)

        self.assertEqual(data["assumptions"]["triggered"], ["lean-dev", "lean-context"])
        self.assertEqual(
            data["net"],
            data["gross_saving"] - data["always_on"] - data["triggered_tokens"],
        )

    def test_missing_atlas_exits_one_in_all_modes(self) -> None:
        self.seed_repo()
        for mode in ([], ["--json"], ["--markdown"]):
            result = run(MEASURE, "--root", self.tmp, *mode)
            self.assertEqual(
                result.returncode, 1,
                f"mode={mode} stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            combined = result.stdout + result.stderr
            self.assertIn("atlas.py", combined)
            self.assertIn("map", combined.lower())

        # A missing map is an error in every mode even before "no source files":
        # an empty fixture must still exit 1, not 2 with no hint.
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(empty, ignore_errors=True))
        for mode in ([], ["--json"], ["--markdown"]):
            result = run(MEASURE, "--root", empty, *mode)
            self.assertEqual(result.returncode, 1, f"empty tree mode={mode}")

    def test_zero_or_negative_assumptions_are_rejected(self) -> None:
        self.seed_repo()
        self.build_atlas()
        for args in (
            ("--assume-files", "0"),
            ("--assume-files", "-2"),
            ("--assume-reread", "-1"),
        ):
            result = run(MEASURE, "--root", self.tmp, *args)
            self.assertEqual(result.returncode, 2, f"{args}: {result.stderr!r}")
            self.assertIn("must be", result.stderr)

    def test_file_count_matches_atlas_cache(self) -> None:
        self.seed_repo(count=5)
        write(self.tmp / "node_modules" / "skipped.py", '"""Vendored."""\n')
        write(self.tmp / "generated" / "skipped.py", '"""Generated."""\n')
        write(self.tmp / "README.md", "# not source\n")
        write(self.tmp / ".gitignore", "generated/\n")
        self.build_atlas()

        cache = json.loads((self.tmp / ".ai" / "atlas.json").read_text(encoding="utf-8"))
        data, _ = self.measure_json()
        self.assertEqual(len(cache["files"]), 5)
        self.assertEqual(data["files"], len(cache["files"]))

    def test_truncation_notice_warns(self) -> None:
        self.seed_repo(count=4)
        self.build_atlas()
        atlas_md = self.tmp / ".ai" / "atlas.md"
        atlas_md.write_text(
            atlas_md.read_text(encoding="utf-8")
            + "\n> 9 directories not shown, raise --max-lines or use --dir <path>.\n",
            encoding="utf-8",
        )

        human = run(MEASURE, "--root", self.tmp)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("incomplete", human.stdout.lower())

        data, machine = self.measure_json()
        self.assertTrue(data["atlas_incomplete"])
        self.assertIn("incomplete", machine.stderr.lower())

    def test_breakeven_never_on_tiny_repo(self) -> None:
        write(self.tmp / "tiny.py", "x = 1\n")
        self.build_atlas()

        human = run(MEASURE, "--root", self.tmp)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("never", human.stdout.lower())
        self.assertNotIn("task None", human.stdout)
        self.assertIn("negative", human.stdout.lower())

        data, _ = self.measure_json()
        self.assertIsNone(data["breakeven_tasks"])
        self.assertIsNone(data["breakeven_map_only_tasks"])
        self.assertTrue(all(row["negative"] for row in data["sensitivity"]))

    def test_triggered_selects_skill_bodies(self) -> None:
        self.seed_repo(count=6)
        self.build_atlas()
        default, _ = self.measure_json()
        single, _ = self.measure_json("--triggered", "lean-context")

        self.assertEqual(default["assumptions"]["triggered"],
                         ["lean-dev", "lean-context"])
        self.assertEqual(single["assumptions"]["triggered"], ["lean-context"])
        self.assertGreater(default["triggered_tokens"], single["triggered_tokens"])
        self.assertGreater(single["triggered_tokens"], 0)
        self.assertEqual(
            single["net"],
            single["gross_saving"] - single["always_on"] - single["triggered_tokens"],
        )

    def test_sensitivity_table_math_matches_report(self) -> None:
        self.seed_repo()
        self.build_atlas()
        data, _ = self.measure_json()

        human = run(MEASURE, "--root", self.tmp)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("sensitivity to --assume-reread", human.stdout)
        table_rows = [line for line in human.stdout.splitlines()
                      if re.match(r"^\s+\d+\s+~", line)]
        self.assertEqual(len(table_rows), 4)

        avg = data["avg_file_tokens"]
        atlas_tokens = data["atlas_tokens"]
        files_per_task = data["assumptions"]["files_per_task"]
        for row in data["sensitivity"]:
            expected = avg * (files_per_task + row["rereads"]) - (
                atlas_tokens + avg * files_per_task)
            self.assertEqual(row["saving"], expected)

    def test_standalone_copy_warns_about_fallback(self) -> None:
        self.seed_repo(count=5)
        self.build_atlas()
        standalone = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(standalone, ignore_errors=True))
        copy = standalone / "measure.py"
        shutil.copyfile(MEASURE, copy)

        fallback = run(copy, "--root", self.tmp, "--json")
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        self.assertIn("fallback", fallback.stderr.lower())
        data = json.loads(fallback.stdout)
        self.assertEqual(data["files"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
