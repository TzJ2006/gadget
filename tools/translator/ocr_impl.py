"""Gadget-owned OCR. Standalone and hosted callers import this module.

No parent workspace path. Model name, host, and pull permission come from the environment.


The recognition call is the existing Ollama vision request. This module does not
download a model unless TRANSLATOR_OCR_ALLOW_PULL=1.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

OLLAMA_OCR_MODEL = os.environ.get("TRANSLATOR_OCR_MODEL", "hf.co/sahilchachra/Unlimited-OCR-GGUF")
OLLAMA_OCR_PROMPT = os.environ.get("TRANSLATOR_OCR_PROMPT", "document parsing.")
OLLAMA_OCR_TEMPERATURE = float(os.environ.get("TRANSLATOR_OCR_TEMPERATURE", "0.6"))
OLLAMA_OCR_TIMEOUT = int(os.environ.get("TRANSLATOR_OCR_TIMEOUT", "300"))
OLLAMA_OCR_NUM_CTX = int(os.environ.get("TRANSLATOR_OCR_NUM_CTX", "8192"))
OLLAMA_PULL_TIMEOUT = int(os.environ.get("TRANSLATOR_OCR_PULL_TIMEOUT", "3600"))
PDF_RENDER_DPI = int(os.environ.get("TRANSLATOR_PDF_DPI", "150"))
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
_GROUNDING_LINE = re.compile(r"^\s*(\w+)?\s*\[[\d,\s]+\](.*)$")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def ollama_host() -> str:
    try:
        from common.engine import ollama_native_host
        return ollama_native_host()
    except Exception:
        return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _junk(text: str) -> bool:
    return not text or (text.startswith("[") and text.endswith("]"))


def _grounding_to_markdown(raw: str) -> str:
    blocks: list[str] = []
    for line in raw.splitlines():
        match = _GROUNDING_LINE.match(line)
        if match:
            label, content = (match.group(1) or "").lower(), match.group(2).strip()
            if not _junk(content):
                blocks.append(f"# {content}" if label == "title" else content)
        elif not _junk(line.strip()):
            blocks.append(line.strip())
    return "\n\n".join(blocks)


def _pull_allowed() -> bool:
    return os.environ.get("TRANSLATOR_OCR_ALLOW_PULL", "") == "1"


def _ollama_pull(model: str) -> None:
    if not _pull_allowed():
        raise RuntimeError(f"模型 {model} 未安装。已拒绝自动下载。需要时设置 TRANSLATOR_OCR_ALLOW_PULL=1。")
    request = urllib_request(
        ollama_host() + "/api/pull",
        data=json.dumps({"model": model, "stream": False}).encode("utf-8"),
    )
    try:
        with urllib_open(request, timeout=OLLAMA_PULL_TIMEOUT) as response:
            status = json.loads(response.read()).get("status", "")
    except (urllib_error().URLError, TimeoutError) as exc:
        raise RuntimeError(f"ollama pull {model} failed: {exc}") from exc
    if status != "success":
        raise RuntimeError(f"ollama pull {model} failed: {status or 'unknown error'}")


def urllib_request(url: str, data: bytes):
    import urllib.request
    return urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})


def urllib_open(request, timeout: int):
    import urllib.request
    return urllib.request.urlopen(request, timeout=timeout)


def urllib_error():
    import urllib.error
    return urllib.error


def _require_ocr_lease(model: str) -> str:
    """Fail closed unless the installed model_access package grants a lease.

    A missing package, a denied lease, or another resident model does not fall
    through to an uncoordinated Ollama request or a second backend.
    The returned id is an active-use lease. Releasing it does not unload Ollama.
    """
    try:
        from model_access.resources import before_backend
    except ImportError as exc:
        raise RuntimeError(
            "未安装 model_access，拒绝在没有统一 GPU 租约的情况下加载 OCR 模型。"
            "安装该包后再运行；不会改走未登记的推理后端。"
        ) from exc
    gate = before_backend(
        "ollama", model, holder="gadget-ocr", endpoint=ollama_host(), purpose="ocr",
    )
    if not gate.allowed:
        raise RuntimeError(gate.reason or "拒绝加载 OCR 模型")
    return gate.lease_id


def _release_ocr_lease(lease_id: str) -> None:
    if not lease_id:
        return
    try:
        from model_access.resources import ResourceBoard
    except ImportError:
        return
    ResourceBoard().release(lease_id)


def ocr_via_ollama(path: str, *, model: str = OLLAMA_OCR_MODEL, timeout: int = OLLAMA_OCR_TIMEOUT, _retry: bool = True) -> str:
    lease_id = _require_ocr_lease(model)
    try:
        return _ocr_request(path, model=model, timeout=timeout, _retry=_retry)
    finally:
        _release_ocr_lease(lease_id)


def _ocr_request(path: str, *, model: str, timeout: int, _retry: bool) -> str:
    name = os.path.basename(path)
    payload = {
        "model": model,
        "prompt": OLLAMA_OCR_PROMPT,
        "images": [base64.b64encode(Path(path).read_bytes()).decode("ascii")],
        "stream": False,
        "options": {"temperature": OLLAMA_OCR_TEMPERATURE, "num_ctx": OLLAMA_OCR_NUM_CTX},
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "30m"),
    }
    text = ""
    for _attempt in range(3):
        request = urllib_request(ollama_host() + "/api/generate", json.dumps(payload).encode("utf-8"))
        try:
            with urllib_open(request, timeout) as response:
                text = (json.loads(response.read()).get("response") or "").strip()
        except urllib_error().HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 404 and "not found" in detail and _retry:
                _ollama_pull(model)
                return ocr_via_ollama(path, model=model, timeout=timeout, _retry=False)
            raise RuntimeError(
                f"ollama OCR failed for {name} ({exc.code}): {detail} — is the model pulled? `ollama pull {model}`"
            ) from exc
        except (urllib_error().URLError, TimeoutError) as exc:
            raise RuntimeError(f"ollama OCR failed for {name}: {exc} — is Ollama running?") from exc
        if text:
            break
    if not text:
        raise RuntimeError(f"ollama OCR produced no text for {name} after 3 attempts")
    return _grounding_to_markdown(text)


def pdf_via_ollama(path: str, pbar=None) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF OCR via ollama needs PyMuPDF (`pip install pymupdf`), "
            "or set TRANSLATOR_OCR_BACKEND=marker"
        ) from exc
    name = os.path.basename(path)
    pages: list[str] = []
    with fitz.open(path) as doc, tempfile.TemporaryDirectory() as tmp:
        if doc.page_count == 0:
            raise RuntimeError(f"{name} has no pages")
        if pbar is not None:
            pbar.total = doc.page_count
        for index, page in enumerate(doc):
            png = os.path.join(tmp, f"page{index}.png")
            page.get_pixmap(dpi=PDF_RENDER_DPI).save(png)
            pages.append(ocr_via_ollama(png))
            if pbar is not None:
                pbar.update(1)
    return "\n\n".join(pages)


def docx_to_markdown(path: str) -> str:
    name = os.path.basename(path)
    try:
        with zipfile.ZipFile(path) as handle:
            xml = handle.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise RuntimeError(f"{name} is not a valid .docx (no word/document.xml)") from exc
    blocks: list[str] = []
    for paragraph in ET.fromstring(xml).iter(f"{_W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_W}t")).strip()
        if not text:
            continue
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        val = style.get(f"{_W}val", "") if style is not None else ""
        if val.startswith("Heading") and val[-1:].isdigit():
            text = "#" * min(int(val[-1]), 6) + " " + text
        blocks.append(text)
    if not blocks:
        raise RuntimeError(f"docx produced empty markdown for {name} (no text found?)")
    return "\n\n".join(blocks)


def run_marker(path: str, *, env: str, timeout: int) -> str:
    name = os.path.basename(path)
    with tempfile.TemporaryDirectory() as out_dir:
        cmd = ["conda", "run", "-n", env, "marker_single", path, "--output_dir", out_dir, "--output_format", "markdown"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"marker timed out after {timeout}s converting {name}") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"could not run marker: `conda` not found on PATH (needs the '{env}' env)") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"marker failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}")
        files = glob.glob(os.path.join(out_dir, "**", "*.md"), recursive=True)
        if not files:
            raise RuntimeError(f"marker produced no markdown for {name}")
        text = Path(files[0]).read_text(encoding="utf-8")
        if not text.strip():
            raise RuntimeError(f"marker produced empty markdown for {name} (no text found?)")
        return text
