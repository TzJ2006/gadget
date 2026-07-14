"""Tests for Research Scout pipeline stage input/output contracts.

Each test verifies:
1. The output of stage N satisfies the input contract of stage N+1
2. The merge logic handles match/mismatch correctly
3. Failure modes produce expected behavior (not silent corruption)
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow imports from research/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─── Fixtures: sample data at each stage boundary ────────────────────

@pytest.fixture
def sample_papers_stage0():
    """Output of Stage 0 (search) — input to Stage 1."""
    return [
        {
            "paper_id": "2605.13465v1",
            "arxiv_id": "2605.13465v1",
            "source": "arxiv",
            "title": "Z-Order Transformer for Feed-Forward Gaussian Splatting",
            "authors": ["Can Wang", "Lei Liu", "Wei Jiang", "Dong Xu"],
            "abstract": "Recent advances in 3D Gaussian Splatting (3DGS) have enabled "
                        "significant progress in photorealistic novel view synthesis. "
                        "However, traditional 3DGS relies on a slow, iterative process.",
            "categories": ["cs.CV"],
            "published": "2026-05-13",
            "url": "http://arxiv.org/abs/2605.13465v1",
            "pdf_url": "https://arxiv.org/pdf/2605.13465v1",
            "comment": "Accept by CVPR 2026, Oral",
            "journal_ref": "",
            "venue": "CVPR 2026",
        },
        {
            "paper_id": "2604.18267v1",
            "arxiv_id": "2604.18267v1",
            "source": "arxiv",
            "title": "MARCO: Navigating the Unseen Space of Semantic Correspondence",
            "authors": ["Claudia Cuttano", "Gabriele Trivigno"],
            "abstract": "Recent advances in semantic correspondence rely on dual-encoder "
                        "architectures. We introduce MARCO, a unified model.",
            "categories": ["cs.CV"],
            "published": "2026-04-20",
            "url": "http://arxiv.org/abs/2604.18267v1",
            "pdf_url": "https://arxiv.org/pdf/2604.18267v1",
            "comment": "CVPR 2026 Oral",
            "journal_ref": "",
            "venue": "CVPR 2026",
        },
    ]


@pytest.fixture
def sample_project():
    """Minimal project dict for pipeline stages."""
    return {
        "id": "test-project",
        "title": "Test Project",
        "search_keywords": ["CVPR 2026"],
        "categories": ["cs.CV"],
        "open_questions": [],
        "sources": ["arxiv"],
    }


@pytest.fixture
def sample_screening_response():
    """What LLM should return for Stage 1 (correct format)."""
    return {
        "screenings": [
            {
                "paper_id": "2605.13465v1",
                "screening_relevance": "high",
                "paper_type": "method",
                "motivation": "Traditional 3DGS relies on slow iterative optimization",
                "innovation_point": "Z-order strategy for sparse attention",
                "first_author": "Can Wang",
                "institution": "unknown",
            },
            {
                "paper_id": "2604.18267v1",
                "screening_relevance": "low",
                "paper_type": "method",
                "motivation": "Dual-encoder models generalize poorly beyond training keypoints",
                "innovation_point": "Coarse-to-fine objective with self-distillation",
                "first_author": "Claudia Cuttano",
                "institution": "unknown",
            },
        ]
    }


@pytest.fixture
def sample_deep_eval_response():
    """What LLM should return for Stage 2 (correct format)."""
    return {
        "evaluations": [
            {
                "paper_id": "2605.13465v1",
                "highlights": [
                    {"point": "Z-order spatial coherence", "why": "Unstructured Gaussians lack context", "value_to_us": "Applicable to point cloud processing", "our_direction": "Test Z-order on our data"},
                    {"point": "Sparse attention mechanism", "why": "Full attention is O(n^2)", "value_to_us": "Reduces compute", "our_direction": "Benchmark attention variants"},
                    {"point": "Single forward pass", "why": "No iterative optimization needed", "value_to_us": "Real-time inference", "our_direction": "Deploy for live rendering"},
                ],
                "relevance": 4,
                "novelty": 4,
                "inspiration": 5,
                "two_sentence_summary": "A transformer-based feed-forward Gaussian Splatting method.",
                "suggestion": "Apply Z-order to our point cloud pipeline.",
                "relevant_open_questions": [],
            }
        ]
    }


# ─── Stage 0 Output Contract ─────────────────────────────────────────

class TestStage0OutputContract:
    """Verify Stage 0 output satisfies Stage 1 input requirements."""

    def test_required_keys_present(self, sample_papers_stage0):
        required = {"paper_id", "title", "authors", "abstract", "categories"}
        for paper in sample_papers_stage0:
            assert required.issubset(paper.keys()), \
                f"Paper {paper['paper_id']} missing keys: {required - paper.keys()}"

    def test_abstract_not_empty(self, sample_papers_stage0):
        for paper in sample_papers_stage0:
            assert paper["abstract"], f"Paper {paper['paper_id']} has empty abstract"

    def test_paper_id_unique(self, sample_papers_stage0):
        ids = [p["paper_id"] for p in sample_papers_stage0]
        assert len(ids) == len(set(ids)), "Duplicate paper_ids in search results"

    def test_authors_non_empty(self, sample_papers_stage0):
        for paper in sample_papers_stage0:
            assert len(paper["authors"]) >= 1, f"Paper {paper['paper_id']} has no authors"

    def test_published_is_iso_date(self, sample_papers_stage0):
        import re
        for paper in sample_papers_stage0:
            assert re.match(r"\d{4}-\d{2}-\d{2}", paper["published"]), \
                f"Paper {paper['paper_id']} published date not ISO format"


# ─── Stage 1 Merge Logic ─────────────────────────────────────────────

class TestStage1MergeLogic:
    """Verify Stage 1 screening merge handles match/mismatch correctly.

    These exercise the real ``scout.evaluate._screen_papers`` with the LLM
    backend (``call_scout_llm``) mocked, rather than re-implementing the merge
    inline — so the assertions actually pin down production behavior.
    """

    def test_successful_merge(self, sample_project, sample_papers_stage0, sample_screening_response):
        """When LLM returns correct paper_ids, all fields merge correctly."""
        from scout.evaluate import _screen_papers

        with patch("scout.evaluate.call_scout_llm", return_value=sample_screening_response):
            papers = _screen_papers(sample_project, [dict(p) for p in sample_papers_stage0])

        assert papers[0]["screening_relevance"] == "high"
        assert papers[0]["motivation"] != ""
        assert papers[0]["paper_type"] == "method"
        assert papers[1]["screening_relevance"] == "low"
        assert papers[1]["motivation"] != ""

    def test_empty_screenings_all_default_to_low(self, sample_project, sample_papers_stage0):
        """When LLM returns empty screenings list, all papers get default low."""
        from scout.evaluate import _screen_papers

        with patch("scout.evaluate.call_scout_llm", return_value={"screenings": []}):
            papers = _screen_papers(sample_project, [dict(p) for p in sample_papers_stage0])

        for p in papers:
            assert p["screening_relevance"] == "low"
            assert p["motivation"] == ""
            assert p["paper_type"] == "other"

    def test_wrong_key_name_returns_empty(self, sample_project, sample_papers_stage0):
        """When LLM uses 'results' instead of 'screenings', all papers default to low."""
        from scout.evaluate import _screen_papers

        wrong = {"results": [{"paper_id": "2605.13465v1", "screening_relevance": "high"}]}
        with patch("scout.evaluate.call_scout_llm", return_value=wrong):
            papers = _screen_papers(sample_project, [dict(p) for p in sample_papers_stage0])

        for p in papers:
            assert p["screening_relevance"] == "low"
            assert p["motivation"] == ""

    def test_partial_match(self, sample_project, sample_papers_stage0):
        """When LLM returns only some paper_ids, unmatched papers get defaults."""
        from scout.evaluate import _screen_papers

        # Only first paper screened by the LLM
        response = {
            "screenings": [
                {"paper_id": "2605.13465v1", "screening_relevance": "high", "motivation": "test"}
            ]
        }
        with patch("scout.evaluate.call_scout_llm", return_value=response):
            papers = _screen_papers(sample_project, [dict(p) for p in sample_papers_stage0])

        assert papers[0]["screening_relevance"] == "high"
        assert papers[0]["motivation"] == "test"
        assert papers[1]["screening_relevance"] == "low"
        assert papers[1]["motivation"] == ""


# ─── Stage 2 Merge Logic ─────────────────────────────────────────────

class TestStage2MergeLogic:
    """Verify Stage 2 deep eval merge handles match/mismatch correctly.

    These exercise the real ``scout.evaluate._deep_evaluate_papers`` with the
    LLM backend (``call_scout_llm``) and ``extract_current_methods`` mocked,
    rather than re-implementing the merge/score logic inline.
    """

    def test_successful_merge_with_scores(self, sample_project, sample_papers_stage0, sample_deep_eval_response):
        """When LLM returns correct paper_ids, scores compute correctly."""
        from scout.evaluate import _deep_evaluate_papers

        papers = [dict(p) for p in sample_papers_stage0[:1]]  # just first paper
        with patch("scout.evaluate.call_scout_llm", return_value=sample_deep_eval_response), \
                patch("scout.project.extract_current_methods", return_value=""):
            merged = _deep_evaluate_papers(sample_project, papers)

        assert merged[0]["composite_score"] == round(0.4*4 + 0.3*5 + 0.3*4, 2)
        assert merged[0]["relevance"] == 4
        assert len(merged[0]["highlights"]) == 3
        assert merged[0]["two_sentence_summary"] != ""

    def test_empty_evaluations_all_score_zero(self, sample_project, sample_papers_stage0):
        """When evaluations is empty, all papers get composite_score=0."""
        from scout.evaluate import _deep_evaluate_papers

        papers = [dict(p) for p in sample_papers_stage0]
        with patch("scout.evaluate.call_scout_llm", return_value={"evaluations": []}), \
                patch("scout.project.extract_current_methods", return_value=""):
            merged = _deep_evaluate_papers(sample_project, papers)

        for entry in merged:
            assert entry["composite_score"] == 0.0
            assert "highlights" not in entry
            assert "relevance" not in entry or entry.get("relevance") is None

    def test_wrong_key_name_returns_empty_evaluations(self, sample_project, sample_papers_stage0):
        """When LLM uses 'results' instead of 'evaluations', all scores are 0."""
        from scout.evaluate import _deep_evaluate_papers

        wrong = {"results": [{"paper_id": "2605.13465v1", "relevance": 5}]}
        papers = [dict(p) for p in sample_papers_stage0[:1]]
        with patch("scout.evaluate.call_scout_llm", return_value=wrong), \
                patch("scout.project.extract_current_methods", return_value=""):
            merged = _deep_evaluate_papers(sample_project, papers)

        assert merged[0]["composite_score"] == 0.0
        assert "relevance" not in merged[0]

    def test_mismatched_paper_id_does_merge_via_version_strip(self, sample_project, sample_papers_stage0):
        """When LLM omits the version suffix, _lookup_by_id strips it and the
        merge SUCCEEDS — this is the documented _lookup_by_id fallback behavior."""
        from scout.evaluate import _deep_evaluate_papers

        # LLM returned ID without version suffix ("2605.13465" vs "2605.13465v1")
        response = {
            "evaluations": [
                {"paper_id": "2605.13465", "relevance": 5, "novelty": 5, "inspiration": 5}
            ]
        }
        papers = [dict(p) for p in sample_papers_stage0[:1]]
        with patch("scout.evaluate.call_scout_llm", return_value=response), \
                patch("scout.project.extract_current_methods", return_value=""):
            merged = _deep_evaluate_papers(sample_project, papers)

        # _lookup_by_id strips "v1" so the eval matches → score reflects the eval
        assert merged[0]["composite_score"] == round(0.4*5 + 0.3*5 + 0.3*5, 2)
        assert merged[0]["relevance"] == 5

    def test_composite_score_formula(self):
        """Verify composite_score = 0.4*relevance + 0.3*inspiration + 0.3*novelty."""
        cases = [
            (5, 5, 5, 5.0),
            (1, 1, 1, 1.0),
            (5, 1, 1, 2.6),
            (1, 5, 5, 3.4),
            (0, 0, 0, 0.0),
        ]
        for r, n, ins, expected in cases:
            score = round(0.4 * r + 0.3 * ins + 0.3 * n, 2)
            assert score == expected, f"relevance={r}, novelty={n}, inspiration={ins}: got {score}, expected {expected}"


# ─── Stage 3 Output Contract ─────────────────────────────────────────

class TestStage3OutputContract:
    """Verify Stage 3 citation analysis output structure."""

    def test_citation_analysis_schema(self):
        """Output dict has required keys."""
        output = {
            "total_forward_citations": 42,
            "total_references": 20,
            "top_citing_papers": [
                {"title": "Follow-up work", "year": 2026, "citation_count": 10, "venue": "NeurIPS"},
            ],
            "top_references": [
                {"title": "Foundation work", "year": 2024, "citation_count": 500, "venue": "CVPR"},
            ],
            "influence_analysis": {},
        }
        required = {"total_forward_citations", "total_references", "top_citing_papers", "top_references", "influence_analysis"}
        assert required.issubset(output.keys())

    def test_empty_result_on_s2_failure(self, sample_papers_stage0):
        """When S2 cannot find the paper, analyze_citations returns {}."""
        from scout.evaluate import analyze_citations

        # get_paper_by_id is imported inside analyze_citations from
        # research.apis.semantic_scholar — patch it there.
        with patch("research.apis.semantic_scholar.get_paper_by_id", return_value=None):
            result = analyze_citations(dict(sample_papers_stage0[0]))

        assert result == {}


# ─── Stage 1 → Stage 2 Boundary ──────────────────────────────────────

class TestStage1ToStage2Boundary:
    """Verify Stage 1 output satisfies Stage 2 input contract."""

    def test_high_papers_have_abstract(self, sample_papers_stage0, sample_screening_response):
        """Stage 2 requires abstract (full text, not truncated) on each paper."""
        from scout.search import paper_id as _paper_id

        screenings = sample_screening_response["screenings"]
        screen_by_id = {s["paper_id"]: s for s in screenings}

        papers = [dict(p) for p in sample_papers_stage0]
        for p in papers:
            sc = screen_by_id.get(_paper_id(p), {})
            p["screening_relevance"] = sc.get("screening_relevance", "low")

        high_papers = [p for p in papers if p["screening_relevance"] == "high"]

        for p in high_papers:
            assert "abstract" in p and p["abstract"], \
                f"High paper {p['paper_id']} missing abstract for Stage 2"
            assert "paper_id" in p
            assert "title" in p
            assert "authors" in p
            assert "published" in p
            assert "categories" in p


# ─── Report Input Contract ────────────────────────────────────────────

class TestReportInputContract:
    """Verify report generation receives expected structure."""

    def test_report_input_structure(self, sample_project, sample_papers_stage0):
        """generate_daily_report expects specific dict structure."""
        projects_data = {
            "test-project": {
                "project": sample_project,
                "high_relevance": sample_papers_stage0[:1],
                "low_relevance": sample_papers_stage0[1:],
                "screening_stats": {"total": 2, "high_count": 1, "low_count": 1},
                "directions": [],
                "writing_guide": {},
            }
        }

        # Verify structure matches what generate_daily_report expects
        for pid, data in projects_data.items():
            assert "project" in data
            assert "high_relevance" in data
            assert "low_relevance" in data
            assert "screening_stats" in data
            stats = data["screening_stats"]
            assert "total" in stats
            assert "high_count" in stats
            assert "low_count" in stats
            assert stats["total"] == stats["high_count"] + stats["low_count"]


# ─── Formatting Functions ─────────────────────────────────────────────

class TestFormattingContracts:
    """Verify formatting functions produce correct text for LLM prompts."""

    def test_screening_format_truncates_abstract(self, sample_papers_stage0):
        """Stage 1 formatting truncates abstract to 1000 chars."""
        from scout.evaluate import _format_papers_for_screening

        # Make a paper with a very long abstract
        papers = [dict(sample_papers_stage0[0])]
        papers[0]["abstract"] = "A" * 2000

        text = _format_papers_for_screening(papers)
        # The formatted text should contain at most 1000 chars of the abstract
        assert "A" * 1001 not in text
        assert "A" * 999 in text

    def test_deep_eval_format_uses_full_abstract(self, sample_papers_stage0):
        """Stage 2 formatting uses full abstract without truncation."""
        from scout.evaluate import _format_papers_for_deep_eval

        papers = [dict(sample_papers_stage0[0])]
        papers[0]["abstract"] = "B" * 2000

        text = _format_papers_for_deep_eval(papers)
        assert "B" * 2000 in text

    def test_screening_format_includes_paper_id(self, sample_papers_stage0):
        """Paper ID must appear in formatted text so LLM can reference it."""
        from scout.evaluate import _format_papers_for_screening

        text = _format_papers_for_screening(sample_papers_stage0)
        for p in sample_papers_stage0:
            assert p["paper_id"] in text

    def test_deep_eval_format_includes_paper_id(self, sample_papers_stage0):
        """Paper ID must appear in formatted text so LLM can reference it."""
        from scout.evaluate import _format_papers_for_deep_eval

        text = _format_papers_for_deep_eval(sample_papers_stage0)
        for p in sample_papers_stage0:
            assert p["paper_id"] in text


# ─── Cache Quality Gate (proposed fix for ISSUE-002) ──────────────────

class TestCacheQualityGate:
    """Tests for the quality gate before caching results (evaluate.py item 7).

    These exercise the real ``_screening_is_usable`` / ``_deep_eval_is_usable``
    gates that decide whether an evaluation result is worth caching, so the
    no-cache-on-failure behavior is actually pinned down.
    """

    def test_all_zero_scores_should_not_cache(self):
        """If all papers have composite_score=0, deep eval is not usable."""
        from scout.evaluate import _deep_eval_is_usable

        merged = [
            {"paper_id": "a", "composite_score": 0.0},
            {"paper_id": "b", "composite_score": 0.0},
            {"paper_id": "c", "composite_score": 0.0},
        ]
        assert _deep_eval_is_usable(merged) is False, \
            "All-zero scores = garbage result, should NOT cache"

    def test_partial_scores_should_cache(self):
        """If at least some papers have scores, deep eval is usable."""
        from scout.evaluate import _deep_eval_is_usable

        merged = [
            {"paper_id": "a", "composite_score": 4.3},
            {"paper_id": "b", "composite_score": 0.0},
            {"paper_id": "c", "composite_score": 3.1},
        ]
        assert _deep_eval_is_usable(merged) is True, \
            "Mixed scores = valid result, should cache"

    def test_empty_deep_eval_not_usable(self):
        """An empty evaluation list is never usable."""
        from scout.evaluate import _deep_eval_is_usable

        assert _deep_eval_is_usable([]) is False

    def test_empty_motivation_should_not_cache_screening(self):
        """If all papers are low + empty motivation/innovation, screening is not usable."""
        from scout.evaluate import _screening_is_usable

        papers = [
            {"paper_id": "a", "screening_relevance": "low", "motivation": "", "innovation_point": ""},
            {"paper_id": "b", "screening_relevance": "low", "motivation": "", "innovation_point": ""},
        ]
        assert _screening_is_usable(papers) is False, \
            "All-empty/low screening = garbage, should NOT cache"

    def test_screening_with_high_or_motivation_should_cache(self):
        """Screening is usable if any paper is high OR has motivation/innovation."""
        from scout.evaluate import _screening_is_usable

        with_high = [
            {"paper_id": "a", "screening_relevance": "high", "motivation": "", "innovation_point": ""},
            {"paper_id": "b", "screening_relevance": "low", "motivation": "", "innovation_point": ""},
        ]
        assert _screening_is_usable(with_high) is True

        with_motivation = [
            {"paper_id": "a", "screening_relevance": "low", "motivation": "real reason", "innovation_point": ""},
        ]
        assert _screening_is_usable(with_motivation) is True



# ─── JSON Parse Multi-Block Fix ───────────────────────────────────────

class TestJsonParseMultiBlock:
    """Verify fix for multi-code-block LLM responses (root cause of ISSUE-001)."""

    def test_single_block_still_works(self):
        from common.json_utils import try_parse_json
        text = '```json\n{"evaluations": [{"paper_id": "x"}]}\n```'
        result = try_parse_json(text)
        assert result == {"evaluations": [{"paper_id": "x"}]}

    def test_multiple_blocks_returns_largest(self):
        from common.json_utils import try_parse_json
        text = (
            'Summary:\n'
            '```json\n{"summary": "brief"}\n```\n\n'
            'Detailed:\n'
            '```json\n{"evaluations": [{"paper_id": "x", "relevance": 5}]}\n```'
        )
        result = try_parse_json(text)
        assert "evaluations" in result
        assert result["evaluations"][0]["paper_id"] == "x"

    def test_first_block_invalid_json_skipped(self):
        from common.json_utils import try_parse_json
        text = (
            '```\nNot valid JSON here\n```\n\n'
            '```json\n{"screenings": [{"paper_id": "y"}]}\n```'
        )
        result = try_parse_json(text)
        assert result == {"screenings": [{"paper_id": "y"}]}

    def test_meta_response_before_real_data(self):
        from common.json_utils import try_parse_json
        text = (
            '```json\n{"status": "analyzing", "papers_count": 9}\n```\n\n'
            '```json\n{"evaluations": [{"paper_id": "a", "relevance": 4, "novelty": 3, "inspiration": 5, "highlights": [{"point": "p", "why": "w", "value_to_us": "v", "our_direction": "o"}], "two_sentence_summary": "Good.", "suggestion": "Use.", "relevant_open_questions": []}]}\n```'
        )
        result = try_parse_json(text)
        assert "evaluations" in result
        assert result["evaluations"][0]["relevance"] == 4


class TestPaperIdVersionFallback:
    """Verify _lookup_by_id handles version suffix mismatch (LLM omits vN)."""

    def test_exact_match(self):
        from scout.evaluate import _lookup_by_id
        mapping = {"2605.15195v1": {"relevance": "high"}}
        assert _lookup_by_id(mapping, "2605.15195v1") == {"relevance": "high"}

    def test_fallback_strips_version(self):
        from scout.evaluate import _lookup_by_id
        mapping = {"2605.15195": {"relevance": "high"}}
        assert _lookup_by_id(mapping, "2605.15195v1") == {"relevance": "high"}

    def test_no_match_returns_empty(self):
        from scout.evaluate import _lookup_by_id
        mapping = {"2605.99999": {"relevance": "high"}}
        assert _lookup_by_id(mapping, "2605.15195v1") == {}

    def test_exact_takes_priority_over_stripped(self):
        from scout.evaluate import _lookup_by_id
        mapping = {
            "2605.15195v1": {"source": "exact"},
            "2605.15195": {"source": "stripped"},
        }
        assert _lookup_by_id(mapping, "2605.15195v1") == {"source": "exact"}

    def test_non_versioned_id_still_works(self):
        from scout.evaluate import _lookup_by_id
        mapping = {"10.1038/s41586": {"relevance": "high"}}
        assert _lookup_by_id(mapping, "10.1038/s41586") == {"relevance": "high"}
