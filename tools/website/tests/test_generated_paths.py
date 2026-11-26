"""Every consumer must answer "is this file ours?" the same way.

The path list is a fast guess used to avoid reading a few thousand files; the
real ownership answer is the gadget_generated marker inside the file. But while
the guess existed in three places with three matching rules, the guess itself
disagreed with itself:

  publish.py      had its own copy of the tuples and matched path.name, so any
                  file anywhere called benchmark.md counted as generated
  preflight       imported the tuples and matched the exact relative path
  translate_site  resolved them to absolute paths and matched by parent

The consequence was real, not theoretical: a hand-written content/posts/
benchmark.md was generated to publish and hand-written to preflight, so the
publish step skipped rewriting its stale ../../static links while preflight
went on reporting them.
"""

from pathlib import Path

import generated_paths as gp
import preflight_check as pf
import publish as pub


CONTENT = Path("/site/content")


# ─── the matcher itself ──────────────────────────────────────────────

def test_the_listed_files_match_at_their_own_path():
    assert gp.is_generated_relpath("benchmark.md")
    assert gp.is_generated_relpath("benchmark.zh.md")


def test_a_same_named_file_in_a_subdirectory_is_not_ours():
    """The list names content/benchmark.md, not every benchmark.md."""
    assert not gp.is_generated_relpath("posts/benchmark.md")
    assert not gp.is_generated_relpath("leetcode/benchmark.zh.md")


def test_listed_directories_match_themselves_and_their_contents():
    assert gp.is_generated_relpath("bugJournal/daily")
    assert gp.is_generated_relpath("bugJournal/daily/2026-06-13.md")
    assert gp.is_generated_relpath("research/some-project/paper.zh.md")


def test_a_prefix_that_is_not_a_path_boundary_does_not_match():
    assert not gp.is_generated_relpath("bugJournal/dailyish/x.md")
    assert not gp.is_generated_relpath("researchers/index.md")


def test_hand_written_content_is_left_alone():
    for rel in ("posts/hello.md", "About.pdf", "leetcode/1.md", "Resume.md"):
        assert not gp.is_generated_relpath(rel), rel


def test_a_path_outside_the_content_root_is_not_ours():
    assert not gp.is_generated_path(Path("/elsewhere/benchmark.md"), CONTENT)


# ─── and every consumer routes through it ────────────────────────────

def test_publish_and_preflight_agree_on_every_case():
    cases = [
        "benchmark.md", "benchmark.zh.md", "posts/benchmark.md",
        "bugJournal/daily/2026-06-13.md", "bugJournal/dailyish/x.md",
        "research/p/paper.md", "posts/hello.md", "Resume.md",
    ]
    disagreements = []
    for rel in cases:
        path = pub.SRC_DIR / rel
        if pub._is_generated(path) != pf._is_generated(path, pub.SRC_DIR):
            disagreements.append(rel)
    assert not disagreements, f"publish and preflight still disagree on {disagreements}"


def test_publish_no_longer_keeps_its_own_copy_of_the_lists():
    import inspect

    src = inspect.getsource(pub)
    assert "GENERATED_CONTENT_DIRS = (" not in src, (
        "publish.py redefines the path lists; they will drift again")


def test_both_consumers_call_the_shared_matcher():
    import inspect

    for mod, fn in ((pub, pub._is_generated), (pf, pf._is_generated)):
        assert "is_generated_path" in inspect.getsource(fn), (
            f"{mod.__name__}._is_generated has its own rule again")
