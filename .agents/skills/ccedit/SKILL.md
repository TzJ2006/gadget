---
name: ccedit
description: Execute an approved AI Dev Companion ECL function DAG with verification and atomic status updates.
---

# AI Dev Companion Codex Adapter: ccedit

Read `D:/GitHub/ai-companion/skills/ccedit/SKILL.md` before execution. Use `@aidev/exec` as
the authoritative DAG parser, verifier, and status writer. Map the core
workflow's Agent calls to Codex subagents when available; otherwise execute
independent ready nodes serially. Never let a worker update ECL status directly.
