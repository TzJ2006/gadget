"""Unit tests for translator.core — mocks the heavy bits (model inference,
marker subprocess) and exercises the real routing / language logic.

Run from repo root:  python -m pytest tools/translator/tests/test_core.py
Or:  cd tools && python -m pytest translator/tests
"""

import subprocess
import types
from pathlib import Path

import pytest

from common import translation
from translator import core


class FakeEngine:
    """Stand-in TranslationEngine; records calls, never loads a model."""

    def __init__(self, out: str = "OUT") -> None:
        self.out = out
        self.calls: list[list[str]] = []

    def generate_batch(self, prompts, **kw):
        self.calls.append(list(prompts))
        return [self.out for _ in prompts]

    def load(self):
        pass

    def unload(self):
        pass


class EchoEngine:
    """Returns each prompt's source text unchanged (perfect identity 'translation').

    build_translation_prompt puts the chunk after a single '\\n\\n' separator, so
    echoing that tail exercises the REAL protect→split→restore pipeline without a
    model — proving markdown structure is preserved verbatim.
    """

    def generate_batch(self, prompts, **kw):
        return [p.split("\n\n", 1)[1] for p in prompts]

    def load(self):
        pass

    def unload(self):
        pass


# ── resolve_langs ──────────────────────────────────────────────
def test_resolve_langs_auto_detects_chinese():
    assert core.resolve_langs("你好世界，今天天气不错", "auto", "auto") == ("zh", "en")


def test_resolve_langs_auto_detects_english():
    assert core.resolve_langs("hello world, nice day", "auto", "auto") == ("en", "zh")


def test_resolve_langs_explicit_choices_win():
    assert core.resolve_langs("anything", "en", "zh") == ("en", "zh")
    assert core.resolve_langs("anything", "zh", "en") == ("zh", "en")


# ── translate_text ─────────────────────────────────────────────
def test_translate_text_empty_returns_unchanged_no_inference():
    eng = FakeEngine()
    assert core.translate_text("", "zh", eng) == ""
    assert core.translate_text("   \n\t ", "zh", eng) == "   \n\t "
    assert eng.calls == []  # the empty guard skips the engine entirely


def test_translate_text_delegates_to_translate_body(monkeypatch):
    eng = FakeEngine()
    seen = {}

    def fake_tb(text, target, engine, pbar=None, target_chars=None, context_chars=0):
        seen.update(text=text, target=target, engine=engine)
        return "TRANSLATED"

    monkeypatch.setattr(core, "translate_body", fake_tb)
    assert core.translate_text("# Hi\n```py\nx=1\n```", "zh", eng) == "TRANSLATED"
    assert seen == {"text": "# Hi\n```py\nx=1\n```", "target": "zh", "engine": eng}


# ── file_to_markdown routing ───────────────────────────────────
def test_file_to_markdown_reads_text_files(tmp_path):
    p = tmp_path / "doc.md"
    body = "# Title\n\n```py\nx = 1\n```\n"
    p.write_text(body, encoding="utf-8")
    assert core.file_to_markdown(str(p)) == body


def test_file_to_markdown_routes_rich_files_to_marker(monkeypatch, tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(core, "OCR_BACKEND", "marker")
    monkeypatch.setattr(core, "run_marker", lambda path, **kw: "# from marker")
    assert core.file_to_markdown(str(p)) == "# from marker"


# ── docx_to_markdown (stdlib, no marker — the weasyprint-bug fix) ───────
def _make_docx(path, *paragraphs):
    """Write a minimal valid .docx. paragraphs: (text, style|None) tuples."""
    import zipfile

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ""
    for text, style in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body += f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"
    doc = f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)


def test_docx_to_markdown_extracts_text_and_headings(tmp_path):
    p = tmp_path / "doc.docx"
    _make_docx(p, ("My Title", "Heading1"), ("A paragraph.", None), ("Sub", "Heading2"))
    assert core.docx_to_markdown(str(p)) == "# My Title\n\nA paragraph.\n\n## Sub"


def test_file_to_markdown_routes_docx_to_stdlib_not_marker(monkeypatch, tmp_path):
    p = tmp_path / "doc.docx"
    _make_docx(p, ("hello", None))
    monkeypatch.setattr(core, "run_marker", lambda *a, **k: pytest.fail("marker used for docx"))
    assert core.file_to_markdown(str(p)) == "hello"


def test_docx_to_markdown_empty_raises(tmp_path):
    p = tmp_path / "blank.docx"
    _make_docx(p, ("   ", None))
    with pytest.raises(RuntimeError, match="empty markdown"):
        core.docx_to_markdown(str(p))


def test_docx_to_markdown_invalid_file_raises(tmp_path):
    p = tmp_path / "fake.docx"
    p.write_bytes(b"not a zip")
    with pytest.raises(RuntimeError, match="not a valid .docx"):
        core.docx_to_markdown(str(p))


# ── run_marker subprocess bridge ───────────────────────────────
def test_run_marker_success(monkeypatch):
    def fake_run(cmd, **kw):
        # marker writes <output_dir>/<stem>/<stem>.md — simulate that.
        out_dir = cmd[cmd.index("--output_dir") + 1]
        sub = Path(out_dir) / "scan"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "scan.md").write_text("# OCR result\n", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    assert core.run_marker("scan.pdf") == "# OCR result\n"


def test_run_marker_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(
        core.subprocess, "run",
        lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    with pytest.raises(RuntimeError, match="marker failed"):
        core.run_marker("scan.pdf")


def test_run_marker_no_markdown_raises(monkeypatch):
    monkeypatch.setattr(
        core.subprocess, "run",
        lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    with pytest.raises(RuntimeError, match="no markdown"):
        core.run_marker("scan.pdf")


def test_run_marker_timeout_becomes_runtimeerror(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))

    monkeypatch.setattr(core.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="timed out"):
        core.run_marker("scan.pdf", timeout=1)


def test_run_marker_missing_conda_becomes_runtimeerror(monkeypatch):
    def boom(cmd, **kw):
        raise FileNotFoundError("conda")

    monkeypatch.setattr(core.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="conda` not found"):
        core.run_marker("scan.pdf")


def test_run_marker_empty_markdown_raises(monkeypatch):
    def fake_run(cmd, **kw):
        out_dir = cmd[cmd.index("--output_dir") + 1]
        Path(out_dir, "scan.md").write_text("   \n\n  ", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="empty markdown"):
        core.run_marker("scan.pdf")


def test_run_marker_uses_list_args_no_shell(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["shell"] = kw.get("shell", False)
        out_dir = cmd[cmd.index("--output_dir") + 1]
        Path(out_dir, "x.md").write_text("ok", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    core.run_marker("/path/with spaces/файл.pdf", env="deepseek-ocr")
    assert captured["shell"] is False
    assert isinstance(captured["cmd"], list)
    assert "/path/with spaces/файл.pdf" in captured["cmd"]
    assert captured["cmd"][:5] == ["conda", "run", "-n", "deepseek-ocr", "marker_single"]


# ── translate_file end-to-end (mocked inference) ───────────────
def test_translate_file_text_auto_en_source(monkeypatch, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("hello world", encoding="utf-8")
    monkeypatch.setattr(core, "translate_body", lambda text, target, engine, pbar=None, target_chars=None, context_chars=0: "你好世界")
    out, name, pair = core.translate_file(str(p), "auto", "auto", FakeEngine())
    assert out == "你好世界"
    assert name == "doc.zh.md"   # en source → zh target
    assert pair == "en->zh"


def test_translate_file_rich_file_uses_marker(monkeypatch, tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF")
    monkeypatch.setattr(core, "OCR_BACKEND", "marker")
    monkeypatch.setattr(core, "run_marker", lambda path, **kw: "你好，这是扫描件")
    monkeypatch.setattr(core, "translate_body", lambda text, target, engine, pbar=None, target_chars=None, context_chars=0: "Hello, this is a scan")
    out, name, pair = core.translate_file(str(p), "auto", "auto", FakeEngine())
    assert out == "Hello, this is a scan"
    assert name == "scan.en.md"  # zh source → en target
    assert pair == "zh->en"


# ── markdown-preservation hard criterion (REQ-002/003), real translate_body ────
def test_markdown_structure_preserved_real_pipeline():
    """Exercise the REAL translate_body via an echo engine (no model, no mock).

    With an identity 'translation', the protect→split→restore pipeline must return
    headings, fenced code blocks, and URLs byte-for-byte — the load-bearing markdown
    hard criterion that the mocked tests above cannot assert.
    """
    src = (
        "# Title\n\n"
        "Some **bold** text.\n\n"
        "## Section\n\n"
        "```python\ndef add(a, b):\n    return a + b\n```\n\n"
        "Visit https://example.com for details.\n"
    )
    out = core.translate_text(src, "zh", EchoEngine())
    assert out.count("```") == src.count("```")                 # fenced blocks
    assert out.count("\n#") == src.count("\n#")                 # heading lines
    assert "def add(a, b):\n    return a + b" in out            # code body verbatim
    assert "https://example.com" in out                         # URL preserved


class FakePbar:
    """Minimal tqdm-ish pbar: records updates and carries a settable total."""

    def __init__(self):
        self.total = 1
        self.steps = 0

    def update(self, k=1):
        self.steps += k


def test_count_tokens_uses_engine_tokenizer():
    class Tok:
        def encode(self, text):
            return text.split()  # 1 token per whitespace word

    eng = FakeEngine()
    eng._tokenizer = Tok()
    assert core.count_tokens(eng, "one two three") == 3


def test_count_tokens_uses_llama_tokenize():
    class LLM:
        def tokenize(self, raw):
            return list(raw)[:5]

    eng = FakeEngine()
    eng._llm = LLM()
    assert core.count_tokens(eng, "hello") == 5


def test_count_tokens_falls_back_to_char_estimate():
    eng = FakeEngine()  # no _tokenizer, no _llm
    assert core.count_tokens(eng, "") == 0
    assert core.count_tokens(eng, "a" * 40) == 10  # ~4 chars/token


def test_count_tokens_tokenizer_error_falls_back(caplog):
    class Tok:
        def encode(self, text):
            raise ValueError("bad tok")

    eng = FakeEngine()
    eng._tokenizer = Tok()
    with caplog.at_level("DEBUG", logger="translator.core"):
        assert core.count_tokens(eng, "a" * 40) == 10
    assert "bad tok" in caplog.text


def test_count_tokens_llama_tokenize_error_falls_back(caplog):
    class LLM:
        def tokenize(self, raw):
            raise RuntimeError("tokenize boom")

    eng = FakeEngine()
    eng._llm = LLM()
    with caplog.at_level("DEBUG", logger="translator.core"):
        assert core.count_tokens(eng, "a" * 40) == 10
    assert "tokenize boom" in caplog.text


def test_ollama_helpers_imported_under_public_names():
    """B19 public names, with alias fallback to the current _-prefixed helpers."""
    assert callable(core.ollama_native_host)
    assert callable(core.free_ollama_vram)


def test_count_chunks_matches_translate_body_steps():
    """count_chunks must equal the number of pbar.update(1) calls translate_body
    makes — otherwise the progress bar would over/undershoot."""
    src = "# A\n\n" + ("word " * 4000) + "\n\n## B\n\nmore text here\n"
    pbar = FakePbar()
    core.translate_text(src, "zh", EchoEngine(), pbar=pbar)
    assert pbar.steps == core.count_chunks(src) > 1  # multi-chunk on purpose


def test_translate_file_sets_pbar_total_then_drives_it(monkeypatch, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("hello world\n\nsecond paragraph\n", encoding="utf-8")
    pbar = FakePbar()
    core.translate_file(str(p), "auto", "auto", EchoEngine(), pbar=pbar)
    assert pbar.total == core.count_chunks(p.read_text(encoding="utf-8"))
    assert pbar.steps == pbar.total


def test_micro_chunk_splits_multiparagraph_into_batch():
    """A multi-paragraph page under the 7000 hard cap must still split into a
    batch (the only real batch=1 speedup) AND reconstruct byte-for-byte."""
    src = "This is a sentence about robots learning tasks.\n\n" * 30  # ~1500 chars
    chunks = translation.split_large_text(src, target_chars=core.MICRO_CHUNK_CHARS)
    assert len(chunks) > 1                # batched, not one chunk
    assert "".join(chunks) == src         # exact reconstruction — no data loss


def test_micro_chunk_keeps_single_paragraph_whole():
    """A single paragraph with no internal boundary is never split (meaning kept)."""
    src = "one short paragraph, no blank lines at all, must stay a single chunk"
    assert translation.split_large_text(src, target_chars=core.MICRO_CHUNK_CHARS) == [src]


def test_split_large_text_default_behavior_unchanged():
    """target_chars=None must preserve original behavior — other tools rely on it."""
    src = "para\n\n" * 50  # ~300 chars, under 7000 → one chunk, as before
    assert translation.split_large_text(src) == [src]


def test_build_prompt_no_background_is_unchanged():
    """background_text=None must be byte-identical to omitting it (and to the old
    prompt) — other tools (website/research/summarize) rely on this."""
    p0 = translation.build_translation_prompt("hi", "zh")
    p1 = translation.build_translation_prompt("hi", "zh", background_text=None)
    assert p0 == p1
    assert "【背景信息】" not in p0


def test_build_prompt_with_background_has_structure():
    p = translation.build_translation_prompt("hi", "zh", background_text="ctx here")
    assert "【背景信息】" in p and "【待翻译文本】" in p
    assert "ctx here" in p and "hi" in p


def test_context_injected_only_when_multichunk_single_batch_call():
    """Multi-chunk translation injects background into every chunk prompt, yet
    still makes exactly one generate_batch call (batching preserved)."""
    eng = FakeEngine()
    src = "Para about robots and policy learning here.\n\n" * 80  # > MICRO_CHUNK → many chunks
    core.translate_text(src, "zh", eng)
    assert len(eng.calls) == 1                          # single batch call
    assert len(eng.calls[0]) > 1                        # genuinely multi-chunk
    assert all("【背景信息】" in p for p in eng.calls[0])


def test_context_not_injected_for_single_chunk():
    """A single short paste has no cross-chunk context to preserve → no background
    (no wasted tokens)."""
    eng = FakeEngine()
    core.translate_text("one short line, single chunk", "zh", eng)
    assert len(eng.calls[0]) == 1
    assert "【背景信息】" not in eng.calls[0][0]


def test_restore_fragments_tolerates_mangled_placeholder():
    """Regression for the real E2E finding: the model can drop a bracket from a
    placeholder (`[[[HYMTPH_1]]` ), which the literal replace misses. The tolerant
    pass must still recover the protected fragment."""
    protected = {"[[[HYMTPH_0]]]": "`code`", "[[[HYMTPH_1]]]": "https://example.com"}
    mangled = "see [[[HYMTPH_0]]] and [[[HYMTPH_1]] now"  # second token lost a bracket
    restored = translation.restore_fragments(mangled, protected)
    assert restored == "see `code` and https://example.com now"


# ---- ollama OCR backend ----------------------------------------------------

def test_ocr_via_ollama_success(tmp_path, monkeypatch):
    import io, json
    from unittest.mock import patch
    from translator import core

    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG fake")
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R(json.dumps({"response": "# Hello\n\nOCR text"}).encode())

    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    with patch("urllib.request.urlopen", fake_urlopen):
        out = core.ocr_via_ollama(str(img), model="test-ocr")
    assert out == "# Hello\n\nOCR text"
    assert seen["url"].endswith("/api/generate")
    assert seen["body"]["model"] == "test-ocr"
    assert seen["body"]["images"]  # base64 payload present
    # 8192 keeps the OCR model ~5.7GB resident instead of 13.3GB (measured)
    assert seen["body"]["options"]["num_ctx"] == core.OLLAMA_OCR_NUM_CTX
    assert seen["body"]["keep_alive"] == "30m"


def test_file_to_markdown_routes_image_to_ollama(tmp_path, monkeypatch):
    from unittest.mock import patch
    from translator import core

    img = tmp_path / "scan.jpg"
    img.write_bytes(b"fake")
    monkeypatch.setattr(core, "OCR_BACKEND", "ollama")
    with patch.object(core, "ocr_via_ollama", return_value="md") as m:
        assert core.file_to_markdown(str(img)) == "md"
    m.assert_called_once_with(str(img))


def test_pdf_via_ollama_joins_pages(tmp_path, monkeypatch):
    from unittest.mock import patch, MagicMock
    import sys
    from translator import core

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")
    page = MagicMock()
    doc = MagicMock()
    doc.page_count = 2
    doc.__iter__ = lambda s: iter([page, page])
    doc.__enter__ = lambda s: doc
    doc.__exit__ = lambda s, *a: False
    fitz = MagicMock()
    fitz.open.return_value = doc
    with patch.dict(sys.modules, {"fitz": fitz}), \
         patch.object(core, "ocr_via_ollama", side_effect=["page one", "page two"]):
        out = core.pdf_via_ollama(str(pdf))
    assert out == "page one\n\npage two"


def test_file_to_markdown_routes_pdf_to_ollama_by_default(tmp_path):
    from unittest.mock import patch
    from translator import core

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")
    assert core.OCR_BACKEND == "ollama"  # default backend
    with patch.object(core, "pdf_via_ollama", return_value="md") as m:
        assert core.file_to_markdown(str(pdf)) == "md"
    m.assert_called_once_with(str(pdf), pbar=None)


def test_ocr_via_ollama_pulls_model_on_404_then_retries(tmp_path):
    import io, json
    import urllib.error
    from unittest.mock import patch
    from translator import core

    img = tmp_path / "page0.png"
    img.write_bytes(b"\x89PNG fake")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if req.full_url.endswith("/api/pull"):
            body = {"status": "success"}
        elif len([c for c in calls if c.endswith("/api/generate")]) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {},
                io.BytesIO(b'{"error":"model \'m\' not found"}'))
        else:
            body = {"response": "ocr text"}
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R(json.dumps(body).encode())

    with patch("urllib.request.urlopen", fake_urlopen):
        assert core.ocr_via_ollama(str(img), model="m") == "ocr text"
    # generate(404) -> pull -> generate(ok), and no infinite retry loop
    assert [c.rsplit("/", 1)[1] for c in calls] == ["generate", "pull", "generate"]


def test_grounding_to_markdown_strips_coords_and_junk():
    from translator.core import _grounding_to_markdown
    raw = (" [NO TEXT]\n"
           "title [30, 156, 682, 252]Hello World: OCR smoke test 12345\n"
           "text [32, 416, 834, 552]The quick brown fox jumps over the lazy dog.\n"
           "First block sometimes has no coords\n"
           "text [31, 688, 687, 823]你好，世界。这是一个中文识别测试。")
    out = _grounding_to_markdown(raw)
    assert out == ("# Hello World: OCR smoke test 12345\n\n"
                   "The quick brown fox jumps over the lazy dog.\n\n"
                   "First block sometimes has no coords\n\n"
                   "你好，世界。这是一个中文识别测试。")
    assert "[" not in out


def test_pdf_via_ollama_reports_page_progress(tmp_path):
    from unittest.mock import patch, MagicMock
    import sys
    from translator import core

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")
    page = MagicMock()
    doc = MagicMock()
    doc.page_count = 3
    doc.__iter__ = lambda s: iter([page, page, page])
    doc.__enter__ = lambda s: doc
    doc.__exit__ = lambda s, *a: False
    fitz = MagicMock()
    fitz.open.return_value = doc

    class Pbar:
        total = 1
        steps = []
        def update(self, k=1): self.steps.append(k)

    pbar = Pbar()
    with patch.dict(sys.modules, {"fitz": fitz}), \
         patch.object(core, "ocr_via_ollama", return_value="p"):
        core.pdf_via_ollama(str(pdf), pbar=pbar)
    assert pbar.total == 3
    assert pbar.steps == [1, 1, 1]
