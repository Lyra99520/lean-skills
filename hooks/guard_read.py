#!/usr/bin/env python3
"""guard_read.py - optional PreToolUse guard: refuse unbounded whole-file reads.

Off by default. Enable it by adding this file to hooks.json (see README) and
setting LEAN_READ_GUARD=1 in the environment. With the variable unset, the
script reads nothing and exits 0, so it can be wired up safely before you trust
it.

Contract: reads the hook payload from stdin, and when the model asks for a file
with no `limit` that is longer than MAX_LINES, writes one reason to stderr and
exits 2 (a blocking hook error). Otherwise exits 0 and changes nothing.
"""

import json
import os
import sys
from pathlib import Path

MAX_LINES = 300


def line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(65536), b"")) + 1
    except OSError:
        return 0


def main() -> int:
    if os.environ.get("LEAN_READ_GUARD") != "1":
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if payload.get("tool_name") not in (None, "Read"):
        return 0
    tool_input = payload.get("tool_input") or {}
    if tool_input.get("limit") or tool_input.get("offset"):
        return 0
    raw = tool_input.get("file_path")
    if not raw:
        return 0
    path = Path(raw)
    if not path.is_file():
        return 0
    total = line_count(path)
    if total <= MAX_LINES:
        return 0
    sys.stderr.write(
        f"read at most 200 lines at a time: {path} has {total} lines. "
        "Pass offset/limit, or read .ai/atlas.md first to find the right range."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
