# tools/website

Hugo blog and the script that publishes it. Deep guide: [AGENTS.md](AGENTS.md).

## Hugo roots

`config.yml`, `content/`, `layouts/`, `static/`, `archetypes/`, `assets/`.

A human page has no `gadget_generated: true` marker. Generated pages carry that marker. The pipeline will not overwrite a human page.

## Markdown and mathematics

Use `\(x + y\)` for inline math and `\[...\]` or `$$...$$` for display math. Hugo renders formulas to native MathML at build time; no browser script is required. A single `$` remains ordinary text so dollar prices cannot consume surrounding Markdown. Keep a blank line between headings and tables or lists.

## Pipeline

`update.sh` (macOS, Linux, Git Bash) and `update.ps1` (Windows) run compression, translation, preflight, the Hugo build, and the push.

Python scripts next to them: `compress_image.py`, `compress_video.py`, `translate_content.py`, `translate_site_batch.py`, `preflight_check.py`, `publish.py`, `generated_paths.py`.

## public/

`public/` is a separate git repo (`tzj2006/tzj2006.github.io`). The update scripts commit and push it. Do not commit into `public/` from this repo.

## Where new files go

- A hand-written page: `content/`, without `gadget_generated: true`. Bilingual pages are `file.md` and `file.zh.md`.
- Layouts: `layouts/`. Theme CSS: `assets/`. Files Hugo copies unchanged: `static/`. New content types: `archetypes/`.
- A pipeline step: a script beside `update.sh`, called from `update.sh` and `update.ps1`.
