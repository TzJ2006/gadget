# Running summarize on a local LLM (Ollama, RTX 5090)

Recorded 2026-06-30. summarize (and any `common.llm` `openai`-backend caller) can run
against a **local Ollama server** instead of a cloud API — no `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`, everything on-GPU.

- **Default runtime: Windows-native Ollama.** WSL2 works identically (see the comparison
  below) but Windows is the standard because it's simpler to keep running (tray service,
  no distro idle-shutdown) and the summarize client runs natively in the same place.
- **Model:** `gemma4:26b` — Gemma4-26B, 4-bit GGUF (~18 GB), 256K declared context.
  Runs **100% on GPU**. summarize points straight at this tag: there is **no
  `-sum` variant any more** (Ollama 0.33 auto-sizes the context window — measured
  65536 for the bare tag, exactly what the old variant hardcoded).
  (Swapped in 2026-09-02, replacing `qwen3.8:27b` / `qwen3.8-sum`, which had itself
  replaced `qwen3.6:35b` — 35B-A3B MoE, ~23 GB. The benchmark table below was measured
  on that oldest model; the JSON-shape notes below were measured on qwen3.8. Neither
  has been re-run on gemma4.)
- **Host:** single RTX 5090 (32 GB, Blackwell SM_120).
- **Serving:** Ollama 0.31 — bundles its own CUDA (`cuda_v13`), so there is **no
  CUDA-toolkit / nvcc / kernel-JIT setup** (that's why we use Ollama and not vLLM here;
  see [Why Ollama, not vLLM](#why-ollama-not-vllm)).

Translation **also runs through Ollama by default**, and as of 2026-09-02 on the **same
model as chat** — `common.engine`'s `OllamaEngine` calls the same local server (native
`/api/chat`) with the served chat tag, so there is one model on the GPU instead of two.
It falls back to the in-process llama.cpp GGUF engine (dedicated MT model
`tencent/Hy-MT2-1.8B`) when Ollama is unreachable. Force a backend with `GADGET_TRANSLATION_BACKEND`
(`ollama`/`llamacpp`/`vllm`/`transformers`). See [Translation on Windows](#translation-on-windows).

---

## Windows-native setup (default)

Everything runs in **base conda** (py3.13) — it already has `openai` and the editable
`gadget` package, so **no separate `AI` env is needed on Windows.**

1. **Install Ollama for Windows** — download the installer from <https://ollama.com/download>.
   It installs a background service (tray icon) that auto-starts and listens on `:11434`.
   Verify: `ollama --version` and `curl http://localhost:11434/api/version`.
2. **Pull the model** (~18 GB): `ollama pull gemma4:26b`
3. **Check the context window** — from Git Bash:
   ```bash
   bash scripts/serve_local_llm.sh        # pulls, then fails if context < 65536
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
   > $env:OLLAMA_MODEL="gemma4:26b"; $env:OPENAI_REASONING_EFFORT="none"
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
| `OLLAMA_MODEL` | ollama | Served model id, e.g. `gemma4:26b`. Falls back to `OPENAI_MODEL`. |
| `OLLAMA_BASE_URL` | ollama | Endpoint override; defaults to `http://127.0.0.1:11434/v1`. Falls back to `OPENAI_BASE_URL`. |
| `OPENAI_BASE_URL` | openai | Endpoint for the `openai` backend (real OpenAI if unset). |
| `OPENAI_MODEL` | openai | Served model id (local servers don't use `gpt-4o`). |
| `OPENAI_API_KEY` | both | Real OpenAI needs it; ollama ignores it (keyless). |
| `OPENAI_REASONING_EFFORT` | both | Passed via `extra_body`. Set to `none` to disable a reasoning model's `<think>` phase. **Essential** — see gotchas. Unset ⇒ no effect. |

`tools/summarize/onboarding.py` preflight accepts `--api ollama` (keyless local) and
`OPENAI_BASE_URL` in place of a key for `--api openai`.

### Schema-constrained decoding (ollama only)

`call_ollama` sends the caller's existing Anthropic tool schema as
`response_format: {"type": "json_schema", ...}`, so Ollama constrains decoding to that
shape. `call_openai` deliberately stays on plain `json_object` (cloud `json_schema` is
strict-only and would reject these schemas, and the cloud models follow the prompt anyway).

This is not cosmetic. Under plain `json_object`, qwen3.8 answers the daily merge **one level
too deep** on roughly half of runs — `{"global": ..., "devices": ...}`, i.e. the contents of
the `daily_overview` field, as the whole report. Valid JSON, wrong level, and every other
section (tasks, problems, learnings) reads empty. Measured over 5 real merges: 2 correct,
3 truncated to the overview.

`_schema_from_tools` also promotes **every** top-level property to `required`. Constrained
decoding otherwise makes the model emit exactly the declared-required fields and stop —
on the daily schema (`required: [date, summary, tasks]`) that produced a 434-char stub.
All-required, same prompt:

| Mode | Output | Sections filled |
|------|-------:|----------------:|
| `json_object` (unconstrained) | 5,677 chars | 7 / 9 |
| `json_schema`, original `required` | 434 chars | 3 / 9 |
| `json_schema`, all-required | 5,093–6,460 chars | 8–9 / 9 |

Sections with nothing to report still come back, as `[]`.

The constraint helps a lot but is **not** a cure: on real merges qwen3.8 still escaped it on
1 of 3 clean runs (vs 3 of 5 unconstrained). Two backstops sit behind it in
`tools/summarize/summarizer.py`:

- `_finalize_report` retries the merge **once** when the answer has no report-shaped keys.
  Sampling is the only difference between a good and a bad answer, so a retry costs one merge
  call (~2 min, chunk summaries already computed) and only on runs that already failed.
- `_renest_overview` then re-nests a bare `daily_overview` payload and lifts `global.what` into
  `summary`, so a doubly-unlucky run — or any non-ollama backend — degrades to a working
  overview instead of a blank report. Tasks/problems/learnings are genuinely absent from such a
  response and cannot be recovered.

---

## Verified test result (2026-06-26 daily merge) + WSL vs Windows

> Measured on the **previous** model, `qwen3.6:35b` / `qwen3.6-sum` (~23 GB MoE). Kept as the
> WSL-vs-Windows host comparison, which is model-independent. Not re-run on `qwen3.8:27b`.

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

- **Ollama (default, when available):** `create_engine()` selects **`OllamaEngine`**, which
  translates over the same `/api/chat` server as summarize, using the **same served chat
  model** — **no extra process VRAM**, nothing extra to pull, no PyTorch/llama-cpp needed.
  Model tag: `OLLAMA_TRANSLATION_MODEL` > `OLLAMA_MODEL` > `gemma4:26b`. Point
  `OLLAMA_TRANSLATION_MODEL` at `hf.co/tencent/Hy-MT2-1.8B-GGUF` to go back to the
  dedicated MT model (it is ~1.5 GB and co-resides cheaply).
- **Fallback — in-process:** if Ollama lacks the model, `create_engine()` uses `llama-cpp-python`
  (`LlamaCppEngine`, GGUF) if installed, else vLLM (Linux) / transformers. Default model
  **`tencent/Hy-MT2-1.8B-GGUF`**, auto-downloaded from HuggingFace on first translate.

So translation, like summarize, runs fully local. To force a backend regardless of auto-detection,
set `GADGET_TRANSLATION_BACKEND` (`ollama`/`llamacpp`/`vllm`/`transformers`); override the model
with `OLLAMA_TRANSLATION_MODEL` (ollama) or `GADGET_TRANSLATION_MODEL` (in-process).

---

## Tuning knobs

- **Context window**: no longer a repo-side knob. Ollama 0.33 auto-sizes it (measured
  65536 for the bare `gemma4:26b` tag — what the retired `-sum` variant hardcoded), and
  the **`/v1` OpenAI-compat endpoint the chat backend uses ignores per-request
  `options.num_ctx`** (verified 2026-09-02: sent 8192, runner stayed at 65536). So the
  only lever is the SERVER's `OLLAMA_CONTEXT_LENGTH`. `serve_local_llm.sh` reads the
  loaded `context_length` back from `/api/ps` and **fails** below `MIN_CTX` (65536)
  rather than letting summarize silently truncate a ~52k-token chunk. The translation
  path is different — it uses native `/api/chat`, where `OLLAMA_TRANSLATION_NUM_CTX`
  (default 8192) does apply per request.
  For reference, 65536 measured **17/32 GB, 100% GPU** on the previous `qwen3.8-sum`;
  not re-measured on gemma4.
- **`OPENAI_REASONING_EFFORT=none`**: disables thinking — faster, but **measurably degrades
  summary quality**, so it is deliberately not the default and not emitted by
  `serve_local_llm.sh`. On qwen3.8 with the constrained schema, same prompt: thinking on gave
  5,093–6,460 chars / 8–9 of 9 sections in 67–113 s; thinking off gave 2,376–2,526 chars /
  6 of 9 in 43–49 s. Roughly half the report for half the time. Only set it if you accept that
  trade-off — note the repo-root `config.json` template ships `"reasoning_effort": "none"`.
  (`max_tokens` is 8192, so the think phase fits; if `content` comes back empty with
  `finish_reason: length`, raise it.)
  The **frontmatter review** call (`common/translation/frontmatter.py`) is the one exception:
  it pins `none` internally, because it is a short structured-JSON edit where the think phase
  ate the whole 1024-token budget and returned empty — 19 s of nothing vs 0.2 s of valid JSON.
- **Keep-alive**: Ollama unloads a model after 5 min idle. Translation/OCR requests now send
  `keep_alive` (default `30m`, override with `OLLAMA_KEEP_ALIVE`) per request; the chat model
  goes through the OpenAI-compat path which can't set it — for qwen residency across long
  pipelines, set `OLLAMA_KEEP_ALIVE=30m` in the Ollama *server's* environment.
  **`python -m summarize auto` frees ALL resident models (qwen included) when the pipeline
  completes** — set `GADGET_KEEP_OLLAMA=1` to keep them warm (e.g. back-to-back cron runs).
- **Translation concurrency**: `GADGET_TRANSLATION_CONCURRENCY` (default 4) — concurrent chunk
  requests batch inside Ollama for ~2.2× wall-clock; `1` restores sequential.
- **Translation context**: `OLLAMA_TRANSLATION_NUM_CTX` (default 8192) keeps HY-MT2 at ~3.6GB
  so it **co-resides** with the chat model (no more ~10s evict/reload per
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
ollama pull gemma4:26b
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
- **Reports auto-upload:** if the summarize section of repo-root `config.json`
  (override with `GADGET_CONFIG`) has `rclone_remote`, `merge` uploads the report to
  that remote as a side effect.
- **WSL-only:** don't launch `ollama serve` with `nohup … &` and let the shell return — WSL
  shuts the distro down when idle, killing detached processes. Use the systemd `ollama`
  service. `/tmp` is tmpfs (wiped on restart) — write logs under `~/` (ext4).
