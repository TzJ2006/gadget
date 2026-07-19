# Gadgets

> 详细教程见 [TUTORIAL.zh.md](TUTORIAL.zh.md) · English version: [../README.md](../README.md)

日常开发中积累的实用工具集，涵盖 AI 日报生成、论文发现、性能测试、博客自动化和文档翻译。

`tools/` 下每个目录是一个独立工具，可以单独使用。共享基础设施统一放在根目录的 `common/` 包中（通过 `pip install -e .` 安装），提供 LLM 调用、JSON 解析、磁盘缓存、原子写入、翻译与 Hugo 部署等通用能力。开发工作流（规划 / 执行 / 变更追踪）和所有 Claude Code skills 由 **ai-companion** 提供——它是一个独立仓库（`git@github.com:TzJ2006/ai-companion.git`），检出在同级目录 `../ai-companion/`，通过 hooks 接入本仓库。

本文是面向全部工具的**简介**；每个工具的分步操作、配置、数据格式与常见问题，请见 [TUTORIAL.zh.md](TUTORIAL.zh.md) 与各工具自带的源文档。

## 目录

- [仓库结构](#仓库结构)
- [工具一览](#工具一览)
- [各工具简介](#各工具简介)
  - [Summarize — AI 对话日报/周报/月报](#summarize--ai-对话日报周报月报)
  - [Research — 论文发现与学者分析](#research--论文发现与学者分析)
  - [Benchmark — 性能测试套件](#benchmark--性能测试套件)
  - [Website — Hugo 博客](#website--hugo-博客)
  - [Translator — Gradio 文档翻译器](#translator--gradio-文档翻译器)
- [common / scripts / ai-companion](#common--scripts--ai-companion)
  - [common/ — 共享基础设施包](#common--共享基础设施包)
  - [scripts/ — 运维与维护脚本](#scripts--运维与维护脚本)
  - [AI Companion — 独立仓库](#ai-companion--独立仓库)
  - [新服务器 Onboarding](#新服务器-onboarding)
- [输出目录](#输出目录)
- [环境要求](#环境要求)
- [注意事项](#注意事项)

## 仓库结构

```text
gadget/
├── tools/              # 五个独立工具产品（要改某个工具，进这里）
│   ├── summarize/      # AI 对话日报 / 周报 / 月报
│   ├── research/       # 论文发现 + 学者分析 + 引用图谱
│   ├── benchmark/      # CPU/GPU 性能测试
│   ├── website/        # Hugo 博客（增量媒体压缩 + 自动构建发布）
│   └── translator/     # Gradio 文档翻译器
├── common/             # 共享基础设施包（LLM / 缓存 / IO / 翻译 / Hugo）——被所有工具依赖
├── scripts/            # 运维 + 维护脚本（sync.py、onboard.py、profile_translation.py、内容语言审计…）
├── docs/               # 设计文档、ECL 计划（docs/ecl/）、审计报告、历史归档（docs/archive/）
├── outputs/            # 所有生成产物（gitignore，可自动重建）
├── AGENTS.md           # 所有 AI agent 的工作流协议（动手前先读）
├── CLAUDE.md           # 给 Claude Code 的仓库指南
└── pyproject.toml      # common/ + 各工具的打包配置（pip install -e .）
```

> 开发工作流引擎与所有 skills 在独立仓库 **ai-companion**（同级 `../ai-companion/`），不在本仓库内；通过 `.claude/`、`.codex/` 的 hooks 接入。`build/` 与 `gadget.egg-info/` 是 `pip install -e .` 的生成物（已 gitignore，始终位于根目录）。数据同步运行 `python scripts/sync.py`。

**想改东西，看这里：**

| 想做的事 | 去哪儿 |
|----------|--------|
| 改某个工具的逻辑 | `tools/<tool>/` |
| 改共享能力（LLM / 缓存 / 翻译 / Hugo 部署） | `common/` |
| 改数据同步 | `scripts/sync.py` |
| 一次性配置新机器 | `scripts/onboard.py` |
| 改开发工作流 / skill | **ai-companion** 仓库（同级 `../ai-companion/`） |
| 看计划 / 设计文档 | `docs/ecl/`、`docs/` |

## 工具一览

| 目录 | 功能 | 主要技术 |
|------|------|----------|
| [**tools/summarize/**](../tools/summarize/) | AI 对话日报/周报/月报总结（多设备两阶段架构） | Claude/OpenAI API, ccusage 20.x（统一多来源）, matplotlib |
| [**tools/research/**](../tools/research/) | 论文发现 + 学者分析 + 引用图谱 | arXiv/bioRxiv/PubMed, Semantic Scholar, LLM |
| [**tools/benchmark/**](../tools/benchmark/) | CPU/GPU 跨平台性能测试 | PyTorch, NumPy, Plotly |
| [**tools/website/**](../tools/website/) | Hugo 博客站点（增量媒体压缩 + 自动构建发布） | Hugo, pngquant, HandBrakeCLI |
| [**tools/translator/**](../tools/translator/) | Gradio 文档翻译器（基于 common 翻译引擎） | Gradio, GGUF/transformers |
| [**common/**](../common/) | 共享基础设施包（LLM、缓存、IO、翻译、Hugo 部署） | pip install -e . |
| [**scripts/**](../scripts/) | 运维 + 维护脚本（`sync.py` rclone 同步、`onboard.py` 机器配置等） | rclone, Python |
| **../ai-companion/**（独立仓库） | AI 代码变更追踪 + 规划/执行 skill 流水线 + 全部 skills | Node.js, TypeScript |

## 各工具简介

### Summarize — AI 对话日报/周报/月报

自动读取你每天与 AI 的对话记录（Claude Code / Codex / Cursor Agent / ChatGPT / 通用 JSON），调用 LLM API 生成结构化日报、周报和月度总结。多设备工作流：在每台设备上导出对话 log，通过云盘同步或手动拷贝汇总，生成最终日报；积累足够日报后可继续生成周报和月度趋势总结。通过 [ccusage](https://github.com/ryoppippi/ccusage) 20.x 的逐源命名空间命令（`ccusage claude`、`ccusage codex`、`ccusage gemini`…）自动发现并统计所有 agent CLI 的 token 用量和费用。AI 总结后端四选一，统一通过 `--api` 切换：`ollama`（默认——本地 Ollama，无需 key，Qwen3.6-35B）、`claude_cli`（复用 Claude Code CLI 登录态，无需 API key）、`anthropic`、`openai`。

```bash
python -m summarize daily export                                   # Phase 1: 导出所有未导出日期
python -m summarize daily merge --sync-all                         # Phase 2: 批量同步所有日期并逐天合并
python -m summarize weekly generate --week 2026-W12 --deploy       # 周报 + 部署
python -m summarize monthly generate --month 2026-02 --deploy      # 月报 + 部署
python -m summarize auto --deploy                                  # 全流程一键 export → merge → weekly → monthly + 部署
```

> 旧入口 `python tools/summarize/daily_summary.py ...` / `weekly_summary.py` / `monthly_summary.py` 仍可用（向后兼容 re-export shim），推荐使用上面的 `python -m summarize` 新形式。

详细分步操作见 [TUTORIAL.zh.md — Summarize](TUTORIAL.zh.md#summarize) 与源文档 [tools/summarize/tutorial.md](../tools/summarize/tutorial.md)。

### Research — 论文发现与学者分析

统一的学术研究工具包，通过单一 CLI 入口 `tools/research/research_scout.py` 提供四大功能：

- **论文发现**：从 arXiv / bioRxiv / PubMed 搜索论文，三阶段 LLM 管线（快速筛选 → 深度分析 → 引用影响），生成研究周报并部署到 Hugo。支持会议论文搜索和作者搜索。
- **论文深度洞察（`--insight`）**：下载论文全文，LLM 分析写作结构、发表策略、可复用核心知识；自动匹配 OpenReview 获取审稿意见并分析共识与争议；跨论文综合生成研究写作指南。
- **研究者画像**：从 ArXiv + Semantic Scholar 获取论文和引用数据，LLM 生成研究轨迹分析，计算 tier 评分，通过主页提取 + 共著模式自动发现师生关系。支持同名消歧和反向查找。
- **引用图分析**：基于 Semantic Scholar API 的前向引用 / 反向参考文献分析，配合 LLM 影响力解读。

```bash
python tools/research/research_scout.py report --project my-project        # 完整流水线：搜索 → 三阶段评估 → 报告
python tools/research/research_scout.py ask "找 Pieter Abbeel 最近的机器人操作论文"  # 自然语言搜索（自动路由来源）
python tools/research/research_scout.py profile "Sergey Levine"             # 研究者画像
python tools/research/research_scout.py citations 2301.12597               # 引用图谱（按 arXiv ID / DOI）
python tools/research/research_scout.py deploy                              # 部署报告到 Hugo
```

所有 LLM 功能支持 `--api` 切换后端：`ollama`（默认——本地 Ollama，无需 key，Qwen3.6-35B）、`claude_cli`（无需 API key）、`anthropic`、`openai`。

详细分步操作见 [TUTORIAL.zh.md — Research](TUTORIAL.zh.md#research) 与源文档 [tools/research/TUTORIAL.md](../tools/research/TUTORIAL.md)。

### Benchmark — 性能测试套件

跨平台 CPU/GPU FLOPS 基准测试工具：在不同硬件厂商与精度档位上统一测量浮点性能。实际跑分支持 NVIDIA (CUDA)、Apple Silicon (MPS)、Intel (XPU)（`--info` 可能检测到 OpenCL，但 `gpu.py` 不跑 OpenCL），覆盖 FP64 / FP32 / FP16 / BF16 / FP8(实验性) 等精度。测量采用预热 + 正式测量 + 统计分析（中位数、IQR 剔除异常值），GPU 显式同步保证计时准确。结果以追加模式累积到 CSV（永不覆盖，天然支持多硬件累积排行），并可生成带 Plotly 图表的交互式 HTML 报告与排行榜，还支持部署到 Hugo 网站、提交到公共排行榜。

```bash
# 注意：所有命令需先 cd 进 tools/benchmark/
cd tools/benchmark
python -m benchmark.cli                # 运行全部测试（结果追加到 CSV）
python -m benchmark.cli --cpu-only     # 仅 CPU
python -m benchmark.cli --gpu-only     # 仅 GPU
python -m benchmark.cli --report       # 运行测试并生成 HTML 报告
python -m benchmark.cli --report --deploy  # 生成报告并发布到 Hugo /benchmark/
```

详细分步操作见 [TUTORIAL.zh.md — Benchmark](TUTORIAL.zh.md#benchmark) 与源文档 [tools/benchmark/tutorial.md](../tools/benchmark/tutorial.md)。

### Website — Hugo 博客

Hugo 静态博客站点（"TzJ's Net"，PaperMod 主题），部署到 GitHub Pages（`https://tzj2006.github.io/`）。内置增量图片/视频压缩流水线（仅压缩自 `.last_build` 以来变更的媒体：图片走 pngquant，视频走 HandBrakeCLI）和本地模型双语翻译（默认 Ollama，Linux 兜底 vLLM、Windows 兜底 transformers，模型 `tencent/Hy-MT2-1.8B` 首次运行自动下载，不走云端 LLM API）。自动生成的内容（日报/周报/月报、研究报告、benchmark 页面、图片）由部署管线直接写入 `tools/website/content|static`（单一内容根，文件带 `gadget_generated` 标记，与手写内容共存；无 gadget 标记的手写文件管线绝不覆盖），构建时翻译、压缩、构建并推送。`tools/website/public/` 是一个**独立的**部署仓库（`tzj2006/tzj2006.github.io`），由构建脚本自动 commit + push，不要直接 commit 到其中。

```bash
pip install -e ".[website]"                          # 安装依赖（含 torch + transformers 翻译依赖）
cd tools/website && bash update.sh                   # macOS/Linux：增量压缩 + Hugo 构建 + 推送 Pages
powershell -ExecutionPolicy Bypass -File tools/website/update.ps1  # Windows（脚本会自行 cd 到所在目录）
cd tools/website && hugo server -D                   # 本地预览（dev server，含草稿）
```

详细分步操作见 [TUTORIAL.zh.md — Website](TUTORIAL.zh.md#website) 与源文档 [tools/website/CLAUDE.md](../tools/website/CLAUDE.md)。

### Translator — Gradio 文档翻译器

基于 `common` 翻译引擎的 Gradio 文档翻译器：一个 Google-Translate 风格的本地翻译网页，对文字和文件（`.md` / `.txt` / `.pdf` / `.docx` / 图片）做翻译，并保留 Markdown 格式（代码块、URL、Hugo shortcode 等片段会被保护）。本地推理、不走云 API：复用 `common.engine.create_engine()` 自动选择后端（`ollama` 在模型 tag 已 pull 时自动优选，`transformers` 为 Windows 兜底，`vllm` 为 Linux 优选，`llamacpp` 为 GGUF 低显存选项），模型常驻内存（warm），切换模型时按需懒加载。默认模型 `tencent/Hy-MT2-1.8B`（GGUF 变体 `tencent/Hy-MT2-1.8B-GGUF`），首次使用自动下载，可用 `GADGET_TRANSLATION_MODEL` 或 GUI 内模型管理覆盖。源语言可选 `auto`（按文本 CJK 比例检测），目标 `auto` 时在 zh↔en 间翻转。

```bash
pip install -e ".[translator]"   # 安装依赖（gradio + GGUF 翻译栈）
python -m translator             # 启动 Gradio GUI（浏览器打开）
```

详细分步操作见 [TUTORIAL.zh.md — Translator](TUTORIAL.zh.md#translator)。UI 接线见 `tools/translator/app.py`，翻译与文件逻辑见 `tools/translator/core.py`，共享引擎见 `common/engine.py`、`common/translation.py`。

## common / scripts / ai-companion

### common/ — 共享基础设施包

被所有工具依赖的共享层，通过 `pip install -e .` 安装为 Python 包：

- LLM 调用（统一两层 API，支持 `ollama`（默认）/ `claude_cli` / `anthropic` / `openai` 四后端）
- JSON 解析与修复
- SHA-256 磁盘缓存（命名空间 + TTL）
- 原子写入与内容哈希
- 本地推理翻译引擎（Ollama / vLLM / transformers / GGUF）与双语内容生成
- 跨平台 Hugo 部署

改共享能力（LLM、缓存、翻译、Hugo 部署）在这里改。

### scripts/ — 运维与维护脚本

- `sync.py` — 集中式 rclone 数据同步（push / pull / status / bootstrap / config，覆盖 summarize / website / research / test / backups 各类目；另含特殊 `dag` 类目用于生成 + 部署 DAG 站）。运行 `python scripts/sync.py`，配置为仓库根 `config.json` 的 `sync` 段（可用 `GADGET_CONFIG` 覆盖路径）。
- `onboard.py` — 仓库级一次性机器 onboarding：填一张 YAML sheet（`tokens/onboard.yaml`），跑一次脚本，自动完成 SSH 配置、Claude/Codex CLI 安装与鉴权、pip extras 与 ai-companion 安装、各工具 config、rclone bootstrap。
- 其余：`audit_content_languages.py`（审计/修复双语 Hugo 内容）、`fix_report_languages.py`、`profile_translation.py`（翻译引擎 GPU profiler）。

### AI Companion — 独立仓库

**ai-companion** 是一个独立的 Node.js 仓库（`git@github.com:TzJ2006/ai-companion.git`），检出在同级目录 `../ai-companion/`，**不在本仓库内**。它记录函数级代码变更、生成测试与 HTML 报告，提供 `/idea`→`/ccplan`→`/ccedit` 规划执行流水线，并托管全部 Claude Code skills（方法论 + 领域）。本仓库通过 `.claude/`、`.codex/` 里的 hooks 接入它。

它同时打包成**标准 Claude Code 插件**和**等效的 Codex 接入**——安装即用、无需构建（变更追踪 hook 为随仓库提交的预构建单文件产物）。所有 skills（方法论 skills：ccplan 规划、optimize 优化、cchypothesis 调试、repo-audit 审计、repo-tidy 整理；领域 skills：summarize 代码概述、slurm-gpu 集群检测、nature-benchmark / NIPS-2025-paper 论文写作顾问）均在该仓库，本仓库不再包含 `skills/` 目录。安装方式见 `../ai-companion/scripts/install.ts`。

### 新服务器 Onboarding

两条互补路径：

- **本仓库的机器配置** — `scripts/onboard.py`：填 `tokens/onboard.yaml` 后跑一次，配置 SSH、Claude/Codex 鉴权、pip extras、各工具 config 与 rclone bootstrap。
- **服务器系统级安装** — 为 Ubuntu 22.04/24.04 服务器一键安装 SSH 公钥、Claude Code、Codex、Superpowers、Ponytail 和 AI Companion 的脚本已随平台迁至 **ai-companion** 仓库：`../ai-companion/scripts/onboard-server.sh`。拆库后 `--companion-repo` 直接传 ai-companion repo（`git@github.com:TzJ2006/ai-companion.git`），不再需要 `--companion-ref`。用法见 `bash ../ai-companion/scripts/onboard-server.sh --help`。

## 输出目录

所有生成的输出统一放在 `outputs/` 目录下（已 gitignore，可自动重建）：

```text
outputs/
├── logs/         # 中间产物（export log、运行日志）
├── reports/      # 最终报告（Markdown、JSON、HTML）
├── cache/        # LLM 缓存、搜索缓存
├── data/         # 结构化数据（CSV、JSON profiles）
├── images/       # 图表与生成图片
└── backups/      # 强制覆盖前的备份（website-force 等）
```

Hugo 站点内容直接写入 `tools/website/content|static`（已无单独的 `outputs/site` staging 树）。

## 环境要求

- Python 3.10+（推荐 conda 环境 `AI`，`conda activate AI`）
- Node.js 18+（仅独立仓库 `../ai-companion/` 需要）
- 各工具的具体依赖见对应目录的 `requirements.txt`
- common 包 + 全部工具依赖：`pip install -e ".[all]"`
- 网站/翻译使用本地推理引擎（默认 Ollama；Linux 兜底 vLLM，Windows 兜底 transformers），模型 `tencent/Hy-MT2-1.8B` 首次运行自动下载

## 注意事项

- GPU 基准测试会自动检测 CUDA / Apple MPS / Intel XPU
- `tokens/` 目录存放 API 密钥与 onboarding sheet，已 gitignore，切勿提交其内容
- 所有生成文件输出到 `outputs/` 目录，已 gitignore
- 四个 LLM 后端统一通过 `--api` 参数切换：`ollama`（默认，本地 Qwen3.6-35B）、`claude_cli`、`anthropic`、`openai`
- 翻译链路不走 `--api`，而是使用 `GADGET_TRANSLATION_BACKEND` 选择的本地推理引擎：`ollama`（模型已 pull 时默认，走本地 Ollama 服务）→ `llamacpp`/`vllm`/`transformers`（进程内），模型 `tencent/Hy-MT2-1.8B`
- 跨设备数据同步使用 `python scripts/sync.py push/pull`（需配置 rclone）
- 永远不要 `git add` 自动生成内容、rclone 同步的数据、构建产物（`build/`、`gadget.egg-info/`）或 `tools/website/` 下的部署/主题仓库
- 各工具配置统一在仓库根 `config.json`（已 gitignore；从 `config.example.json` 复制）。可用 `GADGET_CONFIG` 覆盖路径。
