# lean-skills

[![ci](https://github.com/Lyra99520/lean-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/Lyra99520/lean-skills/actions/workflows/ci.yml) [![version](https://img.shields.io/badge/version-0.2.0-blue)](CHANGELOG.md) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

四个技能和三个脚本，降低 agent 读代码库的开销，并且让省下来的量可以被测量。

```bash
/plugin marketplace add Lyra99520/lean-skills
/plugin install lean-skills@lean-skills
```

第二条命令会打开插件面板，在那里选安装范围才能完成安装。

Python 3.9+（在 3.9 与 3.12 上测试），只用标准库。没有构建步骤，没有服务，不需要 API key。

## 它是干什么的

Agent 在真正动手写代码之前，就把大部分预算花掉了：找文件、为了一个函数通读整个文件、把上千行测试输出整段粘进来、同一个错误改两遍还是错。

这套技能给上面每一步规定固定顺序，并且每一步都写了什么时候该停。三个小脚本负责那些根本不需要模型的部分：清点文件、跑项目自己的检查、估算成本。

回复也会变短，但那是最后的效果，不是目的。

## 提升在哪

| 开销 | 没用之前 | 用了之后 | 由谁负责 |
| --- | --- | --- | --- |
| 找文件 | 每次会话重复 5–10 次 grep 和 glob | 一次 `--find`，直接查缓存的符号表 | `atlas.py` |
| 读文件 | 整个文件读，本语料平均 4,793 token | 只读目标区间，最多 200 行 | 读取阶梯 |
| 看测试输出 | 全量粘贴，经常超过 1000 行 | 第一处错误 + 计数，单行截断到 300 字符 | `verify.py` |
| 改错了 | 一直试到碰巧对 | 同一个错误出现两次就停 | 停止条件 |
| 回复 | 复述代码再加一段总结 | 固定四行：改了什么 / 为什么 / 验证 / 跳过了什么 | 输出契约 |
| 性能判断 | 凭感觉 | 按影响排序的前三条，每条带量级 | `lean-code` |
| 证明有效 | 只能声称 | 带假设、扣除自身开销、附敏感性区间的估算 | `lean-stats` |

## 数字长什么样

在 CPython 3.10 标准库（去掉测试套件）上实测：568 个文件，284,864 行。

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

要引用的是**区间**，不是 32.3%。这个数字的本质是"地图替掉了两次重读"：把 `--assume-reread` 设成 0，同一个地图每个任务反而多花 295 token。所以 `measure.py` 会打印敏感性表，并用 `net first task` 扣掉插件自身的成本——四个 description 每轮常驻（约 368 token），每个被触发的正文约 820 token。

token 是按字符构成估算的，与真实分词器差 20% 左右。地图被截断时脚本会警告；地图无法回本时直接打印 `never`。真正的测量面是你会话账单里的用量，这里算的是可计算的那部分。

## 四个技能

| 技能 | 做什么 | 改善什么 |
| --- | --- | --- |
| `lean-dev` | 定位、改动、验证、报告，每步都有可写下来的停止条件 | 单任务的工具调用次数、返工率、回复长度 |
| `lean-context` | 读取阶梯、分级地图、校验输出压缩 | 每次查找消耗的 token 和调用次数 |
| `lean-code` | 按影响排序的运行时开销审查（附正确性清单） | 上线前发现的瓶颈数、误报数 |
| `lean-stats` | 测量前三个技能的效果（用 `/lean-skills:lean-stats` 调用） | 不改善什么，它告诉你该不该留着它们 |

每个技能的描述都写明了什么时候用、什么时候不要用；每个也都附了「什么时候可以不遵守」——一条规则如果到处硬套，代价比收益大。

## 三个脚本

```bash
# 在克隆的源码树里路径就是字面量；在技能内部同样的命令写成
# ${CLAUDE_SKILL_DIR} / ${CLAUDE_PLUGIN_ROOT}，装成插件后仍然可用。
python skills/lean-context/scripts/atlas.py --root .
python skills/lean-context/scripts/atlas.py --root . --find handler   # 符号 -> path:line，一次调用
python skills/lean-context/scripts/atlas.py --root . --dir src/api
python skills/lean-context/scripts/atlas.py --root . --check          # 任何修改后都会报 stale
python skills/lean-context/scripts/atlas.py --root . --since HEAD~1

python skills/lean-context/scripts/verify.py --root .
python skills/lean-context/scripts/verify.py --root . --only test
python skills/lean-context/scripts/verify.py --root . --run "pytest -x tests/test_a.py"

python skills/lean-stats/scripts/measure.py --root . --markdown
```

地图是分级的：不超过 150 个文件时一行一个文件，超过就一行一个目录，需要细节时用 `--dir` 只展开那一个。上面那个语料里，完整的目录级地图是 42 行、约 295 token，平均每行 7 token 左右。目录行只带文件数：这一层的符号列表大约贵三倍，而且多数是噪音。

地图写到 `.ai/`，记得把它加进 `.gitignore`（`--add-gitignore` 会帮你加一次）。`--check` 在文件新增、删除或修改时返回 1。`--since` 在没有缓存、或 git 无法回答时会退化成全量扫描——坏 ref 不会产生一张空地图。

`verify.py` 会识别项目自己的检查；工具装在 venv 里但不在 `PATH` 上时，回退到 `python -m pytest|ruff|mypy`。它只返回第一处错误、一个计数和一个结论；一个检查都识别不到时返回 2。

## 会话开始时发生什么

`hooks/hooks.json` 在第一条提示之前跑一个命令：存在 `.ai/atlas.md` 时只加一行提示，不存在时完全静默。整张地图不会被注入——那会让它变成每轮常驻成本，小仓库上直接亏。

`hooks/guard_read.py` 是可选的 `PreToolUse` 守卫：拒绝超过 300 行的整文件读取，把"200 行上限"从请求变成约束。启用方式：把它加进 `hooks/hooks.json` 并设置环境变量 `LEAN_READ_GUARD=1`：

```json
"PreToolUse": [
  { "matcher": "Read",
    "hooks": [ { "type": "command",
                 "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/guard_read.py\"",
                 "timeout": 5 } ] }
]
```

## 自己验证

```bash
python -m unittest discover -s tests -p "test_*.py"   # 67 个测试
python tests/validate_manifests.py                    # 打包规则校验
```

测试覆盖：地图完整性与分级、过期与增量护栏、符号查找、npx/venv 检测、输出截断、编码、超时、测量算法，以及会让插件加载失败的清单规则。CI 在 Linux、macOS、Windows 上跑 Python 3.9 和 3.12。

## 它不做什么

- 除了报告格式，不改变 agent 的说话风格。压缩文风是收益里最小的一块，也最容易过头。
- 不做 lint 或格式化。`verify.py` 只跑你已有的检查并转述结果；它会执行项目自己的命令，请像对待"自己跑测试"一样对待它，在陌生仓库先用 `--dry-run` 看一眼。
- 在 40 个文件的仓库上帮助不大。地图在那里几乎没意义，只有输出纪律还成立。
- 不代替思考。每条规则都写了例外，选错例外比省下的那点 token 贵得多。
- 不在你的机器上证明收益。`measure.py` 是带假设的估算；账单数字来自你的会话记录。

## 目录

```
.claude-plugin/     marketplace 与 plugin 清单
hooks/              会话开始提示、可选的读取守卫
skills/lean-dev/          工作流与输出契约
skills/lean-context/      读取阶梯、atlas.py、verify.py
skills/lean-code/         运行时开销与正确性审查
skills/lean-stats/        measure.py
tests/              脚本自测与清单校验
CHANGELOG.md        0.2.0 改了什么
```

## 许可

MIT，见 `LICENSE`。
0.2.0 的修复见 `CHANGELOG.md`。

[English](README.md)
