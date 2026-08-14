# tools/translator — Gradio Document Translator

Local Gradio GUI over `common.engine` (HY-MT) for pasted text and dropped files (`.md` / `.txt` / `.pdf` / `.docx` / images). Logic lives in `core.py` (ingest + OCR + markdown-preserving translation); the UI is `app.py`. OCR defaults to a local Ollama vision model; PDFs are rendered page-by-page then OCR'd. Translation is local inference only — no cloud LLM APIs.

## Commands

```bash
pip install -e ".[translator]"                         # from repo root: gradio + pymupdf + llama-cpp
python -m translator                                   # Gradio GUI (blocks until closed)
cd tools && python -m pytest translator/tests          # unit tests (pure mock; no network/GPU/models)
python -m pytest tools/translator/tests/test_core.py   # same suite from repo root
```

## Quirks

- Never run `python -m translator` in a foreground agent/CI shell — Gradio `launch()` blocks until the UI is closed.
- Default OCR backend is Ollama (`TRANSLATOR_OCR_BACKEND=ollama`). PDF OCR on that path needs PyMuPDF (`import fitz`); missing it raises `RuntimeError` pointing at `pip install pymupdf` or `TRANSLATOR_OCR_BACKEND=marker`. `pymupdf` is in the `translator` extra; the unit suite mocks `fitz` and never imports it.
- Marker fallback shells into the `deepseek-ocr` conda env (`TRANSLATOR_MARKER_ENV`); `conda` must be on PATH.
- Ollama URLs use `127.0.0.1`, never `localhost` (Windows IPv6 stall) — same host helper as `common.engine`.
- `translator.core.translate_file` is document ingest (file → markdown → translate). Website `translate_content.translate_file` is Hugo bilingual publish. They are different; do not merge into `common/`.
- `tests/_e2e_real.py` is a manual live-model check, not part of the unit suite.
