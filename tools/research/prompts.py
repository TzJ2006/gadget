"""LLM prompt templates for researcher analysis."""

from __future__ import annotations

TRAJECTORY_ANALYSIS_PROMPT = """\
You are an academic research analysis expert. Please analyze the following researcher's academic trajectory.

## Researcher Information
- Name: {name}
- Affiliation: {affiliation}
- h-index: {h_index}
- Total Citations: {total_citations}
- Recent Citations (5yr): {recent_citations}
- Paper Count: {paper_count}
- Top Venue Papers: {top_venue_count}
- Publication Period: {first_year} - {latest_year}

## Paper List
{papers_text}

Please output the following analysis in **English**, returning strict JSON format (keep paper titles in their original form):

```json
{{
  "trajectory_summary": "2-3 paragraphs: why this person became a field leader/rising star, what the key turning points were",
  "breakthroughs": [
    {{
      "title": "Paper title of the breakthrough work (original)",
      "year": 2020,
      "description": "What this work does",
      "why_not_before": "Why it couldn't be done before",
      "impact": "Impact on the field"
    }}
  ],
  "research_themes": ["Main research direction 1", "Main research direction 2"],
  "methodology_evolution": "How methodology evolved over time (1-2 paragraphs)",
  "field_impact": "Assessment of impact on the entire field (1 paragraph)"
}}
```

Notes:
1. For breakthroughs, select the 3-5 most important breakthrough works
2. Focus on analyzing "why it couldn't be done before" — was it insufficient data, compute, or a missing key insight?
3. Base your analysis on actual data from the paper list; do not fabricate non-existent papers
"""

TRAJECTORY_ANALYSIS_DETAILED_PROMPT = """\
You are an academic research analysis expert. Please provide an in-depth analysis of the following researcher's academic trajectory.

## Researcher Information
- Name: {name}
- Affiliation: {affiliation}
- h-index: {h_index}
- Total Citations: {total_citations}
- Recent Citations (5yr): {recent_citations}
- Paper Count: {paper_count}
- Top Venue Papers: {top_venue_count}
- Publication Period: {first_year} - {latest_year}

## Paper List
{papers_text}

## Key Paper Full Texts
{full_text_section}

Please output the following in-depth analysis in **English**, returning strict JSON format (keep paper titles in their original form):

```json
{{
  "trajectory_summary": "3-4 paragraphs of in-depth narrative: why this person became a field leader/rising star, key turning points, methodology innovation trajectory",
  "breakthroughs": [
    {{
      "title": "Paper title (original)",
      "year": 2020,
      "description": "Detailed description of the methodology innovation in this work",
      "why_not_before": "In-depth analysis of why it couldn't be done before",
      "impact": "Far-reaching impact on the field",
      "technical_insight": "Core technical insight"
    }}
  ],
  "research_themes": ["Main research direction 1", "Main research direction 2"],
  "methodology_evolution": "How methodology evolved over time, including specific technical details (2-3 paragraphs)",
  "field_impact": "In-depth assessment of impact on the entire field, including how subsequent work was inspired (1-2 paragraphs)",
  "key_collaborations": "Important collaborative relationships and their influence on research directions"
}}
```

Notes:
1. You have full paper texts for reference; please analyze methodology details in depth
2. For breakthroughs, select the 3-7 most important breakthrough works
3. Focus on the causal chain of technical innovation: what preconditions made the breakthrough possible
4. Base your analysis on actual paper content; do not fabricate
"""

STUDENT_EVALUATION_PROMPT = """\
You are an academic relationship analysis expert. Please analyze the following researcher's potential students/mentees and assess their development potential.

## Advisor Information
- Name: {advisor_name}
- Main Research Directions: {research_themes}

## Potential Student Candidates
{candidates_text}

Please output analysis in **English**, returning strict JSON format:

```json
{{
  "students": [
    {{
      "name": "Student name (original)",
      "relationship_type": "PhD student/Postdoc/Close collaborator",
      "research_direction": "The student's main research direction",
      "development_assessment": "Assessment of development trajectory",
      "rising_star_potential": "High/Medium/Low"
    }}
  ]
}}
```
"""


AWARD_IDENTIFICATION_PROMPT = """\
You are an academic conference award expert. Based on your knowledge, identify papers from the following list that have received conference awards.

## Paper List
{papers_list}

Please identify papers that have received the following awards:
- best_paper: Best Paper Award / Outstanding Paper Award
- highlight: Highlighted Paper / Notable Paper
- spotlight: Spotlight Presentation
- oral: Oral Presentation (selected for oral presentation, typically acceptance rate < 5%)

Notes:
1. Only label papers you are **confident** have received awards; do not label uncertain ones
2. For oral, only label oral presentations at top conferences (NeurIPS, ICML, ICLR, CVPR, ICCV, ECCV, etc.)
3. Return strict JSON format

```json
{{
  "awards": [
    {{"title": "Full paper title", "award": "best_paper|highlight|spotlight|oral"}}
  ]
}}
```

If no papers have received awards, return `{{"awards": []}}`.
"""


CITATION_IMPACT_PROMPT = """\
Analyze the citation impact of the following paper.

## Target Paper
- Title: {title}
- Abstract: {abstract}
- Citation Count: {citation_count}

## Highly-Cited Follow-up Works Citing This Paper (Top {n})
{citing_papers_text}

Please analyze in English:
1. Why is this paper widely cited? What is the core contribution?
2. What main directions have follow-up works pursued?
3. What trend did this paper initiate?

Return strict JSON format:
```json
{{
  "popularity_reason": "Why it is widely cited",
  "followup_directions": ["Follow-up direction 1", "Follow-up direction 2", "Follow-up direction 3"],
  "trend_impact": "What trend it initiated"
}}
```

Notes: Base your analysis on actual data; do not fabricate. If citation data is insufficient for analysis, state so honestly.
"""


HOMEPAGE_URL_PROMPT = """\
You are an academic research assistant. Given a researcher's name and affiliation, suggest the most likely URLs for their personal homepage or lab page.

## Researcher
- Name: {name}
- Affiliation: {affiliation}

Think about common university URL patterns:
- Faculty pages: https://[university].edu/~[username]/ or https://[dept].[university].edu/people/[name]/
- Personal sites: https://[name].github.io/ or https://[name].com/
- Lab pages: https://[labname].[university].edu/

Return strictly JSON (no explanation):
```json
{{"urls": ["https://...", "https://..."]}}
```

Rules:
1. Suggest 2-3 most likely URLs only
2. Prefer .edu faculty pages and well-known personal sites
3. Include the lab page URL if you know it
4. Only suggest URLs you are fairly confident exist
"""

HOMEPAGE_STUDENT_PROMPT = """\
You are an academic relationship analyst. Extract students, postdocs, and advisees from the following webpage text.

## Researcher: {researcher_name}

## Page Content
{page_text}

Extract ALL people who appear to be students, postdocs, or advisees of {researcher_name}. Look for:
- "Students" / "Group Members" / "Lab Members" / "Team" sections
- "PhD Students" / "Graduate Students" / "Postdocs" / "Alumni" listings
- "Advised" / "Supervised" / "Mentored" mentions

Return strictly JSON:
```json
{{
  "students": [
    {{
      "name": "Full Name",
      "status": "current|graduated|postdoc|unknown",
      "research_direction": "brief research focus if mentioned"
    }}
  ]
}}
```

Rules:
1. Include both current and former students/postdocs
2. Set status to "current" for current members, "graduated" for alumni/former, "postdoc" for postdocs
3. If status is unclear, use "unknown"
4. Only include people who are clearly students/postdocs/advisees, not collaborators or faculty peers
5. If no students are found, return {{"students": []}}
"""


def format_papers_for_prompt(papers: list[dict], mode: str = "fast") -> str:
    """Format paper list for LLM prompt, grouped by year."""
    from collections import defaultdict

    AWARD_LABELS = {
        "best_paper": "⭐ Best Paper",
        "highlight": "✨ Highlight",
        "spotlight": "🔦 Spotlight",
        "oral": "🎤 Oral",
    }

    # Group papers by year
    by_year: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, p in enumerate(papers, 1):
        year = p.get("published", "")[:4] if p.get("published") else "Unknown"
        by_year[year].append((i, p))

    # Sort years chronologically
    sorted_years = sorted(by_year.keys(), key=lambda y: (y == "Unknown", y))

    sections = ["The following papers are listed chronologically by year, with up to 10 representative works per year.\n"]
    for year in sorted_years:
        items = by_year[year]
        sections.append(f"## {year} ({len(items)} papers)\n")
        for idx, p in items:
            title = p.get("title", "")
            cites = p.get("citation_count", 0)
            venue = p.get("venue", "")
            abstract = p.get("abstract", "")
            award = p.get("award", "")

            line = f"{idx}. [{year}] {title}"
            if venue:
                line += f" ({venue})"
            if cites:
                line += f" [Citations: {cites}]"
            if award and award in AWARD_LABELS:
                line += f" {AWARD_LABELS[award]}"
            if mode == "fast" and abstract:
                abs_short = abstract[:300] + "..." if len(abstract) > 300 else abstract
                line += f"\n   Abstract: {abs_short}"
            elif mode == "detailed" and abstract:
                line += f"\n   Abstract: {abstract}"
            sections.append(line)
        sections.append("")  # blank line between years

    return "\n\n".join(sections)


def format_full_texts(papers_with_text: list[dict], max_chars_per_paper: int = 50000) -> str:
    """Format full paper texts for detailed mode prompt."""
    sections = []
    for p in papers_with_text:
        text = p.get("full_text", "")
        if not text:
            continue
        title = p.get("title", "")
        if len(text) > max_chars_per_paper:
            text = text[:max_chars_per_paper] + "\n...[truncated]"
        sections.append(f"### {title}\n\n{text}")

    return "\n\n---\n\n".join(sections) if sections else "(No full text data)"


def format_candidates_for_prompt(candidates: list[dict]) -> str:
    """Format student candidates for LLM evaluation."""
    lines = []
    for c in candidates:
        name = c.get("name", "")
        collabs = c.get("coauthor_count", 0)
        first = c.get("first_author_count", 0)
        start = c.get("collab_start_year", 0)
        end = c.get("collab_end_year", 0)
        score = c.get("relationship_score", 0)
        lines.append(
            f"- {name}: Co-authored {collabs} papers, First author (advisor last) {first} papers, "
            f"Collaboration period {start}-{end}, Relationship score {score:.2f}"
        )
    return "\n".join(lines) if lines else "(No candidates)"
