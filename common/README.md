# common/

Shared library for every gadget tool. Tools do not import each other; they import this package. `common/` does not import from `tools/`.

Layering: [docs/reference/architecture.md](../docs/reference/architecture.md).

## Modules

`common/__init__.py` does not re-export (`__all__` is empty). Import the module you need. Public modules named there:

| Module | Role |
|---|---|
| `bilingual.py` | Write a Hugo `.md` / `.zh.md` pair |
| `cache.py` | SHA-256 disk cache |
| `config.py` | Repo-root `config.json` (`GADGET_CONFIG`) |
| `engine/` | Local translation backends |
| `hugo.py` | Run Hugo |
| `io.py` | Atomic writes, hashing, JSON load |
| `json_utils.py` | Parse and repair LLM JSON |
| `llm.py` | Shared chat client (ollama / anthropic / openai / claude_cli) |
| `paths.py` | `outputs/` directory constants |
| `site_staging.py` | Write generated Hugo pages into the site |
| `translation/` | Markdown translation |
| `website_backup.py` | Refuse to overwrite human Hugo pages |

`html_text.py` is a small HTML-to-text helper. It is not in that public list.

## Translation engines

New backends go in `common/engine/` and are exported from `common/engine/__init__.py`.

| File | Export |
|---|---|
| `base.py` | `TranslationEngine` and shared helpers |
| `ollama.py` | `OllamaEngine` |
| `vllm.py` | `VLLMEngine` |
| `llamacpp.py` | `LlamaCppEngine` |
| `transformers.py` | `TransformersEngine` |
| `__init__.py` | `create_engine()`, `shutdown_engines()`, and the classes above |

## Markdown translation

`common/translation/` is the Markdown pipeline: `protect.py` (chunks and placeholders), `frontmatter.py` (YAML fields), `document.py` (`translate_markdown_document`).

## Where new files go

- Shared LLM, cache, IO, Hugo, or config code: a module in this directory. If it is public, name it in the `common/__init__.py` docstring.
- A new translation backend: `common/engine/<name>.py`, then export it from `common/engine/__init__.py`.
- Markdown translation behavior: `common/translation/`.
- Tests: `common/tests/`.

Tool behavior stays in `tools/<tool>/`. Cross-tool ops stay in [`scripts/`](../scripts/README.md).
