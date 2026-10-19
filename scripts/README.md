# scripts/

Cross-tool operations. A new op that is not one tool's behavior goes here, with a test in `tests/` when the script is pure enough to test without a network or a model.

| Script | Role |
|---|---|
| `sync.py` | rclone push, pull, and status. `python scripts/sync.py`. Still copies `outputs/data/benchmark/results.csv`. The benchmark CLI appends to `tools/benchmark/benchmark_results.csv`; that CSV is not this sync path. |
| `onboard.py` | Machine setup from a YAML sheet. Template: `onboard.example.yaml`. |
| `smoke.sh` | Read-only start and parse check. `bash scripts/smoke.sh`. |
| `serve_local_llm.sh` | Print the Ollama env for summarize. `eval "$(bash scripts/serve_local_llm.sh env)"` prints env and returns. See [docs/guides/summarize-local-llm.md](../docs/guides/summarize-local-llm.md). |
| `language.py` | Hugo bilingual audit and summarize report rename. |
| `profile_translation.py` | Time the local translation engine. It loads a model; it is not part of smoke. |
| `wsl_local_llm_cleanup.sh` | Dry-run unless `--yes`. Run it inside WSL only. |
| `tests/` | pytest for the scripts that can run without a live service. |

Tool behavior stays in `tools/<name>/`. Shared library code stays in [`common/`](../common/README.md).
