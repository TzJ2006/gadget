# Summarize — AI 对话日报 & 月度总结

自动读取每天与 AI 的对话记录（Claude Code / Codex / ChatGPT / 通用 JSON），调用 LLM API 生成结构化日报和月度总结。

支持多设备工作流：在每台设备上导出对话 log，通过云盘同步或手动拷贝汇总，生成最终日报。同时通过 [ccusage](https://github.com/ryoppippi/ccusage) 20.x 的逐源命名空间命令（`ccusage <source> daily`）自动发现并统计所有 agent CLI（Claude Code / Codex / Gemini 等）的 token 用量和费用。

## 架构总览

```
设备 A ──export──→ outputs/logs/summarize/2026-02-13_macbook.json  ─┐
设备 B ──export──→ outputs/logs/summarize/2026-02-13_office-pc.json ─┼──merge──→ outputs/reports/summarize/2026-02-13.md
设备 C ──export──→ outputs/logs/summarize/2026-02-13_server.json   ─┘           outputs/reports/summarize/2026-02-13.json
                                                          ↕                         │
                                                    云盘自动同步                      ↓
                                               (rclone / Google Drive)             monthly
                                                                                    ↓
                                                          outputs/reports/summarize/2026-02-monthly.md
                                                          outputs/reports/summarize/2026-02-monthly.json
                                                          outputs/reports/summarize/2026-02-monthly-tokens.png
```

### 日报流程 (`daily_summary.py`)

- **export** (Phase 1) — 各设备本地运行，解析对话并导出为可移植 JSON log，不需要 API key。不带 `--date` 时自动导出所有未导出日期
- **merge** (Phase 2) — 收集所有设备的 log 文件，调 API 生成最终汇总日报。支持 `--sync` 自动从 rclone 远端拉取 log，`--sync-all` 批量处理所有日期
- **deploy** — 批量将已有报告部署到 Hugo 站点（独立于 merge）
- **config** — 配置管理（`--init` 交互式创建，`--show` 查看当前配置）

无子命令时默认执行 export（仅导出，不调 API）。

### 周报流程 (`weekly_summary.py`)

- **generate** — 读取一周的日报 JSON，调 LLM 分析趋势，生成结构化周报（ISO 8601 周一至周日）
- **list** — 列出可用周及日报数量

### 月度流程 (`monthly_summary.py`)

- **generate** — 读取一个月的所有日报 JSON，调 LLM 分析趋势和模式，生成结构化月度总结
- **list** — 列出可用月份及日报数量

### 全流程自动化 (`auto.py`)

一键运行完整管线：daily export → daily merge → weekly → monthly。适合定时任务或日常一键总结。

```bash
python -m summarize auto                    # 默认处理昨天
python -m summarize auto --deploy           # 全流程 + Hugo 部署
python -m summarize auto --date 2026-04-18  # 指定目标日期
python -m summarize auto --force            # 强制重新生成
```

### Onboarding / readiness check

`auto` 会在真正执行 export / merge / weekly / monthly 之前先检查运行条件。
如果缺少必需项（例如 `rclone_remote`、`rclone`、所选 LLM 后端的依赖
（如 `--api claude_cli` 需要 `claude` CLI），或 `--deploy` 需要的 Hugo 站点/二进制），命令会停止并给出修复步骤，
避免跑到一半才失败。

```bash
python -m summarize onboard                 # 检查 summarize auto 所需条件
python -m summarize onboard --init-config   # 交互式创建仓库内 tools/summarize/config.json
python -m summarize onboard --deploy        # 同时检查 Hugo 部署要求
python -m summarize auto                    # 自动先运行 readiness check
python -m summarize auto --skip-onboard-check  # 仅在明确要跳过检查时使用
```

## 依赖

```bash
pip install -r tools/summarize/requirements.txt
```

AI 总结后端四选一（默认 Ollama，可用 `GADGET_LLM_BACKEND` 或 config `default_api` 改默认）：

| 后端 | 安装 | 需要 API key |
|------|------|-------------|
| Ollama（默认，本地） | 本地 Ollama 服务（Qwen3.6-35B）+ `pip install openai` | 否 |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` | 否 |
| Anthropic API | `pip install anthropic` | 是 |
| OpenAI API | `pip install openai` | 是 |

Token 统计（可选，需要 Node.js）：ccusage 20.x 一个工具即覆盖所有 agent CLI。
- 全部来源：`npx ccusage@latest --help`
- 单来源（命名空间）：`npx ccusage@latest claude|codex|gemini daily --help`

> 缺失或低于 20.x 时会静默尝试 `npm install -g ccusage@latest`，失败则回退 npx。

月度图表（可选）：`pip install matplotlib`

## 快速开始

```bash
# 首次使用：配置设备别名和输出路径（可选但推荐）
python tools/summarize/daily_summary.py config --init

# Phase 1: 导出（不需要 API key）
python tools/summarize/daily_summary.py export                          # 导出所有未导出日期（默认行为）
python tools/summarize/daily_summary.py export --date 2026-02-13        # 导出指定日期
python tools/summarize/daily_summary.py --date 2026-02-13               # 等同于 export --date

# Phase 2: 合并生成日报
python tools/summarize/daily_summary.py merge --sync --date 2026-02-13  # 从远端同步 log 后合并
python tools/summarize/daily_summary.py merge --sync-all                # 同步所有日期，批量处理
python tools/summarize/daily_summary.py merge outputs/logs/summarize/2026-02-13_*.json  # 手动指定文件

# 批量部署报告到 Hugo
python tools/summarize/daily_summary.py deploy                          # 部署所有报告
python tools/summarize/daily_summary.py deploy --date 2026-02-13        # 部署指定日期

# 月度总结
python tools/summarize/monthly_summary.py list                              # 查看可用月份
python tools/summarize/monthly_summary.py generate --month 2026-02          # 生成月度总结
python tools/summarize/monthly_summary.py generate --month 2026-02 --deploy # 生成 + Hugo 部署
python tools/summarize/monthly_summary.py generate                          # 默认上个月

# 全流程自动化（推荐）
python -m summarize auto --deploy                                     # 一键: export → merge → weekly → monthly + 部署
python -m summarize auto --date 2026-04-18                            # 指定目标日期

# 首次或换新机器时检查依赖
python -m summarize onboard --deploy
python -m summarize onboard --init-config
```

## 配置文件

通过 summarize 配置文件设置设备别名、输出路径和云盘同步。解析顺序：`SUMMARIZE_CONFIG` 环境变量（显式路径）> 仓库内 `tools/summarize/config.json`（`config --init` 写入这里，gitignored，模板 `config.example.json`）> 旧版 `~/.config/summarize/config.json`：

```bash
python tools/summarize/daily_summary.py config --init   # 交互式创建
python tools/summarize/daily_summary.py config --show   # 查看当前配置
```

```json
{
  "device_name": "home-server",
  "logs_dir": "~/Google Drive/summarize/logs",
  "reports_dir": "~/Google Drive/summarize/reports",
  "rclone_remote": "gdrive:gadget/summarize"
}
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `device_name` | 设备别名，用于 export 文件名（如 `2026-02-13_home-server.json`） | 系统主机名 |
| `logs_dir` | logs 输出目录，支持 `~`，可指向云盘同步目录 | `outputs/logs/summarize/` |
| `reports_dir` | reports 输出目录，支持 `~` | `outputs/reports/summarize/` |
| `rclone_remote` | rclone 远端路径，export 上传到 `<remote>/logs/`，merge 上传到 `<remote>/reports/` | （不上传） |
| `rclone_path` | rclone 二进制路径，支持 `~`（无 sudo 时手动指定） | 从 PATH 查找 |

输出路径优先级：`--output` CLI 参数 > 环境变量 (`SUMMARIZE_LOGS_DIR` / `SUMMARIZE_REPORTS_DIR`) > config.json > 默认路径。

## 云盘同步

支持两种方式，解决多设备间 log 文件传输问题：

- **云盘 App**（有桌面环境的设备）— 将 `logs_dir`/`reports_dir` 指向云盘同步目录，文件写入后自动同步
- **rclone**（headless server 推荐）— 设置 `rclone_remote`，export 上传到 `<remote>/logs/`，merge 上传到 `<remote>/reports/`。merge 时使用 `--sync` 自动从远端拉取所有设备的 log

```bash
# 设备 A / B 各自 export（自动上传到 remote/logs/）
python tools/summarize/daily_summary.py export --date 2026-02-13

# 任意设备 merge（--sync 自动从远端下载 log）
python tools/summarize/daily_summary.py merge --sync --date 2026-02-13
python tools/summarize/daily_summary.py merge --sync --date 2026-02-13 --deploy
```

详见 [tutorial.md](tutorial.md) 中的「云盘同步」章节。

## 图表

所有图表通过 `charts.py` 生成（需要 `pip install matplotlib`，可选）。

- **日报/周报图表** (`<date>-usage.png`)：三子图 PNG — Tokens（按平台×模型堆叠）/ Cost / Cache
- **月度图表**：`<month>-monthly-cost.png`（费用趋势）、`<month>-monthly-tokens.png`（Token 趋势）
- 输出到 `outputs/images/summarize/`

## 日报内容

| 章节 | 内容 |
|------|------|
| 一句话总结 | 今日工作概要 |
| 任务列表 | 名称、状态（完成/进行中/阻塞）、描述 |
| 问题与解决方案 | 遇到的问题、解决方案、关键洞察 |
| 人类 vs AI 思路对比 | 双方思路及差异分析 |
| AI 局限性 | AI 在交互中的不足 |
| 今日收获 | 关键学习点 |
| Token 用量 | Claude Code / Codex 分开统计的 token 数和费用明细 |

## 月度总结内容

`monthly_summary.py` 读取一个月的所有日报 JSON，由 LLM 综合分析趋势，同时机械聚合 token 用量和统计数据。

| 章节 | 内容 | 来源 |
|------|------|------|
| 本月概览 | 活跃天数、总对话数、项目数、Token 总量、总费用 | 机械聚合 |
| 项目进展 | 各项目活跃天数、关键里程碑、状态 | LLM 分析 |
| 本月关键成就 | 全月最重要的 5-10 项成就 | LLM 分析 |
| 反复出现的问题 | 多天重复出现的问题模式、根本原因、解决状态 | LLM 分析 |
| 人机协作趋势 | AI 局限性模式、改进方向 | LLM 分析 |
| 本月收获精选 | 按类别（架构/调试/工具/领域）分组的收获 | LLM 分析 |
| Token 用量统计 | Claude Code / Codex 月度汇总、每日费用趋势图 (matplotlib)、模型分布表 | 机械聚合 |

输出文件（默认在 `outputs/reports/summarize/` 下）：
- `YYYY-MM-monthly.md` — Markdown 月度报告
- `YYYY-MM-monthly.json` — 结构化 JSON 数据
- `YYYY-MM-monthly-tokens.png` — 每日 Token/费用趋势双轴折线图

缓存机制：LLM 结果缓存在 `outputs/cache/summarize/monthly/`，基于所有源日报的 SHA-256 哈希，任一日报变更即自动失效。`--no-cache` 跳过缓存，`--force` 忽略已有输出。

## 对话来源

| 来源 | 说明 | 自动扫描 |
|------|------|----------|
| Claude Code | `~/.claude/projects/` 下的 `.jsonl` | 是 |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | 是 |
| ChatGPT | 导出的 `conversations.json` | 否，需 `--chatgpt` |
| 通用格式 | `[{"role": "...", "content": "..."}]` | 否，需 `--generic` |

## Hugo 部署

### merge 时部署

merge 时加 `--deploy` 会将日报发布为 Hugo bugJournal 文章并执行站点构建推送：

```bash
python tools/summarize/daily_summary.py merge --deploy --hugo-site /path/to/site outputs/logs/summarize/*.json
```

### 批量部署

使用独立的 `deploy` 子命令可以将已有报告批量部署到 Hugo，无需重新调 API：

```bash
python tools/summarize/daily_summary.py deploy                                    # 部署所有报告
python tools/summarize/daily_summary.py deploy --date 2026-02-13                  # 部署指定日期
python tools/summarize/daily_summary.py deploy --hugo-site /path/to/site          # 指定 Hugo 站点路径
python tools/summarize/daily_summary.py deploy --reports-dir /path/to/reports     # 指定报告目录
python tools/summarize/daily_summary.py deploy --force                            # 强制重新部署
```

### 月度总结部署

`monthly_summary.py generate --deploy` 会将月度报告和 token 趋势图一并发布到 Hugo：

```bash
python tools/summarize/monthly_summary.py generate --month 2026-02 --deploy
python tools/summarize/monthly_summary.py generate --month 2026-02 --deploy --hugo-site /path/to/site
```

发布内容：
- `content/bugJournal/YYYY-MM-monthly.md` — 月度总结文章（日期设为月末，排在所有日报之后）
- `static/images/monthly/YYYY-MM-monthly-tokens.png` — Token 趋势图

## 详细教程

参见 [tutorial.md](tutorial.md)。
