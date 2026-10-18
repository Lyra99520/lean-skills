#!/usr/bin/env python3
"""measure.py - measure what a repo map saves, including what the skills cost.

Why it exists:
    Plenty of skills claim to save tokens. Almost none can show a number. This
    script computes the part that is computable and prints every assumption next
    to the result. The headline is a gross saving: full-file reads avoided minus
    the map itself. The net first task is the honest number: it also subtracts
    the skill descriptions that sit in context permanently and the SKILL.md
    bodies that the triggered skills must read, both measured from the sibling
    skill files instead of guessed.

Usage:
    python measure.py --root .                  # human readable report
    python measure.py --root . --json           # machine readable
    python measure.py --root . --markdown       # table for a README
    python measure.py --root . --assume-files 4 --assume-reread 2
    python measure.py --root . --triggered lean-dev,lean-context

    Requires .ai/atlas.md. Build it first with the sibling lean-context skill:
    python <repo>/skills/lean-context/scripts/atlas.py --root .

Exit codes:
    0 report printed, 1 map missing or unreadable, 2 bad usage / no source files.

Constraints:
    Standard library only, Python 3.9+. File selection and token estimation are
    imported from atlas.py, so this script and the map it measures cannot
    disagree about which files exist. All file IO names its encoding; nothing
    depends on the locale.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

MAX_READ_BYTES = 8_000_000
SENSITIVITY_REREADS = (0, 1, 2, 5)
DEFAULT_TRIGGERED = "lean-dev,lean-context"
DEFAULT_ATLAS = ".ai/atlas.md"

# Local fallback, used only when atlas.py cannot be imported (standalone copies).
# Keep in sync with skills/lean-context/scripts/atlas.py: importing it is the
# normal path, this exists so the script still runs without a sibling install.
FALLBACK_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "dist", "build",
    "out", "target", "vendor", "third_party", "__pycache__", ".venv", "venv",
    "env", ".idea", ".vscode", ".next", ".nuxt", ".cache", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", "htmlcov",
    ".ai", ".workbuddy-ai", ".gradle", ".terraform", "Pods",
}

FALLBACK_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".swift": "swift",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".scala": "scala", ".vue": "vue", ".svelte": "svelte",
}


def fallback_estimate_tokens(text: str) -> int:
    """Same character-mix estimate as atlas.estimate_tokens."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_chars / 4 + (len(text) - ascii_chars) / 1.2) + 1


class NoIgnore:
    """Stand-in for atlas.Gitignore when it is unavailable in a standalone copy."""

    def ignored(self, rel: str) -> bool:
        return False


def fallback_iter_source_files(root: Path, ignore=None, extra_skip=None):
    """Minimal copy of atlas.iter_source_files for standalone installs."""
    skip = set(FALLBACK_SKIP_DIRS)
    if extra_skip:
        skip.update(str(name) for name in extra_skip)
    seen_dirs = set()
    root_text = str(root)

    def on_error(_exc):
        return None

    for dirpath, dirnames, filenames in os.walk(
        root_text, topdown=True, followlinks=False, onerror=on_error
    ):
        try:
            stat = os.stat(dirpath)
            key = (stat.st_dev, stat.st_ino)
        except OSError:
            dirnames[:] = []
            continue
        if key in seen_dirs:
            dirnames[:] = []
            continue
        seen_dirs.add(key)

        rel_dir = os.path.relpath(dirpath, root_text)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        dirnames[:] = [
            name for name in dirnames
            if name not in skip
            and not (ignore and ignore.ignored(f"{rel_dir}/{name}" if rel_dir else name))
        ]
        for name in filenames:
            if Path(name).suffix.lower() not in FALLBACK_LANG:
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if ignore and ignore.ignored(rel):
                continue
            yield Path(dirpath) / name


def load_atlas_module():
    """Import the sibling atlas.py by path so there is one definition of a source file."""
    script = Path(__file__).resolve()
    try:
        skills_root = script.parents[2]
    except IndexError:  # script copied somewhere shallow, e.g. C:\\measure.py
        skills_root = script.parent
    atlas_path = skills_root / "lean-context" / "scripts" / "atlas.py"
    try:
        spec = importlib.util.spec_from_file_location("lean_skills_atlas", str(atlas_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"no import spec for {atlas_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["lean_skills_atlas"] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop("lean_skills_atlas", None)
            raise
        return module, atlas_path, None
    except Exception as exc:  # OSError, ImportError, SyntaxError, ...
        return None, atlas_path, f"{type(exc).__name__}: {exc}"


_ATLAS, _ATLAS_PATH, _ATLAS_ERROR = load_atlas_module()
_ATLAS_NAMES = ("LANG", "SKIP_DIRS", "iter_source_files", "estimate_tokens")
if _ATLAS is not None and all(hasattr(_ATLAS, name) for name in _ATLAS_NAMES):
    LANG = _ATLAS.LANG
    SKIP_DIRS = _ATLAS.SKIP_DIRS
    iter_source_files = _ATLAS.iter_source_files
    estimate_tokens = _ATLAS.estimate_tokens
    Gitignore = getattr(_ATLAS, "Gitignore", None)
    ATLAS_IMPORTED = True
else:
    if _ATLAS is None:
        _detail = _ATLAS_ERROR or "unknown import error"
    else:
        _detail = "atlas.py is missing LANG/SKIP_DIRS/iter_source_files/estimate_tokens"
    print(
        f"warning: could not import {_ATLAS_PATH} ({_detail}); "
        "using the local fallback file walker. File selection may diverge from atlas.py.",
        file=sys.stderr,
    )
    LANG = FALLBACK_LANG
    SKIP_DIRS = FALLBACK_SKIP_DIRS
    iter_source_files = fallback_iter_source_files
    estimate_tokens = fallback_estimate_tokens
    Gitignore = None
    ATLAS_IMPORTED = False


def make_ignore(root: Path):
    """Same ignore rules atlas used to build the cache, when available."""
    if Gitignore is None:
        return NoIgnore()
    try:
        return Gitignore(root)
    except Exception as exc:
        print(f"warning: could not read .gitignore under {root} ({exc}); "
              "matching atlas.py by not ignoring anything.", file=sys.stderr)
        return NoIgnore()


def collect_source_files(root: Path):
    """Measure every file atlas would list. Returns (files, warnings)."""
    files = []
    warnings = []
    ignore = make_ignore(root)
    try:
        for path in iter_source_files(root, ignore):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                warnings.append(f"warning: skipped unreadable file {rel}: {exc}")
                files.append({"path": rel, "lines": 0, "tokens": 0})
                continue
            if size > MAX_READ_BYTES:
                # The map lists these name-only; count them so both stay in sync.
                files.append({"path": rel, "lines": 0, "tokens": size // 4 + 1})
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                warnings.append(f"warning: skipped unreadable file {rel}: {exc}")
                files.append({"path": rel, "lines": 0, "tokens": 0})
                continue
            if b"\0" in data[:8192]:
                continue  # binary: atlas omits these from its cache too
            text = data.decode("utf-8", errors="replace")
            if not text:
                files.append({"path": rel, "lines": 0, "tokens": 0})
                continue
            files.append({
                "path": rel,
                "lines": text.count("\n") + 1,
                "tokens": estimate_tokens(text),
            })
    except OSError as exc:
        warnings.append(f"warning: could not walk {root}: {exc}")
    return files, warnings


def find_skill_files() -> list:
    """Locate the sibling skills/*/SKILL.md files that define this plugin's context cost."""
    script = Path(__file__).resolve()
    candidates = []
    try:
        skills_root = script.parents[2]
    except IndexError:
        skills_root = None
    if skills_root is not None and skills_root.is_dir() and (
        (skills_root / "lean-context").is_dir() or (skills_root / "lean-stats").is_dir()
    ):
        candidates = sorted(skills_root.glob("*/SKILL.md"))
    if not candidates:
        try:
            own = script.parents[1] / "SKILL.md"
        except IndexError:
            own = None
        if own is not None and own.is_file():
            candidates = [own]
    return [path for path in candidates if path.is_file()]


def _delimiter_index(lines: list, start: int):
    for index in range(start, len(lines)):
        if lines[index].strip() == "---":
            return index
    return None


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    if value[:1] in ("'", '"'):
        return value[1:]
    return value


def _join_indented(lines: list) -> str:
    """Collect a YAML block scalar / next-line value; ignore indentation and blanks."""
    collected = []
    for line in lines:
        if not line.strip():
            continue
        if not line[:1].isspace():
            break
        text = line.strip()
        if not collected and text in (">", "|", ">-", "|-", ">+", "|+"):
            continue
        collected.append(text)
    return " ".join(collected)


def _frontmatter_description(front: list) -> str:
    """Loose parse of one frontmatter `description:` value (quoted or block style)."""
    for index, line in enumerate(front):
        stripped = line.strip()
        if not stripped.startswith("description:"):
            continue
        value = stripped[len("description:"):].strip()
        if not value or value in (">", "|", ">-", "|-", ">+", "|+"):
            return _join_indented(front[index + 1:])
        return _strip_quotes(value)
    return ""


def parse_skill_md(text: str):
    """Return (frontmatter description, body after the closing ---).

    Deliberately loose: the description may be quoted and must not be assumed to
    be a fixed one-line shape. The body is everything after the closing marker.
    """
    lines = text.splitlines()
    start = _delimiter_index(lines, 0)
    if start is None:
        return "", text.strip("\n")
    end = _delimiter_index(lines, start + 1)
    if end is None:
        return "", text.strip("\n")
    front = lines[start + 1:end]
    body = "\n".join(lines[end + 1:]).strip("\n")
    return _frontmatter_description(front), body


def measure_skills(triggered: list):
    """Measure always-on descriptions (all skills) and triggered bodies."""
    warnings = []
    rows = []
    paths = find_skill_files()
    if not paths:
        warnings.append(
            "warning: no sibling SKILL.md files found next to this script; "
            "always-on and triggered-skill costs are reported as 0, so the net "
            "number is optimistic."
        )
        return rows, warnings
    wanted = set(triggered)
    for path in paths:
        name = path.parent.name
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            warnings.append(f"warning: could not read {path}: {exc}; excluded from skill cost.")
            continue
        description, body = parse_skill_md(text)
        rows.append({
            "name": name,
            "path": str(path),
            "description_tokens": estimate_tokens(description) if description else 0,
            "body_tokens": estimate_tokens(body) if body.strip() else 0,
            "triggered": name.lower() in wanted,
        })
    known = {row["name"].lower() for row in rows}
    for name in triggered:
        if name not in known:
            warnings.append(
                f"warning: --triggered names unknown skill '{name}' "
                "(no sibling skill directory matches it); ignored."
            )
    return rows, warnings


def parse_triggered(raw: str) -> list:
    names = []
    for part in (raw or "").split(","):
        name = part.strip().lower()
        if name and name not in names:
            names.append(name)
    return names


def sensitivity_rows(avg_file: int, atlas_tokens: int, assume_files: int,
                     always_on: int, triggered_tokens: int) -> list:
    rows = []
    for rereads in SENSITIVITY_REREADS:
        naive = avg_file * (assume_files + rereads)
        with_atlas = atlas_tokens + avg_file * assume_files
        saving = naive - with_atlas
        saving_pct = round(saving / naive * 100, 1) if naive else 0.0
        rows.append({
            "rereads": rereads,
            "saving": saving,
            "saving_pct": saving_pct,
            "negative": saving < 0,
            "net": saving - always_on - triggered_tokens,
        })
    return rows


def fmt_int(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def fmt_pct(value) -> str:
    return f"{value:g}%"


def fmt_break_even(value) -> str:
    """'never' when the map cannot pay back; otherwise 'task N'."""
    if value is None:
        return "never"
    number = float(value)
    if number.is_integer():
        return f"task {int(number)}"
    return f"task {number:.2f}"


def build_report(root, files, atlas_tokens, atlas_text, assume_files, assume_reread,
                 triggered, skill_rows) -> dict:
    total_tokens = sum(item["tokens"] for item in files)
    total_lines = sum(item["lines"] for item in files)
    avg_file = total_tokens // len(files) if files else 0

    always_on = sum(row["description_tokens"] for row in skill_rows)
    triggered_tokens = sum(row["body_tokens"] for row in skill_rows if row["triggered"])

    per_task_naive = avg_file * (assume_files + assume_reread)
    per_task_atlas = atlas_tokens + avg_file * assume_files
    gross = per_task_naive - per_task_atlas
    gross_pct = round(gross / per_task_naive * 100, 1) if per_task_naive else 0.0
    net = gross - always_on - triggered_tokens
    net_pct = round(net / per_task_naive * 100, 1) if per_task_naive else 0.0
    one_time = atlas_tokens + always_on + triggered_tokens

    map_only_breakeven = round(atlas_tokens / gross, 2) if gross > 0 else None
    breakeven = round(one_time / gross, 2) if gross > 0 else None
    # atlas.py marks an incomplete map with "not shown" (dir level) or a future
    # renderer may write "Truncated"; either way the ratio is computed on a
    # partial map and the reader has to be told.
    incomplete = ("not shown" in atlas_text) or ("truncated" in atlas_text.lower())

    return {
        "root": str(root),
        "files": len(files),
        "lines": total_lines,
        "source_tokens": total_tokens,
        "avg_file_tokens": avg_file,
        "atlas_tokens": atlas_tokens,
        "atlas_ratio": round(atlas_tokens / total_tokens * 100, 2) if total_tokens else None,
        "atlas_incomplete": incomplete,
        "assumptions": {
            "files_per_task": assume_files,
            "rereads": assume_reread,
            "triggered": list(triggered),
        },
        "per_task_naive": per_task_naive,
        "per_task_with_atlas": per_task_atlas,
        "saving_per_task": gross,
        "gross_saving": gross,
        "saving_pct": gross_pct,
        "always_on": always_on,
        "triggered_tokens": triggered_tokens,
        "bodies": triggered_tokens,
        "net": net,
        "net_first_task": net,
        "net_pct": net_pct,
        "one_time_cost": one_time,
        "sensitivity": sensitivity_rows(avg_file, atlas_tokens, assume_files,
                                        always_on, triggered_tokens),
        "skills": skill_rows,
        "breakeven_tasks": breakeven,
        "breakeven_honest_tasks": breakeven,
        "breakeven_map_only_tasks": map_only_breakeven,
    }


def human_lines(report: dict) -> list:
    lines = [
        f"repo: {report['root']}",
        f"source: {fmt_int(report['files'])} files / {fmt_int(report['lines'])} lines "
        f"/ ~{fmt_int(report['source_tokens'])} tokens",
        f"average file: ~{fmt_int(report['avg_file_tokens'])} tokens",
        "",
    ]
    if report["atlas_incomplete"]:
        lines.append(
            "warning: atlas.md contains a truncation notice ('not shown' / "
            "'Truncated'); atlas_tokens, atlas_ratio and every saving below are "
            "computed on an incomplete map."
        )
    ratio = report["atlas_ratio"]
    lines.append(
        f"map: ~{fmt_int(report['atlas_tokens'])} tokens, "
        f"{'n/a' if ratio is None else fmt_pct(ratio)} of the source"
    )
    lines.append("")
    files = report["assumptions"]["files_per_task"]
    rereads = report["assumptions"]["rereads"]
    lines.append(f"assumes {files} full file reads per task, plus {rereads} re-reads "
                 "when there is no map")
    lines.append(f"  without a map  ~{fmt_int(report['per_task_naive'])} tokens/task")
    lines.append(f"  with a map     ~{fmt_int(report['per_task_with_atlas'])} tokens/task")
    gross_mark = "  negative" if report["gross_saving"] < 0 else ""
    lines.append(f"  gross saving   ~{fmt_int(report['gross_saving'])} tokens/task "
                 f"({fmt_pct(report['saving_pct'])}){gross_mark}")
    lines.append("")
    triggered_names = ", ".join(report["assumptions"]["triggered"]) or "none"
    lines.append("installed skills (measured from the sibling SKILL.md files):")
    lines.append(f"  always-on descriptions ({len(report['skills'])} skills): "
                 f"~{fmt_int(report['always_on'])} tokens")
    lines.append(f"  triggered bodies ({triggered_names}): "
                 f"~{fmt_int(report['triggered_tokens'])} tokens")
    net_mark = ""
    if report["net"] < 0:
        net_mark = "  negative: the installed skills cost more than the map saves on task one"
    lines.append(f"  net first task: ~{fmt_int(report['net'])} tokens "
                 f"({fmt_pct(report['net_pct'])} of a naive task){net_mark}")
    lines.append("")
    lines.append("sensitivity to --assume-reread (other assumptions fixed; "
                 "negative means the map costs more than it saves):")
    lines.append("  rereads  saving/task   saving %")
    for row in report["sensitivity"]:
        mark = "  negative" if row["negative"] else ""
        lines.append(f"  {row['rereads']:<8} ~{fmt_int(row['saving']):<13} "
                     f"{fmt_pct(row['saving_pct'])}{mark}")
    lines.append("")
    lines.append(f"payback: one-time cost ~{fmt_int(report['one_time_cost'])} tokens "
                 f"(map ~{fmt_int(report['atlas_tokens'])} + skill overhead "
                 f"~{fmt_int(report['always_on'] + report['triggered_tokens'])})")
    lines.append(f"  break-even: {fmt_break_even(report['breakeven_tasks'])} "
                 "(includes the installed-skill overhead)")
    lines.append("")
    lines.append("This is the computable part only. Token counts are estimates "
                 "(within ~20% of a tokenizer); tool round trips and reasoning are "
                 "excluded; the model assumes whole-file reads.")
    return lines


def markdown_lines(report: dict) -> list:
    ratio = report["atlas_ratio"]
    triggered_names = ", ".join(report["assumptions"]["triggered"]) or "none"
    net_cell = f"~{fmt_int(report['net'])} tokens"
    if report["net"] < 0:
        net_cell += " (negative)"
    lines = [
        "| Metric | Value |",
        "| --- | --- |",
        f"| Source files | {fmt_int(report['files'])} |",
        f"| Lines of code | {fmt_int(report['lines'])} |",
        f"| Full source, estimated | ~{fmt_int(report['source_tokens'])} tokens |",
        f"| Map, estimated | ~{fmt_int(report['atlas_tokens'])} tokens "
        f"({'n/a' if ratio is None else fmt_pct(ratio)} of source) |",
        f"| Map complete | {'no (truncation notice in atlas.md)' if report['atlas_incomplete'] else 'yes'} |",
        f"| Average file | ~{fmt_int(report['avg_file_tokens'])} tokens |",
        f"| Always-on skill descriptions | ~{fmt_int(report['always_on'])} tokens |",
        f"| Triggered skill bodies ({triggered_names}) | "
        f"~{fmt_int(report['triggered_tokens'])} tokens |",
        f"| Gross saving per task | ~{fmt_int(report['gross_saving'])} tokens "
        f"({fmt_pct(report['saving_pct'])}) |",
        f"| Net first task | {net_cell} |",
        f"| Break-even | {fmt_break_even(report['breakeven_tasks'])} "
        "(includes skill overhead) |",
        f"| Assumptions | {report['assumptions']['files_per_task']} files per task, "
        f"{report['assumptions']['rereads']} re-reads |",
        "",
        "### Sensitivity to --assume-reread",
        "",
        "| Re-reads | Saving per task | Saving % |",
        "| --- | --- | --- |",
    ]
    for row in report["sensitivity"]:
        mark = " (negative)" if row["negative"] else ""
        lines.append(f"| {row['rereads']} | ~{fmt_int(row['saving'])} tokens | "
                     f"{fmt_pct(row['saving_pct'])}{mark} |")
    return lines


def configure_streams() -> None:
    """Never crash on a character the terminal cannot encode; never touch locale."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def missing_atlas_hint(atlas_path: Path, root: Path) -> str:
    return (f"error: map not found or unreadable: {atlas_path}\n"
            f'hint: run atlas.py --root "{root}" first, then measure again '
            "(or pass --atlas <path>).")


def main() -> int:
    configure_streams()
    parser = argparse.ArgumentParser(
        description="Estimate the honest per-task context saving of a repo map")
    parser.add_argument("--root", default=".", help="repository root, default current directory")
    parser.add_argument("--atlas", default=DEFAULT_ATLAS,
                        help=f"map path, relative to --root, default {DEFAULT_ATLAS}")
    parser.add_argument("--assume-files", type=int, default=3,
                        help="files fully read per task, default 3")
    parser.add_argument("--assume-reread", type=int, default=2,
                        help="extra re-reads without a map, default 2")
    parser.add_argument("--triggered", default=DEFAULT_TRIGGERED,
                        help="comma list of skill names whose bodies count toward "
                             f"the first task, default {DEFAULT_TRIGGERED}")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--markdown", action="store_true", help="markdown table for a README")
    args = parser.parse_args()

    if args.assume_files < 1:
        parser.error("--assume-files must be >= 1")
    if args.assume_reread < 0:
        parser.error("--assume-reread must be >= 0")

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    # The map is required in every output mode, so fail on it before anything
    # else: a missing map must exit 1, never produce a report with null ratios.
    atlas_path = Path(args.atlas)
    if not atlas_path.is_absolute():
        atlas_path = root / atlas_path
    try:
        atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        atlas_text = None
    if atlas_text is None:
        hint = missing_atlas_hint(atlas_path, root)
        print(hint, file=sys.stderr)
        if not args.json and not args.markdown:
            print(hint)  # human mode: keep the hint where a terminal user reads
        return 1

    files, warnings = collect_source_files(root)
    for message in warnings:
        print(message, file=sys.stderr)
    if not files:
        print("No source files found", file=sys.stderr)
        return 2

    triggered = parse_triggered(args.triggered)
    skill_rows, skill_warnings = measure_skills(triggered)
    for message in skill_warnings:
        print(message, file=sys.stderr)

    report = build_report(
        root=root,
        files=files,
        atlas_tokens=estimate_tokens(atlas_text),
        atlas_text=atlas_text,
        assume_files=args.assume_files,
        assume_reread=args.assume_reread,
        triggered=triggered,
        skill_rows=skill_rows,
    )

    if report["atlas_incomplete"]:
        # Human output repeats this inline on stdout; machine modes keep stdout
        # parseable and put the warning only on stderr.
        print("warning: atlas.md contains a truncation notice ('not shown'/"
              "'Truncated'); atlas_tokens, atlas_ratio and every saving below "
              "are computed on an incomplete map.", file=sys.stderr)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    if args.markdown:
        print("\n".join(markdown_lines(report)))
        return 0

    print("\n".join(human_lines(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
