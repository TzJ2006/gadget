"""Translation logic for the GUI — text + file → translated markdown.

Almost everything is reuse:
  * the HY-MT GGUF engine via ``common.engine.create_engine`` (load once, stay warm)
  * markdown-preserving translation via ``common.translation.translate_body``
    (it protects code blocks / URLs / shortcodes, chunks, batches, restores)
  * auto source-language detection via ``common.translation.detect_language``

Only the file-ingestion glue is new. Rich files (.pdf / .docx / images) are
converted to markdown by the ``marker-pdf`` CLI that lives in the ``deepseek-ocr``
conda env — invoked as a subprocess so its torch/surya stack stays out of this
env (see docs/ecl/translator-gui.yaml, DEC-003b).
"""

from __future__ import annotations

import logging
import os
import subprocess
import zipfile
from pathlib import Path

from common.engine import TranslationEngine, create_engine
from common.translation import (
    chunk_ceiling,
    detect_language,
    protect_fragments,
    split_large_text,
    translate_body,
)

try:
    from common.engine import free_ollama_vram, ollama_native_host
except ImportError:
    from common.engine import (
        _free_ollama_vram as free_ollama_vram,
        _ollama_native_host as ollama_native_host,
    )

logger = logging.getLogger(__name__)

TEXT_EXTS = {".txt", ".md", ".markdown"}

# Micro-chunk multi-paragraph input into a batch — the GPU is launch-bound at
# batch=1, so batching is the only real speedup (see perf_report.md). ~1000 chars
# balances batch size against per-chunk context loss. Override if quality drifts.
MICRO_CHUNK_CHARS = int(os.environ.get("TRANSLATOR_MICRO_CHUNK_CHARS", "1000"))

# Inject the document (capped to this many chars) as background into each chunk's
# prompt so micro-chunked translations keep terminology/referents consistent.
# Only fires when there is >1 chunk; 0 disables. Env-overridable.
TRANSLATOR_CONTEXT_CHARS = int(os.environ.get("TRANSLATOR_CONTEXT_CHARS", "3000"))

# ponytail: conda env name is a hardcode with an env-var escape hatch — override
# TRANSLATOR_MARKER_ENV if marker lives in a differently-named env.
MARKER_ENV = os.environ.get("TRANSLATOR_MARKER_ENV", "deepseek-ocr")
MARKER_TIMEOUT = int(os.environ.get("TRANSLATOR_MARKER_TIMEOUT", "600"))

# OCR backend for images and PDFs: "ollama" (default — baidu/Unlimited-OCR GGUF
# served by the local Ollama; pull with `ollama pull hf.co/sahilchachra/Unlimited-OCR-GGUF`)
# or "marker" (subprocess into the deepseek-ocr conda env). PDFs are rendered
# page-by-page to PNG via PyMuPDF before OCR on the ollama path.
OCR_BACKEND = os.environ.get("TRANSLATOR_OCR_BACKEND", "ollama")
OLLAMA_OCR_MODEL = os.environ.get(
    "TRANSLATOR_OCR_MODEL", "hf.co/sahilchachra/Unlimited-OCR-GGUF")
# "document parsing." is the model card's recommended task prompt; other phrasings
# (e.g. "convert to markdown") return EMPTY output from the GGUF quant.
OLLAMA_OCR_PROMPT = os.environ.get("TRANSLATOR_OCR_PROMPT", "document parsing.")
# temperature 0 (greedy) makes the GGUF quant emit EOS immediately on a fresh
# load (eval_count=1, empty output); 0.6 is reliable. Empty results are retried.
OLLAMA_OCR_TEMPERATURE = float(os.environ.get("TRANSLATOR_OCR_TEMPERATURE", "0.6"))
OLLAMA_OCR_TIMEOUT = int(os.environ.get("TRANSLATOR_OCR_TIMEOUT", "300"))
# 8192 keeps the OCR model at ~5.7GB resident instead of 13.3GB at the 32768
# default (measured, output identical — test/performance/results/ocr_ctx_sizes.json);
# a page is ~278 vision tokens + ~1k output, so 8192 has ample headroom.
OLLAMA_OCR_NUM_CTX = int(os.environ.get("TRANSLATOR_OCR_NUM_CTX", "8192"))
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

def get_engine(model: str | None = None) -> TranslationEngine:
    """Return a warm engine for *model* (default model when None).

    ``create_engine`` caches one engine per model id and loads it before
    returning, so switching models in the GUI loads each lazily and keeps every
    loaded model warm for reuse.
    """
    return create_engine(model)


def resolve_langs(text: str, src_choice: str, tgt_choice: str) -> tuple[str, str]:
    """Resolve ('auto'|'zh'|'en', 'auto'|'zh'|'en') into a concrete (src, tgt).

    'auto' source is detected from the text; 'auto' target flips zh↔en.
    """
    src = detect_language(text) if src_choice == "auto" else src_choice
    if tgt_choice == "auto":
        tgt = "en" if src == "zh" else "zh"
    else:
        tgt = tgt_choice
    return src, tgt


def count_tokens(engine: TranslationEngine, text: str) -> int:
    """Best-effort output token count by reusing the engine's own tokenizer.

    transformers / vLLM expose ``_tokenizer``; llama-cpp exposes ``_llm.tokenize``.
    Falls back to a ~4-chars/token estimate when neither is reachable.
    """
    if not text:
        return 0
    tok = getattr(engine, "_tokenizer", None)
    if tok is not None:
        try:
            return len(tok.encode(text))
        except (TypeError, ValueError, AttributeError, UnicodeError, RuntimeError, OSError) as e:
            logger.debug("count_tokens: tokenizer.encode failed (%s); trying next fallback", e)
    llm = getattr(engine, "_llm", None)
    if llm is not None and hasattr(llm, "tokenize"):
        try:
            return len(llm.tokenize(text.encode("utf-8")))
        except (TypeError, ValueError, AttributeError, UnicodeError, RuntimeError, OSError) as e:
            logger.debug("count_tokens: llama tokenize failed (%s); using char estimate", e)
    return max(1, len(text) // 4)  # ponytail: ~4 chars/token when no tokenizer is reachable


def count_chunks(text: str) -> int:
    """How many non-empty chunks ``translate_body`` will translate (= pbar steps)."""
    if not text or not text.strip():
        return 0
    protected, _ = protect_fragments(text)
    # Mirror translate_body's chunking exactly (incl. the zh-aware hard ceiling)
    # or the progress bar total drifts from the actual step count.
    chunks = split_large_text(
        protected, max_chars=chunk_ceiling(protected), target_chars=MICRO_CHUNK_CHARS)
    return sum(1 for c in chunks if c.strip())


def translate_text(text: str, target_lang: str, engine: TranslationEngine, pbar=None) -> str:
    """Translate a text/markdown string, preserving markdown. Empty → unchanged."""
    if not text or not text.strip():
        return text
    return translate_body(
        text, target_lang, engine, pbar=pbar,
        target_chars=MICRO_CHUNK_CHARS, context_chars=TRANSLATOR_CONTEXT_CHARS,
    )


from translator import ocr_impl as _ocr_impl


def run_marker(path: str, *, env: str = MARKER_ENV, timeout: int = MARKER_TIMEOUT) -> str:
    """Convert a rich file via marker_single. Same function as ``ocr_impl.run_marker``."""
    return _ocr_impl.run_marker(path, env=env, timeout=timeout)


def _ollama_pull(model: str) -> None:
    return _ocr_impl._ollama_pull(model)


def _junk(text: str) -> bool:
    return _ocr_impl._junk(text)


def _grounding_to_markdown(raw: str) -> str:
    return _ocr_impl._grounding_to_markdown(raw)


def ocr_via_ollama(path: str, *, model: str = OLLAMA_OCR_MODEL,
                   timeout: int = OLLAMA_OCR_TIMEOUT, _retry: bool = True) -> str:
    """Call the gadget-owned recognizer. This wrapper is not a second algorithm."""
    return _ocr_impl.ocr_via_ollama(path, model=model, timeout=timeout, _retry=_retry)


# ponytail: 150 DPI render — enough for body text OCR; raise if small print misreads.
PDF_RENDER_DPI = _ocr_impl.PDF_RENDER_DPI


def pdf_via_ollama(path: str, pbar=None) -> str:
    """OCR a PDF page-by-page. Same function as ``ocr_impl.pdf_via_ollama``."""
    return _ocr_impl.pdf_via_ollama(path, pbar=pbar)


def docx_to_markdown(path: str) -> str:
    """Extract a .docx as markdown. Same function as ``ocr_impl.docx_to_markdown``."""
    return _ocr_impl.docx_to_markdown(path)


def _is_docx(path: str) -> bool:
    """A .docx is a zip containing word/document.xml — sniff content, don't trust
    the extension (gradio's temp upload path may not preserve it)."""
    try:
        with zipfile.ZipFile(path) as z:
            return "word/document.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def file_to_markdown(path: str, pbar=None) -> str:
    """Read text files directly; .docx via stdlib; images and PDFs via the
    configured OCR backend (ollama default, marker fallback). *pbar* (optional,
    tqdm-ish) gets per-page progress on the ollama PDF path only."""
    suffix = Path(path).suffix.lower()
    if suffix in TEXT_EXTS:
        return Path(path).read_text(encoding="utf-8")
    if _is_docx(path):
        return docx_to_markdown(path)
    if OCR_BACKEND == "ollama":
        if suffix in IMAGE_EXTS:
            return ocr_via_ollama(path)
        if suffix == ".pdf":
            return pdf_via_ollama(path, pbar=pbar)
    return run_marker(path)


def translate_file(
    path: str, src_choice: str, tgt_choice: str, engine: TranslationEngine, pbar=None
) -> tuple[str, str, str]:
    """file → markdown → translated markdown.

    Converts once, then resolves languages from the converted content (so 'auto'
    works for rich files too). Returns (translated_text, suggested_filename,
    "src->tgt").
    """
    md = file_to_markdown(path)
    src, tgt = resolve_langs(md, src_choice, tgt_choice)
    if pbar is not None and hasattr(pbar, "total"):
        pbar.total = max(count_chunks(md), 1)  # chunk count only known after conversion
    translated = translate_text(md, tgt, engine, pbar=pbar)
    return translated, f"{Path(path).stem}.{tgt}.md", f"{src}->{tgt}"
