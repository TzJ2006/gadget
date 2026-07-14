# CLAUDE.md

> **Workflow**: This module follows the agentic protocol in [`AGENTS.md`](AGENTS.md) — AI Dev Companion pipeline; plans live in `../../docs/ecl/*.yaml`.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Hugo blog ("TzJ's Net") using the PaperMod theme, deployed to GitHub Pages at `https://tzj2006.github.io/`. **`content/` and `static/` are the single Hugo roots** — both auto-generated posts (bugJournal daily/weekly/monthly, research, benchmark) and hand-written posts (leetcode, posts, root pages) live in the same tree. There is no staging layer: deploy pipelines write directly via `common.site_staging` (the old `outputs/site` staging tree, `module.mounts`, and `sync_staging.py` were all removed in the 2026-07 migration).

### Generated vs human-written content

Ownership is per-file and machine-readable (`common/website_backup.py`):

- **Generated** files carry `gadget_generated: true` in frontmatter (stamped by `write_site_content`) or a `gadget:src-hash:` comment (stamped by `write_bilingual`). Pipelines may update/overwrite them; `--force` redeploys back the previous version up into `outputs/backups/website-force/YYYYMMDD-HHMMSS/` (with `manifest.json`) before overwriting.
- **Human-written** files have no gadget marker (or explicit `gadget_generated: false`). Pipelines refuse to overwrite them — a collision raises `HumanContentError`; the only override is the explicit `--overwrite-human` flag.
- Hand-authored `_index.md`/`_index.zh.md` section indexes inside generated dirs are human-owned (no marker) and safe: pipelines only write date/name-keyed filenames.
- Static assets carry no marker; pipelines own their namespaces (`static/images/{daily,weekly,monthly}`, `static/benchmark-report`) and `--force` backs up before overwriting there too.

### Two-Repo Architecture

- **`gadget`** — source code repo (this repo). All Hugo source files, build scripts, and content live here.
- **`website/public/`** — a **separate** git repo (`tzj2006/tzj2006.github.io`) used solely for deployment. `update.sh`/`update.ps1` builds Hugo into `public/`, then pushes that repo to GitHub Pages.

These are independent repos. Never confuse them — `git add`/`commit`/`push` in `gadget` does NOT affect `public/`, and vice versa. Do not commit to `public/` directly; the build scripts handle it.

## Commands

```bash
# Install website runtime dependencies
pip install -e ".[website]"

# Translation dependencies are installed automatically with website group
# pip install -e ".[website]"  # includes torch + transformers
# Model tencent/Hy-MT2-1.8B is auto-downloaded on first run

# Full build + deploy pipeline (incremental compress + Hugo build + git push to Pages)
bash update.sh                # macOS/Linux
powershell -ExecutionPolicy Bypass -File update.ps1   # Windows

# Hugo dev server (for local preview)
hugo server -D

# Hugo build only (no deploy)
hugo

# Create new content
hugo new bugJournal/2026-03-03.md
hugo new leetcode/problem-name.md

# Compress a single image (converts JPEG→PNG, uses pngquant)
python compress_image.py static/images/path/to/image.png

# Compress a single video (uses HandBrakeCLI, 720p30, no audio)
python compress_video.py static/videos/path/to/video.mp4
```

### Platform Notes

- **Windows**: Use `update.ps1` instead of `update.sh`. It auto-skips image/video compression when `pngquant` or `HandBrakeCLI` are not installed. Use `python` (not `python3`).
- **macOS/Linux**: Use `update.sh`. Requires `pngquant` and `HandBrakeCLI` for compression steps.

## Build Pipeline (`update.sh` / `update.ps1`)

Eight sequential steps:
1. **Content translation** — `translate_site_batch.py --root content` backfills missing or changed `.md` / `.zh.md` pairs across the whole content tree (generated + hand-written) using local batch inference (`tencent/Hy-MT2-1.8B` via Ollama, vLLM, or transformers). Complete valid pairs are skipped via `.translation_state.json` (bootstrapped for free on first sight)
2. **Markdown rewriting** — In modified hand-written `.md` files: replaces `../../static` with the site URL, converts `.jpg`/`.jpeg` extensions to `.png`, converts video URLs to Hugo `{{< video >}}` shortcodes. Generated dirs (`$GENERATED_CONTENT_DIRS`: bugJournal daily/weekly/monthly, research) and `benchmark*.md` are pruned — pipeline output is already URL-correct and must not be sed-rewritten
3. **Image compression** — Runs `compress_image.py` in parallel on images newer than `.last_build`
4. **Video compression** — Runs `compress_video.py` (or HandBrakeCLI fallback) in parallel on videos newer than `.last_build`
5. **Preflight check** — `preflight_check.py` validates modified hand-written content (images/links/frontmatter/bilingual pairs/language, with translation auto-fix). Generated dirs are excluded (`GENERATED_CONTENT_DIRS` in the script) — auto-"fixing" pipeline output would desync it from its `gadget:src-hash` marker
6. **Hugo build** — Cleans `public/` (preserving `.git`), then runs `hugo`
7. **Deploy** — `cd public && git add -A && git commit && git push && git gc --aggressive`
8. **Timestamp update** — Touches `.last_build` for next incremental run

The `.last_build` file tracks what's already been processed. Delete it to force a full rebuild.

## Content Sections

| Section | Path | Archetype | Description |
|---------|------|-----------|-------------|
| bugJournal | `content/bugJournal/` | `archetypes/bugJournal.md` | Debugging journals with daily/weekly/monthly sub-sections |
| benchmark | `content/benchmark.md` | n/a | Auto-generated benchmark wrapper page for the latest HTML leaderboard |
| leetcode | `content/leetcode/` | `archetypes/leetcode.md` | Algorithm solutions with complexity analysis |
| posts | `content/posts/` | `archetypes/default.md` | Blog posts and study notes |

Special pages: `Resume.md`, `Search.md`, `Random.md` at content root.

## Static Assets

- **Images**: `static/images/` — organized by date folders. Always use `.png` (JPEG gets auto-converted).
- **Videos**: `static/videos/` — organized by date folders. Use `{{< video src="/videos/..." >}}` shortcode, not markdown links.
- **PDFs**: `static/pdfs/`

## Hugo Configuration (`config.yml`)

- **Theme**: PaperMod (in `themes/PaperMod/`)
- **Goldmark unsafe mode**: enabled (raw HTML allowed in markdown)
- **MathJax/LaTeX**: enabled via `mathjax: true` and `math: true`
- **Search**: Fuse.js powered, requires JSON output format
- **Busuanzi**: page view counter enabled
- **Hugo version**: requires v0.125.7+ extended

## Key Conventions

- Markdown files reference images via absolute site URLs (`https://tzj2006.github.io/images/...`), not relative paths — `update.sh` rewrites `../../static` references automatically.
- Video embedding uses the custom shortcode `{{< video src="/videos/file.mp4" type="video/mp4" preload="auto" width="360" >}}`, not standard markdown.
- Bug journal filenames follow `YYYY-MM-DD.md` date format.
- Comments in `update.sh` are in Chinese.

## Git Tracking Rules

Never `git add` anything under `website/content/` or `website/static/` unless it appears in the tracked allowlist below. See the root `.gitignore` for the full ignore list.

**Why:** Most content and static assets are auto-generated (written by deploy pipelines with `gadget_generated` markers), synced externally (rclone `website` category), or belong to separate repos (`public/` is the GitHub Pages deployment repo, `themes/` are cloned Hugo themes).

**Key tracked files (not exhaustive):** `CLAUDE.md`, `config.yml`, `archetypes/`, `layouts/`, `assets/`, `content/Search.md`, `content/bugJournal/_index.md`, build scripts (`update.sh`, `update.ps1`, `compress_*.py`, `preflight_check.py`, `translate_site_batch.py`).

## Pre-flight Check (`preflight_check.py`)

Verifies deployment readiness before running the full build pipeline. Checks for required tools (Hugo, pngquant, HandBrakeCLI), validates config, and reports any issues.

## Dependencies

- Hugo extended (v0.125.7+)
- Python 3 + PIL/Pillow (for JPEG→PNG conversion in `compress_image.py`)
- Python torch + transformers (for translation; model `tencent/Hy-MT2-1.8B` auto-downloaded on first run). Optional: Ollama (default when the tag is pulled) or vLLM on Linux for faster batch inference.
- pngquant (image compression)
- HandBrakeCLI (video compression)
