"""Build the two writing-benchmark posts (concise version, grouped by tool).

They are NOT translations of each other: the Chinese page is the Chinese-prompt
run (zhbench.json), the English page is the English-prompt run (enbench.json),
same models and same settings. One small table per tool, then the full texts.

    python gen_post.py
"""
import json
from pathlib import Path

def _repo_root() -> Path:
    """Directory that contains both outputs/ and tools/, from this file upward."""
    here = Path(__file__).resolve().parent
    for p in (here, *here.parents):
        if (p / "outputs").is_dir() and (p / "tools").is_dir():
            return p
    raise SystemExit("cannot find repo root (directory containing outputs/ and tools/)")


ROOT = _repo_root()
REPORTS = ROOT / "outputs" / "reports"


def load(name):
    d = json.loads((REPORTS / name).read_text(encoding="utf-8"))
    return [r for r in d if not r.get("error") and r.get("text")]


ZH_DATA = load("zhbench.json")
EN_DATA = load("enbench.json")

DATE = "2026-08-26T10:00:00-04:00"  # must not be in the future or Hugo skips the page

ZH_PROMPT = ("请用中文写一个约500字的小说开头，以一位在战争爆炸中失去一条腿的芭蕾舞演员为主角，"
             "通过描写她在战后生活来侧面体现出她的挣扎。")
EN_PROMPT = ("Please write the opening of a novel in English, about 500 words, with a ballerina "
             "who lost a leg in a wartime explosion as the protagonist, conveying her struggle "
             "indirectly through a portrayal of her postwar life.")

# Display name per model; insertion order is the row order inside each group (newest first).
PRETTY = {
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6-astra": "GPT-6 Astra", "gpt-6-sol": "GPT-6 Sol", "gpt-6-luna": "GPT-6 Luna",
    "gpt-5.6-sol": "GPT-5.6 Sol", "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna", "gpt-5.5": "GPT-5.5", "gpt-5.4-mini": "GPT-5.4 Mini",
    "opus-5.5": "Opus 5.5", "fable-high": "Fable 5.1 (effort high)", "opus": "Opus 5",
    "sonnet": "Sonnet 5", "haiku": "Haiku 4.5",
    "grok-4.7-high": "Grok 4.7 High", "grok-4.6-high": "Grok 4.6 High",
    "composer-2.5": "Composer 2.5", "gemini-3.7-flash": "Gemini 3.7 Flash",
    "gemma4:26b": "Gemma4 26B", "gemma4:12b": "Gemma4 12B",
    "qwen3.8-sum:latest": "Qwen3.8 27B", "qwen3.6-sum:latest": "Qwen3.6 36B",
}
ORDER = list(PRETTY)
GROUPS = [("codex", "Codex (OpenAI)"), ("claude", "Claude Code (Anthropic)"),
          ("cursor", "Cursor"), ("ollama", "本地 Ollama / Local Ollama")]


def model(r):
    return r["key"].split("/", 1)[1]


def group(data, tool):
    rows = [r for r in data if r["key"].split("/", 1)[0] == tool]
    return sorted(rows, key=lambda r: ORDER.index(model(r)) if model(r) in ORDER else 99)


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def row(r, zh):
    s = r["stats"]
    size = s["han_chars"] if zh else s["words"]
    speed = r.get("decode_tps") if r["kind"] == "ollama" else r.get("effective_tps")
    hits = ("、" if zh else ", ").join(dict.fromkeys(w.lower() for w in s["on_the_nose"])) \
        or ("—")
    return [PRETTY.get(model(r), model(r)), size, f"{r['wall_s']:.0f} s",
            r["output_tokens"], f"{speed} tok/s" if speed else "—", hits]


def body(data, zh):
    h = (["模型", "字数", "耗时", "输出 tokens", "速度", "直接点题的词"] if zh else
         ["Model", "Words", "Time", "Output tokens", "Speed", "Theme named outright"])
    parts = []
    for tool, title in GROUPS:
        rows = group(data, tool)
        if not rows:
            continue
        title = title.split(" / ")[0 if zh else -1]
        parts.append(f"### {title}\n\n" + table(h, [row(r, zh) for r in rows]))
    return "\n\n".join(parts)


def texts(data, zh):
    out = []
    for tool, title in GROUPS:
        rows = group(data, tool)
        if not rows:
            continue
        out.append(f"### {title.split(' / ')[0 if zh else -1]}\n")
        for r in rows:
            n = r["stats"]["han_chars"] if zh else r["stats"]["words"]
            cap = f"{n} 字" if zh else f"{n} words"
            out.append(f"<details>\n<summary><b>{PRETTY.get(model(r), model(r))}</b> — {cap}"
                       f"</summary>\n\n{r['text'].strip()}\n\n</details>\n")
    return "\n".join(out)


ZH = f"""---
title: "模型中文能力大比拼"
date: {DATE}
draft: false
gadget_generated: true
---

同一条 prompt，{len(ZH_DATA)} 个模型各写一遍，按调用工具分组。英文版是另一次独立实验，不是本页翻译。

```text
{ZH_PROMPT}
```

**条件**：每个模型只跑 1 次，无 system prompt，数字按量级读。云端模型经各自的 Agent CLI
（`codex exec` / `claude -p` / `cursor-agent --print`）在空目录中串行调用，耗时含 CLI 启动；
本地模型在 RTX 5090 上冷启动，速度为纯解码速度，两类速度不可互比。
Fable 5.1 显式 `--effort high`，其余 Claude 模型为默认 effort。
「直接点题的词」匹配 `挣扎`、`痛苦不堪`、`内心的煎熬`、`无法接受`——题目要求侧面体现，命中即正面点题。

## 结果

{body(ZH_DATA, True)}

## 全部正文

{texts(ZH_DATA, True)}

## 复现

`zhbench.py`（跑测，断点续跑）→ `zhbench.json`（完整记录）→ `gen_post.py`（生成本页）。
"""

EN = f"""---
title: "Model English Writing Showdown"
date: {DATE}
draft: false
gadget_generated: true
---

One prompt, {len(EN_DATA)} models, one run each, grouped by the tool that called them. This is a
separate run from the Chinese page, not a translation of it.

```text
{EN_PROMPT}
```

**Conditions**: one run per model, no system prompt — read the numbers as orders of magnitude.
Cloud models ran serially through their agent CLIs (`codex exec` / `claude -p` /
`cursor-agent --print`) in an empty directory, so time includes CLI startup. Local models ran cold
on an RTX 5090 and their speed is pure decode, so the two speeds are not comparable. Fable 5.1 had
`--effort high` pinned; the other Claude models used the default effort. "Theme named outright"
matches *struggle*, *unbearable*, *agony*, *anguish*, *torment* — the prompt asked for indirection.

## Results

{body(EN_DATA, False)}

## Full texts

{texts(EN_DATA, False)}

## Reproducing

`enbench.py` (run, resumable) → `enbench.json` (full record) → `gen_post.py` (builds this page).
"""

SITE = ROOT / "tools" / "website" / "content" / "posts"
REPORTS.mkdir(parents=True, exist_ok=True)
for d in (REPORTS, SITE):
    (d / "chinese-writing-benchmark.zh.md").write_text(ZH, encoding="utf-8")
    (d / "chinese-writing-benchmark.md").write_text(EN, encoding="utf-8")
print(f"zh: {len(ZH_DATA)} runs -> chinese-writing-benchmark.zh.md")
print(f"en: {len(EN_DATA)} runs -> chinese-writing-benchmark.md")
