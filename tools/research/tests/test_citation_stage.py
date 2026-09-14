"""Stage 3 (citation impact) is part of the pipeline, with a gate and a cache.

I-027 describes a three-stage pipeline whose every round caches behind an
LLM-failure check. Two of the three did. Citation impact lived as an inline loop
in the CLI — outside evaluate_papers_for_project, with no cache entry and no
quality gate — which is how the most expensive round ended up the least
protected, and why cmd_citations grew a second copy of the same calls.

These pin the three properties the design claims: it runs inside the pipeline,
its result is gated before caching, and one dead paper does not lose the rest.
"""

from unittest.mock import patch

from research.scout import evaluate


PROJECT = {"id": "proj", "search_keywords": ["robots"], "open_questions": []}


def _papers(n):
    return [{"paper_id": f"p{i}", "arxiv_id": f"p{i}", "title": f"t{i}",
             "abstract": "a" * 50, "composite_score": 5.0 - i} for i in range(n)]


def _analysis(citations=7):
    return {"total_forward_citations": citations, "total_references": 3,
            "top_citing_papers": [], "top_references": [],
            "influence_analysis": "influential"}


# ─── the gate ────────────────────────────────────────────────────────

def test_empty_analyses_are_not_usable():
    assert evaluate._citation_is_usable({}) is False


def test_all_blank_analyses_are_not_usable():
    """Semantic Scholar down or the LLM read empty — do not freeze that in."""
    blank = {"p0": {"total_forward_citations": 0, "total_references": 0,
                    "influence_analysis": ""}}
    assert evaluate._citation_is_usable(blank) is False


def test_any_real_signal_is_usable():
    assert evaluate._citation_is_usable({"p0": _analysis()}) is True
    assert evaluate._citation_is_usable(
        {"p0": {"total_forward_citations": 0, "total_references": 0,
                "influence_analysis": "still says something"}}) is True


# ─── the stage ───────────────────────────────────────────────────────

def test_only_the_top_n_are_analysed():
    """Stage 2 sorts by composite_score descending, so the slice is the top N."""
    seen = []

    def fake(paper, **kw):
        seen.append(paper["paper_id"])
        return _analysis()

    with patch.object(evaluate, "analyze_citations", side_effect=fake), \
         patch.object(evaluate, "_load_eval_cache", return_value=None), \
         patch.object(evaluate, "_save_eval_cache"), \
         patch.object(evaluate, "load_scout_config", return_value={}):
        out = evaluate._run_citation_stage(PROJECT, _papers(9), "ollama", 60, False)

    assert seen == ["p0", "p1", "p2", "p3", "p4"]  # MAX_CITATION_ANALYSIS
    assert set(out) == set(seen)


def test_project_can_raise_the_cap():
    with patch.object(evaluate, "analyze_citations", return_value=_analysis()), \
         patch.object(evaluate, "_load_eval_cache", return_value=None), \
         patch.object(evaluate, "_save_eval_cache"), \
         patch.object(evaluate, "load_scout_config", return_value={}):
        out = evaluate._run_citation_stage(
            {**PROJECT, "max_citation_analysis": 2}, _papers(9), "ollama", 60, False)
    assert len(out) == 2


def test_one_failing_paper_does_not_lose_the_others():
    def flaky(paper, **kw):
        if paper["paper_id"] == "p1":
            raise RuntimeError("semantic scholar 503")
        return _analysis()

    with patch.object(evaluate, "analyze_citations", side_effect=flaky), \
         patch.object(evaluate, "_load_eval_cache", return_value=None), \
         patch.object(evaluate, "_save_eval_cache"), \
         patch.object(evaluate, "load_scout_config", return_value={}):
        out = evaluate._run_citation_stage(PROJECT, _papers(3), "ollama", 60, False)

    assert set(out) == {"p0", "p2"}


def test_blank_results_are_not_cached():
    blank = {"total_forward_citations": 0, "total_references": 0,
             "top_citing_papers": [], "top_references": [], "influence_analysis": ""}
    with patch.object(evaluate, "analyze_citations", return_value=blank), \
         patch.object(evaluate, "_load_eval_cache", return_value=None), \
         patch.object(evaluate, "_save_eval_cache") as save, \
         patch.object(evaluate, "load_scout_config", return_value={}):
        evaluate._run_citation_stage(PROJECT, _papers(2), "ollama", 60, True)
    save.assert_not_called()


def test_real_results_are_cached_and_reused():
    with patch.object(evaluate, "analyze_citations", return_value=_analysis()), \
         patch.object(evaluate, "_load_eval_cache", return_value=None), \
         patch.object(evaluate, "_save_eval_cache") as save, \
         patch.object(evaluate, "load_scout_config", return_value={}):
        evaluate._run_citation_stage(PROJECT, _papers(2), "ollama", 60, True)
    assert save.call_count == 1

    cached = {"analyses": {"p0": _analysis()}}
    with patch.object(evaluate, "analyze_citations",
                      side_effect=AssertionError("cache hit must not call S2")), \
         patch.object(evaluate, "_load_eval_cache", return_value=cached), \
         patch.object(evaluate, "load_scout_config", return_value={}):
        out = evaluate._run_citation_stage(PROJECT, _papers(2), "ollama", 60, True)
    assert out == cached["analyses"]


# ─── wired into the pipeline ─────────────────────────────────────────

def test_pipeline_attaches_citation_analysis():
    """The property that was missing: stage 3 runs without the CLI doing it."""
    papers = _papers(2)
    with patch.object(evaluate, "_screen_papers", return_value=[
             {**p, "screening_relevance": "high"} for p in papers]), \
         patch.object(evaluate, "_deep_evaluate_papers",
                      side_effect=lambda pj, hp, *a, **k: hp), \
         patch.object(evaluate, "_run_citation_stage",
                      return_value={"p0": _analysis(42)}) as stage3, \
         patch.object(evaluate, "_load_eval_cache", return_value=None), \
         patch.object(evaluate, "_save_eval_cache"):
        result = evaluate.evaluate_papers_for_project(
            PROJECT, papers, api="ollama", timeout=60, use_cache=False)

    assert stage3.call_count == 1
    high = {p["paper_id"]: p for p in result["high_relevance"]}
    assert high["p0"]["citation_analysis"]["total_forward_citations"] == 42
    assert "citation_analysis" not in high["p1"]
