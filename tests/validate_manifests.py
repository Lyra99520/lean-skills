#!/usr/bin/env python3
"""validate_manifests.py - fail fast on the packaging mistakes that stop a load.

Checks:
    .claude-plugin/plugin.json   required fields, kebab-case name
    .claude-plugin/marketplace.json  required fields, entry sources, and the
        strict-mode conflict that makes a plugin fail to load when a
        plugin.json is also present
    hooks/hooks.json             valid JSON, top-level "hooks" object
    skills/<name>/SKILL.md       frontmatter fields, name matches the directory,
        description length, no unsupported frontmatter keys

Run:  python tests/validate_manifests.py
Exit: 0 clean (warnings allowed) / 1 errors
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT_FIELDS = ("commands", "agents", "skills", "hooks", "outputStyles", "themes")
ALLOWED_FRONTMATTER = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
    "disable-model-invocation", "user-invocable", "context", "agent", "model",
    "hooks", "paths",
}
KEBAB = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

errors: list[str] = []
warnings: list[str] = []


def load_json(rel: str) -> dict | None:
    path = ROOT / rel
    if not path.exists():
        errors.append(f"{rel}: missing")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        errors.append(f"{rel}: not valid JSON ({exc})")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{rel}: top level must be an object")
        return None
    return payload


def check_plugin() -> None:
    payload = load_json(".claude-plugin/plugin.json")
    if payload is None:
        return
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        errors.append("plugin.json: name is required")
    elif not KEBAB.match(name):
        errors.append(f"plugin.json: name {name!r} is not kebab-case")
    if not isinstance(payload.get("version"), str):
        warnings.append("plugin.json: version is missing; installed users stay pinned")


def check_marketplace() -> None:
    payload = load_json(".claude-plugin/marketplace.json")
    if payload is None:
        return
    for key in ("name", "owner", "plugins"):
        if key not in payload:
            errors.append(f"marketplace.json: {key} is required")
    owner = payload.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        errors.append("marketplace.json: owner.name is required")
    has_plugin_json = (ROOT / ".claude-plugin/plugin.json").exists()
    plugins = payload.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        errors.append("marketplace.json: plugins must be a non-empty array")
        return
    for index, entry in enumerate(plugins):
        label = f"marketplace.json: plugins[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: must be an object")
            continue
        if not isinstance(entry.get("name"), str) or not entry["name"]:
            errors.append(f"{label}: name is required")
        source = entry.get("source")
        if not isinstance(source, str) or not (source == "." or source.startswith("./")):
            errors.append(f"{label}: source must be \".\" or start with \"./\"")
        declared = [key for key in COMPONENT_FIELDS if key in entry]
        if has_plugin_json and entry.get("strict") is False and declared:
            errors.append(
                f"{label}: strict=false plus component fields {declared} conflicts with plugin.json; "
                "the plugin fails to load. Remove them (skills auto-discover from skills/)."
            )
        for key in declared:
            if not has_plugin_json:
                continue
            if entry.get("strict", True) is False:
                errors.append(f"{label}: {key} is a component field and cannot be combined this way")


def check_hooks() -> None:
    path = ROOT / "hooks" / "hooks.json"
    if not path.exists():
        warnings.append("hooks/hooks.json: not present (no session-start hint)")
        return
    payload = load_json("hooks/hooks.json")
    if payload is None:
        return
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        errors.append("hooks/hooks.json: top-level \"hooks\" object is required")
        return
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            errors.append(f"hooks/hooks.json: {event} must be an array")
            continue
        for entry in entries:
            for item in (entry or {}).get("hooks", []):
                if item.get("type") != "command" or not item.get("command"):
                    errors.append(f"hooks/hooks.json: {event} entry needs type=command and command")


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def check_skills() -> None:
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        errors.append("skills/: directory is missing")
        return
    seen = set()
    for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
        rel = f"skills/{skill_dir.name}/SKILL.md"
        path = skill_dir / "SKILL.md"
        if not path.exists():
            errors.append(f"{rel}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        if not fields:
            errors.append(f"{rel}: frontmatter block is missing")
            continue
        name = fields.get("name")
        if name != skill_dir.name:
            errors.append(f"{rel}: name {name!r} does not match directory {skill_dir.name!r}")
        if name in seen:
            errors.append(f"{rel}: duplicate skill name {name!r}")
        seen.add(name)
        description = fields.get("description", "")
        if not description:
            errors.append(f"{rel}: description is required")
        elif len(description) > 1024:
            errors.append(f"{rel}: description is {len(description)} chars, limit is 1024")
        for key in fields:
            if key not in ALLOWED_FRONTMATTER:
                warnings.append(f"{rel}: unrecognised frontmatter field {key!r}")
        body = text.split("---", 2)[2] if text.count("---") >= 2 else ""
        if len(body.splitlines()) > 200:
            warnings.append(f"{rel}: body is {len(body.splitlines())} lines; keep it under 200")


def main() -> int:
    check_plugin()
    check_marketplace()
    check_hooks()
    check_skills()
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"ERROR {error}")
    if errors:
        print(f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK: manifests and {len(list((ROOT / 'skills').glob('*/SKILL.md')))} skills validated "
          f"({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
