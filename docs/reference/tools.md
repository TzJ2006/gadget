# Tool Inventory

Practical "how do I run it and where does its stuff go" reference for the five
tools + the sync script. All commands assume `pip install -e .` (or the tool's
extra) so `common` and the tool packages are importable. Config resolution is
**CLI flag > env var > config.json > default** everywhere.

> Default LLM backend is `ollama` (local, keyless — needs a running Ollama with
> `qwen3.6:35b`), **not** a cloud key. Switch with `--api` or `GADGET_LLM_BACKEND`.

---

## summarize — AI conversation summarization

- **Run**: `python -m summarize {daily,weekly,monthly,auto,onboard} [args]`
  - `python -m summarize daily export --date 2026-02-13 --summarize`
  - `python -m summarize daily merge --sync-all`
  - `python -m summarize auto --deploy`
- **Config**: `SUMMARIZE_CONFIG` env (explicit path — beats both lookups; test isolation / multi-config switching), else repo-local `tools/summarize/config.json` (preferred; copy `config.example.json`), else `~/.config/summarize/config.json`. Init: `python -m summarize daily config --init`.
- **Outputs**: `outputs/logs/summarize/` (export logs + usage), `outputs/reports/summarize/` (daily/weekly/monthly `.json`+`.md`), `outputs/images/summarize/` (usage PNGs), `outputs/cache/summarize/` (chunk cache).
- **Gotchas**: startup runs `apply_env_from_config()` which bridges config keys → env vars via `os.environ.setdefault` (a real exported env var still wins). `cli_defaults()` lets config supply `--api`/`--deploy`/`--hugo-site`/`--workers`. Runs fine from repo root.
- Evidence: `tools/summarize/__main__.py:13-46`, `cli.py:38-112`, `config.py:15-26,100-118`.

## research — paper scout + profiler + citation graph

- **Run**: `python tools/research/research_scout.py {init,ask,list,search,report,profile,citations,deploy,config} [args]`
  - `python tools/research/research_scout.py report --project my-project --api claude_cli`
  - `python tools/research/research_scout.py ask "找 Pieter Abbeel 最近的机器人操作论文"`
  - Profiler standalone: `python -m research {analyze,show,list,config}`
- **Config**: scout `~/.config/research_scout/config.json` (primary); profiler `~/.config/research/config.json` (fallback, merged — scout keys win). Init: `research_scout.py config --init` (scout) and `python -m research config --init` (profiler).
- **Outputs**: scout → `outputs/reports/research-scout/`, `outputs/cache/research-scout/{eval,papers,insight}/`, `outputs/logs/research-scout/research_scout.log`. Profiler → `outputs/data/research-profiler/profiles/`, `outputs/reports/research-profiler/`. Project defs live in `tools/research/projects/<name>/`.
- **Gotchas**: `research_scout.py` is a **deprecation shim** (emits `DeprecationWarning`, inserts repo root on `sys.path`) — real logic in `scout/`. Stage-1 screening times out on ~100 papers → cap `--max-results ~50` or raise `--timeout`. `--conference`/`--author` are mutually exclusive. `--insight` (Stage 4/5) needs `openreview-py`; PyMuPDF optional for full-text.
- Evidence: `research_scout.py:25-35`, `scout/cli.py:838-937`, `scout/config.py:53-54`, `config.py:10-11`.

## benchmark — CPU/GPU FLOPS benchmark

- **Run**: `cd tools/benchmark && python -m benchmark.cli [--cpu-only|--gpu-only|--report|--report-only|--deploy|--info]`
  - `cd tools/benchmark && python -m benchmark.cli --report --deploy`
  - `cd tools/benchmark && python -m benchmark.cli --info` (prints hardware, writes nothing)
- **Config**: none — all CLI flags. Only env fallback is `BENCHMARK_RELAY_URL` (optional leaderboard upload).
- **Outputs**: CSV `outputs/data/benchmark/results.csv` (append-only, `--output` to override), HTML `outputs/reports/benchmark/report.html`. `--deploy` copies the HTML to `tools/website/static/benchmark-report/` + writes the `content/benchmark.md` wrapper, then runs Hugo.
- **Gotchas**: the `benchmark` package IS installed editable so `python -m benchmark.cli` resolves anywhere, **but importing it requires `torch/numpy/pandas/plotly/tqdm`** — in a bare env it dies at import with `ModuleNotFoundError: plotly`; install `pip install -r requirements.txt` (or `pip install -e ".[benchmark]"`). Bare `python -m benchmark.cli` (no flags) runs benchmarks and **writes CSV** — use `--info`/`--report-only` for read-only.
- Evidence: `tools/benchmark/benchmark/cli.py:22-23,84-244,334-337`, `pyproject.toml:19`.

## website — Hugo blog build + deploy

- **Run**: `cd tools/website && bash update.sh` (macOS/Linux/Git-Bash). Windows: `powershell -ExecutionPolicy Bypass -File update.ps1`. Dev preview: `hugo server -D`.
- **Read-only audit**: `python tools/website/preflight_check.py --no-fix` (reports pair/language issues, writes nothing, loads no model).
- **Config**: no JSON config — reads Hugo `config.yml`, state files `.last_build` (incremental) and `.translation_state.json`.
- **Outputs**: builds into `tools/website/public/` — a **separate git repo** (`tzj2006.github.io`) pushed to GitHub Pages. `content/` + `static/` are the single Hugo roots (generated + hand-written together; generated files carry `gadget_generated`/`gadget:src-hash` markers).
- **Gotchas**: `update.sh` is bash-only (`set -euo pipefail`, `find`/`sed`/`mapfile`) — on Windows use `update.ps1`. `preflight_check.py` exit codes: `0` clean, `2` WARN, `1` BLOCK (BLOCK aborts the build). Preflight **auto-fix** (default, no `--no-fix`) and translation steps load the local translation engine (heavy). Needs Hugo extended ≥ 0.125.7; `pngquant`/`HandBrakeCLI` optional. **Never manually commit into `public/`** — `update.sh` owns that repo.
- Evidence: `tools/website/update.sh:1-24,159-199`, `preflight_check.py:390-467`.

## translator — Gradio document/text translator

- **Run**: `python -m translator` (launches Gradio UI on `127.0.0.1`).
- **Config**: `~/.config/gadget/translator_models.json` — the model dropdown list, edited via the UI. Defaults: `tencent/Hy-MT2-1.8B` (+ `-1.8B-FP8`, `-7B`, `-7B-FP8`).
- **Outputs**: none persistent — file translation writes `<stem>.<lang>.md` to the OS temp dir for download.
- **Gotchas**: needs the `translator` extra (gradio + translation-gguf). `main()` prepends `127.0.0.1,localhost` to `NO_PROXY` so Gradio's launch health-check isn't routed through an HTTP proxy (else `WinError 10061` on Windows). 7B/FP8 models download + cold-load on first use. Not in the `all` extra by design.
- Evidence: `tools/translator/__main__.py:3-6`, `app.py:138-145`, `models.py:15-22`.

## scripts/sync — rclone data sync (Google Drive)

- **Run**: `python scripts/sync.py {push,pull,status,bootstrap,config} [--category N] [--dry-run]`
  - `python scripts/sync.py status`
  - `python scripts/sync.py push --category summarize`
  - `python scripts/sync.py config --init`
  - Special: `python scripts/sync.py --category dag` (no subcommand — generates + deploys the encrypted DAG site).
- **Config**: `~/.config/gadget/sync.json` (`rclone_remote`, `rclone_path`); if absent, derives from summarize config. Init: `python scripts/sync.py config --init`.
- **Outputs**: no local dir — rclone-copies local trees ↔ remote (summarize logs/reports/images, research projects+cache, benchmark data, website content, etc.).
- **Gotchas**: needs the `rclone` binary on PATH (else hard exit). `status` does **network I/O** (`rclone check`, compare-only, no writes). The `dag` category is not a GDrive sync — it needs `STATICRYPT_PASSWORD`, Node/npx/tsx, and the sibling `../ai-companion` repo, and it triggers `update.sh`.
- Evidence: `scripts/sync.py:42-44,65-113,533-553,594-655`.

---

For failure isolation and log/cache locations, see `debugging.md`. For adding
features safely, see `development.md`.
