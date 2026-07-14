# Running summarize on a local LLM (Ollama, RTX 5090)

Recorded 2026-06-30. summarize (and any `common.llm` `openai`-backend caller) can run
against a **local Ollama server** instead of a cloud API — no `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`, everything on-GPU.

- **Default runtime: Windows-native Ollama.** WSL2 works identically (see the comparison
  below) but Windows is the standard because it's simpler to keep running (tray service,
  no distro idle-shutdown) and the summarize client runs natively in the same place.
- **Model:** `qwen3.6:35b` — Qwen3.6-35B-A3B, a 35B-total / 3B-active hybrid Mamba+attention
  MoE, 4-bit GGUF (~23 GB). Runs **100% on GPU**. A `num_ctx`-enlarged variant `qwen3.6-sum`
  is what summarize actually points at.
- **Host:** single RTX 5090 (32 GB, Blackwell SM_120).
- **Serving:** Ollama 0.31 — bundles its own CUDA (`cuda_v13`), so there is **no
  CUDA-toolkit / nvcc / kernel-JIT setup** (that's why we use Ollama and not vLLM here;
  see [Why Ollama, not vLLM](#why-ollama-not-vllm)).

Translation (the HY-MT model) now **also runs through Ollama by default** — `common.engine`
adds an `OllamaEngine` that calls the same local server (native `/api/chat`) for
`tencent/Hy-MT2-1.8B`. It's auto-selected when Ollama has the model pulled
(`ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF`), and falls back to the in-process
llama.cpp GGUF engine otherwise. Force a backend with `GADGET_TRANSLATION_BACKEND`
(`ollama`/`llamacpp`/`vllm`/`transformers`). See [Translation on Windows](#translation-on-windows).

---

## Windows-native setup (default)

Everything runs in **base conda** (py3.13) — it already has `openai` and the editable
`gadget` package, so **no separate `AI` env is needed on Windows.**

1. **Install Ollama for Windows** — download the installer from <https://ollama.com/download>.
   It installs a background service (tray icon) that auto-starts and listens on `:11434`.
   Verify: `ollama --version` and `curl http://localhost:11434/api/version`.
2. **Pull the model** (~23 GB): `ollama pull qwen3.6:35b`
3. **Create the summarize-tuned variant** (larger context) — from Git Bash:
   ```bash
   bash scripts/serve_local_llm.sh        # creates qwen3.6-sum (num_ctx 65536)
   ```
4. **Point summarize at it and run** — from Git Bash, in `tools/`:
   ```bash
   eval "$(bash ../scripts/serve_local_llm.sh env)"   # exports OLLAMA_MODEL + reasoning knob
   cd /d/Github/gadget/tools
   python -m summarize auto --api ollama                       # full daily→weekly→monthly
   # single date, explicit local logs (merge does NOT auto-glob from --date alone):
   python -m summarize daily merge --date 2026-06-26 --api ollama \
     ../outputs/logs/summarize/2026-06-26_*.json
   ```
   > PowerShell equivalent for the env vars:
   > ```powershell
   > $env:OLLAMA_MODEL="qwen3.6-sum"; $env:OPENAI_REASONING_EFFORT="none"
   > ```
   > The `ollama` backend defaults to `http://127.0.0.1:11434/v1` and is keyless, so
   > no base-url/key vars are needed for the localhost case.

---

## How it works (code)

There are two distinct backend families, kept separate:

- **`--api ollama`** (`call_ollama` in `common/llm.py`) — the local path. Defaults to
  `127.0.0.1:11434/v1` (not `localhost` — Windows resolves that IPv6-first and stalls ~2s per
  request), keyless, reads `OLLAMA_MODEL`. Use this for local summarization.
- **`--api openai`** (`call_openai`) — real cloud OpenAI, **or** an explicit
  `OPENAI_BASE_URL` override (legacy way to reach a local server; still works).

Both speak the OpenAI protocol and share the same HTTP core; they differ only in config.

| Env var | Backend | Purpose |
|---------|---------|---------|
| `OLLAMA_MODEL` | ollama | Served model id, e.g. `qwen3.6-sum`. Falls back to `OPENAI_MODEL`. |
| `OLLAMA_BASE_URL` | ollama | Endpoint override; defaults to `http://127.0.0.1:11434/v1`. Falls back to `OPENAI_BASE_URL`. |
| `OPENAI_BASE_URL` | openai | Endpoint for the `openai` backend (real OpenAI if unset). |
| `OPENAI_MODEL` | openai | Served model id (local servers don't use `gpt-4o`). |
| `OPENAI_API_KEY` | both | Real OpenAI needs it; ollama ignores it (keyless). |
| `OPENAI_REASONING_EFFORT` | both | Passed via `extra_body`. Set to `none` to disable a reasoning model's `<think>` phase. **Essential** — see gotchas. Unset ⇒ no effect. |

`tools/summarize/onboarding.py` preflight accepts `--api ollama` (keyless local) and
`OPENAI_BASE_URL` in place of a key for `--api openai`.

---

## Verified test result (2026-06-26 daily merge) + WSL vs Windows

Ran `daily merge` over 4 device logs (15 conversations, 1,469 messages, 472,328 chars).
summarize hierarchically chunked it into **4 segments + 1 merge = 5 LLM calls**. Both hosts
produced a valid report; timing is Ollama's own server-side measurement.

| Call | Input tok | WSL prefill | Win prefill | WSL decode | Win decode |
|------|----------:|------------:|------------:|-----------:|-----------:|
| chunk 1 | 27,644 | 6,319 t/s | 784 t/s\* | 157.7 t/s | 186.9 t/s |
| chunk 2 | 51,772 | 6,292 | 6,260 | 185.8 | 181.4 |
| chunk 3 | 47,036 | 6,445 | 6,383 | 187.7 | 185.5 |
| chunk 4 | 44,519 | 6,442 | 6,454 | 189.4 | 187.8 |
| merge   | 10,129 | 6,872 | 6,824 | 208.5 | 220.1 |

\* Windows chunk 1's 784 t/s is a **cold model load** (~30 s to load 23 GB into VRAM) folded
into the first prefill; the WSL run was pre-warmed. Not an architectural difference.

**Warm averages: prefill ~6,475 t/s (both), decode ~186 t/s (WSL) vs ~192 t/s (Windows).**
The two are effectively **tied** — both drive the same RTX 5090 through the same Windows WDDM
driver, so WSL2's GPU-paravirtualization overhead is negligible. We standardize on Windows
for operational convenience, not speed.

- **Total: ~194,300 tokens** (~181,100 input + ~13,245 generated)
- **VRAM:** 28.6 / 32 GB, 100% GPU, no CPU offload (num_ctx 65536)
- **Time:** ~28 s prefill + ~71 s generation ≈ ~99 s compute (~109 s wall)
- **Output:** `outputs/reports/summarize/2026-06-26.{json,md}` + `outputs/images/summarize/2026-06-26-usage.png`

Chunk 2 hit **51,772 input tokens** — this is why the enlarged `num_ctx` is required; Ollama's
default 32,768 context would silently truncate it.

---

## Translation on Windows

Bilingual content (`common.bilingual` / `common.translation` / `common.engine`) uses a local
inference engine. `create_engine()` prefers Ollama, then falls back by what's installed:

- **Ollama (default, when available):** if the local server has the HY-MT2 model pulled
  (`ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF`), `create_engine()` selects **`OllamaEngine`**,
  which translates over the same `/api/chat` server as summarize — **no extra process VRAM**,
  no PyTorch/llama-cpp needed. Model tag: `OLLAMA_TRANSLATION_MODEL` (default
  `hf.co/tencent/Hy-MT2-1.8B-GGUF`).
- **Fallback — in-process:** if Ollama lacks the model, `create_engine()` uses `llama-cpp-python`
  (`LlamaCppEngine`, GGUF) if installed, else vLLM (Linux) / transformers. Default model
  **`tencent/Hy-MT2-1.8B-GGUF`**, auto-downloaded from HuggingFace on first translate.

So translation, like summarize, runs fully local. To force a backend regardless of auto-detection,
set `GADGET_TRANSLATION_BACKEND` (`ollama`/`llamacpp`/`vllm`/`transformers`); override the model
with `OLLAMA_TRANSLATION_MODEL` (ollama) or `GADGET_TRANSLATION_MODEL` (in-process).

---

## Tuning knobs

- **`num_ctx`** (the `qwen3.6-sum` variant): 65536 uses ~28.6/32 GB. Raise for bigger chunks
  (costs KV-cache VRAM); drop toward 40960 if you OOM. `NUM_CTX=... bash scripts/serve_local_llm.sh`.
- **`OPENAI_REASONING_EFFORT=none`**: disables thinking — faster, but **measurably degrades
  summary quality**, so it is deliberately not the default and not emitted by
  `serve_local_llm.sh`. Only set it if you accept the quality trade-off. (`max_tokens` is 8192,
  so the think phase fits; if `content` comes back empty with `finish_reason: length`, raise it.)
- **Keep-alive**: Ollama unloads a model after 5 min idle. Translation/OCR requests now send
  `keep_alive` (default `30m`, override with `OLLAMA_KEEP_ALIVE`) per request; the chat model
  goes through the OpenAI-compat path which can't set it — for qwen residency across long
  pipelines, set `OLLAMA_KEEP_ALIVE=30m` in the Ollama *server's* environment.
  **`python -m summarize auto` frees ALL resident models (qwen included) when the pipeline
  completes** — set `GADGET_KEEP_OLLAMA=1` to keep them warm (e.g. back-to-back cron runs).
- **Translation concurrency**: `GADGET_TRANSLATION_CONCURRENCY` (default 4) — concurrent chunk
  requests batch inside Ollama for ~2.2× wall-clock; `1` restores sequential.
- **Translation context**: `OLLAMA_TRANSLATION_NUM_CTX` (default 8192) keeps HY-MT2 at ~3.6GB
  so it **co-resides** with the 24GB chat model (no more ~10s evict/reload per
  summarize↔translate switch). Chunkers cap zh chunks at 5000 chars to fit.
- **`chunk_text` max_chars** (150,000 in `common/llm.py`) ≈ ~40k tokens/chunk for these dev logs;
  stays under `num_ctx 65536` with headroom for the prompt + output.

---

## Why Ollama, not vLLM

vLLM 0.24.0 loaded the NVFP4 build fine but crashed in memory-profiling: the NVFP4 W4A4 path
JIT-compiles a CUTLASS FP4 SM_120 kernel via flashinfer, which needs `nvcc` + version-matched
CUDA headers. The pip `cuda-toolkit` metapackage installed **nvcc 13.2 against CUDA-13.0
headers** → CCCL "compiler and toolkit headers are incompatible", and no real
`nvidia-cuda-nvcc-cu13==13.0` wheel exists on PyPI to realign it. Ollama sidesteps all of this
by shipping prebuilt CUDA kernels. vLLM's advantage (continuous batching for many concurrent
users) is irrelevant for summarize's single-user batch workload; the ~10% single-stream speed
tax is negligible here. To switch to vLLM later, nothing in summarize changes — it's the same
OpenAI `/v1` endpoint and env vars.

---

## WSL fallback / revert

WSL2 performs identically (table above) — keep it as a fallback. To stand it back up after the
WSL-side cleanup (`scripts/wsl_local_llm_cleanup.sh`; WSL-only — it refuses to run outside WSL),
do the following **inside WSL**:

```bash
# 0. gadget + OpenAI SDK in a py3.10–3.12 env (the conda `AI` env, or make one)
conda activate AI && pip install -e /mnt/d/Github/gadget openai
# 1. install Ollama (needs sudo) + start the systemd service
curl -fsSL https://ollama.com/install.sh | sh
# 2. pull the model + create the variant
ollama pull qwen3.6:35b
bash /mnt/d/Github/gadget/scripts/serve_local_llm.sh
# 3. run (from tools/)
cd /mnt/d/Github/gadget/tools
eval "$(bash ../scripts/serve_local_llm.sh env)"
python -m summarize daily merge --date <DATE> --api ollama ../outputs/logs/summarize/<DATE>_*.json
```

The cleanup script leaves a one-line pointer at `~/.gadget-local-llm-revert` in WSL that
points back to this section.

---

## Troubleshooting / gotchas

- **`OPENAI_REASONING_EFFORT` unset ⇒ empty output.** This is a thinking model; without
  `=none` it burns the whole token budget in `<think>` (`finish_reason: length`).
- **`daily merge` says "无 log 文件可合并"** — pass log file paths explicitly or use `--sync`/
  `--sync-all`; `--date` alone does not glob the logs dir.
- **Check GPU vs CPU split:** `ollama ps` (PROCESSOR column) — should read `100% GPU`.
- **Live token timing (Windows):** `%LOCALAPPDATA%\Ollama\server.log` (prompt eval = prefill,
  eval = generation). WSL: `journalctl -u ollama -f | grep "eval time"`.
- **Reports auto-upload:** if the summarize config (repo-local `tools/summarize/config.json`,
  else `~/.config/summarize/config.json`) has `rclone_remote`, `merge` uploads the report to
  that remote as a side effect.
- **WSL-only:** don't launch `ollama serve` with `nohup … &` and let the shell return — WSL
  shuts the distro down when idle, killing detached processes. Use the systemd `ollama`
  service. `/tmp` is tmpfs (wiped on restart) — write logs under `~/` (ext4).
