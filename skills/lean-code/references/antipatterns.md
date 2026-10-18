# Performance antipatterns

Organised as "if you see this, check that". Symptom and fix only, no full code.

## Database and IO

| Pattern | Symptom | Fix |
| --- | --- | --- |
| N+1 query | `find/get/query` inside a loop | Collect ids, one `where in (...)`, assemble in memory |
| Await in loop | `for ... await db.save()` | Batch insert or `gather`, watch transaction scope |
| Unindexed filter | `where status=? order by created_at` scans | Composite index on `(status, created_at)` |
| `SELECT *` | 3 columns used, 40 returned | Explicit columns |
| No pagination | List endpoint without `limit` | Force paging, cursor over offset |
| Connect per request | `connect()` inside the handler | Pool, sized to worker count |
| Remote call in transaction | HTTP inside a transaction block | Move it out, shorten lock hold |
| Row-by-row upsert | Bulk import writes one at a time | Bulk upsert, COPY, or the vendor bulk API |

## Algorithm and data structure

| Pattern | Symptom | Fix |
| --- | --- | --- |
| Nested lookup | `in list` inside a nested loop | Build a set/dict first, O(n²) → O(n) |
| Recomputation | Same pure call repeated per iteration | Hoist out of the loop |
| String concatenation | `s += part` in a loop | Collect and `join` |
| Sort for top-k | Full sort to take the first 10 | Heap / partial sort |
| Linear scan for extremum | `max/min` every pass | Track incrementally or keep a heap |
| Naive recursion | Exponential repeated subproblems | Memoise or iterate |

## Memory

| Pattern | Symptom | Fix |
| --- | --- | --- |
| Full load | `read()` / `fetchall()` unbounded | Stream or page |
| Unbounded cache | Dict cache that never evicts | LRU with a cap, or TTL |
| Deep copy | Copying a large structure to change one field | Shallow copy plus local replacement |
| Closure retention | Callback captures the whole response body | Capture the fields you need |
| Chained intermediates | `map`/`filter` chain building lists | Generators, single pass |

## Concurrency

| Pattern | Symptom | Fix |
| --- | --- | --- |
| Coarse lock | IO or long compute inside the lock | Narrow the critical section |
| Unbounded pool | `ThreadPoolExecutor()` with no max | Size to downstream capacity, reject on overflow |
| Read-modify-write race | Non-atomic update | Atomic DB update or optimistic version |
| Sync inside async | Blocking IO in an async function | Async driver, or `to_thread` |
| Concurrent file writes | Multiple processes appending | Single writer with a queue, or shard |

## Network and serialisation

| Pattern | Symptom | Fix |
| --- | --- | --- |
| Serial remote calls | Independent requests awaited in sequence | Concurrent, with timeout and breaker |
| Uncompressed payload | Multi-MB JSON | Paginate, gzip, trim fields |
| Repeated parsing | `json.loads` on the same payload | Parse once, pass the object |
| Missing timeout | Any HTTP client without one | Always set one, 3–10s |

## Frontend rendering

| Pattern | Symptom | Fix |
| --- | --- | --- |
| Unvirtualised list | Thousands of rows rendered | Virtual scroll or paginate |
| Broad re-render | One state change re-renders the tree | Split components, memo, push state down |
| Render-time compute | `filter`/`sort` of a large array in the body | `useMemo` or move to the data layer |
| Unsized images | Layout shift | Explicit dimensions plus lazy load |
