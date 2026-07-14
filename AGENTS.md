# AGENTS.md — Agentic Workflow Protocol

This file defines the workflow for ALL AI agents (Claude Code, Codex, Cursor, Copilot) working in this repository. Read it before taking action.

This repo is developed **with** AI Dev Companion (the **ai-companion** TypeScript monorepo — a *separate repo*, `git@github.com:TzJ2006/ai-companion.git`, checked out at the sibling `../ai-companion/`): function-level change tracking plus a planning/execution skill pipeline. For any non-trivial change, prefer the pipeline below over ad-hoc edits.

## Pipeline

```
/idea  →  /ccdiscuss  →  /ccplan  →  /ccedit  →  /ccdebug
backlog    align          plan        execute     debug-on-failure
                            ▲
                      /cconboard  (onboard existing code)
```

- **/ccdiscuss** — Align on intent before planning. The human writes the expected result first; the AI surfaces its five questions (是什么 / 为什么做 / 如何做 / 为什么这样做 / 期望结果) and flags divergence. Output: an aligned ECL. Read-only.
- **/ccplan** — Diverge-then-converge requirement engineering. Output: an ECL document under `docs/ecl/*.yaml`. **STOPS for approval before any implementation.**
- **/ccedit** — DAG-driven executor for an *approved* ECL: topologically sorts the function graph, runs independent nodes in parallel, runs each node's `verify`, and writes `status` back. Routes failures to `/ccdebug`.
- **/ccdebug** — Failure → source function → root cause → fix. Fix code, not tests; max 3 retries; full regression before done.
- **/cconboard** — Scan, analyze, modularize, test, and document existing code.

## Confirmation Gate (hard requirement)

Before writing or modifying any code file, paraphrase your understanding of the task back to the user — goal, in-scope files, success criteria, and what you will NOT do — and get explicit confirmation. Do not write code "while waiting." `/ccplan` Phase 9 enforces this stop-for-approval; outside the skills, apply it manually.

## ECL — the persistent plan (`docs/ecl/*.yaml`)

Plans and decisions live as Evolving Constraint Language YAML in `docs/ecl/`. A single file can act as:
1. a **planning document** (requirements, features, modules, functions, decisions);
2. an **execution DAG** (`functions:` nodes carrying `depends_on`, `output`, `verify`, `status`); and/or
3. a **feature guard** — a `feature_guard` section listing `key_files`, `invariants`, and a `verification` command. When a guard names key files, preserve their invariants when editing those files and run the verification afterward.

## Change Tracking

A PostToolUse hook records every `.py`/`.ts` edit at function level (and `.yaml`/`.md` at file level) into `.devcompanion/`. It runs automatically — no action needed.

## Verification

Each tool module documents its verification commands in its own `AGENTS.md`. Run the relevant ones (typically `python -m pytest <tool>/tests/`) before considering a task complete. ECL FN nodes additionally carry their own `verify` commands, which `/ccedit` runs during execution.

## Enforcement

- Hooks are wired in `.codex/hooks.json` (Codex) and `.claude/settings.json` (Claude Code; local, gitignored) to the sibling `../ai-companion/` change-tracking hooks.
- (Re)install the hooks per machine with `npx tsx ../ai-companion/scripts/install.ts . --enforce` after building ai-companion (`cd ../ai-companion && npm install && npm run build`).
- Cursor / Copilot: follow this protocol manually.
- Read prior ECLs in `docs/ecl/*.yaml` and change history in `.devcompanion/` for context when resuming work.
