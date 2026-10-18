# Read strategy

## Symbol search patterns

Designed for "find the definition of a name", which is an order of magnitude
cheaper than reading the file that contains it.

First choice: `atlas.py --find NAME` reads the cached symbol table and returns
`path:line` in one call. Use the patterns below only when there is no atlas.

| Target | Pattern |
| --- | --- |
| Python class/function | `^\s*(class\|def\|async def) NAME` |
| JS/TS export | `export (default )?(function\|class\|const\|interface\|type) NAME` |
| Go | `^func (\([^)]*\) )?NAME` |
| Rust | `^(pub )?(fn\|struct\|enum\|trait) NAME` |
| Java/Kotlin | `(class\|interface\|enum\|record) NAME\b` |
| Any reference | `\bNAME\b` restricted to source extensions |
| Call sites only | `NAME\(` excluding tests |

## Large files

1. Get the skeleton first: search definitions only. Cost is usually under 1KB.
2. Then get the body: read `offset = start_line - 3`, `limit = length + 6`, so
   the boundaries stay visible.
3. Above 1,500 lines, treat the file as a module index. Do not try to hold it.

## When a full read is correct

All three must hold:

- File is under 300 lines.
- The task needs overall data flow, not a single edit.
- You will reference several parts of it again (one read beats five ranges).

## Subagent brief

Use the subagent as a compiler: question in, conclusion out, no source text.
`Explore`-style agents start without the conversation, so the brief must stand
alone.

```
Explore <directory>. Answer three questions in under 200 words:
1. Where is the HTTP entry point (file and function)?
2. Which layers does a request cross, one clause each?
3. To add <feature>, which 1-3 files change?
No code. Paths and line numbers only.
```

If no subagent tool is available, stop at the ranged read and say
`Explored partially` — do not simulate a subagent by reading ten files yourself.

## Common waste

- Reading files across a directory to decide which one matters.
- `cat` on a 2,000-line log.
- Re-reading a file to confirm an Edit that already returned success.
- Re-discovering the same structure every session because no map was kept.
- Asking for a file-level map of a repo with more than a few hundred files.
