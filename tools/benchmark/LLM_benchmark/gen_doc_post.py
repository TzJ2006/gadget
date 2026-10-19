"""Build the bilingual README-tutorial post from docbench.json (concise, grouped by tool).

Data only -- one small table per tool and the full outputs. No rankings, no
commentary. Re-run after any docbench.py run:
    python gen_doc_post.py
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
DATA = json.loads((REPORTS / "docbench.json").read_text(encoding="utf-8"))
DATA = [r for r in DATA if not r.get("error") and r.get("text")]
N = len(DATA)

DATE = "2026-08-26T10:00:00-04:00"  # must not be in the future or Hugo skips the page

PROMPT_HEAD = (
    "下面是开源项目 gadget 的 README。请你完成两件事：\n"
    "1. 先用中文总结这个项目：它是什么、仓库结构、每个工具分别做什么。\n"
    "2. 然后写一份详细的中文使用教程，面向第一次接触这个项目的人，"
    "覆盖环境准备、安装、配置，以及每个工具的典型用法（给出可以直接复制的命令）。\n"
    "只依据 README 里写到的内容，不要编造 README 中没有出现的命令或参数。\n\n"
    "===== README.md =====\n<README.md 全文，20 768 字符>"
)

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

# The sixteen README facts docbench.py checks: key -> short name shown when missed.
FACTS = {
    "install_all": '`.[all]`', "translator_extra": "`[translator]`",
    "summarize_cli": "`python -m summarize`", "research_cli": "`research_scout.py`",
    "benchmark_cd": "`cd tools/benchmark`", "website_update": "`update.sh`",
    "translator_cli": "`python -m translator`", "config_json": "`config.json`",
    "gadget_config_env": "`GADGET_CONFIG`", "api_backends": "`--api`",
    "outputs_dir": "`outputs/`", "sync_script": "`sync.py`", "tokens_secret": "`tokens/`",
    "python_310": "Python 3.10+", "gpl3": "GPL-3", "ai_companion": "ai-companion",
}


def model(r):
    return r["key"].split("/", 1)[1]


def name(r):
    return PRETTY.get(model(r), model(r))


def group(tool):
    rows = [r for r in DATA if r["key"].split("/", 1)[0] == tool]
    return sorted(rows, key=lambda r: ORDER.index(model(r)) if model(r) in ORDER else 99)


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def row(r):
    s = r["stats"]
    speed = r.get("decode_tps") if r["kind"] == "ollama" else r.get("effective_tps")
    missed = [v for k, v in FACTS.items() if k not in s["facts_hit"]]
    return [name(r), f"{s['chars']:,}", f"{r['wall_s']:.0f} s", f"{r['output_tokens']:,}",
            f"{speed} tok/s" if speed else "—", s["commands"], s["commands_invented"] or "—",
            f"{len(s['facts_hit'])}/{len(FACTS)}", " ".join(missed) or "—"]


def body(zh):
    h = (["模型", "字符数", "耗时", "输出 tokens", "速度", "命令数", "README 中无的命令",
          "事实点", "漏掉的"] if zh else
         ["Model", "Chars", "Time", "Output tokens", "Speed", "Commands", "Not in README",
          "Facts", "Missed"])
    parts = []
    for tool, title in GROUPS:
        rows = group(tool)
        if rows:
            parts.append(f"### {title.split(' / ')[0 if zh else -1]}\n\n"
                         + table(h, [row(r) for r in rows]))
    return "\n\n".join(parts)


def texts(zh):
    out = []
    for tool, title in GROUPS:
        rows = group(tool)
        if not rows:
            continue
        out.append(f"### {title.split(' / ')[0 if zh else -1]}\n")
        for r in rows:
            s = r["stats"]
            cap = (f"{s['chars']:,} 字符 · 事实点 {len(s['facts_hit'])}/{len(FACTS)}" if zh else
                   f"{s['chars']:,} chars · {len(s['facts_hit'])}/{len(FACTS)} facts")
            out.append(f"<details>\n<summary><b>{name(r)}</b> — {cap}</summary>\n\n"
                       f"{r['text'].strip()}\n\n</details>\n")
    return "\n".join(out)


ZH = f"""---
title: "{N} 个模型，同一份 README"
date: {DATE}
draft: false
gadget_generated: true
---

把 gadget 的 `README.md`（20 768 字符）原样交给 {N} 个模型，要求先总结项目、再写中文使用教程。按调用工具分组。

```text
{PROMPT_HEAD}
```

**条件**：每个模型只跑 1 次，无 system prompt，数字按量级读。云端模型经各自的 Agent CLI
（`codex exec` / `claude -p` / `cursor-agent --print`）在空目录中串行调用，prompt 走 stdin，耗时含 CLI 启动；
本地模型在 RTX 5090 上冷启动，速度为纯解码速度，两类速度不可互比。
Fable 5.1 显式 `--effort high`，其余 Claude 模型为默认 effort。

**指标**（全部正则计算）：「命令数」是代码块里以 `pip` / `python` / `cd` / `bash` 等开头的行；
「README 中无的命令」是去掉注释、压缩空白后在 README 原文里找不到的命令；
「事实点」是 {len(FACTS)} 个能在 README 里逐字查到的事实被提到了几个，「漏掉的」列出没提到的。

## 结果

{body(True)}

## 全部输出

{texts(True)}

## 复现

`docbench.py`（跑测，断点续跑）→ `docbench.json`（完整记录）→ `gen_doc_post.py`（生成本页）。
"""

EN = f"""---
title: "{N} Models, One README"
date: {DATE}
draft: false
gadget_generated: true
---

The gadget `README.md` (20,768 characters) handed verbatim to {N} models, asking for a project
summary and then a usage tutorial in Chinese. Grouped by the tool that called them.

```text
{PROMPT_HEAD}
```

> *Summarize the project in Chinese, then write a detailed Chinese tutorial for a first-time user
> with copy-pasteable commands. Use only what the README says; do not invent commands or flags.*

**Conditions**: one run per model, no system prompt — read the numbers as orders of magnitude.
Cloud models ran serially through their agent CLIs (`codex exec` / `claude -p` /
`cursor-agent --print`) in an empty directory, prompt on stdin, so time includes CLI startup. Local
models ran cold on an RTX 5090 and their speed is pure decode, so the two speeds are not comparable.
Fable 5.1 had `--effort high` pinned; the other Claude models used the default effort.

**Metrics** (all regex): "Commands" counts code-block lines starting with `pip`, `python`, `cd`,
`bash` and similar; "Not in README" counts those that, comments stripped and whitespace collapsed,
cannot be found in the README; "Facts" is how many of {len(FACTS)} word-for-word README facts the
output mentions, and "Missed" lists the rest.

## Results

{body(False)}

## Full outputs

{texts(False)}

## Reproducing

`docbench.py` (run, resumable) → `docbench.json` (full record) → `gen_doc_post.py` (builds this page).
"""

SITE = ROOT / "tools" / "website" / "content" / "posts"
REPORTS.mkdir(parents=True, exist_ok=True)
for d in (REPORTS, SITE):
    (d / "readme-tutorial-benchmark.zh.md").write_text(ZH, encoding="utf-8")
    (d / "readme-tutorial-benchmark.md").write_text(EN, encoding="utf-8")
print(f"{N} runs -> readme-tutorial-benchmark.zh.md / .md")
