---
name: lean-context
description: "Read a codebase at the cheapest sufficient depth: a reading ladder, a tiered repo atlas, and compressed verification output. Use when exploring unfamiliar code, when tool output is huge, or when the user says the context is too long; not for editing or reviewing. Triggers: 探索代码, 代码在哪, 项目结构, 从哪开始, 上下文太长, token 太多, 输出太长, 找不到文件. Off: 正常模式, 详细说."
license: MIT
---

# lean-context

Read at the cheapest rung that answers the question, then stop.

| Rung | Action | Stop when |
| --- | --- | --- |
| 0 | Read `.ai/atlas.md` | it names the module |
| 1 | Symbol search: `atlas.py --find NAME` (one call, cached), else grep → `file:line` | one hit matches |
| 2 | Ranged read with `offset`/`limit`, at most 200 lines | the range answers it |
| 3 | Whole file | under 300 lines **and** you need its flow |
| 4 | Subagent (brief in `references/read-strategy.md`) | broad and unfamiliar |

A missing rung costs one rung, not the whole ladder: no atlas → rung 1; no grep →
filename glob then rung 2; no subagent → stop at 2 and say `Explored partially`.
Rung 4 returns a conclusion only; reject any reply that contains code or file text.
Never read a file you will not cite or edit; never re-read after a successful edit.

## Scripts

Run them, read stdout, never read their source.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/atlas.py" --root .                  # build or refresh the map
python "${CLAUDE_SKILL_DIR}/scripts/atlas.py" --root . --find NAME       # symbol -> path:line
python "${CLAUDE_SKILL_DIR}/scripts/atlas.py" --root . --dir src/api     # expand one directory
python "${CLAUDE_SKILL_DIR}/scripts/atlas.py" --root . --check           # is the map stale?
python "${CLAUDE_SKILL_DIR}/scripts/atlas.py" --root . --since HEAD~1    # rescan git changes only
python "${CLAUDE_SKILL_DIR}/scripts/verify.py" --root .                  # lint/type/test, compressed
python "${CLAUDE_SKILL_DIR}/scripts/verify.py" --root . --run "pytest -x tests/test_a.py"
```

`atlas.py` prints the map's own size. Keep the map around 120 lines or less: at
directory level one line is one directory, and `--dir` expands the part you need.
`--check` exits 1 when a file was added, removed or modified; rebuild then. Add
`.ai/` to `.gitignore` (`--add-gitignore` appends it once). If Python or the
scripts are unavailable, say `Scripts unavailable` once and use rungs 1–3.

`verify.py` returns the first error plus a count and exits 2 when it detects no
checks at all. In a monorepo, point `--root` at the changed package.

## The atlas is tiered

Up to 150 files: one line per file. More: one line per directory, `--dir` expands
one. Never ask for a file-level map of a large repo: it costs more than the files
it describes.

```
Bad:  build a file-level map of a 900-file repo
Good: directory map (~120 lines), then --dir src/api
```

## When to break the ladder

1. **Stack trace in hand.** Read the exact frame and the function it calls.
2. **User pasted the content.** Do not re-read it from disk to "confirm".
3. **Convention check.** Read one representative file whole; partial reads hide the pattern.
4. **Generated or vendored code.** Skip it.
5. **Notebook.** Grep the cell text; never read it whole.

## Pre-send check

1. Name the rung you used (`atlas`, `find`, `read:12-60`, `whole`); if you cannot
   name it, you read more than the task needed.
2. Before search call 4, write `Search: <hypothesis> → <result>`; no new
   hypothesis → ask the user.
3. Long tool output quoted in full when one line decided the outcome → cut it.
