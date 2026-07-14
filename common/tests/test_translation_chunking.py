"""zh-aware chunk ceiling — chunks must fit the Ollama translator's num_ctx.

A 7000-char zh chunk is ~4.5k tokens; with the 4096-token output budget it
overflows the 8192 default num_ctx and Ollama silently left-truncates the
prompt. chunk_ceiling caps zh chunks at 5000 chars (EN stays at 7000).
"""

from common import translation

ZH_PARA = ("模型驻留很重要，因为重新加载权重需要数十秒。翻译引擎批量处理提示词以提高吞吐。"
           "\n\n")
EN_PARA = ("Model residency matters because reloading weights costs tens of seconds. "
           "The engine batches prompts for throughput.\n\n")


def test_chunk_ceiling_by_language():
    assert translation.chunk_ceiling(ZH_PARA * 5) == 5000
    assert translation.chunk_ceiling(EN_PARA * 5) == 7000


def test_zh_split_respects_ceiling_and_reconstructs():
    body = ZH_PARA * 300  # ~12K chars
    chunks = translation.split_large_text(body, max_chars=translation.chunk_ceiling(body))
    assert len(chunks) >= 3          # 5000-cap → 3 chunks (7000-cap would give 2)
    assert all(len(c) <= 5000 for c in chunks)
    assert "".join(chunks) == body   # byte-exact reconstruction


def test_translate_body_uses_zh_ceiling():
    captured: list[str] = []

    class Eng:
        def generate_batch(self, prompts, **kw):
            captured.extend(prompts)
            return ["译" for _ in prompts]

    body = ZH_PARA * 300
    translation.translate_body(body, "en", Eng())
    assert len(captured) >= 3                      # split under the tighter zh cap
    assert all(len(p) < 5000 + 600 for p in captured)  # chunk + prompt boilerplate


def test_hard_split_boundaryless_zh_line():
    """A single-line zh paragraph (no headers/blank lines) must still respect the
    ceiling — silently overflowing num_ctx truncates the translation output."""
    src = "这是一个没有换行的超长句子，用于验证强制切分逻辑。" * 300  # ~7200 chars, one line
    chunks = translation.split_large_text(src, max_chars=5000)
    assert len(chunks) >= 2
    assert all(len(c) <= 5000 for c in chunks)
    assert "".join(chunks) == src
    assert all(c.endswith("。") for c in chunks[:-1])  # cut at sentence breaks


def test_hard_split_no_punctuation_falls_back_to_plain_cut():
    src = "字" * 12000  # degenerate: no boundaries, no punctuation
    chunks = translation.split_large_text(src, max_chars=5000)
    assert all(len(c) <= 5000 for c in chunks)
    assert "".join(chunks) == src


def test_translate_body_en_ceiling_unchanged():
    captured: list[str] = []

    class Eng:
        def generate_batch(self, prompts, **kw):
            captured.extend(prompts)
            return ["x" for _ in prompts]

    body = EN_PARA * 100  # ~12K chars → 2 chunks at the 7000 ceiling
    translation.translate_body(body, "zh", Eng())
    assert len(captured) == 2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
