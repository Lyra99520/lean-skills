#!/usr/bin/env python3
"""Regression tests for the defects fixed in atlas.py for 0.2.0.

Each class maps to a defect id from the review:
    A5  map truncation / tiering on the real file count
    A4  --check misses modified files
    A2  --since writes a partial map when there is no cache
    A3  --since with a failing git diff wrote an empty map
    A11 --dir prefix matching and the root bucket
    A12 traversal, .gitignore, binary files
    A13 corrupt cache
    A14 --out-dir escaping the repository
    A15 rename/quoting parsing and skip-dir filtering
    A18 --max-files 0
    A6  Python 3.9 write path
    new --find returns path:line
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
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


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ATLAS), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=180)


def load_atlas():
    spec = importlib.util.spec_from_file_location("atlas_under_test", str(ATLAS))
    module = importlib.util.module_from_spec(spec)
    sys.modules["atlas_under_test"] = module
    spec.loader.exec_module(module)
    return module


def run_main(module, *args: str) -> tuple[int, str, str]:
    old_argv = sys.argv
    out, err = io.StringIO(), io.StringIO()
    sys.argv = ["atlas.py", *args]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main()
    finally:
        sys.argv = old_argv
    return code, out.getvalue(), err.getvalue()


class AtlasCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def map_text(self, root: Path) -> str:
        return (root / ".ai" / "atlas.md").read_text(encoding="utf-8")

    def cache(self, root: Path) -> dict:
        payload = json.loads((root / ".ai" / "atlas.json").read_text(encoding="utf-8"))
        return payload["files"]


class MapCompletenessTests(AtlasCase):
    def test_file_level_map_keeps_purpose_and_symbols(self) -> None:
        write(self.tmp / "app" / "service.py", '''
            """User service: joins profiles and orders."""


            class UserService:
                def get(self, uid):
                    return None
            ''')
        result = run("--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.map_text(self.tmp)
        self.assertIn("file level", text)
        self.assertIn("User service: joins profiles and orders", text)
        self.assertIn("UserService", text)
        self.assertNotIn("service.py - User service", text)

    def test_directory_level_lists_every_directory(self) -> None:
        for directory in "abcde":
            for index in range(100):
                write(self.tmp / directory / f"m{index:03d}.py", '"""M."""\n\n\ndef f():\n    pass\n')
        result = run("--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.map_text(self.tmp)
        self.assertIn("dir level", text)
        for directory in "abcde":
            self.assertIn(f"`{directory}/`", text)
        self.assertEqual(text.count("100 files"), 5, text)
        self.assertIn("500 files", text)

    def test_directory_counts_are_not_truncated(self) -> None:
        # A5: b/ had 100 files but the old truncation reported 49.
        for index in range(350):
            write(self.tmp / "a" / f"m{index:03d}.py", '"""M."""\n')
        for index in range(100):
            write(self.tmp / "b" / f"m{index:03d}.py", '"""M."""\n')
        run("--root", str(self.tmp), "--level", "dir")
        text = self.map_text(self.tmp)
        self.assertIn("`a/` — 350 files", text)
        self.assertIn("`b/` — 100 files", text)
        self.assertIn("450 files", text)

    def test_tier_uses_the_real_file_count(self) -> None:
        for index in range(510):
            write(self.tmp / "big" / f"m{index:03d}.py", '"""M."""\n')
        result = run("--root", str(self.tmp), "--max-files", "100")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.map_text(self.tmp)
        self.assertIn("dir level", text, text)
        self.assertIn("510 files", text)

    def test_max_lines_caps_directory_lines_and_says_so(self) -> None:
        for directory in "abcd":
            for index in range(50):
                write(self.tmp / directory / f"m{index:03d}.py", '"""M."""\n')
        run("--root", str(self.tmp), "--max-lines", "2")
        text = self.map_text(self.tmp)
        self.assertIn("2 directories not shown", text, text)

    def test_empty_repository_builds_and_checks_clean(self) -> None:
        result = run("--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 files", self.map_text(self.tmp))
        self.assertEqual(run("--root", str(self.tmp), "--check").returncode, 0)


class FindTests(AtlasCase):
    def setUp(self) -> None:
        super().setUp()
        write(self.tmp / "app" / "service.py", '''
            """Service."""


            class UserService:
                def get(self, uid):
                    return None
            ''')
        write(self.tmp / "app" / "models.py", '"""Models."""\n\n\nclass User:\n    pass\n')
        self.assertEqual(run("--root", str(self.tmp)).returncode, 0)

    def test_find_returns_path_line_and_name(self) -> None:
        result = run("--root", str(self.tmp), "--find", "userservice")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("app/service.py:5", result.stdout)
        self.assertIn("UserService", result.stdout)

    def test_find_is_case_insensitive(self) -> None:
        self.assertEqual(run("--root", str(self.tmp), "--find", "USERSERVICE").returncode, 0)

    def test_find_without_cache_fails_clearly(self) -> None:
        empty = self.tmp / "nocache"
        empty.mkdir()
        result = run("--root", str(empty), "--find", "anything")
        self.assertEqual(result.returncode, 2)
        self.assertIn("atlas cache", result.stderr)


class StalenessTests(AtlasCase):
    def setUp(self) -> None:
        super().setUp()
        write(self.tmp / "app" / "svc.py", '"""Service."""\n\n\ndef old_name():\n    pass\n')

    def test_missing_map_is_stale(self) -> None:
        self.assertEqual(run("--root", str(self.tmp), "--check").returncode, 1)

    def test_fresh_map_is_current(self) -> None:
        run("--root", str(self.tmp))
        result = run("--root", str(self.tmp), "--check")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("OK", result.stdout)

    def test_modified_content_is_stale(self) -> None:
        run("--root", str(self.tmp))
        write(self.tmp / "app" / "svc.py", '"""Service."""\n\n\ndef brand_new_name():\n    pass\n')
        result = run("--root", str(self.tmp), "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("modified", result.stdout)
        self.assertIn("svc.py", result.stdout)

    def test_removed_file_is_stale(self) -> None:
        run("--root", str(self.tmp))
        (self.tmp / "app" / "svc.py").unlink()
        result = run("--root", str(self.tmp), "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("removed", result.stdout)

    def test_corrupt_cache_is_reported_not_raised(self) -> None:
        run("--root", str(self.tmp))
        (self.tmp / ".ai" / "atlas.json").write_text("{broken", encoding="utf-8")
        result = run("--root", str(self.tmp), "--check")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("STALE", result.stdout)


class IncrementalTests(AtlasCase):
    def test_since_without_cache_does_a_full_scan(self) -> None:
        # A2: the old code wrote a one-file map as if it were the whole repo.
        write(self.tmp / "keep.py", '"""Keep."""\n\n\ndef keep():\n    pass\n')
        write(self.tmp / "changed.py", '"""Changed."""\n\n\ndef changed():\n    pass\n')
        module = load_atlas()
        original = module.git_changed
        module.git_changed = lambda root, since: {"changed.py"}
        try:
            code, stdout, stderr = run_main(module, "--root", str(self.tmp), "--since", "HEAD~1")
        finally:
            module.git_changed = original
        self.assertEqual(code, 0, stderr)
        self.assertEqual(set(self.cache(self.tmp)), {"keep.py", "changed.py"}, stdout)

    def test_since_without_git_falls_back_to_full_scan(self) -> None:
        write(self.tmp / "a.py", '"""A."""\n')
        write(self.tmp / "b.py", '"""B."""\n')
        result = run("--root", str(self.tmp), "--since", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(self.cache(self.tmp)), {"a.py", "b.py"})

    def test_since_skips_paths_the_full_scan_would_ignore(self) -> None:
        # A15: a git-reported path inside node_modules must not enter the map.
        write(self.tmp / "app.py", '"""A."""\n')
        write(self.tmp / "node_modules" / "pkg" / "x.js", "const a = 1;\n")
        run("--root", str(self.tmp))
        module = load_atlas()
        original = module.git_changed
        module.git_changed = lambda root, since: {"node_modules/pkg/x.js"}
        try:
            code, _, stderr = run_main(module, "--root", str(self.tmp), "--since", "HEAD~1")
        finally:
            module.git_changed = original
        self.assertEqual(code, 0, stderr)
        self.assertEqual(set(self.cache(self.tmp)), {"app.py"})

    def test_rename_parsing_keeps_both_sides(self) -> None:
        module = load_atlas()
        self.assertEqual(module.normalise_path(' "caf\\303\\251.py" '), "caf/303/251.py")
        # A rename line is split on the arrow, not turned into one bogus path.
        self.assertIn(" -> ", "R  a.py -> c.py")


class ExpandTests(AtlasCase):
    def setUp(self) -> None:
        super().setUp()
        for directory in ("src/api", "src/api_v2"):
            for index in range(80):
                write(self.tmp / directory / f"f{index}.py", '"""M."""\n\n\ndef g():\n    pass\n')
        write(self.tmp / "main.py", '"""Entry."""\n\n\ndef main():\n    pass\n')
        self.assertEqual(run("--root", str(self.tmp)).returncode, 0)

    def test_expand_matches_exactly(self) -> None:
        run("--root", str(self.tmp), "--dir", "src/api")
        text = self.map_text(self.tmp)
        self.assertIn("## src/api", text)
        self.assertNotIn("## src/api_v2", text)

    def test_expand_root_bucket(self) -> None:
        run("--root", str(self.tmp), "--dir", ".")
        self.assertIn("## (root)", self.map_text(self.tmp))

    def test_expand_backslash_path(self) -> None:
        run("--root", str(self.tmp), "--dir", "src\\api")
        self.assertIn("## src/api", self.map_text(self.tmp))


class TraversalTests(AtlasCase):
    def test_binary_files_are_skipped(self) -> None:
        write(self.tmp / "good.py", '"""Good."""\n')
        (self.tmp / "blob.py").write_bytes(b"\x00\x01\x02binary")
        run("--root", str(self.tmp))
        text = self.map_text(self.tmp)
        self.assertIn("good.py", text)
        self.assertNotIn("blob.py", text)

    def test_gitignore_is_respected(self) -> None:
        write(self.tmp / "good.py", '"""Good."""\n')
        (self.tmp / ".gitignore").write_text("generated/\n", encoding="utf-8")
        write(self.tmp / "generated" / "gen.py", '"""Gen."""\n')
        run("--root", str(self.tmp))
        text = self.map_text(self.tmp)
        self.assertIn("good.py", text)
        self.assertNotIn("generated", text)

    def test_skipped_directories_are_not_walked(self) -> None:
        write(self.tmp / "src" / "a.py", '"""A."""\n')
        write(self.tmp / "node_modules" / "pkg" / "y.js", "const a = 1;\n")
        module = load_atlas()
        found = {path.relative_to(self.tmp).as_posix() for path in module.iter_source_files(self.tmp)}
        self.assertEqual(found, {"src/a.py"})


class GuardTests(AtlasCase):
    def test_out_dir_outside_root_is_rejected(self) -> None:
        write(self.tmp / "a.py", '"""A."""\n')
        result = run("--root", str(self.tmp), "--out-dir", "../escape")
        self.assertEqual(result.returncode, 2)
        self.assertIn("inside", result.stderr)

    def test_missing_root_is_rejected(self) -> None:
        result = run("--root", str(self.tmp / "nope"))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_max_lines_zero_is_a_usage_error(self) -> None:
        result = run("--root", str(self.tmp), "--max-lines", "0")
        self.assertEqual(result.returncode, 2)

    def test_writes_without_python310_only_apis(self) -> None:
        # A6: Path.write_text(..., newline=...) is 3.10+. The fix must not use it.
        original = Path.write_text

        def write_text_39(self, data, encoding=None, errors=None):  # 3.9 signature
            return original(self, data, encoding, errors)

        write(self.tmp / "a.py", '"""A."""\n')
        module = load_atlas()
        Path.write_text = write_text_39
        try:
            code, _, stderr = run_main(module, "--root", str(self.tmp))
        finally:
            Path.write_text = original
        self.assertEqual(code, 0, stderr)
        self.assertNotIn("unexpected keyword argument 'newline'", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
