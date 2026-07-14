"""Real end-to-end check (NOT part of the unit suite — loads the actual model).

Validates REQ-002/003 hard criterion: markdown structure (fenced code block, URL)
survives a real translation. Run: python translator/tests/_e2e_real.py
"""

from translator.core import get_engine, translate_text

SAMPLE = """# Hello World

This is a **test** document with a list:

- first item
- second item

```python
def add(a, b):
    return a + b
```

Visit https://example.com for details.
"""


def main() -> None:
    eng = get_engine()
    out = translate_text(SAMPLE, "zh", eng)
    print("=== OUTPUT ===")
    print(out)
    print("=== CHECKS ===")
    in_fences = SAMPLE.count("```")
    out_fences = out.count("```")
    has_code_body = "def add(a, b):" in out and "return a + b" in out
    has_url = "https://example.com" in out
    has_cjk = any("一" <= c <= "鿿" for c in out)
    nonempty = bool(out.strip())
    print(f"fenced code blocks: in={in_fences} out={out_fences} -> {'OK' if in_fences == out_fences else 'FAIL'}")
    print(f"code body verbatim: {'OK' if has_code_body else 'FAIL'}")
    print(f"url preserved:      {'OK' if has_url else 'FAIL'}")
    print(f"contains chinese:   {'OK' if has_cjk else 'FAIL'}")
    print(f"non-empty:          {'OK' if nonempty else 'FAIL'}")
    ok = in_fences == out_fences and has_code_body and has_url and has_cjk and nonempty
    print("RESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
