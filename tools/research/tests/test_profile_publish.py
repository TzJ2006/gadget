"""The researcher profile is published like every other generated page.

Profiles were the only thing written into content/research/ through
``write_site_content`` instead of ``write_bilingual``, so they never got a
Chinese twin — and nothing caught it because ``deploy_to_hugo`` had no test at
all. These pin the contract rather than the rendering: the profile must go
through the bilingual publisher, at the same relative path, carrying the
caller's force/overwrite flags.
"""

from pathlib import Path
from unittest.mock import patch

from research import output
from research.models import ResearcherProfile


def _profile() -> ResearcherProfile:
    return ResearcherProfile(
        name="Ada Lovelace",
        fetched_at="2026-09-13T12:00:00",
        analysis={"trajectory_summary": "Analytical engines, then everything else.",
                  "research_themes": ["computing", "mathematics"]},
    )


def test_profile_is_published_through_the_bilingual_writer(tmp_path):
    site = tmp_path / "site"
    # The disambiguating filename scheme is not what this pins — derive it.
    expected_rel = Path("research") / (output._safe_filename("Ada Lovelace") + ".md")
    en = site / "content" / expected_rel
    with patch.object(output, "write_bilingual",
                      return_value=(en, en.with_suffix(".zh.md"))) as wb, \
         patch.object(output, "resolve_site_content_dir"), \
         patch.object(output, "write_site_content",
                      side_effect=AssertionError(
                          "profiles must not bypass write_bilingual")):
        out = output.deploy_to_hugo(_profile(), site)

    assert wb.call_count == 1
    args, kwargs = wb.call_args
    assert args[0] == site
    assert args[1] == expected_rel
    assert args[2].startswith("---\n")  # frontmatter still leads the body
    assert "Ada Lovelace" in args[2]
    assert out == en


def test_force_and_overwrite_flags_reach_the_writer(tmp_path):
    site = tmp_path / "site"
    with patch.object(output, "write_bilingual", return_value=(None, None)) as wb, \
         patch.object(output, "resolve_site_content_dir"):
        output.deploy_to_hugo(_profile(), site, force=True, overwrite_human=True)

    _, kwargs = wb.call_args
    assert kwargs["force"] is True
    assert kwargs["overwrite_human"] is True
