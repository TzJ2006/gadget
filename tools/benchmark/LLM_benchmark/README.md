# LLM language-ability benchmark

Runs local Ollama models and agent CLIs on a fixed prompt: a ~500 character Chinese story opening (`zhbench.py`), the English ~500 word counterpart (`enbench.py`), and a second round that reads the repo README and writes a tutorial (`docbench.py`). `gen_post.py` and `gen_doc_post.py` turn the JSON records into the report articles.

This is not the CPU/GPU FLOPS tool. That one is [../README.md](../README.md).

## Commands

From the repo root:

```bash
python tools/benchmark/LLM_benchmark/zhbench.py
python tools/benchmark/LLM_benchmark/enbench.py
python tools/benchmark/LLM_benchmark/docbench.py
python tools/benchmark/LLM_benchmark/gen_post.py
python tools/benchmark/LLM_benchmark/gen_doc_post.py
```

The same scripts work from this directory (`python zhbench.py`, and the same for the other four). Runners take `--only <model-substring>`, `--skip-cli`, and `--skip-ollama`. They call live models.

## Results

JSON and markdown artifacts are written to `outputs/reports/` (`zhbench.json`, `enbench.json`, `docbench.json`, `chinese-writing-benchmark.md` / `.zh.md`, `readme-tutorial-benchmark.md` / `.zh.md`). The repo root is resolved from this file's location, so a run started in `tools/benchmark/` still lands in that directory. `gen_post.py` and `gen_doc_post.py` also copy their articles into `tools/website/content/posts/`.
