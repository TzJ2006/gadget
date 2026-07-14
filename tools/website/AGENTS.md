# AGENTS.md — website module

> **Workflow Protocol**: Follow [../../AGENTS.md](../../AGENTS.md) — AI Dev Companion pipeline (/ccdiscuss → /ccplan → /ccedit → /ccdebug; plans in `../../docs/ecl/*.yaml`).
> Paraphrase the task and get explicit confirmation before editing code.

## Module Scope

- Hugo blog with PaperMod theme (GitHub Pages deploy)
- `update.sh` / `update.ps1` — incremental compress + Hugo build + deploy
- `compress_image.py`, `compress_video.py` — media optimization
- `translate_content.py`, `translate_site_batch.py` — bilingual content via local inference
- `preflight_check.py` — pre-deploy validation
- `config.yml` — Hugo site configuration

## Verification Commands

Use these to verify changes to this module:

```bash
cd tools/website && hugo --minify 2>&1 | tail -5                        # Hugo build succeeds
python tools/website/preflight_check.py                                  # Preflight validation
python -c "from common.translation import translate_markdown_document; print('OK')"  # Translation import
```

## Coding Conventions

- Hugo content in `content/`, layouts in `layouts/`, static in `static/`
- Bilingual pairs: `file.md` (English) + `file.zh.md` (Chinese)
- Translation uses `common.engine` + `common.translation` — no cloud LLM APIs
- Media: compress before commit, never commit uncompressed originals

## File Conventions

| Purpose | Location |
|---------|----------|
| Plans / ECL | `../../docs/ecl/*.yaml` |
| Change tracking | `../../.devcompanion/` |

## Git Tracking

- Do NOT commit: `public/`, `themes/`, `resources/`, `.hugo_build.lock`
- DO commit: `content/`, `layouts/`, `static/`, `config.yml`, Python scripts
