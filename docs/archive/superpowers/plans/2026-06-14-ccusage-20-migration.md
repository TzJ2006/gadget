# ccusage 20.x Per-Source Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `summarize/` token tracking from the legacy split (bare `ccusage` for Claude Code + `npx @ccusage/codex` for Codex) to ccusage 20.x namespaced per-source commands, with source discovery, generic normalization, silent best-effort global upgrade, and per-source reporting.

**Architecture:** ccusage 20.x unifies 15+ agent CLIs but its unified `daily --json` collapses all sources into one `agent:"all"` blob (no per-source token counts). Per-source data requires namespaced commands (`ccusage <source> daily --json --breakdown`), whose JSON shape differs per source (Claude = standard `modelBreakdowns`/`totalCost`; Codex = `models{}`/`costUSD`). We discover which sources have data via `metadata.agents` from one unified call, then fetch each namespaced, normalize to one canonical shape, and store one snapshot per source.

**Tech Stack:** Python 3.10+, `subprocess`, `pytest` + `unittest.mock` (stub `subprocess.run`, no real network), matplotlib (charts, optional).

**Phasing:**
- **Phase 1 (Tasks 1–8):** Core fetch migration + version guard + daily wiring. Keeps Claude/Codex display working via backward-compat aliases. Fixes 20.x breakage; removes `@ccusage/codex`. Shippable on its own.
- **Phase 2 (Tasks 9–12):** Generalize formatter/charts/weekly/monthly to render *all* discovered sources.
- **Phase 3 (Tasks 13–14):** rclone filter + docs.

---

## Canonical normalized usage shape (reference for all tasks)

Every `_normalize_usage()` output, every saved snapshot's `usage` field, and every `_merge_token_usages()` input/consumer uses this shape (identical to what the `claude` namespace already returns):

```python
{
  "daily": [
    {
      "date": "2026-06-13",                # ISO; from `date` or `period`
      "inputTokens": int, "outputTokens": int,
      "cacheCreationTokens": int, "cacheReadTokens": int,
      "totalTokens": int, "totalCost": float,
      "reasoningOutputTokens": int,        # OPTIONAL — only if source provides it
      "modelBreakdowns": [
        {"modelName": str, "inputTokens": int, "outputTokens": int,
         "cacheCreationTokens": int, "cacheReadTokens": int, "cost": float,
         "reasoningOutputTokens": int}     # reasoning OPTIONAL
      ],
    },
  ],
  "totals": { ...same token/cost fields, no `date`, no `modelBreakdowns` },
  "_source": "claude",                     # ccusage namespace name
}
```

**Source key convention:** ccusage namespace names (`claude`, `codex`, `gemini`, …) come from `metadata.agents`. Internal report/source labels map the namespace via `_SOURCE_LABEL`: `{"claude": "claude_code"}`, every other namespace maps to itself. So `token_usage_by_source` keys are `claude_code`, `codex`, `gemini`, …

---

## Phase 1 — Core fetch migration

### Task 1: Canonical normalizer `_normalize_entry` / `_normalize_usage`

**Files:**
- Modify: `summarize/usage.py` (add new functions; will delete old codex normalizers in Task 4)
- Test: `summarize/tests/test_usage.py` (create)

- [ ] **Step 1: Write failing tests**

Create `summarize/tests/test_usage.py`:

```python
"""Unit tests for ccusage 20.x per-source usage tracking."""
import json
from unittest import mock

from summarize import usage


# ---- standard (claude namespace) sample ----
CLAUDE_RAW = {
    "daily": [{
        "date": "2026-06-13",
        "inputTokens": 100, "outputTokens": 50,
        "cacheCreationTokens": 10, "cacheReadTokens": 200,
        "totalTokens": 360, "totalCost": 1.5,
        "modelBreakdowns": [{
            "modelName": "claude-opus-4-6",
            "inputTokens": 100, "outputTokens": 50,
            "cacheCreationTokens": 10, "cacheReadTokens": 200, "cost": 1.5,
        }],
    }],
    "totals": {"inputTokens": 100, "outputTokens": 50,
               "cacheCreationTokens": 10, "cacheReadTokens": 200,
               "totalTokens": 360, "totalCost": 1.5},
}

# ---- codex namespace sample (models dict, costUSD, reasoning) ----
CODEX_RAW = {
    "daily": [{
        "date": "2026-04-01",
        "inputTokens": 436934, "outputTokens": 75382,
        "cacheReadTokens": 4548480, "reasoningOutputTokens": 51131,
        "totalTokens": 5060796, "costUSD": 3.36,
        "models": {"gpt-5.4": {
            "inputTokens": 436934, "outputTokens": 75382,
            "cacheReadTokens": 4548480, "reasoningOutputTokens": 51131,
            "totalTokens": 5060796,
        }},
    }],
    "totals": {"inputTokens": 436934, "outputTokens": 75382,
               "cacheReadTokens": 4548480, "totalTokens": 5060796,
               "costUSD": 3.36, "reasoningOutputTokens": 51131},
}


def test_normalize_standard_passthrough():
    out = usage._normalize_usage(CLAUDE_RAW, "claude")
    assert out["_source"] == "claude"
    day = out["daily"][0]
    assert day["date"] == "2026-06-13"
    assert day["totalCost"] == 1.5
    assert day["modelBreakdowns"][0]["modelName"] == "claude-opus-4-6"
    assert day["modelBreakdowns"][0]["cost"] == 1.5
    assert out["totals"]["totalTokens"] == 360


def test_normalize_codex_shape():
    out = usage._normalize_usage(CODEX_RAW, "codex")
    day = out["daily"][0]
    assert day["date"] == "2026-04-01"
    assert day["totalCost"] == 3.36           # costUSD -> totalCost
    assert day["reasoningOutputTokens"] == 51131
    mb = day["modelBreakdowns"][0]            # models{} -> modelBreakdowns[]
    assert mb["modelName"] == "gpt-5.4"
    assert mb["cost"] == 3.36                 # single model -> day cost
    assert mb["cacheReadTokens"] == 4548480
    assert out["totals"]["totalCost"] == 3.36


def test_normalize_period_fallback():
    raw = {"daily": [{"period": "2026-06-14", "totalTokens": 5, "totalCost": 0.1}],
           "totals": {}}
    out = usage._normalize_usage(raw, "gemini")
    assert out["daily"][0]["date"] == "2026-06-14"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd /run/media/thomas/F2A6C96DA6C932C1/GitHub/gadget && python -m pytest summarize/tests/test_usage.py -q`
Expected: FAIL — `AttributeError: module 'summarize.usage' has no attribute '_normalize_usage'`.

- [ ] **Step 3: Implement the normalizer**

In `summarize/usage.py`, add after the imports block (before `_refresh_usage_snapshots`):

```python
# ccusage 20.x namespace name -> internal report source label
_SOURCE_LABEL = {"claude": "claude_code"}


def _source_label(namespace: str) -> str:
    """Map a ccusage namespace (claude/codex/gemini/...) to an internal label."""
    return _SOURCE_LABEL.get(namespace, namespace)


def _normalize_entry(d: dict, is_total: bool = False) -> dict:
    """Map one ccusage entry (standard OR codex shape) to the canonical shape."""
    entry = {
        "inputTokens": d.get("inputTokens", 0),
        "outputTokens": d.get("outputTokens", 0),
        "cacheCreationTokens": d.get("cacheCreationTokens", 0),
        "cacheReadTokens": d.get("cacheReadTokens", d.get("cachedInputTokens", 0)),
        "totalTokens": d.get("totalTokens", 0),
        "totalCost": d.get("totalCost", d.get("costUSD", 0)),
    }
    if not is_total:
        entry["date"] = d.get("date") or d.get("period", "")
    if d.get("reasoningOutputTokens"):
        entry["reasoningOutputTokens"] = d.get("reasoningOutputTokens", 0)

    # modelBreakdowns[] (standard) preferred; else convert models{} dict (codex)
    mbs = d.get("modelBreakdowns")
    if mbs is None and isinstance(d.get("models"), dict):
        models = d["models"]
        single = len(models) == 1
        mbs = []
        for name, md in models.items():
            mb = {
                "modelName": name,
                "inputTokens": md.get("inputTokens", 0),
                "outputTokens": md.get("outputTokens", 0),
                "cacheCreationTokens": md.get("cacheCreationTokens", 0),
                "cacheReadTokens": md.get("cacheReadTokens", md.get("cachedInputTokens", 0)),
                "cost": md.get("cost", d.get("costUSD", 0) if single else 0),
            }
            if md.get("reasoningOutputTokens"):
                mb["reasoningOutputTokens"] = md.get("reasoningOutputTokens", 0)
            mbs.append(mb)
    if mbs:
        entry["modelBreakdowns"] = mbs
    return entry


def _normalize_usage(raw: dict, source: str) -> dict:
    """Normalize a raw namespaced ccusage payload to the canonical shape."""
    return {
        "daily": [_normalize_entry(day) for day in raw.get("daily", [])],
        "totals": _normalize_entry(raw.get("totals", {}), is_total=True),
        "_source": source,
    }
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/usage.py summarize/tests/test_usage.py
git commit -m "feat(summarize): canonical per-source ccusage normalizer"
```

---

### Task 2: Version guard + command builder (`_ccusage_version`, `_ensure_ccusage_global`, `_ccusage_cmd`)

**Files:**
- Modify: `summarize/usage.py:38-80` (replace `_ensure_ccusage_global`)
- Test: `summarize/tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

Append to `summarize/tests/test_usage.py`:

```python
def _completed(stdout="", code=0):
    m = mock.Mock()
    m.returncode = code
    m.stdout = stdout
    m.stderr = ""
    return m


def test_version_parse_modern_no_upgrade():
    with mock.patch.object(usage.shutil, "which", return_value="/usr/bin/ccusage"), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed("20.0.13")) as run:
        usage._USE_NPX = True            # force a known starting state
        usage._ensure_ccusage_global()
    assert usage._USE_NPX is False       # modern global -> use global
    assert run.call_count == 1           # only the --version probe ran


def test_version_old_triggers_silent_upgrade(monkeypatch):
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:2] == ["npm", "install"]:
            return _completed("", 0)
        # --version: report modern only after an npm install has happened
        ver = "20.0.13" if any(c[:2] == ["npm", "install"] for c in calls[:-1]) else "18.0.10"
        return _completed(ver)

    monkeypatch.setattr(usage.shutil, "which", lambda *_: "/usr/bin/ccusage")
    monkeypatch.setattr(usage.subprocess, "run", fake_run)
    usage._USE_NPX = False
    usage._ensure_ccusage_global()
    assert any(c[:2] == ["npm", "install"] for c in calls)
    assert usage._USE_NPX is False       # upgrade succeeded


def test_missing_falls_back_to_npx(monkeypatch):
    monkeypatch.setattr(usage.shutil, "which", lambda *_: None)
    monkeypatch.setattr(usage.subprocess, "run", lambda *a, **k: _completed("", 1))
    usage._USE_NPX = False
    usage._ensure_ccusage_global()
    assert usage._USE_NPX is True


def test_ccusage_cmd_switches_on_flag():
    usage._USE_NPX = False
    assert usage._ccusage_cmd(["codex", "daily"]) == ["ccusage", "codex", "daily"]
    usage._USE_NPX = True
    assert usage._ccusage_cmd(["codex", "daily"]) == \
        ["npx", "--yes", "ccusage@latest", "codex", "daily"]
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python -m pytest summarize/tests/test_usage.py -q -k "version or npx or cmd"`
Expected: FAIL — `module 'summarize.usage' has no attribute '_USE_NPX'` / `_ccusage_cmd`.

- [ ] **Step 3: Implement**

In `summarize/usage.py`, add `import re` to the imports. Replace the entire `_ensure_ccusage_global` function (lines 38-80) with:

```python
# Module flag: prefer `npx --yes ccusage@latest` when no usable >=20 global exists.
_USE_NPX = False

_MIN_MAJOR = 20


def _ccusage_version() -> Optional[tuple]:
    """Return the global ccusage version as (major, minor, patch), or None."""
    if not shutil.which("ccusage"):
        return None
    try:
        r = subprocess.run(["ccusage", "--version"], capture_output=True,
                           text=True, timeout=15, shell=(sys.platform == "win32"))
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", r.stdout or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _ensure_ccusage_global() -> None:
    """Silent best-effort: ensure a >=20 global ccusage, else fall back to npx.

    Sets module flag `_USE_NPX`. Never prompts; never blocks the pipeline.
    """
    global _USE_NPX
    ver = _ccusage_version()
    if ver and ver[0] >= _MIN_MAJOR:
        _USE_NPX = False
        return

    print("[info] ccusage 缺失或版本过旧(<20)，尝试静默升级: npm install -g ccusage@latest")
    try:
        r = subprocess.run(["npm", "install", "-g", "ccusage@latest"],
                           capture_output=True, text=True, timeout=300,
                           shell=(sys.platform == "win32"))
        new_ver = _ccusage_version()
        if r.returncode == 0 and new_ver and new_ver[0] >= _MIN_MAJOR:
            print("[ok] ccusage 已升级到 20.x")
            _USE_NPX = False
            return
        print("[warn] 全局升级失败，本次回退 npx --yes ccusage@latest")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"[warn] 全局升级异常({e})，本次回退 npx --yes ccusage@latest")
    _USE_NPX = True


def _ccusage_cmd(args: list) -> list:
    """Build the ccusage invocation, honoring the npx-fallback flag."""
    base = ["npx", "--yes", "ccusage@latest"] if _USE_NPX else ["ccusage"]
    return base + list(args)
```

Then check whether the old config imports are still used:
Run: `grep -n "_CONFIG_PATH\|_config_module\|ccusage_global_install" summarize/usage.py`
If there are no remaining references, remove `from .config import _CONFIG_PATH` and `from . import config as _config_module` (lines 18-19). Keep `from .config import _load_config, _get_device_name, _resolve_output_dir`.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/usage.py summarize/tests/test_usage.py
git commit -m "feat(summarize): silent best-effort ccusage 20.x version guard"
```

---

### Task 3: Source discovery (`discover_sources`)

**Files:**
- Modify: `summarize/usage.py`
- Test: `summarize/tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
UNIFIED_RAW = {
    "daily": [
        {"period": "2026-06-13", "agent": "all",
         "metadata": {"agents": ["claude", "codex"]}, "totalTokens": 1},
        {"period": "2026-06-14", "agent": "all",
         "metadata": {"agents": ["claude"]}, "totalTokens": 2},
    ],
    "totals": {},
}


def test_discover_sources_union():
    with mock.patch.object(usage, "_ensure_ccusage_global"), \
         mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "daily", "--json"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed(json.dumps(UNIFIED_RAW))):
        assert usage.discover_sources() == ["claude", "codex"]


def test_discover_sources_failure_default():
    with mock.patch.object(usage, "_ensure_ccusage_global"), \
         mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "daily", "--json"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed("", 1)):
        assert usage.discover_sources() == ["claude", "codex"]
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest summarize/tests/test_usage.py -q -k discover`
Expected: FAIL — no attribute `discover_sources`.

- [ ] **Step 3: Implement**

Add to `summarize/usage.py`:

```python
_DEFAULT_SOURCES = ["claude", "codex"]


def discover_sources() -> list:
    """Run the unified report once; return ccusage namespaces that have data.

    Reads `metadata.agents` from every daily entry (the unified report cannot
    split per-source token counts, but it does list which agents contributed).
    Falls back to `_DEFAULT_SOURCES` on any failure.
    """
    _ensure_ccusage_global()
    cmd = _ccusage_cmd(["daily", "--json"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           shell=(sys.platform == "win32"))
    except (subprocess.TimeoutExpired, OSError):
        print("[warn] 来源发现失败，回退默认来源")
        return list(_DEFAULT_SOURCES)
    if r.returncode != 0:
        print("[warn] 来源发现失败，回退默认来源")
        return list(_DEFAULT_SOURCES)
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("[warn] 来源发现解析失败，回退默认来源")
        return list(_DEFAULT_SOURCES)
    if isinstance(data, list):
        data = {"daily": data}
    agents = set()
    for entry in data.get("daily", []):
        for a in entry.get("metadata", {}).get("agents", []):
            agents.add(a)
    return sorted(agents) if agents else list(_DEFAULT_SOURCES)
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q -k discover`
Expected: passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/usage.py summarize/tests/test_usage.py
git commit -m "feat(summarize): discover ccusage sources via metadata.agents"
```

---

### Task 4: Per-source fetch + save (`fetch_source_usage`, `save_usage_file`); remove codex-specific code

**Files:**
- Modify: `summarize/usage.py` — add `fetch_source_usage`, `save_usage_file`; delete `fetch_ccusage_full`, `_normalize_codex_date`, `_normalize_codex_data`, `fetch_codex_usage_full`, `save_codex_usage_file`
- Test: `summarize/tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_fetch_source_usage_normalizes():
    with mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "codex", "daily", "--json", "--breakdown"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed(json.dumps(CODEX_RAW))):
        out = usage.fetch_source_usage("codex")
    assert out["_source"] == "codex"
    assert out["daily"][0]["totalCost"] == 3.36


def test_fetch_source_usage_empty_returns_none():
    with mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "gemini", "daily"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed(json.dumps({"daily": [], "totals": {}}))):
        assert usage.fetch_source_usage("gemini") is None


def test_save_usage_file_roundtrip(tmp_path):
    norm = usage._normalize_usage(CLAUDE_RAW, "claude")
    with mock.patch.object(usage, "_get_device_name", return_value="dev1"):
        path = usage.save_usage_file(norm, "claude_code", tmp_path)
    assert path.name == "usage_claude_code_dev1.json"
    env = json.loads(path.read_text(encoding="utf-8"))
    assert env["source"] == "claude_code"
    assert env["usage"]["daily"][0]["date"] == "2026-06-13"
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest summarize/tests/test_usage.py -q -k "fetch_source or save_usage"`
Expected: FAIL — no attribute `fetch_source_usage`.

- [ ] **Step 3: Implement and delete**

Delete these functions from `summarize/usage.py`: `fetch_ccusage_full`, `_normalize_codex_date`, `_normalize_codex_data`, `fetch_codex_usage_full`, `save_codex_usage_file`. (Keep `fetch_ccusage` — fixed in Task 6. Keep `save_ccusage_file` — harmless, still imported.)

Add:

```python
def fetch_source_usage(source: str) -> Optional[dict]:
    """Fetch one source's full history via `ccusage <source> daily --json --breakdown`.

    Returns canonical normalized usage, or None on failure/empty.
    """
    cmd = _ccusage_cmd([source, "daily", "--json", "--breakdown"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           shell=(sys.platform == "win32"))
    except subprocess.TimeoutExpired:
        print(f"[warn] ccusage {source} 超时，跳过该来源")
        return None
    except OSError:
        print(f"[warn] ccusage {source} 无法执行，跳过该来源")
        return None
    if r.returncode != 0:
        print(f"[warn] ccusage {source} 退出码 {r.returncode}，跳过该来源")
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"[warn] ccusage {source} 输出解析失败，跳过该来源")
        return None
    if isinstance(data, list):
        data = {"daily": data, "totals": {}}
    if not data.get("daily"):
        return None
    norm = _normalize_usage(data, source)
    tot = norm["totals"]
    print(f"[info] ccusage {source}: {tot.get('totalTokens', 0):,} tokens, "
          f"${tot.get('totalCost', 0):.4f}")
    return norm


def save_usage_file(usage_data: dict, source_label: str, logs_dir: Path) -> Path:
    """Save one source's normalized usage to usage_<source_label>_<device>.json."""
    device_name = _get_device_name()
    envelope = {
        "device_name": device_name,
        "updated_at": datetime.now().isoformat(),
        "source": source_label,
        "usage": usage_data,
    }
    out_path = logs_dir / f"usage_{source_label}_{device_name}.json"
    _atomic_write(out_path, json.dumps(envelope, ensure_ascii=False, indent=2))
    return out_path
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/usage.py summarize/tests/test_usage.py
git commit -m "feat(summarize): per-source fetch+save; drop @ccusage/codex code"
```

---

### Task 5: `load_ccusage_for_date` reads new + legacy files

**Files:**
- Modify: `summarize/usage.py:352-379`
- Test: `summarize/tests/test_usage.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_load_reads_new_and_legacy(tmp_path):
    import datetime as _dt
    # new-format file
    norm = usage._normalize_usage(CLAUDE_RAW, "claude")
    (tmp_path / "usage_claude_code_dev1.json").write_text(json.dumps({
        "device_name": "dev1", "source": "claude_code", "usage": norm,
    }), encoding="utf-8")
    # legacy codex file
    codex_norm = usage._normalize_usage(CODEX_RAW, "codex")
    (tmp_path / "codex_usage_dev2.json").write_text(json.dumps({
        "device_name": "dev2", "ccusage": codex_norm, "_source": "codex",
    }), encoding="utf-8")

    got = usage.load_ccusage_for_date(tmp_path, _dt.date(2026, 6, 13))
    assert any(g["_source"] == "claude_code" for g in got)
    got2 = usage.load_ccusage_for_date(tmp_path, _dt.date(2026, 4, 1))
    assert any(g["_source"] == "codex" for g in got2)
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest summarize/tests/test_usage.py -q -k load`
Expected: FAIL — new `usage_*` files ignored by current globs.

- [ ] **Step 3: Implement**

Replace `load_ccusage_for_date` (352-379) with:

```python
def load_ccusage_for_date(logs_dir: Path, target_date: date) -> list[dict]:
    """Load per-source usage for a date from snapshot files.

    Reads new per-source files (usage_<label>_<device>.json) and, for backward
    compatibility, legacy ccusage_*.json (claude_code) / codex_usage_*.json (codex).
    Returns [{"device_name", "usage": {"daily": [...], "totals": {...}}, "_source"}].
    """
    result = []
    date_str = target_date.isoformat()

    def _emit(device_name, raw, source):
        daily = raw.get("daily", [])
        matched = [d for d in daily if d.get("date") == date_str]
        if matched:
            result.append({
                "device_name": device_name,
                "usage": {"daily": matched, "totals": matched[0]},
                "_source": source,
            })

    # New per-source files: envelope carries `source` + `usage`.
    for f in sorted(logs_dir.glob("usage_*_*.json")):
        try:
            env = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _emit(env.get("device_name", "unknown"),
              env.get("usage", {}), env.get("source", "unknown"))

    # Legacy files: envelope carries `ccusage`.
    legacy = [("ccusage_*.json", "claude_code"), ("codex_usage_*.json", "codex")]
    for pattern, source in legacy:
        for f in sorted(logs_dir.glob(pattern)):
            try:
                env = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            dev = env.get("device_name",
                          f.stem.replace("ccusage_", "").replace("codex_usage_", ""))
            _emit(dev, env.get("ccusage", {}), source)
    return result
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/usage.py summarize/tests/test_usage.py
git commit -m "feat(summarize): load per-source usage + legacy fallback"
```

---

### Task 6: `_refresh_usage_snapshots` discover→fetch loop; fix legacy `fetch_ccusage`

**Files:**
- Modify: `summarize/usage.py:23-35` (`_refresh_usage_snapshots`), `summarize/usage.py:83-148` (`fetch_ccusage`)
- Test: `summarize/tests/test_usage.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_refresh_snapshots_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "discover_sources", lambda: ["claude", "codex"])
    monkeypatch.setattr(usage, "fetch_source_usage",
                        lambda s: usage._normalize_usage(
                            CLAUDE_RAW if s == "claude" else CODEX_RAW, s))
    monkeypatch.setattr(usage, "_get_device_name", lambda: "devX")
    monkeypatch.setattr(usage, "_rclone_upload", lambda *a, **k: None)

    usage._refresh_usage_snapshots(tmp_path)
    names = sorted(p.name for p in tmp_path.glob("usage_*.json"))
    assert names == ["usage_claude_code_devX.json", "usage_codex_devX.json"]
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest summarize/tests/test_usage.py -q -k refresh`
Expected: FAIL — old refresh writes `ccusage_*` / `codex_usage_*`.

- [ ] **Step 3: Implement**

Replace `_refresh_usage_snapshots` (23-35):

```python
def _refresh_usage_snapshots(logs_dir: Path) -> None:
    """Discover sources with data, fetch each namespaced, save one file per source."""
    sources = discover_sources()
    print(f"[info] 发现 token 用量来源: {', '.join(sources) if sources else '(无)'}")
    for source in sources:
        data = fetch_source_usage(source)
        if not data:
            continue
        label = _source_label(source)
        path = save_usage_file(data, label, logs_dir)
        print(f"[ok] usage 快照已更新: {path}")
        _rclone_upload(path, subdirectory="logs")
```

Replace the command + parsing inside `fetch_ccusage`. Keep the signature and deprecation docstring, but replace its body (lines 94-148) with:

```python
    _ensure_ccusage_global()
    date_str = target_date.isoformat()
    cmd = _ccusage_cmd(["claude", "daily", "--since", date_str,
                        "--until", date_str, "--json", "--breakdown"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                shell=(sys.platform == "win32"))
    except (subprocess.TimeoutExpired, OSError):
        print("[warn] ccusage 不可用，跳过 token 统计")
        return None
    if result.returncode != 0:
        print(f"[warn] ccusage 执行失败 (exit {result.returncode})，跳过 token 统计")
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("[warn] ccusage 输出解析失败，跳过 token 统计")
        return None
    if isinstance(data, list):
        data = {"daily": data, "totals": {}}
    if not data.get("daily"):
        print(f"[info] ccusage: {target_date.isoformat()} 无 token 用量数据")
        return None
    return _normalize_usage(data, "claude")
```

Update the module docstring line 1 from "via ccusage (Claude Code) and @ccusage/codex (Codex)" to "via ccusage 20.x namespaced per-source commands".

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/usage.py summarize/tests/test_usage.py
git commit -m "feat(summarize): per-source snapshot refresh; fix legacy fetch"
```

---

### Task 7: Fix import lists in `daily.py` and `daily_summary.py`

**Files:**
- Modify: `summarize/daily.py:36-38`
- Modify: `summarize/daily_summary.py:65-71`

- [ ] **Step 1: Update `daily.py` imports (36-38)**

```python
from .usage import (fetch_ccusage, save_ccusage_file,
                    discover_sources, fetch_source_usage, save_usage_file,
                    load_ccusage_for_date, _merge_token_usages,
                    _refresh_usage_snapshots, _source_label)
```

- [ ] **Step 2: Update `daily_summary.py` re-export shim (65-71)**

Replace the `from summarize.usage import (...)` block's removed names. The new block:

```python
from summarize.usage import (  # noqa: F401
    _refresh_usage_snapshots,
    fetch_ccusage,
    save_ccusage_file,
    discover_sources,
    fetch_source_usage,
    save_usage_file,
```

Keep the remaining imported names (`load_ccusage_for_date`, `_merge_token_usages`, etc.) intact below. Removed: `fetch_ccusage_full`, `fetch_codex_usage_full`, `save_codex_usage_file`.

- [ ] **Step 3: Verify imports resolve**

Run: `python -c "import summarize.daily, summarize.daily_summary; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Run import contract test**

Run: `python -m pytest summarize/tests/test_imports.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/daily.py summarize/daily_summary.py
git commit -m "refactor(summarize): update usage import lists for 20.x"
```

---

### Task 8: Wire `daily.py` merge to per-source schema (with backward-compat aliases)

**Files:**
- Modify: `summarize/daily.py:656-694` (merge token usage block + chart call)
- Modify: `summarize/daily.py:755-811` (`cmd_legacy` usage block + chart call)

- [ ] **Step 1: Update the merge block (656-676)**

Replace lines 656-676 with:

```python
    # 合并多设备 token 用量，按来源分组（优先独立快照，旧 log 内嵌数据兜底）
    standalone_usages = load_ccusage_for_date(logs_dir, target_date)

    by_source_inputs = {}
    for u in standalone_usages:
        by_source_inputs.setdefault(u.get("_source", "unknown"), []).append(u)

    standalone_claude_devices = {
        u["device_name"] for u in by_source_inputs.get("claude_code", [])}
    for inline in device_token_usages:
        dev = inline.get("device_name", inline.get("device", "unknown"))
        if dev not in standalone_claude_devices:
            by_source_inputs.setdefault("claude_code", []).append(inline)

    token_usage_by_source = {
        source: _merge_token_usages(items)
        for source, items in by_source_inputs.items() if items
    }
    if token_usage_by_source:
        report["token_usage_by_source"] = token_usage_by_source
        # backward-compat aliases consumed by formatter/charts/weekly/monthly
        if "claude_code" in token_usage_by_source:
            report["token_usage"] = token_usage_by_source["claude_code"]
        if "codex" in token_usage_by_source:
            report["codex_token_usage"] = token_usage_by_source["codex"]
```

- [ ] **Step 2: Update the chart call (was 691-693)**

Replace the `from .charts import generate_daily_chart` + `chart_path = generate_daily_chart(...)` lines with:

```python
    from .charts import generate_daily_chart
    chart_path = generate_daily_chart(
        report.get("token_usage_by_source"), target_date,
        token_usage=report.get("token_usage"),
        codex_usage=report.get("codex_token_usage"))
    chart_name = chart_path.name if chart_path else None
```

(The new `generate_daily_chart` signature lands in Task 10; this call form is forward-compatible. See the Self-Review note on phase ordering.)

- [ ] **Step 3: Update `cmd_legacy` (the usage + chart block, ~755-811)**

Replace the block that loads `standalone_usages`, splits claude/codex, calls `fetch_ccusage`, and builds the chart, with:

```python
    standalone_usages = load_ccusage_for_date(logs_dir, target_date)
    by_source_inputs = {}
    for u in standalone_usages:
        by_source_inputs.setdefault(u.get("_source", "unknown"), []).append(u)

    if not by_source_inputs.get("claude_code"):
        fetched = fetch_ccusage(target_date)
        if fetched:
            by_source_inputs.setdefault("claude_code", []).append(
                {"device_name": _get_device_name(), "usage": fetched})

    token_usage_by_source = {
        s: _merge_token_usages(items)
        for s, items in by_source_inputs.items() if items}
    if token_usage_by_source:
        report["token_usage_by_source"] = token_usage_by_source
        if "claude_code" in token_usage_by_source:
            report["token_usage"] = token_usage_by_source["claude_code"]
        if "codex" in token_usage_by_source:
            report["codex_token_usage"] = token_usage_by_source["codex"]

    output_dir = _resolve_output_dir(args.output, "SUMMARIZE_REPORTS_DIR",
                                     "reports_dir", _DEFAULT_REPORTS_DIR)
    from .charts import generate_daily_chart
    chart_path = generate_daily_chart(
        report.get("token_usage_by_source"), target_date,
        token_usage=report.get("token_usage"),
        codex_usage=report.get("codex_token_usage"))
    chart_name = chart_path.name if chart_path else None
```

Note: `fetch_ccusage` now returns canonical `{"daily","totals","_source"}`; wrapping it as `{"device_name","usage"}` matches `_merge_token_usages` input.

- [ ] **Step 4: Smoke test**

Run: `python -c "import summarize.daily; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add summarize/daily.py
git commit -m "feat(summarize): per-source token_usage_by_source in daily merge"
```

**▶ END OF PHASE 1.** Run the full suite:
Run: `python -m pytest summarize/tests/ -q` → expect all pass.

---

## Phase 2 — Generalize downstream to all sources

### Task 9: `formatter.py` renders every source

**Files:**
- Modify: `summarize/formatter.py:270-290`
- Test: `summarize/tests/test_formatter.py`

- [ ] **Step 1: Add failing test**

Append to `summarize/tests/test_formatter.py`:

```python
def test_markdown_lists_all_sources():
    from summarize.formatter import generate_markdown
    from datetime import date
    report = {
        "summary": "s", "daily_overview": "", "tasks": [],
        "token_usage_by_source": {
            "claude_code": {"totals": {"totalCost": 1.0, "totalTokens": 1_000_000}},
            "gemini": {"totals": {"totalCost": 0.5, "totalTokens": 2_000_000}},
        },
    }
    md = generate_markdown(report, date(2026, 6, 14))
    assert "## Token Usage" in md
    assert "$1.50" in md            # combined total cost
    assert "3.0M tokens" in md      # combined total tokens
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest summarize/tests/test_formatter.py -q -k all_sources`
Expected: FAIL — current code only sums `token_usage` + `codex_token_usage`.

- [ ] **Step 3: Implement**

Replace `formatter.py` lines 270-290 with:

```python
    # Token 用量（chart-based rendering）
    by_source = report.get("token_usage_by_source")
    if not by_source:
        # backward compat: synthesize from legacy aliases
        by_source = {}
        if report.get("token_usage"):
            by_source["claude_code"] = report["token_usage"]
        if report.get("codex_token_usage"):
            by_source["codex"] = report["codex_token_usage"]

    if by_source:
        lines.append("## Token Usage\n")
        if _chart:
            lines.append(f"![Token Usage]({_chart})\n")

        _SOURCE_DISPLAY = {"claude_code": "Claude Code", "codex": "Codex",
                           "gemini": "Gemini", "copilot": "GitHub Copilot"}
        total_cost = 0.0
        total_tokens = 0
        per_source_lines = []
        for source in sorted(by_source):
            t = (by_source[source] or {}).get("totals", {})
            c = t.get("totalCost", 0)
            tok = t.get("totalTokens", 0)
            total_cost += c
            total_tokens += tok
            if c or tok:
                disp = _SOURCE_DISPLAY.get(source, source)
                per_source_lines.append(
                    f"- **{disp}**: ${c:.2f} — {tok / 1_000_000:.1f}M tokens")
        lines.append(f"**Total: ${total_cost:.2f}** — "
                     f"{total_tokens / 1_000_000:.1f}M tokens\n")
        if len(per_source_lines) > 1:
            lines.extend(per_source_lines)
            lines.append("")
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest summarize/tests/test_formatter.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/formatter.py summarize/tests/test_formatter.py
git commit -m "feat(summarize): render all token sources in daily markdown"
```

---

### Task 10: Generalize `charts.generate_daily_chart` to N sources

**Files:**
- Modify: `summarize/charts.py:76-253`
- Test: `summarize/tests/test_usage.py`

- [ ] **Step 1: Add a smoke test**

Append to `summarize/tests/test_usage.py`:

```python
def test_chart_multi_source_smoke(tmp_path):
    from summarize import charts
    from datetime import date
    raw_by_source = {
        "claude_code": usage._normalize_usage(CLAUDE_RAW, "claude"),
        "codex": usage._normalize_usage(CODEX_RAW, "codex"),
    }
    by_source = {k: usage._merge_token_usages([{"device_name": "d", "usage": v}])
                 for k, v in raw_by_source.items()}
    out = charts.generate_daily_chart(by_source, date(2026, 6, 13),
                                      output_dir=tmp_path)
    # matplotlib may be absent -> None acceptable; if present, a file exists
    assert out is None or out.exists()
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest summarize/tests/test_usage.py -q -k chart`
Expected: FAIL — old signature's first positional arg is `token_usage` (a single dict), so passing a `{source: usage}` dict mis-renders/raises.

- [ ] **Step 3: Implement**

Replace `charts.py` lines 76-253 (from the `_CLAUDE_PALETTE` constants through the end of `generate_daily_chart`) with:

```python
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
```

Keep the existing `_stacked_bar` helper above line 76 if present, OR delete it if now unused (run `grep -n "_stacked_bar" summarize/charts.py` — if only the definition remains, delete it). Update the module docstring (charts.py 1-10) to say "X-axis: source (Claude Code, Codex, Gemini, …)".

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest summarize/tests/test_usage.py -q -k chart`
Expected: passed.

- [ ] **Step 5: Commit**

```bash
git add summarize/charts.py summarize/tests/test_usage.py
git commit -m "feat(summarize): N-source daily usage chart"
```

---

### Task 11: Monthly aggregation + chart over all sources

**Files:**
- Modify: `summarize/monthly_summary.py:129` (`aggregate_token_usage` signature/body), `:557-575` (`_generate_chart`), `:927-949` (aggregation/assembly)

- [ ] **Step 1: Extend `aggregate_token_usage` to read per-source**

Change the signature (line 129) and add a `_get` helper at the top of the body:

```python
def aggregate_token_usage(daily_reports: list[dict],
                          usage_key: str = "token_usage",
                          source: Optional[str] = None) -> dict:
    """机械聚合日报中的 usage 字段。

    若给定 source，则从 report['token_usage_by_source'][source] 读取；
    否则回退到 usage_key（向后兼容旧报告）。
    """
    def _get(report):
        if source is not None:
            bs = report.get("token_usage_by_source") or {}
            if source in bs:
                return bs[source] or {}
            if source == "claude_code":
                return report.get("token_usage", {}) or {}
            if source == "codex":
                return report.get("codex_token_usage", {}) or {}
            return {}
        return report.get(usage_key, {}) or {}
```

Then replace the loop's first line `tu = report.get(usage_key, {}) or {}` with `tu = _get(report)`.

- [ ] **Step 2: Update assembly (927-949)**

Replace the three `aggregate_token_usage(...)` / `combine_usage_summaries(...)` lines with:

```python
    # 机械聚合（按来源）
    sources = set()
    for r in daily_reports:
        sources.update((r.get("token_usage_by_source") or {}).keys())
        if r.get("token_usage"):
            sources.add("claude_code")
        if r.get("codex_token_usage"):
            sources.add("codex")
    usage_by_source = {
        s: aggregate_token_usage(daily_reports, source=s) for s in sorted(sources)}
    combined_token_usage = combine_usage_summaries(*usage_by_source.values())
```

In the report dict assembly, replace the `"token_usage_summary"/"codex_token_usage_summary"/"combined_token_usage_summary"` lines with:

```python
        "token_usage_by_source_summary": usage_by_source,
        "token_usage_summary": usage_by_source.get("claude_code", {}),
        "codex_token_usage_summary": usage_by_source.get("codex", {}),
        "combined_token_usage_summary": combined_token_usage,
```

And replace the chart call:

```python
    if _has_usage_data(combined_token_usage):
        chart_path = _generate_chart(usage_by_source, year, month)
```

- [ ] **Step 3: Update `_generate_chart` (557-575)**

Replace with:

```python
def _generate_chart(usage_by_source: dict, year: int, month: int) -> Optional[Path]:
    """生成月报 usage 图表（单 PNG 三子图，按来源）。"""
    from .charts import generate_daily_chart
    from common.paths import IMAGES_DIR

    chart_input = {}
    for source, summary in (usage_by_source or {}).items():
        totals = summary.get("totals", {})
        if not totals:
            continue
        chart_input[source] = {
            "totals": totals,
            "modelBreakdowns": [{"modelName": n, **v}
                                for n, v in summary.get("model_breakdown", {}).items()],
        }
    if not chart_input:
        return None
    out = IMAGES_DIR / "summarize"
    return generate_daily_chart(chart_input, date(year, month, 1), output_dir=out)
```

The monthly markdown's `has_claude_usage`/`has_codex_usage` block still works via the retained `token_usage_summary`/`codex_token_usage_summary` aliases — no change needed there.

- [ ] **Step 4: Verify + tests**

Run: `python -c "import summarize.monthly_summary; print('ok')"` → `ok`
Run: `python -m pytest summarize/tests/test_imports.py -q` → all passed (signature preserved).

- [ ] **Step 5: Commit**

```bash
git add summarize/monthly_summary.py
git commit -m "feat(summarize): monthly aggregation over all token sources"
```

---

### Task 12: Weekly aggregation over all sources

**Files:**
- Modify: `summarize/weekly_summary.py:798-803` + the report assembly fields below it

- [ ] **Step 1: Update aggregation (798-803)**

Replace with:

```python
    # 机械聚合（按来源）
    sources = set()
    for r in daily_reports:
        sources.update((r.get("token_usage_by_source") or {}).keys())
        if r.get("token_usage"):
            sources.add("claude_code")
        if r.get("codex_token_usage"):
            sources.add("codex")
    usage_by_source = {
        s: aggregate_token_usage(daily_reports, source=s) for s in sorted(sources)}
    token_usage = usage_by_source.get("claude_code", {})
    codex_token_usage = usage_by_source.get("codex", {})
    combined_token_usage = combine_usage_summaries(*usage_by_source.values())
```

- [ ] **Step 2: Add the per-source field to the report dict**

In the `report = {...}` assembly, add alongside `token_usage_summary`:

```python
        "token_usage_by_source_summary": usage_by_source,
```

(Keep `token_usage_summary`, `codex_token_usage_summary`, `combined_token_usage_summary` — now sourced from `usage_by_source`.)

- [ ] **Step 3: Verify + tests**

Run: `python -c "import summarize.weekly_summary; print('ok')"` → `ok`
Run: `python -m pytest summarize/tests/ -q` → all passed.

- [ ] **Step 4: Commit**

```bash
git add summarize/weekly_summary.py
git commit -m "feat(summarize): weekly aggregation over all token sources"
```

---

## Phase 3 — Sync filter + docs

### Task 13: rclone include filter for new snapshot files

**Files:**
- Modify: `summarize/remote.py:131-133`

- [ ] **Step 1: Update the include patterns**

Replace lines 131-133:

```python
        cmd += ["--include", pattern,
                "--include", "usage_*.json",
                "--include", "ccusage_*.json",
                "--include", "codex_usage_*.json"]
        print(f"[info] rclone copy {src} → {local_logs_dir}/ "
              f"(filter: {pattern} + usage/ccusage/codex_usage)")
```

- [ ] **Step 2: Verify import**

Run: `python -c "import summarize.remote; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add summarize/remote.py
git commit -m "feat(summarize): sync per-source usage_*.json snapshots"
```

---

### Task 14: Documentation

**Files:**
- Modify: `CLAUDE.md`, `summarize/CLAUDE.md`, `README.md`, `summarize/README.md`, `summarize/tutorial.md`, `docs/external_dependencies_inventory.md`

- [ ] **Step 1: Find every stale mention**

Run: `grep -rn "@ccusage/codex\|ccusage_global_install\|codex_token_usage" CLAUDE.md summarize/CLAUDE.md README.md summarize/README.md summarize/tutorial.md docs/external_dependencies_inventory.md`

- [ ] **Step 2: Rewrite each hit**

- "Token usage tracking: ccusage + @ccusage/codex" → "Token usage tracking: ccusage 20.x namespaced per-source commands (Claude Code, Codex, Gemini, …)".
- Remove `ccusage_global_install` from the config-keys list in `summarize/CLAUDE.md` (~line 126).
- In `summarize/CLAUDE.md`, update the Report data-format line to add `token_usage_by_source`.
- In `docs/external_dependencies_inventory.md`, drop `@ccusage/codex` as a separate dependency; note ccusage `>=20` requirement and silent auto-upgrade.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md summarize/CLAUDE.md README.md summarize/README.md summarize/tutorial.md docs/external_dependencies_inventory.md
git commit -m "docs(summarize): document ccusage 20.x per-source migration"
```

---

## Final verification

- [ ] Run full module suite: `python -m pytest summarize/tests/ -q` → all pass.
- [ ] Run workflow gate: `python workflow/verify.py` → pass.
- [ ] Live smoke (optional, needs ccusage): `python -m summarize daily export --date 2026-06-14` → observe `[info] 发现 token 用量来源: ...` and `usage_<source>_<device>.json` files written under `outputs/logs/summarize/`.

---

## Self-Review

**Spec coverage:**
- Version guard (silent best-effort + npx fallback) → Task 2. ✓
- Source discovery via `metadata.agents` → Task 3. ✓
- Per-source namespaced fetch + generic normalization → Tasks 1, 4. ✓
- Remove `@ccusage/codex` / `_normalize_codex_*` → Task 4; imports → Task 7. ✓
- Per-source snapshots + load (new + legacy) → Tasks 4, 5, 6. ✓
- Legacy `fetch_ccusage` fixed → Task 6. ✓
- `token_usage_by_source` schema + backward-compat aliases → Task 8. ✓
- formatter / charts / weekly / monthly generalization → Tasks 9–12. ✓
- rclone filter → Task 13. ✓ Docs → Task 14. ✓

**Type consistency:** Canonical shape defined once at top. `_normalize_usage` → `save_usage_file`/`_merge_token_usages` → `load_ccusage_for_date` → `token_usage_by_source` all use it. `generate_daily_chart(usage_by_source, target_date, output_dir, token_usage, codex_usage)` consistent across Tasks 8, 10, 11. `aggregate_token_usage(daily_reports, usage_key, source)` consistent across Tasks 11, 12.

**Placeholders:** none — every code step contains full code.

**Phase-ordering caveat:** Task 8 calls `generate_daily_chart` with the new signature before Task 10 defines it. The call passes BOTH `token_usage_by_source` (positional) and `token_usage`/`codex_usage` kwargs. The OLD signature is `generate_daily_chart(token_usage, codex_usage, target_date, output_dir)` — so the Task 8 call would misbind under the old signature. **Therefore: execute Task 10 immediately after Task 8 (before exercising charts), or treat Tasks 8+10 as a paired unit.** Unit tests in Tasks 1–7 don't touch charts, so the suite stays green until Task 8; run Task 10 before any end-to-end daily run.
```
