# Gadgets Tutorial

> Back to overview: [README.md](README.md) · 中文版: [docs/TUTORIAL.zh.md](docs/TUTORIAL.zh.md)

This is the **detailed usage guide** for the gadget toolkit, covering setup, step-by-step usage of the five tools (Summarize / Research / Benchmark / Website / Translator), plus cross-device data sync and new-machine onboarding. Each tool also keeps its own source docs (under `tools/<tool>/`); this file is their consolidated, unified entry point.

> All LLM tools accept `--api` to switch backends (`ollama` default / `claude_cli` / `anthropic` / `openai`); the translation path uses a local inference engine and does not go through `--api`.

## Table of Contents

- [Platform Tutorial: Installation, Data Sync, and Machine Onboarding](#platform-tutorial-installation-data-sync-and-machine-onboarding)
  - [Installation and Environment](#installation-and-environment)
  - [Data Sync: `scripts/sync.py`](#data-sync-scriptssyncpy)
  - [One-time Machine Onboarding: `scripts/onboard.py`](#one-time-machine-onboarding-scriptsonboardpy)
- [Summarize](#summarize)
  - [Directory structure](#directory-structure)
  - [Prerequisites](#prerequisites)
  - [Config file (recommended)](#config-file-recommended)
  - [Machine identity](#machine-identity)
  - [Workflow](#workflow)
  - [Full pipeline automation (auto)](#full-pipeline-automation-auto)
  - [Cloud-drive sync](#cloud-drive-sync)
  - [Weekly report](#weekly-report)
  - [Monthly summary](#monthly-summary)
  - [Charts](#charts)
  - [Hugo blog deployment](#hugo-blog-deployment)
  - [Supported conversation sources](#supported-conversation-sources)
  - [Daily report content](#daily-report-content)
  - [Key points of the data format and import contract](#key-points-of-the-data-format-and-import-contract)
  - [`--api` parameter description](#--api-parameter-description)
  - [Running tests](#running-tests)
  - [Common command cheat sheet](#common-command-cheat-sheet)
- [Research](#research)
  - [1. Initial Configuration](#1-initial-configuration)
  - [2. Creating a Research Project](#2-creating-a-research-project)
  - [3. Searching Papers](#3-searching-papers)
  - [4. Generating a Weekly Report (Full Pipeline)](#4-generating-a-weekly-report-full-pipeline)
  - [5. Paper Deep Insight (--insight)](#5-paper-deep-insight---insight)
  - [6. Conference Paper Search](#6-conference-paper-search)
  - [7. Multi-source Search](#7-multi-source-search)
  - [8. Natural-Language Search (ask command)](#8-natural-language-search-ask-command)
  - [9. Researcher Profiling](#9-researcher-profiling)
  - [10. Citation Graph Analysis](#10-citation-graph-analysis)
  - [11. Deploying to the Website](#11-deploying-to-the-website)
  - [12. Parameter Tuning](#12-parameter-tuning)
  - [13. Workflow Examples](#13-workflow-examples)
  - [14. File Structure Description](#14-file-structure-description)
  - [15. FAQ](#15-faq)
- [Benchmark](#benchmark)
  - [1. Environment Setup](#1-environment-setup)
  - [2. Running Your First Benchmark](#2-running-your-first-benchmark)
  - [3. Understanding the Results](#3-understanding-the-results)
  - [4. Generating an HTML Report](#4-generating-an-html-report)
  - [5. Accumulating Data from Multiple Machines](#5-accumulating-data-from-multiple-machines)
  - [6. Tuning Test Parameters](#6-tuning-test-parameters)
  - [7. Deploying to the Website](#7-deploying-to-the-website)
  - [8. Submitting Results to the Public Leaderboard](#8-submitting-results-to-the-public-leaderboard)
  - [9. GPU Backend Compatibility Cheat Sheet](#9-gpu-backend-compatibility-cheat-sheet)
  - [10. CSV Format](#10-csv-format)
  - [11. Python API](#11-python-api)
  - [12. Tips for Getting Stable Results](#12-tips-for-getting-stable-results)
- [Website](#website)
  - [Installing Dependencies](#installing-dependencies)
  - [One-Command Build + Deploy](#one-command-build--deploy)
  - [Build Pipeline (the ten steps of `update.sh`)](#build-pipeline-the-ten-steps-of-updatesh)
  - [Local Preview (dev server)](#local-preview-dev-server)
  - [Incremental Translation State (`translate_site_batch.py`)](#incremental-translation-state-translatesitebatchpy)
  - [Preflight (`preflight_check.py`)](#preflight-preflightcheckpy)
  - [Generated content (single content root)](#generated-content-single-content-root)
  - [Authoring Content](#authoring-content)
  - [Content Sections](#content-sections)
  - [Static Assets](#static-assets)
  - [Hugo Configuration (`config.yml`)](#hugo-configuration-configyml)
  - [Key Conventions](#key-conventions)
  - [Git Tracking Rules](#git-tracking-rules)
- [Translator](#translator)
  - [1. Installation](#1-installation)
  - [2. Launching the GUI](#2-launching-the-gui)
  - [3. Gradio UI Usage](#3-gradio-ui-usage)
  - [4. Backend and Model Environment Variables](#4-backend-and-model-environment-variables)
  - [5. Low-VRAM GGUF Path](#5-low-vram-gguf-path)
  - [Related Files](#related-files)

## Platform Tutorial: Installation, Data Sync, and Machine Onboarding

### Installation and Environment

#### Python and conda

- Requires **Python 3.10+**. The conda environment `AI` is recommended:

  ```bash
  conda activate AI
  ```

- Windows: use PowerShell or Git Bash. Forward-slash paths work in Python; use backslashes in the native shell.

#### Installing the common package and tool dependencies

Each tool has its own `requirements.txt`, which can be installed individually:

```bash
pip install -r tools/<tool>/requirements.txt
```

More commonly, use the editable install, which installs the `common/` package together with the individual tool packages:

```bash
pip install -e .              # Install only common/ and the tool package skeleton
pip install -e ".[all]"       # Install all tool dependencies (= summarize + research + benchmark + website)
```

Overview of the optional dependency extras in `pyproject.toml`:

| extra | Contents |
|-------|------|
| `summarize` | anthropic or openai; optional Node.js (ccusage / `@ccusage/codex` token stats), matplotlib (token usage charts) |
| `research` | arxiv, anthropic or openai, openreview-py; optional PyMuPDF (PDF text extraction in `--insight` mode). bioRxiv/PubMed use stdlib only |
| `benchmark` | torch, numpy, pandas, plotly, tqdm; optional threadpoolctl, pyopencl |
| `website` | Pillow (image processing), torch + transformers (translation); optional vLLM (Linux, faster batch inference), llama-cpp-python (GGUF backend) |
| `translation` | torch + transformers (`TransformersEngine`, Windows fallback; the default backend is Ollama, no extra deps) |
| `translation-gguf` | llama-cpp-python + huggingface-hub (`LlamaCppEngine`, low-memory GGUF, no PyTorch) |
| `translator` | gradio + translation-gguf (Gradio document translator) |
| `all` | summarize + research + benchmark + website |

Install a single extra as needed, for example:

```bash
pip install -e ".[summarize]"
pip install -e ".[translation]"        # Windows fallback translation backend (default is Ollama, no extra deps)
pip install -e ".[translation-gguf]"   # Low-memory GGUF backend
pip install -e ".[translator]"         # Gradio translator
```

> `build/` and `gadget.egg-info/` are artifacts generated by the editable install — already gitignored, do not commit.

#### Translation backends (local inference)

Bilingual content has its backend auto-selected by `common.engine.create_engine()`, and **does not go through `--api`**:

- Ollama (`OllamaEngine`, **default**) — no extra deps; auto-preferred when the tag is pulled (`ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF`)
- `pip install -e ".[translation]"` → torch + transformers (`TransformersEngine`, Windows fallback)
- Linux: optionally `pip install vllm>=0.8` → `VLLMEngine` (faster batch inference)
- `pip install -e ".[translation-gguf]"` → `LlamaCppEngine` (low-memory GGUF, no PyTorch)

Default model `tencent/Hy-MT2-1.8B` (GGUF variant `tencent/Hy-MT2-1.8B-GGUF`), auto-downloaded on first run. Override via:

- Model: `GADGET_TRANSLATION_MODEL` environment variable or `--model` CLI flag
- Backend: `GADGET_TRANSLATION_BACKEND` (`ollama` / `vllm` / `transformers` / `llamacpp`)
- Batch size: `GADGET_TRANSLATION_BATCH_SIZE`

#### LLM backends and `--api`

All LLM-using tools support the `--api` flag to switch backends:

| `--api` value | Backend | Required |
|-----------|------|------|
| `ollama` (default) | Local Ollama server, keyless | A running Ollama with the chat model pulled |
| `claude_cli` | Local Claude Code CLI | `claude` CLI installed and logged in |
| `anthropic` | Anthropic API | Environment variable `ANTHROPIC_API_KEY` |
| `openai` | OpenAI API | Environment variable `OPENAI_API_KEY` |

Related environment variables:

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — API access
- `GADGET_LLM_BACKEND` — globally override the default `--api` backend
- `SUMMARIZE_LOGS_DIR`, `SUMMARIZE_REPORTS_DIR` — override summarize default output paths

Config resolution order (consistent across all tools): CLI flag > environment variable > `config.json` > hardcoded default. Per-tool config files: summarize resolves `SUMMARIZE_CONFIG` env var > repo-local `tools/summarize/config.json` > `~/.config/summarize/config.json`; research uses `~/.config/research_scout/config.json` and `~/.config/research/config.json`. Each is creatable via the tool's `config --init`.

#### Tests

There is no repo-wide test runner; tests are organized per module and run with `pytest`:

```bash
pytest tools/summarize/tests/            # summarize: config, formatter, imports, summarizer, parsers
pytest tools/summarize/tests/test_config.py  # Single test file
pytest tools/research/tests/             # research: pipeline contract tests
```

Tests use `unittest.mock` to stub out model loading, inference, and LLM backends.

---

### Data Sync: `scripts/sync.py`

Centralized rclone-based personal data sync (to and from Google Drive). Configuration lives in `~/.config/gadget/sync.json`.

#### Subcommands

```bash
python scripts/sync.py push                      # Local → remote
python scripts/sync.py pull                      # Remote → local
python scripts/sync.py status                    # Show diff between local and remote (rclone check)
python scripts/sync.py config                    # View current configuration
python scripts/sync.py config --init             # Interactively initialize configuration
python scripts/sync.py bootstrap --remote gdrive:gadget  # One-click init for a new device (pull config + data)
```

#### Options

- `--dry-run` — preview only, no actual transfer; can be placed either before or after the subcommand (e.g. both `python scripts/sync.py --dry-run push` and `push --dry-run` work).
- `--category <name>` — sync only one category. Available categories: `summarize`, `website`, `research`, `test` (there is also a special top-level category `dag`, see below). Supported by `push`/`pull`/`status`.
- `--include-config` — on `push`, also back up the config files to the remote (for other devices to bootstrap).
- `--include-tokens` — on `push` / `bootstrap`, include the `tokens/` directory (which contains API keys).

Examples:

```bash
python scripts/sync.py push --category summarize        # Sync only the summarize category
python scripts/sync.py push --include-config            # Push data + back up config
python scripts/sync.py push --include-tokens            # Push data + back up tokens/
python scripts/sync.py status --category research       # Check only the research diff
python scripts/sync.py pull --dry-run                   # Preview pull
```

#### Sync category mapping

| Category | Synced contents (examples) |
|------|------------------|
| `summarize` | `outputs/logs/summarize`, `outputs/reports/summarize`, `outputs/images/summarize` |
| `website` | `tools/website/content/bugJournal/{daily,weekly,monthly}`, `tools/website/content/research`, `tools/website/static/images/{weekly,monthly}`, `tools/website/static/benchmark-report`, `tools/website/content/{leetcode,posts}` and several loose files (About.pdf, Resume.md/pdf, Random.md, benchmark.md/zh.md) |
| `research` | `outputs/cache/research-scout`, `tools/research/projects`, `outputs/reports/research-scout`, `outputs/logs/research-scout`, `outputs/{reports,data}/research-profiler` |
| `test` | `outputs/data/benchmark` (including `results.csv`) |
| `backups` | `outputs/backups/website-force`, `outputs/backups/summarize` (pre-overwrite backups) |

#### First-time configuration (`config --init`)

Asks interactively:

- The rclone remote base path (default `gdrive:gadget`)
- If `rclone` is not found on PATH, additionally asks for the rclone binary path (e.g. `~/.local/bin/rclone`)

Writes to `~/.config/gadget/sync.json`. If not configured separately, the script will also try to derive the remote base path from the summarize config.

#### One-click init for a new device (`bootstrap`)

```bash
python scripts/sync.py bootstrap --remote gdrive:gadget
python scripts/sync.py bootstrap --remote gdrive:gadget --include-tokens   # Also pull tokens/ (contains keys)
python scripts/sync.py bootstrap --dry-run
```

`bootstrap` proceeds in order: write a minimal `sync.json` → verify remote connectivity (`rclone lsd`) → pull the config files → (optionally `--include-tokens`) pull tokens → pull all data directories. `--remote` defaults to `gdrive:gadget`.

#### Special category `dag` (generate + deploy, not a GDrive sync)

The `dag` category has different semantics from rclone sync — it "generates + deploys the DAG site". It can only be used at the top level, without a subcommand:

```bash
STATICRYPT_PASSWORD='<your-password>' python scripts/sync.py --category dag
python scripts/sync.py --category dag --dry-run     # Only print the commands to be run and the target paths
```

It will:

1. Run `npx tsx ../ai-companion/scripts/build-dag-site.ts stage` (generate the overview + per-project detail pages → StatiCrypt encryption → land in `tools/website/static/dag/`), with the password passed in via the `STATICRYPT_PASSWORD` environment variable (never hardcoded);
2. Trigger the website publish (`tools/website/update.sh`, Hugo build and push to the `/dag/` path).

On `--dry-run`, it only prints the commands to be run, without actually generating or deploying.

---

### One-time Machine Onboarding: `scripts/onboard.py`

Repo-level one-time configuration: **fill in one YAML sheet, run the script once**. Each section has an `enabled:` toggle, so each machine runs only the steps it needs. Safe actions are applied automatically; high-risk actions (writing SSH private keys, pushing public keys to remotes, extra global npm) prompt for confirmation first unless `--yes` is added. Re-running skips already-completed steps (idempotent).

#### Three-step quick start

```bash
cp scripts/onboard.example.yaml tokens/onboard.yaml   # 1. Copy the template
# 2. Edit tokens/onboard.yaml, filling in each section (see below)
python scripts/onboard.py                             # 3. Run
```

By default reads `tokens/onboard.yaml` (gitignored); the template is `scripts/onboard.example.yaml`.

#### Command-line options

```bash
python scripts/onboard.py [--sheet PATH] [--only a,b] [--skip a,b]
                          [--dry-run] [--yes] [--no-verify]
                          [--verify-only] [--list]
```

- `--sheet PATH` — specify the sheet path (default `tokens/onboard.yaml`).
- `--only a,b` — run only these steps (comma-separated), overriding `enabled` in the sheet.
- `--skip a,b` — skip these steps.
- `--dry-run` — print the actions to be performed, without changing anything.
- `--yes` / `-y` — assume yes for all high-risk prompts.
- `--no-verify` — skip the readiness check at the end.
- `--verify-only` — run only the readiness check (without executing any steps).
- `--list` — list the registered steps and their enabled status in the sheet.

Registered steps (in order): `ssh`, `claude`, `install`, `gadgets`, `sync`. Without `--only`, the script runs all sections with `enabled: true` in the sheet. A single step failing does not interrupt the other steps.

#### Sheet sections

Every top-level section has an `enabled:` toggle. Each value is marked (required) or (optional); (optional) ones already come with usable defaults.

**`ssh`** — writes `~/.ssh/config` (wrapped in sentinel comments, modifying only its own block), optionally writes a private key, optionally pushes a public key to the remote:

```yaml
ssh:
  enabled: true
  hosts:
    - alias: gpu1                       # (required) afterwards you can `ssh gpu1`
      hostname: gpu1.example.edu        # (required)
      user: thomas                      # (required)
      port: 22                          # (optional) default 22
      identity_file: ~/.ssh/id_ed25519  # (optional) default ~/.ssh/id_ed25519
      install_private_key:              # (optional) RISKY (prompts for confirmation): write the private key to this machine; omit to skip
        from: tokens/keys/id_ed25519    # (required if install_private_key) repo-relative or absolute path
        to: ~/.ssh/id_ed25519           # (optional) default ~/.ssh/id_ed25519, chmod 600 (POSIX) / icacls (Windows)
      push_public_key: false            # (optional) RISKY (prompts for confirmation): append the public key to the remote authorized_keys; default false
      public_key: ~/.ssh/id_ed25519.pub # (optional) default identity_file + ".pub"
```

**`claude`** — installs the Claude/Codex CLI and writes Claude Code user-level auth (writes into the `env` of `~/.claude/settings.json`, **not** the repo's `.claude/settings.json`):

```yaml
claude:
  enabled: true
  install: true                         # npm i -g @anthropic-ai/claude-code (skipped if already installed)
  codex:
    install: true
    package: "@openai/codex"            # override when the package name differs
  auth_mode: api                        # (required) api | bedrock | platform_aws — only reads the matching block
```

`auth_mode` has three auth modes; only the corresponding sub-block is read (before applying, all env variables of the other modes are stripped first, to avoid the previous mode shadowing this one):

- **`api`** — direct connection to the Anthropic API:
  ```yaml
  api:
    ANTHROPIC_API_KEY: "sk-ant-..."     # (required if auth_mode=api)
  ```
- **`bedrock`** — via AWS Bedrock (sets `CLAUDE_CODE_USE_BEDROCK=1`):
  ```yaml
  bedrock:
    AWS_REGION: us-east-1               # (required if auth_mode=bedrock)
    AWS_PROFILE: ""                     # (optional) any one of PROFILE / access keys / bearer token suffices
    AWS_ACCESS_KEY_ID: ""
    AWS_SECRET_ACCESS_KEY: ""
    AWS_SESSION_TOKEN: ""
    AWS_BEARER_TOKEN_BEDROCK: ""
    ANTHROPIC_DEFAULT_OPUS_MODEL: ""    # (optional) e.g. us.anthropic.claude-opus-4-8
    ANTHROPIC_DEFAULT_SONNET_MODEL: ""
    ANTHROPIC_DEFAULT_HAIKU_MODEL: ""
    awsAuthRefresh: ""                  # (optional) top-level key in settings.json (a command string)
  ```
- **`platform_aws`** — Claude Platform on AWS (Anthropic-operated API, via AWS, **not** Bedrock, sets `CLAUDE_CODE_USE_ANTHROPIC_AWS=1`):
  ```yaml
  platform_aws:
    ANTHROPIC_AWS_WORKSPACE_ID: "wrkspc_..."  # (required if auth_mode=platform_aws)
    AWS_REGION: us-east-1                      # (required if auth_mode=platform_aws)
    ANTHROPIC_AWS_API_KEY: ""                  # (optional) or leave empty to rely on the AWS SigV4 credentials in the environment
    ANTHROPIC_AWS_BASE_URL: ""                 # (optional) corporate proxy
  ```

**`install`** — pip extras + ai-companion + Claude plugins + extra global npm:

```yaml
install:
  enabled: true
  ai_companion: true                    # npx tsx ../ai-companion/scripts/install.ts . --enforce (skills/hooks/harness, claude+codex)
  claude_plugins: []                    # RISKY (prompts for confirmation): list of `claude plugin install <id>`
  pip_extras: [all]                     # a subset of summarize/research/benchmark/website/translator/all; default [all]
  global_npm: []                        # RISKY (prompts for confirmation): extra `npm i -g` packages
```

**`gadgets`** — writes each tool's config JSON (omitting a tool skips it):

```yaml
gadgets:
  enabled: true
  summarize:                            # -> ~/.config/summarize/config.json
    device_name: ""                     # empty = hostname
    logs_dir: ""                        # empty = default (~/.claude + codex log directory)
    reports_dir: ""                     # empty = outputs/reports
    hugo_site: "tools/website"          # repo-relative Hugo site root
    rclone_remote: "gdrive:gadget/summarize"
    rclone_path: ""                     # empty = remote default
    default_api: claude_cli             # ollama | claude_cli | anthropic | openai; default: ollama
  research:                             # -> ~/.config/research/config.json
    model: sonnet
    default_mode: fast
    default_depth: 1
    max_students: 10
    output_dir: ""
    semantic_scholar_api_key: ""        # setting this can raise the rate limit
  research_scout:                       # -> ~/.config/research_scout/config.json
    default_api: claude_cli
    hugo_site: "tools/website"          # repo-relative Hugo site root
    default_lookback_days: 7
    default_max_results: 50             # recommended ~50 or fewer, to avoid screening timeouts
    default_top_papers_in_report: 5
    max_high_relevance: 20
    default_insight_top_n: 3
  benchmark: {}                         # no config file; only pip extra + import check
  translator: {}                        # no config file; only pip extra + import check
  website: {}                           # no config file; only pip extra + import check
```

**`sync`** — optional rclone bootstrap (reuses `scripts/sync.py`), off by default:

```yaml
sync:
  enabled: false                        # off by default; enable on a given machine as needed
  bootstrap: false                      # true runs python scripts/sync.py bootstrap
  remote: "gdrive:gadget"               # (required if sync enabled) rclone remote root
  include_tokens: false                 # RISKY (prompts for confirmation): also pull tokens/ (API keys)
```

#### Common invocation examples

```bash
python scripts/onboard.py --list                 # See which steps are enabled
python scripts/onboard.py --dry-run              # Dry run, changes nothing
python scripts/onboard.py --only ssh,claude      # Run only ssh and claude
python scripts/onboard.py --skip sync            # Run all enabled steps, but skip sync
python scripts/onboard.py --yes                  # Confirm all high-risk prompts
python scripts/onboard.py --verify-only          # Run only the readiness check at the end
```

#### Readiness check (verify)

Unless `--no-verify` is added, the script runs a readiness check at the end: it verifies whether the `claude` (required) / `codex` (optional) CLIs are on PATH, whether the Claude auth environment variables are written according to `auth_mode`, whether each SSH host is reachable, and whether the configured tool dependencies can be imported. `--verify-only` can run this check on its own (the exit code reflects whether there are any blocking failures).

## Summarize

A complete tutorial for the AI-conversation daily/weekly/monthly summarization tool. This tool automatically reads your daily conversations with AI (Claude Code / Codex / ChatGPT / generic JSON), calls an LLM API, and generates structured daily, weekly, and monthly summaries.

It supports a multi-device workflow: export the conversation logs on each machine, aggregate them via cloud-drive sync or manual copy, and generate the final daily report. Once you have accumulated enough daily reports, you can generate weekly reports and monthly trend summaries.

### Directory structure

```
summarize/                   # pip-installable package (python -m summarize)
├── __init__.py              # Package entry
├── __main__.py              # Unified CLI: python -m summarize {daily,weekly,monthly,auto}
├── config.py                # Config loading, path resolution, device name
├── remote.py                # rclone upload/download
├── parsers.py               # Conversation parsing (Claude Code / Codex / ChatGPT / generic)
├── usage.py                 # Token usage collection (ccusage 20.x per-source namespaced commands)
├── summarizer.py            # LLM summarization, chunking, hierarchical merge
├── formatter.py             # Markdown generation, importance ranking, Hugo integration, bilingual output
├── charts.py                # Token usage charts (matplotlib): three-subplot PNG (Tokens/Cost/Cache)
├── daily.py                 # Daily-report pipeline orchestration (export / merge / deploy / config)
├── cli.py                   # argparse setup + subcommand routing
├── auto.py                  # Full-pipeline automation: daily export → merge → weekly → monthly
├── monthly_summary.py       # Monthly summary (generate / list)
├── weekly_summary.py        # Weekly summary (generate / list)
├── daily_summary.py         # Backward-compat re-export shim (old import paths still work)
├── llm_backends.py          # Re-export shim → common/
├── requirements.txt         # Python dependencies
└── tests/                   # pytest test suite
    ├── test_imports.py      # Import-contract tests (must run after refactoring)
    ├── test_config.py       # Config logic tests
    ├── test_parsers.py      # Parser tests
    ├── test_formatter.py    # Formatter tests
    └── test_summarizer.py   # Chunking/prompt tests

outputs/                     # all generated files (under the project root, gitignored)
├── logs/summarize/          # Conversation logs from export (intermediate, syncable across devices)
├── reports/summarize/       # Daily + weekly + monthly reports
│   ├── 2026-02-13.json / .md              # Daily report
│   ├── 2026-W07-weekly.json / .md         # Weekly report
│   ├── 2026-02-monthly.json / .md         # Monthly report
├── images/summarize/        # Usage chart PNGs
│   ├── 2026-02-13-usage.png               # Daily three-subplot chart (Tokens/Cost/Cache)
│   ├── 2026-02-monthly-tokens.png         # Monthly token trend chart
│   └── 2026-02-monthly-cost.png           # Monthly cost trend chart
└── cache/summarize/         # LLM chunk cache
    ├── weekly/              # Weekly LLM cache
    └── monthly/             # Monthly LLM cache

tools/summarize/
└── config.json              # Optional config file (device alias, output paths, rclone remote; ~/.config/summarize/config.json is still read as a fallback)
```

### Prerequisites

Python 3.10+; no extra installation is needed to run `export` (pure local parsing).

Token usage statistics require Node.js (invoked through npx to run [ccusage](https://github.com/ryoppippi/ccusage)); not having it installed does not affect other features. ccusage 20.x covers all agent CLIs with a single tool:

- All sources: `npx ccusage@latest --help`
- Single source (namespace): `npx ccusage@latest claude|codex|gemini daily --help`

> When it is missing or below 20.x, it will silently try `npm install -g ccusage@latest`, and fall back to npx on failure.

Monthly charts (optional): `pip install matplotlib`.

Install the package and Python dependencies:

```bash
# Install the summarize package (recommended, enables the python -m summarize command)
pip install -e .
# Or install only the Python dependencies
pip install -r tools/summarize/requirements.txt
```

> **CLI usage change**: After the refactor, the recommended form is `python -m summarize daily ...`. The old `python tools/summarize/daily_summary.py ...` still works (backward compatible). All commands in this tutorial use the new form.

> ⚠️ **Running `python -m summarize` directly from the repository root may be shadowed by a leftover empty directory `summarize/` of the same name at the root** (a leftover from before the `tools/` reorganization). Please call it after installing with `pip install -e .`, or run it from within the `tools/` directory; you may also delete the leftover empty directories `summarize/ research/ website/ workflow/` at the root.

When calling an API to generate summaries, there are four backends to choose from. The default is `ollama` — a keyless local Ollama server (see `scripts/serve_local_llm.sh`; override globally with `GADGET_LLM_BACKEND`). The three alternatives:

#### Option 1: Claude Code CLI

Use the locally installed Claude Code CLI to generate summaries — **no API key required**; it reuses Claude Code's existing login state directly.

```bash
# Install the Claude Code CLI (if not installed yet)
npm install -g @anthropic-ai/claude-code

# Confirm you are logged in
claude --version
```

Select it with `--api claude_cli`:

```bash
python -m summarize daily export --summarize --date 2026-02-13 --api claude_cli
```

#### Option 2: Anthropic API

Call the Claude API directly; an API key is required:

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

python -m summarize daily export --summarize --date 2026-02-13 --api anthropic
```

#### Option 3: OpenAI API

```bash
pip install openai
export OPENAI_API_KEY="sk-..."

python -m summarize daily export --summarize --date 2026-02-13 --api openai
```

### Config file (recommended)

When using multiple devices, it is recommended to create a config file on each device to set the device alias and output paths.

Config file path: repo-local `tools/summarize/config.json` (template: `config.example.json`; `config --init` writes here). If it does not exist, `~/.config/summarize/config.json` is read as a fallback; the `SUMMARIZE_CONFIG` env var (explicit path) beats both.

#### Quick creation

```bash
python -m summarize daily config --init
```

Interactively asks about each setting and generates the config file.

#### Manual editing

```json
{
  "device_name": "home-server",
  "logs_dir": "~/Google Drive/summarize/logs",
  "reports_dir": "~/Google Drive/summarize/reports",
  "rclone_remote": "gdrive:gadget/summarize",
  "rclone_path": "~/.local/bin/rclone"
}
```

#### Field descriptions

| Field | Description | Default |
|------|------|--------|
| `device_name` | Device alias, used in the export filename and log content | System hostname (`platform.node()`) |
| `logs_dir` | logs output directory, supports `~`, can point to a cloud-drive sync directory | `outputs/logs/summarize/` |
| `reports_dir` | reports output directory, supports `~` | `outputs/reports/summarize/` |
| `rclone_remote` | rclone remote path; export uploads to `<remote>/logs/`, merge uploads to `<remote>/reports/`, and `--sync` downloads from `<remote>/logs/` | (no upload) |
| `rclone_path` | rclone binary path, supports `~`, for environments without sudo privileges | Looked up from PATH |

All fields are optional; you can omit the ones you do not need. Without a config file, all behavior is the same as before. The complete list of config keys: `device_name`, `logs_dir`, `reports_dir`, `rclone_remote`, `rclone_path`, plus CLI-default keys `default_api`, `deploy`, `hugo_site`, `workers`, and local-LLM/translation keys `model`, `base_url`, `reasoning_effort`, `translation_model`, `translation_model_ollama`, `translation_backend`.

#### View the current config

```bash
python -m summarize daily config --show
```

Example output:

```
配置文件路径: /home/user/gadget/tools/summarize/config.json
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

#### Output path priority

Output paths are resolved by the following priority, with higher priority overriding lower:

```
--output CLI flag > environment variable > config.json > default path
```

Environment variables: `SUMMARIZE_LOGS_DIR` (export output), `SUMMARIZE_REPORTS_DIR` (merge / single-machine mode output).

Example: even if `logs_dir` is set in the config, `--output /tmp/test` still takes precedence:

```bash
python -m summarize daily export --output /tmp/test --date 2026-02-13
# → /tmp/test/2026-02-13_home-server.json
```

### Machine identity

Each device can set a human-readable alias via `device_name`, replacing the default system hostname (such as `DESKTOP-ABC123`).

How to set it:
- Run `config --init` for interactive setup
- Or manually add `"device_name": "my-alias"` to the repo-local `tools/summarize/config.json` (or `~/.config/summarize/config.json` if that is what the machine uses — it is still read as a fallback)

#### Filename change

The export filename uses `device_name`:

```
Without config: 2026-02-14_DESKTOP-ABC123.json
With config:    2026-02-14_home-server.json
```

#### Device info in the export log

Both `device_name` and the original `hostname` are kept in the export log:

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

When merge generates the daily report, the AI sees `device_name` as the device label, making the report more readable.

### Workflow

The whole tool has two phases. With no subcommand, it defaults to running export (export only, no API call).

#### Phase 1: Export (run on each device)

Run `export` on each machine that has AI conversation records; no API key is needed:

```bash
# Export conversations for all unexported dates (default behavior)
python -m summarize daily export

# Specify a date (export that day only)
python -m summarize daily export --date 2026-02-13

# Also include ChatGPT / generic formats
python -m summarize daily export --date 2026-02-13 \
    --chatgpt conversations.json \
    --generic other_chat.json
```

Without `--date`, `export` scans all dates that have conversations, skips the ones already exported, and exports each day into its corresponding date file.

Generated file: `<logs_dir>/2026-02-13_<device_name>.json`

For example, with `device_name: "macbook"` configured: `outputs/logs/summarize/2026-02-13_macbook.json`

This JSON contains:
- Device info (device alias, hostname, platform, username)
- All conversation content for that day
- Token usage statistics (collected automatically via ccusage, including token counts and cost for each model)
- An optional single-device AI summary (see below)

If `rclone_remote` is configured, the log file is automatically uploaded to `<rclone_remote>/logs/` (such as `gdrive:gadget/summarize/logs/`).

**Optional: generate a single-device summary while exporting**

```bash
python -m summarize daily export --date 2026-02-13 --summarize
```

Adding `--summarize` calls the API to first produce a summary of this device's conversations; the result is stored in the log's `device_summary` field. Later, merge uses these summaries as context to improve the quality of the final daily report.

#### Phase 2: Merge (run on any device)

There are two ways to provide log files to merge:

**Option 1: `--sync` automatic pull (recommended)**

Once `rclone_remote` is configured, use `--sync` to automatically download all devices' logs from the remote `<remote>/logs/`:

```bash
# Sync the day's logs from the remote, then merge (recommended)
python -m summarize daily merge --sync --date 2026-02-13

# Sync + deploy to Hugo
python -m summarize daily merge --sync --date 2026-02-13 --deploy

# Use the Anthropic API
python -m summarize daily merge --sync --date 2026-02-13 --api anthropic
```

`--sync` downloads `2026-02-13_*.json` to the local `logs_dir`, then merges all matching files. You can also manually specify additional log files at the same time; they are deduplicated by path and merged together.

When `rclone_remote` is not configured, `--sync` only prints a notice and does not affect the local flow.

**Batch processing: `--sync-all`**

`--sync-all` downloads all log files from the remote, groups them by date, and starts an independent subprocess to process each day. Dates that already have a report are skipped automatically:

```bash
# Sync all dates and generate a daily report day by day
python -m summarize daily merge --sync-all

# Sync all + deploy each day to Hugo
python -m summarize daily merge --sync-all --deploy

# Specify API and timeout
python -m summarize daily merge --sync-all --api anthropic --timeout 300
```

Each subprocess's timeout is computed dynamically based on the log file size (using the number of seconds specified by `--timeout` per 150K chunk).

**Parallel speedup: `--workers`**

`--sync-all` processes dates sequentially by default. When there are many dates, use `--workers N` to run N workers in parallel (backed by `ThreadPoolExecutor`, each worker running its own `merge --sync` subprocess):

```bash
# Batch-merge with 4 parallel workers
python -m summarize daily merge --sync-all --workers 4
```

The default is `--workers 1` (sequential, preserving the original behavior); the effective worker count is capped at the number of dates to process. This flag **only affects the `--sync-all` batch merge** — single-date merge and export are unaffected. Each worker is an independent subprocess, with its log written separately under `outputs/logs/summarize/merge_logs/`. Higher concurrency means more simultaneous requests to the LLM backend — keep it modest when using `claude_cli` or a rate-limited API.

**Option 2: specify files manually**

If the log files are already local (synced via a cloud-drive app or manually copied), specify the paths directly:

```bash
python -m summarize daily merge outputs/logs/summarize/2026-02-13_*.json
python -m summarize daily merge --api openai outputs/logs/summarize/*.json
```

The output goes under `reports_dir` (default `outputs/reports/summarize/`):
- `2026-02-13.md` — Markdown daily report
- `2026-02-13.json` — structured data

If `rclone_remote` is configured, the report is automatically uploaded to `<rclone_remote>/reports/`.

#### Complete workflow example

```bash
# Device A (macbook):
python -m summarize daily export --date 2026-02-14
# → logs/2026-02-14_macbook.json → auto-uploaded to gdrive:gadget/summarize/logs/

# Device B (desktop):
python -m summarize daily export --date 2026-02-14
# → logs/2026-02-14_desktop.json → auto-uploaded to gdrive:gadget/summarize/logs/

# On any device, merge:
python -m summarize daily merge --sync --date 2026-02-14
# → Downloads 2026-02-14_*.json from gdrive:gadget/summarize/logs/
# → Merges all logs → calls the API to generate the daily report
# → Uploads the report to gdrive:gadget/summarize/reports/
```

### Full pipeline automation (auto)

The `auto` subcommand strings together the complete pipeline via subprocesses: daily export → daily merge → weekly → monthly, covering daily summarization with a single command. It is well suited for cron / systemd timer scheduled jobs, or for manual triggering before wrapping up each day.

#### Basic usage

```bash
# Default: process yesterday (most common; today's conversations are usually not finished, so the aggregation target defaults to yesterday)
python -m summarize auto

# Process + deploy to Hugo
python -m summarize auto --deploy

# Specify a target date (weekly report uses that date's ISO week, monthly report uses its month)
python -m summarize auto --date 2026-04-18

# Specify the LLM backend (passed through to merge / weekly / monthly)
python -m summarize auto --api anthropic
python -m summarize auto --api openai

# Force regeneration (ignore caches and existing output; covers daily / weekly / monthly)
python -m summarize auto --force

# Combined usage
python -m summarize auto --date 2026-04-18 --api anthropic --deploy --force
```

#### Parameter descriptions

| Parameter | Default | Description |
|------|------|------|
| `--date YYYY-MM-DD` | Yesterday | Aggregation target date. Determines which week the weekly report covers and which month the monthly report covers. **Does not affect** `daily export` / `merge --sync-all`, which still process all dates that are not yet exported / not yet finalized |
| `--api {ollama,claude_cli,anthropic,openai}` | `ollama` | LLM backend, passed through to all LLM-calling steps |
| `--deploy` | Off | Appends `--deploy` to merge / weekly / monthly, publishing the daily / weekly / monthly reports together to Hugo |
| `--force` | Off | Appends `--force` to all four steps, ignoring caches and existing output files and forcing a rerun |
| `--workers N` | 1 | Passed through to `daily merge --sync-all`: run N workers in parallel to merge multiple days (default 1 = sequential). See the "Parallel speedup" note for `--sync-all` above |

#### Execution flow

Internally, `auto` invokes four independent subprocesses in sequence via `subprocess.run` (see `summarize/auto.py`):

1. `python -m summarize daily export` — scans all dates with conversations on this machine, skips those already exported, and writes each day to `<logs_dir>/YYYY-MM-DD_<device>.json`. At the same time it automatically collects token usage per source via ccusage 20.x (after discovering sources, it runs `ccusage <source> daily` for each source and writes `usage_<source>_<device>.json`). If `rclone_remote` is configured, it uploads to `<remote>/logs/`.
2. `python -m summarize daily merge --sync-all` — pulls all devices' logs from the remote `<remote>/logs/`, groups them by date, and starts an independent subprocess per day to merge them into a daily report. Dates that are already finalized are skipped automatically.
3. `python -m summarize weekly generate --week <target-week>` — the target week = the ISO 8601 week (Monday to Sunday) that `--date` (or yesterday) falls in. It reads all daily reports for that week and calls the LLM to produce `<week>-weekly.{md,json}` and `<monday-date>-usage.png`.
4. `python -m summarize monthly generate --month <target-month>` — the target month = the month that `--date` (or yesterday) falls in. It reads all daily reports for that month and produces `<month>-monthly.{md,json}` as well as `<month>-monthly-cost.png` / `<month>-monthly-tokens.png`.

Before executing each subprocess, a prominent banner is printed:

```
============================================================
[auto] /path/to/python -m summarize daily merge --sync-all --deploy
============================================================
```

**A failure in any step (non-zero exit code) does not interrupt the subsequent steps**; it only prints `[auto] exited <code>, continuing...`. This is intentional: for example, if a day could not sync from the remote due to network issues, the later weekly / monthly steps can still proceed based on the existing local data. After all steps complete, it prints `[auto] Pipeline complete.`.

#### Typical use cases

**1. Daily scheduled job (cron)** — at 23:55 each night, process yesterday's conversations and deploy:

```cron
55 23 * * * cd /path/to/gadget && /path/to/conda/envs/AI/bin/python -m summarize auto --deploy >> ~/logs/summarize-auto.log 2>&1
```

**2. Backfilling a historical date** — for example, you missed Tuesday last week:

```bash
python -m summarize auto --date 2026-04-14 --deploy
```

Note: `daily export` and `merge --sync-all` process all incomplete dates (not just `--date`), so even if this command's only purpose is to backfill Tuesday's daily report, it may also incidentally backfill several previously missed days. The weekly / monthly reports only recompute the week / month corresponding to `--date`.

**3. Full refresh after switching API or updating the prompt** — combine with `--force` to ignore the cache and regenerate:

```bash
python -m summarize auto --date 2026-04-18 --api anthropic --force --deploy
```

#### auto vs. step-by-step execution

`auto` is not required; it is fully equivalent to manually running the four commands in sequence. How to choose:

- **Use `auto`**: you want a single command to cover the entire daily flow, and you are fine with the "a failure in any step does not block the subsequent ones" behavior.
- **Step-by-step execution**: you need fine-grained control (for example, rerunning only weekly, manually specifying log files, interactively inspecting each step's output, or using a different `--api` per step).

#### Onboarding / readiness check

`auto` first checks the run conditions before actually executing export / merge / weekly / monthly. If a required item is missing (for example `rclone_remote`, `rclone`, a reachable Ollama endpoint for the default `ollama` backend (or the `claude` CLI when using `claude_cli`), or the Hugo site/binary needed by `--deploy`), the command stops and gives repair steps, avoiding failing halfway through.

```bash
python -m summarize onboard                 # Check the requirements for summarize auto
python -m summarize onboard --init-config   # Interactively create tools/summarize/config.json
python -m summarize onboard --deploy        # Also check Hugo deploy requirements
python -m summarize auto                    # Automatically runs the readiness check first
python -m summarize auto --skip-onboard-check  # Only when you explicitly want to skip the check
```

#### auto FAQ

- **Why does the aggregation target default to yesterday instead of today?** Because the current day's conversations are often not yet finished, so both the daily report and the ccusage statistics are incomplete. If you do need to process the current day, explicitly pass `--date $(date +%F)`.
- **Does `auto` upload to rclone?** `daily export` and `daily merge` upload automatically according to the config (the same behavior as running them individually); the `weekly` / `monthly` outputs are not uploaded automatically (they need `--deploy` to trigger the Hugo deploy flow).
- **In a multi-device setup, which machine should run `auto`?** Every device needs to run `daily export` (to parse local conversations), while `merge / weekly / monthly` only need to run on one central machine. In most cases the recommendation is: every device runs `daily export` on its own (cron works fine), and the central machine runs `auto --deploy` (its daily export amounts to a backfill, and merge amounts to the aggregation).

### Cloud-drive sync

For passing log/reports files between multiple devices, there are two cloud-drive approaches that solve the problem of transferring log files between devices.

#### Option 1: cloud-drive app sync (recommended for devices with a desktop environment)

Point the output directory at the cloud-drive sync folder; once files are written, the cloud-drive app automatically syncs them to all devices.

Set the following in each device's repo-local `tools/summarize/config.json` (or `~/.config/summarize/config.json` if that is what the machine uses — it is still read as a fallback):

```json
{
  "device_name": "macbook",
  "logs_dir": "~/Google Drive/summarize/logs",
  "reports_dir": "~/Google Drive/summarize/reports"
}
```

This way all devices' export logs are written into the same cloud-drive directory, and merge reads them directly.

Typical sync paths for each cloud drive:

| Cloud drive | macOS | Windows | Linux |
|------|-------|---------|-------|
| Google Drive | `~/Google Drive/` | `~/Google Drive/` | — (no official client) |
| OneDrive | `~/OneDrive/` | `~/OneDrive/` | — |
| Dropbox | `~/Dropbox/` | `~/Dropbox/` | `~/Dropbox/` |
| iCloud | `~/Library/Mobile Documents/com~apple~CloudDocs/` | — | — |

> A Linux headless server usually has no cloud-drive desktop client; Option 2, rclone, is recommended.

#### Option 2: rclone (recommended for headless servers)

[rclone](https://rclone.org/) is a command-line cloud-drive tool that supports 40+ cloud storage providers (Google Drive, OneDrive, S3, ...), requires no desktop environment, and is very well suited for headless servers.

Once configured, export automatically uploads to `<remote>/logs/`, and merge automatically uploads to `<remote>/reports/`. During merge you can use `--sync` to pull other devices' logs from `<remote>/logs/`. Upload/download failures only print `[warn]` and do not block the main flow.

**1. Install rclone**

With sudo privileges:

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

Without sudo privileges (common on headless servers) — download the binary directly to the user directory:

```bash
# Download and extract to ~/.local/bin/
mkdir -p ~/.local/bin
curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip
unzip rclone-current-linux-amd64.zip
cp rclone-*-linux-amd64/rclone ~/.local/bin/
chmod +x ~/.local/bin/rclone
rm -rf rclone-*-linux-amd64*
```

If `~/.local/bin` is not on PATH, specify `rclone_path` in the config:

```json
{
  "rclone_path": "~/.local/bin/rclone",
  "rclone_remote": "gdrive:gadget/summarize"
}
```

The program prefers the path specified by `rclone_path`, and only looks it up from PATH if not found.

**2. Configure the remote**

On a device with a browser:

```bash
rclone config
```

Follow the prompts to select the cloud-drive type and complete OAuth authorization.

Headless server (no browser) — first obtain the token on a device that has a browser:

```bash
rclone authorize "drive"     # Google Drive
rclone authorize "onedrive"  # OneDrive
```

The browser pops up an authorization page; once done, the terminal prints the token JSON. Then run `rclone config` on the server, choose to enter the token manually, and paste the JSON output from the previous step.

**3. Enable automatic upload**

Set `rclone_remote` in the repo-local `tools/summarize/config.json` (or `~/.config/summarize/config.json` if that is what the machine uses — it is still read as a fallback):

```json
{
  "device_name": "linux-server",
  "rclone_remote": "gdrive:gadget/summarize"
}
```

The format of `rclone_remote` is `<remote-name>:<path>`, where the remote name is the name you set during `rclone config`.

Common configuration examples:

| Cloud drive | rclone_remote example |
|------|-------------------|
| Google Drive | `gdrive:gadget/summarize` |
| OneDrive | `onedrive:summarize` |
| Dropbox | `dropbox:summarize` |
| S3 | `s3:my-bucket/summarize` |

**4. Verify**

```bash
# Check whether the config took effect (shows the logs/reports subpaths)
python -m summarize daily config --show

# Manually test rclone connectivity
rclone ls gdrive:gadget/summarize/logs/
rclone ls gdrive:gadget/summarize/reports/
```

**Mixed use**

You can use the cloud-drive app on desktop devices (setting `logs_dir` to point at the sync directory) and rclone on the server (setting `rclone_remote`); both end up with files in the same cloud-drive directory and do not conflict with each other.

> **Tip**: When using rclone, export uploads to `<remote>/logs/`, and merge uploads to `<remote>/reports/`. If you previously used a flat directory structure (no logs/reports subdirectories), the existing files are unaffected, and new files are automatically uploaded to the corresponding subdirectory.

### Weekly report

After accumulating a week of daily reports, you can generate an ISO weekly report (Monday to Sunday).

#### View available weeks

```bash
python -m summarize weekly list
```

Example output:

```
周              日报数    已有周报
----------------------------------
2026-W12         5    ✅
2026-W11         7
2026-W10         6

共 3 周, 18 份日报
```

#### Generate the weekly report

```bash
# Generate a specific week
python -m summarize weekly generate --week 2026-W12

# Default: last week
python -m summarize weekly generate

# Generate + deploy to Hugo
python -m summarize weekly generate --week 2026-W12 --deploy

# Choose the API backend
python -m summarize weekly generate --week 2026-W12 --api anthropic
```

Generated files (by default under `outputs/reports/summarize/`):
- `2026-W12-weekly.md` — Markdown weekly report
- `2026-W12-weekly.json` — structured JSON

Charts (under `outputs/images/summarize/`, requires matplotlib):
- `<monday-date>-usage.png` — three-subplot PNG (Tokens / Cost / Cache compared per platform)

#### Caching mechanism

Same as the monthly summary: LLM call results are cached in `outputs/cache/summarize/weekly/`, keyed by the hash of the source daily reports.

```bash
# Skip the LLM cache and force a fresh API call
python -m summarize weekly generate --week 2026-W12 --no-cache
```

### Monthly summary

After accumulating a month of daily reports, you can generate a monthly trend summary.

#### View available months

```bash
python -m summarize monthly list
```

Example output:

```
月份              日报数      已有月报
----------------------------------
2026-02          22    ✅
2026-03           3

共 2 个月, 25 份日报
```

#### Generate the monthly summary

```bash
# Generate the summary for a specific month
python -m summarize monthly generate --month 2026-02

# Default: last month
python -m summarize monthly generate

# Choose the API backend (same four backends as the daily report)
python -m summarize monthly generate --month 2026-02 --api anthropic
python -m summarize monthly generate --month 2026-02 --api openai
```

Generated files (by default under `outputs/reports/summarize/`):
- `2026-02-monthly.md` — Markdown monthly report
- `2026-02-monthly.json` — structured JSON

Charts (under `outputs/images/summarize/`, requires matplotlib):
- `2026-02-monthly-cost.png` — daily cost trend bar chart
- `2026-02-monthly-tokens.png` — daily token trend bar chart

#### How it works

The monthly summary has two parts:

1. **LLM analysis** (requires an API call) — reads all daily report JSONs, strips the `token_usage` and `conversation_summaries` fields (these are mechanically aggregated), formats the remaining content, and sends it to the LLM to analyze trends. If the content exceeds 150K characters, it automatically groups by week to summarize in segments and then merges.
2. **Mechanical aggregation** (pure local computation) — aggregates token usage (total, daily average, peak, model distribution) and statistics (active days, conversation count, task count, project count).

#### Caching mechanism

LLM call results are cached in `outputs/cache/summarize/monthly/YYYY-MM.json`, with the cache key being the SHA-256 hash of all source daily report files. When any daily report is updated, the cache is automatically invalidated.

```bash
# Skip the LLM cache and force a fresh API call
python -m summarize monthly generate --month 2026-02 --no-cache

# Ignore existing output files and force regeneration
python -m summarize monthly generate --month 2026-02 --force
```

#### Monthly summary content

`monthly_summary.py` reads all daily report JSONs for a month, has the LLM comprehensively analyze trends, and at the same time mechanically aggregates token usage and statistics.

| Section | Content | Source |
|------|------|------|
| This month's overview | Active days, total conversations, project count, total tokens, total cost | Mechanical aggregation |
| Project progress | Active days per project, key milestones, status | LLM analysis |
| This month's key achievements | The 5-10 most important achievements of the whole month | LLM analysis |
| Recurring problems | Problem patterns recurring across multiple days, root causes, resolution status | LLM analysis |
| Human-AI collaboration trends | Patterns of AI limitations, directions for improvement | LLM analysis |
| This month's highlight takeaways | Takeaways grouped by category (architecture / debugging / tools / domain) | LLM analysis |
| Token usage statistics | Claude Code / Codex monthly summary, daily cost trend chart (matplotlib), model distribution table | Mechanical aggregation |

#### Monthly summary + Hugo deployment

```bash
python -m summarize monthly generate --month 2026-02 --deploy
python -m summarize monthly generate --month 2026-02 --deploy --hugo-site /path/to/site
```

This will:
1. Generate the monthly report
2. Publish the Markdown to Hugo at `content/bugJournal/2026-02-monthly.md` (with the date set to the last day of the month at 23:59, placing it after all daily reports)
3. Copy the trend charts to Hugo's `static/images/monthly/`
4. Run `update.sh` to build and push

### Charts

All charts are generated by `charts.py`, which requires `pip install matplotlib` (optional; when not installed, charts are skipped and report generation is unaffected). Output goes to `outputs/images/summarize/`.

#### Daily / weekly charts

Each daily and weekly report generates a three-subplot PNG (`<date>-usage.png`):

| Subplot | X axis | Y axis | Description |
|------|------|------|------|
| Tokens | Platform (Claude Code / Codex) | Token count | Stacked by model |
| Cost | Platform | Cost ($) | Stacked by model |
| Cache | Platform | Token count | Stacked by type (input/output/cache) |

#### Monthly charts

The monthly report generates two independent charts:
- **Cost trend chart** (`<month>-monthly-cost.png`) — X axis is date, a bar chart of cost stacked by model
- **Token trend chart** (`<month>-monthly-tokens.png`) — X axis is date, a bar chart stacked by token type

### Hugo blog deployment

#### Deploy during merge

Adding `--deploy` during merge can automatically publish the daily report to the Hugo site:

```bash
python -m summarize daily merge --sync --date 2026-02-13 --deploy
python -m summarize daily merge --deploy outputs/logs/summarize/2026-02-13_*.json
```

This will:
1. Generate an article with frontmatter at `<hugo-site>/content/bugJournal/2026-02-13.md`
2. Copy the daily report charts to `<hugo-site>/static/images/daily/`
3. Run `<hugo-site>/update.sh` to build and push to GitHub Pages

The Hugo site path defaults to `<project-root>/website` (computed dynamically), and can be changed via `--hugo-site`:

```bash
python -m summarize daily merge --deploy --hugo-site /path/to/hugo/site outputs/logs/summarize/*.json
```

#### Batch deployment (deploy subcommand)

Using the standalone `deploy` subcommand, you can batch-deploy existing reports under the `reports/` directory to Hugo without re-calling the API:

```bash
# Deploy all reports
python -m summarize daily deploy

# Deploy a specific date
python -m summarize daily deploy --date 2026-02-13

# Specify the Hugo site path and reports directory
python -m summarize daily deploy --hugo-site /path/to/site --reports-dir /path/to/reports

# Force re-deployment of existing articles
python -m summarize daily deploy --force
```

`deploy` iterates over all `.md` report files, generates a Hugo article for each file, and finally runs `update.sh` once for a unified build and push. Adding `--force` forces re-deployment of existing articles.

### Supported conversation sources

| Source | Description | Auto-scanned |
|------|------|----------|
| Claude Code | Reads `.jsonl` files under `~/.claude/projects/` | Yes |
| Codex | Reads session directories under `~/.codex/sessions/` | Yes |
| ChatGPT | The `conversations.json` exported from ChatGPT | No, requires `--chatgpt` to specify |
| Generic format | A JSON array of `[{"role": "user", "content": "..."}]` | No, requires `--generic` to specify |

> **WSL support**: When running inside WSL, Claude/Codex data is usually written to the Windows user directory rather than the Linux home. After detecting WSL (the kernel contains `microsoft`), it additionally scans `.claude*/projects/` and `.codex/sessions/` under `/mnt/c/Users/*`, with no configuration needed. (It assumes the C drive is mounted at `/mnt/c`.)

### Daily report content

The generated daily report contains the following sections:

- **One-line summary** — an overview of today's work
- **Daily overview** — a three-sentence summary of what / how / impact
- **Task list** — each task's name, status (done / in progress / blocked), and description
- **Problems and solutions** — problems encountered, solutions, key insights
- **Human vs. AI thinking comparison** — an analysis of the differences in how the human and the AI each approached things
- **AI limitations** — shortcomings the AI exhibited during the interaction
- **Today's takeaways** — key learning points
- **Token usage** — token counts and cost details, tracked separately for Claude Code / Codex
- **Usage charts** — three-subplot PNG (Tokens / Cost / Cache, requires matplotlib)

### Key points of the data format and import contract

**Export log** (`logs/YYYY-MM-DD_<device>.json`):

```
{version, date, device, conversations[], device_summary{}, token_usage, _merged_devices[], _finalized}
```

**Report** (`reports/YYYY-MM-DD.json`):

```
{date, summary, daily_overview, tasks[], problems_and_solutions[], human_vs_ai[],
 ai_limitations[], learnings[], conversation_summaries[],
 token_usage_by_source{<source>: usage}, token_usage, codex_token_usage}
```

`token_usage_by_source` is canonical (one entry per discovered source); `token_usage` (Claude Code) and `codex_token_usage` are kept as backward-compatible aliases.

**Weekly Report** (`reports/YYYY-WNN-weekly.json`):

```
{week, date_range{start,end}, summary, project_progress[], key_tasks[], problems_resolved[],
 learnings[], ai_usage_notes{}, next_week_outlook, statistics,
 token_usage_summary, codex_token_usage_summary, combined_token_usage_summary}
```

ISO 8601 weeks (Monday to Sunday). Each item in tasks/problems/learnings carries `level: "high"|"low"` and `importance: 1-10`, used for priority sorting.

**Import contract**: `daily_summary.py` is a backward-compatible re-export shim and is a stable API surface (referenced by the monthly/weekly pipelines and external consumers). The key exports consumed externally: `_atomic_write`, `_resolve_output_dir`, `_load_config`, `run_hugo_update`, `format_reports_for_llm`, `aggregate_token_usage`. `tests/test_imports.py` parametrically verifies that all expected symbols are still importable after the refactor; it must be run after structural changes. New code should import the specific submodules directly.

### `--api` parameter description

All commands that need AI summarization (`export --summarize`, `merge`, `weekly generate`, `monthly generate`, `auto`) support the `--api` parameter:

| Value | Description | API key required? |
|----|------|-----------------|
| `ollama` | Calls a local Ollama server (default) | No, keyless local server |
| `claude_cli` | Calls the local Claude Code CLI | No, reuses the CLI's login state |
| `anthropic` | Calls the Anthropic Claude API | Yes, requires `ANTHROPIC_API_KEY` |
| `openai` | Calls the OpenAI API | Yes, requires `OPENAI_API_KEY` |

The `claude_cli` mode passes the prompt to the Claude Code CLI via `claude --print`. It requires Claude Code to be installed and logged in beforehand.

#### `--timeout` parameter

All LLM-calling commands (`export --summarize`, `merge`) support `--timeout` to control the timeout in seconds per 150K chunk:

```bash
# Default 600 seconds
python -m summarize daily merge --sync --date 2026-02-13

# Custom timeout
python -m summarize daily merge --sync --date 2026-02-13 --timeout 300
python -m summarize daily export --summarize --date 2026-02-13 --timeout 900
```

### Running tests

```bash
# Run all tests
python -m pytest tools/summarize/tests/ -v

# Run only the import-contract tests (must run after refactoring; verifies all external import paths)
python -m pytest tools/summarize/tests/test_imports.py -v

# Run a single test file
python -m pytest tools/summarize/tests/test_config.py -v
python -m pytest tools/summarize/tests/test_parsers.py -v
python -m pytest tools/summarize/tests/test_formatter.py -v
python -m pytest tools/summarize/tests/test_summarizer.py -v
```

### Common command cheat sheet

```bash
# ── Config ──
python -m summarize daily config --init    # Interactively create the config
python -m summarize daily config --show    # Show the current config

# ── Phase 1: Export ──
python -m summarize daily export                                # Export all unexported dates
python -m summarize daily export --date 2026-02-13              # Export a specific date
python -m summarize daily export --date 2026-02-13 --summarize  # Export + single-device AI summary

# ── Phase 2: Merge ──
python -m summarize daily merge --sync --date 2026-02-13            # Sync logs from the remote, then merge
python -m summarize daily merge --sync --date 2026-02-13 --deploy   # Sync + merge + Hugo deploy
python -m summarize daily merge --sync-all                          # Batch-sync all dates and process day by day
python -m summarize daily merge --sync-all --deploy                 # Batch sync + deploy
python -m summarize daily merge outputs/logs/summarize/2026-02-13_*.json  # Manually specify log files

# ── Batch deploy ──
python -m summarize daily deploy                          # Deploy all reports to Hugo
python -m summarize daily deploy --date 2026-02-13        # Deploy a specific date

# ── Full-pipeline automation ──
python -m summarize auto                                  # One-click run: export → merge → weekly → monthly
python -m summarize auto --deploy                         # Full pipeline + Hugo deploy
python -m summarize auto --date 2026-04-18 --deploy       # Specify a target date

# ── Weekly report ──
python -m summarize weekly list                               # List available weeks
python -m summarize weekly generate --week 2026-W12           # Generate a specific week
python -m summarize weekly generate                           # Default: last week
python -m summarize weekly generate --week 2026-W12 --deploy  # Generate + Hugo deploy

# ── Monthly summary ──
python -m summarize monthly list                              # List available months
python -m summarize monthly generate --month 2026-02          # Generate a specific month
python -m summarize monthly generate                          # Default: last month
python -m summarize monthly generate --month 2026-02 --deploy # Generate + Hugo deploy
python -m summarize monthly generate --month 2026-02 --no-cache  # Skip the LLM cache
python -m summarize monthly generate --month 2026-02 --force     # Ignore existing output

# ── Run tests ──
python -m pytest tools/summarize/tests/ -v                          # Run all tests
python -m pytest tools/summarize/tests/test_imports.py -v           # Import-contract tests
```

## Research

Research Scout is a unified academic research toolkit with four core capabilities:

1. **Paper discovery**: Search papers from arXiv / bioRxiv / PubMed via a three-stage LLM pipeline (fast screening → deep analysis → citation impact), generating a weekly report
2. **Paper deep insight** (`--insight`): Download full paper text, use the LLM to analyze writing structure, publication strategy, and core knowledge; automatically fetch OpenReview reviews and analyze reviewer consensus; generate a research writing guide
3. **Researcher profiling**: Analyze a researcher's academic trajectory, score tiering, and discover advisor-student relationships
4. **Citation graph analysis**: View a paper's forward citations (who cited it) and backward references (who it cited), with LLM-generated impact analysis

All capabilities are invoked through a single unified CLI entry point, `research_scout.py`.

### 1. Initial Configuration

Configuration is required before first use:

```bash
python tools/research/research_scout.py config --init
```

This interactively asks for the following configuration items:
- **Default LLM backend**: `ollama` (default, keyless local Ollama server) / `claude_cli` (calls the Claude CLI directly) / `anthropic` / `openai`
- **Hugo site path**: Used to deploy weekly reports to your blog (optional)
- **Default lookback days**: How many recent days of papers to search (default 7 days)
- **Default max results**: Maximum number of papers returned per project per search (default 50)
- **Number of high-scoring papers shown in the report**: How many are shown in detail in the weekly report (default 5)

The config file is saved at `~/.config/research_scout/config.json`.

View the current configuration:

```bash
python tools/research/research_scout.py config --show
```

> **Note**: Using the `anthropic` backend requires setting the environment variable `ANTHROPIC_API_KEY`; using the `openai` backend requires `OPENAI_API_KEY`. The `claude_cli` backend requires no additional configuration, but the Claude CLI must be installed.

### 2. Creating a Research Project

A "project" defines one of your research directions. Each project has its own keywords, categories, and open questions.

#### Basic creation

```bash
python tools/research/research_scout.py init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "error recovery" "benchmarking" \
    --categories "cs.RO" "cs.AI"
```

Parameter descriptions:
- `robot-manipulation`: Project ID (lowercase letters, digits, hyphens)
- `--title`: Project title (displayed in the report)
- `--keywords`: Search keywords (combined with OR for searching)
- `--categories`: arXiv category codes (common ones include `cs.RO` Robotics, `cs.LG` Machine Learning, `cs.CV` Computer Vision, `cs.AI` Artificial Intelligence)

#### Creating from an existing overview

If you already have a research overview document, you can let the LLM automatically extract the project information:

```bash
python tools/research/research_scout.py init my-project \
    --from-overview path/to/overview.md
```

The LLM will automatically extract the title, keywords, and open questions from the document.

#### Adding open questions (optional but recommended)

Open questions help the LLM better judge how relevant a paper is to your research:

```bash
python tools/research/research_scout.py init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "grasping" \
    --categories "cs.RO" \
    --questions "How can a robot achieve stable grasping in unknown environments?" \
                "What are the best practices for vision-tactile fusion in manipulation tasks?"
```

#### Viewing all projects

```bash
python tools/research/research_scout.py list
```

#### Manually editing a project

After creation you can directly edit `research/projects/<project-id>/project.json` to modify keywords, categories, open questions, and so on. You can also edit `overview.md` to add your research background and current progress (in Chinese); this information is used by the Stage 2 deep evaluation.

### 3. Searching Papers

Search fetches papers from the configured sources without calling the LLM, so it is very fast.

#### Searching a single project

```bash
python tools/research/research_scout.py search --project robot-manipulation
```

By default it searches the most recent 7 days of papers (from arXiv), up to 50 papers.

#### Adjusting the search scope

```bash
# Search the most recent 30 days
python tools/research/research_scout.py search --project robot-manipulation --lookback-days 30

# Return up to 100 papers
python tools/research/research_scout.py search --project robot-manipulation --max-results 100
```

#### Searching a specific author

```bash
python tools/research/research_scout.py search --author "Pieter Abbeel"
```

#### Searching all projects

```bash
python tools/research/research_scout.py search
```

When `--project` is not specified, it searches all projects with `active` status.

#### Ignoring the cache

Search results for the same project on the same day are cached. To force a fresh search:

```bash
python tools/research/research_scout.py search --project robot-manipulation --no-cache
```

### 4. Generating a Weekly Report (Full Pipeline)

This is the most core command. It runs the full pipeline: **search → three-stage LLM evaluation → direction suggestions → generate weekly report**.

```bash
python tools/research/research_scout.py report --project robot-manipulation
```

#### Three-stage evaluation flow

```
50 papers (from arXiv / bioRxiv / PubMed)
    |
Stage 1: Fast screening (1 LLM call, all papers)
    |--- Each paper annotated with: motivation, novelty, paper type, institution
    |--- Classified as "high" (highly relevant) or "low" (low relevance)
    |
    +--- Low-relevance papers → report's "Literature Reading Log" (collapsed display)
    |
    +--- High-relevance papers (up to 20)
            |
            Stage 2: Deep analysis (1 LLM call)
                |--- 3 highlights per paper (key point / design motivation / value to us / action suggestion)
                |--- Relevance / novelty / inspiration scoring (1-5)
                |--- Composite score = 0.4×relevance + 0.3×inspiration + 0.3×novelty
                |--- Ranking: descending composite score, citation count as tiebreaker
                |
                Stage 3: Citation impact analysis (automatic, top 5 high-scoring papers)
                    |--- Find paper IDs via Semantic Scholar
                    |--- Fetch forward citations (who cited it, sorted by citation count, top 20)
                    |--- Fetch backward references (who it cited, top 20)
                    |--- LLM analysis: "Why is this paper widely cited? In what direction does follow-up work go?"
                |
                → Suggest new research directions
                → Automatically update the project's overview.md
                → Generate Markdown weekly report
                |
                [Optional] Add --insight to enable Stage 4+5 (see Section 5)
```

#### Choosing the LLM backend

```bash
# Use the Anthropic API (requires ANTHROPIC_API_KEY)
python tools/research/research_scout.py report --project robot-manipulation --api anthropic

# Use the OpenAI API (requires OPENAI_API_KEY)
python tools/research/research_scout.py report --project robot-manipulation --api openai

# Use the Claude CLI (default, no API key needed)
python tools/research/research_scout.py report --project robot-manipulation --api claude_cli
```

#### Choosing the output language

```bash
# English output
python tools/research/research_scout.py report --project robot-manipulation --language en

# Chinese output (default)
python tools/research/research_scout.py report --project robot-manipulation --language zh
```

#### Skipping the cache

Evaluation results are cached (Stage 1 and Stage 2 are cached separately). To re-evaluate:

```bash
python tools/research/research_scout.py report --project robot-manipulation --no-cache
```

#### Generating a report and deploying at the same time

```bash
python tools/research/research_scout.py report --project robot-manipulation --deploy
```

### 5. Paper Deep Insight (--insight)

On top of the standard three-stage evaluation, `--insight` enables two additional stages that help you truly **understand** a paper:

- **Stage 4: Paper insight analysis** — Download the full text and use the LLM to analyze writing structure, publication strategy, and reusable knowledge
- **Stage 5: OpenReview reviews** — Automatically match papers to OpenReview, fetch reviewer scores and comments, and use the LLM to analyze consensus and disputes
- **Combined output: research writing guide** — Cross-paper synthesis that generates field writing conventions, reviewer focus points, methodological takeaways, and code references

#### Basic usage

```bash
# Standard weekly report + deep insight
python tools/research/research_scout.py report --project robot-manipulation --insight

# Used together with the ask command
python tools/research/research_scout.py ask "diffusion policy robot control" --insight

# Customize the number of papers to analyze (default 3)
python tools/research/research_scout.py report --project robot-manipulation --insight --insight-top-n 5

# Deploy to Hugo
python tools/research/research_scout.py report --project robot-manipulation --insight --deploy
```

#### Processing flow

```
After Stage 1-3 completes (as described in Section 4)
    |
    +--- High-relevance papers (sorted by composite_score)
            |
            Take top N papers (default 3, adjustable via --insight-top-n)
            |
            Stage 4: Paper insight analysis
                |
                [4a] Download full text
                |    ├── arXiv: HTML preferred, PDF fallback (reuses arxiv_client.download_fulltext)
                |    ├── bioRxiv: attempt HTML full text
                |    ├── PubMed: degrade to abstract only
                |    └── Truncate to 40,000 characters (avoid LLM context overflow)
                |
                [4b] LLM three-dimensional analysis (single call)
                     ├── Writing structure: argument flow, section patterns, argumentation style
                     ├── Publication elements: key strengths, positioning strategy, experimental design
                     └── Core knowledge: core insights, reusable techniques, implementation tips
                |
            Stage 5: OpenReview reviews
                |
                [5a] Paper matching
                |    ├── Search OpenReview via fuzzy title matching
                |    ├── Covers ICLR / NeurIPS / ICML and other mainstream conferences
                |    └── Match failure → skip (does not affect Stage 4 results)
                |
                [5b] Fetch reviews
                |    └── Scores, confidence, strengths, weaknesses, questions
                |
                [5c] LLM consensus analysis
                     ├── 0 reviews → skip
                     ├── 1 review → single-reviewer summary
                     ├── 2 reviews → limited consensus analysis
                     └── 3+ reviews → full consensus / dispute analysis
                |
            Combined: research writing guide
                |--- LLM synthesizes insights + reviews from all papers
                |--- Outputs four sections:
                |    ├── Field writing conventions (how the paper should be written)
                |    ├── Reviewer focus tips (what reviewers look at)
                |    ├── Methodological takeaways (what can be learned technically)
                |    └── Code implementation references (how to turn ideas into code)
                |
                → Add "Paper Deep Insight" and "Research Writing Guide" sections to the report
```

#### Example report output

After enabling `--insight`, two extra sections appear in the Markdown weekly report:

**Paper Deep Insight** — each analyzed paper contains:

```
#### [2503.12345] Paper Title

**Writing structure**:
- Argument flow: Problem → Gap → Hypothesis → Method → Experiments → Ablation → Discussion
- Section pattern: Introduction → Related Work → Preliminary → Method → Experiments → Conclusion
- Argumentation style: Experiment-driven, extensive ablation studies validating design choices

**Publication elements**:
- Strength: First to surpass human-level performance on task X
- Strength: Proposes a general framework applicable to multiple scenarios
- Positioning strategy: Fills the gap between X and Y
- Experimental design: 6 datasets, 3 strong baselines, complete ablation

**Core knowledge**:
- Insight: The key finding is that the trade-off between X and Y can be resolved via Z
- Reusable technique: The proposed attention mask strategy can be directly used for other tasks
- Implementation tip: The learning rate needs 1000 steps of warmup, and batch size has a large effect on the results

**Reviews** (3 reviewers):
- Average score: 6.7 / 10
- Consensus strengths: Comprehensive experiments, method has theoretical support
- Consensus issues: Computational cost not discussed, missing comparison with the latest methods
- Points of dispute: Reviewer 2 considers the novelty limited, Reviewer 3 strongly objects
- Key suggestions: Add computational efficiency analysis and more baseline comparisons
```

**Research Writing Guide** — cross-paper synthesis:

```
**Field writing conventions**
Papers in this field generally adopt a four-part structure of "problem definition → method → theoretical analysis → experimental validation".
The Introduction typically uses 1-2 paragraphs to describe a real-world scenario, then clearly points out the gap in existing methods...

**Reviewer focus tips**
The three aspects reviewers value most: (1) the comprehensiveness and fairness of experiments (2) gap analysis against the state-of-the-art
(3) the generalization argument of the method. Common reasons for rejection include...

**Methodological takeaways**
Technical trends common to the three papers: (1) using a diffusion model for policy representation
(2) contrastive learning for feature alignment (3) mixed-precision training for acceleration...

**Code implementation references**
The core algorithm is recommended to use PyTorch + Hydra config management. Paper A's key innovation can be implemented in
3 lines of code: first compute the attention mask, then...
```

#### OpenReview configuration

OpenReview runs in **guest mode** by default (no account needed) and can read publicly available reviews.

If you want to fetch more data (such as not-yet-public reviews), you can configure an account:

```bash
export OPENREVIEW_USERNAME="your@email.com"
export OPENREVIEW_PASSWORD="your_password"
```

> **Supported conferences**: ICLR, NeurIPS, ICML, COLM, and other conferences that use the OpenReview platform.
> **Not supported**: AAAI, CVPR, ICCV, ECCV, and other conferences that use different review systems (the insight analysis for these papers still works normally, just without reviews).

#### Cost notes

`--insight` is **opt-in** (must be explicitly enabled) because it adds extra LLM calls:

| Analysis type | Number of LLM calls | Approximate token consumption |
|---------|------------|----------------|
| Stage 4: Insight analysis | 1 per paper | ~50K tokens/paper |
| Stage 5: Review consensus | 1 per reviewed paper | ~5K tokens/paper |
| Writing guide synthesis | 1 (total) | ~20K tokens |
| **Default 3 papers total** | **about 5-7 calls** | **about 170-200K tokens** |

By default it analyzes the top 3 high-scoring papers. Adjust the number via `--insight-top-n` (it is automatically capped to not exceed the number of papers shown in the report).

#### Caching

Insight analysis results are cached (based on paper ID + content hash); rerunning the same project will not repeatedly call the LLM. Use `--no-cache` to force a fresh analysis.

Cache location: `outputs/cache/research-scout/insight/`

### 6. Conference Paper Search

You can search papers from a specific conference (such as CVPR, ICRA, NeurIPS):

```bash
# Search only CVPR 2025 papers
python tools/research/research_scout.py search --conference "CVPR 2025"

# Search CVPR 2025 papers relevant to your project
python tools/research/research_scout.py search --conference "CVPR 2025" --project robot-manipulation

# Full pipeline: conference papers + three-stage evaluation
python tools/research/research_scout.py report --conference "CVPR 2025" --project robot-manipulation
```

**How it works**: arXiv has no conference field, but authors usually note the conference in the comment (such as "Accepted at CVPR 2025"). The tool searches arXiv full text, then applies a second filter using the comment field.

> **Note**: Conference search does not need `--lookback-days`, because conference papers span a fixed time period and use relevance ranking rather than date ranking. `--conference` and `--author` cannot be used at the same time.

### 7. Multi-source Search

In addition to arXiv, searching papers from bioRxiv and PubMed is also supported:

```bash
# Search arXiv and bioRxiv at the same time
python tools/research/research_scout.py search --project my-project --source arxiv biorxiv

# Search PubMed
python tools/research/research_scout.py search --project my-project --source pubmed

# Search all three sources
python tools/research/research_scout.py search --project my-project --source arxiv biorxiv pubmed
```

You can also configure the default search sources in `project.json`:

```json
{
  "id": "my-bio-project",
  "title": "...",
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience", "bioinformatics"],
  "pubmed_journals": ["Nature", "Science"]
}
```

> **Note**: bioRxiv and PubMed search use the standard library (`urllib.request`, `xml.etree`) and need no extra dependencies.

### 8. Natural-Language Search (ask command)

The `ask` command accepts natural-language queries, automatically parsing intent and routing to the appropriate search source (author / conference / journal / topic):

```bash
python tools/research/research_scout.py ask "找 Pieter Abbeel 最近的机器人操作论文"          # Author + topic
python tools/research/research_scout.py ask "ICRA 2025 的灵巧手操作"                          # Conference search
python tools/research/research_scout.py ask "BMJ/Lancet 上最近的 AI 诊断论文"                 # Journal search (auto PubMed)
python tools/research/research_scout.py ask "sim-to-real transfer 在 legged robot 上的进展"  # Topic search
python tools/research/research_scout.py ask "找最近的 diffusion policy 机器人控制论文" --deploy  # + deploy
python tools/research/research_scout.py ask "diffusion policy robot control" --insight        # + deep insight
```

### 9. Researcher Profiling

Analyze a researcher's academic trajectory: fetch paper data from ArXiv and Semantic Scholar, use the LLM to analyze the research journey, and compute scores and tiering.

#### Basic usage

```bash
# Analyze a single researcher (fast mode)
python tools/research/research_scout.py profile "Sergey Levine"

# Detailed mode (downloads full paper text for deep analysis)
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed

# Analyze multiple researchers
python tools/research/research_scout.py profile "Sergey Levine" "Pieter Abbeel"

# Disambiguating same names: via an affiliation hint
python tools/research/research_scout.py profile "Wei Zhang" --affiliation "MIT"

# Reverse lookup: find the author via a known paper
python tools/research/research_scout.py profile "Name" --paper "2301.12597"

# Directly specify the Semantic Scholar author ID
python tools/research/research_scout.py profile "Name" --author-id "1234567"

# Provide the researcher's homepage (used to discover students)
python tools/research/research_scout.py profile "Sergey Levine" --homepage "https://..."
```

#### Recursively discovering students

The tool can infer advisor-student relationships from co-authorship patterns and recursively analyze the discovered students:

```bash
# Depth 1: analyze Sergey Levine and discover their students
python tools/research/research_scout.py profile "Sergey Levine" --depth 1

# Depth 2: further analyze the students' students (note that API call volume grows exponentially)
python tools/research/research_scout.py profile "Sergey Levine" --depth 2
```

Student discovery is based on two sources (automatically merged and deduplicated):

1. **Homepage extraction** (preferred) — Obtain the researcher's homepage from the Semantic Scholar homepage field or an LLM-inferred URL, parse the HTML, and extract the student list. The URL can be manually provided via `--homepage`
2. **Co-authorship inference** (supplementary) — Scored based on the following signals:
   - Number of papers with first author + advisor in last position (strongest signal, weight 40%)
   - Collaboration concentrated within a 3-6 year PhD cycle (25%)
   - Co-authorship frequency (20%)
   - Recency of the collaboration (15%)

#### Batch analysis

```bash
# Read names from a file (one per line)
python tools/research/research_scout.py profile --from-file names.txt
```

#### Model and backend selection

```bash
# Use the Opus model (deeper analysis)
python tools/research/research_scout.py profile "Sergey Levine" --model opus

# Use the Anthropic API backend
python tools/research/research_scout.py profile "Sergey Levine" --api anthropic

# Ignore the cache
python tools/research/research_scout.py profile "Sergey Levine" --no-cache
```

#### Analysis flow

```
Researcher name (+ optional: --affiliation, --paper, --author-id, --homepage)
    |
[1/6] Fetch papers from ArXiv (up to 100)
    |
[2/6] Fetch metrics from Semantic Scholar (h-index, citation count, all papers and their citation counts)
    |--- Merge S2 and ArXiv data (S2 primary, ArXiv supplements arxiv_id, pdf_url, etc.)
    |--- Keep up to 10 representative works per year (sorted by awards and citation count)
    |
[3/6] LLM identifies paper awards (Best Paper / Spotlight / Oral, etc.)
    |
[4/6] Download full text (detailed mode only; HTML preferred, PDF fallback)
    |
[5/6] LLM analyzes the research trajectory
    |--- Trajectory summary: why they became a field leader/rising star, key turning points
    |--- Breakthrough work (3-7 items): what was done, why it couldn't be done before, impact on the field
    |--- Research directions, methodology evolution, field impact assessment
    |
[6/6] Compute score
    |--- Weighting: h-index 25% + total citations 20% + last-5-years citations 20% + top-venue ratio 20% + career stage 15%
    |--- Tiering: Field Leader (≥75) / Rising Star (≥50) / Active Researcher (≥30) / Early-career Researcher (<30)
```

Disambiguation hint parameter descriptions:
- `--affiliation`: Institution name, used to disambiguate authors with the same name (such as "MIT", "Stanford")
- `--paper`: A known paper (arXiv ID, DOI, or title), used to reverse-look-up the author from the paper
- `--author-id`: Directly specify the Semantic Scholar author ID, skipping the search
- `--homepage`: The researcher's homepage URL, used to discover students (takes priority over automatic discovery)

#### Deploying to Hugo

```bash
# Deploy directly to the Hugo site after analysis
python tools/research/research_scout.py profile "Sergey Levine" --deploy
python tools/research/research_scout.py profile "Sergey Levine" --deploy --hugo-site /path/to/site
```

#### Output

Results are saved under the `outputs/` directory (project root):
- `outputs/data/research-profiler/profiles/<name>.json`: Complete structured data
- `outputs/reports/research-profiler/<name>.md`: Markdown-format researcher report
- `outputs/cache/research-profiler/`: API + LLM response cache

If a custom `output_dir` is set in the Profiler config, all files are placed together under that directory.

It can also be used via the standalone module CLI:

```bash
python -m research analyze "Sergey Levine"                  # Analyze a researcher
python -m research analyze "Sergey Levine" --api anthropic  # Choose a backend (ollama/claude_cli/anthropic/openai)
python -m research show "Sergey Levine"                     # View a cached profile
python -m research list                                     # List all analyzed researchers
python -m research config --init                            # Initialize the Profiler config
```

### 10. Citation Graph Analysis

Perform citation graph analysis on any paper: view who cited it (forward citations), who it cited (backward references), and LLM-generated impact analysis.

#### Basic usage

```bash
# Query by arXiv ID
python tools/research/research_scout.py citations 2301.12597

# Query by DOI
python tools/research/research_scout.py citations 10.1038/s41586-023-06221-2
```

#### Parameters

```bash
# Show the top 20 citations/references (default 10)
python tools/research/research_scout.py citations 2301.12597 --top-n 20

# Use the Anthropic API for impact analysis
python tools/research/research_scout.py citations 2301.12597 --api anthropic

# Ignore the cache
python tools/research/research_scout.py citations 2301.12597 --no-cache
```

#### Output contents

```
Paper info
├── Title, year, venue, citation count
│
├── Forward citations (descending by citation count)
│   # | Year | Citations | Title | Venue
│
├── Backward references (descending by citation count)
│   # | Year | Citations | Title | Venue
│
└── LLM impact analysis (automatically triggered when citation count ≥ 5)
    ├── Reasons for being widely cited
    ├── Follow-up research directions
    └── Trends it pioneered
```

Data comes from the Semantic Scholar API, with caching support (7-day TTL).

> **Note**: Citation graph analysis is also automatically integrated into Stage 3 of the weekly report—the top 5 high-scoring papers automatically come with citation impact analysis.

### 11. Deploying to the Website

Deploy a generated weekly report to your Hugo blog:

```bash
# Deploy all undeployed reports
python tools/research/research_scout.py deploy

# Force re-deploy all reports
python tools/research/research_scout.py deploy --force
```

The Hugo site path must be configured during `config --init`.

### 12. Parameter Tuning

The priority order of parameters is: **command-line arguments > project.json > config.json > hardcoded defaults**.

#### Global defaults (config.json)

Via `config --init` or by directly editing `~/.config/research_scout/config.json`:

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

Overview of configurable parameters (Research Scout):

| Parameter | Config key | Default |
|------|-----------|--------|
| LLM backend | `default_api` | `ollama` |
| Hugo site path | `hugo_site` | `tools/website` |
| Lookback days | `default_lookback_days` | 7 |
| Max search results | `default_max_results` | 50 |
| Papers shown in report | `default_top_papers_in_report` | 5 |
| Max high-relevance | `max_high_relevance` | 20 |
| Output language | `--language` (CLI only) | `zh` |
| Insight top N | `default_insight_top_n` | 3 |
| Max full-text characters | (hardcoded) | 40000 |

#### Project-level overrides (project.json)

Some projects have a large paper volume and can be configured separately. Edit `research/projects/<id>/project.json` and add optional fields:

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

This way the `robot-manipulation` project searches 14 days and up to 100 papers by default, while other projects still use the global defaults.

#### Command-line temporary overrides

```bash
python tools/research/research_scout.py report --project robot-manipulation \
    --lookback-days 30 --max-results 200
```

Command-line arguments have the highest priority and do not affect the config files.

#### Researcher profiling configuration

The Profiler uses a separate config file, `~/.config/research/config.json`:

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

| Parameter | Config key | Default |
|------|-----------|--------|
| Claude model | `model` | `sonnet` |
| Analysis mode | `default_mode` | `fast` |
| Recursion depth | `default_depth` | `1` |
| Max students per level | `max_students` | `10` |
| Output directory | `output_dir` | `""` (empty = use default `outputs/` structure) |
| S2 API key | `semantic_scholar_api_key` | (none) |

- When `output_dir` is empty, the default unified `outputs/` directory structure is used; once set, all output is placed together in the specified directory
- `semantic_scholar_api_key` is optional; free anonymous access already has a rate limit of 10 requests per second

Initialize via `python -m research config --init`.

### 13. Workflow Examples

#### Daily workflow: once a week

```bash
# 1. Generate weekly reports for all projects (automatically includes citation impact analysis)
python tools/research/research_scout.py report

# 2. Want to deeply understand this week's most important papers? Add --insight
python tools/research/research_scout.py report --insight

# 3. View the generated reports
# Markdown reports are under the outputs/reports/research-scout/ directory
# Named as <date>-research.md

# 4. Deploy to the blog
python tools/research/research_scout.py deploy
```

#### Tracking a new direction

```bash
# 1. Create a new project
python tools/research/research_scout.py init diffusion-policy \
    --title "Diffusion Policy for Robotics" \
    --keywords "diffusion policy" "denoising diffusion" "robot learning" \
    --categories "cs.RO" "cs.LG" \
    --questions "What are the advantages of diffusion models in robot policy learning?" \
                "How can diffusion model inference be accelerated to meet real-time control?"

# 2. First search to see how many relevant papers there are recently
python tools/research/research_scout.py search --project diffusion-policy --lookback-days 30

# 3. The number of papers looks reasonable, so generate the full report
python tools/research/research_scout.py report --project diffusion-policy
```

#### Focused reading of conference papers

```bash
# Papers in ICRA 2025 related to robot manipulation
python tools/research/research_scout.py report \
    --conference "ICRA 2025" \
    --project robot-manipulation \
    --api anthropic
```

#### Getting to know a researcher

```bash
# 1. Quickly get to know a researcher
python tools/research/research_scout.py profile "Sergey Levine"

# 2. Want to go deeper? Use detailed mode (downloads full text)
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed

# 3. See what their students are working on
python tools/research/research_scout.py profile "Sergey Levine" --depth 1

# 4. Disambiguate same names
python tools/research/research_scout.py profile "Wei Zhang" --affiliation "Stanford"

# 5. Deploy directly to the blog after analysis
python tools/research/research_scout.py profile "Sergey Levine" --deploy
```

#### Deeply analyzing the impact of a paper

```bash
# 1. View a paper's citation graph
python tools/research/research_scout.py citations 2301.12597

# 2. More detail
python tools/research/research_scout.py citations 2301.12597 --top-n 20 --api anthropic
```

#### Deep research before writing a paper

```bash
# 1. Search for relevant papers
python tools/research/research_scout.py ask "sim-to-real transfer for legged robots" --insight

# The report will include:
# - Standard paper screening and evaluation
# - Writing structure analysis of each high-scoring paper (how others wrote it)
# - Publication strategy analysis (why it could be published)
# - Core knowledge extraction (what can be learned)
# - OpenReview reviews (how reviewers see it)
# - A comprehensive writing guide (how you should write)

# 2. Specify a project + more papers
python tools/research/research_scout.py report \
    --project my-project --insight --insight-top-n 5

# 3. Writing-style research on conference papers
python tools/research/research_scout.py report \
    --conference "ICLR 2025" --project my-project --insight
```

#### Cross-source biomedical research

```bash
# 1. Create a biomedical project
python tools/research/research_scout.py init brain-computer \
    --title "Brain-Computer Interfaces" \
    --keywords "brain computer interface" "neural decoding" \
    --categories "q-bio.NC" "cs.HC"

# 2. Edit project.json to add multi-source configuration
# "sources": ["arxiv", "biorxiv", "pubmed"],
# "biorxiv_categories": ["neuroscience"],
# "pubmed_journals": ["Nature Neuroscience", "Neuron"]

# 3. Generate a cross-source report
python tools/research/research_scout.py report --project brain-computer
```

### 14. File Structure Description

```
research/
├── research_scout.py          # Main program (unified CLI entry point)
├── CLAUDE.md                  # Development docs
├── TUTORIAL.md                # This tutorial
├── requirements.txt           # Python dependencies
│
├── # ── Paper discovery ──
├── projects/                  # Project definitions (git-tracked)
│   └── <project-id>/
│       ├── project.json       # Project config (keywords, categories, sources, open questions)
│       └── overview.md        # Project overview (Chinese, read by the LLM)
│
├── # ── Researcher profiling (module package) ──
├── __init__.py, __main__.py, cli.py
├── analysis.py                # Main orchestrator: BFS recursive analysis
├── models.py                  # Data classes: Paper, ResearcherProfile, ...
├── scoring.py                 # Weighted scoring + tiering
├── student_discovery.py       # Advisor-student relationship inference
├── homepage_discovery.py      # Homepage extraction + student discovery
├── llm.py                     # Multi-backend LLM wrapper
├── prompts.py                 # LLM prompt templates
├── cache.py                   # Re-export shim → common.cache.DiskCache
├── config.py                  # Profiler config
├── output.py                  # JSON persistence + Markdown report rendering + Hugo deploy
├── apis/
│   ├── arxiv_client.py        # ArXiv author search + full-text download
│   ├── semantic_scholar.py    # S2 metrics, paper data, citation graph, co-authorship analysis
│   ├── openreview_client.py   # OpenReview review fetching
│   └── rate_limiter.py        # Token-bucket rate limiter

outputs/                       # All generated files (under project root, gitignored)
├── reports/research-scout/    # Research Scout weekly reports
│   ├── <date>-research.json
│   └── <date>-research.md
├── cache/research-scout/      # Research Scout cache
│   ├── papers/                # Search result cache
│   ├── eval/                  # LLM evaluation cache (Stage 1 + Stage 2)
│   └── insight/               # Insight analysis cache (Stage 4 + Stage 5)
├── logs/research-scout/       # Rotating logs (5MB×3)
├── data/research-profiler/    # Profiler structured data
│   └── profiles/              # JSON researcher data
├── reports/research-profiler/ # Profiler Markdown reports
└── cache/research-profiler/   # Profiler cache (api/, llm/ subdirectories)
```

#### Weekly report content structure

The generated Markdown weekly report contains the following parts:

1. **High-relevance paper summary table** — score, title, type, one-sentence summary
2. **Detailed analysis** — for each high-relevance paper:
   - Scores (relevance / novelty / inspiration)
   - Two-sentence summary
   - 3 highlights, each containing: key point, design motivation, value to us, action suggestion
   - Suggestion
3. **Citation impact analysis** (automatically attached to the top 5 high-scoring papers) — each containing:
   - Citation count and number of references
   - List of high-citation follow-up work (year, citations, title, venue)
   - LLM impact analysis: why it is widely cited, follow-up directions, trends it pioneered
4. **New direction suggestions** — research direction suggestions based on the high-scoring papers (in Chinese)
5. **Paper Deep Insight** (only `--insight`) — for each analyzed paper: writing structure, publication strategy, core knowledge, reviews
6. **Research Writing Guide** (only `--insight`) — cross-paper synthesis: field writing conventions, reviewer focus, methodological takeaways, code references
7. **Literature Reading Log** — a collapsed list of low-relevance papers (one per line: title, type, authors, venue, motivation, novelty)

### 15. FAQ

#### Q: What if no papers are found?

- Check whether the keywords are too narrow; try more general terms
- Increase `--lookback-days` (such as 30 days)
- Check whether the arXiv categories are correct (`cs.RO` rather than `csRO`)
- Use `--no-cache` to rule out cache issues
- Try multi-source search: `--source arxiv biorxiv pubmed`

#### Q: The evaluation results are not satisfactory?

- Edit `overview.md` to add more research background and current progress. Stage 2 reads this content to make a more precise evaluation
- Modify the `open_questions` in `project.json` to make it clearer to the LLM what you care about
- Try a different LLM backend (`--api anthropic` vs `--api claude_cli`)
- Try English output: `--language en`

#### Q: The LLM call times out?

- The default timeout is 600 seconds (10 minutes); you can increase it with `--timeout 900`
- Reduce `--max-results` to lower the number of papers (the single Stage 1 screening call tends to time out at ~100 papers; it is recommended to keep `--max-results` within ~50, or raise `--timeout` accordingly)
- Using `--api anthropic` is usually more stable than `claude_cli`

#### Q: How do I pause/resume a project?

Edit `research/projects/<id>/project.json` and change `status` from `"active"` to `"paused"`. Paused projects are not processed by global search/report commands, but can still be explicitly targeted via `--project`.

#### Q: What is the caching mechanism?

- **Search cache** (`outputs/cache/research-scout/papers/`): search results for the same project on the same day call the API only once
- **Stage 1 cache** (`outputs/cache/research-scout/eval/`): based on a hash of project context + paper ID + first 200 chars of the abstract
- **Stage 2 cache** (`outputs/cache/research-scout/eval/`): based on a hash of project context + paper ID + first 500 chars of the abstract
- **Stage 3 citation cache** (Semantic Scholar citation graph): the weekly report's Stage 3 forward citations/backward references are also cached
- **Semantic Scholar cache** (Profiler: `outputs/cache/research-profiler/api/`): API results cached with a 7-day TTL
- **LLM cache** (Profiler: `outputs/cache/research-profiler/llm/`): based on a SHA-256 hash of backend + model + prompt
- Use `--no-cache` to skip all caches (including the Stage 3 citation cache)

#### Q: What is the difference between the researcher profiling `profile` and `citations` subcommands?

- `profile` analyzes a **researcher**: academic trajectory, scores, advisor-student relationships
- `citations` analyzes a **paper**: citation graph, impact

#### Q: Which papers does --insight analyze?

By default it analyzes the 3 papers with the highest composite_score. This can be adjusted via `--insight-top-n`, but will not exceed the number of papers shown in the report (default 5).

#### Q: What if OpenReview cannot find a match?

OpenReview matching is based on fuzzy title matching (similarity threshold 0.85). Matching may fail in the following cases:
- The paper is in a conference not on the OpenReview platform (such as CVPR, AAAI)
- The paper has not yet been submitted to a conference (pure arXiv preprint)
- The arXiv title and the submission title differ significantly

A match failure does not affect the Stage 4 insight analysis, only the reviews section is absent.

#### Q: --insight is too slow?

Full-text download + LLM analysis takes 1-3 minutes per paper. You can:
- Reduce the number analyzed: `--insight-top-n 1`
- Use a faster API: `--api anthropic` (usually faster than claude_cli)
- Full-text and insight analysis results are cached, so running the same project a second time will be fast

#### Q: Do I need to install openreview-py?

`openreview-py` is an optional dependency. If it is not installed, Stage 5 (reviews) is automatically skipped, while Stage 4 (insight analysis) and the writing guide still work normally.

Install: `pip install openreview-py`

#### Q: How do I get a Semantic Scholar API Key?

Apply at https://www.semanticscholar.org/product/api. The free tier already has a rate limit of 10 requests per second, which is usually sufficient for personal use. The API Key can be configured in the Profiler's `config --init`, or left unconfigured (using anonymous access).

## Benchmark

This tutorial walks you through using this cross-platform CPU/GPU benchmarking tool from scratch.

### 1. Environment Setup

#### Installing Dependencies

```bash
cd tools/benchmark
pip install -r requirements.txt
```

Core dependencies: `torch`, `numpy`, `pandas`, `plotly`, `tqdm`.

You can also install them manually:

```bash
pip install torch numpy pandas plotly tqdm
```

Optional dependencies:

- `threadpoolctl` — precise control over BLAS thread count (affects the accuracy of CPU all-cores tests)
- `pyopencl` — Intel/AMD GPU support (a fallback beyond CUDA and MPS)

```bash
pip install threadpoolctl  # Precise BLAS thread control
pip install pyopencl       # Intel/AMD GPU fallback support
```

#### Verifying the Installation

```bash
python -m benchmark.cli --info
```

This command prints the detected CPU, GPU, and software version information without running any benchmarks. If you can see your hardware information, the environment is configured correctly.

### 2. Running Your First Benchmark

#### Quick Try (about 2 seconds)

```bash
python -m benchmark.cli --cpu-only --matrix-size 1024 --duration 1 --no-save
```

This runs only the CPU tests, with matrix size 1024, 1 second per test, and does not save the results. It's good for confirming everything works.

#### Standard Test

```bash
python -m benchmark.cli
```

This runs all CPU and GPU benchmarks (10 seconds each by default), and the results are automatically appended to the CSV file.

Test items:

- **CPU Single-Core** — pure Python scalar operations (a `sqrt + add` loop), measuring single-core performance
- **CPU Single-Core BLAS** — NumPy matrix multiplication (single-threaded), measuring BLAS library performance
- **CPU All-Cores BLAS** — NumPy matrix multiplication (all cores), measuring multi-core parallel performance
- **GPU** — PyTorch matrix multiplication, tested separately for each supported precision (FP64/FP32/FP16/BF16)

#### Testing Only CPU or GPU

```bash
python -m benchmark.cli --cpu-only
python -m benchmark.cli --gpu-only
```

#### Example Output

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

### 3. Understanding the Results

When the run finishes, the terminal displays output similar to:

```
CPU Single-Core
  Performance: 123.45 MFLOPS/s

CPU All-Cores BLAS (8 threads, 4096x4096)
  Performance: 456.78 GFLOPS/s

GPU CUDA FP32 (NVIDIA RTX 4090, 8192x8192)
  Performance: 12.34 TFLOPS/s
```

**Unit explanation**:

- MFLOPS = millions of floating-point operations per second (CPU scalar)
- GFLOPS = billions of floating-point operations per second (CPU BLAS)
- TFLOPS = trillions of floating-point operations per second (GPU)

#### How FLOPS Is Calculated

- Scalar loop: `2 * iterations` (one sqrt + one add per iteration)
- Matrix multiplication (GEMM): `2 * N^3 * iterations` (N is the matrix size)

#### Measurement Methodology

Each test goes through three phases:

1. **Warmup** — runs 5–100 iterations (depending on the test type) to let the CPU/GPU reach a stable frequency
2. **Formal measurement** — repeatedly runs 5–50 iterations within the `--duration` time window
3. **Statistical analysis** — takes the median and removes outliers using the IQR method (`RobustTimer`)

GPU tests explicitly call `torch.cuda.synchronize()` or `torch.mps.synchronize()` after each iteration to ensure accurate timing.

#### Default Measurement Parameters

- **Duration**: 10 seconds per benchmark by default
- CPU single-core scalar: 10,000,000 scalar iterations (sqrt + add)
- CPU BLAS: matrix_size 2048 (single core), 4096 (all cores)
- GPU: matrix_size 8192 (auto-adjusted based on VRAM), 50 iterations

### 4. Generating an HTML Report

```bash
# Run benchmarks + generate the report
python -m benchmark.cli --report

# Generate the report from an existing CSV (without rerunning benchmarks)
python -m benchmark.cli --report-only
```

The report includes:

- A hardware performance leaderboard
- Comparison bar charts across different hardware
- Performance comparison for each precision
- Historical trend line charts

Default output paths:

- CSV: `outputs/data/benchmark/results.csv` (relative to the gadget project root)
- HTML: `outputs/reports/benchmark/report.html`

#### Customizing Output Paths

```bash
python -m benchmark.cli --output my_results.csv
python -m benchmark.cli --report-only --input-csv my_results.csv --report-output my_report.html
```

### 5. Accumulating Data from Multiple Machines

The CSV uses **append mode** — every run's results are appended to the end of the file rather than overwriting historical data. This makes it possible to accumulate across many different machines and track history over time; the report reads all history to generate the leaderboard and trend charts.

A typical workflow:

```bash
# Run on machine A
python -m benchmark.cli --output shared_results.csv

# Copy shared_results.csv to machine B
# Run on machine B (results appended to the same file)
python -m benchmark.cli --output shared_results.csv

# Generate a comparison report covering all hardware
python -m benchmark.cli --report-only --input-csv shared_results.csv
```

The report automatically displays every piece of hardware that has ever been tested.

### 6. Tuning Test Parameters

#### Adjusting Test Duration

```bash
# Quick test (3 seconds per item)
python -m benchmark.cli --duration 3

# High-precision test (1 minute per item)
python -m benchmark.cli --duration 60

# Paper-grade precision (5 minutes per item)
python -m benchmark.cli --duration 300
```

Longer test times = more samples = more stable results. The default 10 seconds is sufficient for everyday use.

#### Adjusting Matrix Size

```bash
# Smaller matrix (good for low-VRAM GPUs or quick tests)
python -m benchmark.cli --matrix-size 4096

# Larger matrix (fully utilizes high-end GPUs)
python -m benchmark.cli --matrix-size 16384
```

The GPU matrix size is auto-adjusted based on VRAM, but can be manually overridden.

#### Other Common Options

```bash
# Run without saving to CSV
python -m benchmark.cli --no-save

# Quiet mode (minimal output)
python -m benchmark.cli --quiet

# Verbose mode (detailed output)
python -m benchmark.cli --verbose
```

### 7. Deploying to the Website

If you have configured a Hugo website (`gadget/website/`), you can deploy the report directly:

```bash
# Run benchmarks + generate report + deploy to Hugo
python -m benchmark.cli --report --deploy

# Deploy an existing report only
python -m benchmark.cli --report-only --deploy
```

Deployment copies the HTML report into `tools/website/static/benchmark-report/`, generates the `content/benchmark.md` Hugo wrapper page, and then triggers the website build (`common.hugo.run_hugo_update()`).

### 8. Submitting Results to the Public Leaderboard

If a relay server is configured, you can submit your test results to the public leaderboard:

```bash
# After the run, interactively ask whether to upload (default No)
python -m benchmark.cli --relay-url https://relay.example.com/submit

# Auto-upload (suitable for scripts/CI)
python -m benchmark.cli --upload --relay-url https://relay.example.com/submit

# Or use an environment variable
export BENCHMARK_RELAY_URL=https://relay.example.com/submit
python -m benchmark.cli

# Explicitly disable the upload flow
python -m benchmark.cli --no-upload
```

Notes:

- The upload prompt only appears after a benchmark run with saving enabled (`--no-save` disables it).
- An upload failure does not affect your local test results.
- `--report-only` and `--info` do not trigger upload behavior.

#### Manual Submission

```bash
# Preview the data to submit (takes the last row of the CSV)
python scripts/submit_result.py --dry-run

# Submit the last row of the CSV to the relay endpoint
python scripts/submit_result.py --relay-url https://relay.example.com/submit

# Trusted direct GitHub dispatch (requires a token)
python scripts/submit_result.py \
  --github-owner YOUR_ORG \
  --github-repo YOUR_REPO \
  --github-token "$GITHUB_TOKEN"
```

#### Testing Ingestion Locally

```bash
python scripts/ingest_submissions.py \
  --pending-file data/pending_submissions.ndjson \
  --csv-path benchmark_results.csv \
  --rejected-file data/rejected_submissions.ndjson \
  --log-file data/ingest_log.json
```

Queue/audit files:

- `data/pending_submissions.ndjson`: raw queued submissions
- `data/rejected_submissions.ndjson`: rejected records and their reasons
- `data/ingest_log.json`: summary of the most recent ingest

Validation rules in `ingest_submissions.py`:

- Must contain all 20 CSV columns
- `backend` is in `{cpu, cuda, mps, xpu, opencl, ocl}`
- `benchmark_type` is in `{gpu, cpu_single_core, cpu_single_core_blas, cpu_all_cores}` (or has a `cpu_*` prefix)
- Numeric range checks (e.g. `cpu_cores` 1–2048, `flops_gflops` > 0, `time_seconds` < 3600)
- PII redaction: emails, IPs, hostnames, and user paths are masked
- SHA-256 fingerprint deduplication (based on date + hardware + benchmark type + result)

#### Website Auto-Update Pipeline

The repository contains a GitHub-based pipeline that publishes benchmark reports as a website and continuously updates from queued submissions:

- `.github/workflows/accept-submission.yml` — receives the `repository_dispatch` event `benchmark_submission` and appends the payload to `data/pending_submissions.ndjson`
- `.github/workflows/daily-publish.yml` — runs daily (`00:00 UTC`) or manually: consumes the queue with strict validation/deduplication/redaction and regenerates the report when the dataset changes
- `.github/workflows/pages-deploy.yml` — deploys the benchmark report to GitHub Pages

GitHub configuration checklist:

- Enable **GitHub Pages** with the source set to **GitHub Actions**
- Ensure workflow permissions allow Actions to write to the repository
- If using direct dispatch, you need a token that can invoke repository dispatch events
- For public-facing collection, run a separate relay server that does validation/rate-limiting and forwards the payload to `repository_dispatch`

### 9. GPU Backend Compatibility Cheat Sheet

| Precision | CUDA (NVIDIA) | MPS (Apple) | XPU (Intel) |
|---------|:---:|:---:|:---:|
| FP64    | ✓   | ✗   | ✓   |
| FP32    | ✓   | ✓   | ✓   |
| FP16    | ✓   | ✓   | ✓   |
| BF16    | ✓   | ✗   | ✓   |
| FP8_exp | ✓*  | ✗   | ✗   |

\* FP8 requires CUDA 8.9+, and PyTorch does not yet fully support it.

Platform support matrix:

| Platform | CPU | GPU (NVIDIA) | GPU (Apple) | GPU (Intel) | GPU (AMD) |
|----------|-----|--------------|-------------|-------------|-----------|
| Linux    | ✓   | ✓ (CUDA)     | ✗           | ✓ (XPU/OCL) | ✓ (OCL)   |
| macOS    | ✓   | ✗            | ✓ (MPS)     | ✗           | ✗         |
| Windows  | ✓   | ✓ (CUDA)     | ✗           | ✓ (XPU/OCL) | ✓ (OCL)   |

MPS (Apple Silicon) does not support FP64 or BF16. FP8 matmul requires CUDA compute capability 8.9+ and a compatible PyTorch build, which PyTorch does not yet fully support.

### 10. CSV Format

The CSV file records all benchmark results in append mode, containing the following columns:

| Column | Description |
|--------|-------------|
| `timestamp` | ISO-format timestamp |
| `cpu_model` | CPU model name |
| `cpu_cores` | Number of CPU cores |
| `cpu_frequency` | CPU frequency (GHz) |
| `gpu_vendor` | GPU vendor (NVIDIA/Apple/Intel/AMD) |
| `gpu_model` | GPU model name |
| `gpu_memory_gb` | GPU VRAM (GB) |
| `gpu_compute_capability` | Compute capability version |
| `benchmark_name` | Benchmark name |
| `benchmark_type` | Type (cpu_single_core, cpu_all_cores, gpu) |
| `backend` | Backend (cpu/cuda/mps/xpu) |
| `dtype` | Data type (FP64/FP32/FP16/BF16/FP8) |
| `matrix_size` | Matrix size for GEMM benchmarks |
| `flops_gflops` | Performance (GFLOPS) |
| `time_seconds` | Median time per iteration |
| `iterations` | Number of iterations |
| `os` | Operating system |
| `python_version` | Python version |
| `torch_version` | PyTorch version |
| `cuda_version` | CUDA version (if applicable) |

### 11. Python API

```python
from benchmark import get_system_info, cpu, gpu, core

# Get system info
system_info = get_system_info()

# Run CPU benchmarks
cpu_results = cpu.run_all_cpu_benchmarks()

# Run GPU benchmarks
gpu_results = gpu.run_all_gpu_benchmarks()

# Save to CSV
results_manager = core.BenchmarkResults('output.csv')
for result in cpu_results + gpu_results:
    results_manager.add(result, system_info)
results_manager.save()
```

### 12. Tips for Getting Stable Results

- Close background applications to reduce interference
- Ensure the device is well-cooled (thermal throttling reduces performance)
- Use a longer `--duration` (60 seconds or more)
- Run multiple times and take the best value — CSV append mode preserves all historical data, and the report automatically picks the best
- Plug in laptops while running
- GPU support depends on whether PyTorch has the corresponding backend installed

## Website

A complete build-and-deploy tutorial for the Hugo blog (PaperMod theme): from local-model translation, Markdown rewriting, incremental media compression, preflight checks, to Hugo build and GitHub Pages push — over a single content root shared by generated and hand-written posts.

### Installing Dependencies

```bash
# Install website runtime dependencies (translation deps install automatically with the website group: torch + transformers)
pip install -e ".[website]"
# The model tencent/Hy-MT2-1.8B is auto-downloaded on first run
```

External tool dependencies:

- **Hugo extended** (v0.125.7+)
- **Python 3 + PIL/Pillow** — the JPEG→PNG conversion in `compress_image.py`
- **Python torch + transformers** — translation; on Linux, vLLM optionally accelerates batch inference
- **pngquant** — image compression
- **HandBrakeCLI** — video compression

Platform notes:

- **Windows**: use `update.ps1` instead of `update.sh`; image/video compression is automatically skipped when `pngquant` or `HandBrakeCLI` is not installed; use `python` (not `python3`).
- **macOS/Linux**: use `update.sh`; the compression steps require `pngquant` and `HandBrakeCLI`.

### One-Command Build + Deploy

All commands are run from the `tools/website/` directory:

```bash
cd tools/website

bash update.sh                                        # macOS/Linux
powershell -ExecutionPolicy Bypass -File update.ps1   # Windows
```

`update.sh` is an eight-step sequential pipeline (detailed in the next section). Content translation, Hugo build, and push all happen automatically; the `.last_build` timestamp ensures only changed files are processed. `content/` and `static/` are the **single Hugo roots** — deploy pipelines (summarize/research/benchmark) write generated posts directly into them, marked with `gadget_generated: true` frontmatter; hand-written posts live in the same tree without the marker and are never overwritten by pipelines.

### Build Pipeline (the eight steps of `update.sh`)

1. **Content translation** — `translate_site_batch.py --root content --state-file .translation_state.json` backfills missing or changed `*.md` / `*.zh.md` pairs across the whole content tree (generated + hand-written), using local batch inference (`tencent/Hy-MT2-1.8B`). Complete valid pairs are recorded/skipped for free; a failure in the translation stage does not block the subsequent build.
2. **Markdown rewriting** — for hand-written `.md` files modified since `.last_build`: replace `../../static` with the site URL (read from `baseURL` in `config.yml`), change `.jpg`/`.jpeg` extensions to `.png`, and convert local video links into the Hugo `{{< video >}}` shortcode. Generated dirs (bugJournal daily/weekly/monthly, research) and `benchmark*.md` are excluded — pipeline output is already URL-correct.
3. **Image compression** — for images updated since `.last_build`, run `compress_image.py` in parallel (skipped if `pngquant` is not installed).
4. **Video compression** — for updated videos, run `compress_video.py` in parallel, falling back to `HandBrakeCLI` when the script is absent (skipped if neither is installed nor present).
5. **Preflight check** — `preflight_check.py` validates modified hand-written content for images/links/frontmatter/bilingual/language (generated dirs excluded); the build is aborted if a blocking error is found (exit 1).
6. **Clean and rebuild `public/`** — empty `public/` (keeping `.git`), then run `hugo`.
7. **Commit and push** — `cd public && git add -A`, and if there are changes, `git commit && git push` (the first push uses `git push -u origin <branch>`), followed by `git gc --aggressive`.
8. **Update the timestamp** — `touch .last_build`, for the next incremental run.

> `.last_build` records what has already been processed. Deleting it forces a full rebuild.

### Local Preview (dev server)

```bash
cd tools/website
hugo server -D          # includes drafts, local hot-reload preview
hugo                    # build only, no deploy
```

### Incremental Translation State (`translate_site_batch.py`)

`translate_site_batch.py` incrementally syncs English/Chinese Hugo markdown pairs, purpose-built to be called before the `update.sh` build:

- Two canonical file forms: English/default `foo.md`, Chinese `foo.zh.md`.
- Backfills the missing counterpart; detects which side changed since the last successful sync.
- Uses a local state file `.translation_state.json` to avoid en↔zh translation ping-ponging back and forth.
- Translation uses local inference (vLLM on Linux, transformers on Windows).

Common parameters: `--root <directory>` (translation root), `--state-file .translation_state.json` (state file), `--exclude <path>` (exclude a section, can be passed multiple times).

### Preflight (`preflight_check.py`)

Runs between media compression (Step 6) and the Hugo build (Step 8), checking files modified since `.last_build`:

1. Uncompressed images (leftover `.jpg`/`.jpeg`)
2. Broken links (un-rewritten `../../static` references)
3. frontmatter YAML validity
4. Bilingual pair completeness (`.md` ↔ `.zh.md`) — auto-generates the missing counterpart
5. Language correctness (`.md` should have English body text, `.zh.md` should have Chinese body text) — auto-fixed

Language-aware pair generation (check 4):

- `foo.md` exists and has Chinese content → copy to `foo.zh.md`, and translate `foo.md` into English
- `foo.md` exists and has English content → translate to generate `foo.zh.md`
- `foo.zh.md` exists and has English content → copy to `foo.md`, and translate `foo.zh.md` into Chinese
- `foo.zh.md` exists and has Chinese content → translate to generate `foo.md`

Severity tiers:

- **BLOCK** → exit 1, abort the build (frontmatter errors)
- **WARN** → printed but the build continues (broken links, uncompressed images)
- **FIX** → auto-fixed via the translation engine (missing pairs, language mismatch)

Exit codes: `0` = clean; `1` = blocking error; `2` = warnings only.

### Generated content (single content root)

There is no staging layer and no `sync_staging.py` (removed 2026-07). Deploy pipelines write generated posts directly into the site tree via `common.site_staging`:

| Writer | Website target | Marker |
|--------|----------------|--------|
| `python -m summarize daily deploy` | `content/bugJournal/daily/` | `gadget:src-hash` + `gadget_generated` |
| `python -m summarize weekly deploy` / `generate --deploy` | `content/bugJournal/weekly/` + `static/images/weekly/` | same |
| `python -m summarize monthly deploy` / `generate --deploy` | `content/bugJournal/monthly/` + `static/images/monthly/` | same |
| `research_scout.py deploy` / profiler `--deploy` | `content/research/` | same |
| `benchmark.cli --report --deploy` | `content/benchmark.md` + `static/benchmark-report/` | `gadget_generated` |

Files **without** a gadget marker are treated as human-written: pipelines refuse to overwrite them (explicit `--overwrite-human` required). `--force` redeploys back the previous generated file up into `outputs/backups/website-force/YYYYMMDD-HHMMSS/` (with a `manifest.json` recording sha256/paths/ownership) before overwriting.

### Authoring Content

```bash
# Create new content
hugo new bugJournal/2026-03-03.md
hugo new leetcode/problem-name.md

# Compress a single image (JPEG→PNG, using pngquant)
python compress_image.py static/images/path/to/image.png

# Compress a single video (using HandBrakeCLI, 720p30, no audio track)
python compress_video.py static/videos/path/to/video.mp4
```

### Content Sections

| Section | Path | Archetype | Description |
|---------|------|-----------|-------------|
| bugJournal | `content/bugJournal/` | `archetypes/bugJournal.md` | Debugging logs, with daily/weekly/monthly sub-sections |
| benchmark | `content/benchmark.md` | n/a | Auto-generated benchmark wrapper page, pointing to the latest HTML leaderboard |
| leetcode | `content/leetcode/` | `archetypes/leetcode.md` | Algorithm problem solutions, with complexity analysis |
| posts | `content/posts/` | `archetypes/default.md` | Blog posts and study notes |

Special pages (content root): `Resume.md`, `Search.md`, `Random.md`.

### Static Assets

- **Images**: `static/images/` — organized in date folders, uniformly using `.png` (JPEG is auto-converted).
- **Videos**: `static/videos/` — organized in date folders, using the `{{< video src="/videos/..." >}}` shortcode, not markdown links.
- **PDFs**: `static/pdfs/`

### Hugo Configuration (`config.yml`)

- **Theme**: PaperMod (located at `themes/PaperMod/`)
- **Goldmark unsafe mode**: enabled (raw HTML allowed in markdown)
- **MathJax/LaTeX**: enabled via `mathjax: true` and `math: true`
- **Search**: powered by Fuse.js, requires the JSON output format
- **Busuanzi**: page view counter enabled
- **Hugo version**: requires v0.125.7+ extended

### Key Conventions

- Markdown references images with absolute site URLs (`https://tzj2006.github.io/images/...`), not relative paths — `update.sh` automatically rewrites `../../static` references.
- Video embeds use the custom shortcode `{{< video src="/videos/file.mp4" type="video/mp4" preload="auto" width="360" >}}`, not standard markdown.
- bug journal filenames follow the `YYYY-MM-DD.md` date format.
- The comments in `update.sh` are in Chinese.

### Git Tracking Rules

Unless listed in the tracking allowlist below, do not `git add` anything under `website/content/` or `website/static/`. Most content and static assets are auto-generated (written by deploy pipelines, carrying `gadget_generated` markers), externally synced (rclone `website` category), or belong to separate repos (`public/` is the GitHub Pages deployment repo, `themes/` is the cloned Hugo theme).

**Key tracked files (non-exhaustive)**: `CLAUDE.md`, `config.yml`, `archetypes/`, `layouts/`, `assets/`, `content/Search.md`, `content/bugJournal/_index.md`, build scripts (`update.sh`, `update.ps1`, `compress_*.py`, `preflight_check.py`, `translate_site_batch.py`).

## Translator

Complete usage guide for the Gradio document translator. It reuses the local translation engine from `common`, translating text and files while preserving Markdown formatting. The tool itself is just UI wiring (`tools/translator/app.py`) + file ingestion (`tools/translator/core.py`); the core translation logic lives in `common/engine.py` and `common/translation.py`.

### 1. Installation

The optional-dependency extra for translator is `translator`, which includes Gradio and the GGUF translation stack (`gradio>=4.0.0` + `gadget[translation-gguf]`, i.e. `llama-cpp-python` + `huggingface-hub`):

```bash
pip install -e ".[translator]"
```

If you want to use other backends, add the corresponding extra as needed:

```bash
pip install -e ".[translation]"        # transformers backend (Windows fallback): torch + transformers
# On Linux, additionally install vLLM manually (faster batch inference):
pip install "vllm>=0.8"
```

> The default model `tencent/Hy-MT2-1.8B` (GGUF variant `tencent/Hy-MT2-1.8B-GGUF`) is automatically downloaded from HuggingFace on first use.

### 2. Launching the GUI

```bash
python -m translator
```

This calls `main()` in `tools/translator/app.py`: it first injects `127.0.0.1,localhost` into `NO_PROXY` / `no_proxy` (bypassing the proxy's interception of the localhost health check, otherwise gradio's `launch()` may raise `WinError 10061` on Windows), then builds and `launch()`es the Gradio interface. Once started, open the local address shown in the prompt in your browser.

### 3. Gradio UI Usage

The interface is titled **Gadget Translate**, with three dropdowns at the top + two tabs.

Top control bar:

- **Model**: model dropdown, defaulting to the first item in the list; selecting a model for the first time downloads and loads it (7B / FP8 models are large). Candidates come from `~/.config/gadget/translator_models.json`; when no config file exists, it falls back to the built-in default list (`tencent/Hy-MT2-1.8B`, `tencent/Hy-MT2-1.8B-FP8`, `tencent/Hy-MT2-7B`, `tencent/Hy-MT2-7B-FP8`).
- **Source** / **Target**: choose from `auto` / `zh` / `en`.
  - `auto` source: auto-detected by the text's CJK ratio (`common.translation.detect_language`).
  - `auto` target: automatically flips between zh↔en (if Chinese is detected, translate to English, otherwise translate to Chinese).

#### "Translate" Tab

- On the left is the multimodal input box **Source**: you can directly paste/type text, or drag in or select a file. Supported file types: `.md` `.markdown` `.txt` `.pdf` `.docx` `.png` `.jpg` `.jpeg` (single file).
- The right side **Translation** displays the result.
- Click the **Translate** button to trigger it. Submission rule: **when a file is present, the file takes priority**, otherwise the typed text is used; if both are empty it prompts "enter text or drag in a file".
- For file translation, the **Download** below provides the converted/translated document (named `<original-name>.<target-language>.md`, written to the system temp directory).
- The status line at the bottom shows progress and speed: success is `✅ <src> → <tgt> · <n> tok · <s>s · <r> tok/s` (speed only counts the generation phase, excluding model loading and OCR conversion); failure is `❌ <error message>` (any exception is caught and displayed without crashing the interface).

File handling details (`tools/translator/core.py`):

- `.txt` / `.md` / `.markdown`: read directly as UTF-8.
- `.docx`: read `word/document.xml` directly using stdlib (`zipfile` + `xml`), with no dependencies and lossless for body text; `HeadingN` styles are converted to `#`..`######`, tables are flattened to cell text, and images/graphics are discarded. (It does not go through marker, avoiding the weasyprint native dependency of docx→pdf.)
- `.pdf` / images: invoke the `marker_single` CLI to OCR-convert to Markdown, running as a subprocess in the `deepseek-ocr` conda environment (isolating its torch/surya stack from this environment). Requires `conda` to be on the PATH and that environment to have `marker-pdf` installed; otherwise the status line gives a clear error (cannot find `conda`, timeout, empty Markdown output, etc.).

#### "Models" Tab

Add or remove translation models by entering a HuggingFace repo id (in the form `org/Model-Name`). Changes take effect immediately and are persisted to `~/.config/gadget/translator_models.json`.

- **Add**: enter a repo id and click add; empty or duplicate entries are a no-op.
- **Delete selected**: deletes the model selected in the dropdown; if the list becomes empty, it falls back to the built-in default list.

### 4. Backend and Model Environment Variables

The translation pipeline does not use the `--api` flag; instead `common.engine.create_engine()` automatically selects the backend. You can override it with the following environment variables (export them before starting `python -m translator`):

| Environment Variable | Effect |
|----------|------|
| `GADGET_TRANSLATION_MODEL` | Overrides the default model (HuggingFace repo id). Used as the GGUF model id under the `llamacpp` backend. |
| `GADGET_TRANSLATION_BACKEND` | Force the backend: `ollama` / `vllm` / `transformers` / `llamacpp`. Leave empty for automatic selection: prefer Ollama when the default model's tag is pulled, otherwise vLLM if available, otherwise GGUF if llama-cpp is available, otherwise transformers. |
| `GADGET_TRANSLATION_BATCH_SIZE` | Batch size (default `0` = automatically estimated from VRAM). |

Translator-specific fine-tuning environment variables (`tools/translator/core.py`):

| Environment Variable | Default | Effect |
|----------|------|------|
| `TRANSLATOR_MICRO_CHUNK_CHARS` | `1000` | Micro-chunk character count for multi-segment input (the GPU is limited by startup overhead at batch=1, so chunked batch processing is the main speedup lever). Adjustable if quality drifts. |
| `TRANSLATOR_CONTEXT_CHARS` | `3000` | Upper character limit of document background injected into each chunk's prompt, keeping terminology/reference consistent; only takes effect when the chunk count is >1, `0` disables it. |
| `TRANSLATOR_MARKER_ENV` | `deepseek-ocr` | The conda environment name for running `marker_single`. |
| `TRANSLATOR_MARKER_TIMEOUT` | `600` | The marker OCR subprocess timeout (seconds). |

Examples:

```bash
# Force the transformers backend + specify the model
GADGET_TRANSLATION_BACKEND=transformers GADGET_TRANSLATION_MODEL=tencent/Hy-MT2-1.8B python -m translator

# When marker is installed in a differently named environment
TRANSLATOR_MARKER_ENV=my-ocr python -m translator
```

### 5. Low-VRAM GGUF Path

The GGUF backend (`llama-cpp-python`) is fast, frugal with VRAM, and does not need PyTorch, making it suitable for machines with tight VRAM or no GPU. `pip install -e ".[translator]"` already includes the GGUF stack (the `translator` extra depends on `gadget[translation-gguf]`).

Explicitly go through GGUF:

```bash
# Force the llamacpp backend; defaults to the GGUF model tencent/Hy-MT2-1.8B-GGUF
GADGET_TRANSLATION_BACKEND=llamacpp python -m translator

# Specify a GGUF model
GADGET_TRANSLATION_BACKEND=llamacpp GADGET_TRANSLATION_MODEL=tencent/Hy-MT2-1.8B-GGUF python -m translator
```

When the backend is not forced, the automatic selection logic (`common/engine.py`) is: vLLM available → vLLM; otherwise llama-cpp available → GGUF (when the model is the default model, it automatically switches to the corresponding GGUF variant); otherwise → transformers.

### Related Files

- Entry point: `tools/translator/__main__.py`
- UI: `tools/translator/app.py`
- Translation/file logic: `tools/translator/core.py`
- Model list: `tools/translator/models.py` (`~/.config/gadget/translator_models.json`)
- Shared engine: `common/engine.py`, `common/translation.py`
