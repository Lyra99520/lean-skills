# Review process and threshold

## When optimising is worth it

All three must hold. Otherwise record it and recommend nothing.

1. **Hot path.** Called frequently, or data volume grows with the business.
2. **Quantified.** A measurement, a call-count estimate, or a stated data size.
3. **Cheaper to fix than to live with.** Local change, no new dependency, no
   interface break.

If any fails, the conclusion is "not now", plus the trigger condition
("revisit when daily orders exceed 10k").

## Steps

1. **Scope.** Only the changed files and their direct callers. Not the module.
2. **Find heat.** Loops, DB calls, network calls, serialisation. If there is no
   heat data, say so and name the one measurement that would produce it.
3. **Scan patterns.** Walk `antipatterns.md` by category, record hits.
4. **Estimate magnitude.** Data size and growth curve, not a precise multiple.
5. **Take the top three** by impact ÷ fix cost.
6. **State the fix** in one line each. Do not write the implementation.

## Writing magnitude

Verifiable phrasing only:

- Good: "1,000 orders → 1,001 round trips, linear in order count"
- Bad: "very slow"
- Good: "peak memory grows with file size, ~30MB resident for a 10MB input"
- Bad: "high memory usage"

## Conclusion template

```
Scope: <files, max three>

1. <location> — <symptom>
   Magnitude: <size and growth>
   Fix: <one line>

2. ...

Skipped: <N> items — <cold path / no data / fix costs more than the problem>
```

## Common misjudgements

- Treating ugly code as slow code. They are independent.
- Concluding performance from 10 test rows.
- Optimising a cold path while the real bottleneck stands.
- Hiding an N+1 behind a cache; it returns the day the cache misses.
- Reporting a correctness bug as a performance issue. Bugs go first; see
  `correctness.md`.
