"""Token usage chart generation — single PNG with three side-by-side subplots.

Layout (left to right):
  1. Tokens — X-axis: source (Claude Code, Codex, Gemini, …), stacked by model
  2. Cost   — X-axis: source, stacked by model
  3. Cache  — X-axis: source, stacked by token type (overall)

All legends on the right side of each subplot.
Output: outputs/images/summarize/<date>-usage.png
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from common.paths import IMAGES_DIR

_DEFAULT_IMAGES_DIR = IMAGES_DIR / "summarize"


def _try_import():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        import numpy as np
        return plt, font_manager, np
    except ImportError:
        print("[warn] matplotlib not installed, skipping chart (pip install matplotlib)")
        return None, None, None


def _setup_style(plt, font_manager) -> None:
    _cjk_fonts = ["PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                   "Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei"]
    for fname in _cjk_fonts:
        try:
            result = font_manager.findfont(fname, fallback_to_default=False)
            if result:
                plt.rcParams["font.sans-serif"] = (
                    [fname] + plt.rcParams["font.sans-serif"])
                break
        except ValueError:
            continue
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["axes.facecolor"] = "#fafafa"
    plt.rcParams["figure.facecolor"] = "#ffffff"


def _shorten_model(name: str) -> str:
    parts = name.split("-")
    if len(parts) >= 2:
        core = parts[0] + "-" + parts[1]
        if len(core) > 18:
            return core[:16] + "…"
        return core
    return name[:18]


def _get_breakdowns(usage: Optional[dict]) -> list[dict]:
    if not usage:
        return []
    bds = usage.get("modelBreakdowns", [])
    if bds:
        return bds
    for d in usage.get("daily", []):
        bds = d.get("modelBreakdowns", [])
        if bds:
            return bds
    return []


# Palette per source slot (cycled by index for arbitrary sources).
_PALETTES = [
    ["#6366f1", "#818cf8", "#a5b4fc", "#c7d2fe", "#e0e7ff"],  # indigo (Claude)
    ["#f97316", "#fb923c", "#fdba74", "#fed7aa", "#fff7ed"],  # orange (Codex)
    ["#10b981", "#34d399", "#6ee7b7", "#a7f3d0", "#d1fae5"],  # green (Gemini)
    ["#ec4899", "#f472b6", "#f9a8d4", "#fbcfe8", "#fce7f3"],  # pink
    ["#0ea5e9", "#38bdf8", "#7dd3fc", "#bae6fd", "#e0f2fe"],  # sky
]

_SOURCE_DISPLAY = {"claude_code": "Claude Code", "codex": "Codex",
                   "gemini": "Gemini", "copilot": "GitHub Copilot"}

_TYPE_COLORS = {
    "Input": "#6366f1", "Output": "#06b6d4", "Cache Creation": "#8b5cf6",
    "Cache Read": "#a78bfa", "Reasoning": "#f97316",
}


def generate_daily_chart(
    usage_by_source=None,
    target_date: date = None,
    output_dir: Optional[Path] = None,
    token_usage: Optional[dict] = None,
    codex_usage: Optional[dict] = None,
) -> Optional[Path]:
    """Generate a 3-subplot PNG (Tokens / Cost / Cache) per source.

    `usage_by_source` maps source label -> merged usage dict. For backward compat,
    if it is falsy, `token_usage` (Claude Code) and `codex_usage` (Codex) are used.
    """
    plt, font_manager, np = _try_import()
    if plt is None:
        return None
    _setup_style(plt, font_manager)

    if not usage_by_source:
        usage_by_source = {}
        if token_usage:
            usage_by_source["claude_code"] = token_usage
        if codex_usage:
            usage_by_source["codex"] = codex_usage

    # Keep only sources with data, stable order (known sources first).
    order = ["claude_code", "codex"] + sorted(
        s for s in usage_by_source if s not in ("claude_code", "codex"))
    sources = []
    for s in order:
        u = usage_by_source.get(s)
        if not u:
            continue
        if _get_breakdowns(u) or (u.get("totals") or {}):
            sources.append(s)
    if not sources:
        return None

    labels = [_SOURCE_DISPLAY.get(s, s) for s in sources]
    x = np.arange(len(sources))
    bar_w = 0.45
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 5.5))
    seen_labels = set()

    def _dedup(label):
        if label in seen_labels:
            return "_nolegend_"
        seen_labels.add(label)
        return label

    # ── Subplot 1: Tokens by model ──
    for pi, s in enumerate(sources):
        bds = _get_breakdowns(usage_by_source[s])
        palette = _PALETTES[pi % len(_PALETTES)]
        bottom = 0.0
        for mi, mb in enumerate(bds):
            val = mb.get("totalTokens", 0) or (
                mb.get("inputTokens", 0) + mb.get("outputTokens", 0)
                + mb.get("cacheCreationTokens", 0) + mb.get("cacheReadTokens", 0)
                + mb.get("reasoningOutputTokens", 0))
            val_m = val / 1_000_000
            if val_m <= 0:
                continue
            ax1.bar(pi, val_m, bar_w, bottom=bottom, color=palette[mi % len(palette)],
                    edgecolor="white", linewidth=0.5,
                    label=_dedup(_shorten_model(mb.get("modelName", "?"))))
            bottom += val_m
        if bottom > 0:
            ax1.text(pi, bottom + 0.3, f"{bottom:.1f}M", ha="center", va="bottom",
                     fontsize=9, fontweight="bold")
    ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Tokens (M)", fontsize=11)
    ax1.set_title("Tokens", fontsize=12, fontweight="bold")
    ax1.set_ylim(bottom=0); ax1.grid(axis="y", alpha=0.3); ax1.set_axisbelow(True)
    ax1.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, framealpha=0.9)

    # ── Subplot 2: Cost by model ──
    seen_labels.clear()
    for pi, s in enumerate(sources):
        bds = _get_breakdowns(usage_by_source[s])
        palette = _PALETTES[pi % len(_PALETTES)]
        bottom = 0.0
        for mi, mb in enumerate(bds):
            cost = mb.get("cost", 0)
            if cost <= 0:
                continue
            ax2.bar(pi, cost, bar_w, bottom=bottom, color=palette[mi % len(palette)],
                    edgecolor="white", linewidth=0.5,
                    label=_dedup(_shorten_model(mb.get("modelName", "?"))))
            bottom += cost
        if bottom > 0:
            ax2.text(pi, bottom, f"${bottom:.2f}", ha="center", va="bottom",
                     fontsize=9, fontweight="bold")
    ax2.set_xticks(x); ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("Cost ($)", fontsize=11)
    ax2.set_title("Cost", fontsize=12, fontweight="bold")
    ax2.set_ylim(bottom=0); ax2.grid(axis="y", alpha=0.3); ax2.set_axisbelow(True)
    ax2.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, framealpha=0.9)

    # ── Subplot 3: Token-type breakdown ──
    type_keys = [("inputTokens", "Input"), ("outputTokens", "Output"),
                 ("cacheCreationTokens", "Cache Creation"),
                 ("cacheReadTokens", "Cache Read"),
                 ("reasoningOutputTokens", "Reasoning")]
    seen_labels.clear()
    for pi, s in enumerate(sources):
        totals = (usage_by_source[s] or {}).get("totals", {})
        bottom = 0.0
        for field, label in type_keys:
            val = totals.get(field, 0) / 1_000_000
            if val <= 0:
                continue
            ax3.bar(pi, val, bar_w, bottom=bottom, color=_TYPE_COLORS[label],
                    edgecolor="white", linewidth=0.5, label=_dedup(label))
            bottom += val
        if bottom > 0:
            ax3.text(pi, bottom + 0.3, f"{bottom:.1f}M", ha="center", va="bottom",
                     fontsize=9, fontweight="bold")
    ax3.set_xticks(x); ax3.set_xticklabels(labels, fontsize=10)
    ax3.set_ylabel("Tokens (M)", fontsize=11)
    ax3.set_title("Token Breakdown", fontsize=12, fontweight="bold")
    ax3.set_ylim(bottom=0); ax3.grid(axis="y", alpha=0.3); ax3.set_axisbelow(True)
    ax3.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, framealpha=0.9)

    fig.suptitle(f"Token Usage — {target_date.isoformat()}", fontsize=14,
                 fontweight="bold", y=1.02)
    fig.tight_layout()
    if output_dir is None:
        output_dir = _DEFAULT_IMAGES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{target_date.isoformat()}-usage.png"
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[ok] Usage chart saved: {path}")
    return path
