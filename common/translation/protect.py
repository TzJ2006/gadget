"""Fragment protection, chunking, language detection, and translation prompts.

Preserves code blocks, URLs, and Hugo shortcodes during translation, and
splits large bodies so chunks fit the translator's context window.
"""

from __future__ import annotations

import re
from pathlib import Path

LANG_NAMES = {"en": "English", "zh": "Chinese"}

# ---------------------------------------------------------------------------
# Frontmatter splitting
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^(---\s*\n.*?\n---\s*\n?)(.*)$", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split Hugo markdown into (frontmatter_block, body).

    Returns ("", text) when no frontmatter is found.
    """
    match = FRONTMATTER_RE.match(text)
    if match:
        return match.group(1), match.group(2)
    return "", text


def _reattach_body(frontmatter: str, translated_fm: str, body: str) -> str:
    """Rejoin a re-serialized frontmatter block to its body.

    ``splitlines()`` + ``"\\n".join()`` drops the frontmatter block's trailing
    newline(s), which would glue the closing ``---`` fence onto the first body
    line and corrupt the document. Restore the original block's exact trailing
    newline(s) so the boundary is preserved.
    """
    if not frontmatter:
        return f"{translated_fm}{body}"
    trailing = frontmatter[len(frontmatter.rstrip("\n")):]
    return translated_fm.rstrip("\n") + trailing + body


# ---------------------------------------------------------------------------
# Fragment protection (code blocks, shortcodes, URLs, inline code)
# ---------------------------------------------------------------------------

PROTECTED_PATTERNS = [
    # Embedded usage-card component (summarize reports) — raw HTML, keep verbatim
    re.compile(r"(?s)<style>\s*\.usage-card.*?</style>"),
    re.compile(r'(?s)<footer class="usage-card">.*?</footer>'),
    re.compile(r"(?ms)^```.*?^```[ \t]*\n?"),
    re.compile(r"(?s)\{\{[%<].*?[>%]\}\}"),
    re.compile(r"(?s)<!--.*?-->"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"https?://[^\s)>\]]+"),
]


def protect_fragments(text: str) -> tuple[str, dict[str, str]]:
    """Replace untranslatable fragments with placeholder tokens."""
    protected: dict[str, str] = {}
    counter = 0

    for pattern in PROTECTED_PATTERNS:
        def replacer(match: re.Match[str]) -> str:
            nonlocal counter
            token = f"[[[HYMTPH_{counter}]]]"
            protected[token] = match.group(0)
            counter += 1
            return token

        text = pattern.sub(replacer, text)

    return text, protected


# The model occasionally mangles a placeholder's surrounding brackets/spacing
# (e.g. emits `[[[HYMTPH_1]]` with one bracket dropped), which a literal replace
# misses and silently drops the protected fragment (URL/code/etc). This tolerant
# matcher mops those up. Anchored on `HYMTPH_\d+` so it cannot match real content.
_PLACEHOLDER_RE = re.compile(r"\[{2,3}\s*(HYMTPH_\d+)\s*\]{2,3}")


def restore_fragments(text: str, protected: dict[str, str]) -> str:
    """Restore placeholder tokens back to original fragments.

    First an exact replace, then a tolerant pass that recovers placeholders the
    model lightly corrupted (wrong bracket count / stray spaces).
    """
    for token, original in protected.items():
        text = text.replace(token, original)

    def _recover(match: re.Match[str]) -> str:
        canonical = f"[[[{match.group(1)}]]]"
        return protected.get(canonical, match.group(0))

    return _PLACEHOLDER_RE.sub(_recover, text)


# ---------------------------------------------------------------------------
# Text chunking for large documents
# ---------------------------------------------------------------------------

_SENTENCE_BREAKS = "。！？；!?;．"


def _hard_split(chunk: str, max_chars: int) -> list[str]:
    """Last-resort split for a boundary-less blob longer than *max_chars*.

    Cuts at the latest sentence-ending punctuation in each window (plain cut when
    none exists), so the translator's num_ctx can never be silently overflowed by
    one giant single-line paragraph. Concatenating the parts reproduces the input
    byte-for-byte.
    """
    parts: list[str] = []
    rest = chunk
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = max(window.rfind(p) for p in _SENTENCE_BREAKS) + 1
        if cut <= max_chars // 2:  # no usable sentence break in the window
            cut = max_chars
        parts.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        parts.append(rest)
    return parts


def split_large_text(
    text: str, max_chars: int = 7000, target_chars: int | None = None
) -> list[str]:
    """Split text into chunks at header or blank-line boundaries.

    With *target_chars* set, also packs paragraphs into ~target_chars chunks even
    when the whole text fits under max_chars — so a multi-paragraph page becomes a
    real batch (the GPU is launch-bound at batch=1; batching is the only real
    speedup — see translator/perf_report.md). max_chars is a HARD ceiling: a
    paragraph with no internal boundary is split at sentence punctuation as a
    last resort (silently overflowing the translator's context window truncates
    output, which is strictly worse for meaning than a sentence-boundary cut).
    target_chars=None keeps the original max_chars-only behavior, so other
    callers (website/research/summarize) are unaffected.
    """
    soft = target_chars or max_chars
    if len(text) <= soft:
        return [text]

    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    breakpoints: list[int] = []

    def flush(chunk_lines: list[str]) -> None:
        chunk = "".join(chunk_lines)
        if not chunk:
            return
        if len(chunk) > max_chars:
            chunks.extend(_hard_split(chunk, max_chars))
        else:
            chunks.append(chunk)

    for line in lines:
        current.append(line)
        current_len += len(line)
        if line.startswith("#") or not line.strip():
            breakpoints.append(len(current))

        # soft cut: reached target while sitting on a boundary → emit whole buffer
        if current_len >= soft and breakpoints and breakpoints[-1] == len(current):
            flush(current)
            current = []
            current_len = 0
            breakpoints = []
            continue

        if current_len < max_chars:
            continue

        if breakpoints:
            cut = breakpoints[-1]
        else:
            cut = len(current)

        flush(current[:cut])
        current = current[cut:]
        current_len = sum(len(item) for item in current)
        breakpoints = []
        for index, item in enumerate(current, start=1):
            if item.startswith("#") or not item.strip():
                breakpoints.append(index)

    flush(current)
    return [chunk for chunk in chunks if chunk]


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Heuristic: if CJK chars exceed 5% of content, treat it as Chinese."""
    stripped = text.strip()
    if not stripped:
        return "en"
    cjk = sum(1 for char in stripped if "\u4e00" <= char <= "\u9fff")
    return "zh" if cjk / len(stripped) > 0.05 else "en"


def chunk_ceiling(text: str) -> int:
    """Hard chunk-size cap (chars) so a chunk + 4096 output tokens fits the
    Ollama translator's num_ctx (default 8192 \u2014 see OllamaEngine).

    CJK runs ~0.65 tokens/char, so a 7000-char zh chunk (~4.5k tokens) would
    overflow and get silently left-truncated; 5000 chars (~3.3k tokens) fits.
    EN text at 7000 chars is only ~1.8k tokens \u2014 the original ceiling stands.
    """
    return 5000 if detect_language(text) == "zh" else 7000


def zh_path(relative_path: Path) -> Path:
    """Convert a .md path to its .zh.md counterpart."""
    return relative_path.parent / f"{relative_path.stem}.zh{relative_path.suffix}"


# A model that echoes its input (server hiccup, prompt confusion) used to sail
# through validation and get stamped with the src-hash marker — freezing the
# untranslated original as the "current" translation forever. Judge on prose
# only: code/URLs/HTML are protected fragments, and a code-heavy page is mostly
# non-prose, which would otherwise always read as English.
# Low on purpose: a near-empty daily report's whole prose is a heading or two
# (~35 chars). A false positive only costs a re-translation next run; a false
# negative freezes an untranslated page on the site.
_PROSE_MIN = 20


def wrong_language(text: str, target_lang: str) -> bool:
    """True when *text* has enough prose to judge and it is not in *target_lang*."""
    protected, _ = protect_fragments(text)
    prose = _PLACEHOLDER_RE.sub("", protected).strip()
    return len(prose) >= _PROSE_MIN and detect_language(prose) != target_lang


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_translation_prompt(
    text: str,
    target_lang: str,
    *,
    markdown: bool = True,
    background_text: str | None = None,
) -> str:
    task = "Markdown文本" if markdown else "文本"
    target_name = "中文" if target_lang == "zh" else "English"
    proper_nouns = (
        "该翻译的内容必须翻译。"
        "不要翻译专有名词、项目名称、工具名称、模型名称和缩写词，保留原文"
        "（例如 LeRobot, NeurIPS, MIHD, RecoverBench, BlackHole, STAIG, Hugo, Claude 等）。"
    )
    if target_lang == "zh":
        proper_nouns += (
            "若标题或专业名词原本就是英文，在中文中保留英文，不要强行意译。"
        )
    preserve = (
        "保持原始Markdown格式不变；不要翻译代码块、行内代码、URL、文件路径、HTML标签、Hugo shortcodes、占位符 token。"
        if markdown
        else "保留占位符 token、URL、文件路径和代码标识符。"
    )
    instruction = (
        f"将以下{task}翻译为{target_name}，注意只需要输出翻译后的结果，不要额外解释。"
        f"{proper_nouns}{preserve}"
    )
    # background_text gives the model document-level context (terminology /
    # referents) so independently-translated chunks stay consistent. None →
    # byte-identical to the original prompt (other callers unaffected).
    if background_text:
        return (
            f"【背景信息】\n{background_text}\n\n"
            f"{instruction}\n\n"
            f"【待翻译文本】\n{text}"
        )
    return f"{instruction}\n\n{text}"
