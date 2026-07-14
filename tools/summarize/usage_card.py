"""Minimal footer-card HTML for token usage — replaces the matplotlib PNG.

Self-contained <style> + <footer> block embedded directly in report markdown
(Hugo goldmark unsafe HTML is enabled). Colors follow TokenMonitor:
Claude #d0724a, Codex #4a8db8, active #5a8878.
"""

from __future__ import annotations

_SOURCE_DISPLAY = {"claude_code": "Claude Code", "codex": "Codex",
                   "gemini": "Gemini", "copilot": "GitHub Copilot"}

# claude_code / codex map to the two named tokens; extra sources cycle these.
_SOURCE_COLORS = {"claude_code": "var(--usage-cost-main)",
                  "codex": "var(--usage-cost-secondary)"}
_EXTRA_COLORS = ["#5a8878", "#8a7ab8", "#b8a04a"]

CARD_CSS = """<style>
  .usage-card {
    --usage-bg: #fafaf9;
    --usage-border: rgba(0, 0, 0, 0.08);
    --usage-text: #1a1a1a;
    --usage-muted: #8a8880;
    --usage-cost-main: #d0724a;
    --usage-cost-secondary: #4a8db8;
    --usage-cache: #c9c7c0;
    --usage-active: #5a8878;
    --usage-bar-bg: rgba(0, 0, 0, 0.05);
    box-sizing: border-box;
    background: var(--usage-bg);
    border: 1px solid var(--usage-border);
    border-radius: 10px;
    padding: 1.5rem 1.75rem 1.375rem;
    color: var(--usage-text);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 16px;
    line-height: 1.4;
  }
  .usage-card *, .usage-card *::before { box-sizing: inherit; }
  @media (prefers-color-scheme: dark) {
    .usage-card {
      --usage-bg: #141416;
      --usage-border: rgba(255, 255, 255, 0.09);
      --usage-text: rgba(255, 255, 255, 0.93);
      --usage-muted: rgba(255, 255, 255, 0.45);
      --usage-cache: #4a4a48;
      --usage-bar-bg: rgba(255, 255, 255, 0.06);
    }
  }
  .usage-card__head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
  .usage-card__title { font-size: 0.875rem; font-weight: 600; letter-spacing: 0.01em; }
  .usage-card__source { font-size: 0.75rem; color: var(--usage-muted); }
  /* selectors doubled (.usage-card dl./div.) to out-rank theme .md-content dl/dt/dd rules */
  .usage-card dl.usage-card__stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 1rem 1.5rem;
    margin: 1.25rem 0 1.5rem;
  }
  .usage-card div.usage-card__stat { display: flex; flex-direction: column-reverse; gap: 0.2rem; }
  .usage-card .usage-card__stat dd { width: auto; margin: 0; padding: 0; font-size: 1.3125rem; font-weight: 600; letter-spacing: -0.01em; }
  .usage-card .usage-card__stat dt { width: auto; margin: 0; font-size: 0.6875rem; font-weight: 400; color: var(--usage-muted); text-transform: uppercase; letter-spacing: 0.06em; white-space: nowrap; }
  .usage-card__row { margin-top: 1rem; }
  .usage-card__row-labels { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; font-size: 0.75rem; margin-bottom: 0.45rem; }
  .usage-card__row-name { color: var(--usage-text); font-weight: 500; }
  .usage-card__row-detail { color: var(--usage-muted); }
  .usage-card__item { white-space: nowrap; }
  .usage-card__dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 0.3em; vertical-align: 0.02em; }
  .usage-card__bar { display: flex; gap: 2px; height: 6px; border-radius: 3px; overflow: hidden; background: var(--usage-bar-bg); }
  .usage-card__bar span { border-radius: 2px; }
  .usage-card__note { margin: 1.375rem 0 0; font-size: 0.8125rem; color: var(--usage-muted); }
</style>"""


def _fmt_tokens(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.0f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}K"
    return f"{n:.0f}"


def _source_color(source: str, index: int) -> str:
    return _SOURCE_COLORS.get(source, _EXTRA_COLORS[index % len(_EXTRA_COLORS)])


def _bar(name: str, segments: list[tuple[str, str, float, str]]) -> str:
    """segments: (label, color, width_pct, legend_text)."""
    legend = " ·\n            ".join(
        f'<span class="usage-card__item"><span class="usage-card__dot" '
        f'style="background:{color}"></span>{legend_text}</span>'
        for _, color, _, legend_text in segments)
    aria = ", ".join(f"{label} ({pct:.1f}%)" for label, _, pct, _ in segments)
    spans = "\n          ".join(
        f'<span style="width:{pct:.1f}%; background:{color}"></span>'
        for _, color, pct, _ in segments if pct > 0)
    return f"""      <div class="usage-card__row">
        <div class="usage-card__row-labels">
          <span class="usage-card__row-name">{name}</span>
          <span class="usage-card__row-detail">
            {legend}
          </span>
        </div>
        <div class="usage-card__bar" role="img" aria-label="{name}: {aria}">
          {spans}
        </div>
      </div>"""


def render_usage_card(usage_by_source: dict, title: str) -> str:
    """Render the usage footer card as embeddable HTML. Empty string if no data."""
    sources = []  # (source, totals) with any data
    for s in sorted(usage_by_source or {},
                    key=lambda s: (s not in ("claude_code", "codex"), s)):
        t = (usage_by_source[s] or {}).get("totals", {}) or {}
        if t.get("totalCost", 0) or t.get("totalTokens", 0):
            sources.append((s, t))
    if not sources:
        return ""

    total_cost = sum(t.get("totalCost", 0) for _, t in sources)
    total_tokens = sum(t.get("totalTokens", 0) for _, t in sources)
    output_tokens = sum(t.get("outputTokens", 0)
                        + t.get("reasoningOutputTokens", 0) for _, t in sources)
    cache_read = sum(t.get("cacheReadTokens", 0) for _, t in sources)
    cache_pct = 100 * cache_read / total_tokens if total_tokens else 0

    stats = []
    if total_cost:
        stats.append(("Total cost", f"${total_cost:,.2f}"))
    if total_tokens:
        stats.append(("Total tokens", _fmt_tokens(total_tokens)))
    if output_tokens:
        stats.append(("Output tokens", _fmt_tokens(output_tokens)))
    if total_tokens:
        stats.append(("Cache read", f"{cache_pct:.1f}%"))
    stats_html = "\n        ".join(
        f'<div class="usage-card__stat"><dt>{k}</dt><dd>{v}</dd></div>'
        for k, v in stats)

    rows = []
    if total_cost and len(sources) > 1:
        rows.append(_bar("Cost split", [
            (_SOURCE_DISPLAY.get(s, s), _source_color(s, i),
             100 * t.get("totalCost", 0) / total_cost,
             f"{_SOURCE_DISPLAY.get(s, s)} ${t.get('totalCost', 0):,.0f}")
            for i, (s, t) in enumerate(sources)]))
    if total_tokens and cache_read:
        rows.append(_bar("Token character", [
            ("cache reads", "var(--usage-cache)", cache_pct,
             f"Cache reads {cache_pct:.1f}%"),
            ("active tokens", "var(--usage-active)", 100 - cache_pct,
             f"Active {100 - cache_pct:.1f}%")]))

    note = ""
    if total_cost and total_tokens:
        top_s, top_t = max(sources, key=lambda st: st[1].get("totalCost", 0))
        parts = []
        if cache_read and cache_pct > 50:
            parts.append("Most token volume came from cache reads")
        if len(sources) > 1 and total_cost:
            share = 100 * top_t.get("totalCost", 0) / total_cost
            if share > 80:
                parts.append(f"{_SOURCE_DISPLAY.get(top_s, top_s)} "
                             "drove nearly all cost")
        if parts:
            note = (f'      <p class="usage-card__note">\n'
                    f'        {"; ".join(parts)}.\n      </p>\n')

    source_label = " + ".join(_SOURCE_DISPLAY.get(s, s) for s, _ in sources)
    return f"""{CARD_CSS}
<footer class="usage-card">
      <div class="usage-card__head">
        <span class="usage-card__title">{title}</span>
        <span class="usage-card__source">{source_label}</span>
      </div>
      <dl class="usage-card__stats">
        {stats_html}
      </dl>
{chr(10).join(rows)}
{note}</footer>"""


if __name__ == "__main__":  # self-check
    demo = {
        "claude_code": {"totals": {"totalCost": 2990.0, "totalTokens": 2.41e9,
                                   "outputTokens": 20e6, "cacheReadTokens": 2.17e9}},
        "codex": {"totals": {"totalCost": 117.0, "totalTokens": 131e6,
                             "outputTokens": 4e6, "cacheReadTokens": 123e6}},
    }
    html = render_usage_card(demo, "AI Usage · June 2026")
    assert "usage-card" in html and "$3,107.00" in html and "2.54B" in html
    assert "Claude Code $2,990" in html and "Codex $117" in html
    assert render_usage_card({}, "x") == ""
    print(html)
