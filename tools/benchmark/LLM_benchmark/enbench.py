"""English counterpart of zhbench.py: same 16 models, same settings, English prompt.

Not a translation of the Chinese run -- a parallel experiment. Results go to
enbench.json so the two runs stay independent.

Stdlib only. Resumable: results are written after every run.
    python enbench.py --only gemma4:12b
    python enbench.py --skip-cli
"""
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

def _repo_root() -> Path:
    """Directory that contains both outputs/ and tools/, from this file upward."""
    here = Path(__file__).resolve().parent
    for p in (here, *here.parents):
        if (p / "outputs").is_dir() and (p / "tools").is_dir():
            return p
    raise SystemExit("cannot find repo root (directory containing outputs/ and tools/)")


REPORTS = _repo_root() / "outputs" / "reports"
OUT = REPORTS / "enbench.json"

PROMPT = (
    "Please write the opening of a novel in English, about 500 words, with a ballerina who lost a "
    "leg in a wartime explosion as the protagonist, conveying her struggle indirectly through a "
    "portrayal of her postwar life."
)

OLLAMA_MODELS = ["gemma4:12b", "gemma4:26b", "qwen3.8-sum:latest", "qwen3.6-sum:latest"]

CLI_PROMPT = PROMPT

# Full paths to the .cmd shims: CreateProcess does not do PATHEXT resolution for
# extensionless npm shims the way the shell does.
CURSOR = r"C:\Users\tongt\AppData\Local\cursor-agent\cursor-agent.cmd"
NPM = r"C:\Users\tongt\AppData\Roaming\npm"

CODEX = [NPM + r"\codex.cmd", "exec", "--json", "--sandbox", "read-only",
         "--skip-git-repo-check", "-c", 'model_reasoning_effort="medium"']
# No --bare: it drops the OAuth settings source and the run 401s.
CLAUDE = ["claude", "-p", CLI_PROMPT, "--output-format", "json",
          "--disallowed-tools", "Bash,Edit,Write,Read,Glob,Grep"]
CUR = [CURSOR, "--print", "--output-format", "json", "--mode", "ask", "--trust"]

CLI_JOBS = [
    ("codex/gpt-6.1-sol", CODEX + ["-m", "gpt-6.1-sol", CLI_PROMPT]),
    ("codex/gpt-6-astra", CODEX + ["-m", "gpt-6-astra", CLI_PROMPT]),
    ("codex/gpt-6-sol", CODEX + ["-m", "gpt-6-sol", CLI_PROMPT]),
    ("codex/gpt-6-luna", CODEX + ["-m", "gpt-6-luna", CLI_PROMPT]),
    ("codex/gpt-5.6-sol", CODEX + ["-m", "gpt-5.6-sol", CLI_PROMPT]),
    ("codex/gpt-5.6-terra", CODEX + ["-m", "gpt-5.6-terra", CLI_PROMPT]),
    ("codex/gpt-5.6-luna", CODEX + ["-m", "gpt-5.6-luna", CLI_PROMPT]),
    ("codex/gpt-5.5", CODEX + ["-m", "gpt-5.5", CLI_PROMPT]),
    ("codex/gpt-5.4-mini", CODEX + ["-m", "gpt-5.4-mini", CLI_PROMPT]),
    # The other claude jobs run at the CLI's default effort; this one is pinned.
    ("claude/fable-high", CLAUDE + ["--model", "claude-fable-5-1", "--effort", "high"]),
    ("claude/opus-5.5", CLAUDE + ["--model", "claude-opus-5-5"]),
    ("claude/opus", CLAUDE + ["--model", "opus"]),
    ("claude/sonnet", CLAUDE + ["--model", "sonnet"]),
    ("claude/haiku", CLAUDE + ["--model", "haiku"]),
    ("cursor/composer-2.5", CUR + ["--model", "composer-2.5", CLI_PROMPT]),
    ("cursor/grok-4.7-high", CUR + ["--model", "grok-4.7-high", CLI_PROMPT]),
    ("cursor/grok-4.6-high", CUR + ["--model", "cursor-grok-4.6-high", CLI_PROMPT]),
    ("cursor/gemini-3.7-flash", CUR + ["--model", "gemini-3.7-flash-high", CLI_PROMPT]),
]


# ---------- English text stats (mirrors zhbench.py's Chinese ones) ----------

WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
ADVERB = re.compile(r"\b[A-Za-z]{3,}ly\b")
NON_ASCII = re.compile(r"[^\x00-\x7f]")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27bf]")
MARKDOWN = re.compile(r"(^|\n)\s*(#{1,6} |\* |- |\d+\. |```)")
ON_THE_NOSE = re.compile(r"\b(struggl\w*|unbearable|agony|anguish|torment\w*)\b", re.I)


def en_stats(text: str) -> dict:
    words = WORD.findall(text)
    sentences = [s for s in re.split(r"[.!?…\n]+", text) if WORD.search(s)]
    lens = [len(WORD.findall(s)) for s in sentences] or [0]
    lower = [w.lower() for w in words]
    return {
        "words": len(words),
        "unique_words": len(set(lower)),
        "type_token_ratio": round(len(set(lower)) / len(words), 3) if words else None,
        "non_ascii": len(NON_ASCII.findall(text)),
        "emoji": len(EMOJI.findall(text)),
        "markdown": bool(MARKDOWN.search(text)),
        "sentences": len(sentences),
        "median_sentence_words": statistics.median(lens),
        "max_sentence_words": max(lens),
        "ly_adverbs": len(ADVERB.findall(text)),
        "on_the_nose": ON_THE_NOSE.findall(text),
    }


# ---------- GPU sampling ----------

def gpu_used_mib() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return -1


def ollama_ps() -> str:
    try:
        return subprocess.run(["ollama", "ps"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return ""


def ollama_show(model: str) -> dict:
    """architecture / parameters / context length / quantization, from `ollama show`."""
    info = {}
    try:
        out = subprocess.run(["ollama", "show", model], capture_output=True, text=True,
                             timeout=60).stdout
    except Exception:
        return info
    # First occurrence wins: multimodal models print a second projector block.
    for line in out.splitlines():
        p = line.split()
        k = None
        if len(p) == 2 and p[0] in ("architecture", "parameters", "quantization"):
            k, v = p[0], p[1]
        elif len(p) == 3 and p[0] in ("context", "embedding") and p[1] == "length":
            k, v = p[0] + "_length", p[2]
        if k and k not in info:
            info[k] = v
    return info


class Probe(threading.Thread):
    """Sample nvidia-smi peak AND the target model's own `ollama ps` row."""

    def __init__(self, model: str):
        super().__init__(daemon=True)
        self.model = model.split(":")[0]
        self.peak = 0
        self.ps_row = ""
        self.others = set()
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, gpu_used_mib())
            for line in ollama_ps().splitlines()[1:]:
                if not line.strip():
                    continue
                name = line.split()[0]
                if name.startswith(self.model):
                    self.ps_row = " ".join(line.split())
                else:
                    self.others.add(name)
            self._stop.wait(0.4)

    def stop(self):
        self._stop.set()
        self.join(timeout=3)
        return self.peak, self.ps_row, sorted(self.others)


# ---------- runners ----------

def run_ollama(model: str) -> dict:
    for m in OLLAMA_MODELS:  # cold start: evict everything first
        subprocess.run(["ollama", "stop", m], capture_output=True, timeout=60)
    time.sleep(2)
    baseline = gpu_used_mib()

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "think": False,
    }).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})

    probe = Probe(model)
    probe.start()
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        probe.stop()
        return {"key": f"ollama/{model}", "kind": "ollama", "error": repr(e)}
    wall = time.perf_counter() - t0
    peak, ps, others = probe.stop()

    text = data.get("message", {}).get("content", "")
    ns = 1e9
    ev, evd = data.get("eval_count", 0), data.get("eval_duration", 0)
    pe, ped = data.get("prompt_eval_count", 0), data.get("prompt_eval_duration", 0)
    return {
        "key": f"ollama/{model}", "kind": "ollama", "text": text, "wall_s": round(wall, 2),
        "meta": ollama_show(model),
        "load_s": round(data.get("load_duration", 0) / ns, 2),
        "total_s": round(data.get("total_duration", 0) / ns, 2),
        "prompt_tokens": pe,
        "prefill_tps": round(pe / (ped / ns), 1) if ped else None,
        "output_tokens": ev,
        "decode_tps": round(ev / (evd / ns), 1) if evd else None,
        "gpu_baseline_mib": baseline, "gpu_peak_mib": peak,
        "gpu_delta_mib": peak - baseline if peak > 0 and baseline > 0 else None,
        "ollama_ps": ps, "coresident": others,
        "stats": en_stats(text),
    }


USAGE_KEYS = {
    "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens",
    "total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens",  # cursor
    "prompt_tokens", "completion_tokens",
    "ttft_ms", "duration_ms", "duration_api_ms", "num_turns",
}


def _dig(obj, keys):
    """Find the first int under any of `keys`, anywhere in a nested structure."""
    found = {}
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and isinstance(v, int) and k not in found:
                    found[k] = v
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
    return found


def _longest_text(obj) -> str:
    best, stack = "", [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, str):
            if len(o) > len(best):
                best = o
        elif isinstance(o, dict):
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return best


def parse_cli(key: str, stdout: str) -> tuple:
    """-> (text, usage_dict). Each CLI has its own shape; fall through gracefully."""
    if key.startswith("codex"):
        text, last_usage = "", {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            got = _dig(ev, USAGE_KEYS)
            if got:
                last_usage = got
            msg = ev.get("msg", ev)
            if isinstance(msg, dict) and msg.get("type") in ("agent_message", "item.completed"):
                cand = msg.get("message") or msg.get("item", {}).get("text") or ""
                if len(cand) > len(text):
                    text = cand
        if not text:
            text = _longest_text([json.loads(l) for l in stdout.splitlines()
                                  if l.strip().startswith("{")] or stdout)
        return text, last_usage

    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        d = None
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if d is None:
        return stdout, {}
    return _longest_text(d), _dig(d, USAGE_KEYS)


def reported_model(stdout: str) -> str:
    """Which model the CLI says it actually used (claude reports `modelUsage`)."""
    for line in [stdout] + stdout.splitlines():
        if '"modelUsage"' not in line:
            continue
        try:
            d = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        stack = [d]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if o.get("modelUsage"):
                    return ", ".join(o["modelUsage"])
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return ""


def run_cli(key: str, argv: list, workdir: str) -> dict:
    env = dict(os.environ)
    env.pop("SSL_CERT_FILE", None)  # Git Bash points it at a missing cacert.pem
    t0 = time.perf_counter()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=workdir, env=env, timeout=900)
    except subprocess.TimeoutExpired:
        return {"key": key, "kind": "cli", "error": "timeout 900s",
                "wall_s": round(time.perf_counter() - t0, 2)}
    wall = time.perf_counter() - t0
    text, usage = parse_cli(key, r.stdout)
    out_tok = usage.get("output_tokens") or usage.get("outputTokens") \
        or usage.get("completion_tokens")
    return {
        "key": key, "kind": "cli", "text": text, "wall_s": round(wall, 2),
        "cli_version": CLI_VERSIONS.get(key.split("/")[0], ""),
        "model_reported": reported_model(r.stdout),
        "returncode": r.returncode, "usage": usage,
        "output_tokens": out_tok,
        "effective_tps": round(out_tok / wall, 1) if out_tok else None,
        "stderr_tail": r.stderr[-500:] if r.stderr else "",
        "stats": en_stats(text),
    }


CLI_BIN = {"codex": NPM + r"\codex.cmd", "claude": "claude", "cursor": CURSOR}
CLI_VERSIONS = {}


def cli_versions():
    for tool, exe in CLI_BIN.items():
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                 timeout=120).stdout.strip().splitlines()
            CLI_VERSIONS[tool] = out[-1].strip() if out else ""
        except Exception as e:
            CLI_VERSIONS[tool] = repr(e)


# ---------- main ----------

def save(results: list):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    skip_cli = "--skip-cli" in sys.argv
    skip_ollama = "--skip-ollama" in sys.argv

    results = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    done = {r["key"] for r in results
            if not r.get("error") and r.get("returncode") in (0, None)}

    if not skip_ollama:
        for m in OLLAMA_MODELS:
            key = f"ollama/{m}"
            if (only and only not in m) or key in done:
                continue
            print(f"[ollama] {m} ...", flush=True)
            results = [r for r in results if r["key"] != key]
            results.append(run_ollama(m))
            save(results)
            r = results[-1]
            print(f"  -> {r.get('decode_tps')} tok/s, {r.get('output_tokens')} tok, "
                  f"{r['stats']['words']} words, peak {r.get('gpu_peak_mib')} MiB", flush=True)

    if not skip_cli:
        cli_versions()
        print(f"cli versions: {CLI_VERSIONS}")
        workdir = tempfile.mkdtemp(prefix="enbench_")
        print(f"CLI sandbox cwd: {workdir}", flush=True)
        for key, argv in CLI_JOBS:
            if (only and only not in key) or key in done:
                continue
            print(f"[cli] {key} ...", flush=True)
            results = [r for r in results if r["key"] != key]
            results.append(run_cli(key, argv, workdir))
            save(results)
            r = results[-1]
            print(f"  -> {r.get('wall_s')}s, {r.get('output_tokens')} tok, "
                  f"{r['stats']['words']} words, rc={r.get('returncode')}", flush=True)
        leftovers = list(Path(workdir).iterdir())
        print(f"sandbox leftovers: {[p.name for p in leftovers] or 'none'}")

    save(results)
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
