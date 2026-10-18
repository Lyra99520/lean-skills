---
name: lean-code
description: "Runtime cost review for code that actually runs hot: algorithm, IO, memory, concurrency, ranked by impact. Use when something is slow, laggy, memory-heavy or racy, or when a hot path changed; not for correctness, security or style review. Triggers: 太慢, 卡, 内存, 并发, 性能, 优化, N+1, 慢查询. Off: 正常模式, 详细说."
license: MIT
---

# lean-code

**Correctness first, then cost.** A fast wrong answer is still wrong. This skill
reviews runtime cost; if the request is a correctness or security review, say so
and use `references/correctness.md` instead.

## Review order

Work top-down. Stop when the remaining layers cannot change the answer.

| Order | Layer | Typical payoff |
| --- | --- | --- |
| 1 | Algorithm and data structure | Drops a complexity class |
| 2 | IO and network | Round trips, batching, indexes, pooling |
| 3 | Memory | Full loads, unbounded caches, large copies |
| 4 | Concurrency | Lock scope, races, pool sizing |
| 5 | Readability | Last, and never mixed into the perf list |

Patterns to scan for: `references/antipatterns.md` (read it when a layer looks
hot). Threshold for "worth fixing at all": `references/review-checklist.md`.

## Output limit

- Report **three** problems, ordered by impact ÷ fix cost.
- Each one is four fields: `location` / `symptom` / `magnitude` / `fix in one line`.
- End with `Skipped: <N> more` so "review everything" still has an answer; list
  the rest only if the user asks.
- No option menus. Pick the fix you would actually ship.
- Without a measurement, state the degradation curve, not a speedup multiple.

```
Bad:  This code has performance issues. You could use a cache, or batch the
      queries, or add an index. Also the variable names could be improved.

Good: 1. src/api/orders.py:88 — one query per order inside the loop (N+1)
         Magnitude: 1,000 orders → 1,001 round trips, linear in order count
         Fix: single `where user_id in (...)` then assemble in memory
      Skipped: 4 more (2 cold path, 2 style)
```

## When to break these rules

1. **The user asks for a full audit.** Report everything, grouped by layer, with
   the top three marked.
2. **Correctness bug found mid-review.** Stop the perf review, report the bug
   first, resume after.
3. **Throwaway script or prototype.** Say "not worth optimizing" and stop.
4. **Cold path.** Runs once at startup → the fix is noise. Say so.
5. **The fix costs more than the problem.** A dependency, a cache layer or a
   background job to save 3 ms: reject it out loud.
6. **No heat data at all.** Say what cannot be determined, and give the one
   command that would measure it instead of guessing.

## Pre-send check

1. Did you claim a speedup without a measurement or a stated data size?
2. Are naming, formatting or architecture opinions leaking into the perf list?
3. Is any reported problem outside the changed files and their direct callers?
4. Did you propose a new dependency for something the standard library does?
