# Gadgets 使用教程

> 返回总览 [README.zh.md](README.zh.md) · English version: [../TUTORIAL.md](../TUTORIAL.md)

本文是 gadget 工具集的**详细使用教程**，覆盖安装与环境、五个工具（Summarize / Research / Benchmark / Website / Translator）的分步操作，以及跨设备数据同步与新机器 Onboarding。每个工具仍保留各自的源文档（`tools/<tool>/` 下），本文是它们的合并与统一入口。

> 所有 LLM 工具支持 `--api` 切换后端（`ollama` 默认 / `claude_cli` / `anthropic` / `openai`）；翻译链路走本地推理引擎，不经 `--api`。

## 目录

- [平台教程：安装、数据同步与机器 Onboarding](#平台教程安装数据同步与机器-onboarding)
  - [安装与环境](#安装与环境)
  - [数据同步：`scripts/sync.py`](#数据同步scriptssyncpy)
  - [一次性机器 Onboarding：`scripts/onboard.py`](#一次性机器-onboardingscriptsonboardpy)
- [Summarize](#summarize)
  - [目录结构](#目录结构)
  - [前置条件](#前置条件)
  - [配置文件（推荐）](#配置文件推荐)
  - [机器标识](#机器标识)
  - [工作流程](#工作流程)
  - [全流程自动化（auto）](#全流程自动化auto)
  - [云盘同步](#云盘同步)
  - [周报](#周报)
  - [月度总结](#月度总结)
  - [图表](#图表)
  - [Hugo 博客部署](#hugo-博客部署)
  - [支持的对话来源](#支持的对话来源)
  - [日报内容](#日报内容)
  - [数据格式与导入契约要点](#数据格式与导入契约要点)
  - [`--api` 参数说明](#--api-参数说明)
  - [运行测试](#运行测试)
  - [常用命令速查](#常用命令速查)
- [Research](#research)
  - [1. 初始配置](#1-初始配置)
  - [2. 创建研究项目](#2-创建研究项目)
  - [3. 搜索论文](#3-搜索论文)
  - [4. 生成周报（完整管线）](#4-生成周报完整管线)
  - [5. 论文深度洞察（--insight）](#5-论文深度洞察--insight)
  - [6. 会议论文搜索](#6-会议论文搜索)
  - [7. 多源搜索](#7-多源搜索)
  - [8. 自然语言搜索（ask 命令）](#8-自然语言搜索ask-命令)
  - [9. 研究者画像](#9-研究者画像)
  - [10. 引用图分析](#10-引用图分析)
  - [11. 部署到网站](#11-部署到网站)
  - [12. 参数调优](#12-参数调优)
  - [13. 工作流示例](#13-工作流示例)
  - [14. 文件结构说明](#14-文件结构说明)
  - [15. 常见问题](#15-常见问题)
- [Benchmark](#benchmark)
  - [1. 环境准备](#1-环境准备)
  - [2. 运行第一次基准测试](#2-运行第一次基准测试)
  - [3. 理解测试结果](#3-理解测试结果)
  - [4. 生成 HTML 报告](#4-生成-html-报告)
  - [5. 积累多台硬件数据](#5-积累多台硬件数据)
  - [6. 调优测试参数](#6-调优测试参数)
  - [7. 部署到网站](#7-部署到网站)
  - [8. 提交结果到公共排行榜](#8-提交结果到公共排行榜)
  - [9. GPU 后端兼容性速查](#9-gpu-后端兼容性速查)
  - [10. CSV 格式](#10-csv-格式)
  - [11. Python API](#11-python-api)
  - [12. 获取稳定结果的建议](#12-获取稳定结果的建议)
- [Website](#website)
  - [安装依赖](#安装依赖)
  - [一键构建 + 部署](#一键构建--部署)
  - [构建流水线（`update.sh` 八步）](#构建流水线updatesh-八步)
  - [本地预览（dev server）](#本地预览dev-server)
  - [增量翻译状态（`translate_site_batch.py`）](#增量翻译状态translatesitebatchpy)
  - [预检（`preflight_check.py`）](#预检preflightcheckpy)
  - [生成内容（单一内容根）](#生成内容单一内容根)
  - [内容创作](#内容创作)
  - [内容分区](#内容分区)
  - [静态资源](#静态资源)
  - [Hugo 配置（`config.yml`）](#hugo-配置configyml)
  - [关键约定](#关键约定)
  - [Git 追踪规则](#git-追踪规则)
- [Translator](#translator)
  - [1. 安装](#1-安装)
  - [2. 启动 GUI](#2-启动-gui)
  - [3. Gradio UI 用法](#3-gradio-ui-用法)
  - [4. 后端与模型环境变量](#4-后端与模型环境变量)
  - [5. 低显存 GGUF 路径](#5-低显存-gguf-路径)
  - [相关文件](#相关文件)

## 平台教程：安装、数据同步与机器 Onboarding

### 安装与环境

#### Python 与 conda

- 需要 **Python 3.10+**。推荐使用 conda 环境 `AI`：

  ```bash
  conda activate AI
  ```

- Windows：用 PowerShell 或 Git Bash。正斜杠路径在 Python 中可用；原生 shell 用反斜杠。

#### 安装 common 包与工具依赖

每个工具有自己的 `requirements.txt`，可单独安装：

```bash
pip install -r tools/<tool>/requirements.txt
```

更常用的是 editable install，它会把 `common/` 包和各工具包一起装上：

```bash
pip install -e .              # 仅安装 common/ 与工具包骨架
pip install -e ".[all]"       # summarize + research + benchmark + website（不含 translator）
```

`pyproject.toml` 中可选依赖 extras 一览：

| extra | 内容 |
|-------|------|
| `summarize` | anthropic 或 openai；可选 Node.js（ccusage / `@ccusage/codex` token 统计）、matplotlib（token 用量图） |
| `research` | arxiv、anthropic 或 openai、openreview-py；可选 PyMuPDF（`--insight` 模式 PDF 文本抽取）。bioRxiv/PubMed 仅用 stdlib |
| `benchmark` | torch、numpy、pandas、plotly、tqdm；可选 threadpoolctl、pyopencl |
| `website` | Pillow（图像处理）、torch + transformers（翻译）；可选 vLLM（Linux，更快批量推理）、llama-cpp-python（GGUF 后端） |
| `translation` | torch + transformers（`TransformersEngine`，Windows 回退；默认后端是 Ollama，无额外依赖） |
| `translation-gguf` | llama-cpp-python + huggingface-hub（`LlamaCppEngine`，低内存 GGUF，无 PyTorch） |
| `translator` | gradio + translation-gguf（Gradio 文档翻译器） |
| `all` | summarize + research + benchmark + website（**不含** `translator`） |

按需安装单个 extra，例如：

```bash
pip install -e ".[summarize]"
pip install -e ".[translation]"        # Windows 回退翻译后端（默认是 Ollama，无额外依赖）
pip install -e ".[translation-gguf]"   # 低内存 GGUF 后端
pip install -e ".[translator]"         # Gradio 翻译器
```

> `build/` 与 `gadget.egg-info/` 是 editable install 的生成物——已 gitignore，不要提交。项目许可为 GPL-3（见仓库根 `LICENSE`）。

#### 翻译后端（本地推理）

双语内容由 `common.engine.create_engine()` 自动选择后端，**不走 `--api`**：

- Ollama（`OllamaEngine`，**默认**）— 无额外依赖；拉取标签后自动优先（`ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF`）
- `pip install -e ".[translation]"` → torch + transformers（`TransformersEngine`，Windows 回退）
- Linux：可选 `pip install vllm>=0.8` → `VLLMEngine`（更快的批量推理）
- `pip install -e ".[translation-gguf]"` → `LlamaCppEngine`（低内存 GGUF，无 PyTorch）

默认模型 `tencent/Hy-MT2-1.8B`（GGUF 变体 `tencent/Hy-MT2-1.8B-GGUF`），首次运行自动下载。覆盖方式：

- 模型：`GADGET_TRANSLATION_MODEL` 环境变量或 `--model` CLI 参数
- 后端：`GADGET_TRANSLATION_BACKEND`（`ollama` / `vllm` / `transformers` / `llamacpp`）
- 批大小：`GADGET_TRANSLATION_BATCH_SIZE`

#### LLM 后端与 `--api`

所有使用 LLM 的工具都支持 `--api` 参数切换后端：

| `--api` 值 | 后端 | 所需 |
|-----------|------|------|
| `ollama`（默认） | 本地 Ollama 服务，无需 key | 本地运行的 Ollama 及已拉取的对话模型 |
| `claude_cli` | 本地 Claude Code CLI | 已安装并登录 `claude` CLI |
| `anthropic` | Anthropic API | 环境变量 `ANTHROPIC_API_KEY` |
| `openai` | OpenAI API | 环境变量 `OPENAI_API_KEY` |

相关环境变量：

- `ANTHROPIC_API_KEY`、`OPENAI_API_KEY` — API 访问
- `GADGET_LLM_BACKEND` — 全局覆盖默认 `--api` 后端
- `SUMMARIZE_LOGS_DIR`、`SUMMARIZE_REPORTS_DIR` — 覆盖 summarize 默认输出路径

配置解析顺序（所有工具一致）：CLI 参数 > 环境变量 > `config.json` 段 > 硬编码默认值。所有工具共用仓库根 **`config.json`**（gitignored；模板 `config.example.json`），按段命名（`summarize`、`research_scout`、`research`、`sync`、`translator`）。用 `GADGET_CONFIG` 覆盖文件路径。各工具的 `config --init` 写入对应段。

#### 测试

没有仓库级测试 runner，测试按模块组织，用 `pytest` 运行：

```bash
pytest tools/summarize/tests/            # summarize: config、formatter、imports、summarizer、parsers
pytest tools/summarize/tests/test_config.py  # 单个测试文件
pytest tools/research/tests/             # research: 流水线契约测试
```

测试用 `unittest.mock` 桩掉模型加载、推理和 LLM 后端。

---

### 数据同步：`scripts/sync.py`

基于 rclone 的集中式个人数据同步（与 Google Drive 之间）。配置为仓库根 `config.json` 的 `sync` 段（可用 `GADGET_CONFIG` 覆盖路径）。

#### 子命令

```bash
python scripts/sync.py push                      # 本地 → 远端
python scripts/sync.py pull                      # 远端 → 本地
python scripts/sync.py status                    # 显示本地与远端差异（rclone check）
python scripts/sync.py config                    # 查看当前配置
python scripts/sync.py config --init             # 交互式初始化配置
python scripts/sync.py bootstrap --remote gdrive:gadget  # 新设备一键初始化（拉配置 + 数据）
```

#### 选项

- `--dry-run` — 预览，不实际传输；可放在子命令前后任意位置（例如 `python scripts/sync.py --dry-run push` 或 `push --dry-run` 均可）。
- `--category <name>` — 只同步某一类。可用类目：`summarize`、`website`、`research`、`benchmark`、`backups`（`test` 是 `benchmark` 的旧名别名；顶层另有特殊类目 `dag`，见下）。`push`/`pull`/`status` 均支持。
- `--include-config` — `push` 时同时把配置文件备份到远端（供其他设备 bootstrap）。
- `--include-tokens` — `push` / `bootstrap` 时包含 `tokens/` 目录（含 API 密钥）。

示例：

```bash
python scripts/sync.py push --category summarize        # 只同步 summarize 一类
python scripts/sync.py push --include-config            # push 数据 + 备份配置
python scripts/sync.py push --include-tokens            # push 数据 + 备份 tokens/
python scripts/sync.py status --category research       # 只检查 research 差异
python scripts/sync.py pull --dry-run                   # 预览 pull
```

#### 同步类目映射

| 类目 | 同步内容（示例） |
|------|------------------|
| `summarize` | `outputs/logs/summarize`、`outputs/reports/summarize`、`outputs/images/summarize` |
| `website` | `tools/website/content/bugJournal/{daily,weekly,monthly}`、`tools/website/content/research`、`tools/website/static/images/{weekly,monthly}`、`tools/website/static/benchmark-report`、`tools/website/content/{leetcode,posts}` 及若干松散文件（About.pdf、Resume.md/pdf、Random.md、benchmark.md/zh.md） |
| `research` | `outputs/cache/research-scout`、`tools/research/projects`、`outputs/reports/research-scout`、`outputs/logs/research-scout`、`outputs/{reports,data}/research-profiler` |
| `benchmark` | `outputs/data/benchmark`（含 `results.csv`）；`--category test` 为旧名别名 |
| `backups` | `outputs/backups/website-force`、`outputs/backups/summarize`（覆盖前自动备份） |

#### 首次配置（`config --init`）

交互式询问：

- rclone 远端基础路径（默认 `gdrive:gadget`）
- 若 PATH 上找不到 `rclone`，再询问 rclone 二进制路径（如 `~/.local/bin/rclone`）

写入仓库根 `config.json` 的 `sync` 段。如未单独配置，脚本也会尝试从 summarize config 推导远端基础路径。

#### 新设备一键初始化（`bootstrap`）

```bash
python scripts/sync.py bootstrap --remote gdrive:gadget
python scripts/sync.py bootstrap --remote gdrive:gadget --include-tokens   # 同时拉取 tokens/（含密钥）
python scripts/sync.py bootstrap --dry-run
```

`bootstrap` 依次：向仓库根 `config.json` 写入最小 `sync` 段 → 校验远端连通性（`rclone lsd`）→ 拉取配置文件 → （可选 `--include-tokens`）拉取 tokens → 拉取全部数据目录。`--remote` 默认 `gdrive:gadget`。

#### 特殊类目 `dag`（生成 + 部署，非 GDrive 同步）

`dag` 类目语义不同于 rclone 同步——它「生成 + 部署 DAG 站」。只能在顶层用、不带子命令：

```bash
STATICRYPT_PASSWORD='<your-password>' python scripts/sync.py --category dag
python scripts/sync.py --category dag --dry-run     # 仅打印将运行的命令与目标路径
```

它会：

1. 运行 `npx tsx ../ai-companion/scripts/build-dag-site.ts stage`（生成 overview + 各项目详情页 → StatiCrypt 加密 → 落地 `tools/website/static/dag/`），密码经环境变量 `STATICRYPT_PASSWORD` 传入（绝不硬编码）；
2. 触发 website 发布（`tools/website/update.sh`，Hugo 构建并推送到 `/dag/` 路径）。

`--dry-run` 时仅打印将运行的命令，不实际生成或部署。

---

### 一次性机器 Onboarding：`scripts/onboard.py`

仓库级一次性配置：**填一张 YAML sheet，跑一次脚本**。每个 section 有 `enabled:` 开关，让每台机器只跑自己需要的步骤。安全动作自动应用；高风险动作（落 SSH 私钥、向远端推公钥、额外全局 npm）会先提示确认，除非加 `--yes`。重复运行会跳过已完成步骤（幂等）。

#### 三步上手

```bash
cp scripts/onboard.example.yaml tokens/onboard.yaml   # 1. 复制模板
# 2. 编辑 tokens/onboard.yaml，填好各 section（见下）
python scripts/onboard.py                             # 3. 运行
```

默认读 `tokens/onboard.yaml`（gitignore），模板是 `scripts/onboard.example.yaml`。

#### 命令行选项

```bash
python scripts/onboard.py [--sheet PATH] [--only a,b] [--skip a,b]
                          [--dry-run] [--yes] [--no-verify]
                          [--verify-only] [--list]
```

- `--sheet PATH` — 指定 sheet 路径（默认 `tokens/onboard.yaml`）。
- `--only a,b` — 只跑这些步骤（逗号分隔），覆盖 sheet 里的 `enabled`。
- `--skip a,b` — 跳过这些步骤。
- `--dry-run` — 打印将执行的动作，不改任何东西。
- `--yes` / `-y` — 对高风险提示一律假定为 yes。
- `--no-verify` — 跳过结尾的就绪检查。
- `--verify-only` — 只跑就绪检查（不执行任何步骤）。
- `--list` — 列出已注册的步骤及其在 sheet 中的启用状态。

注册步骤（按顺序）：`ssh`、`claude`、`install`、`gadgets`、`sync`。不带 `--only` 时，脚本运行 sheet 里 `enabled: true` 的所有 section。单个步骤失败不会中断其他步骤。

#### sheet 各 section

每个顶层 section 都有 `enabled:` 开关。各值标注 (required) 或 (optional)，(optional) 已带可用默认值。

**`ssh`** — 写 `~/.ssh/config`（哨兵注释包裹，只改自己的块）、可选落私钥、可选推公钥到远端：

```yaml
ssh:
  enabled: true
  hosts:
    - alias: gpu1                       # (required) 之后可 `ssh gpu1`
      hostname: gpu1.example.edu        # (required)
      user: thomas                      # (required)
      port: 22                          # (optional) 默认 22
      identity_file: ~/.ssh/id_ed25519  # (optional) 默认 ~/.ssh/id_ed25519
      install_private_key:              # (optional) RISKY（提示确认）：把私钥落到本机；省略则跳过
        from: tokens/keys/id_ed25519    # (required if install_private_key) 仓库相对或绝对路径
        to: ~/.ssh/id_ed25519           # (optional) 默认 ~/.ssh/id_ed25519，chmod 600 (POSIX) / icacls (Windows)
      push_public_key: false            # (optional) RISKY（提示确认）：把公钥追加到远端 authorized_keys；默认 false
      public_key: ~/.ssh/id_ed25519.pub # (optional) 默认 identity_file + ".pub"
```

**`claude`** — 安装 Claude/Codex CLI 并写 Claude Code 用户级鉴权（写入 `~/.claude/settings.json` 的 `env`，**不是**仓库的 `.claude/settings.json`）：

```yaml
claude:
  enabled: true
  install: true                         # npm i -g @anthropic-ai/claude-code（已装则跳过）
  codex:
    install: true
    package: "@openai/codex"            # 包名不同时覆盖
  auth_mode: api                        # (required) api | bedrock | platform_aws — 只读匹配的那个块
```

`auth_mode` 三种鉴权模式，只读对应的子块（应用前会先剥掉其它模式的所有 env 变量，避免上一次的模式遮蔽本次）：

- **`api`** — 直连 Anthropic API：
  ```yaml
  api:
    ANTHROPIC_API_KEY: "sk-ant-..."     # (required if auth_mode=api)
  ```
- **`bedrock`** — 通过 AWS Bedrock（设 `CLAUDE_CODE_USE_BEDROCK=1`）：
  ```yaml
  bedrock:
    AWS_REGION: us-east-1               # (required if auth_mode=bedrock)
    AWS_PROFILE: ""                     # (optional) PROFILE / access keys / bearer token 三者择一即可
    AWS_ACCESS_KEY_ID: ""
    AWS_SECRET_ACCESS_KEY: ""
    AWS_SESSION_TOKEN: ""
    AWS_BEARER_TOKEN_BEDROCK: ""
    ANTHROPIC_DEFAULT_OPUS_MODEL: ""    # (optional) 如 us.anthropic.claude-opus-4-8
    ANTHROPIC_DEFAULT_SONNET_MODEL: ""
    ANTHROPIC_DEFAULT_HAIKU_MODEL: ""
    awsAuthRefresh: ""                  # (optional) settings.json 顶层 key（命令字符串）
  ```
- **`platform_aws`** — Claude Platform on AWS（Anthropic 运营的 API，经 AWS，**非** Bedrock，设 `CLAUDE_CODE_USE_ANTHROPIC_AWS=1`）：
  ```yaml
  platform_aws:
    ANTHROPIC_AWS_WORKSPACE_ID: "wrkspc_..."  # (required if auth_mode=platform_aws)
    AWS_REGION: us-east-1                      # (required if auth_mode=platform_aws)
    ANTHROPIC_AWS_API_KEY: ""                  # (optional) 或留空依赖环境里的 AWS SigV4 凭证
    ANTHROPIC_AWS_BASE_URL: ""                 # (optional) 公司代理
  ```

**`install`** — pip extras + ai-companion + Claude 插件 + 额外全局 npm：

```yaml
install:
  enabled: true
  ai_companion: true                    # npx tsx ../ai-companion/scripts/install.ts . --enforce（skills/hooks/harness，claude+codex）
  claude_plugins: []                    # RISKY（提示确认）：`claude plugin install <id>` 列表
  pip_extras: [all]                     # 要安装的 extras；默认 [all] = summarize+research+benchmark+website，不含 translator
  global_npm: []                        # RISKY（提示确认）：额外 `npm i -g` 包
```

**`gadgets`** — 写各工具 config JSON（省略某工具即跳过它）：

```yaml
gadgets:
  enabled: true
  summarize:                            # -> config.json "summarize"
    device_name: ""                     # 空 = hostname
    logs_dir: ""                        # 空 = 默认（outputs/logs/summarize）
    reports_dir: ""                     # 空 = outputs/reports/summarize
    hugo_site: "tools/website"          # 相对仓库根的 Hugo 站点
    rclone_remote: "gdrive:gadget/summarize"
    rclone_path: ""                     # 空 = 远端默认
    default_api: claude_cli             # ollama | claude_cli | anthropic | openai; 默认: ollama
  research:                             # -> config.json "research"
    model: sonnet
    default_mode: fast
    default_depth: 1
    max_students: 10
    output_dir: ""
    semantic_scholar_api_key: ""        # 设置可提高速率上限
  research_scout:                       # -> config.json "research_scout"
    default_api: claude_cli
    hugo_site: "tools/website"          # 相对仓库根的 Hugo 站点
    default_lookback_days: 7
    default_max_results: 50             # 建议 ~50 以内，避免筛选超时
    default_top_papers_in_report: 5
    max_high_relevance: 20
    default_insight_top_n: 3
  benchmark: {}                         # 无独立 config；仅 pip extra + import 检查
  translator: {}                        # 模型列表在 config.json translator.models
  website: {}                           # 无独立 config；仅 pip extra + import 检查
```

**`sync`** — 可选的 rclone bootstrap（复用 `scripts/sync.py`），默认关闭：

```yaml
sync:
  enabled: false                        # 默认关；按需在某台机器打开
  bootstrap: false                      # true 则跑 python scripts/sync.py bootstrap
  remote: "gdrive:gadget"               # (required if sync enabled) rclone 远端根
  include_tokens: false                 # RISKY（提示确认）：同时拉取 tokens/（API 密钥）
```

#### 常用调用示例

```bash
python scripts/onboard.py --list                 # 看哪些步骤启用了
python scripts/onboard.py --dry-run              # 预演，不改任何东西
python scripts/onboard.py --only ssh,claude      # 只跑 ssh 和 claude
python scripts/onboard.py --skip sync            # 跑全部 enabled 步骤，但跳过 sync
python scripts/onboard.py --yes                  # 对高风险提示一律确认
python scripts/onboard.py --verify-only          # 只跑结尾的就绪检查
```

#### 就绪检查（verify）

除非加 `--no-verify`，脚本结尾会跑就绪检查：核验 `claude`（必需）/ `codex`（可选）CLI 是否在 PATH、Claude 鉴权环境变量是否按 `auth_mode` 写好、各 SSH 主机是否可达、已配置的工具依赖是否可 import。`--verify-only` 可单独跑此检查（退出码反映是否有阻塞性失败）。

## Summarize

AI 对话日报 & 周报 & 月度总结工具完整教程。这个工具自动读取你每天和 AI 的对话记录（Claude Code / Codex / Cursor Agent / ChatGPT / 通用 JSON），调 LLM API 生成结构化日报、周报和月度总结。

支持多设备工作流：在每台机器上导出对话 log，通过云盘同步或手动拷贝汇总，生成最终日报。积累足够日报后可生成周报和月度趋势总结。

### 目录结构

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

tools/summarize/
config.json                  # 仓库根统一配置（summarize 段：设备别名、输出路径、rclone；模板 config.example.json）
```

### 前置条件

Python 3.10+，无需额外安装即可运行 `export`（纯本地解析）。

Token 用量统计需要 Node.js（通过 npx 调用 [ccusage](https://github.com/ryoppippi/ccusage)），没装也不影响其他功能。ccusage 20.x 一个工具即覆盖所有 agent CLI：

- 全部来源：`npx ccusage@latest --help`
- 单来源（命名空间）：`npx ccusage@latest claude|codex|gemini daily --help`

> 缺失或低于 20.x 时会静默尝试 `npm install -g ccusage@latest`，失败则回退 npx。

月度图表（可选）：`pip install matplotlib`。

安装包和 Python 依赖：

```bash
# 安装 summarize 包（推荐，启用 python -m summarize 命令）
pip install -e .
# 或只安装 Python 依赖
pip install -r tools/summarize/requirements.txt
```

> **CLI 用法变更**：重构后推荐使用 `python -m summarize daily ...` 形式。旧的 `python tools/summarize/daily_summary.py ...` 仍然可用（向后兼容）。本教程中的命令均使用新形式。

> 请先 `pip install -e .`，再从仓库根目录运行 `python -m summarize`。

调 API 生成总结时，有四种后端可选。默认是 `ollama` —— 无需 key 的本地 Ollama 服务（见 `scripts/serve_local_llm.sh`；可用 `GADGET_LLM_BACKEND` 全局覆盖）。另外三种：

#### 方式一：Claude Code CLI

使用本地安装的 Claude Code CLI 生成总结，**无需设置 API key**，直接复用 Claude Code 的登录状态。

```bash
# 安装 Claude Code CLI（如果还没装）
npm install -g @anthropic-ai/claude-code

# 确认已登录
claude --version
```

使用时通过 `--api claude_cli` 选择：

```bash
python -m summarize daily export --summarize --date 2026-02-13 --api claude_cli
```

#### 方式二：Anthropic API

直接调用 Claude API，需要 API key：

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

python -m summarize daily export --summarize --date 2026-02-13 --api anthropic
```

#### 方式三：OpenAI API

```bash
pip install openai
export OPENAI_API_KEY="sk-..."

python -m summarize daily export --summarize --date 2026-02-13 --api openai
```

### 配置文件（推荐）

多设备使用时，建议在每台设备上创建配置文件，设置设备别名和输出路径。

配置文件路径：仓库根 `config.json` 的 `summarize` 段（模板：根目录 `config.example.json`；`config --init` / `onboard --init-config` 写到这里）。用 `GADGET_CONFIG` 覆盖文件路径。不再读取 `tools/summarize/config.json` 或 `~/.config/summarize/config.json`。

#### 快速创建

```bash
python -m summarize daily config --init
```

交互式询问各项设置，生成配置文件。

#### 手动编辑

```json
{
  "device_name": "home-server",
  "logs_dir": "~/Google Drive/summarize/logs",
  "reports_dir": "~/Google Drive/summarize/reports",
  "rclone_remote": "gdrive:gadget/summarize",
  "rclone_path": "~/.local/bin/rclone"
}
```

#### 字段说明

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `device_name` | 设备别名，用于 export 文件名和 log 内容 | 系统主机名（`platform.node()`） |
| `logs_dir` | logs 输出目录，支持 `~`，可指向云盘同步目录 | `outputs/logs/summarize/` |
| `reports_dir` | reports 输出目录，支持 `~` | `outputs/reports/summarize/` |
| `rclone_remote` | rclone 远端路径，export 上传到 `<remote>/logs/`，merge 上传到 `<remote>/reports/`，`--sync` 从 `<remote>/logs/` 下载 | （不上传） |
| `rclone_path` | rclone 二进制路径，支持 `~`，用于无 sudo 权限的环境 | 从 PATH 查找 |

所有字段都是可选的，不需要的可以不写。没有配置文件时一切行为与之前相同。配置键完整列表：`device_name`、`logs_dir`、`reports_dir`、`rclone_remote`、`rclone_path`，以及 CLI 默认值键 `default_api`、`deploy`、`hugo_site`、`workers`，和本地 LLM / 翻译键 `model`、`base_url`、`reasoning_effort`、`translation_model`、`translation_model_ollama`、`translation_backend`。

#### 查看当前配置

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

#### 输出路径优先级

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

### 机器标识

每台设备可以通过 `device_name` 设置一个易读的别名，替代默认的系统主机名（如 `DESKTOP-ABC123`）。

设置方法：
- 运行 `config --init` 交互式设置
- 或手动在仓库根 `config.json` 的 `summarize` 段中添加 `"device_name": "my-alias"`

#### 文件名变化

export 导出的文件名使用 `device_name`：

```
未配置: 2026-02-14_DESKTOP-ABC123.json
配置后: 2026-02-14_home-server.json
```

#### export log 中的设备信息

`device_name` 和原始 `hostname` 都会保留在 export log 中：

```json
{
  "device": {
    "device_name": "home-server",
    "hostname": "DESKTOP-ABC123",
    "platform": "win32",
    "username": "your-user"
  }
}
```

merge 生成日报时，AI 会看到 `device_name` 作为设备标签，报告更易读。

### 工作流程

整个工具分两个阶段。无子命令时默认执行 export（仅导出，不调 API）。

#### Phase 1: Export（每台设备上运行）

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

#### Phase 2: Merge（任意设备上运行）

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

默认 `--workers 1`（顺序处理，保持原有行为），实际并行数会被裁剪到「待处理日期数」。该参数**仅对 `--sync-all` 批量合并生效**，单日期 merge 与 export 不受影响。每个 worker 是独立子进程，日志分别写到 `outputs/logs/summarize/merge_logs/`。并发越高对 LLM 后端的瞬时请求越多——用 `claude_cli` 或有速率限制的 API 时不宜调太大。

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

#### 完整工作流示例

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

### 全流程自动化（auto）

`auto` 子命令通过子进程串起完整管线：daily export → daily merge → weekly → monthly，一条命令覆盖日常总结。适合 cron / systemd timer 定时任务，或每天收工前手动触发。

#### 基本用法

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

#### 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `--date YYYY-MM-DD` | 昨天 | 聚合目标日期。决定周报取哪一周、月报取哪一月。**不影响** `daily export` / `merge --sync-all`，它们仍处理所有未导出 / 未 finalized 日期 |
| `--api {ollama,claude_cli,anthropic,openai}` | `ollama` | LLM 后端，透传给所有调 LLM 的步骤 |
| `--deploy` | 关 | 对 merge / weekly / monthly 都追加 `--deploy`，把日报 / 周报 / 月报一并发布到 Hugo |
| `--force` | 关 | 对所有四步追加 `--force`，忽略缓存和已存在的输出文件，强制重跑 |
| `--workers N` | 1 | 透传给 `daily merge --sync-all`，开 N 个 worker 并行合并多天日报（默认 1 = 顺序）。详见上文 `--sync-all` 的「并行加速」说明 |

#### 执行流程

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

#### 典型使用场景

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

#### auto vs 分步执行

`auto` 不是必需的，完全等价于手动依次执行四条命令。选择：

- **用 `auto`**：希望一条命令兜住全部日常流程；对「任一步失败不阻断后续」的行为能接受。
- **分步执行**：需要细粒度控制（例如只重跑 weekly、手动指定 log 文件、交互式检查每一步输出、或各步使用不同 `--api`）。

#### Onboarding / readiness check

`auto` 会在真正执行 export / merge / weekly / monthly 之前先检查运行条件。如果缺少必需项（例如 `rclone_remote`、`rclone`、默认 `ollama` 后端可达的 Ollama 服务（用 `claude_cli` 时则是 `claude` CLI），或 `--deploy` 需要的 Hugo 站点/二进制），命令会停止并给出修复步骤，避免跑到一半才失败。

```bash
python -m summarize onboard                 # 检查 summarize auto 所需条件
python -m summarize onboard --init-config   # 交互式创建/更新 config.json 的 summarize 段
python -m summarize onboard --deploy        # 同时检查 Hugo 部署要求
python -m summarize auto                    # 自动先运行 readiness check
python -m summarize auto --skip-onboard-check  # 仅在明确要跳过检查时使用
```

#### auto 常见问题

- **聚合目标为什么默认是昨天，不是今天？** 因为当天对话往往尚未结束，日报和 ccusage 统计都不完整。如确需处理当天，显式传 `--date $(date +%F)`。
- **`auto` 会上传到 rclone 吗？** `daily export` 和 `daily merge` 会按配置自动上传（与单独运行它们行为一致），`weekly` / `monthly` 的输出不会自动上传（需要 `--deploy` 触发 Hugo 部署流程）。
- **多设备环境下在哪台机器跑 `auto`？** 每台设备都需要跑 `daily export`（解析本地对话），而 `merge / weekly / monthly` 只需在一台中心机器上跑。多数情况下建议：所有设备各自跑 `daily export`（可用 cron），中心机器跑 `auto --deploy`（它的 daily export 相当于补跑 + merge 相当于汇总）。

### 云盘同步

多设备间传递 log/reports 文件，有两种云盘方案，解决多设备间 log 文件传输问题。

#### 方式一：云盘 App 同步（有桌面环境的设备推荐）

将输出目录指向云盘同步文件夹，文件写入后由云盘 App 自动同步到所有设备。

在每台设备仓库根 `config.json` 的 `summarize` 段中设置：

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

#### 方式二：rclone（headless server 推荐）

[rclone](https://rclone.org/) 是命令行云盘工具，支持 40+ 种云存储（Google Drive、OneDrive、S3、...），不需要桌面环境，非常适合 headless server。

配置后，export 自动上传到 `<remote>/logs/`，merge 自动上传到 `<remote>/reports/`。merge 时可用 `--sync` 从 `<remote>/logs/` 拉取其他设备的 log。上传/下载失败只打 `[warn]`，不阻断主流程。

**1. 安装 rclone**

有 sudo 权限：

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

无 sudo 权限（headless server 常见）—— 直接下载二进制文件到用户目录：

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

**2. 配置 remote**

有浏览器的设备：

```bash
rclone config
```

按提示选择云盘类型、完成 OAuth 授权。

headless server（无浏览器）—— 先在有浏览器的设备上获取 token：

```bash
rclone authorize "drive"     # Google Drive
rclone authorize "onedrive"  # OneDrive
```

浏览器弹出授权页面，完成后终端输出 token JSON。然后在 server 上运行 `rclone config`，选择手动输入 token，粘贴上一步输出的 JSON。

**3. 启用自动上传**

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

**4. 验证**

```bash
# 查看配置是否生效（会显示 logs/reports 子路径）
python -m summarize daily config --show

# 手动测试 rclone 连通性
rclone ls gdrive:gadget/summarize/logs/
rclone ls gdrive:gadget/summarize/reports/
```

**混合使用**

可以在桌面设备用云盘 App（设 `logs_dir` 指向同步目录），在 server 上用 rclone（设 `rclone_remote`），两者最终文件到同一个云盘目录，互不冲突。

> **提示**：使用 rclone 时，export 上传到 `<remote>/logs/`，merge 上传到 `<remote>/reports/`。如果你之前使用的是 flat 目录结构（没有 logs/reports 子目录），已有文件不受影响，新文件会自动上传到对应子目录。

### 周报

积累一周的日报后，可以生成 ISO 周报（周一至周日）。

#### 查看可用周

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

#### 生成周报

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

#### 缓存机制

与月度总结相同，LLM 调用结果按源日报哈希缓存在 `outputs/cache/summarize/weekly/`。

```bash
# 跳过 LLM 缓存，强制重新调 API
python -m summarize weekly generate --week 2026-W12 --no-cache
```

### 月度总结

积累一个月的日报后，可以生成月度趋势总结。

#### 查看可用月份

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

#### 生成月度总结

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

#### 工作原理

月度总结分两部分：

1. **LLM 分析**（需调 API）— 读取所有日报 JSON，剥离 `token_usage` 和 `conversation_summaries` 字段（这些机械聚合），将剩余内容格式化后发给 LLM 分析趋势。如果内容超过 150K 字符，自动按周分组分段总结再合并。
2. **机械聚合**（纯本地计算）— 汇总 token 用量（总量、日均、峰值、模型分布）和统计数据（活跃天数、对话数、任务数、项目数）。

#### 缓存机制

LLM 调用结果缓存在 `outputs/cache/summarize/monthly/YYYY-MM.json`，缓存键为所有源日报文件的 SHA-256 哈希。任一日报更新后缓存自动失效。

```bash
# 跳过 LLM 缓存，强制重新调 API
python -m summarize monthly generate --month 2026-02 --no-cache

# 忽略已有输出文件，强制重新生成
python -m summarize monthly generate --month 2026-02 --force
```

#### 月度总结内容

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

#### 月度总结 + Hugo 部署

```bash
python -m summarize monthly generate --month 2026-02 --deploy
python -m summarize monthly generate --month 2026-02 --deploy --hugo-site /path/to/site
```

这会：
1. 生成月度报告
2. 将 Markdown 发布到 Hugo `content/bugJournal/2026-02-monthly.md`（日期设为月末最后一天 23:59，排在所有日报之后）
3. 将趋势图复制到 Hugo `static/images/monthly/`
4. 执行 `update.sh` 构建并推送

### 图表

所有图表通过 `charts.py` 生成，需要 `pip install matplotlib`（可选，未安装时跳过图表不影响报告生成）。输出到 `outputs/images/summarize/`。

#### 日报/周报图表

每份日报和周报生成一张三子图 PNG（`<date>-usage.png`）：

| 子图 | X 轴 | Y 轴 | 说明 |
|------|------|------|------|
| Tokens | 平台 (Claude Code / Codex) | Token 数 | 按模型堆叠 |
| Cost | 平台 | 费用 ($) | 按模型堆叠 |
| Cache | 平台 | Token 数 | 按类型堆叠 (input/output/cache) |

#### 月度图表

月度报告生成两张独立图表：
- **费用趋势图** (`<month>-monthly-cost.png`) — X 轴为日期，按模型堆叠的费用柱状图
- **Token 趋势图** (`<month>-monthly-tokens.png`) — X 轴为日期，按 token 类型堆叠的柱状图

### Hugo 博客部署

#### merge 时部署

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

#### 批量部署（deploy 子命令）

使用独立的 `deploy` 子命令可以将 `reports/` 目录下已有的报告批量部署到 Hugo，无需重新调 API：

```bash
# 部署所有报告
python -m summarize daily deploy

# 部署指定日期
python -m summarize daily deploy --date 2026-02-13

# 指定 Hugo 站点路径和报告目录
python -m summarize daily deploy --hugo-site /path/to/site --reports-dir /path/to/reports

# 强制重新部署已有文章
python -m summarize daily deploy --force
```

`deploy` 会遍历所有 `.md` 报告文件，为每个文件生成 Hugo 文章，最后执行一次 `update.sh` 统一构建推送。加 `--force` 可强制重新部署已有文章。

### 支持的对话来源

| 来源 | 说明 | 自动扫描 |
|------|------|----------|
| Claude Code | 读取 `~/.claude/projects/` 下的 `.jsonl` 文件 | 是 |
| Codex | 读取 `~/.codex/sessions/` 下的会话目录 | 是 |
| Cursor Agent | 读取 `~/.cursor/projects/*/agent-transcripts/<uuid>/<uuid>.jsonl`（仅 parent；无 token usage） | 是 |
| ChatGPT | ChatGPT 导出的 `conversations.json` | 否，需 `--chatgpt` 指定 |
| 通用格式 | `[{"role": "user", "content": "..."}]` 的 JSON 数组 | 否，需 `--generic` 指定 |

> **WSL 支持**：在 WSL 中运行时，Claude/Codex 的数据通常写在 Windows 用户目录而非 Linux home。检测到 WSL（内核含 `microsoft`）后会额外扫描 `/mnt/c/Users/*` 下的 `.claude*/projects/` 与 `.codex/sessions/`，无需配置。（假设 C 盘挂在 `/mnt/c`。）

### 日报内容

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

### 数据格式与导入契约要点

**Export log**（`logs/YYYY-MM-DD_<device>.json`）：

```
{version, date, device, conversations[], device_summary{}, token_usage, _merged_devices[], _finalized}
```

**Report**（`reports/YYYY-MM-DD.json`）：

```
{date, summary, daily_overview, tasks[], problems_and_solutions[], human_vs_ai[],
 ai_limitations[], learnings[], conversation_summaries[],
 token_usage_by_source{<source>: usage}, token_usage, codex_token_usage}
```

`token_usage_by_source` 是 canonical（每个发现的来源一条）；`token_usage`（Claude Code）和 `codex_token_usage` 作为向后兼容别名保留。

**Weekly Report**（`reports/YYYY-WNN-weekly.json`）：

```
{week, date_range{start,end}, summary, project_progress[], key_tasks[], problems_resolved[],
 learnings[], ai_usage_notes{}, next_week_outlook, statistics,
 token_usage_summary, codex_token_usage_summary, combined_token_usage_summary}
```

ISO 8601 周（周一至周日）。tasks/problems/learnings 中每一项都带 `level: "high"|"low"` 和 `importance: 1-10`，用于优先级排序。

**导入契约**：`daily_summary.py` 是向后兼容 re-export shim，是稳定的 API surface（被 monthly/weekly 管线和外部消费者引用）。被外部消费的关键导出：`_atomic_write`、`_resolve_output_dir`、`_load_config`、`run_hugo_update`、`format_reports_for_llm`、`aggregate_token_usage`。`tests/test_imports.py` 参数化验证重构后所有期望符号仍可导入，结构变动后必跑。新代码应直接 import 具体子模块。

### `--api` 参数说明

所有需要 AI 总结的命令（`export --summarize`、`merge`、`weekly generate`、`monthly generate`、`auto`）都支持 `--api` 参数：

| 值 | 说明 | 是否需要 API key |
|----|------|-----------------|
| `ollama` | 调用本地 Ollama 服务（默认） | 否，本地无 key 服务 |
| `claude_cli` | 调用本地 Claude Code CLI | 否，复用 CLI 登录状态 |
| `anthropic` | 调用 Anthropic Claude API | 是，需 `ANTHROPIC_API_KEY` |
| `openai` | 调用 OpenAI API | 是，需 `OPENAI_API_KEY` |

`claude_cli` 模式通过 `claude --print` 将 prompt 传给 Claude Code CLI。需要提前安装并登录 Claude Code。

#### `--timeout` 参数

所有 LLM 调用命令（`export --summarize`、`merge`）支持 `--timeout` 控制每 150K chunk 的超时秒数：

```bash
# 默认 600 秒
python -m summarize daily merge --sync --date 2026-02-13

# 自定义超时
python -m summarize daily merge --sync --date 2026-02-13 --timeout 300
python -m summarize daily export --summarize --date 2026-02-13 --timeout 900
```

### 运行测试

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

### 常用命令速查

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

## Research

Research Scout 是一个统一的学术研究工具包，包含四大功能：

1. **论文发现**：从 arXiv / bioRxiv / PubMed 搜索论文，三阶段 LLM 管线（快速筛选 → 深度分析 → 引用影响），生成周报
2. **论文深度洞察**（`--insight`）：下载论文全文，LLM 分析写作结构、发表策略、核心知识；自动获取 OpenReview 审稿意见并分析 reviewer 共识；生成研究写作指南
3. **研究者画像**：分析研究者的学术轨迹、评分分层、发现师生关系
4. **引用图分析**：查看论文的前向引用（谁引了它）和反向参考文献（它引了谁），LLM 分析影响力

所有功能通过一个统一的 CLI 入口 `research_scout.py` 调用。

### 1. 初始配置

首次使用前需要进行配置：

```bash
python tools/research/research_scout.py config --init
```

会交互式询问以下配置项：
- **默认 LLM 后端**：`ollama`（默认，本地无 key 的 Ollama 服务）/ `claude_cli`（直接调用 Claude CLI）/ `anthropic` / `openai`
- **Hugo 站点路径**：用于将周报部署到你的博客（可选）
- **默认回溯天数**：搜索最近几天的论文（默认 7 天）
- **默认最大结果数**：每个项目每次搜索最多返回多少篇论文（默认 50）
- **报告中展示的高分论文数**：周报中详细展示多少篇（默认 5）

配置保存在仓库根 `config.json` 的 `research_scout` 段（可用 `GADGET_CONFIG` 覆盖路径）。

查看当前配置：

```bash
python tools/research/research_scout.py config --show
```

> **注意**：使用 `anthropic` 后端需要设置环境变量 `ANTHROPIC_API_KEY`；使用 `openai` 后端需要设置 `OPENAI_API_KEY`。使用 `claude_cli` 后端不需要额外配置，但需要已安装 Claude CLI。

### 2. 创建研究项目

一个"项目"定义了你的一个研究方向。每个项目有自己的关键词、分类和开放问题。

#### 基本创建

```bash
python tools/research/research_scout.py init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "error recovery" "benchmarking" \
    --categories "cs.RO" "cs.AI"
```

参数说明：
- `robot-manipulation`：项目 ID（小写字母、数字、连字符）
- `--title`：项目标题（显示在报告中）
- `--keywords`：搜索关键词（会用 OR 组合搜索）
- `--categories`：arXiv 分类代码（常用的如 `cs.RO` 机器人、`cs.LG` 机器学习、`cs.CV` 计算机视觉、`cs.AI` 人工智能）

#### 从已有 overview 创建

如果你已经有一份研究概述文档，可以让 LLM 自动提取项目信息：

```bash
python tools/research/research_scout.py init my-project \
    --from-overview path/to/overview.md
```

LLM 会从文档中自动提取标题、关键词和开放问题。

#### 添加开放问题（可选但推荐）

开放问题帮助 LLM 更好地判断论文与你研究的相关性：

```bash
python tools/research/research_scout.py init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "grasping" \
    --categories "cs.RO" \
    --questions "如何让机器人在未知环境中进行稳定抓取？" \
                "视觉-触觉融合在操作任务中的最佳实践？"
```

#### 查看所有项目

```bash
python tools/research/research_scout.py list
```

#### 手动编辑项目

创建后可以直接编辑 `research/projects/<project-id>/project.json` 来修改关键词、分类、开放问题等。还可以编辑 `overview.md` 添加你的研究背景和当前进展（中文），这些信息会被 Stage 2 深度评估使用。

### 3. 搜索论文

搜索从配置的来源获取论文，不调用 LLM，速度很快。

#### 搜索单个项目

```bash
python tools/research/research_scout.py search --project robot-manipulation
```

默认搜索最近 7 天的论文（来自 arXiv），最多 50 篇。

#### 调整搜索范围

```bash
# 搜索最近 30 天
python tools/research/research_scout.py search --project robot-manipulation --lookback-days 30

# 最多返回 100 篇
python tools/research/research_scout.py search --project robot-manipulation --max-results 100
```

#### 搜索特定作者

```bash
python tools/research/research_scout.py search --author "Pieter Abbeel"
```

#### 搜索所有项目

```bash
python tools/research/research_scout.py search
```

不指定 `--project` 时，会搜索所有 `active` 状态的项目。

#### 忽略缓存

同一天对同一项目的搜索结果会被缓存。如需强制重新搜索：

```bash
python tools/research/research_scout.py search --project robot-manipulation --no-cache
```

### 4. 生成周报（完整管线）

这是最核心的命令。它会执行完整管线：**搜索 → 三阶段 LLM 评估 → 方向建议 → 生成周报**。

```bash
python tools/research/research_scout.py report --project robot-manipulation
```

#### 三阶段评估流程

```
50 篇论文（来自 arXiv / bioRxiv / PubMed）
    |
Stage 1: 快速筛选（1 次 LLM 调用，所有论文）
    |--- 每篇论文标注：动机、创新点、论文类型、机构
    |--- 分类为 "high"（高相关）或 "low"（低相关）
    |
    +--- 低相关论文 → 报告的"文献阅读记录"（折叠显示）
    |
    +--- 高相关论文（最多 20 篇）
            |
            Stage 2: 深度分析（1 次 LLM 调用）
                |--- 每篇论文 3 个亮点（关键点/设计动机/对我们的价值/行动建议）
                |--- 相关性/新颖性/启发性打分（1-5）
                |--- 综合得分 = 0.4×相关性 + 0.3×启发性 + 0.3×新颖性
                |--- 排序：综合得分降序，引用数作为同分时的 tiebreaker
                |
                Stage 3: 引用影响分析（自动执行，前 5 篇高分论文）
                    |--- 通过 Semantic Scholar 查找论文 ID
                    |--- 获取前向引用（被谁引用了，按引用数排序，前 20 篇）
                    |--- 获取反向参考文献（它引了谁，前 20 篇）
                    |--- LLM 分析："这篇论文为什么被广泛引用？后续工作沿什么方向？"
                |
                → 建议新研究方向
                → 自动更新项目 overview.md
                → 生成 Markdown 周报
                |
                [可选] 加 --insight 开启 Stage 4+5（详见第 5 节）
```

#### 选择 LLM 后端

```bash
# 使用 Anthropic API（需要 ANTHROPIC_API_KEY）
python tools/research/research_scout.py report --project robot-manipulation --api anthropic

# 使用 OpenAI API（需要 OPENAI_API_KEY）
python tools/research/research_scout.py report --project robot-manipulation --api openai

# 使用 Claude CLI（默认，无需 API key）
python tools/research/research_scout.py report --project robot-manipulation --api claude_cli
```

#### 选择输出语言

```bash
# 英文输出
python tools/research/research_scout.py report --project robot-manipulation --language en

# 中文输出（默认）
python tools/research/research_scout.py report --project robot-manipulation --language zh
```

#### 跳过缓存

评估结果会被缓存（Stage 1 和 Stage 2 分别缓存）。如需重新评估：

```bash
python tools/research/research_scout.py report --project robot-manipulation --no-cache
```

#### 生成报告同时部署

```bash
python tools/research/research_scout.py report --project robot-manipulation --deploy
```

### 5. 论文深度洞察（--insight）

在标准的三阶段评估之上，`--insight` 开启两个额外阶段，帮你真正**读懂**论文：

- **Stage 4：论文洞察分析**——下载全文，LLM 分析写作结构、发表策略、可复用知识
- **Stage 5：OpenReview 审稿意见**——自动匹配论文到 OpenReview，获取 reviewer 评分和评价，LLM 分析共识与争议
- **综合输出：研究写作指南**——跨论文综合分析，生成领域写作规范、审稿重点、方法论要点、代码参考

#### 基本用法

```bash
# 标准周报 + 深度洞察
python tools/research/research_scout.py report --project robot-manipulation --insight

# 搭配 ask 命令使用
python tools/research/research_scout.py ask "diffusion policy robot control" --insight

# 自定义分析论文数（默认 3 篇）
python tools/research/research_scout.py report --project robot-manipulation --insight --insight-top-n 5

# 部署到 Hugo
python tools/research/research_scout.py report --project robot-manipulation --insight --deploy
```

#### 处理流程

```
Stage 1-3 完成后（如第 4 节所述）
    |
    +--- 高相关论文（按 composite_score 排序）
            |
            取 top N 篇（默认 3，可通过 --insight-top-n 调整）
            |
            Stage 4: 论文洞察分析
                |
                [4a] 下载全文
                |    ├── arXiv: HTML 优先，PDF 后备（复用 arxiv_client.download_fulltext）
                |    ├── bioRxiv: 尝试 HTML 全文
                |    ├── PubMed: 降级为仅使用 abstract
                |    └── 截断到 40,000 字符（避免 LLM 上下文溢出）
                |
                [4b] LLM 三维度分析（单次调用）
                     ├── 写作结构：论证流程、章节模式、论证风格
                     ├── 发表要素：关键优势、定位策略、实验设计
                     └── 核心知识：核心洞察、可复用技术、实现提示
                |
            Stage 5: OpenReview 审稿意见
                |
                [5a] 论文匹配
                |    ├── 通过 fuzzy title matching 在 OpenReview 搜索
                |    ├── 覆盖 ICLR / NeurIPS / ICML 等主流会议
                |    └── 匹配失败 → 跳过（不影响 Stage 4 结果）
                |
                [5b] 获取审稿意见
                |    └── 评分、置信度、strengths、weaknesses、questions
                |
                [5c] LLM 共识分析
                     ├── 0 条 review → 跳过
                     ├── 1 条 review → 单 reviewer 摘要
                     ├── 2 条 review → 有限共识分析
                     └── 3+ 条 review → 完整共识/争议分析
                |
            综合：研究写作指南
                |--- LLM 综合所有论文的洞察 + 审稿意见
                |--- 输出四个板块：
                |    ├── 领域写作规范（论文该怎么写）
                |    ├── 审稿重点提示（reviewer 看什么）
                |    ├── 方法论要点（技术上能学到什么）
                |    └── 代码实现参考（怎么把想法变成代码）
                |
                → 报告中增加"论文深度洞察"和"研究写作指南"章节
```

#### 报告输出示例

启用 `--insight` 后，Markdown 周报中会多出两个章节：

**论文深度洞察** — 每篇被分析的论文包含：

```
#### [2503.12345] Paper Title

**写作结构**:
- 论证流程: Problem → Gap → Hypothesis → Method → Experiments → Ablation → Discussion
- 章节模式: Introduction → Related Work → Preliminary → Method → Experiments → Conclusion
- 论证风格: 实验驱动，大量消融研究验证设计选择

**发表要素**:
- 优势: 首次在 X 任务上超越人类水平
- 优势: 提出通用框架，适用于多种场景
- 定位策略: 填补了 X 和 Y 之间的鸿沟
- 实验设计: 6 个数据集、3 个强基线、完整消融

**核心知识**:
- 洞察: 关键发现是 X 和 Y 之间的 trade-off 可以通过 Z 解决
- 可复用技术: 提出的 attention mask 策略可以直接用于其他任务
- 实现提示: 学习率需要 warmup 1000 步，batch size 对结果影响很大

**审稿意见** (3 reviewers):
- 平均评分: 6.7 / 10
- 共识优点: 实验全面，方法有理论支撑
- 共识问题: 计算成本未讨论，缺少与最新方法的比较
- 争议点: Reviewer 2 认为 novelty 有限，Reviewer 3 强烈反对
- 关键建议: 增加计算效率分析和更多 baseline 比较
```

**研究写作指南** — 跨论文综合：

```
**领域写作规范**
该领域论文普遍采用"问题定义→方法→理论分析→实验验证"的四段式结构。
Introduction 部分通常用 1-2 段描述现实场景，然后明确指出现有方法的 gap...

**审稿重点提示**
Reviewer 最看重的三个方面：(1) 实验的全面性和公平性 (2) 与 state-of-the-art 的差距分析
(3) 方法的泛化性论证。常见的被拒原因包括...

**方法论要点**
三篇论文共同的技术趋势：(1) 用 diffusion model 做策略表示
(2) contrastive learning 用于特征对齐 (3) 混合精度训练加速...

**代码实现参考**
核心算法建议使用 PyTorch + Hydra 配置管理。Paper A 的关键创新点可以用
3 行代码实现：先计算 attention mask，然后...
```

#### OpenReview 配置

OpenReview 默认以 **guest 模式**（无需账号）运行，可以读取已公开的审稿意见。

如果想获取更多数据（如尚未公开的审稿），可以配置账号：

```bash
export OPENREVIEW_USERNAME="your@email.com"
export OPENREVIEW_PASSWORD="your_password"
```

> **支持的会议**：ICLR、NeurIPS、ICML、COLM 等使用 OpenReview 平台的会议。
> **不支持**：AAAI、CVPR、ICCV、ECCV 等使用其他审稿系统的会议（这些论文的 insight 分析仍然正常，只是没有审稿意见）。

#### 成本说明

`--insight` 是 **opt-in**（需要显式开启），因为它会增加额外的 LLM 调用：

| 分析类型 | LLM 调用次数 | 大约 token 消耗 |
|---------|------------|----------------|
| Stage 4: 洞察分析 | 每篇论文 1 次 | ~50K tokens/篇 |
| Stage 5: 审稿共识 | 有审稿的论文 1 次 | ~5K tokens/篇 |
| 写作指南综合 | 1 次（总） | ~20K tokens |
| **默认 3 篇总计** | **约 5-7 次** | **约 170-200K tokens** |

默认分析前 3 篇高分论文。通过 `--insight-top-n` 调整数量（会自动 cap 到不超过报告展示的论文数）。

#### 缓存

Insight 分析结果会被缓存（基于论文 ID + 内容哈希），重复运行同一项目不会重复调用 LLM。使用 `--no-cache` 可以强制重新分析。

缓存位置：`outputs/cache/research-scout/insight/`

### 6. 会议论文搜索

可以搜索特定会议（如 CVPR、ICRA、NeurIPS）的论文：

```bash
# 仅搜索 CVPR 2025 的论文
python tools/research/research_scout.py search --conference "CVPR 2025"

# 搜索 CVPR 2025 中与你项目相关的论文
python tools/research/research_scout.py search --conference "CVPR 2025" --project robot-manipulation

# 完整管线：会议论文 + 三阶段评估
python tools/research/research_scout.py report --conference "CVPR 2025" --project robot-manipulation
```

**原理**：arXiv 没有会议字段，但作者通常在 comment 中注明会议（如 "Accepted at CVPR 2025"）。工具会搜索 arXiv 全文，然后用 comment 字段二次过滤。

> **注意**：会议搜索不需要 `--lookback-days`，因为会议论文跨越固定时间段，使用相关性排序而非日期排序。`--conference` 和 `--author` 不能同时使用。

### 7. 多源搜索

除了 arXiv，还支持从 bioRxiv 和 PubMed 搜索论文：

```bash
# 同时搜索 arXiv 和 bioRxiv
python tools/research/research_scout.py search --project my-project --source arxiv biorxiv

# 搜索 PubMed
python tools/research/research_scout.py search --project my-project --source pubmed

# 三个来源全部搜索
python tools/research/research_scout.py search --project my-project --source arxiv biorxiv pubmed
```

也可以在 `project.json` 中配置默认搜索来源：

```json
{
  "id": "my-bio-project",
  "title": "...",
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience", "bioinformatics"],
  "pubmed_journals": ["Nature", "Science"]
}
```

> **注意**：bioRxiv 和 PubMed 搜索使用标准库（`urllib.request`、`xml.etree`），不需要额外依赖。

### 8. 自然语言搜索（ask 命令）

`ask` 命令接受自然语言查询，自动解析意图并路由到合适的搜索来源（作者 / 会议 / 期刊 / 主题）：

```bash
python tools/research/research_scout.py ask "找 Pieter Abbeel 最近的机器人操作论文"          # 作者 + 主题
python tools/research/research_scout.py ask "ICRA 2025 的灵巧手操作"                          # 会议搜索
python tools/research/research_scout.py ask "BMJ/Lancet 上最近的 AI 诊断论文"                 # 期刊搜索（自动 PubMed）
python tools/research/research_scout.py ask "sim-to-real transfer 在 legged robot 上的进展"  # 主题搜索
python tools/research/research_scout.py ask "找最近的 diffusion policy 机器人控制论文" --deploy  # + 部署
python tools/research/research_scout.py ask "diffusion policy robot control" --insight        # + 深度洞察
```

### 9. 研究者画像

分析一位研究者的学术轨迹：从 ArXiv 和 Semantic Scholar 获取论文数据，LLM 分析研究历程，计算评分和分层。

#### 基本用法

```bash
# 分析单个研究者（快速模式）
python tools/research/research_scout.py profile "Sergey Levine"

# 详细模式（会下载论文全文进行深度分析）
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed

# 分析多位研究者
python tools/research/research_scout.py profile "Sergey Levine" "Pieter Abbeel"

# 同名消歧：通过机构提示
python tools/research/research_scout.py profile "Wei Zhang" --affiliation "MIT"

# 反向查找：通过已知论文找作者
python tools/research/research_scout.py profile "Name" --paper "2301.12597"

# 直接指定 Semantic Scholar 作者 ID
python tools/research/research_scout.py profile "Name" --author-id "1234567"

# 提供研究者主页（用于发现学生）
python tools/research/research_scout.py profile "Sergey Levine" --homepage "https://..."
```

#### 递归发现学生

工具可以通过共著模式推断出师生关系，并递归分析发现的学生：

```bash
# 深度 1：分析 Sergey Levine 并发现其学生
python tools/research/research_scout.py profile "Sergey Levine" --depth 1

# 深度 2：进一步分析学生的学生（注意 API 调用量会指数增长）
python tools/research/research_scout.py profile "Sergey Levine" --depth 2
```

学生发现基于两个来源（自动合并去重）：

1. **主页提取**（优先）— 从 Semantic Scholar 主页字段或 LLM 推断的 URL 获取研究者主页，解析 HTML 提取学生名单。可通过 `--homepage` 手动提供 URL
2. **共著推断**（补充）— 基于以下信号打分：
   - 一作 + 导师末位的论文数（最强信号，权重 40%）
   - 合作时间集中在 3-6 年的 PhD 周期（25%）
   - 合著频率（20%）
   - 合作的时效性（15%）

#### 批量分析

```bash
# 从文件读取姓名（每行一个）
python tools/research/research_scout.py profile --from-file names.txt
```

#### 模型和后端选择

```bash
# 使用 Opus 模型（更深度的分析）
python tools/research/research_scout.py profile "Sergey Levine" --model opus

# 使用 Anthropic API 后端
python tools/research/research_scout.py profile "Sergey Levine" --api anthropic

# 忽略缓存
python tools/research/research_scout.py profile "Sergey Levine" --no-cache
```

#### 分析流程

```
研究者姓名 (+ 可选：--affiliation, --paper, --author-id, --homepage)
    |
[1/6] 从 ArXiv 获取论文（最多 100 篇）
    |
[2/6] 从 Semantic Scholar 获取指标（h-index、引用数、所有论文及引用数）
    |--- 合并 S2 和 ArXiv 数据（S2 为主，ArXiv 补充 arxiv_id、pdf_url 等）
    |--- 每年最多保留 10 篇代表作（按奖项和引用数排序）
    |
[3/6] LLM 识别论文奖项（Best Paper / Spotlight / Oral 等）
    |
[4/6] 下载全文（仅 detailed 模式；HTML 优先，PDF 后备）
    |
[5/6] LLM 分析研究轨迹
    |--- 轨迹总结：为什么成为领域大佬/新星，关键转折点
    |--- 突破性工作（3-7 项）：做了什么、为什么之前做不出来、对领域的影响
    |--- 研究方向、方法论演进、领域影响评估
    |
[6/6] 计算评分
    |--- 加权：h-index 25% + 总引用 20% + 近5年引用 20% + 顶会比例 20% + 职业阶段 15%
    |--- 分层：领域领袖(≥75) / 学术新星(≥50) / 活跃研究者(≥30) / 早期研究者(<30)
```

消歧提示参数说明：
- `--affiliation`：机构名称，用于同名作者消歧（如 "MIT"、"Stanford"）
- `--paper`：已知论文（arXiv ID、DOI 或标题），通过论文反向查找作者
- `--author-id`：直接指定 Semantic Scholar 作者 ID，跳过搜索
- `--homepage`：研究者主页 URL，用于发现学生（优先于自动发现）

#### 部署到 Hugo

```bash
# 分析后直接部署到 Hugo 站点
python tools/research/research_scout.py profile "Sergey Levine" --deploy
python tools/research/research_scout.py profile "Sergey Levine" --deploy --hugo-site /path/to/site
```

#### 输出

结果保存在 `outputs/` 目录下（项目根目录）：
- `outputs/data/research-profiler/profiles/<name>.json`：完整的结构化数据
- `outputs/reports/research-profiler/<name>.md`：Markdown 格式的研究者报告
- `outputs/cache/research-profiler/`：API + LLM 响应缓存

如果在 Profiler 配置中设置了自定义 `output_dir`，则所有文件统一放在该目录下。

也可以通过独立的模块 CLI 使用：

```bash
python -m research analyze "Sergey Levine"                  # 分析研究者
python -m research analyze "Sergey Levine" --api anthropic  # 选择后端（ollama/claude_cli/anthropic/openai）
python -m research show "Sergey Levine"                     # 查看已缓存的画像
python -m research list                                     # 列出所有已分析的研究者
python -m research config --init                            # 初始化 Profiler 配置
```

### 10. 引用图分析

对任意论文进行引用图分析：查看谁引用了它（前向引用）、它引用了谁（反向参考文献），以及 LLM 生成的影响力分析。

#### 基本用法

```bash
# 用 arXiv ID 查询
python tools/research/research_scout.py citations 2301.12597

# 用 DOI 查询
python tools/research/research_scout.py citations 10.1038/s41586-023-06221-2
```

#### 参数

```bash
# 显示前 20 篇引用/参考文献（默认 10）
python tools/research/research_scout.py citations 2301.12597 --top-n 20

# 使用 Anthropic API 进行影响力分析
python tools/research/research_scout.py citations 2301.12597 --api anthropic

# 忽略缓存
python tools/research/research_scout.py citations 2301.12597 --no-cache
```

#### 输出内容

```
论文信息
├── 标题、年份、会议、引用数
│
├── 前向引用（按引用数降序）
│   # | 年份 | 引用数 | 标题 | 会议
│
├── 反向参考文献（按引用数降序）
│   # | 年份 | 引用数 | 标题 | 会议
│
└── LLM 影响力分析（当引用数 ≥ 5 时自动触发）
    ├── 被广泛引用的原因
    ├── 后续研究方向
    └── 开创的趋势
```

数据来源于 Semantic Scholar API，支持缓存（7 天 TTL）。

> **注意**：引用图分析也会自动集成到周报的 Stage 3 中——前 5 篇高分论文会自动附带引用影响分析。

### 11. 部署到网站

将已生成的周报部署到 Hugo 博客：

```bash
# 部署所有未部署的报告
python tools/research/research_scout.py deploy

# 强制重新部署所有报告
python tools/research/research_scout.py deploy --force
```

需要在 `config --init` 中配置好 Hugo 站点路径。

### 12. 参数调优

参数的优先级为：**命令行参数 > project.json > config.json > 硬编码默认值**。

#### 全局默认值（config.json）

通过 `config --init` 或直接编辑仓库根 `config.json` 的 `research_scout` 段：

```json
{
  "default_api": "ollama",
  "hugo_site": "tools/website",
  "default_lookback_days": 7,
  "default_max_results": 50,
  "default_top_papers_in_report": 5,
  "max_high_relevance": 20,
  "default_insight_top_n": 3
}
```

可配置参数总览（Research Scout）：

| 参数 | Config key | 默认值 |
|------|-----------|--------|
| LLM 后端 | `default_api` | `ollama` |
| Hugo 站点路径 | `hugo_site` | `tools/website` |
| 回溯天数 | `default_lookback_days` | 7 |
| 最大搜索结果数 | `default_max_results` | 50 |
| 报告中展示的论文数 | `default_top_papers_in_report` | 5 |
| 最大高相关数 | `max_high_relevance` | 20 |
| 输出语言 | `--language`（仅 CLI） | `zh` |
| Insight top N | `default_insight_top_n` | 3 |
| 全文最大字符数 | （硬编码） | 40000 |

#### 项目级覆盖（project.json）

某些项目论文量大，可以单独配置。编辑 `research/projects/<id>/project.json`，添加可选字段：

```json
{
  "id": "robot-manipulation",
  "title": "Robot Manipulation",
  "lookback_days": 14,
  "max_results": 100,
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience"],
  "pubmed_journals": ["Nature Robotics"],
  ...
}
```

这样 `robot-manipulation` 项目默认搜索 14 天、最多 100 篇，而其他项目仍然使用全局默认。

#### 命令行临时覆盖

```bash
python tools/research/research_scout.py report --project robot-manipulation \
    --lookback-days 30 --max-results 200
```

命令行参数优先级最高，不会影响配置文件。

#### 研究者画像配置

Profiler 使用同一仓库根 `config.json` 的 `research` 段：

```json
{
  "model": "sonnet",
  "default_mode": "fast",
  "default_depth": 1,
  "max_students": 10,
  "output_dir": "",
  "semantic_scholar_api_key": ""
}
```

| 参数 | Config key | 默认值 |
|------|-----------|--------|
| Claude 模型 | `model` | `sonnet` |
| 分析模式 | `default_mode` | `fast` |
| 递归深度 | `default_depth` | `1` |
| 每层最大学生数 | `max_students` | `10` |
| 输出目录 | `output_dir` | `""`（空 = 使用默认 `outputs/` 结构） |
| S2 API key | `semantic_scholar_api_key` | （无） |

- `output_dir` 为空时使用默认的 `outputs/` 统一目录结构；设置后所有输出统一放在指定目录
- `semantic_scholar_api_key` 可选，免费匿名访问已有每秒 10 次请求限制

通过 `python -m research config --init` 初始化。

### 13. 工作流示例

#### 日常工作流：每周一次

```bash
# 1. 对所有项目生成周报（自动包含引用影响分析）
python tools/research/research_scout.py report

# 2. 想要深入理解本周最重要的论文？加 --insight
python tools/research/research_scout.py report --insight

# 3. 查看生成的报告
# Markdown 报告在 outputs/reports/research-scout/ 目录下
# 格式为 <date>-research.md

# 4. 部署到博客
python tools/research/research_scout.py deploy
```

#### 追踪新方向

```bash
# 1. 创建新项目
python tools/research/research_scout.py init diffusion-policy \
    --title "Diffusion Policy for Robotics" \
    --keywords "diffusion policy" "denoising diffusion" "robot learning" \
    --categories "cs.RO" "cs.LG" \
    --questions "扩散模型在机器人策略学习中的优势是什么？" \
                "如何加速扩散模型的推理速度以满足实时控制？"

# 2. 先搜索看看最近有多少相关论文
python tools/research/research_scout.py search --project diffusion-policy --lookback-days 30

# 3. 看着论文数量合适，生成完整报告
python tools/research/research_scout.py report --project diffusion-policy
```

#### 会议论文集中阅读

```bash
# ICRA 2025 中和机器人操作相关的论文
python tools/research/research_scout.py report \
    --conference "ICRA 2025" \
    --project robot-manipulation \
    --api anthropic
```

#### 了解一位研究者

```bash
# 1. 快速了解一位研究者
python tools/research/research_scout.py profile "Sergey Levine"

# 2. 想深入了解？用详细模式（会下载全文）
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed

# 3. 看看他的学生都在做什么
python tools/research/research_scout.py profile "Sergey Levine" --depth 1

# 4. 同名消歧
python tools/research/research_scout.py profile "Wei Zhang" --affiliation "Stanford"

# 5. 分析完直接部署到博客
python tools/research/research_scout.py profile "Sergey Levine" --deploy
```

#### 深入分析一篇论文的影响力

```bash
# 1. 看一篇论文的引用图
python tools/research/research_scout.py citations 2301.12597

# 2. 更多细节
python tools/research/research_scout.py citations 2301.12597 --top-n 20 --api anthropic
```

#### 写论文前的深度调研

```bash
# 1. 搜索相关论文
python tools/research/research_scout.py ask "sim-to-real transfer for legged robots" --insight

# 报告会包含：
# - 标准的论文筛选和评估
# - 每篇高分论文的写作结构分析（别人怎么写的）
# - 发表策略分析（为什么能发表）
# - 核心知识提取（能学到什么）
# - OpenReview 审稿意见（reviewer 怎么看的）
# - 综合写作指南（你该怎么写）

# 2. 指定项目 + 更多论文
python tools/research/research_scout.py report \
    --project my-project --insight --insight-top-n 5

# 3. 会议论文的写作风格调研
python tools/research/research_scout.py report \
    --conference "ICLR 2025" --project my-project --insight
```

#### 跨来源生物医学研究

```bash
# 1. 创建生物医学项目
python tools/research/research_scout.py init brain-computer \
    --title "Brain-Computer Interfaces" \
    --keywords "brain computer interface" "neural decoding" \
    --categories "q-bio.NC" "cs.HC"

# 2. 编辑 project.json，添加多来源配置
# "sources": ["arxiv", "biorxiv", "pubmed"],
# "biorxiv_categories": ["neuroscience"],
# "pubmed_journals": ["Nature Neuroscience", "Neuron"]

# 3. 生成跨来源报告
python tools/research/research_scout.py report --project brain-computer
```

### 14. 文件结构说明

```
research/
├── research_scout.py          # 主程序（统一 CLI 入口）
├── CLAUDE.md                  # 开发文档
├── TUTORIAL.md                # 本教程
├── requirements.txt           # Python 依赖
│
├── # ── 论文发现 ──
├── projects/                  # 项目定义（git 跟踪）
│   └── <project-id>/
│       ├── project.json       # 项目配置（关键词、分类、来源、开放问题）
│       └── overview.md        # 项目概述（中文，LLM 会读取）
│
├── # ── 研究者画像（模块包）──
├── __init__.py, __main__.py, cli.py
├── analysis.py                # 主编排器：BFS 递归分析
├── models.py                  # 数据类：Paper, ResearcherProfile, ...
├── scoring.py                 # 加权评分 + 分层
├── student_discovery.py       # 师生关系推断
├── homepage_discovery.py      # 主页提取 + 学生发现
├── llm.py                     # 多后端 LLM 封装
├── prompts.py                 # LLM 提示词模板
├── cache.py                   # 重导出 shim → common.cache.DiskCache
├── config.py                  # Profiler 配置
├── output.py                  # JSON 持久化 + Markdown 报告渲染 + Hugo 部署
├── apis/
│   ├── arxiv_client.py        # ArXiv 作者搜索 + 全文下载
│   ├── semantic_scholar.py    # S2 指标、论文数据、引用图、共著分析
│   ├── openreview_client.py   # OpenReview 审稿意见获取
│   └── rate_limiter.py        # 令牌桶限速器

outputs/                       # 所有生成文件（项目根目录下，已 gitignore）
├── reports/research-scout/    # Research Scout 周报
│   ├── <date>-research.json
│   └── <date>-research.md
├── cache/research-scout/      # Research Scout 缓存
│   ├── papers/                # 搜索结果缓存
│   ├── eval/                  # LLM 评估缓存（Stage 1 + Stage 2）
│   └── insight/               # Insight 分析缓存（Stage 4 + Stage 5）
├── logs/research-scout/       # 轮转日志 (5MB×3)
├── data/research-profiler/    # Profiler 结构化数据
│   └── profiles/              # JSON 研究者数据
├── reports/research-profiler/ # Profiler Markdown 报告
└── cache/research-profiler/   # Profiler 缓存（api/、llm/ 子目录）
```

#### 周报内容结构

生成的 Markdown 周报包含以下部分：

1. **高相关性论文摘要表** — 得分、标题、类型、一句话总结
2. **详细分析** — 每篇高相关论文的：
   - 评分（相关性/新颖性/启发性）
   - 两句话摘要
   - 3 个亮点，每个包含：关键点、设计动机、对我们的价值、行动建议
   - 建议
3. **引用影响分析**（前 5 篇高分论文自动附带）— 每篇包含：
   - 被引次数和参考文献数
   - 高引后续工作列表（年份、引用数、标题、会议）
   - LLM 影响力分析：为什么被广泛引用、后续方向、开创的趋势
4. **新方向建议** — 基于高分论文的研究方向建议（中文）
5. **论文深度洞察**（仅 `--insight`）— 每篇分析论文的写作结构、发表策略、核心知识、审稿意见
6. **研究写作指南**（仅 `--insight`）— 跨论文综合：领域写作规范、审稿重点、方法论要点、代码参考
7. **文献阅读记录** — 折叠显示的低相关性论文列表（一行一篇：标题、类型、作者、会议、动机、创新点）

### 15. 常见问题

#### Q: 搜不到论文怎么办？

- 检查关键词是否太窄，尝试更通用的词
- 增大 `--lookback-days`（比如 30 天）
- 检查 arXiv 分类是否正确（`cs.RO` 而非 `csRO`）
- 用 `--no-cache` 排除缓存问题
- 尝试多来源搜索：`--source arxiv biorxiv pubmed`

#### Q: 评估结果不理想？

- 编辑 `overview.md`，添加更多研究背景和当前进展。Stage 2 会读取这些内容来做更精准的评估
- 修改 `project.json` 中的 `open_questions`，让 LLM 更清楚你关心什么
- 尝试不同的 LLM 后端（`--api anthropic` vs `--api claude_cli`）
- 尝试英文输出：`--language en`

#### Q: LLM 调用超时？

- 默认超时 600 秒（10 分钟），可以用 `--timeout 900` 增加
- 减少 `--max-results` 以减少论文数量（Stage 1 单次筛选调用在 ~100 篇时容易超时，建议把 `--max-results` 控制在 ~50 以内，或相应提高 `--timeout`）
- 使用 `--api anthropic` 通常比 `claude_cli` 更稳定

#### Q: 如何暂停/恢复项目？

编辑 `research/projects/<id>/project.json`，将 `status` 从 `"active"` 改为 `"paused"`。暂停的项目不会被全局搜索/报告命令处理，但可以通过 `--project` 显式指定。

#### Q: 缓存机制是什么？

- **搜索缓存**（`outputs/cache/research-scout/papers/`）：同一天、同一项目的搜索结果只调用一次 API
- **Stage 1 缓存**（`outputs/cache/research-scout/eval/`）：基于项目上下文 + 论文 ID + 摘要前 200 字的哈希
- **Stage 2 缓存**（`outputs/cache/research-scout/eval/`）：基于项目上下文 + 论文 ID + 摘要前 500 字的哈希
- **Stage 3 引用缓存**（Semantic Scholar 引用图）：周报 Stage 3 的前向引用/反向参考文献也会缓存
- **Semantic Scholar 缓存**（Profiler: `outputs/cache/research-profiler/api/`）：API 结果缓存 7 天 TTL
- **LLM 缓存**（Profiler: `outputs/cache/research-profiler/llm/`）：基于后端 + 模型 + 提示词的 SHA-256 哈希
- 用 `--no-cache` 可以跳过所有缓存（包括 Stage 3 引用缓存）

#### Q: 研究者画像的 profile 和 citations 子命令有什么区别？

- `profile` 分析一位**研究者**：学术轨迹、评分、师生关系
- `citations` 分析一篇**论文**：引用图、影响力

#### Q: --insight 分析了哪些论文？

默认分析 composite_score 最高的 3 篇论文。可以通过 `--insight-top-n` 调整，但不会超过报告中展示的论文数（默认 5）。

#### Q: OpenReview 匹配不到怎么办？

OpenReview 匹配基于 fuzzy title matching（相似度阈值 0.85）。以下情况可能匹配失败：
- 论文不在 OpenReview 平台上的会议（如 CVPR、AAAI）
- 论文还未提交到会议（纯 arXiv 预印本）
- arXiv 标题和投稿标题差异较大

匹配失败不会影响 Stage 4 的洞察分析，只是没有审稿意见部分。

#### Q: --insight 太慢了？

全文下载 + LLM 分析每篇论文需要 1-3 分钟。可以：
- 减少分析数量：`--insight-top-n 1`
- 使用更快的 API：`--api anthropic`（通常比 claude_cli 快）
- 全文和 insight 分析结果会被缓存，第二次运行同一项目会很快

#### Q: 需要安装 openreview-py 吗？

`openreview-py` 是可选依赖。如果未安装，Stage 5（审稿意见）会自动跳过，Stage 4（洞察分析）和写作指南仍然正常工作。

安装：`pip install openreview-py`

#### Q: 如何获取 Semantic Scholar API Key？

访问 https://www.semanticscholar.org/product/api 申请。免费版已有每秒 10 次的请求限制，对于个人使用通常够用。API Key 可以在 Profiler 的 `config --init` 中配置，也可以不配置（使用匿名访问）。

## Benchmark

本教程将带你从零开始使用这个跨平台 CPU/GPU 基准测试工具。

### 1. 环境准备

#### 安装依赖

```bash
cd tools/benchmark
pip install -r requirements.txt
```

核心依赖：`torch`、`numpy`、`pandas`、`plotly`、`tqdm`。

也可手动安装：

```bash
pip install torch numpy pandas plotly tqdm
```

可选依赖：

- `threadpoolctl` — 精确控制 BLAS 线程数（影响 CPU 全核测试准确性）
- `pyopencl` — Intel/AMD GPU 支持（CUDA 和 MPS 之外的后备方案）

```bash
pip install threadpoolctl  # 精确 BLAS 线程控制
pip install pyopencl       # Intel/AMD GPU 后备支持
```

#### 验证安装

```bash
python -m benchmark.cli --info
```

这条命令会打印检测到的 CPU、GPU 和软件版本信息，不会运行任何基准测试。如果能看到你的硬件信息，说明环境配置正确。

### 2. 运行第一次基准测试

#### 快速体验（约 2 秒）

```bash
python -m benchmark.cli --cpu-only --matrix-size 1024 --duration 1 --no-save
```

这会只跑 CPU 测试，矩阵大小 1024，每项测试 1 秒，不保存结果。适合确认一切正常。

#### 标准测试

```bash
python -m benchmark.cli
```

这会运行所有 CPU 和 GPU 基准测试（每项默认 10 秒），结果自动追加到 CSV 文件。

测试项目：

- **CPU Single-Core** — 纯 Python 标量运算（`sqrt + add` 循环），衡量单核性能
- **CPU Single-Core BLAS** — NumPy 矩阵乘法（单线程），衡量 BLAS 库性能
- **CPU All-Cores BLAS** — NumPy 矩阵乘法（全核），衡量多核并行性能
- **GPU** — PyTorch 矩阵乘法，对每种支持的精度（FP64/FP32/FP16/BF16）分别测试

#### 只测 CPU 或 GPU

```bash
python -m benchmark.cli --cpu-only
python -m benchmark.cli --gpu-only
```

#### 示例输出

```
============================================================
Cross-Platform CPU/GPU Benchmarking Tool
============================================================

============================================================
System Information
============================================================

CPU: AMD EPYC 7513 32-Core Processor
  Cores: 128
  Frequency: 2.0 GHz
  Architecture: x86_64

GPU(s): 1 detected
  [0] NVIDIA RTX 4090
      Memory: 24 GB
      Backend: cuda
      Compute: 8.9

Software:
  OS: Linux 5.15.0-119-generic
  Python: 3.10.16
  PyTorch: 2.10.0+cu130
  CUDA: 13.0
============================================================

Running CPU benchmarks...
  [1/3] Single-core (scalar operations)...
       Result: 120.83 GFLOPS/s
  [2/3] Single-core BLAS (matrix multiplication)...
       Result: 291.18 GFLOPS/s
  [3/3] All-cores BLAS (matrix multiplication)...
       Result: 491.80 GFLOPS/s
✓ CPU benchmarks complete.

Running GPU benchmarks...
  Detected 1 device(s) with 1 backend(s)

  [NVIDIA GeForce RTX 4090]
    [1/5] FP64... ✓ 1.18 TFLOPS/s
    [2/5] FP32... ✓ 52.84 TFLOPS/s
    [3/5] FP16... ✓ 141.04 TFLOPS/s
    [4/5] BF16... ✓ 143.20 TFLOPS/s
    [5/5] FP8_exp... ✗ (not supported)
✓ GPU benchmarks complete.

Results saved to: outputs/data/benchmark/results.csv
Total records in file: 8
```

### 3. 理解测试结果

运行结束后，终端会显示类似输出：

```
CPU Single-Core
  Performance: 123.45 MFLOPS/s

CPU All-Cores BLAS (8 threads, 4096x4096)
  Performance: 456.78 GFLOPS/s

GPU CUDA FP32 (NVIDIA RTX 4090, 8192x8192)
  Performance: 12.34 TFLOPS/s
```

**单位说明**：

- MFLOPS = 百万浮点运算/秒（CPU 标量）
- GFLOPS = 十亿浮点运算/秒（CPU BLAS）
- TFLOPS = 万亿浮点运算/秒（GPU）

#### FLOPS 计算方式

- 标量循环：`2 * iterations`（每次迭代一次 sqrt + 一次 add）
- 矩阵乘法（GEMM）：`2 * N^3 * iterations`（N 为矩阵大小）

#### 测量方法学

每项测试经过三个阶段：

1. **预热（Warmup）** — 运行 5–100 次迭代（依测试类型而定），让 CPU/GPU 达到稳定频率
2. **正式测量** — 在 `--duration` 时间窗口内反复运行 5–50 次迭代
3. **统计分析** — 取中位数（median），用 IQR 方法剔除异常值（`RobustTimer`）

GPU 测试会在每次迭代后显式调用 `torch.cuda.synchronize()` 或 `torch.mps.synchronize()` 以确保计时准确。

#### 默认测量参数

- **时长**：每项基准默认 10 秒
- CPU 单核标量：10,000,000 次标量迭代（sqrt + add）
- CPU BLAS：matrix_size 2048（单核）、4096（全核）
- GPU：matrix_size 8192（按显存自动调整）、50 次迭代

### 4. 生成 HTML 报告

```bash
# 运行测试 + 生成报告
python -m benchmark.cli --report

# 从已有 CSV 生成报告（不重新跑测试）
python -m benchmark.cli --report-only
```

报告包含：

- 硬件性能排行榜（Leaderboard）
- 不同硬件的对比柱状图
- 各精度的性能对比
- 历史趋势折线图

默认输出路径：

- CSV：`outputs/data/benchmark/results.csv`（相对于 gadget 项目根目录）
- HTML：`outputs/reports/benchmark/report.html`

#### 自定义输出路径

```bash
python -m benchmark.cli --output my_results.csv
python -m benchmark.cli --report-only --input-csv my_results.csv --report-output my_report.html
```

### 5. 积累多台硬件数据

CSV 使用**追加模式（append）**——每次运行结果都会追加到文件末尾，不会覆盖历史数据。这使得可以跨多台不同硬件累积并做历史追踪，报告会读取全部历史以生成排行榜和趋势图。

典型工作流程：

```bash
# 在机器 A 上运行
python -m benchmark.cli --output shared_results.csv

# 把 shared_results.csv 复制到机器 B 上
# 在机器 B 上运行（结果追加到同一文件）
python -m benchmark.cli --output shared_results.csv

# 生成包含所有硬件的对比报告
python -m benchmark.cli --report-only --input-csv shared_results.csv
```

报告会自动展示所有曾经测试过的硬件。

### 6. 调优测试参数

#### 调整测试时长

```bash
# 快速测试（每项 3 秒）
python -m benchmark.cli --duration 3

# 高精度测试（每项 1 分钟）
python -m benchmark.cli --duration 60

# 论文级精度（每项 5 分钟）
python -m benchmark.cli --duration 300
```

更长的测试时间 = 更多采样 = 更稳定的结果。默认 10 秒对日常使用足够。

#### 调整矩阵大小

```bash
# 较小矩阵（适合低显存 GPU 或快速测试）
python -m benchmark.cli --matrix-size 4096

# 较大矩阵（充分利用高端 GPU）
python -m benchmark.cli --matrix-size 16384
```

GPU 矩阵大小会根据显存自动调整，但可以手动覆盖。

#### 其他常用选项

```bash
# 运行但不保存到 CSV
python -m benchmark.cli --no-save

# 静默模式（最少输出）
python -m benchmark.cli --quiet

# 详细模式（详尽输出）
python -m benchmark.cli --verbose
```

### 7. 部署到网站

如果你配置了 Hugo 网站（`gadget/website/`），可以直接部署报告：

```bash
# 运行测试 + 生成报告 + 部署到 Hugo
python -m benchmark.cli --report --deploy

# 只部署已有报告
python -m benchmark.cli --report-only --deploy
```

部署会将 HTML 报告复制到 `tools/website/static/benchmark-report/`，并生成 `content/benchmark.md` wrapper 页面，然后触发网站构建（`common.hugo.run_hugo_update()`）。

### 8. 提交结果到公共排行榜

如果有配置 relay 服务器，可以把测试结果提交到公共排行榜：

```bash
# 运行测试后交互式询问是否上传（默认 No）
python -m benchmark.cli --relay-url https://relay.example.com/submit

# 自动上传（适合脚本/CI）
python -m benchmark.cli --upload --relay-url https://relay.example.com/submit

# 也可以用环境变量
export BENCHMARK_RELAY_URL=https://relay.example.com/submit
python -m benchmark.cli

# 显式禁用上传流程
python -m benchmark.cli --no-upload
```

注意事项：

- 上传提示仅在启用保存的基准运行后出现（`--no-save` 会禁用它）。
- 上传失败不会影响本地测试结果。
- `--report-only` 和 `--info` 不会触发上传行为。

#### 手动提交

```bash
# 预览要提交的数据（取 CSV 最后一行）
python scripts/submit_result.py --dry-run

# 提交 CSV 中最后一行到 relay 端点
python scripts/submit_result.py --relay-url https://relay.example.com/submit

# 受信任的直接 GitHub dispatch（需要 token）
python scripts/submit_result.py \
  --github-owner YOUR_ORG \
  --github-repo YOUR_REPO \
  --github-token "$GITHUB_TOKEN"
```

#### 本地测试 Ingestion

```bash
python scripts/ingest_submissions.py \
  --pending-file data/pending_submissions.ndjson \
  --csv-path benchmark_results.csv \
  --rejected-file data/rejected_submissions.ndjson \
  --log-file data/ingest_log.json
```

队列/审计文件：

- `data/pending_submissions.ndjson`：原始排队投稿
- `data/rejected_submissions.ndjson`：被拒记录及原因
- `data/ingest_log.json`：最近一次 ingest 摘要

`ingest_submissions.py` 的校验规则：

- 必须包含全部 20 个 CSV 列
- `backend` 在 `{cpu, cuda, mps, xpu, opencl, ocl}` 中
- `benchmark_type` 在 `{gpu, cpu_single_core, cpu_single_core_blas, cpu_all_cores}` 中（或 `cpu_*` 前缀）
- 数值范围检查（如 `cpu_cores` 1–2048、`flops_gflops` > 0、`time_seconds` < 3600）
- PII 脱敏：邮箱、IP、主机名、用户路径会被遮蔽
- SHA-256 指纹去重（基于 日期 + 硬件 + 基准类型 + 结果）

#### Website 自动更新流水线

仓库内含一套基于 GitHub 的流水线，把基准报告发布为网站并从排队投稿持续更新：

- `.github/workflows/accept-submission.yml` — 接收 `repository_dispatch` 事件 `benchmark_submission`，把 payload 追加到 `data/pending_submissions.ndjson`
- `.github/workflows/daily-publish.yml` — 每日（`00:00 UTC`）或手动运行：以严格校验/去重/脱敏方式消费队列，数据集变化时重新生成报告
- `.github/workflows/pages-deploy.yml` — 把基准报告部署到 GitHub Pages

GitHub 配置清单：

- 启用 **GitHub Pages**，source 设为 **GitHub Actions**
- 确保 workflow 权限允许 Actions 对仓库写入
- 若使用直接 dispatch，需用能调用 repository dispatch 事件的 token
- 对外公开收集时，运行单独的 relay 服务做校验/限流并把 payload 转发到 `repository_dispatch`

### 9. GPU 后端兼容性速查

| 精度    | CUDA (NVIDIA) | MPS (Apple) | XPU (Intel) |
|---------|:---:|:---:|:---:|
| FP64    | ✓   | ✗   | ✓   |
| FP32    | ✓   | ✓   | ✓   |
| FP16    | ✓   | ✓   | ✓   |
| BF16    | ✓   | ✗   | ✓   |
| FP8_exp | ✓*  | ✗   | ✗   |

\* FP8 需要 CUDA 8.9+，PyTorch 尚未完全支持。

平台支持矩阵：

| 平台     | CPU | GPU (NVIDIA) | GPU (Apple) | GPU (Intel) | GPU (AMD) |
|----------|-----|--------------|-------------|-------------|-----------|
| Linux    | ✓   | ✓ (CUDA)     | ✗           | ✓ (XPU/OCL) | ✓ (OCL)   |
| macOS    | ✓   | ✗            | ✓ (MPS)     | ✗           | ✗         |
| Windows  | ✓   | ✓ (CUDA)     | ✗           | ✓ (XPU/OCL) | ✓ (OCL)   |

MPS（Apple Silicon）不支持 FP64 或 BF16。FP8 matmul 需要 CUDA compute capability 8.9+ 与兼容的 PyTorch 构建，目前 PyTorch 尚未完全支持。

### 10. CSV 格式

CSV 文件以追加模式记录所有基准结果，包含以下列：

| 列 | 说明 |
|--------|-------------|
| `timestamp` | ISO 格式时间戳 |
| `cpu_model` | CPU 型号名称 |
| `cpu_cores` | CPU 核心数 |
| `cpu_frequency` | CPU 频率 (GHz) |
| `gpu_vendor` | GPU 厂商 (NVIDIA/Apple/Intel/AMD) |
| `gpu_model` | GPU 型号名称 |
| `gpu_memory_gb` | GPU 显存 (GB) |
| `gpu_compute_capability` | Compute capability 版本 |
| `benchmark_name` | 基准名称 |
| `benchmark_type` | 类型 (cpu_single_core, cpu_all_cores, gpu) |
| `backend` | 后端 (cpu/cuda/mps/xpu) |
| `dtype` | 数据类型 (FP64/FP32/FP16/BF16/FP8) |
| `matrix_size` | GEMM 基准的矩阵大小 |
| `flops_gflops` | 性能 (GFLOPS) |
| `time_seconds` | 每次迭代的中位时间 |
| `iterations` | 迭代次数 |
| `os` | 操作系统 |
| `python_version` | Python 版本 |
| `torch_version` | PyTorch 版本 |
| `cuda_version` | CUDA 版本（如适用） |

### 11. Python API

```python
from benchmark import get_system_info, cpu, gpu, core

# 获取系统信息
system_info = get_system_info()

# 运行 CPU 基准
cpu_results = cpu.run_all_cpu_benchmarks()

# 运行 GPU 基准
gpu_results = gpu.run_all_gpu_benchmarks()

# 保存到 CSV
results_manager = core.BenchmarkResults('output.csv')
for result in cpu_results + gpu_results:
    results_manager.add(result, system_info)
results_manager.save()
```

### 12. 获取稳定结果的建议

- 关闭后台应用程序，减少干扰
- 确保设备散热良好（热节流会降低性能）
- 使用较长的 `--duration`（60 秒以上）
- 多次运行取最佳值——CSV 追加模式会保留所有历史数据，报告自动取最优
- 笔记本电脑请接电源运行
- GPU 支持取决于 PyTorch 是否安装了对应后端

## Website

Hugo 博客（PaperMod 主题）的完整构建与部署教程：从本地模型翻译、Markdown 重写、增量媒体压缩、预检，到 Hugo 构建和 GitHub Pages 推送——生成内容与手写内容共用单一内容根。

### 安装依赖

```bash
# 安装 website 运行时依赖（翻译依赖随 website 组自动安装：torch + transformers）
pip install -e ".[website]"
# 模型 tencent/Hy-MT2-1.8B 在首次运行时自动下载
```

外部工具依赖：

- **Hugo extended**（v0.125.7+）
- **Python 3 + PIL/Pillow** —— `compress_image.py` 的 JPEG→PNG 转换
- **Python torch + transformers** —— 翻译；Linux 可选 vLLM 加速批量推理
- **pngquant** —— 图片压缩
- **HandBrakeCLI** —— 视频压缩

平台说明：

- **Windows**：用 `update.ps1` 代替 `update.sh`；当 `pngquant` 或 `HandBrakeCLI` 未安装时自动跳过图片/视频压缩；使用 `python`（不是 `python3`）。
- **macOS/Linux**：用 `update.sh`，压缩步骤需要 `pngquant` 和 `HandBrakeCLI`。

### 一键构建 + 部署

所有命令都在 `tools/website/` 目录下执行：

```bash
cd tools/website

bash update.sh                                        # macOS/Linux
powershell -ExecutionPolicy Bypass -File update.ps1   # Windows
```

`update.sh` 是一条八步顺序流水线（下一节详述）。其中内容翻译、Hugo 构建、推送都自动完成；`.last_build` 时间戳保证只处理变更过的文件。`content/` 与 `static/` 是**单一 Hugo 根**——部署管线（summarize/research/benchmark）把生成内容直接写入其中并打上 `gadget_generated: true` frontmatter 标记；手写内容在同一棵树里、无标记，管线绝不覆盖。

### 构建流水线（`update.sh` 八步）

1. **内容翻译** —— `translate_site_batch.py --root content --state-file .translation_state.json` 回填整个内容树（生成 + 手写）下缺失或变更的 `*.md` / `*.zh.md` 配对，用本地批量推理（`tencent/Hy-MT2-1.8B`）。完整有效的配对免费登记/跳过；翻译阶段失败不阻断后续构建。
2. **Markdown 重写** —— 对自 `.last_build` 以来修改过的**手写** `.md` 文件：把 `../../static` 替换为站点 URL（从 `config.yml` 的 `baseURL` 读取）、把 `.jpg`/`.jpeg` 扩展名改为 `.png`、把本地视频链接转换为 Hugo `{{< video >}}` 短代码。生成目录（bugJournal daily/weekly/monthly、research）及 `benchmark*.md` 被排除——管线输出的 URL 已经正确。
3. **图片压缩** —— 对自 `.last_build` 以来更新的图片，并行运行 `compress_image.py`（未装 `pngquant` 则跳过）。
4. **视频压缩** —— 对更新的视频并行运行 `compress_video.py`，无脚本时回退到 `HandBrakeCLI`（未装且无脚本则跳过）。
5. **Preflight 检查** —— `preflight_check.py` 校验修改过的手写内容的图片/链接/frontmatter/双语/语言（生成目录被排除）；发现阻断性错误（exit 1）则终止构建。
6. **清理并重建 `public/`** —— 清空 `public/`（保留 `.git`），运行 `hugo`。
7. **提交并推送** —— `cd public && git add -A`，有变更时 `git commit && git push`（首次推送用 `git push -u origin <branch>`），随后 `git gc --aggressive`。
8. **更新时间戳** —— `touch .last_build`，供下次增量运行。

> `.last_build` 记录已处理内容。删除它可强制全量重建。

### 本地预览（dev server）

```bash
cd tools/website
hugo server -D          # 含草稿（draft），本地热重载预览
hugo                    # 仅构建，不部署
```

### 增量翻译状态（`translate_site_batch.py`）

`translate_site_batch.py` 增量同步英文/中文 Hugo markdown 配对，专为 `update.sh` 构建前调用设计：

- 两种规范文件形态：英文/默认 `foo.md`，中文 `foo.zh.md`。
- 回填缺失的对应文件；检测自上次成功同步以来哪一侧发生改动。
- 通过本地状态文件 `.translation_state.json` 避免 en↔zh 翻译来回乒乓。
- 翻译用本地推理（Linux 用 vLLM，Windows 用 transformers）。

常用参数：`--root <目录>`（翻译根）、`--state-file .translation_state.json`（状态文件）、`--exclude <路径>`（排除某分区，可多次传入）。

### 预检（`preflight_check.py`）

在媒体压缩（Step 6）与 Hugo 构建（Step 8）之间运行，检查自 `.last_build` 以来修改过的文件：

1. 未压缩图片（残留的 `.jpg`/`.jpeg`）
2. 失效链接（未重写的 `../../static` 引用）
3. frontmatter YAML 合法性
4. 双语配对完整性（`.md` ↔ `.zh.md`）—— 自动生成缺失的配对
5. 语言正确性（`.md` 应为英文正文，`.zh.md` 应为中文正文）—— 自动修复

语言感知的配对生成（检查 4）：

- `foo.md` 存在且为中文内容 → 复制为 `foo.zh.md`，并把 `foo.md` 翻译成英文
- `foo.md` 存在且为英文内容 → 翻译生成 `foo.zh.md`
- `foo.zh.md` 存在且为英文内容 → 复制为 `foo.md`，并把 `foo.zh.md` 翻译成中文
- `foo.zh.md` 存在且为中文内容 → 翻译生成 `foo.md`

分级严重度：

- **BLOCK** → exit 1，终止构建（frontmatter 错误）
- **WARN** → 打印但继续构建（失效链接、未压缩图片）
- **FIX** → 通过翻译引擎自动修复（缺失配对、语言不匹配）

退出码：`0` = 干净；`1` = 阻断性错误；`2` = 仅警告。

### 生成内容（单一内容根）

没有 staging 层，也没有 `sync_staging.py`（2026-07 迁移中移除）。部署管线经 `common.site_staging` 直接写入站点树：

| 写入方 | website 目标 | 标记 |
|--------|----------------|------|
| `python -m summarize daily deploy` | `content/bugJournal/daily/` | `gadget:src-hash` + `gadget_generated` |
| `python -m summarize weekly deploy` / `generate --deploy` | `content/bugJournal/weekly/` + `static/images/weekly/` | 同上 |
| `python -m summarize monthly deploy` / `generate --deploy` | `content/bugJournal/monthly/` + `static/images/monthly/` | 同上 |
| `research_scout.py deploy` / profiler `--deploy` | `content/research/` | 同上 |
| `benchmark.cli --report --deploy` | `content/benchmark.md` + `static/benchmark-report/` | `gadget_generated` |

**无** gadget 标记的文件视为手写内容：管线拒绝覆盖（需显式 `--overwrite-human`）。`--force` 重新部署前会把旧的生成文件备份到 `outputs/backups/website-force/YYYYMMDD-HHMMSS/`（含记录 sha256/路径/归属的 `manifest.json`）。

### 内容创作

```bash
# 新建内容
hugo new bugJournal/2026-03-03.md
hugo new leetcode/problem-name.md

# 压缩单张图片（JPEG→PNG，用 pngquant）
python compress_image.py static/images/path/to/image.png

# 压缩单个视频（用 HandBrakeCLI，720p30，无音轨）
python compress_video.py static/videos/path/to/video.mp4
```

### 内容分区

| 分区 | 路径 | Archetype | 说明 |
|---------|------|-----------|-------------|
| bugJournal | `content/bugJournal/` | `archetypes/bugJournal.md` | 调试日志，含 daily/weekly/monthly 子分区 |
| benchmark | `content/benchmark.md` | n/a | 自动生成的 benchmark 包装页，指向最新 HTML 排行榜 |
| leetcode | `content/leetcode/` | `archetypes/leetcode.md` | 算法题解，含复杂度分析 |
| posts | `content/posts/` | `archetypes/default.md` | 博客文章和学习笔记 |

特殊页面（内容根目录）：`Resume.md`、`Search.md`、`Random.md`。

### 静态资源

- **图片**：`static/images/` —— 按日期文件夹组织，统一用 `.png`（JPEG 会被自动转换）。
- **视频**：`static/videos/` —— 按日期文件夹组织，用 `{{< video src="/videos/..." >}}` 短代码，不用 markdown 链接。
- **PDF**：`static/pdfs/`

### Hugo 配置（`config.yml`）

- **主题**：PaperMod（位于 `themes/PaperMod/`）
- **Goldmark unsafe 模式**：启用（markdown 中允许 raw HTML）
- **MathJax/LaTeX**：通过 `mathjax: true` 和 `math: true` 启用
- **搜索**：Fuse.js 驱动，需要 JSON 输出格式
- **Busuanzi**：页面访问计数器启用
- **Hugo 版本**：需 v0.125.7+ extended

### 关键约定

- Markdown 用绝对站点 URL 引用图片（`https://tzj2006.github.io/images/...`），不用相对路径 —— `update.sh` 会自动重写 `../../static` 引用。
- 视频嵌入用自定义短代码 `{{< video src="/videos/file.mp4" type="video/mp4" preload="auto" width="360" >}}`，不用标准 markdown。
- bug journal 文件名遵循 `YYYY-MM-DD.md` 日期格式。
- `update.sh` 中的注释为中文。

### Git 追踪规则

除非在下方追踪允许清单中，否则不要 `git add` `website/content/` 或 `website/static/` 下的任何内容。多数内容和静态资源是自动生成（部署管线写入，带 `gadget_generated` 标记）、外部同步（rclone `website` 类目），或属于独立仓库（`public/` 是 GitHub Pages 部署仓库，`themes/` 是克隆的 Hugo 主题）。

**关键追踪文件（非穷尽）**：`CLAUDE.md`、`config.yml`、`archetypes/`、`layouts/`、`assets/`、`content/Search.md`、`content/bugJournal/_index.md`、构建脚本（`update.sh`、`update.ps1`、`compress_*.py`、`preflight_check.py`、`translate_site_batch.py`）。

## Translator

Gradio 文档翻译器的完整使用步骤。它复用 `common` 的本地翻译引擎，对文字和文件做翻译并保留 Markdown 格式。本工具本身只是 UI 接线（`tools/translator/app.py`）+ 文件摄取（`tools/translator/core.py`），核心翻译逻辑在 `common/engine.py` 与 `common/translation.py`。

### 1. 安装

translator 的可选依赖 extra 为 `translator`，它包含 Gradio 和 GGUF 翻译栈（`gradio>=4.0.0` + `gadget[translation-gguf]`，即 `llama-cpp-python` + `huggingface-hub`）：

```bash
pip install -e ".[translator]"
```

如果想用其它后端，按需追加对应 extra：

```bash
pip install -e ".[translation]"        # transformers 后端（Windows 回退）：torch + transformers
# Linux 上额外手动安装 vLLM（更快的批量推理）：
pip install "vllm>=0.8"
```

> 默认模型 `tencent/Hy-MT2-1.8B`（GGUF 变体 `tencent/Hy-MT2-1.8B-GGUF`）会在首次使用时自动从 HuggingFace 下载。

### 2. 启动 GUI

```bash
python -m translator
```

它会调用 `tools/translator/app.py` 的 `main()`：先把 `127.0.0.1,localhost` 注入 `NO_PROXY` / `no_proxy`（绕过代理对 localhost 健康检查的拦截，否则 gradio 的 `launch()` 在 Windows 上可能报 `WinError 10061`），然后构建并 `launch()` Gradio 界面。启动后在浏览器打开提示的本地地址即可。

### 3. Gradio UI 用法

界面标题为 **Gadget Translate**，顶部三个下拉框 + 两个标签页。

顶部控制栏：

- **模型 Model**：模型下拉，默认选中列表第一项；首次选择某模型会下载并加载（7B / FP8 模型较大）。候选来自仓库根 `config.json` 的 `translator.models` 列表，没有配置时回退到内置默认列表（`tencent/Hy-MT2-1.8B`、`tencent/Hy-MT2-1.8B-FP8`、`tencent/Hy-MT2-7B`、`tencent/Hy-MT2-7B-FP8`）。
- **源语言 Source** / **目标 Target**：可选 `auto` / `zh` / `en`。
  - `auto` 源：按文本 CJK 比例自动检测（`common.translation.detect_language`）。
  - `auto` 目标：自动在 zh↔en 间翻转（检测到中文则译英，否则译中）。

#### 标签页「翻译 Translate」

- 左侧是多模态输入框 **原文 Source**：可直接粘贴/输入文字，也可拖入或选择文件。支持的文件类型：`.md` `.markdown` `.txt` `.pdf` `.docx` `.png` `.jpg` `.jpeg`（单文件）。
- 右侧 **译文 Translation** 显示结果。
- 点 **翻译 Translate** 按钮触发。提交规则：**有文件时文件优先**，否则用输入的文字；两者都空会提示「输入文字或拖入文件」。
- 文件翻译时，下方 **下载 Download** 会给出转换/翻译后的文档（命名为 `<原名>.<目标语言>.md`，写入系统临时目录）。
- 底部状态行显示进度与速度：成功为 `✅ <src> → <tgt> · <n> tok · <s>s · <r> tok/s`（速度只统计生成阶段，不含模型加载和 OCR 转换）；失败为 `❌ <错误信息>`（任何异常都被捕获并显示，不会让界面崩溃）。

文件处理细节（`tools/translator/core.py`）：

- `.txt` / `.md` / `.markdown`：直接按 UTF-8 读取。
- `.docx`：用 stdlib（`zipfile` + `xml`）直接读 `word/document.xml`，无依赖、对正文无损；`HeadingN` 样式转 `#`..`######`，表格拍平为单元格文本，图片/图形丢弃。（不走 marker，避免 docx→pdf 的 weasyprint 原生依赖。）
- `.pdf` / 图片：调用 `marker_single` CLI 做 OCR 转 Markdown，在 `deepseek-ocr` conda 环境里以子进程运行（让其 torch/surya 栈与本环境隔离）。需要 `conda` 在 PATH 上、且该环境装了 `marker-pdf`；否则状态行会给出明确报错（找不到 `conda`、超时、产出空 Markdown 等）。

#### 标签页「模型管理 Models」

增删翻译模型，填 HuggingFace repo id（形如 `org/Model-Name`）。改动即时生效并持久化到仓库根 `config.json` 的 `translator.models` 列表。

- **添加 Add**：填入 repo id 后点添加；空或重复为 no-op。
- **删除选中 Delete**：删除下拉选中的模型；若删空则回退到内置默认列表。

### 4. 后端与模型环境变量

翻译链路不走 `--api` 参数，而是由 `common.engine.create_engine()` 自动选后端。可用以下环境变量覆盖（在启动 `python -m translator` 前 export）：

| 环境变量 | 作用 |
|----------|------|
| `GADGET_TRANSLATION_MODEL` | 覆盖默认模型（HuggingFace repo id）。`llamacpp` 后端下用作 GGUF 模型 id。 |
| `GADGET_TRANSLATION_BACKEND` | 强制后端：`ollama` / `vllm` / `transformers` / `llamacpp`。留空则自动选择：默认模型的 Ollama 标签已拉取时优先 Ollama，否则有 vLLM 用 vLLM，否则有 llama-cpp 用 GGUF，再否则用 transformers。 |
| `GADGET_TRANSLATION_BATCH_SIZE` | 批量大小（默认 `0` = 自动按显存估算）。 |

translator 专属的微调环境变量（`tools/translator/core.py`）：

| 环境变量 | 默认 | 作用 |
|----------|------|------|
| `TRANSLATOR_MICRO_CHUNK_CHARS` | `1000` | 多段输入的微分块字符数（GPU 在 batch=1 时受启动开销限制，分块批处理是主要提速手段）。质量漂移时可调。 |
| `TRANSLATOR_CONTEXT_CHARS` | `3000` | 注入每个分块 prompt 的文档背景上限字符数，保持术语/指代一致；仅在分块数 >1 时生效，`0` 关闭。 |
| `TRANSLATOR_MARKER_ENV` | `deepseek-ocr` | 跑 `marker_single` 的 conda 环境名。 |
| `TRANSLATOR_MARKER_TIMEOUT` | `600` | marker OCR 子进程超时（秒）。 |

示例：

```bash
# 强制 transformers 后端 + 指定模型
GADGET_TRANSLATION_BACKEND=transformers GADGET_TRANSLATION_MODEL=tencent/Hy-MT2-1.8B python -m translator

# marker 装在别名环境时
TRANSLATOR_MARKER_ENV=my-ocr python -m translator
```

### 5. 低显存 GGUF 路径

GGUF 后端（`llama-cpp-python`）快、省显存、且不需要 PyTorch，适合显存紧张或没有 GPU 的机器。`pip install -e ".[translator]"` 已经包含 GGUF 栈（`translator` extra 依赖 `gadget[translation-gguf]`）。

显式走 GGUF：

```bash
# 强制 llamacpp 后端；默认用 GGUF 模型 tencent/Hy-MT2-1.8B-GGUF
GADGET_TRANSLATION_BACKEND=llamacpp python -m translator

# 指定 GGUF 模型
GADGET_TRANSLATION_BACKEND=llamacpp GADGET_TRANSLATION_MODEL=tencent/Hy-MT2-1.8B-GGUF python -m translator
```

不强制 backend 时，自动选择逻辑（`common/engine.py`）为：vLLM 可用 → vLLM；否则 llama-cpp 可用 → GGUF（当模型为默认模型时自动换成对应的 GGUF 变体）；否则 → transformers。

### 相关文件

- 入口：`tools/translator/__main__.py`
- UI：`tools/translator/app.py`
- 翻译/文件逻辑：`tools/translator/core.py`
- 模型列表：`tools/translator/models.py`（仓库根 `config.json` → `translator.models`）
- 共享引擎：`common/engine.py`、`common/translation.py`
