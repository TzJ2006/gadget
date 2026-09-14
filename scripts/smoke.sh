#!/usr/bin/env bash
# scripts/smoke.sh — Phase 0 safe smoke test for gadget.
#
# READ-ONLY ONLY: --help / --info / config-show / import checks. No LLM calls,
# no model loads, no writes, no deploy, no network sync. Verifies "does each
# tool start and parse" — NOT that output is correct.
#
# Exit: non-zero if any check FAILS. Missing optional deps SKIP (don't fail).
# ponytail: dep-missing is detected by grepping stderr for ModuleNotFoundError;
#           good enough for a smoke net. It did lie once: the pattern also had
#           a bare 'not found', which matched any message containing those
#           words — a missing file, a broken binary, a tool reporting "config
#           not found" — and reported the real breakage as SKIP, which nobody
#           goes on to read. Every check below invokes $PY with a module, so a
#           genuinely absent optional dependency always surfaces as
#           ModuleNotFoundError; anything else is a failure.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python}"
pass=0 skip=0 fail=0

# run <label> <workdir-rel-to-root> <cmd...>
run() {
  local label="$1" wd="$2"; shift 2
  local out rc
  out="$(cd "$ROOT/$wd" && "$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    printf 'PASS  %s\n' "$label"; pass=$((pass+1))
  elif printf '%s' "$out" | grep -qiE 'ModuleNotFoundError|No module named'; then
    local why; why="$(printf '%s' "$out" | grep -oiE "No module named '?[A-Za-z0-9_.]+'?" | head -1)"
    printf 'SKIP  %s  (%s)\n' "$label" "${why:-missing dep/binary}"; skip=$((skip+1))
  else
    printf 'FAIL  %s  (exit %s)\n' "$label" "$rc"; fail=$((fail+1))
    printf '%s\n' "$out" | tail -6 | sed 's/^/      | /'
  fi
}

echo "== gadget smoke test (read-only) =="
echo "root: $ROOT   python: $($PY --version 2>&1)"
echo

# common/ imports — no model load/network at import time
run "common: core imports"        "." $PY -c "import common.io, common.llm, common.engine, common.translation"
run "common: create_engine import" "." $PY -c "from common.engine import create_engine"

# summarize — help + read-only config-show
run "summarize: --help"           "tools" $PY -m summarize --help
run "summarize: daily config"     "tools" $PY -m summarize daily config
for sub in "daily export" "daily merge" "daily deploy" "weekly generate" "monthly generate" "auto"; do
  run "summarize: $sub -h"        "tools" $PY -m summarize $sub -h
done

# research — deprecation-shim CLI (writes a benign log file; that's all)
run "research: report --help"     "." $PY tools/research/research_scout.py report --help
run "research: profile --help"    "." $PY tools/research/research_scout.py profile --help
run "research: ask --help"        "." $PY tools/research/research_scout.py ask --help

# benchmark — --info prints hardware + returns before any CSV write (SKIPs if plotly absent)
run "benchmark: --info"           "tools/benchmark" $PY -m benchmark.cli --info

# translator — import only (no gradio/model load)
run "translator: core import"     "tools" $PY -c "import translator.core"

# website — preflight --help imports the module (needs PyYAML)
run "website: preflight --help"   "." $PY tools/website/preflight_check.py --help

# sync — --help parses the CLI (avoids network/rclone that `status` would need)
run "sync: --help"                "." $PY scripts/sync.py --help

# language — --help parses the merged hugo/reports CLI (no engine load)
run "language: --help"            "." $PY scripts/language.py --help

echo
printf '== %d passed, %d skipped, %d failed ==\n' "$pass" "$skip" "$fail"
[ "$fail" -eq 0 ]
