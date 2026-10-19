# Docs index

What is current, and what is only a record. The one-screen repo map is [README.md](../README.md). Layering is [reference/architecture.md](reference/architecture.md).

## Current

- [reference/](reference/) — how the repo is built and extended.
  - [architecture.md](reference/architecture.md) — layering source (hub-and-spoke: `common/` vs `tools/`).
  - [development.md](reference/development.md) — where to add a backend, a tool, or a config key.
  - [debugging.md](reference/debugging.md) — config resolution, logs, caches, and side effects.
  - [tools.md](reference/tools.md) — how to run each tool and where its output goes.
  - [external-dependencies-inventory.md](reference/external-dependencies-inventory.md) — binaries, packages, and environment variables.
- [guides/summarize-local-llm.md](guides/summarize-local-llm.md) — running summarize on local Ollama.
- [guides/claude-code-skills-guide.md](guides/claude-code-skills-guide.md) — Claude Code skills: where they load and how to invoke them.

## Historical

Kept so older notes stay findable. They are not the current map.

- [archive/](archive/) — retired workflow notes, including [2026-05-11-unified-workflow.md](archive/2026-05-11-unified-workflow.md) and [workflow-reviews/](archive/workflow-reviews/).
- [archive/2026-04-21-repo-audit.md](archive/2026-04-21-repo-audit.md) and [archive/2026-04-21-repo-audit.json](archive/2026-04-21-repo-audit.json) — April 2026 audit.
- [archive/superpowers/](archive/superpowers/) — saved plans and specs (`plans/2026-06-14-ccusage-20-migration.md`, `specs/2026-06-14-ccusage-20-unified-migration-design.md`).
- [reports/phase0-baseline.md](reports/phase0-baseline.md) — phase-0 baseline.
- `docs/ecl/` — gitignored local plans. Not in this tree.

Chinese overview: [README.zh.md](README.zh.md). Usage: [../TUTORIAL.md](../TUTORIAL.md) and [TUTORIAL.zh.md](TUTORIAL.zh.md).
