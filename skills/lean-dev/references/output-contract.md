# Output contract

Every reply ends with one of four shapes. Pick the shape before writing, not
after.

## Case 1 — reporting a change

Bad (~300 tokens, low density):

> I've completed the changes. Specifically, in `src/api/routes.py`, I changed the
> hard-coded retry count from 1 to read from config. The original was:
> ```python
> for _ in range(1):
> ```
> And now it is:
> ```python
> for _ in range(settings.RETRY):
> ```

Good (~45 tokens, four lines):

```
Change: src/api/routes.py:42 — retry count now reads config, default 3
Why: the request named the hard-coded 1 as the bug
Verify: pytest tests/test_routes.py → passes
Skipped: none
```

## Case 2 — reporting a diagnosis

Bad: retelling three hours of investigation in chronological order.

Good:

```
Cause: pool limit 5, but 16 workers, so peak-hour acquisition times out.
Evidence: pg_stat_activity held 16 idle-in-transaction for 4 minutes.
Fix: pool_size=16, plus a 3s acquire timeout.
Unverified: not reproduced under load test; needs staging.
```

Fixed shape: **cause / evidence / fix / unverified**.

## Case 3 — reporting a review

Used by `lean-code` (runtime cost) and by a correctness review. Three findings,
each with location / symptom / magnitude / fix, then one closing line:

```
1. src/api/orders.py:88 — one query per order inside the loop (N+1)
   Magnitude: 1,000 orders → 1,001 round trips, linear in order count
   Fix: single `where user_id in (...)` then assemble in memory

2. ...

Skipped: 9 more (style, cold path); say the word and I'll list them.
```

## The test

Read your reply and ask: **if I delete half of this, can the user still act?**
If yes, delete that half.

## Exceptions

Expansion is correct, not waste, when:

- The user asked for an explanation or a walkthrough.
- The action is irreversible (delete, migrate, deploy) and needs review.
- The conclusion contradicts the user's expectation and needs the reasoning.
- A safety or security warning is involved. Never compress a warning.
- The user says 详细说 / explain fully. Suspend the contract for that turn.
