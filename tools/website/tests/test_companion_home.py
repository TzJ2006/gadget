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

    output = tmp_path / "site"
    for language in ("", "zh"):
        prefix = f"{language}/" if language else ""
        html = unescape((output / language / "index.html").read_text(encoding="utf-8"))
        assert 'class="portfolio"' in html
        assert '<video controls playsinline preload="none"' in html
        assert 'id="theme-toggle"' in html
        assert 'class="research-art"' not in html
        for section in ("projects", "posts", "library", "resume"):
            assert f'/{prefix}{section}/' in html
        projects = (output / language / "projects/index.html").read_text(encoding="utf-8")
        assert 'id="recoverbench"' in projects and '<video' in projects
        for article in (output / language / "leetcode").glob("*/index.html"):
            text = article.read_text(encoding="utf-8")
            if 'class="post-single"' in text:
                assert '<math' in text, article
                assert 'MathJax-script' not in text
        research = (output / language / "research/enes_eken/index.html").read_text(encoding="utf-8")
        assert research.count('<table>') >= 2
        currency = (output / language / "bugjournal/daily/2026-02-17/index.html").read_text(encoding="utf-8")
        assert '$' in currency and '<math' not in currency
    for slug in ('collision-recovery', 'grasp-recovery'):
        assert (output / f'media/recoverbench/{slug}.mp4').stat().st_size > 10000
