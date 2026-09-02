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
#   then:    ollama pull gemma4:26b                            # ~18 GB 4-bit
#
# This script creates a summarize-tuned variant and prints the env to use.
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
# ponytail: the knob that matters is NUM_CTX (bigger fits summarize's ~40k-token
# chunks but costs KV-cache VRAM; 65536 measured 17/32 GB 100% GPU on the previous
# 27B model, leaving ~15 GB of headroom. Not re-measured on gemma4:26b — drop toward
# 40960 if you OOM.
# OPENAI_REASONING_EFFORT=none is deliberately NOT emitted:
# it is faster but measurably degrades summary quality. For model residency
# across pipeline stages, set OLLAMA_KEEP_ALIVE=30m in the Ollama SERVER's
# environment (tray-service env on Windows / systemd override in WSL) — client
# env can't change it for the chat model.
set -euo pipefail

BASE_MODEL="${BASE_MODEL:-gemma4:26b}"
VARIANT="${VARIANT:-gemma4-sum}"
NUM_CTX="${NUM_CTX:-65536}"
PORT="${PORT:-11434}"
# Translation model for common/engine.py's OllamaEngine
# (GADGET_TRANSLATION_BACKEND=ollama). Defaults to the same variant the chat side
# serves: one runner, no second copy of the weights on the GPU. Point it at
# hf.co/tencent/Hy-MT2-1.8B-GGUF to go back to the dedicated MT model.
TRANSLATE_MODEL="${TRANSLATE_MODEL:-${VARIANT}}"

if [ "${1:-setup}" = "env" ]; then
  # Print export lines for the `ollama` chat backend (see call_ollama in
  # common/llm.py). Base URL + key are defaulted (localhost, keyless), so only the
  # model name and the reasoning knob are needed.
  echo "export OLLAMA_MODEL=${VARIANT}"
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

# Create/refresh the summarize variant with a larger context window.
# ponytail: a real temp file, not `-f -` — ollama 0.32 dropped stdin Modelfiles
# ("no Modelfile or safetensors files found"). cygpath because ollama.exe under
# Git Bash can't resolve a POSIX /tmp path.
MODELFILE="$(mktemp)"
trap 'rm -f "$MODELFILE"' EXIT
printf 'FROM %s\nPARAMETER num_ctx %s\n' "$BASE_MODEL" "$NUM_CTX" > "$MODELFILE"
MODELFILE_ARG="$MODELFILE"
command -v cygpath >/dev/null 2>&1 && MODELFILE_ARG="$(cygpath -w "$MODELFILE")"
ollama create "$VARIANT" -f "$MODELFILE_ARG"
# Pull the translation model so the ollama translation backend works — skipped when
# it IS the variant we just created locally (nothing to pull, and `pull` would fail).
if [ "$TRANSLATE_MODEL" != "$VARIANT" ]; then
  ollama pull "$TRANSLATE_MODEL" || echo "warn: could not pull ${TRANSLATE_MODEL} — translation backend will fall back to in-process GGUF"
fi
echo "Created ${VARIANT} (num_ctx=${NUM_CTX}); translating with ${TRANSLATE_MODEL}. Run 'bash $0 env' for the env vars."
