"""Report pages leave the build encrypted, and their text is gone from feeds, search and list cards."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import protect  # noqa: E402

SECRET = "private report text"
CARD = '<article class="post-entry"><p>%s</p><a href="https://x.io/bugjournal/daily/2026-01-01/"></a></article>' % SECRET


def site(tmp_path):
    for folder in ("bugjournal/daily/2026-01-01", "zh/bugjournal", "posts/hello", "tags/bug-journal"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "bugjournal/daily/2026-01-01/index.html").write_text("<html>%s</html>" % SECRET, encoding="utf-8")
    (tmp_path / "bugjournal/index.xml").write_text(SECRET, encoding="utf-8")
    (tmp_path / "zh/bugjournal/index.html").write_text("<html>%s</html>" % SECRET, encoding="utf-8")
    (tmp_path / "posts/hello/index.html").write_text("<html>public post</html>", encoding="utf-8")
    (tmp_path / "tags/bug-journal/index.html").write_text(
        '<html><a href="/bugjournal/">menu</a>%s<article><a href="/posts/hello/">kept</a></article></html>' % CARD, encoding="utf-8")
    (tmp_path / "index.xml").write_text(
        "<rss><item><link>https://x.io/bugjournal/daily/2026-01-01/</link><description>%s</description></item>"
        "<item><link>https://x.io/posts/hello/</link></item></rss>" % SECRET, encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([
        {"permalink": "https://x.io/bugjournal/daily/2026-01-01/", "content": SECRET},
        {"permalink": "https://x.io/posts/hello/", "content": "public post"}]), encoding="utf-8")
    (tmp_path / "sitemap.xml").write_text("<loc>https://x.io/bugjournal/daily/2026-01-01/</loc>", encoding="utf-8")
    return tmp_path


def test_reports_are_encrypted_and_removed_from_public_listings(tmp_path, monkeypatch):
    monkeypatch.setattr(protect, "ITERATIONS", 1000)
    public = site(tmp_path)
    assert protect.protect(public, "pw") == 2
    assert not (public / "bugjournal/index.xml").exists()
    for path in public.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8"), path
    page = (public / "bugjournal/daily/2026-01-01/index.html").read_text(encoding="utf-8")
    data = protect.base64.b64decode(page.split('DATA="')[1].split('"')[0])
    assert protect.decrypt(protect.derive_key("pw"), data) == b"<html>%s</html>" % SECRET.encode()
    with pytest.raises(Exception):
        protect.decrypt(protect.derive_key("wrong"), data)
    assert "kept" in (public / "tags/bug-journal/index.html").read_text(encoding="utf-8")
    assert "posts/hello" in (public / "index.xml").read_text(encoding="utf-8")
    assert len(json.loads((public / "index.json").read_text(encoding="utf-8"))) == 1
    assert (public / "posts/hello/index.html").read_text(encoding="utf-8") == "<html>public post</html>"
    again = site(tmp_path / "again")
    protect.protect(again, "pw")  # same page, same bytes: nothing to commit when nothing changed
    assert (again / "bugjournal/daily/2026-01-01/index.html").read_text(encoding="utf-8") == page


def test_publish_is_refused_without_password_or_when_text_stays_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(protect, "ITERATIONS", 1000)
    with pytest.raises(RuntimeError, match="没有设置报告密码"):
        protect.protect(site(tmp_path / "a"), "")
    leaky = site(tmp_path / "b")
    (leaky / "posts/hello/index.html").write_text('<p>%s</p><a href="/bugjournal/daily/2026-01-01/">x</a>' % SECRET, encoding="utf-8")
    with pytest.raises(RuntimeError, match="停止发布"):
        protect.protect(leaky, "pw")
