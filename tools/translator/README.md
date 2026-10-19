# tools/translator

Local document translator: a Gradio UI, an OCR CLI, and a text-entry CLI. Deep guide: [AGENTS.md](AGENTS.md).

Engines live in [`common/engine/`](../../common/engine/). Markdown translation lives in [`common/translation/`](../../common/translation/).

## Entry points

```bash
pip install -e ".[translator]"   # from the repo root
python -m translator             # Gradio GUI; blocks until the window closes
python -m translator.ocr_cli <file>  # exactly one image, PDF, or docx
python -m translator.text_entry < json  # JSON object on stdin (model, base_url, and text or source_path)
```

## Important files

- `app.py` — Gradio UI
- `core.py` — file ingest and translation
- `ocr_cli.py`, `ocr_impl.py` — OCR CLI and implementation
- `text_entry/` — `python -m translator.text_entry`
- `models.py` — model list stored in repo-root `config.json`
- `perf_report.md` — a hardware timing note, not the usage guide

## Where new files go

UI changes go in `app.py`. Ingest and translation behavior go in `core.py`. OCR goes in `ocr_impl.py`, with the CLI in `ocr_cli.py`. Text-entry commands stay under `text_entry/`. Tests go in `tests/`.
