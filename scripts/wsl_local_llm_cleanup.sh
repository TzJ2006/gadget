#!/usr/bin/env bash
# Reclaim WSL disk after moving the local-LLM stack to Windows-native Ollama.
#
# Removes the heavy artifacts we created while experimenting in WSL (Ollama model
# store + service, vLLM venv, downloaded FP4 / GGUF HuggingFace models, the vLLM +
# cuda-toolkit pip packages in the `AI` conda env) and leaves a one-line revert
# pointer at ~/.gadget-local-llm-revert.
#
# Run this INSIDE WSL (it needs sudo for the Ollama service/store):
#   bash /mnt/d/Github/gadget/scripts/wsl_local_llm_cleanup.sh          # DRY RUN — just shows sizes
#   bash /mnt/d/Github/gadget/scripts/wsl_local_llm_cleanup.sh --yes    # actually delete
#
# It does NOT unregister the distro or delete the `AI` conda env — that's your
# "minimal revert path". To go back to serving on WSL, follow docs/guides/summarize-local-llm.md
# ("WSL fallback / revert"). To also drop the whole AI env, see the commented line below.
#
# ponytail: dry-run default because this box's WSL was frozen when the script was
# written, so its exact contents couldn't be verified first. Look, then --yes.
set -uo pipefail

# Hard guard: outside WSL, ~ is the WINDOWS home — deleting ~/.ollama there would
# nuke the production Windows-native Ollama model store this migration moved TO.
grep -qi microsoft /proc/version 2>/dev/null || {
  echo "ERROR: run this inside WSL. Outside WSL it would delete your Windows ~/.ollama store."
  exit 1
}

CONFIRM=0
[ "${1:-}" = "--yes" ] && CONFIRM=1
AI_ENV="${AI_ENV:-AI}"

if [ "$CONFIRM" = 0 ]; then
  echo "=== DRY RUN — showing what WOULD be removed. Re-run with --yes to delete. ==="
else
  echo "=== DELETING (--yes) ==="
fi
echo

# rm a path with a size readout; honors CONFIRM. Uses sudo when $2 = sudo.
zap() {
  local path="$1" use_sudo="${2:-}"
  local du=(du -sh) rm=(rm -rf)
  [ "$use_sudo" = sudo ] && { du=(sudo du -sh); rm=(sudo rm -rf); }
  if [ -e "$path" ]; then
    printf '  %-8s %s\n' "$("${du[@]}" "$path" 2>/dev/null | cut -f1)" "$path"
    [ "$CONFIRM" = 1 ] && "${rm[@]}" "$path" && echo "    removed."
  else
    printf '  %-8s %s (absent)\n' "-" "$path"
  fi
}

echo "[1] Ollama (WSL) — service + model store + binary"
if command -v ollama >/dev/null 2>&1; then
  if [ "$CONFIRM" = 1 ]; then
    sudo systemctl disable --now ollama 2>/dev/null && echo "  ollama service stopped + disabled"
  else
    echo "  would: sudo systemctl disable --now ollama"
  fi
fi
zap /usr/share/ollama/.ollama sudo      # ~23 GB model blobs
zap ~/.ollama                           # per-user models, if any
if [ "$CONFIRM" = 1 ]; then
  sudo rm -f /usr/local/bin/ollama /usr/bin/ollama 2>/dev/null && echo "  ollama binary removed"
  sudo userdel ollama 2>/dev/null && echo "  ollama service user removed"
else
  echo "  would: sudo rm -f /usr/local/bin/ollama ; sudo userdel ollama"
fi
echo

echo "[2] vLLM leftovers"
zap ~/vllm-venv
zap ~/ollama            # the tarball extract dir from an earlier manual install attempt
for f in ~/vllm*.log ~/ollama*.log ~/serve*.log; do zap "$f"; done
echo

echo "[3] HuggingFace model cache (our downloads only — other models are left alone)"
HUB=~/.cache/huggingface/hub
if [ -d "$HUB" ]; then
  # size readout only — deleting $HUB here would wipe models the KEPT list promises to keep
  printf '  %-8s %s (total size, NOT deleted)\n' "$(du -sh "$HUB" 2>/dev/null | cut -f1)" "$HUB"
  echo "  matching our models (Qwen / FP4 / tencent-HY):"
  shopt -s nullglob
  for d in "$HUB"/models--*Qwen* "$HUB"/models--*FP4* "$HUB"/models--tencent--* "$HUB"/models--*HY-MT* "$HUB"/models--*Hy-MT*; do
    zap "$d"
  done
  echo "  --- everything else in the hub (KEPT) ---"
  for d in "$HUB"/models--*; do
    case "$d" in *Qwen*|*FP4*|*tencent*|*HY-MT*|*Hy-MT*) : ;; *) echo "    KEEP $d" ;; esac
  done
else
  echo "  no HF hub cache."
fi
echo

echo "[4] vLLM + cuda-toolkit pip packages in conda env '$AI_ENV' (env itself is KEPT)"
if command -v conda >/dev/null 2>&1 && conda env list 2>/dev/null | grep -qE "(^|/)$AI_ENV[[:space:]]"; then
  if [ "$CONFIRM" = 1 ]; then
    conda run -n "$AI_ENV" pip uninstall -y vllm cuda-toolkit nvidia-cuda-nvcc-cu13 flashinfer-python 2>/dev/null | tail -1
    echo "  uninstalled vllm/cuda-toolkit/flashinfer from $AI_ENV"
  else
    echo "  would: conda run -n $AI_ENV pip uninstall -y vllm cuda-toolkit nvidia-cuda-nvcc-cu13 flashinfer-python"
  fi
  # To drop the whole env instead (only if it was created solely for this):
  #   conda env remove -n "$AI_ENV"
else
  echo "  conda env '$AI_ENV' not found — skipping."
fi
echo

echo "[5] Leave revert pointer at ~/.gadget-local-llm-revert"
if [ "$CONFIRM" = 1 ]; then
  printf 'Local-LLM serving moved to Windows-native Ollama on %s.\nTo revert to WSL: see /mnt/d/Github/gadget/docs/guides/summarize-local-llm.md ("WSL fallback / revert")\nand run /mnt/d/Github/gadget/scripts/serve_local_llm.sh.\n' "$(hostname)" > ~/.gadget-local-llm-revert
  echo "  wrote ~/.gadget-local-llm-revert"
else
  echo "  would write ~/.gadget-local-llm-revert (revert instructions)"
fi
echo

if [ "$CONFIRM" = 1 ]; then
  echo "Done. To shrink the WSL virtual disk on Windows afterwards (from an admin PowerShell):"
  echo "  wsl --shutdown ; then Optimize-VHD or 'diskpart' compact on the ext4.vhdx"
else
  echo "DRY RUN complete. Re-run with --yes to delete. Nothing was changed."
fi
