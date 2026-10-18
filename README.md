# lean-skills

[![ci](https://github.com/Lyra99520/lean-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/Lyra99520/lean-skills/actions/workflows/ci.yml) [![version](https://img.shields.io/badge/version-0.2.0-blue)](CHANGELOG.md) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Four skills and three scripts that reduce what an agent spends reading a
codebase, and make the saving measurable.

```bash
/plugin marketplace add Lyra99520/lean-skills
/plugin install lean-skills@lean-skills
```

The second command opens the plugin panel; pick a scope there to finish the
install.

Python 3.9+ (tested on 3.9 and 3.12), standard library only. No build step, no
service, no API key.

## What it does

Coding agents spend most of their budget before they write anything: searching
for the right file, reading whole files to find one function, pasting a thousand
lines of test output, and retrying a fix that failed the same way twice.

These skills put a fixed order on each of those steps and give every step a
condition for stopping. Three small scripts do the parts that do not need a
model at all: inventorying files, running the project's own checks, and
estimating the cost.

The reply gets shorter too, but that is the last thing it does, not the point.

## Where it improves

| Cost | Without the skills | With them | Handled by |
| --- | --- | --- | --- |
| Finding a file | 5–10 grep and glob calls, repeated every session | one `--find` call against the cached symbol table | `atlas.py` |
| Reading a file | whole file, 4,793 tokens on average here | target range, 200 lines at most | reading ladder |
| Test output | pasted in full, often over 1,000 lines | first error, a count, lines clipped to 300 chars | `verify.py` |
| A fix that fails | retried until something sticks | stop at two identical failures | stop condition |
| The reply | restated code and a summary paragraph | four fixed lines: change, why, verify, skipped | output contract |
| A performance claim | intuition | top three by impact, each with a magnitude | `lean-code` |
| Proving any of it | assertion | an estimate with its assumptions, net cost and a sensitivity range | `lean-stats` |

## What the numbers look like

Measured on the CPython 3.10 standard library without its test suites (568 files,
284,864 lines):

```
$ python "${CLAUDE_SKILL_DIR}/scripts/measure.py" --root /path/to/stdlib --assume-files 4

repo: /path/to/stdlib
source: 568 files / 284,864 lines / ~2,722,581 tokens
average file: ~4,793 tokens

map: ~295 tokens, 0.01% of the source

assumes 4 full file reads per task, plus 2 re-reads when there is no map
  without a map  ~28,758 tokens/task
  with a map     ~19,467 tokens/task
  gross saving   ~9,291 tokens/task (32.3%)

installed skills (measured from the sibling SKILL.md files):
  always-on descriptions (4 skills): ~368 tokens
  triggered bodies (lean-dev, lean-context): ~1,642 tokens
  net first task: ~7,281 tokens (25.3% of a naive task)

sensitivity to --assume-reread (other assumptions fixed; negative means the map
costs more than it saves):
  rereads  saving/task   saving %
  0        ~-295          -1.5%  negative
  1        ~4,498         18.8%
  2        ~9,291         32.3%
  5        ~23,670        54.9%

payback: one-time cost ~2,305 tokens (map ~295 + skill overhead ~2,010)
  break-even: task 0.25 (includes the installed-skill overhead)
```

Read the range, not the 32.3%. The headline number is "the map saves two
re-reads per task"; at `--assume-reread 0` the same map costs 295 tokens per task
instead of saving any. That is why `measure.py` prints the sensitivity table and
`net first task` subtracts the plugin's own cost: four descriptions are resident
every session (~368 tokens) and each triggered body is ~820 tokens.

Tokens are estimated from character mix, within about 20% of a real tokenizer.
The script also warns when the map it measured was truncated, and reports
`never` when the map cannot pay itself back. The real measurement surface is the
session's billed usage; this is the computable part.

## The four skills

| Skill | Does | Improves |
| --- | --- | --- |
| `lean-dev` | Locate, change, verify, report, each with a stop condition you can write down | tool calls per task, rework rate, reply length |
| `lean-context` | Reading ladder, tiered atlas, compressed verification | tokens and calls per lookup |
| `lean-code` | Runtime cost review, ordered by impact | bottlenecks caught, false alarms raised |
| `lean-stats` | Measures the other three (invoke with `/lean-skills:lean-stats`) | nothing; it tells you whether to keep them |

Each skill's description says when to use it and when not to; every skill also
carries a list of situations where its own rules should be ignored, because a
rule applied everywhere costs more than it saves.

## The three scripts

```bash
# In a clone, paths are literal. Inside a skill the same commands use
# ${CLAUDE_SKILL_DIR} / ${CLAUDE_PLUGIN_ROOT} and keep working after install.
python skills/lean-context/scripts/atlas.py --root .
python skills/lean-context/scripts/atlas.py --root . --find handler   # symbol -> path:line, one call
python skills/lean-context/scripts/atlas.py --root . --dir src/api
python skills/lean-context/scripts/atlas.py --root . --check          # stale after any edit
python skills/lean-context/scripts/atlas.py --root . --since HEAD~1

python skills/lean-context/scripts/verify.py --root .
python skills/lean-context/scripts/verify.py --root . --only test
python skills/lean-context/scripts/verify.py --root . --run "pytest -x tests/test_a.py"

python skills/lean-stats/scripts/measure.py --root . --markdown
```

The atlas is tiered: up to 150 files it emits one line per file, above that one
line per directory, and `--dir` expands the one you need. On the corpus above
the complete directory map is 42 lines and ~295 tokens, about 7 tokens per
directory line. Directory lines carry a file count only: symbol lists at that
level cost about three times more and are mostly noise.

The map goes to `.ai/`; add that to your `.gitignore` (`--add-gitignore` appends
it once). `--check` exits 1 when any file was added, removed or modified. `--since`
falls back to a full scan when there is no cache or when git cannot answer, so a
bad ref cannot produce an empty map.

`verify.py` detects the project's own gates; when a tool is installed inside a
virtualenv but not on `PATH`, it falls back to `python -m pytest|ruff|mypy`. It
returns the first error, a count, and a verdict, and exits 2 when it finds no
checks at all.

## What runs at session start

`hooks/hooks.json` runs one command before the first prompt: it adds a single
line naming `.ai/atlas.md` when a map exists, and stays silent when it does not.
The map itself is never injected; that would turn it into always-on context and
cost more than it saves on small repositories.

`hooks/guard_read.py` is an opt-in `PreToolUse` guard that refuses whole-file
reads over 300 lines, so the 200-line rule becomes a constraint instead of a
request. To enable it, add it to `hooks/hooks.json` and set `LEAN_READ_GUARD=1`:

```json
"PreToolUse": [
  { "matcher": "Read",
    "hooks": [ { "type": "command",
                 "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/guard_read.py\"",
                 "timeout": 5 } ] }
]
```

## Checking it yourself

```bash
python -m unittest discover -s tests -p "test_*.py"   # 67 tests
python tests/validate_manifests.py                    # packaging rules
```

The suite covers the map's completeness and tiering, staleness and incremental
guards, symbol lookup, npx/venv detection, output clipping, encoding, timeouts,
the measurement arithmetic, and the manifest rules that stop a plugin from
loading. CI runs it on Linux, macOS and Windows against Python 3.9 and 3.12.

## What it does not do

- It does not change how the agent talks beyond the report shape. Terse prose is
  the smallest part of the saving and the easiest to overdo.
- It does not lint or format. `verify.py` runs your existing gates and reports
  what they said; it executes the project's own commands, so treat it like
  running the tests yourself and try `--dry-run` first on an unfamiliar repo.
- It does not help much on a 40-file repository. The map barely matters there;
  only the output discipline carries over.
- It does not remove the need to think. Every rule has a documented exception,
  and picking the wrong one costs more than the rule ever saved.
- It does not prove a saving on your machine. `measure.py` is an estimate with
  stated assumptions; the billed figure comes from your session logs.

## Layout

```
.claude-plugin/     marketplace and plugin manifests
hooks/              session-start hint, opt-in read guard
skills/lean-dev/          workflow and output contract
skills/lean-context/      reading ladder, atlas.py, verify.py
skills/lean-code/         runtime cost and correctness review
skills/lean-stats/        measure.py
tests/              script self-tests and the manifest validator
CHANGELOG.md        what changed in 0.2.0
```

## License

MIT. See `LICENSE`.
See `CHANGELOG.md` for the 0.2.0 fixes.

[中文说明](README.zh-CN.md)
