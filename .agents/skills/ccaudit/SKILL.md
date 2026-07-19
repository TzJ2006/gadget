---
name: ccaudit
description: Repo-level dataflow bug audit (NPD/MLK/UAF) of a target C/C++/Java/Python/Go project via patched RepoAudit. Not for TypeScript targets.
---

# AI Dev Companion Codex Adapter: ccaudit

Read `D:/GitHub/ai-companion/skills/ccaudit/SKILL.md` and follow it exactly: preflight the
install at `~/.devcompanion/tools/RepoAudit`, detect the target language,
apply language-aware bug-type defaults, confirm scope, run
`repoaudit.py --model-name claude-code --max-neural-workers 3` per bug type,
and write the report to `<target>/.devcompanion/audit/`.

Codex note: the `codex-cli` backend seam in the patch is experimental and
untested — when running under Codex, still use `--model-name claude-code`
(requires the claude CLI on PATH) unless the user explicitly asks to try
`codex-cli`.
