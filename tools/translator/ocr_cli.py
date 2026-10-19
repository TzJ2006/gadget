"""Standalone OCR entry. Does not look for a personalAgent checkout.

    python -m translator.ocr_cli page.png

Installed gadget is enough (`pip install -e .` from this repo). Configuration is
environment only: OLLAMA_HOST, TRANSLATOR_OCR_MODEL, TRANSLATOR_OCR_ALLOW_PULL.
Loading a model also requires the installed ``model_access`` package.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _load():
    try:
        from translator.ocr_impl import docx_to_markdown, ocr_via_ollama, pdf_via_ollama
    except ImportError:
        root = Path(__file__).resolve().parents[2]
        for item in (root, root / "tools"):
            text = str(item)
            if text not in sys.path:
                sys.path.insert(0, text)
        from translator.ocr_impl import docx_to_markdown, ocr_via_ollama, pdf_via_ollama
    return ocr_via_ollama, pdf_via_ollama, docx_to_markdown


def recognize(path: str) -> str:
    """Run the gadget OCR implementation for an image, PDF, or docx."""
    ocr_via_ollama, pdf_via_ollama, docx_to_markdown = _load()
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return pdf_via_ollama(path)
    if suffix == ".docx":
        return docx_to_markdown(path)
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise RuntimeError("只接受 .png、.jpg、.jpeg、.pdf 或 .docx")
    return ocr_via_ollama(path)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("用法: python -m translator.ocr_cli <图片、PDF 或 docx>", file=sys.stderr)
        return 2
    try:
        print(recognize(args[0]))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
