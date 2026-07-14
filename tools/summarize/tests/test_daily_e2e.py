"""End-to-end: aggregate + translate one real day on the local LLM stack.

This is a REAL run, not mocked — it drives the actual summarize CLI against the
local Ollama server (aggregation) and the local translation engine (llama.cpp GGUF
on Windows) to produce a bilingual daily report. Auto-skips unless the local stack
and the day's device logs are present, so `pytest tests/` stays green in CI.

Run it:
    eval "$(bash scripts/serve_local_llm.sh env)"   # sets OLLAMA_* for the ollama backend
    cd tools && python -m pytest summarize/tests/test_daily_e2e.py -v -s

The aggregate step runs with SUMMARIZE_CONFIG pointed at a nonexistent file (and
HOME/USERPROFILE redirected to a temp dir), so it reads NEITHER the repo-local
tools/summarize/config.json NOR ~/.config/summarize/config.json — and therefore
never uploads to the rclone remote; the report is written under a temp dir,
leaving the canonical one untouched.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import pytest

DATE = "2026-06-26"
ROOT = Path(__file__).resolve().parents[3]          # tools/summarize/tests -> repo root
LOGS = sorted((ROOT / "outputs" / "logs" / "summarize").glob(f"{DATE}_*.json"))


def _ollama_up() -> bool:
    base = (os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "http://127.0.0.1:11434/v1")
    try:
        urllib.request.urlopen(base.rstrip("/") + "/models", timeout=3)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not LOGS, reason=f"no {DATE} device logs under outputs/logs/summarize/"),
    pytest.mark.skipif(not _ollama_up(),
                       reason="local Ollama not reachable — start Ollama and `eval \"$(bash scripts/serve_local_llm.sh env)\"`"),
]


def _cjk_ratio(text: str) -> float:
    """Fraction of alphabetic-or-CJK characters that are CJK. 0 for pure English."""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    letters = sum(1 for ch in text if ch.isalpha())
    return cjk / max(cjk + letters, 1)


def test_daily_aggregate_then_translate(tmp_path):
    # ── 1. AGGREGATE: real Ollama merge over the day's device logs ───────────
    reports_dir = tmp_path / "reports"
    fake_home = tmp_path / "home"          # no config here -> no rclone upload
    fake_home.mkdir()

    # SUMMARIZE_CONFIG beats the repo-local tools/summarize/config.json, which a
    # HOME redirect alone cannot shield against (it resolves from __file__).
    env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home),
           "SUMMARIZE_CONFIG": str(fake_home / "config.json")}
    cmd = [sys.executable, "-m", "summarize", "daily", "merge",
           "--date", DATE, "--api", "ollama", "--no-cache",
           "--output", str(reports_dir), *map(str, LOGS)]

    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=ROOT / "tools", env=env,
                       capture_output=True, text=True, timeout=1800)
    aggregate_s = time.perf_counter() - t0
    assert r.returncode == 0, f"merge failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}"

    report_json = reports_dir / f"{DATE}.json"
    report_md = reports_dir / f"{DATE}.md"
    assert report_json.exists(), f"no report JSON produced\n{r.stdout}"
    assert report_md.exists(), "no report Markdown produced"

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report.get("summary"), "aggregation produced an empty summary"
    assert not report.get("parse_error"), \
        f"LLM output failed to parse: {report.get('raw_response', '')[:300]}"
    md = report_md.read_text(encoding="utf-8")
    assert len(md) > 500, f"report Markdown suspiciously short ({len(md)} chars)"

    # ── 2. TRANSLATE: the real deploy step (adds Hugo frontmatter, then translates
    #      via the local engine) -> bilingual .md / .zh.md pair. Using generate_hugo_post
    #      mirrors `summarize daily merge --deploy` exactly, frontmatter and all. ───────
    from summarize.formatter import generate_hugo_post

    hugo_site = tmp_path / "website"       # content root is tmp_path/website/content
    t0 = time.perf_counter()
    en_path = generate_hugo_post(md, date.fromisoformat(DATE), hugo_site)
    translate_s = time.perf_counter() - t0
    zh_path = en_path.with_name(f"{en_path.stem}.zh.md")

    assert en_path.exists(), "no English-side file written"
    assert zh_path is not None and zh_path.exists(), \
        "translation failed — no .zh.md was produced (check the local translation engine)"

    en_text = en_path.read_text(encoding="utf-8")
    zh_text = zh_path.read_text(encoding="utf-8")
    assert len(zh_text) > 200, f"translated file suspiciously short ({len(zh_text)} chars)"
    assert en_text != zh_text, "the two language versions are identical — translation did not run"
    # .zh.md must be the Chinese side regardless of which language the report came out in
    assert _cjk_ratio(zh_text) > _cjk_ratio(en_text), \
        f".zh.md is not more Chinese than .md (zh={_cjk_ratio(zh_text):.2f}, en={_cjk_ratio(en_text):.2f})"
    assert _cjk_ratio(zh_text) > 0.1, \
        f".zh.md has almost no Chinese (cjk ratio {_cjk_ratio(zh_text):.2f})"

    # Structural completeness: translation preserves section headers, so the Chinese
    # side must keep essentially all of them. Catches silent truncation of long docs
    # (a too-small engine context once dropped the entire first half of the report).
    def _h2(t: str) -> int:
        return sum(1 for ln in t.splitlines() if ln.startswith("## "))
    en_h2, zh_h2 = _h2(en_text), _h2(zh_text)
    assert zh_h2 >= en_h2 - 1, \
        f"translation dropped sections: .md has {en_h2} '##' headers, .zh.md has {zh_h2}"

    print(f"\n[e2e] aggregate {aggregate_s:.0f}s -> {report_json}")
    print(f"[e2e]   sections: en h2={en_h2}  zh h2={zh_h2}")
    print(f"[e2e] translate {translate_s:.0f}s")
    print(f"[e2e]   en: {en_path.name}  {len(en_text)} chars  cjk={_cjk_ratio(en_text):.2f}")
    print(f"[e2e]   zh: {zh_path.name}  {len(zh_text)} chars  cjk={_cjk_ratio(zh_text):.2f}")
