"""`citations` prints the shared stage's result instead of redoing its work.

cmd_citations used to re-implement stage 3 end to end -- resolve on S2, fetch
both directions, rank, prompt, repair -- because the pipeline function did not
call analyze_citations either (fixed in 05cfb7d). With the stage back in the
pipeline the duplicate had no reason left to exist, and two copies of a
citation gate is how the two drift apart.

These pin the merge: the command calls the shared function, it does not fetch
edges itself, and the output it is documented to produce is unchanged.
"""

import ast
import inspect
from unittest.mock import patch

import pytest

from research.scout import cli, evaluate


# ─── the duplicate is gone ───────────────────────────────────────────

def _called_names(func):
    tree = ast.parse(inspect.getsource(func))
    return {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            for n in ast.walk(tree) if isinstance(n, ast.Call)}


def test_the_command_delegates_to_the_shared_stage():
    assert "analyze_citations" in _called_names(cli.cmd_citations)


def test_the_command_no_longer_walks_the_graph_itself():
    """Every one of these was a line-for-line copy of analyze_citations."""
    names = _called_names(cli.cmd_citations)
    for redone in ("get_paper_citations", "get_paper_references",
                   "call_scout_llm", "_try_repair_result", "format"):
        assert redone not in names, f"cmd_citations still does {redone} itself"


def test_the_five_citation_gate_is_declared_once():
    """cli.py:550 and evaluate.py:421 held the same predicate."""
    src = inspect.getsource(evaluate.analyze_citations)
    assert "total_citations >= 5" in src
    # the CLI may still *read* the count to explain a missing analysis, but it
    # must not re-run the LLM behind its own copy of the gate.
    assert "call_scout_llm" not in inspect.getsource(cli.cmd_citations)


# ─── behaviour the merge had to preserve ─────────────────────────────

_S2 = {"paperId": "abc", "title": "A Paper", "citationCount": 40,
       "abstract": "an abstract", "referenceCount": 3}
_EDGES = [{"title": f"Citing {i}", "year": 2020 + i,
           "citationCount": 100 - i, "venue": "NeurIPS"} for i in range(3)]


def _run_stage(**kw):
    with patch("research.apis.semantic_scholar.get_paper_by_id", return_value=_S2), \
         patch("research.apis.semantic_scholar.get_paper_citations", return_value=_EDGES), \
         patch("research.apis.semantic_scholar.get_paper_references", return_value=_EDGES), \
         patch.object(evaluate, "call_scout_llm", return_value={"popularity_reason": "x"}), \
         patch.object(evaluate, "_try_repair_result", side_effect=lambda r, *a: r):
        return evaluate.analyze_citations({"paper_id": "abc"}, **kw)


def test_top_n_is_honoured_so_the_documented_flag_still_works():
    """--top-n N is documented as showing N rows."""
    assert len(_run_stage(top_n=2)["top_citing_papers"]) == 2
    assert len(_run_stage(top_n=10)["top_citing_papers"]) == 3   # only 3 exist


def test_fetch_limit_and_top_n_are_separate_on_purpose():
    """S2 returns edges unordered; ranking happens locally.

    Collapsing them into one number would make the pipeline fetch only as many
    as it keeps, which changes *which* papers it keeps.
    """
    seen = {}

    def spy(pid, limit=50, **kw):
        seen["limit"] = limit
        return _EDGES

    with patch("research.apis.semantic_scholar.get_paper_by_id", return_value=_S2), \
         patch("research.apis.semantic_scholar.get_paper_citations", side_effect=spy), \
         patch("research.apis.semantic_scholar.get_paper_references", return_value=[]), \
         patch.object(evaluate, "call_scout_llm", return_value={}), \
         patch.object(evaluate, "_try_repair_result", side_effect=lambda r, *a: r):
        evaluate.analyze_citations({"paper_id": "abc"})          # pipeline defaults
    assert seen["limit"] == 20, "the pipeline must still fetch wider than it keeps"

    sig = inspect.signature(evaluate.analyze_citations)
    assert sig.parameters["fetch_limit"].default == 20
    assert sig.parameters["top_n"].default == 10


def test_the_title_travels_with_the_result():
    """So the CLI needs no second get_paper_by_id for its header line."""
    assert _run_stage()["title"] == "A Paper"


def test_a_caller_with_only_an_id_still_gets_a_full_prompt():
    """The CLI passes {"paper_id": ...} and nothing else."""
    captured = {}

    def spy(api, prompt, timeout):
        captured["prompt"] = prompt
        return {}

    with patch("research.apis.semantic_scholar.get_paper_by_id", return_value=_S2), \
         patch("research.apis.semantic_scholar.get_paper_citations", return_value=_EDGES), \
         patch("research.apis.semantic_scholar.get_paper_references", return_value=[]), \
         patch.object(evaluate, "call_scout_llm", side_effect=spy), \
         patch.object(evaluate, "_try_repair_result", side_effect=lambda r, *a: r):
        evaluate.analyze_citations({"paper_id": "abc"})
    assert "A Paper" in captured["prompt"], "title fell back to nothing"
    assert "an abstract" in captured["prompt"], "abstract fell back to nothing"


def test_a_missing_paper_gives_the_command_something_to_exit_on():
    with patch("research.apis.semantic_scholar.get_paper_by_id", return_value=None):
        assert evaluate.analyze_citations({"paper_id": "nope"}) == {}


# ─── the S2 twins ────────────────────────────────────────────────────

def test_citation_and_reference_fetchers_share_one_body():
    from research.apis import semantic_scholar as s2

    for fn in (s2.get_paper_citations, s2.get_paper_references):
        assert "_get_paper_edge" in inspect.getsource(fn), (
            f"{fn.__name__} is still a copy of its twin")


def test_the_merged_fetcher_keeps_each_cache_key():
    """Cache keys must not change, or every cached entry is orphaned."""
    from research.apis import semantic_scholar as s2

    keys = []

    class FakeCache:
        def get(self, ns, key, ttl_seconds=None):
            keys.append(key)
            return []

        def put(self, *a):
            pass

    s2.get_paper_citations("abc", limit=20, cache=FakeCache())
    s2.get_paper_references("abc", limit=20, cache=FakeCache())
    assert keys == ["s2_citations:abc:20", "s2_references:abc:20"]
