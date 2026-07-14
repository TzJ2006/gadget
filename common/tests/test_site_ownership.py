"""Ownership rule + force-backup behavior of write_site_content/copy_site_static.

- generated files are stamped `gadget_generated: true` and may be overwritten
- human files (no gadget marker) raise HumanContentError unless overwrite_human
- force=True backs the previous generated file up under
  outputs/backups/website-force/<stamp>/ with a manifest.json
"""

from pathlib import Path

import pytest

import common.website_backup as wb
from common.site_staging import copy_site_static, write_site_content
from common.website_backup import HumanContentError


@pytest.fixture(autouse=True)
def _isolated_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "BACKUP_ROOT", tmp_path / "backups")
    monkeypatch.setattr(wb, "_session_dir", None)


CONTENT = "---\ntitle: t\n---\n\nGenerated body.\n"


def test_written_content_is_stamped_generated(tmp_path):
    site = tmp_path / "website"
    path = write_site_content(site, Path("research") / "x.md", CONTENT)
    text = path.read_text(encoding="utf-8")
    assert "gadget_generated: true" in text
    assert text.startswith("---\ntitle: t\ngadget_generated: true\n---")


def test_generated_file_can_be_overwritten_without_force(tmp_path):
    site = tmp_path / "website"
    rel = Path("research") / "x.md"
    write_site_content(site, rel, CONTENT)
    write_site_content(site, rel, CONTENT + "updated\n")  # no error, no backup
    assert not (wb.BACKUP_ROOT).exists()


def test_human_file_blocks_overwrite(tmp_path):
    site = tmp_path / "website"
    rel = Path("posts") / "hand.md"
    target = site / "content" / rel
    target.parent.mkdir(parents=True)
    target.write_text("---\ntitle: mine\n---\n\nHand-written.\n", encoding="utf-8")

    with pytest.raises(HumanContentError):
        write_site_content(site, rel, CONTENT)
    # blocked attempt is recorded in the session manifest
    manifests = list(wb.BACKUP_ROOT.rglob("manifest.json"))
    assert manifests, "blocked attempt should be recorded"
    assert "collision-blocked" in manifests[0].read_text(encoding="utf-8")

    # explicit dangerous opt-in overwrites
    write_site_content(site, rel, CONTENT, overwrite_human=True)
    assert "gadget_generated: true" in target.read_text(encoding="utf-8")


def test_explicit_human_marker_blocks_even_in_generated_dir(tmp_path):
    site = tmp_path / "website"
    rel = Path("bugJournal") / "daily" / "2026-01-01.md"
    target = site / "content" / rel
    target.parent.mkdir(parents=True)
    target.write_text("---\ntitle: t\ngadget_generated: false\n---\n\nMine.\n",
                      encoding="utf-8")
    with pytest.raises(HumanContentError):
        write_site_content(site, rel, CONTENT)


def test_force_backs_up_previous_generated_file(tmp_path):
    site = tmp_path / "website"
    rel = Path("bugJournal") / "daily" / "2026-01-01.md"
    first = write_site_content(site, rel, CONTENT)
    original = first.read_text(encoding="utf-8")

    write_site_content(site, rel, CONTENT + "regenerated\n", force=True)

    backups = list(wb.BACKUP_ROOT.rglob("2026-01-01.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    manifest = next(wb.BACKUP_ROOT.rglob("manifest.json")).read_text(encoding="utf-8")
    assert "overwritten" in manifest and "sha256" in manifest


def test_force_identical_content_makes_no_backup(tmp_path):
    site = tmp_path / "website"
    rel = Path("bugJournal") / "daily" / "2026-01-02.md"
    write_site_content(site, rel, CONTENT)
    write_site_content(site, rel, CONTENT, force=True)  # byte-identical after stamp
    assert not list(wb.BACKUP_ROOT.rglob("2026-01-02.md"))


def test_copy_site_static_force_backup(tmp_path):
    site = tmp_path / "website"
    src = tmp_path / "chart.png"
    src.write_bytes(b"v1")
    copy_site_static(site, src, Path("images") / "weekly" / "chart.png")
    src.write_bytes(b"v2")
    copy_site_static(site, src, Path("images") / "weekly" / "chart.png", force=True)

    backups = list(wb.BACKUP_ROOT.rglob("chart.png"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"v1"
    assert (site / "static" / "images" / "weekly" / "chart.png").read_bytes() == b"v2"


def test_stamp_no_frontmatter_falls_back_to_comment():
    stamped = wb.stamp_generated("plain text, no frontmatter\n")
    assert "<!-- gadget:generated -->" in stamped
    assert wb.classify_content(stamped) == "generated"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
