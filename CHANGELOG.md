# Changelog

## 0.2.1 — 2026-10-18

- Skills work outside the plugin layout: `lean-dev` addresses the sibling
  `lean-context` scripts as `${CLAUDE_SKILL_DIR}/../lean-context/...` instead of
  `${CLAUDE_PLUGIN_ROOT}/skills/...`, so copying `skills/` into a standalone
  skills folder keeps every command working.
- The verify test shims are cross-platform, so CI is green on Linux and macOS as
  well as Windows.

## 0.2.0 — 2026-10-18

Fixes the blocking defects found by an external review. The plugin now loads,
the map is complete, and the cost numbers are stated net of the plugin itself.

### Plugin packaging

- `marketplace.json`: remove `strict: false` and the `skills` array. With
  `plugin.json` present the entry declared a component field under non-strict
  mode, which makes the plugin fail to load. Skills are auto-discovered from
  `skills/`.
- `plugin.json` / marketplace `metadata.version`: bump to 0.2.0.
- Add `hooks/hooks.json` with a `SessionStart` hook that prints one line about
  `.ai/atlas.md` (silent when there is no map).
- Add `hooks/guard_read.py`, an opt-in `PreToolUse` guard for unbounded reads.
- Add `pyproject.toml` (tooling config only) and this changelog.

### Scripts

- `atlas.py`:
  - directory-level maps are aggregated from every file, so no directory is
    silently dropped by `--max-files`; the tier is chosen on the real file count;
  - `--max-files` is a deprecated alias for `--max-lines`; `--max-lines 0` is a
    usage error;
  - `--check` detects added, removed *and modified* files (mtime + size) and
    reports a corrupt cache instead of raising;
  - `--since` warns and full-scans when there is no cache, treats a failing
    `git diff` (bad ref, no repository) as "unknown" instead of "nothing
    changed", parses renames and quoted paths, and applies the same directory
    filters as a full scan;
  - new `--find SYMBOL` prints `path:line` from the cache, so one call replaces
    several greps;
  - new `--level dir` directory lines carry a file count only (61% cheaper than
    symbol lists on a real corpus); `--dir` matches exactly (`src/api` no longer
    expands `src/api_v2`) and `--dir .` expands the root bucket;
  - walks with pruned `os.walk` instead of `rglob` (no `.git` traversal, ~40–70x
    faster on ignored trees), honours `.gitignore`, skips binary files and
    symlink/junction cycles;
  - `--out-dir` must stay inside the repository; `--add-gitignore` appends
    `.ai/` once;
  - Python 3.9: writes with `open(..., newline="\n")` instead of
    `Path.write_text(newline=...)`, which is 3.10+ only.
- `verify.py`:
  - `npx` detection reads the tool at `cmd[2]` (eslint/tsc stages actually run);
  - local `node_modules/.bin` matching is exact, so a dotfile cannot fake a tool;
  - falls back to `python -m pytest|ruff|mypy` for venv/uv projects;
  - Python project detection also accepts `tests/` or `test_*.py`;
  - `.NET` detection probes the root only, never `**/*.csproj` inside `.git`;
  - child output is captured as bytes and decoded as UTF-8, and stdout no longer
    crashes on characters the console cannot encode;
  - compressed lines are clipped to 300 characters, `--max-lines 0` returns none;
  - a timeout kills the whole process tree and returns in about `--timeout`;
  - new `--run "<command>"` compresses any command, not just the detected gates;
  - `--root` must be a directory, and the "no checks" message distinguishes
    "no project markers" from "markers present, checkers not installed".
- `measure.py`:
  - shares file selection with `atlas.py` (one definition of source files);
  - reports `net_first_task` after subtracting the measured always-on
    description cost and the triggered skill bodies;
  - prints a sensitivity table for `--assume-reread` 0/1/2/5;
  - validates assumptions, prints `never` when break-even does not exist, warns
    when the map is truncated, and exits 1 in every mode when the atlas is
    missing.

### Skills and docs

- All four `SKILL.md` files use `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}`
  for bundled scripts, so the commands work after a plugin install.
- Stop conditions became observable artifacts: `Discovery:` before the fourth
  discovery call, `Attempt n/2 — <error>` after a failure, `Search:` before the
  fourth search, and a fixed four-field report (`Change / Why / Verify / Skipped`).
- Removed the duplicated `Does / Used when / Improves` preambles (the frontmatter
  description already carries that text) and the duplicated atlas/verify prose.
- Descriptions now state negative scope, so a "review" request no longer loads a
  runtime-only skill.
- `lean-stats` is `disable-model-invocation: true`: it is a deliberate command.
- New `references/correctness.md` for correctness reviews, plus a regression-test
  rule for bug fixes.
- README/README.zh-CN claim a net range with its assumptions instead of a single
  gross percentage, and document the plugin install path and the hooks.

### Tests and CI

- Test suite covers the fixed defects: map completeness and tiering, staleness,
  incremental guards, `--find`, symbol line numbers, exact `--dir` matching,
  Python 3.9 write path, npx detection, output clipping, `--max-lines 0`, UTF-8
  output, `--run`, missing root, `measure` consistency and sensitivity.
- `tests/validate_manifests.py` checks the manifests, including the strict-mode
  conflict that caused the load failure.
- CI runs the suite on Python 3.9 and 3.12 across Linux, macOS and Windows, plus
  the manifest validator.

## 0.1.0

Initial release: four skills, three scripts, ten tests.
