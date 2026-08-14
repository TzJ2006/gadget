"""Token usage tracking via ccusage 20.x namespaced per-source commands.

Provides functions to fetch, save, load, merge, and normalize token usage
snapshots from multiple devices and sources.
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from common.io import atomic_write as _atomic_write

from .config import _get_device_name
from .remote import _rclone_upload


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


def _merge_usage_history(old: dict, new: dict) -> dict:
    """Union old+new daily entries by date (new wins); recompute totals.

    ccusage only sees the agent CLIs' local session logs, which are deleted
    after ~30 days (Claude Code cleanupPeriodDays) — every fetch is a rolling
    window. Accumulating here is what preserves history beyond that horizon.
    """
    by_date = {e["date"]: e for e in old.get("daily", []) if e.get("date")}
    by_date.update({e["date"]: e for e in new.get("daily", []) if e.get("date")})
    daily = [by_date[d] for d in sorted(by_date)]

    totals, models = {}, {}
    for e in daily:
        for k, v in e.items():
            if isinstance(v, (int, float)) and k != "date":
                totals[k] = totals.get(k, 0) + v
        for mb in e.get("modelBreakdowns", []):
            agg = models.setdefault(mb.get("modelName", "?"),
                                    {"modelName": mb.get("modelName", "?")})
            for k, v in mb.items():
                if isinstance(v, (int, float)):
                    agg[k] = agg.get(k, 0) + v
    if models:
        totals["modelBreakdowns"] = list(models.values())
    return {**new, "daily": daily, "totals": totals}


def save_usage_file(usage_data: dict, source_label: str, logs_dir: Path) -> Path:
    """Save one source's normalized usage to usage_<source_label>_<device>.json.

    Merges with the existing file so dates that have already scrolled out of
    ccusage's window survive (see _merge_usage_history).
    """
    device_name = _get_device_name()
    out_path = logs_dir / f"usage_{source_label}_{device_name}.json"
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                prev = json.load(f).get("usage", {})
            usage_data = _merge_usage_history(prev, usage_data)
        except (OSError, json.JSONDecodeError):
            pass  # unreadable previous file — write fresh rather than fail export
    envelope = {
        "device_name": device_name,
        "updated_at": datetime.now().isoformat(),
        "source": source_label,
        "usage": usage_data,
    }
    _atomic_write(out_path, json.dumps(envelope, ensure_ascii=False, indent=2))
    return out_path


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


def _merge_token_usages(device_usages: list[dict]) -> dict:
    """合并多台设备的 ccusage 原始数据，汇总 daily 条目和 totals。

    输入: [{"device_name": "...", "usage": <raw ccusage JSON>}, ...]
    输出: 合并后的 ccusage 风格 JSON，额外附带 per_device 明细。
    """
    all_daily = []
    per_device = []

    for item in device_usages:
        raw = item["usage"]
        device_name = item.get("device_name", "unknown")
        for day in raw.get("daily", []):
            all_daily.append(day)
        # 保留每设备的 totals 作为明细
        totals = raw.get("totals", {})
        if totals:
            per_device.append({"device": device_name, **totals})

    if not all_daily:
        return {"daily": [], "totals": {}, "per_device": per_device}

    # 汇总所有 daily 条目 → 合并的 totals 和 modelBreakdowns
    agg_keys = ("inputTokens", "outputTokens", "cacheCreationTokens",
                "cacheReadTokens", "totalTokens", "reasoningOutputTokens")
    merged_totals = {k: 0 for k in agg_keys}
    merged_totals["totalCost"] = 0.0
    model_agg = {}

    for day in all_daily:
        for k in agg_keys:
            merged_totals[k] += day.get(k, 0)
        merged_totals["totalCost"] += day.get("totalCost", 0)

        for mb in day.get("modelBreakdowns", []):
            model = mb.get("modelName", "unknown")
            if model not in model_agg:
                model_agg[model] = {
                    "modelName": model,
                    "inputTokens": 0, "outputTokens": 0,
                    "cacheCreationTokens": 0, "cacheReadTokens": 0,
                    "reasoningOutputTokens": 0,
                    "cost": 0.0,
                }
            for k in ("inputTokens", "outputTokens",
                       "cacheCreationTokens", "cacheReadTokens",
                       "reasoningOutputTokens"):
                model_agg[model][k] += mb.get(k, 0)
            model_agg[model]["cost"] += mb.get("cost", 0)

    # 清理零值的 reasoningOutputTokens（Claude Code 不使用此字段）
    if merged_totals["reasoningOutputTokens"] == 0:
        del merged_totals["reasoningOutputTokens"]
    for m in model_agg.values():
        if m["reasoningOutputTokens"] == 0:
            del m["reasoningOutputTokens"]

    return {
        "daily": all_daily,
        "totals": merged_totals,
        "modelBreakdowns": list(model_agg.values()),
        "per_device": per_device,
    }
