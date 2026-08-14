"""Gradio GUI — Google-Translate-style window/webpage over the local engine.

The UI is wiring only; all logic is in ``translator.core``. Cross-platform by
construction (browser-based, no native GUI deps).
"""

from __future__ import annotations

import os
import tempfile
import time
import warnings
from pathlib import Path

# ponytail: gradio 6.19 still uses starlette's old HTTP_422 constant name;
# harmless — drop this filter once gradio catches up.
warnings.filterwarnings("ignore", message=".*HTTP_422_UNPROCESSABLE_ENTITY.*")

import gradio as gr

from translator.core import (
    count_chunks,
    count_tokens,
    file_to_markdown,
    free_ollama_vram,
    get_engine,
    resolve_langs,
    translate_text,
)
from translator.models import add_model, load_models, remove_model


LANGS = ["auto", "zh", "en"]
FILE_TYPES = [".md", ".markdown", ".txt", ".pdf", ".docx", ".png", ".jpg", ".jpeg"]


def _speed(text: str, elapsed: float, engine) -> str:
    """`<n> tok · <s>s · <r> tok/s` for the status line (generation only)."""
    toks = count_tokens(engine, text)
    rate = toks / elapsed if elapsed > 0 else 0.0
    return f"{toks} tok · {elapsed:.1f}s · {rate:.1f} tok/s"


class _Pbar:
    """Adapts gradio's Progress (a ``progress(fraction, desc=)`` callable) to the
    ``.update(n)`` / ``.total`` tqdm-ish interface ``translate_body`` expects."""

    def __init__(self, progress, total: int = 1, desc: str = "翻译中 Translating…") -> None:
        self.progress = progress
        self.total = max(total, 1)
        self.n = 0
        self.desc = desc
        progress(0.0, desc=desc)

    def update(self, k: int = 1) -> None:
        self.n += k
        frac = min(self.n / max(self.total, 1), 1.0)
        self.progress(frac, desc=f"{self.desc} {self.n}/{self.total}")


def _on_upload(path: str | None, progress=gr.Progress()) -> tuple[str, str | None, str]:
    """Convert an uploaded file to plain text and show it in the left textbox;
    translation then always operates on the visible text. PDFs report per-page
    OCR progress; images/docx are a single step."""
    if not path:
        return gr.skip(), gr.skip(), gr.skip()
    try:
        pbar = _Pbar(progress, desc="转换中 Converting…")  # total set per-page for PDFs
        content = file_to_markdown(path, pbar=pbar)  # OCR/conversion happens here, on upload
    except Exception as e:  # noqa: BLE001 — surface any failure to the UI, never crash
        return gr.skip(), None, f"❌ {e}"
    label = Path(path).name
    return content, label, f"📄 已转换 {label} — 点击 Translate 翻译"


def _on_submit(text: str, label: str | None, src: str, tgt: str, model: str,
               progress=gr.Progress()) -> tuple[str, str | None, str]:
    """Translate the text in the box. Returns (translation, download_path_or_None, status)."""
    content = (text or "").strip()
    if not content:
        return "", None, "✏️ 输入文字或拖入文件 / Type text or drop a file, then Translate."
    try:
        progress(0.0, desc=f"加载模型 Loading {model.split('/')[-1]}…")
        engine = get_engine(model)  # download/cold-start happens here — OUTSIDE the timer
        s, t = resolve_langs(content, src, tgt)
        pbar = _Pbar(progress, count_chunks(content))
        start = time.perf_counter()
        out = translate_text(content, t, engine, pbar=pbar)
        elapsed = time.perf_counter() - start
        if label:  # offer a download for converted/translated documents
            name = f"{Path(label).stem}.{t}.md"
            out_path = os.path.join(tempfile.gettempdir(), name)
            Path(out_path).write_text(out, encoding="utf-8")
            return out, out_path, f"✅ {label} ({s}->{t}) · {_speed(out, elapsed, engine)}"
        return out, None, f"✅ {s} → {t} · {_speed(out, elapsed, engine)}"
    except Exception as e:  # noqa: BLE001 — surface any failure to the UI, never crash
        return "", None, f"❌ {e}"


def _on_add(model_id: str):
    """Add a model; refresh both the main dropdown and the manage list."""
    models = add_model(model_id)
    value = (model_id or "").strip() or (models[0] if models else None)
    msg = f"✅ 已添加 {model_id.strip()}" if (model_id or "").strip() in models else "（已存在或为空）"
    return (gr.update(choices=models, value=value),
            gr.update(choices=models, value=value), "", msg)


def _on_remove(model_id: str):
    """Remove the selected model; refresh both dropdowns."""
    models = remove_model(model_id)
    value = models[0] if models else None
    return (gr.update(choices=models, value=value),
            gr.update(choices=models, value=value), f"🗑️ 已删除 {model_id}")


def build_ui() -> gr.Blocks:
    models = load_models()
    with gr.Blocks(title="Gadget Translate") as demo:
        gr.Markdown("# 🌐 Gadget Translate\n本地 HY-MT 翻译 · 文字 / 文件 · 保留 Markdown 格式")
        with gr.Row():
            model = gr.Dropdown(models, value=models[0], label="模型 Model（7B/FP8 首次选择会下载并加载）")
            src = gr.Dropdown(LANGS, value="auto", label="源语言 Source")
            tgt = gr.Dropdown(LANGS, value="auto", label="目标 Target")
        with gr.Tab("翻译 Translate"):
            with gr.Row():
                box = gr.Textbox(
                    label="原文 Source",
                    placeholder="粘贴文字… / Paste text, or upload a file below…",
                    lines=16, max_lines=16, scale=1,
                )
                out = gr.Textbox(lines=16, max_lines=16, label="译文 Translation", scale=1)
            btn = gr.Button("翻译 Translate", variant="primary")
            upload = gr.File(label="上传文件 Upload (.md .txt .pdf .docx 图片) — 自动转为纯文本",
                             file_types=FILE_TYPES)
            dl = gr.File(label="下载 Download（文件翻译时）")
            status = gr.Markdown()
            file_label = gr.State(None)  # name of the converted file, for the download name
            # show_progress="minimal": don't hide the source box behind gradio's
            # full loading overlay while OCR/conversion (possibly minutes) runs.
            upload.upload(_on_upload, [upload], [box, file_label, status],
                          show_progress="minimal")
            btn.click(_on_submit, [box, file_label, src, tgt, model], [out, dl, status])
        with gr.Tab("模型管理 Models"):
            gr.Markdown("增删翻译模型（填 HuggingFace repo id）。改动即时生效并持久化。")
            manage = gr.Dropdown(models, value=models[0], label="已有模型 Models")
            with gr.Row():
                add_box = gr.Textbox(label="新增模型 Add (HF repo id)", placeholder="org/Model-Name")
                add_btn = gr.Button("添加 Add", variant="primary")
                del_btn = gr.Button("删除选中 Delete")
            manage_status = gr.Markdown()
            add_btn.click(_on_add, [add_box], [model, manage, add_box, manage_status])
            del_btn.click(_on_remove, [manage], [model, manage, manage_status])
    return demo


def main() -> None:
    import atexit

    # ponytail: gradio's launch() health-check (httpx.get on 127.0.0.1) otherwise
    # follows HTTP(S)_PROXY and the proxy refuses localhost → WinError 10061.
    local = "127.0.0.1,localhost"
    for var in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(var, "")
        os.environ[var] = f"{local},{existing}" if existing else local
    # On exit (Ctrl-C included) evict the OCR/translation models from Ollama's
    # VRAM; set GADGET_KEEP_OLLAMA=1 to keep them warm across restarts.
    atexit.register(free_ollama_vram)
    build_ui().launch()


if __name__ == "__main__":
    main()
