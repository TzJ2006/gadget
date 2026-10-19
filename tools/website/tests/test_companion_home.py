"""Build both blog homepages and verify article navigation."""

from html import unescape
from pathlib import Path
import shutil
import subprocess

import pytest


def test_blog_home(tmp_path):
    if not shutil.which("hugo"):
        pytest.skip("Hugo is required for the blog build check")
    site = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["hugo", "--source", str(site), "--destination", str(tmp_path / "site"),
         "--cacheDir", str(tmp_path / "cache"), "--baseURL", "http://127.0.0.1:8765/"],
        check=True, capture_output=True, text=True,
    )

    for language, title in [("", "Hi, I’m TzJ."), ("zh", "你好，我是 TzJ。")]:
        html = unescape((tmp_path / "site" / language / "index.html").read_text(encoding="utf-8"))
        assert title in html
        assert 'class="post-entry"' in html
        assert 'id="theme-toggle"' in html
        assert '<details class="menu-disclosure">' in html
        assert '<summary>' in html
        assert '<details class="menu-disclosure" open' not in html
        assert "AI Companion" not in html
        assert "ai-companion" not in html
        assert 'name="status"' not in html
        prefix = f"{language}/" if language else ""
        assert f'http://127.0.0.1:8765/{prefix}posts/' in html
        assert f'http://127.0.0.1:8765/{prefix}bugjournal/daily/' in html

    for language, heading in [("", "Experiments, observations & ideas."),
                              ("zh", "实验、观察与思考。")]:
        posts = tmp_path / "site" / language / "posts"
        assert heading in unescape((posts / "index.html").read_text(encoding="utf-8"))
        for article in posts.glob("*/index.html"):
            html = article.read_text(encoding="utf-8")
            if 'class="post-single"' not in html:
                continue
            assert 'class="toc"' in html
            assert "TzJ's Net" in unescape(html)
            other = "" if language else "zh/"
            assert f'http://127.0.0.1:8765/{other}posts/{article.parent.name}/' in html
