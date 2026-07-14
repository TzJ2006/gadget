# gadget — repo DAG

This folder turns `gadget` (a pile of independent tool dirs) into two things you can
re-enter cold:

1. **A readable dependency graph** — [`gadget.md`](./gadget.md): milestones (FEAT) and the
   from-scratch tasks (FN) under the open ones, edges = prerequisites, flowing from the
   shared `common/` foundation up to the repo's endpoint.
2. **A "where I left off / why I wrote this" record** — every node carries a `status` and the
   **5 questions**, so you recover both *what's next* and *why each piece exists*.

| File | What |
|------|------|
| [`gadget.ecl.yaml`](./gadget.ecl.yaml) | Canonical two-level DAG (machine-readable): `milestones`, `tasks`, `dependency_graph`, `endpoints`, `left_off`. |
| [`gadget.md`](./gadget.md) | Human view: clickable Mermaid graph (status-colored) + the 5-question record per node + a "where you left off → next actions" table. |

**Endpoint:** `FEAT-gadget-19` — **a publishable toolset** (pip-installable with extras, a
working MCP server, complete docs, `main` consistent).

**The 5 questions (per node):** `what` 是什么 · `why` 为什么做 · `how` 如何做 ·
`why_this_way` 为什么这样做 · `expected` 期望结果.

**Where you left off (at a glance):** active branch `fix/ccusage-20-migration`; the open
frontier is the **L3 distribution** layer — land the ccusage 20.x migration, recreate the
deleted `mcp_server.py` (unblocks the MCP server + the pyproject entry point), fix packaging,
and add `common/CLAUDE.md`. See the table in [`gadget.md`](./gadget.md#where-you-left-off--next-actions).

> Built by hand from the repo's own onboarding output (`docs/ecl/gadget-features.yaml`,
> `docs/repo-audit.md`, `CLAUDE.md`, git history) — no generator script. The repeatable
> recipe lives in the AI Dev Companion repo at `docs/ecl/dag/README.md`. Keep the Mermaid
> edges in `gadget.md` in sync with `dependency_graph` in `gadget.ecl.yaml`.
