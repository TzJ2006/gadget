"""Run one translation in this interpreter.

Empty input prints usage and does not load a model. A request names the model
and endpoint explicitly; this module does not pick another provider.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("用法: python -m translator.text_entry < json", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    if not raw.strip():
        print("用法: python -m translator.text_entry < json", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("用法: 请求必须是 JSON 对象", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("用法: 请求必须是 JSON 对象", file=sys.stderr)
        return 2
    model = str(payload.get("model") or "").strip()
    base = str(payload.get("base_url") or "").strip()
    if not model or not base:
        print("未配置翻译模型或端点", file=sys.stderr)
        return 2
    text = payload.get("text")
    source = payload.get("source_path")
    if text is None and not source:
        print("用法: 需要 text 或 source_path", file=sys.stderr)
        return 2
    try:
        import os

        os.environ["OLLAMA_HOST"] = base.rstrip("/")
        from common.engine.ollama import OllamaEngine
        from translator.core import translate_text

        engine = OllamaEngine(model)
        if not callable(getattr(engine, "generate_batch", None)):
            print("翻译引擎没有 generate_batch", file=sys.stderr)
            return 1
        if text is None:
            body = Path(str(source)).read_text(encoding="utf-8")
        else:
            body = str(text)
        target = str(payload.get("target_lang") or "zh")
        translated = translate_text(body, target, engine)
    except Exception as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps({"text": translated or "", "error": ""}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
