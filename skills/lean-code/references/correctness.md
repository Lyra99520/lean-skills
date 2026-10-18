# Correctness review

Read this when the request is "find the bug", "review this code", or "why does
this fail" — the cases where `lean-code`'s performance order is the wrong tool.
Correctness first, then cost.

## Scan order

Stop at the first mechanism that explains every observation. Each item is a
question with a cheap check, not a lecture.

| Layer | Ask | Cheap check |
| --- | --- | --- |
| Inputs | Null, empty, missing key, wrong type, encoding | one call with an empty value |
| Boundaries | Off-by-one, inclusive/exclusive range, duplicate handling | test first, last, empty |
| Error paths | Swallowed exception, bare `except`, error returns ignored | grep `except`, `catch`, `_ = ` |
| State | Shared mutable state, retries not idempotent, timezone/locale | two calls, or a second request |
| Resources | Unclosed file/socket, missing timeout, unbounded retry | grep `open(`, `Timeout`, `retry` |
| API use | Wrong argument order, async not awaited, deprecated call | read the signature, not the docs page |
| Concurrency | Read-modify-write, check-then-act, lock around await | interleave two callers |
| Tests | The failing case is untested; the test asserts the mock | read the test before the code |

## Reporting a correctness bug

Four lines, same as a diagnosis:

```
Cause: <mechanism> explains <observation>.
Evidence: <file:line or command output that shows it>.
Fix: <one line> and the regression test that would have caught it.
Unverified: <what you could not confirm>.
```

Do not mix correctness findings into a performance list: different order, different
fix cost, different urgency. Report the bug first, then resume the cost review.

## What "verified" means

- The failing case is reproduced before the fix, and passes after it.
- No test asserts a mock instead of the behaviour.
- A fix that cannot be reproduced is reported as "not verified" with the reason.

Never claim a bug is fixed because the code now looks right.
