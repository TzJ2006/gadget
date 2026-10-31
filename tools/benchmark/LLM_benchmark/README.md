# LLM language-ability benchmark

Runs local Ollama models and agent CLIs on a fixed prompt: a ~500 character Chinese story opening (`zhbench.py`), the English ~500 word counterpart (`enbench.py`), and a second round that reads the repo README and writes a tutorial (`docbench.py`). `gen_post.py` and `gen_doc_post.py` turn the JSON records into the report articles.

This is not the CPU/GPU FLOPS tool. That one is [../README.md](../README.md).

## Commands

From the repo root:

```bash
python tools/benchmark/LLM_benchmark/run.py
python tools/benchmark/LLM_benchmark/zhbench.py
python tools/benchmark/LLM_benchmark/enbench.py
python tools/benchmark/LLM_benchmark/docbench.py
python tools/benchmark/LLM_benchmark/gen_post.py
python tools/benchmark/LLM_benchmark/gen_doc_post.py
```

The same scripts work from this directory (`python zhbench.py`, and the same for the other four). `python run.py` runs whichever of `zh`, `en`, and `doc` are listed in the config, in that order. After those suites have been attempted it builds the articles from the JSON already on disk: `gen_post.py` when both `zhbench.json` and `enbench.json` are present, `gen_doc_post.py` when `docbench.json` is present. A missing file skips that generator. It then publishes the Hugo site through the same step as `tools/website/update.ps1` and `update.sh` (`publish.py`). A suite that exits with an error leaves the JSON already saved on disk and does not stop the other suites or the article step.

## Config

Copy `config.example.json` to `config.json` in this directory. `config.json` is gitignored. If it is missing, the runners read the example. This file is separate from the repo-root `config.json`.

The roster is that file's `models` object (`codex`, `claude`, `cursor`, `ollama`), not a list copied into the three runners. `bench_config.py` loads it.

- `suites`: `zh` (`zhbench.py`, about 500 Chinese characters), `en` (`enbench.py`, about 500 English words), `doc` (`docbench.py`, README to a tutorial). A script left out of the list exits without writing results.
- `models`: CLI entries are `key` plus `model`, and `effort` for a Claude model. `enabled` defaults to true; set it to false to keep an id in the file without running it. Ollama entries are model-name strings.
- `output_dir`: where the JSON results go. `outputs/reports` is relative to the repo root, resolved from the script file, not from the shell's current directory. The filenames stay `zhbench.json`, `enbench.json`, and `docbench.json`.
- `only`, `skip_cli`, `skip_ollama`: the same switches as the CLI. A flag overrides the file: `--only`, `--skip-cli`, `--skip-ollama`, `--no-skip-cli`, `--no-skip-ollama`.
- `publish`: defaults to true. `run.py` writes the markdown posts either way. Set it to false, or pass `--no-publish`, to skip the live push. `--publish` turns the push back on.

Each run loads the existing JSON, skips models that already succeeded, and writes that list back plus whatever it actually ran. A key already stored in `outputs/reports/*.json` stays there when that model is absent from `models`.

## Results

JSON and markdown artifacts are written to `outputs/reports/` (`zhbench.json`, `enbench.json`, `docbench.json`, `chinese-writing-benchmark.md` / `.zh.md`, `readme-tutorial-benchmark.md` / `.zh.md`). The repo root is resolved from this file's location, so a run started in `tools/benchmark/` still lands in that directory. `gen_post.py` and `gen_doc_post.py` also copy their articles into `tools/website/content/posts/`.
