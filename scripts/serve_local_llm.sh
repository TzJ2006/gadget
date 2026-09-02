#!/usr/bin/env bash
# Set up a local LLM for the summarize tool via Ollama (OpenAI-compatible API).
#
# Default target: single RTX 5090 (32 GB, Blackwell) on Windows-native Ollama, run from
# Git Bash. Also works verbatim in WSL. Runs the 4-bit GGUF build of Gemma4-26B
# (~18 GB) 100% on GPU. Ollama bundles its own CUDA (cuda_v13), so there's no
# CUDA-toolkit / nvcc / kernel-JIT setup — unlike vLLM on this GPU.
#
# Prereq (one-time):
#   Windows: install Ollama from https://ollama.com/download (runs as a tray service)
#   WSL:     curl -fsSL https://ollama.com/install.sh | sh   # systemd service, needs sudo
#
# This script pulls the model, checks the context window, and prints the env to use.
#
# Then point summarize at it (Windows base conda, or WSL AI conda env — same host):
#   eval "$(bash scripts/serve_local_llm.sh env)"
#   python -m summarize daily merge --date <DATE> --api ollama --no-cache
#
# The `ollama` backend defaults to 127.0.0.1:11434/v1 and is keyless, so the env
# below only needs the model name. (Legacy: `--api openai` still works if you
# also export OPENAI_BASE_URL/OPENAI_API_KEY.)
#
# For a PERSISTENT setup, skip the `eval` entirely: put these in the repo-root
# config.json `summarize` section (`default_api`, `model`, `reasoning_effort`,
# ...), or point GADGET_CONFIG at another JSON file, so `python -m summarize auto`
# just works. See tools/summarize/CLAUDE.md.
#
# ponytail: this used to `ollama create` a num_ctx-65536 variant ("<model>-sum"),
# because summarize chunks reach ~52k tokens and old Ollama defaulted to 32768.
# Ollama 0.33 auto-sizes the context window (measured: the bare gemma4:26b tag
# loads at 65536), so the variant, its Modelfile, and the base-vs-variant name
# split are all gone. The context check below is what replaces it — it FAILS the
# setup rather than letting summarize silently truncate a chunk. If a future
# Ollama auto-sizes lower, set OLLAMA_CONTEXT_LENGTH in the SERVER's environment;
# there is no per-request fix, because Ollama's OpenAI-compat /v1 endpoint (the
# path the chat backend uses) ignores options.num_ctx — verified 2026-09-02.
#
# OPENAI_REASONING_EFFORT=none is deliberately NOT emitted: it is faster but
# measurably degrades summary quality. For model residency across pipeline
# stages, set OLLAMA_KEEP_ALIVE=30m in the Ollama SERVER's environment
# (tray-service env on Windows / systemd override in WSL) — client env can't
# change it for the chat model.
set -euo pipefail

MODEL="${MODEL:-gemma4:26b}"
MIN_CTX="${MIN_CTX:-65536}"
PORT="${PORT:-11434}"
# Translation model for common/engine.py's OllamaEngine
# (GADGET_TRANSLATION_BACKEND=ollama). Defaults to the chat model: one runner, no
# second copy of the weights on the GPU. Point it at
# hf.co/tencent/Hy-MT2-1.8B-GGUF to go back to the dedicated MT model.
TRANSLATE_MODEL="${TRANSLATE_MODEL:-${MODEL}}"

if [ "${1:-setup}" = "env" ]; then
  # Print export lines for the `ollama` chat backend (see call_ollama in
  # common/llm.py). Base URL + key are defaulted (localhost, keyless), so only the
  # model name and the reasoning knob are needed.
  echo "export OLLAMA_MODEL=${MODEL}"
  # Route translation (common/engine.py) through the same Ollama server.
  echo "export GADGET_TRANSLATION_BACKEND=ollama"
  echo "export OLLAMA_TRANSLATION_MODEL=${TRANSLATE_MODEL}"
  # Optional overrides / legacy `--api openai` compatibility:
  if [ "${PORT}" != "11434" ]; then
    # 127.0.0.1, not localhost — Windows resolves localhost IPv6-first and
    # stalls ~2s per request (see common/llm.py OLLAMA_DEFAULT_BASE_URL).
    echo "export OLLAMA_BASE_URL=http://127.0.0.1:${PORT}/v1"
  fi
  exit 0
fi

command -v ollama >/dev/null || { echo "ollama not installed — run the install line above"; exit 1; }
curl -sf "http://127.0.0.1:${PORT}/api/version" >/dev/null || { echo "ollama server not responding on :${PORT} (start the Ollama tray app on Windows, or 'systemctl start ollama' in WSL)"; exit 1; }

ollama pull "$MODEL"
if [ "$TRANSLATE_MODEL" != "$MODEL" ]; then
  ollama pull "$TRANSLATE_MODEL" || echo "warn: could not pull ${TRANSLATE_MODEL} — translation backend will fall back to in-process GGUF"
fi

# Load the model and read back the context window Ollama actually chose. A silent
# undersize is the failure this whole setup step exists to prevent: summarize
# would truncate a chunk mid-merge and still produce a plausible-looking report.
curl -sf "http://127.0.0.1:${PORT}/api/generate" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
  >/dev/null
CTX="$(curl -sf "http://127.0.0.1:${PORT}/api/ps" \
  | python -c "import json,sys; print(next((m.get('context_length') or 0 for m in json.load(sys.stdin)['models'] if m['model'].split(':')[0]=='${MODEL%%:*}'), 0))")"

if [ "$CTX" -lt "$MIN_CTX" ]; then
  echo "ERROR: ${MODEL} loaded with context_length=${CTX}, below the ${MIN_CTX} summarize needs."
  echo "  Ollama's /v1 endpoint ignores per-request num_ctx, so fix it on the SERVER:"
  echo "    set OLLAMA_CONTEXT_LENGTH=${MIN_CTX} in the Ollama service environment and restart it"
  echo "  (Windows: tray app env / system env vars. WSL: systemctl edit ollama.)"
  exit 1
fi

echo "${MODEL} ready (context_length=${CTX}); translating with ${TRANSLATE_MODEL}. Run 'bash $0 env' for the env vars."
