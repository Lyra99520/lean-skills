#!/usr/bin/env python3
"""session_start.py - tell the model one line about the repo map, at session start.

Why it exists:
    A skill can only ask the model to read .ai/atlas.md; it cannot make it. A
    SessionStart hook runs before the first prompt, so this is the one place
    where "the map exists and is current" becomes a fact instead of a hope.

Design rules:
    - One line, about 30 tokens. The whole map is never injected: that would make
      it always-on context and cost more than it saves on small repos.
    - Silent when there is no map. Never nag, never fail the session.
    - stdout must be the hook JSON object and nothing else.
"""

import json
import sys
from pathlib import Path

ATLAS = Path(".ai/atlas.md")
CACHE = Path(".ai/atlas.json")


def build_note() -> str:
    if not ATLAS.exists():
        return ""
    files = None
    try:
        payload = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(payload.get("files"), dict):
            files = len(payload["files"])
    except (OSError, ValueError, AttributeError):
        pass
    if files is None:
        return f"Repo atlas: {ATLAS.as_posix()} exists. Read it before exploring."
    return (f"Repo atlas: {ATLAS.as_posix()} ({files} files). "
            "Read it before exploring; rebuild with the lean-context atlas command if stale.")


def main() -> int:
    note = build_note()
    if not note:
        return 0
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": note,
        }
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
