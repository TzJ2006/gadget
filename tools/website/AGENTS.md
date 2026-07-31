# tools/website — Hugo Blog

Hugo static blog ("TzJ's Net", PaperMod theme) deployed to GitHub Pages (`https://tzj2006.github.io/`). Pipeline scripts: `update.sh` / `update.ps1` (incremental media compression → bilingual translation → preflight → hugo build → push), `compress_image.py` (pngquant), `compress_video.py` (HandBrakeCLI), `translate_content.py` + `translate_site_batch.py` (local-inference translation, incremental state in `.translation_state.json`), `preflight_check.py`. Site config: `config.yml`; content in `content/`, layouts in `layouts/`, static assets in `static/`.

## Commands

```bash
pip install -e ".[website]"                        # from repo root: Pillow + torch/transformers
cd tools/website && bash update.sh                 # macOS/Linux: full incremental publish
powershell -ExecutionPolicy Bypass -File tools/website/update.ps1   # Windows (script cds to its own dir)
cd tools/website && hugo server -D                 # local preview incl. drafts (never exits)
python tools/website/preflight_check.py --help     # pre-deploy validation (needs PyYAML)
```

## Quirks

- `public/` is a **separate** git repo (`tzj2006/tzj2006.github.io`), committed and pushed by the update scripts — never commit into it manually.
- Ownership rule: auto-generated pages carry `gadget_generated: true` frontmatter; files without it are hand-written, and the deploy pipeline refuses to overwrite them (`HumanContentError`).
- Bilingual pairs `file.md` / `file.zh.md`; translation is local inference via `common.engine` — no cloud LLM APIs.
- Media compression is incremental against `.last_build` — only files changed since the last build are recompressed; compress media before commit, never commit uncompressed originals.
- Git: never commit `public/`, `themes/`, `resources/`, `.hugo_build.lock`; generated content/media are gitignored via allowlist patterns in the root `.gitignore` — check it before adding files under `content/` or `static/`.
