#!/usr/bin/env python3
"""atlas.py - build a compact map of a repository.

Why it exists:
    Agents re-discover the same directory structure every session. A one-page
    inventory removes that, and it is far cheaper to read than the files it
    describes.

Usage:
    python atlas.py --root .                    # build the map
    python atlas.py --root . --since HEAD~1     # rescan only git-changed files
    python atlas.py --root . --dir src/api      # expand one directory
    python atlas.py --root . --find handler     # symbol -> path:line
    python atlas.py --root . --check            # report staleness only
    python atlas.py --root . --stats            # file counts per directory

Why it is tiered:
    A file-level map stops paying for itself on large repos. Above 150 files the
    map drops to one line per directory and --dir expands just the part you
    need. Directory lines carry a file count only: symbol lists at that level
    cost about three times more per line and are mostly noise.

Output (default .ai/):
    .ai/atlas.md     the map itself, one line per file or per directory
    .ai/atlas.json   machine-readable cache: path, purpose, symbol lines, mtime

Constraints:
    Standard library only. Files above 400 KB are listed name-only and binary
    files are skipped. At most six symbols are recorded per file so a line stays
    readable. Python 3.9+.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "dist", "build",
    "out", "target", "vendor", "third_party", "__pycache__", ".venv", "venv",
    "env", ".idea", ".vscode", ".next", ".nuxt", ".cache", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", "htmlcov",
    ".ai", ".workbuddy-ai", ".gradle", ".terraform", "Pods",
}

LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".swift": "swift",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".scala": "scala", ".vue": "vue", ".svelte": "svelte",
}

SYM_PATTERNS = {
    "js": re.compile(r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\*?|class|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M),
    "ts": re.compile(r"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?(?:function\*?|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M),
    "go": re.compile(r"^(?:func\s+(?:\([^)]*\)\s*)?|type\s+)([A-Za-z_]\w*)", re.M),
    "rust": re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait|mod|type)\s+([A-Za-z_]\w*)", re.M),
    "java": re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:abstract\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", re.M),
    "kotlin": re.compile(r"^\s*(?:public|private|internal)?\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)?(?:class|interface|object|fun)\s+([A-Za-z_]\w*)", re.M),
    "ruby": re.compile(r"^\s*(?:class|module|def)\s+([A-Za-z_]\w*[?!]?)", re.M),
    "php": re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|function)\s+([A-Za-z_]\w*)", re.M),
    "csharp": re.compile(r"^\s*(?:public|internal|private)?\s*(?:static\s+|sealed\s+|abstract\s+)?(?:class|interface|record|struct|enum)\s+([A-Za-z_]\w*)", re.M),
    "swift": re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:final\s+)?(?:class|struct|enum|protocol|func)\s+([A-Za-z_]\w*)", re.M),
}

MAX_BYTES = 400_000
MAX_SYMBOLS = 6
FILE_THRESHOLD = 150
DEFAULT_MAX_LINES = 400
MAX_MATCHES = 200
COMMENT_PREFIXES = ("//", "#", "/*", "*", "--", '"""', "'''")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ASCII/4 + CJK/1.2, within ~20% of a tokenizer."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_chars / 4 + (len(text) - ascii_chars) / 1.2) + 1


def write_text_lf(path: Path, text: str) -> None:
    """Write UTF-8 with LF on every platform, on Python 3.9+."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


class Gitignore:
    """A small .gitignore reader: build output and generated trees, not git's full rules."""

    def __init__(self, root: Path):
        self.patterns = []
        try:
            lines = (root / ".gitignore").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line or line.startswith(("#", "!")):
                continue
            self.patterns.append(line)

    def ignored(self, rel: str) -> bool:
        if not self.patterns:
            return False
        parts = rel.split("/")
        for raw in self.patterns:
            anchored = raw.startswith("/")
            pattern = raw.lstrip("/").rstrip("/")
            if not pattern:
                continue
            if anchored:
                if fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern + "/"):
                    return True
                continue
            if "/" in pattern:
                if fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern + "/"):
                    return True
                if fnmatch.fnmatch(rel, "*/" + pattern) or ("/" + pattern + "/") in ("/" + rel + "/"):
                    return True
                continue
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False


def iter_source_files(root: Path, ignore: Gitignore | None = None, extra_skip: set[str] | None = None):
    """Walk the tree once, pruning skipped directories in place (no .git traversal)."""
    skip = SKIP_DIRS | (extra_skip or set())
    seen_dirs: set[tuple[int, int]] = set()

    def on_error(_exc):
        return None

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=on_error):
        try:
            stat = os.stat(dirpath)
            key = (stat.st_dev, stat.st_ino)
        except OSError:
            dirnames[:] = []
            continue
        if key in seen_dirs:  # junction/symlink cycle: do not descend twice
            dirnames[:] = []
            continue
        seen_dirs.add(key)

        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        dirnames[:] = [
            name for name in dirnames
            if name not in skip and not (ignore and ignore.ignored(f"{rel_dir}/{name}" if rel_dir else name))
        ]
        for name in filenames:
            if Path(name).suffix.lower() not in LANG:
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if ignore and ignore.ignored(rel):
                continue
            yield Path(dirpath) / name


def should_index(rel: str, ignore: Gitignore, extra_skip: set[str]) -> bool:
    """Apply the same directory filters a full scan applies, to a single path."""
    skipped = SKIP_DIRS | extra_skip
    if any(part in skipped for part in rel.split("/")[:-1]):
        return False
    return not ignore.ignored(rel)


def read_source(path: Path) -> tuple[str, str]:
    """Return (text, kind) where kind is ok / large / binary / unreadable."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return "", "large"
        data = path.read_bytes()
    except OSError:
        return "", "unreadable"
    if b"\0" in data[:8192]:
        return "", "binary"
    return data.decode("utf-8", errors="replace"), "ok"


def parse_python(src: str) -> tuple[str, list[list]]:
    """One parse for both purpose and symbols; symbols carry their line number."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return "", []
    purpose = ""
    doc = ast.get_docstring(tree)
    if doc:
        for line in doc.strip().splitlines():
            if line.strip():
                purpose = line.strip()
                break
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append([node.name, node.lineno])
    return purpose, symbols


def first_comment(src: str) -> str:
    for line in src.splitlines()[:8]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#!", "# -*-", "# coding")):
            continue
        for prefix in COMMENT_PREFIXES:
            if stripped.startswith(prefix):
                text = stripped.lstrip("/*-#'\" \t").strip()
                text = text.rstrip("*/'\" \t").strip()
                if text:
                    return text
                break
    return ""


def regex_symbols(src: str, pattern: re.Pattern) -> list[list]:
    symbols = []
    for match in pattern.finditer(src):
        line = src.count("\n", 0, match.start()) + 1
        symbols.append([match.group(1), line])
        if len(symbols) >= MAX_MATCHES:
            break
    return symbols


def scan_file(path: Path, root: Path) -> dict | None:
    """Return the cache entry for one file, or None when the file is binary."""
    rel = path.relative_to(root).as_posix()
    lang = LANG.get(path.suffix.lower(), "other")
    try:
        stat = path.stat()
        mtime, size = int(stat.st_mtime), stat.st_size
    except OSError:
        mtime, size = 0, 0

    src, kind = read_source(path)
    entry = {
        "path": rel, "lang": lang, "purpose": "", "symbols": [],
        "loc": 0, "mtime": mtime, "size": size, "large": kind == "large",
    }
    if kind == "binary":
        return None
    if kind != "ok":
        return entry

    if lang == "python":
        purpose, symbols = parse_python(src)
    else:
        purpose = first_comment(src)
        pattern = SYM_PATTERNS.get(lang)
        symbols = regex_symbols(src, pattern) if pattern else []

    if purpose:
        purpose = re.sub(rf"^{re.escape(path.name)}\s*[-–—:：]\s*", "", purpose)
        purpose = purpose.rstrip("。.")
    entry["purpose"] = purpose[:80]
    entry["symbols"] = symbols[:MAX_SYMBOLS]
    entry["loc"] = src.count("\n") + 1 if src else 0
    return entry


def normalise_path(raw: str) -> str:
    return raw.strip().strip('"').replace("\\", "/")


def git_changed(root: Path, since: str) -> set[str] | None:
    """Paths touched since `since`, or None when git cannot answer.

    None must never be confused with "nothing changed": a bad ref or a missing
    repository has to trigger a full scan, not an empty map.
    """
    base = ["git", "-C", str(root), "-c", "core.quotepath=false"]
    try:
        diff = subprocess.run(base + ["diff", "--name-only", "--diff-filter=ACMRT", since],
                              capture_output=True, timeout=30)
        status = subprocess.run(base + ["status", "--porcelain"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if diff.returncode != 0 or status.returncode != 0:
        return None

    changed: set[str] = set()
    for raw in diff.stdout.decode("utf-8", "replace").splitlines():
        if raw.strip():
            changed.add(normalise_path(raw))
    for raw in status.stdout.decode("utf-8", "replace").splitlines():
        if len(raw) < 4:
            continue
        payload = raw[3:]
        if " -> " in payload:  # rename: track both sides, not the literal arrow text
            old, new = payload.split(" -> ", 1)
            changed.add(normalise_path(old))
            changed.add(normalise_path(new))
        else:
            changed.add(normalise_path(payload))
    return {rel for rel in changed if rel and not rel.startswith(".git/")}


def load_cache(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    files = payload.get("files")
    return files if isinstance(files, dict) else None


def stale_report(root: Path, cache: dict, ignore: Gitignore) -> tuple[list[str], list[str], list[str]]:
    current = {p.relative_to(root).as_posix() for p in iter_source_files(root, ignore)}
    added = sorted(current - set(cache))
    removed = sorted(set(cache) - current)
    modified = []
    for rel in sorted(current & set(cache)):
        try:
            stat = (root / rel).stat()
        except OSError:
            modified.append(rel)
            continue
        entry = cache[rel]
        if stat.st_size != entry.get("size") or int(stat.st_mtime) != entry.get("mtime"):
            modified.append(rel)
    return added, removed, modified


def file_block(directory: str, group: list[dict], symbols: bool = True) -> list[str]:
    lines = [f"## {directory}"]
    for entry in group:
        name = Path(entry["path"]).name
        parts = [f"- `{name}`"]
        if entry.get("purpose"):
            parts.append(f"— {entry['purpose']}")
        if symbols and entry.get("symbols"):
            names = " ".join(f"`{item[0]}`" for item in entry["symbols"])
            parts.append(f"· {names}")
        if entry.get("large"):
            parts.append("· over 400 KB, name only")
        lines.append(" ".join(parts))
    return lines


def dir_line(directory: str, group: list[dict]) -> str:
    return f"- `{directory}/` — {len(group)} files"


def group_by_dir(entries: list[dict]) -> dict[str, list[dict]]:
    by_dir: dict[str, list[dict]] = {}
    for entry in entries:
        parent = Path(entry["path"]).parent.as_posix()
        by_dir.setdefault("(root)" if parent == "." else parent, []).append(entry)
    return by_dir


def render(files: dict, max_lines: int, level: str, expand_dir: str | None) -> str:
    entries = sorted(files.values(), key=lambda item: item["path"])
    by_dir = group_by_dir(entries)
    total_files, total_dirs = len(entries), len(by_dir)

    # Decide the tier on the real file count, never on a truncated slice.
    if level == "auto":
        level = "file" if total_files <= FILE_THRESHOLD else "dir"
    downgraded = False
    if level == "file" and total_files > max_lines:
        level = "dir"
        downgraded = True

    expand = None
    if expand_dir:
        expand = expand_dir.strip("/\\").replace("\\", "/").rstrip("/") or "."
        if expand in (".", ""):
            expand = "(root)"

    def expanded(directory: str) -> bool:
        return expand is not None and (directory == expand or directory.startswith(expand + "/"))

    lines = [
        "# Repo atlas",
        "",
        "> Generated. Do not edit. Rebuild: run `atlas.py --root .` from the lean-context skill.",
        f"> {total_files} files · {total_dirs} dirs · {level} level",
        "",
    ]

    if level == "file":
        for directory in sorted(by_dir):
            lines.extend(file_block(directory, by_dir[directory]))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    expanded_dirs = [directory for directory in by_dir if expanded(directory)]
    for directory in expanded_dirs:
        lines.extend(file_block(directory, by_dir[directory]))
        lines.append("")

    shown = 0
    for directory in sorted(by_dir):
        if expanded(directory):
            continue
        if shown >= max_lines:
            continue
        lines.append(dir_line(directory, by_dir[directory]))
        shown += 1

    hidden = total_dirs - shown - len(expanded_dirs)
    if downgraded:
        lines.append(f"> File level would exceed --max-lines ({total_files} files); showing directories.")
    if hidden > 0:
        lines.append(f"> {hidden} directories not shown, raise --max-lines or use --dir <path>.")
    if not expand:
        lines.append("> Directory level. Expand one: `--dir <path>`")
    return "\n".join(lines).rstrip() + "\n"


def find_symbols(files: dict, needle: str, limit: int) -> list[str]:
    needle_l = needle.lower()
    hits = []
    for rel in sorted(files):
        for item in files[rel].get("symbols") or []:
            name, line = item[0], item[1] if len(item) > 1 else 0
            if needle_l in str(name).lower():
                hits.append(f"{rel}:{line}  {name}")
                if len(hits) >= limit:
                    return hits
    return hits


def ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    except OSError:
        return
    if any(line.strip().rstrip("/") == ".ai" for line in text.splitlines()):
        return
    prefix = "" if not text or text.endswith("\n") else "\n"
    write_text_lf(path, text + prefix + ".ai/\n")
    print("atlas: added .ai/ to .gitignore")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact repository map")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--out-dir", default=".ai", help="output directory inside the root, default .ai")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES,
                        help="maximum rendered line count, default 400")
    parser.add_argument("--max-files", type=int, default=None,
                        help="deprecated alias for --max-lines")
    parser.add_argument("--level", choices=["auto", "dir", "file"], default="auto",
                        help="auto: drop to directory level above 150 files")
    parser.add_argument("--dir", default=None, help="expand one directory to file level")
    parser.add_argument("--find", default=None, help="print path:line for symbols matching this text")
    parser.add_argument("--find-limit", type=int, default=20, help="maximum --find results, default 20")
    parser.add_argument("--since", default=None, help="rescan git changes only, e.g. HEAD~1")
    parser.add_argument("--check", action="store_true", help="report staleness only")
    parser.add_argument("--stats", action="store_true", help="file counts per directory")
    parser.add_argument("--exclude", action="append", default=[], help="extra directory name to skip")
    parser.add_argument("--add-gitignore", action="store_true", help="append .ai/ to .gitignore once")
    args = parser.parse_args()

    if args.max_files is not None:
        args.max_lines = args.max_files
    if args.max_lines < 1:
        parser.error("--max-lines must be >= 1")

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    ignore = Gitignore(root)
    extra_skip = set(args.exclude)
    out_dir = (root / args.out_dir).resolve()
    try:
        out_dir.relative_to(root)
    except ValueError:
        print(f"error: --out-dir must stay inside {root}", file=sys.stderr)
        return 2
    md_path = out_dir / "atlas.md"
    json_path = out_dir / "atlas.json"

    if args.add_gitignore:
        ensure_gitignore(root)

    if args.check:
        cache = load_cache(json_path)
        if cache is None:
            print("STALE: no readable atlas.json, run a full build")
            return 1
        if not md_path.exists():
            print("STALE: atlas.json exists but atlas.md is missing")
            return 1
        added, removed, modified = stale_report(root, cache, ignore)
        if not (added or removed or modified):
            print(f"OK: map is current ({len(cache)} files)")
            return 0
        print(f"STALE: {len(added)} added, {len(removed)} removed, {len(modified)} modified")
        for label, items in (("+", added), ("-", removed), ("~", modified)):
            for rel in items[:5]:
                print(f"  {label} {rel}")
        return 1

    if args.find:
        cache = load_cache(json_path)
        if cache is None:
            print("no atlas cache at .ai/atlas.json, run a full build first", file=sys.stderr)
            return 2
        hits = find_symbols(cache, args.find, max(1, args.find_limit))
        if not hits:
            print(f"no symbol matching {args.find!r} in {len(cache)} files")
            return 0
        print("\n".join(hits))
        return 0

    if args.stats:
        counts: dict[str, int] = {}
        total = 0
        for path in iter_source_files(root, ignore, extra_skip):
            parent = path.parent.relative_to(root).as_posix()
            counts[parent] = counts.get(parent, 0) + 1
            total += 1
        for directory, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"{count:5d}  {directory}")
        print(f"{total:5d}  total")
        return 0

    started = time.time()
    files: dict[str, dict] = {}
    changed = None
    if args.since:
        changed = git_changed(root, args.since)
        if changed is None:
            print("warn: git unavailable or the ref does not exist; doing a full scan", file=sys.stderr)
        elif not json_path.exists():
            print("warn: no atlas cache yet; doing a full scan", file=sys.stderr)
            changed = None
        else:
            cached = load_cache(json_path)
            if cached is None:
                print("warn: atlas.json is unreadable; doing a full scan", file=sys.stderr)
                changed = None
            else:
                files = cached

    skipped_binary = 0
    if changed is None:
        files = {}
        for path in iter_source_files(root, ignore, extra_skip):
            entry = scan_file(path, root)
            if entry is None:
                skipped_binary += 1
                continue
            files[entry["path"]] = entry
    else:
        for rel in changed:
            target = root / rel
            if (not should_index(rel, ignore, extra_skip)
                    or not target.is_file() or target.suffix.lower() not in LANG):
                files.pop(rel, None)
                continue
            entry = scan_file(target, root)
            if entry is None:
                skipped_binary += 1
                files.pop(rel, None)
            else:
                files[entry["path"]] = entry
        for rel in list(files):
            if not (root / rel).exists():
                files.pop(rel, None)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root": str(root),
        "files": files,
    }
    rendered = render(files, args.max_lines, args.level, args.dir)
    write_text_lf(json_path, json.dumps(payload, ensure_ascii=False, indent=1))
    write_text_lf(md_path, rendered)

    tokens = estimate_tokens(rendered)
    elapsed = time.time() - started
    try:
        shown_path = md_path.relative_to(root).as_posix()
    except ValueError:
        shown_path = str(md_path)
    extra = f", skipped {skipped_binary} binary files" if skipped_binary else ""
    print(f"atlas: {len(files)} files -> {shown_path} "
          f"({len(rendered.splitlines())} lines, ~{tokens:,} tokens{extra}, {elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
