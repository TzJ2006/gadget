"""LLM prompt templates for Research Scout evaluation pipeline."""

from __future__ import annotations

# ─── Language instructions ───────────────────────────────────────────

_LANGUAGE_INSTRUCTIONS = {
    "zh": "IMPORTANT: All descriptive text fields in your response (motivation, innovation_point, highlights, two_sentence_summary, suggestion, description, etc.) MUST be written in Chinese (中文). JSON keys remain in English.",
    "en": "IMPORTANT: All descriptive text fields in your response MUST be written in English.",
}


def language_instruction(lang: str) -> str:
    """Return a language instruction suffix to append to LLM prompts."""
    if lang in _LANGUAGE_INSTRUCTIONS:
        return "\n\n" + _LANGUAGE_INSTRUCTIONS[lang]
    return f"\n\nIMPORTANT: All descriptive text fields in your response MUST be written in {lang}. JSON keys remain in English."


# ─── Stage 1: Quick Screening ───────────────────────────────────────

SCREENING_PROMPT = """You are a research paper screening assistant. Given a research project context and a list of papers, quickly classify each paper's relevance to the project.

## Project Context
Title: {title}
Keywords: {keywords}
Open Questions: {open_questions}

## Instructions
For each paper, provide a quick screening:
- screening_relevance: "high" or "low" — Is this paper highly relevant to our project?
- paper_type: One of "method", "system", "benchmark", "survey", "theory", "application", "dataset", "other"
- motivation: One sentence describing why this paper exists (what problem it solves)
- innovation_point: One sentence describing the key innovation
- first_author: The first author's name
- institution: The first author's institution/affiliation (best-effort from author names/emails, "unknown" if not identifiable)

Important guidelines:
- Be selective: typically only 20-40% of papers should be marked "high" relevance
- "high" means directly related to our research goals or provides immediately useful techniques
- "low" means tangentially related, different domain, or not actionable for our project

Return JSON:
```json
{{
    "screenings": [
        {{
            "paper_id": "2503.12345",
            "screening_relevance": "high",
            "paper_type": "method",
            "motivation": "...",
            "innovation_point": "...",
            "first_author": "...",
            "institution": "..."
        }}
    ]
}}
```

Only return JSON, no other text.
{language_instruction}
## Papers to Screen
{papers_text}
"""

# ─── Stage 2: Deep Evaluation ───────────────────────────────────────

DEEP_EVAL_PROMPT = """You are a thorough research paper analyst. Given a research project context (including current methods) and a set of HIGH-RELEVANCE papers, provide deep analysis for each.

## Project Context
Title: {title}
Keywords: {keywords}
Open Questions: {open_questions}

## Current Methods & Progress
{current_methods}

## Instructions
For each paper, provide:
1. **highlights**: Exactly 3 key highlights, each with:
   - point: What is the key highlight / advantage (the key advantage/improvement)
   - why: Why did the authors think this way / design motivation (design motivation/intuition)
   - value_to_us: How this is valuable to our research (value to our research)
   - our_direction: Concrete action suggestion for us (our action suggestion)
2. **relevance** (1-5): How relevant to our project
3. **novelty** (1-5): How novel is the approach
4. **inspiration** (1-5): How likely to inspire new ideas
5. **two_sentence_summary**: Brief summary in English
6. **suggestion**: One concrete suggestion for how this could inform our project (English)
7. **relevant_open_questions**: Which project open questions this addresses (list)

Return JSON:
```json
{{
    "evaluations": [
        {{
            "paper_id": "2503.12345",
            "highlights": [
                {{
                    "point": "...",
                    "why": "...",
                    "value_to_us": "...",
                    "our_direction": "..."
                }},
                {{
                    "point": "...",
                    "why": "...",
                    "value_to_us": "...",
                    "our_direction": "..."
                }},
                {{
                    "point": "...",
                    "why": "...",
                    "value_to_us": "...",
                    "our_direction": "..."
                }}
            ],
            "relevance": 4,
            "novelty": 3,
            "inspiration": 5,
            "two_sentence_summary": "...",
            "suggestion": "...",
            "relevant_open_questions": ["question1"]
        }}
    ]
}}
```

Only return JSON, no other text.
{language_instruction}
## Papers to Analyze
{papers_text}
"""

# ─── Direction Suggestion ───────────────────────────────────────────

DIRECTION_SUGGESTION_PROMPT = """You are a research direction analysis assistant. Based on the following project context and recent high-scoring papers, suggest 2-3 new research directions.

## Project Context
Title: {title}
Keywords: {keywords}
Open Questions: {open_questions}

## Recent High-Scoring Papers
{top_papers_text}

## Requirements
1. Describe each direction in English
2. Each suggestion should be specific and actionable, not vague
3. Explain which papers are related to the direction
4. Explain which open question of the project the direction addresses

Return JSON:
```json
{{
    "directions": [
        {{
            "title": "Direction title",
            "description": "Detailed description (2-3 sentences)",
            "related_papers": ["2503.12345"],
            "addresses_questions": ["question1"],
            "feasibility": "high | medium | low"
        }}
    ]
}}
```

Return JSON only, no additional text.
{language_instruction}
"""

# ─── Overview extraction (used by create_project_from_overview) ─────

OVERVIEW_EXTRACT_PROMPT = """Extract project information from the following overview.md and return JSON:
- title: Project title
- search_keywords: List of English keywords for arXiv search (5-10)
- arxiv_categories: List of relevant arXiv categories (e.g., cs.RO, cs.LG)
- open_questions: List of open questions (preserve original language)

Return JSON only, no additional text.

```json
{{
    "title": "...",
    "search_keywords": ["kw1", "kw2"],
    "arxiv_categories": ["cs.RO"],
    "open_questions": ["question1"]
}}
```

## overview.md Content

{overview_content}
"""

# ─── Ask intent parsing (used by cmd_ask) ──────────────────────────

ASK_INTENT_PROMPT = """Analyze the following natural language research query and extract search parameters. Return JSON:

```json
{{
    "title": "Short project title (English, 3-6 words)",
    "search_mode": "topic | author | conference | journal | mixed",
    "search_keywords": ["keyword1", "keyword2", ...],
    "arxiv_categories": ["cs.RO", "cs.LG", ...],
    "sources": ["arxiv"],
    "author": "Author full name (only for author/mixed mode, otherwise empty string)",
    "conference": "Conference name + year (only for conference/mixed mode, otherwise empty string)",
    "pubmed_journals": ["journal name", ...],
    "biorxiv_categories": ["category", ...],
    "lookback_days": 30,
    "overview_summary": "Write a 2-3 sentence research direction description in English for downstream paper evaluation context",
    "open_questions": ["open question 1", "open question 2"]
}}
```

## Rules

1. **search_mode selection**:
   - "topic": Search by keywords + field (default)
   - "author": Search by author (requires author field)
   - "conference": Search by conference (requires conference field)
   - "journal": Search by journal (requires pubmed_journals field)
   - "mixed": Combination of multiple modes (e.g., "author + field", fill in relevant fields)

2. **search_keywords**: Must be in English, 5-10 keywords, covering core concepts and synonyms

3. **arxiv_categories**: Must be valid arXiv categories (e.g., cs.RO, cs.LG, cs.CV, cs.AI, cs.CL, q-bio.BM, stat.ML)

4. **sources selection**:
   - CS/ML/AI domain → ["arxiv"]
   - Biomedical/clinical → ["pubmed"] or ["arxiv", "pubmed"]
   - Biology preprints → ["biorxiv"] or ["arxiv", "biorxiv"]
   - Uncertain → ["arxiv"]

5. **lookback_days**: Default 30, "recent" → 7, "this year" → 180, adjust according to user-specified timeframe

6. **overview_summary**: Write a 2-3 sentence research direction description in English to help evaluate paper relevance downstream

Return JSON only, no additional text.

## User Input

{query}
"""

# ─── Stage 4: Insight Analysis (full text) ─────────────────────────

INSIGHT_ANALYSIS_PROMPT = """You are a research paper analyst helping a researcher understand paper writing patterns, publication strategies, and extractable knowledge.

Given a paper's title, abstract, and full text, analyze three dimensions:

## Paper
Title: {title}
Abstract: {abstract}

## Full Text (truncated)
{fulltext}

## Instructions

Analyze this paper across three dimensions and return structured JSON:

1. **writing_structure**: How the paper is written
   - narrative_flow: The paper's argumentation arc (e.g., "Problem → Gap → Method → Theory → Experiments → Ablation → Discussion")
   - section_pattern: Ordered list of section names/types (e.g., ["Introduction", "Related Work", "Method", "Experiments", "Conclusion"])
   - argument_style: How the paper makes its case (e.g., "empirically-driven with extensive ablations", "theoretically-motivated with formal proofs")

2. **publishability**: Why this paper gets published
   - key_strengths: List of 3-5 specific strengths that make this paper strong (be concrete, not generic)
   - positioning_strategy: How the paper positions itself in the field (what gap it claims, how it differentiates)
   - experiment_design: What makes the experimental evaluation convincing (baselines, metrics, datasets, ablations)

3. **knowledge_extraction**: Reusable insights
   - core_insights: 3-5 key technical insights or findings (the "aha" moments)
   - reusable_techniques: Specific methods, algorithms, or tricks that can be applied to other problems
   - implementation_hints: Practical tips for implementing the key ideas (hyperparameters, training tricks, architecture choices)

Return JSON:
```json
{{
    "writing_structure": {{
        "narrative_flow": "...",
        "section_pattern": ["..."],
        "argument_style": "..."
    }},
    "publishability": {{
        "key_strengths": ["..."],
        "positioning_strategy": "...",
        "experiment_design": "..."
    }},
    "knowledge_extraction": {{
        "core_insights": ["..."],
        "reusable_techniques": ["..."],
        "implementation_hints": ["..."]
    }}
}}
```

Only return JSON, no other text.
{language_instruction}
"""

# ─── Stage 4: Insight Analysis (abstract only, reduced) ───────────

INSIGHT_ABSTRACT_PROMPT = """You are a research paper analyst. Given only a paper's title and abstract (full text unavailable), provide a reduced analysis.

## Paper
Title: {title}
Abstract: {abstract}

## Instructions

Analyze this paper with available information. Since we only have the abstract, focus on what can be inferred:

1. **writing_structure**: (limited — infer from abstract style)
   - argument_style: How the paper makes its case based on the abstract's framing

2. **publishability**: Why this paper is notable
   - key_strengths: 2-3 apparent strengths based on claims and methodology described
   - positioning_strategy: How the paper positions itself based on the abstract

3. **knowledge_extraction**: Reusable insights
   - core_insights: 2-3 key insights extractable from the abstract
   - reusable_techniques: Methods or approaches mentioned that could be reused

Return JSON:
```json
{{
    "writing_structure": {{
        "argument_style": "..."
    }},
    "publishability": {{
        "key_strengths": ["..."],
        "positioning_strategy": "..."
    }},
    "knowledge_extraction": {{
        "core_insights": ["..."],
        "reusable_techniques": ["..."]
    }}
}}
```

Only return JSON, no other text.
{language_instruction}
"""

# ─── Stage 5: Review Consensus ─────────────────────────────────────

REVIEW_CONSENSUS_PROMPT = """You are an academic review analyst. Given {review_count} reviewer(s)' feedback for a paper, analyze the reviewing consensus.

## Paper
Title: {title}

## Analysis Mode: {mode}
- "single": Only 1 reviewer — summarize their view, no consensus analysis
- "limited": Only 2 reviewers — note limited sample size
- "full": 3+ reviewers — full consensus and controversy analysis

## Reviews
{reviews_text}

## Instructions

Return JSON:
```json
{{
    "average_rating": "number or description (e.g., '6.5 / 10' or '5: Borderline')",
    "consensus_strengths": ["strengths agreed upon by reviewers"],
    "consensus_weaknesses": ["weaknesses agreed upon by reviewers"],
    "controversies": ["points of disagreement among reviewers"],
    "meta_review_summary": "meta-reviewer summary (if available)",
    "key_takeaway": "most important suggestion for the paper authors"
}}
```

For "single" mode: fill consensus_strengths/weaknesses from the single reviewer's view; leave controversies empty.
For "limited" mode: note in key_takeaway that the sample is limited.

Only return JSON, no other text.
{language_instruction}
"""

# ─── Writing Guide Synthesis ───────────────────────────────────────

WRITING_GUIDE_PROMPT = """You are a research writing advisor. Based on the following in-depth analyses and review feedback for multiple highly relevant papers, generate a comprehensive writing guide for the researcher.

## Project Context
Title: {project_title}
Keywords: {project_keywords}

## Paper Analyses
{papers_text}

## Requirements

Synthesize the analyses of all papers to generate a research writing guide (under 500 words) with four sections:

1. **writing_norms**: Domain writing conventions (paper structure patterns, common argumentation styles, typical section organization)
2. **review_focus**: Review focus points (what reviewers value most, common weaknesses, how to avoid rejection)
3. **methodology_takeaways**: Methodology highlights (technical takeaways directly applicable to your own research, key insights, best practices)
4. **code_references**: Code implementation references (implementation approaches for key algorithms, recommended frameworks/tools, caveats)

Return JSON:
```json
{{
    "writing_norms": "...",
    "review_focus": "...",
    "methodology_takeaways": "...",
    "code_references": "..."
}}
```

Write each field in English. Content should be specific and actionable, not vague.
Return JSON only, no additional text.
{language_instruction}
"""
