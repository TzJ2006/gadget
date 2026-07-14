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

import glob
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from common.engine import TranslationEngine, create_engine
from common.translation import (
    chunk_ceiling,
    detect_language,
    protect_fragments,
    split_large_text,
    translate_body,
)

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
        except Exception:  # noqa: BLE001 — tokenizer quirks must not break the UI
            pass
    llm = getattr(engine, "_llm", None)
    if llm is not None and hasattr(llm, "tokenize"):
        try:
            return len(llm.tokenize(text.encode("utf-8")))
        except Exception:  # noqa: BLE001
            pass
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


def run_marker(path: str, *, env: str = MARKER_ENV, timeout: int = MARKER_TIMEOUT) -> str:
    """Convert a rich file (pdf/docx/image) to markdown via the marker_single CLI.

    Runs in the ``deepseek-ocr`` conda env. Raises RuntimeError on non-zero exit,
    timeout, or when no markdown is produced.
    """
    name = os.path.basename(path)
    with tempfile.TemporaryDirectory() as out_dir:
        # List-form args (no shell) — survives spaces / non-ascii in the path.
        cmd = [
            "conda", "run", "-n", env, "marker_single", path,
            "--output_dir", out_dir, "--output_format", "markdown",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"marker timed out after {timeout}s converting {name}")
        except FileNotFoundError:
            # `conda` not on PATH (ATK-002) — give a clear, actionable message.
            raise RuntimeError(
                "could not run marker: `conda` not found on PATH "
                f"(needs the '{env}' env with marker-pdf installed)"
            )
        if proc.returncode != 0:
            raise RuntimeError(
                f"marker failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}"
            )
        md_files = glob.glob(os.path.join(out_dir, "**", "*.md"), recursive=True)
        if not md_files:
            raise RuntimeError(f"marker produced no markdown for {name}")
        text = Path(md_files[0]).read_text(encoding="utf-8")
        if not text.strip():
            # e.g. an image with no text — surface it instead of a silent ✅.
            raise RuntimeError(f"marker produced empty markdown for {name} (no text found?)")
        return text


OLLAMA_PULL_TIMEOUT = int(os.environ.get("TRANSLATOR_OCR_PULL_TIMEOUT", "3600"))


def _ollama_pull(model: str) -> None:
    """Pull *model* on the local Ollama server (blocking). RuntimeError on failure."""
    import json
    import urllib.error
    import urllib.request

    from common.engine import _ollama_native_host

    req = urllib.request.Request(
        _ollama_native_host() + "/api/pull",
        data=json.dumps({"model": model, "stream": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_PULL_TIMEOUT) as resp:
            status = json.loads(resp.read()).get("status", "")
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"ollama pull {model} failed: {e}")
    if status != "success":
        raise RuntimeError(f"ollama pull {model} failed: {status or 'unknown error'}")


# Unlimited-OCR emits grounding lines: `<label> [x1, y1, x2, y2]<content>`
# (labels seen: title, text, table, figure), sometimes preceded by preamble chatter.
_GROUNDING_LINE = __import__("re").compile(r"^\s*(\w+)?\s*\[[\d,\s]+\](.*)$")


def _grounding_to_markdown(raw: str) -> str:
    """Strip Unlimited-OCR grounding coordinates → plain markdown.

    Lines matching the grounding pattern keep their content (titles become `#`);
    other non-empty lines pass through as-is — the model sometimes emits the
    first block without coordinates, so we must not drop unmatched lines."""
    blocks: list[str] = []
    for line in raw.splitlines():
        m = _GROUNDING_LINE.match(line)
        def _junk(s: str) -> bool:
            # marker-only lines the model emits for figures/empty regions:
            # "[NO TEXT]", "[Non-Text]", ...
            return not s or (s.startswith("[") and s.endswith("]"))

        if m:
            label, content = (m.group(1) or "").lower(), m.group(2).strip()
            if not _junk(content):
                blocks.append(f"# {content}" if label == "title" else content)
        elif not _junk(line.strip()):
            blocks.append(line.strip())
    return "\n\n".join(blocks)


def ocr_via_ollama(path: str, *, model: str = OLLAMA_OCR_MODEL,
                   timeout: int = OLLAMA_OCR_TIMEOUT, _retry: bool = True) -> str:
    """OCR an image to markdown via a vision model on the local Ollama server.

    Uses the native /api/generate endpoint with a base64 image (stdlib urllib,
    same host resolution as the translation OllamaEngine). Raises RuntimeError
    with an actionable message on any failure.
    """
    import base64
    import json
    import urllib.error
    import urllib.request

    from common.engine import _ollama_native_host

    name = os.path.basename(path)
    payload = {
        "model": model,
        "prompt": OLLAMA_OCR_PROMPT,
        "images": [base64.b64encode(Path(path).read_bytes()).decode("ascii")],
        "stream": False,
        "options": {"temperature": OLLAMA_OCR_TEMPERATURE,
                    "num_ctx": OLLAMA_OCR_NUM_CTX},
        # stay resident between pages/documents instead of the 5-minute default
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "30m"),
    }
    text = ""
    for attempt in range(3):  # the quant occasionally emits immediate EOS → retry
        req = urllib.request.Request(
            _ollama_native_host() + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = (json.loads(resp.read()).get("response") or "").strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 404 and "not found" in detail and _retry:
                # Model not pulled yet — pull it (blocking, can take minutes) and retry once.
                _ollama_pull(model)
                return ocr_via_ollama(path, model=model, timeout=timeout, _retry=False)
            raise RuntimeError(
                f"ollama OCR failed for {name} ({e.code}): {detail} — "
                f"is the model pulled? `ollama pull {model}`")
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"ollama OCR failed for {name}: {e} — is Ollama running?")
        if text:
            break
    if not text:
        raise RuntimeError(f"ollama OCR produced no text for {name} after 3 attempts")
    return _grounding_to_markdown(text)


# ponytail: 150 DPI render — enough for body text OCR; raise if small print misreads.
PDF_RENDER_DPI = int(os.environ.get("TRANSLATOR_PDF_DPI", "150"))


def pdf_via_ollama(path: str, pbar=None) -> str:
    """OCR a PDF page-by-page: render each page to PNG (PyMuPDF), OCR via Ollama,
    join with page-break separators. *pbar* (optional, tqdm-ish .total/.update)
    is advanced once per page."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "PDF OCR via ollama needs PyMuPDF (`pip install pymupdf`), "
            "or set TRANSLATOR_OCR_BACKEND=marker")
    name = os.path.basename(path)
    pages: list[str] = []
    with fitz.open(path) as doc, tempfile.TemporaryDirectory() as tmp:
        if doc.page_count == 0:
            raise RuntimeError(f"{name} has no pages")
        if pbar is not None:
            pbar.total = doc.page_count
        for i, page in enumerate(doc):
            png = os.path.join(tmp, f"page{i}.png")
            page.get_pixmap(dpi=PDF_RENDER_DPI).save(png)
            pages.append(ocr_via_ollama(png))
            if pbar is not None:
                pbar.update(1)
    return "\n\n".join(pages)


# Word's main namespace; paragraphs are <w:p>, text runs <w:t>, style <w:pStyle>.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_markdown(path: str) -> str:
    """Extract a .docx as markdown via stdlib (zip + xml) — no marker/OCR.

    A .docx is structured text, not an image: routing it through marker forces a
    docx→pdf step that needs weasyprint (a fragile native-lib dep on Windows).
    Reading word/document.xml directly is lossless for prose and dependency-free.
    HeadingN styles become #..######; everything else is a plain paragraph.
    Tables flatten to their cell text; images/drawings are dropped.
    """
    name = os.path.basename(path)
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise RuntimeError(f"{name} is not a valid .docx (no word/document.xml)")
    blocks: list[str] = []
    for p in ET.fromstring(xml).iter(f"{_W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()
        if not text:
            continue
        style = p.find(f"{_W}pPr/{_W}pStyle")
        val = style.get(f"{_W}val", "") if style is not None else ""
        if val.startswith("Heading") and val[-1:].isdigit():
            text = "#" * min(int(val[-1]), 6) + " " + text
        blocks.append(text)
    if not blocks:
        raise RuntimeError(f"docx produced empty markdown for {name} (no text found?)")
    return "\n\n".join(blocks)


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
