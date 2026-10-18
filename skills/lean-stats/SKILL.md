---
name: lean-stats
description: "Estimate what the lean-* skills save on a repository: source size, atlas size, per-task cost, break-even, and how sensitive that number is. Invoke deliberately with /lean-skills:lean-stats when someone asks whether the plugin is worth it or wants numbers for a README. Not for day-to-day coding."
license: MIT
disable-model-invocation: true
---

# lean-stats

A claim without a number is marketing. This skill produces a number, prints the
assumptions that number depends on, and shows how much it moves when they change.

## Run

```bash
python "${CLAUDE_SKILL_DIR}/scripts/measure.py" --root .                # human report
python "${CLAUDE_SKILL_DIR}/scripts/measure.py" --root . --markdown     # table for a README
python "${CLAUDE_SKILL_DIR}/scripts/measure.py" --root . --json         # machine readable
python "${CLAUDE_SKILL_DIR}/scripts/measure.py" --root . --assume-files 4 --assume-reread 2
python "${CLAUDE_SKILL_DIR}/scripts/measure.py" --root . --triggered lean-dev
```

Requires `.ai/atlas.md`; build it first with `atlas.py` from the lean-context
skill. Exits 1 when the map is missing, in every output mode.

## Read the result

| Field | Meaning |
| --- | --- |
| `source_tokens` | Estimated cost of reading every source file once |
| `atlas_tokens` | Cost of the map, the one-time investment |
| `per_task_naive` | Cost of a task without a map |
| `per_task_with_atlas` | Cost of the same task with a map |
| `saving_per_task` | Gross saving per task |
| `net_first_task` | Gross saving minus the plugin's own always-on and triggered cost |
| `breakeven_tasks` | Tasks before the map pays for itself; `never` is a real answer |
| `sensitivity` | The same saving at `--assume-reread` 0, 1, 2 and 5 |

The sensitivity table is the point: the headline percentage is driven by how much
the agent re-reads without a map, which is an assumption, not a measured fact.
Quote the range, not the single number.

A negative saving is a real result: the repo is too large or too small for this
map. Regenerate with `--level dir`, or point `--root` at the package you work on.

## Honest boundaries

State these whenever quoting a number:

- Tokens are estimated from character mix, ±20% versus a real tokenizer.
- The model assumes full-file reads; ranged reads shift the ratio upward.
- Tool-call round trips and reasoning tokens are excluded. They usually favour the map.
- The plugin is not free: always-on descriptions plus each triggered body are
  subtracted in `net_first_task`.
- This measures context cost, not wall-clock time or answer quality.

```
Bad:  This skill cuts token usage by 70%.

Good: On a 4,000-file repo the directory-level atlas is ~3.8k tokens, about one
      average file. At 3 files read per task the gross saving is 15–30%
      depending on re-reads; after the plugin's own ~2k tokens the first task
      nets 10–20%. Estimate, not a billed figure.
```

## When to break these rules

1. **User asks for a single number.** Give it with the repo size and the
   assumption that produced it attached. A ratio without a denominator is meaningless.
2. **Comparing against another tool.** Measure both on the same repo with the same
   assumptions. Do not compare your estimate to their claim.
3. **Small repo (under 50 files).** Say the map barely matters there. Honesty
   here buys credibility for the large-repo number.

## Pre-send check

1. Is every number labelled as an estimate?
2. Does each ratio name its denominator and its assumption?
3. If the saving is negative, did you say so instead of hiding it?
