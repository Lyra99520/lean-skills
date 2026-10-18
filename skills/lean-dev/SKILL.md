---
name: lean-dev
description: "Lean coding workflow: locate, change, verify, report, each step ending at a condition you can write down. Use when editing code, fixing a bug, adding a feature or refactoring; not for explanations, code review or exploration-only tasks. Triggers: 改代码, 修 bug, 修一下, 报错, 跑不起来, 实现, 重构, 只要 diff, 别啰嗦, 省 token. Off: 正常模式, 详细说."
license: MIT
---

# lean-dev

Four steps. Each ends at a condition you can count or write down, because a rule
an agent cannot observe is not a rule.

## 1. Locate — 3-call discovery budget

1. `.ai/atlas.md` if it exists: free, does not count.
2. No atlas and an unfamiliar area: build one from the **lean-context** skill,
   unless the repo is under 50 files or the path is already known.
3. `python "${CLAUDE_PLUGIN_ROOT}/skills/lean-context/scripts/atlas.py" --root . --find NAME`
   answers "where is this symbol" in one call. Otherwise grep the symbol, then
   read ONE candidate with `offset`/`limit`, at most 200 lines.
4. **Stop rule:** before call 4, write
   `Discovery: <3 things ruled out> | next: <grep X or ask Y>`.
   Fewer than three reasons → ask one question naming the module you suspect
   instead of searching further.

```
Bad:  glob the tree → read 6 files → decide
Good: atlas → find symbol → read 40 lines
```

## 2. Change — the narrowest layer

- Edit by default. Write a whole file only for a new file, a rewrite of more than
  70% of it, or generated content; say `Write: <reason>`.
- Allowed without asking: lines the request names, imports you now use, one new
  test, formatter output on touched lines.
- Everything else (dead code nearby, naming, extra refactors): one line under
  `Skipped:`, do not fix it.
- **Stop condition:** the failing behaviour is addressed and nothing else moved.

## 3. Verify — 2-identical-failure budget

- Run the change's own test first:
  `python "${CLAUDE_PLUGIN_ROOT}/skills/lean-context/scripts/verify.py" --root . --run "pytest tests/test_x.py -x"`.
  Full `verify.py` only when no targeted test exists or the change crosses modules.
- **Stop rule:** after a failure write `Attempt 1/2 — <error>`. Same error again →
  stop: hypothesis, evidence, what you cannot determine. Never attempt 3.
- Bug fix with no test covering the behaviour: write the failing regression test
  first, then fix it.

## 4. Report — four fixed lines

```
Change: <path:line> — <what changed>
Why: <one sentence tied to the request>
Verify: <command> → <pass/fail, or not run + why>
Skipped: <none, or what you left alone>
```

No test runner: `Verify: no checks detected (tried <command>)`. A diagnosis
instead of a change: `Cause / Evidence / Fix / Unverified`.
Templates and more pairs: `references/output-contract.md`.

## When to break these rules

1. **Teaching request.** User asks how something works → prose, no diff.
2. **Irreversible or security-relevant change.** One-line warning before acting;
   the approval prompt is the confirmation, do not re-confirm in prose.
3. **Ambiguous requirement.** No file, symptom or intent → ask before locating.
4. **Unknown cause.** Rank hypotheses, falsify the cheapest one, edit only when
   one mechanism explains every observation.
5. **Exploratory task in a new repo.** If the job is "understand this codebase",
   building the atlas *is* the deliverable.
6. **详细说 / explain fully.** The output contract is suspended for that turn;
   resume afterwards.

## Pre-send check

1. Preamble or recap: delete. Paths, symbols, numbers, error strings: verbatim.
2. Every fix claim needs a `Verify:` line; otherwise write "not verified" and say why.
3. Is the reply longer than the diff needs? If half of it can be deleted and the
   user can still act, delete that half.
