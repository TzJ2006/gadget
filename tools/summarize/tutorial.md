# AI 对话日报 & 周报 & 月度总结工具 — 快速上手

这个工具自动读取你每天和 AI 的对话记录（Claude Code / Codex / Cursor Agent / ChatGPT / 通用 JSON），调 LLM API 生成结构化日报、周报和月度总结。

支持多设备工作流：在每台机器上导出对话 log，通过云盘同步或手动拷贝汇总，生成最终日报。积累足够日报后可生成周报和月度趋势总结。

## 本版修复与变更（2026-06-28）

经一次逻辑审计修复了以下问题（均不改变命令用法，只是让它们正确工作）：

- **日期归类统一为本地时区**：Claude Code 的时间戳过去按 UTC 归日，而 `target_date` 和 Codex（按目录名）按本地日期，导致临近午夜的会话归错天、两个来源对不上。现统一用本地日期（`astimezone()`），同一天的活动正确聚合。
- **`auto` 不再总结当天未完成数据**：`auto` 传给 `daily merge` 的 `--before <今天>` 之前被忽略，当天半截记录照样跑一次 LLM 总结；现已生效。
- **ChatGPT 导出解析更正**：改为沿 `current_node` 走当前激活分支（编辑/重新生成后正确的那条，过去固定取第一个 child 会走废弃分支）；并按消息本地日期过滤，跨天会话不再把其它日期内容混入当天报告。
- **周报/月报渲染不再因缺字段崩溃**：LLM 偶尔漏返回某字段时，渲染由 `KeyError`（丢失整份已生成报告）改为优雅降级。
- **日报「今日概览」部分字段也能渲染**：只返回 `how`/`impact` 或只有 `devices` 时，不再出现空标题或内容丢失。
- **分块缓存键纳入 prompt/上下文**：prompt 前缀或设备摘要变化时正确失效旧分块缓存，不再复用旧 prompt 下生成的摘要。

> 请先 `pip install -e .`，再从仓库根目录运行 `python -m summarize`。

## 目录结构

```
summarize/                   # pip 可安装包（python -m summarize）
├── __init__.py              # 包入口
├── __main__.py              # 统一 CLI: python -m summarize {daily,weekly,monthly,auto}
├── config.py                # 配置加载、路径解析、设备名
├── remote.py                # rclone 上传/下载
├── parsers.py               # 对话解析 (Claude Code / Codex / Cursor Agent / ChatGPT / generic)
├── usage.py                 # token 用量采集 (ccusage 20.x 逐源命名空间命令)
├── summarizer.py            # LLM 总结、分块、分层合并
├── formatter.py             # Markdown 生成、重要性排序、Hugo 集成、双语输出
├── charts.py                # Token 用量图表 (matplotlib)：三子图 PNG (Tokens/Cost/Cache)
├── daily.py                 # 日报管线编排 (export / merge / deploy / config)
├── cli.py                   # argparse 设置 + 子命令路由
├── auto.py                  # 全流程自动化：daily export → merge → weekly → monthly
├── monthly_summary.py       # 月度总结 (generate / list)
├── weekly_summary.py        # 周报总结 (generate / list)
├── daily_summary.py         # 向后兼容 re-export shim（旧 import 路径仍可用）
├── llm_backends.py          # 重导出 shim → common/
├── requirements.txt         # Python 依赖
└── tests/                   # pytest 测试套件
    ├── test_imports.py      # 导入契约测试（重构后必跑）
    ├── test_config.py       # 配置逻辑测试
    ├── test_parsers.py      # 解析器测试
    ├── test_formatter.py    # 格式化测试
    └── test_summarizer.py   # 分块/提示测试

outputs/                     # 所有生成文件（项目根目录下，已 gitignore）
├── logs/summarize/          # export 导出的对话 log（中间产物，可跨设备同步）
├── reports/summarize/       # 日报 + 周报 + 月度报告
│   ├── 2026-02-13.json / .md              # 日报
│   ├── 2026-W07-weekly.json / .md         # 周报
│   ├── 2026-02-monthly.json / .md         # 月度报告
├── images/summarize/        # 用量图表 PNG
│   ├── 2026-02-13-usage.png               # 日报三子图 (Tokens/Cost/Cache)
│   ├── 2026-02-monthly-tokens.png         # 月度 token 趋势图
│   └── 2026-02-monthly-cost.png           # 月度费用趋势图
└── cache/summarize/         # LLM chunk 缓存
    ├── weekly/              # 周报 LLM 缓存
    └── monthly/             # 月度 LLM 缓存

config.json                  # 仓库根统一配置（summarize 段：设备别名、输出路径、rclone 远端；config --init 写入，gitignored，模板 config.example.json）
```

## 前置条件

Python 3.10+，无需额外安装即可运行 `export`（纯本地解析）。

Token 用量统计需要 Node.js（通过 npx 调用 [ccusage](https://github.com/ryoppippi/ccusage)），没装也不影响其他功能。

安装包和 Python 依赖：

```bash
# 安装 summarize 包（推荐，启用 python -m summarize 命令）
pip install -e .
# 或只安装 Python 依赖
pip install -r tools/summarize/requirements.txt
```

> **CLI 用法变更**：重构后推荐使用 `python -m summarize daily ...` 形式。旧的 `python tools/summarize/daily_summary.py ...` 仍然可用（向后兼容）。本教程中的命令均使用新形式。

调 API 生成总结时，有四种后端可选：

### 方式一：Ollama（默认，推荐）

使用本地 Ollama 服务生成总结（默认模型 Gemma4-26B），**无需 API key**。需要本地已运行 Ollama 并拉取聊天模型（参见 `scripts/serve_local_llm.sh`），以及 `pip install openai`（Ollama 走 OpenAI 兼容协议）。

使用时无需额外参数，`--api` 默认就是 `ollama`（全局改默认：`GADGET_LLM_BACKEND` 环境变量或 config 的 `default_api`）：

```bash
python -m summarize daily export --summarize --date 2026-02-13
```

### 方式二：Claude Code CLI

使用本地安装的 Claude Code CLI 生成总结，**无需设置 API key**，直接复用 Claude Code 的登录状态。

```bash
# 安装 Claude Code CLI（如果还没装）
npm install -g @anthropic-ai/claude-code

# 确认已登录
claude --version
```

```bash
python -m summarize daily export --summarize --date 2026-02-13 --api claude_cli
```

### 方式三：Anthropic API

直接调用 Claude API，需要 API key：

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

python -m summarize daily export --summarize --date 2026-02-13 --api anthropic
```

### 方式四：OpenAI API

```bash
pip install openai
export OPENAI_API_KEY="sk-..."

python -m summarize daily export --summarize --date 2026-02-13 --api openai
```

## 配置文件（推荐）

多设备使用时，建议在每台设备上创建配置文件，设置设备别名和输出路径。

配置文件解析顺序：`GADGET_CONFIG` 环境变量（显式路径，优先级最高）> 仓库根 `config.json` 的 `summarize` 段（`config --init` / `onboard --init-config` 写入这里，gitignored，模板根目录 `config.example.json`）。不再读取 `tools/summarize/config.json` 或 `~/.config/summarize/config.json`。

### 快速创建

```bash
python -m summarize daily config --init
```

交互式询问各项设置，生成配置文件。

### 手动编辑

```json
{
  "device_name": "home-server",
  "logs_dir": "~/Google Drive/summarize/logs",
  "reports_dir": "~/Google Drive/summarize/reports",
  "rclone_remote": "gdrive:gadget/summarize",
  "rclone_path": "~/.local/bin/rclone"
}
```

### 字段说明

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `device_name` | 设备别名，用于 export 文件名和 log 内容 | 系统主机名（`platform.node()`） |
| `logs_dir` | logs 输出目录，支持 `~`，可指向云盘同步目录 | `outputs/logs/summarize/` |
| `reports_dir` | reports 输出目录，支持 `~` | `outputs/reports/summarize/` |
| `rclone_remote` | rclone 远端路径，export 上传到 `<remote>/logs/`，merge 上传到 `<remote>/reports/`，`--sync` 从 `<remote>/logs/` 下载 | （不上传） |
| `rclone_path` | rclone 二进制路径，支持 `~`，用于无 sudo 权限的环境 | 从 PATH 查找 |

所有字段都是可选的，不需要的可以不写。没有配置文件时一切行为与之前相同。

### 查看当前配置

```bash
python -m summarize daily config --show
```

输出示例：

```
配置文件路径: /home/user/gadget/config.json  (section: summarize)
配置内容:
{
  "device_name": "home-server",
  "rclone_remote": "gdrive:gadget/summarize"
}

当前生效路径:
  device_name:  home-server
  logs_dir:     /home/user/Documents/gadget/summarize/logs
  reports_dir:  /home/user/Documents/gadget/summarize/reports
  rclone:       gdrive:gadget/summarize (已找到: /usr/bin/rclone)
    logs:       gdrive:gadget/summarize/logs/
    reports:    gdrive:gadget/summarize/reports/
```

### 输出路径优先级

输出路径按以下优先级解析，高优先级覆盖低优先级：

```
--output CLI 参数 > 环境变量 > config.json > 默认路径
```

环境变量：`SUMMARIZE_LOGS_DIR`（export 输出）、`SUMMARIZE_REPORTS_DIR`（merge/单机模式输出）。

示例：即使 config 中设了 `logs_dir`，`--output /tmp/test` 仍然优先：

```bash
python -m summarize daily export --output /tmp/test --date 2026-02-13
# → /tmp/test/2026-02-13_home-server.json
```

## 机器标识

每台设备可以通过 `device_name` 设置一个易读的别名，替代默认的系统主机名（如 `DESKTOP-ABC123`）。

设置方法：
- 运行 `config --init` 交互式设置
- 或手动在仓库根 `config.json` 的 `summarize` 段中添加 `"device_name": "my-alias"`

### 文件名变化

export 导出的文件名使用 `device_name`：

```
未配置: 2026-02-14_DESKTOP-ABC123.json
配置后: 2026-02-14_home-server.json
```

### export log 中的设备信息

`device_name` 和原始 `hostname` 都会保留在 export log 中：

```json
{
  "device": {
    "device_name": "home-server",
    "hostname": "DESKTOP-ABC123",
    "platform": "win32",
    "username": "tongt"
  }
}
```

merge 生成日报时，AI 会看到 `device_name` 作为设备标签，报告更易读。

## 工作流程

整个工具分两个阶段。无子命令时默认执行 export（仅导出，不调 API）。

### Phase 1: Export（每台设备上运行）

在每台有 AI 对话记录的机器上运行 `export`，不需要 API key：

```bash
# 导出所有未导出日期的对话（默认行为）
python -m summarize daily export

# 指定日期（仅导出该天）
python -m summarize daily export --date 2026-02-13

# 同时加入 ChatGPT / 通用格式
python -m summarize daily export --date 2026-02-13 \
    --chatgpt conversations.json \
    --generic other_chat.json
```

不带 `--date` 时，`export` 会扫描所有存在对话的日期，跳过已导出的，逐日导出到对应的日期文件中。

生成文件：`<logs_dir>/2026-02-13_<device_name>.json`

例如配置了 `device_name: "macbook"`：`outputs/logs/summarize/2026-02-13_macbook.json`

这个 JSON 包含：
- 设备信息（设备别名、主机名、平台、用户名）
- 当天所有对话内容
- Token 用量统计（自动通过 ccusage 采集，包含各模型的 token 数和费用）
- 可选的单设备 AI 总结（见下方）

如果配置了 `rclone_remote`，log 文件会自动上传到 `<rclone_remote>/logs/`（如 `gdrive:gadget/summarize/logs/`）。

**可选：导出时顺便生成单设备总结**

```bash
python -m summarize daily export --date 2026-02-13 --summarize
```

加了 `--summarize` 后会调 API 为这台设备的对话先做一次总结，结果存在 log 的 `device_summary` 字段里。后续 merge 时会利用这些总结作为上下文，提高最终日报质量。

### Phase 2: Merge（任意设备上运行）

有两种方式提供 log 文件给 merge：

**方式一：`--sync` 自动拉取（推荐）**

配置了 `rclone_remote` 后，使用 `--sync` 自动从远端 `<remote>/logs/` 下载所有设备的 log：

```bash
# 从远端同步当天 log 后合并（推荐）
python -m summarize daily merge --sync --date 2026-02-13

# 同步 + 部署到 Hugo
python -m summarize daily merge --sync --date 2026-02-13 --deploy

# 用 Anthropic API
python -m summarize daily merge --sync --date 2026-02-13 --api anthropic
```

`--sync` 会下载 `2026-02-13_*.json` 到本地 `logs_dir`，然后合并所有匹配的文件。也可以同时手动指定额外的 log 文件，会按路径去重后一起合并。

未配置 `rclone_remote` 时，`--sync` 仅打印提示，不影响本地流程。

**批量处理：`--sync-all`**

`--sync-all` 从远端下载所有 log 文件，按日期分组，为每天启动独立子进程处理。已有报告的日期会自动跳过：

```bash
# 同步所有日期并逐天生成日报
python -m summarize daily merge --sync-all

# 同步所有 + 每天都部署到 Hugo
python -m summarize daily merge --sync-all --deploy

# 指定 API 和超时
python -m summarize daily merge --sync-all --api anthropic --timeout 300
```

每个子进程的超时时间根据 log 文件大小动态计算（每 150K chunk 使用 `--timeout` 指定的秒数）。

**并行加速：`--workers`**

`--sync-all` 默认顺序逐天处理。日期较多时可用 `--workers N` 开 N 个 worker 并行（基于 `ThreadPoolExecutor`，每个 worker 各自跑一个 `merge --sync` 子进程）：

```bash
# 4 个 worker 并行批量合并
python -m summarize daily merge --sync-all --workers 4
```

默认 `--workers 1`（顺序处理，保持原有行为），实际并行数会被裁剪到「待处理日期数」。该参数**仅对 `--sync-all` 批量合并生效**，单日期 merge 与 export 不受影响。每个 worker 是独立子进程，日志分别写到 `outputs/logs/summarize/merge_logs/`。`auto` 子命令也接受 `--workers N` 并透传给这一步。并发越高对 LLM 后端的瞬时请求越多——用 `claude_cli` 或有速率限制的 API 时不宜调太大。

**方式二：手动指定文件**

如果 log 文件已在本地（通过云盘 App 同步或手动拷贝），直接指定路径：

```bash
python -m summarize daily merge outputs/logs/summarize/2026-02-13_*.json
python -m summarize daily merge --api openai outputs/logs/summarize/*.json
```

输出在 `reports_dir`（默认 `outputs/reports/summarize/`）下：
- `2026-02-13.md` — Markdown 日报
- `2026-02-13.json` — 结构化数据

如果配置了 `rclone_remote`，报告会自动上传到 `<rclone_remote>/reports/`。

### 完整工作流示例

```bash
# 设备 A（macbook）:
python -m summarize daily export --date 2026-02-14
# → logs/2026-02-14_macbook.json → 自动上传到 gdrive:gadget/summarize/logs/

# 设备 B（desktop）:
python -m summarize daily export --date 2026-02-14
# → logs/2026-02-14_desktop.json → 自动上传到 gdrive:gadget/summarize/logs/

# 任意设备 merge:
python -m summarize daily merge --sync --date 2026-02-14
# → 从 gdrive:gadget/summarize/logs/ 下载 2026-02-14_*.json
# → 合并所有 log → 调 API 生成日报
# → 上传报告到 gdrive:gadget/summarize/reports/
```

## 全流程自动化（auto）

`auto` 子命令通过子进程串起完整管线：daily export → daily merge → weekly → monthly，一条命令覆盖日常总结。适合 cron / systemd timer 定时任务，或每天收工前手动触发。

### 基本用法

```bash
# 默认处理昨天（最常用；当天的对话通常尚未结束，所以聚合目标默认是昨天）
python -m summarize auto

# 处理 + 部署到 Hugo
python -m summarize auto --deploy

# 指定目标日期（周报取该日期所在 ISO 周，月报取该日期所在月）
python -m summarize auto --date 2026-04-18

# 指定 LLM 后端（传递给 merge / weekly / monthly）
python -m summarize auto --api anthropic
python -m summarize auto --api openai

# 强制重新生成（忽略缓存和已有输出，覆盖 daily / weekly / monthly）
python -m summarize auto --force

# 组合使用
python -m summarize auto --date 2026-04-18 --api anthropic --deploy --force
```

### 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `--date YYYY-MM-DD` | 昨天 | 聚合目标日期。决定周报取哪一周、月报取哪一月。**不影响** `daily export` / `merge --sync-all`，它们仍处理所有未导出 / 未 finalized 日期 |
| `--api {ollama,claude_cli,anthropic,openai}` | `ollama`（config `default_api` 可改） | LLM 后端，透传给所有调 LLM 的步骤 |
| `--deploy` | 关 | 对 merge / weekly / monthly 都追加 `--deploy`，把日报 / 周报 / 月报一并发布到 Hugo |
| `--force` | 关 | 对所有四步追加 `--force`，忽略缓存和已存在的输出文件，强制重跑 |

### 执行流程

`auto` 内部通过 `subprocess.run` 依次调起四个独立的子进程（见 `summarize/auto.py`）：

1. `python -m summarize daily export` — 扫描本机所有有对话的日期，跳过已导出的，逐日写入 `<logs_dir>/YYYY-MM-DD_<device>.json`。同时自动通过 ccusage 20.x 逐源采集 token 用量（发现来源后对每个来源跑 `ccusage <source> daily`，写入 `usage_<source>_<device>.json`）。若配置了 `rclone_remote` 则上传到 `<remote>/logs/`。
2. `python -m summarize daily merge --sync-all` — 从远端 `<remote>/logs/` 拉取所有设备的 log，按日期分组，为每天启动独立子进程合并成日报。已 finalized 的日期自动跳过。
3. `python -m summarize weekly generate --week <目标周>` — 目标周 = `--date`（或昨天）所在的 ISO 8601 周（周一至周日）。读取该周所有日报，调 LLM 产出 `<week>-weekly.{md,json}` 和 `<周一日期>-usage.png`。
4. `python -m summarize monthly generate --month <目标月>` — 目标月 = `--date`（或昨天）所在月。读取该月所有日报，产出 `<month>-monthly.{md,json}` 以及 `<month>-monthly-cost.png` / `<month>-monthly-tokens.png`。

每个子进程执行前会打印一段醒目的 banner：

```
============================================================
[auto] /path/to/python -m summarize daily merge --sync-all --deploy
============================================================
```

**任一步骤失败（非零退出码）不会中断后续步骤**，只打印 `[auto] exited <code>, continuing...`。这是有意的设计：例如某天因网络原因没能同步远端，后面的 weekly / monthly 仍可基于已有本地数据推进。完成所有步骤后输出 `[auto] Pipeline complete.`。

### 典型使用场景

**1. 每日定时任务（cron）** — 每晚 23:55 处理昨天的对话并部署：

```cron
55 23 * * * cd /path/to/gadget && /path/to/conda/envs/AI/bin/python -m summarize auto --deploy >> ~/logs/summarize-auto.log 2>&1
```

**2. 补跑历史日期** — 例如上周漏跑了周二：

```bash
python -m summarize auto --date 2026-04-14 --deploy
```

注意：`daily export` 和 `merge --sync-all` 会处理所有未完成日期（不只是 `--date`），因此即便本命令目的只是补周二的日报，也可能顺带把之前漏掉的若干天一起补上。周报 / 月报只会重算 `--date` 对应的那一周 / 那一月。

**3. 更换 API 或更新 prompt 后全量回刷** — 结合 `--force` 忽略缓存重新生成：

```bash
python -m summarize auto --date 2026-04-18 --api anthropic --force --deploy
```

### auto vs 分步执行

`auto` 不是必需的，完全等价于手动依次执行四条命令。选择：

- **用 `auto`**：希望一条命令兜住全部日常流程；对「任一步失败不阻断后续」的行为能接受。
- **分步执行**：需要细粒度控制（例如只重跑 weekly、手动指定 log 文件、交互式检查每一步输出、或各步使用不同 `--api`）。

### 常见问题

- **聚合目标为什么默认是昨天，不是今天？** 因为当天对话往往尚未结束，日报和 ccusage 统计都不完整。如确需处理当天，显式传 `--date $(date +%F)`。
- **`auto` 会上传到 rclone 吗？** `daily export` 和 `daily merge` 会按配置自动上传（与单独运行它们行为一致），`weekly` / `monthly` 的输出不会自动上传（需要 `--deploy` 触发 Hugo 部署流程）。
- **多设备环境下在哪台机器跑 `auto`？** 每台设备都需要跑 `daily export`（解析本地对话），而 `merge / weekly / monthly` 只需在一台中心机器上跑。多数情况下建议：所有设备各自跑 `daily export`（可用 cron），中心机器跑 `auto --deploy`（它的 daily export 相当于补跑 + merge 相当于汇总）。

## 云盘同步

多设备间传递 log/reports 文件，有两种云盘方案。

### 方式一：云盘 App 同步（有桌面环境的设备推荐）

将输出目录指向云盘同步文件夹，文件写入后由云盘 App 自动同步到所有设备。

在每台设备的仓库根 `config.json` 的 `summarize` 段中设置：

```json
{
  "device_name": "macbook",
  "logs_dir": "~/Google Drive/summarize/logs",
  "reports_dir": "~/Google Drive/summarize/reports"
}
```

这样所有设备的 export log 都写入同一个云盘目录，merge 时直接读取。

各云盘典型同步路径：

| 云盘 | macOS | Windows | Linux |
|------|-------|---------|-------|
| Google Drive | `~/Google Drive/` | `~/Google Drive/` | — (无官方客户端) |
| OneDrive | `~/OneDrive/` | `~/OneDrive/` | — |
| Dropbox | `~/Dropbox/` | `~/Dropbox/` | `~/Dropbox/` |
| iCloud | `~/Library/Mobile Documents/com~apple~CloudDocs/` | — | — |

> Linux headless server 通常没有云盘桌面客户端，推荐用方式二 rclone。

### 方式二：rclone（headless server 推荐）

[rclone](https://rclone.org/) 是命令行云盘工具，支持 40+ 种云存储（Google Drive、OneDrive、S3、...），不需要桌面环境，非常适合 headless server。

配置后，export 自动上传到 `<remote>/logs/`，merge 自动上传到 `<remote>/reports/`。merge 时可用 `--sync` 从 `<remote>/logs/` 拉取其他设备的 log。上传/下载失败只打 `[warn]`，不阻断主流程。

#### 1. 安装 rclone

**有 sudo 权限：**

```bash
# Linux/macOS
curl https://rclone.org/install.sh | sudo bash

# macOS (Homebrew)
brew install rclone

# Windows (Scoop)
scoop install rclone

# Windows (Chocolatey)
choco install rclone
```

**无 sudo 权限（headless server 常见）：**

直接下载二进制文件到用户目录：

```bash
# 下载并解压到 ~/.local/bin/
mkdir -p ~/.local/bin
curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip
unzip rclone-current-linux-amd64.zip
cp rclone-*-linux-amd64/rclone ~/.local/bin/
chmod +x ~/.local/bin/rclone
rm -rf rclone-*-linux-amd64*
```

如果 `~/.local/bin` 不在 PATH 中，在 config 中指定 `rclone_path`：

```json
{
  "rclone_path": "~/.local/bin/rclone",
  "rclone_remote": "gdrive:gadget/summarize"
}
```

程序会优先使用 `rclone_path` 指定的路径，找不到才从 PATH 中查找。

#### 2. 配置 remote

**有浏览器的设备：**

```bash
rclone config
```

按提示选择云盘类型、完成 OAuth 授权。

**headless server（无浏览器）：**

先在有浏览器的设备上获取 token：

```bash
rclone authorize "drive"     # Google Drive
rclone authorize "onedrive"  # OneDrive
```

浏览器弹出授权页面，完成后终端输出 token JSON。

然后在 server 上运行 `rclone config`，选择手动输入 token，粘贴上一步输出的 JSON。

#### 3. 启用自动上传

在仓库根 `config.json` 的 `summarize` 段中设置 `rclone_remote`：

```json
{
  "device_name": "linux-server",
  "rclone_remote": "gdrive:gadget/summarize"
}
```

`rclone_remote` 的格式是 `<remote名>:<路径>`，其中 remote 名是你在 `rclone config` 时设置的名称。

常见配置示例：

| 云盘 | rclone_remote 示例 |
|------|-------------------|
| Google Drive | `gdrive:gadget/summarize` |
| OneDrive | `onedrive:summarize` |
| Dropbox | `dropbox:summarize` |
| S3 | `s3:my-bucket/summarize` |

#### 4. 验证

```bash
# 查看配置是否生效（会显示 logs/reports 子路径）
python -m summarize daily config --show

# 手动测试 rclone 连通性
rclone ls gdrive:gadget/summarize/logs/
rclone ls gdrive:gadget/summarize/reports/
```

#### 混合使用

可以在桌面设备用云盘 App（设 `logs_dir` 指向同步目录），在 server 上用 rclone（设 `rclone_remote`），两者最终文件到同一个云盘目录，互不冲突。

> **提示**：使用 rclone 时，export 上传到 `<remote>/logs/`，merge 上传到 `<remote>/reports/`。如果你之前使用的是 flat 目录结构（没有 logs/reports 子目录），已有文件不受影响，新文件会自动上传到对应子目录。

## 周报

积累一周的日报后，可以生成 ISO 周报（周一至周日）。

### 查看可用周

```bash
python -m summarize weekly list
```

输出示例：

```
周              日报数    已有周报
----------------------------------
2026-W12         5    ✅
2026-W11         7
2026-W10         6

共 3 周, 18 份日报
```

### 生成周报

```bash
# 生成指定周
python -m summarize weekly generate --week 2026-W12

# 默认上一周
python -m summarize weekly generate

# 生成 + 部署到 Hugo
python -m summarize weekly generate --week 2026-W12 --deploy

# 选择 API 后端
python -m summarize weekly generate --week 2026-W12 --api anthropic
```

生成文件（默认在 `outputs/reports/summarize/` 下）：
- `2026-W12-weekly.md` — Markdown 周报
- `2026-W12-weekly.json` — 结构化 JSON

图表（在 `outputs/images/summarize/` 下，需要 matplotlib）：
- `<周一日期>-usage.png` — 三子图 PNG（Tokens / Cost / Cache 分平台对比）

### 缓存机制

与月度总结相同，LLM 调用结果按源日报哈希缓存在 `outputs/cache/summarize/weekly/`。

```bash
# 跳过 LLM 缓存，强制重新调 API
python -m summarize weekly generate --week 2026-W12 --no-cache
```

## 月度总结

积累一个月的日报后，可以生成月度趋势总结。

### 查看可用月份

```bash
python -m summarize monthly list
```

输出示例：

```
月份              日报数      已有月报
----------------------------------
2026-02          22    ✅
2026-03           3

共 2 个月, 25 份日报
```

### 生成月度总结

```bash
# 生成指定月份的总结
python -m summarize monthly generate --month 2026-02

# 默认生成上个月
python -m summarize monthly generate

# 选择 API 后端（与日报相同的四种后端）
python -m summarize monthly generate --month 2026-02 --api anthropic
python -m summarize monthly generate --month 2026-02 --api openai
```

生成文件（默认在 `outputs/reports/summarize/` 下）：
- `2026-02-monthly.md` — Markdown 月度报告
- `2026-02-monthly.json` — 结构化 JSON

图表（在 `outputs/images/summarize/` 下，需要 matplotlib）：
- `2026-02-monthly-cost.png` — 每日费用趋势柱状图
- `2026-02-monthly-tokens.png` — 每日 Token 趋势柱状图

### 工作原理

月度总结分两部分：

1. **LLM 分析**（需调 API）— 读取所有日报 JSON，剥离 `token_usage` 和 `conversation_summaries` 字段（这些机械聚合），将剩余内容格式化后发给 LLM 分析趋势。如果内容超过 150K 字符，自动按周分组分段总结再合并
2. **机械聚合**（纯本地计算）— 汇总 token 用量（总量、日均、峰值、模型分布）和统计数据（活跃天数、对话数、任务数、项目数）

### 缓存机制

LLM 调用结果缓存在 `outputs/cache/summarize/monthly/YYYY-MM.json`，缓存键为所有源日报文件的 SHA-256 哈希。任一日报更新后缓存自动失效。

```bash
# 跳过 LLM 缓存，强制重新调 API
python -m summarize monthly generate --month 2026-02 --no-cache

# 忽略已有输出文件，强制重新生成
python -m summarize monthly generate --month 2026-02 --force
```

### 月度总结 + Hugo 部署

```bash
python -m summarize monthly generate --month 2026-02 --deploy
```

这会：
1. 生成月度报告
2. 将 Markdown 发布到 Hugo `content/bugJournal/2026-02-monthly.md`（日期设为月末最后一天 23:59，排在所有日报之后）
3. 将趋势图复制到 Hugo `static/images/monthly/`
4. 执行 `update.sh` 构建并推送

## 图表

所有图表通过 `charts.py` 生成，需要 `pip install matplotlib`（可选，未安装时跳过图表不影响报告生成）。

### 日报/周报图表

每份日报和周报生成一张三子图 PNG（`<date>-usage.png`）：

| 子图 | X 轴 | Y 轴 | 说明 |
|------|------|------|------|
| Tokens | 平台 (Claude Code / Codex) | Token 数 | 按模型堆叠 |
| Cost | 平台 | 费用 ($) | 按模型堆叠 |
| Cache | 平台 | Token 数 | 按类型堆叠 (input/output/cache) |

输出到 `outputs/images/summarize/`。

### 月度图表

月度报告生成两张独立图表：
- **费用趋势图** (`<month>-monthly-cost.png`) — X 轴为日期，按模型堆叠的费用柱状图
- **Token 趋势图** (`<month>-monthly-tokens.png`) — X 轴为日期，按 token 类型堆叠的柱状图

## Hugo 博客部署

### merge 时部署

merge 时加 `--deploy` 可以自动将日报发布到 Hugo 站点：

```bash
python -m summarize daily merge --sync --date 2026-02-13 --deploy
python -m summarize daily merge --deploy outputs/logs/summarize/2026-02-13_*.json
```

这会：
1. 在 `<hugo-site>/content/bugJournal/2026-02-13.md` 生成带 frontmatter 的文章
2. 将日报图表复制到 `<hugo-site>/static/images/daily/`
3. 执行 `<hugo-site>/update.sh` 构建并推送到 GitHub Pages

Hugo 站点路径默认是 `<项目根目录>/website`（动态计算），可以通过 `--hugo-site` 修改：

```bash
python -m summarize daily merge --deploy --hugo-site /path/to/hugo/site outputs/logs/summarize/*.json
```

### 批量部署（deploy 子命令）

使用独立的 `deploy` 子命令可以将 `reports/` 目录下已有的报告批量部署到 Hugo，无需重新调 API：

```bash
# 部署所有报告
python -m summarize daily deploy

# 部署指定日期
python -m summarize daily deploy --date 2026-02-13

# 指定 Hugo 站点路径和报告目录
python -m summarize daily deploy --hugo-site /path/to/site --reports-dir /path/to/reports
```

`deploy` 会遍历所有 `.md` 报告文件，为每个文件生成 Hugo 文章，最后执行一次 `update.sh` 统一构建推送。加 `--force` 可强制重新部署已有文章。

## 支持的对话来源

| 来源 | 说明 | 自动扫描 |
|------|------|----------|
| Claude Code | 读取 `~/.claude/projects/` 下的 `.jsonl` 文件 | 是 |
| Codex | 读取 `~/.codex/sessions/` 下的会话目录 | 是 |
| Cursor Agent | 读取 `~/.cursor/projects/*/agent-transcripts/<uuid>/<uuid>.jsonl`（仅 parent；无 token usage） | 是 |
| ChatGPT | ChatGPT 导出的 `conversations.json` | 否，需 `--chatgpt` 指定 |
| 通用格式 | `[{"role": "user", "content": "..."}]` 的 JSON 数组 | 否，需 `--generic` 指定 |

> **WSL 支持**：在 WSL 中运行时，Claude/Codex 的数据通常写在 Windows 用户目录而非 Linux home。检测到 WSL（内核含 `microsoft`）后会额外扫描 `/mnt/c/Users/*` 下的 `.claude*/projects/` 与 `.codex/sessions/`，无需配置。（假设 C 盘挂在 `/mnt/c`。）

## 日报内容

生成的日报包含以下部分：

- **一句话总结** — 今日工作概要
- **每日概览** — what / how / impact 三句话概括
- **任务列表** — 各任务的名称、状态（完成/进行中/阻塞）、描述
- **问题与解决方案** — 遇到的问题、解决方案、关键洞察
- **人类 vs AI 思路对比** — 人类和 AI 各自的思路差异分析
- **AI 局限性** — AI 在交互中表现出的不足
- **今日收获** — 关键学习点
- **Token 用量** — Claude Code / Codex 分开统计的 token 数和费用明细
- **用量图表** — 三子图 PNG（Tokens / Cost / Cache，需 matplotlib）

## `--api` 参数说明

所有需要 AI 总结的命令（`export --summarize`、`merge`、`weekly generate`、`monthly generate`、`auto`）都支持 `--api` 参数：

| 值 | 说明 | 是否需要 API key |
|----|------|-----------------|
| `ollama` | 调用本地 Ollama 服务（默认，Gemma4-26B） | 否，本地 keyless |
| `claude_cli` | 调用本地 Claude Code CLI | 否，复用 CLI 登录状态 |
| `anthropic` | 调用 Anthropic Claude API | 是，需 `ANTHROPIC_API_KEY` |
| `openai` | 调用 OpenAI API | 是，需 `OPENAI_API_KEY` |

默认后端可用 `GADGET_LLM_BACKEND` 环境变量或 config 的 `default_api` 覆盖。

`claude_cli` 模式通过 `claude --print` 将 prompt 传给 Claude Code CLI。需要提前安装并登录 Claude Code。

### `--timeout` 参数

所有 LLM 调用命令（`export --summarize`、`merge`）支持 `--timeout` 控制每 150K chunk 的超时秒数：

```bash
# 默认 600 秒
python -m summarize daily merge --sync --date 2026-02-13

# 自定义超时
python -m summarize daily merge --sync --date 2026-02-13 --timeout 300
python -m summarize daily export --summarize --date 2026-02-13 --timeout 900
```

## 运行测试

```bash
# 运行所有测试
python -m pytest tools/summarize/tests/ -v

# 仅运行导入契约测试（重构后必跑，验证所有外部导入路径）
python -m pytest tools/summarize/tests/test_imports.py -v

# 运行单个测试文件
python -m pytest tools/summarize/tests/test_config.py -v
python -m pytest tools/summarize/tests/test_parsers.py -v
python -m pytest tools/summarize/tests/test_formatter.py -v
python -m pytest tools/summarize/tests/test_summarizer.py -v
```

## 常用命令速查

```bash
# ── 配置 ──
python -m summarize daily config --init    # 交互式创建配置
python -m summarize daily config --show    # 查看当前配置

# ── Phase 1: 导出 ──
python -m summarize daily export                                # 导出所有未导出日期
python -m summarize daily export --date 2026-02-13              # 导出指定日期
python -m summarize daily export --date 2026-02-13 --summarize  # 导出 + 单设备 AI 总结

# ── Phase 2: 合并 ──
python -m summarize daily merge --sync --date 2026-02-13            # 从远端同步 log 后合并
python -m summarize daily merge --sync --date 2026-02-13 --deploy   # 同步 + 合并 + Hugo 部署
python -m summarize daily merge --sync-all                          # 批量同步所有日期并逐天处理
python -m summarize daily merge --sync-all --deploy                 # 批量同步 + 部署
python -m summarize daily merge outputs/logs/summarize/2026-02-13_*.json  # 手动指定 log 文件

# ── 批量部署（不重跑 LLM） ──
python -m summarize daily deploy                          # 部署所有日报到 Hugo
python -m summarize daily deploy --date 2026-02-13        # 部署指定日期
python -m summarize weekly deploy                         # 回放部署已保存周报
python -m summarize monthly deploy --month 2026-02        # 回放部署指定月报

# ── 全流程自动化 ──
python -m summarize auto                                  # 一键运行: export → merge → weekly → monthly
python -m summarize auto --deploy                         # 全流程 + Hugo 部署
python -m summarize auto --date 2026-04-18 --deploy       # 指定目标日期

# ── 周报 ──
python -m summarize weekly list                               # 查看可用周
python -m summarize weekly generate --week 2026-W12           # 生成指定周
python -m summarize weekly generate                           # 默认上一周
python -m summarize weekly generate --week 2026-W12 --deploy  # 生成 + Hugo 部署

# ── 月度总结 ──
python -m summarize monthly list                              # 查看可用月份
python -m summarize monthly generate --month 2026-02          # 生成指定月份
python -m summarize monthly generate                          # 默认上个月
python -m summarize monthly generate --month 2026-02 --deploy # 生成 + Hugo 部署
python -m summarize monthly generate --month 2026-02 --no-cache  # 跳过 LLM 缓存
python -m summarize monthly generate --month 2026-02 --force     # 忽略已有输出

# ── 运行测试 ──
python -m pytest tools/summarize/tests/ -v                          # 运行所有测试
python -m pytest tools/summarize/tests/test_imports.py -v           # 导入契约测试
```
