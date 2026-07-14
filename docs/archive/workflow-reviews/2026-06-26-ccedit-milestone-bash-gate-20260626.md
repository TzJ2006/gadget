# Review: Make the /ccedit milestone Bash gate actually enforce: wire the PreToolUse hook for Bash, allow the trusted exec-CLI entrypoint so orchestrator verification/status commands pass, fail closed on subagent free-form Bash writes, and wire the milestone marker lifecycle into the ccedit orchestrator.
Date: 2026-06-26 17:53 UTC
Duration: 0 min
Task ID: ccedit-milestone-bash-gate-20260626

## Plan (Intent)

1. Add isTrustedExecCli() to the pre-tool hook guard and allow it (alongside read-only Bash) in the ccedit milestone branch; fail closed when the command contains shell metacharacters so only the trusted exec-CLI entrypoint passes. (ai-companion/packages/hook/src/pre-tool-use-guard.ts)

2. Add Bash to the PreToolUse matcher (Edit|Write|Bash) at every wiring site, keeping PostToolUse at Edit|Write. (ai-companion/.codex/hooks.json, ai-companion/packages/cli/src/commands/install.ts, ai-companion/scripts/lib/install-agent-config.ts)

3. Route verification through `cli.ts verify` and wire mark-milestone / clear-marker into the ccedit orchestrator protocol so the marker is created on execute and cleared on completion/exit. (ai-companion/skills/ccedit/SKILL.md, ai-companion/skills/ccedit/ccedit.md)

4. Extend the milestone guard tests: trusted exec-CLI commands allowed while a marker is active, free-form write Bash blocked, metacharacter commands fail closed. (ai-companion/.devcompanion/tests/test_hook_cceditMilestoneGuard.test.ts)

5. Rebuild dist and the bundled plugin hook so hooks/bin/pre-tool-use.cjs contains the milestone guard logic, then run the targeted vitest suite, npm run build, and python workflow/verify.py, and generate both review log formats. (ai-companion/hooks/bin/pre-tool-use.cjs, reviews/)


## Changes
| File | Lines | Change | Reason |
|------|-------|--------|--------|

| ai-companion/packages/hook/src/pre-tool-use-guard.ts | L36,58,78,219,237,259 | Add isTrustedExecCli() + EXEC_CLI allowlist; permit the trusted exec-CLI entrypoint (with read-only Bash) in the ccedit branch and corrupt-marker recovery; fail closed on shell metacharacters | because the milestone Bash gate previously blocked ALL non-read-only Bash, which would have blocked the orchestrator's own verify/status commands, therefore trust exactly the @aidev/exec CLI entrypoint so the orchestrator is not self-blocked, while subagent free-form Bash still fails closed |

| ai-companion/.codex/hooks.json | L5 | PreToolUse matcher Edit|Write -> Edit|Write|Bash | because the PreToolUse hook never fired for Bash, so the entire Bash gate was dead code, therefore register the hook for Bash so the milestone guard actually runs on Bash tool calls |

| ai-companion/packages/cli/src/commands/install.ts | L134 | PreToolUse enforce hook matcher -> Edit|Write|Bash (removeCompanionHooks migrates old installs) | because installs into other repos must wire the Bash gate too, therefore future --enforce installs register the PreToolUse hook for Bash |

| ai-companion/scripts/lib/install-agent-config.ts | L71,110,214,231,238 | Parameterize the Codex addHook matcher; settings.json pre-hook filter now migrates by command and pushes Edit|Write|Bash | because both Codex hooks.json and Claude settings.json install paths hardcoded Edit|Write for PreToolUse, therefore both paths now install the Bash matcher and de-duplicate legacy Edit|Write pre-hooks |

| ai-companion/skills/ccedit/SKILL.md | L91,109,123,170,181 | Wire mark-milestone/clear-marker into the orchestrator protocol and route verification through cli.ts verify; add milestone-boundary safety invariant + recovery note | because the marker lifecycle was implemented in the CLI but never invoked by the orchestrator, and Step 4 ran verify via raw Bash, therefore the orchestrator now activates/releases the marker and runs verify through the trusted CLI (real test runs as a child process, outside the hook) |

| ai-companion/skills/ccedit/ccedit.md | L19,26 | Mirror the milestone marker + CLI-routed verification lifecycle in the short command doc | because the two ccedit docs must describe the same execution flow, therefore ccedit.md now lists mark-milestone, cli.ts verify, set-status, and clear-marker steps |

| ai-companion/.devcompanion/tests/test_hook_cceditMilestoneGuard.test.ts | L122,138,153,163,172 | Add tests: trusted exec-CLI allowed while active, metacharacter commands fail closed, unknown subcommand blocked, clear-marker allowed when stale, and a .codex/hooks.json Bash-matcher wiring assertion | because the trusted-CLI allowance and Bash-matcher wiring are the core of this fix, therefore the guard's allow/deny boundary and the hook wiring are locked by tests |

| ai-companion/hooks/bin/pre-tool-use.cjs | L1 | Rebuilt bundled plugin hook (npm run build + build:plugin) so the milestone + trusted-CLI guard logic is actually deployed | because the previously committed bundle predated the milestone work and contained zero milestone logic, therefore the wired hook now enforces the milestone boundary |

| workflow/active-spec.json | L1 | New active spec for ccedit-milestone-bash-gate-20260626 (proof-of-gate artifact + success criteria) | because the workflow protocol requires an approved spec before implementation, therefore the spec records goal/scope/constraints/success_criteria for this task |


## Reasoning Chain

1. Observed: The PreToolUse hook is wired with matcher Edit|Write only (.codex/hooks.json, install paths), and the bundled pre-tool-use.cjs had zero milestone logic. → Because: Bash never reached the guard, so the milestone Bash gate was dead code and the guard was not even deployed. → Therefore: Added Bash to the PreToolUse matcher at all wiring sites and rebuilt the bundle. (HIGH)

2. Observed: The ccedit orchestrator runs verify and status writes via Bash; a blanket non-read-only Bash block would block the orchestrator itself. → Because: The hook cannot distinguish orchestrator from subagent, and verify.command is Bash. → Therefore: Allowed only the trusted @aidev/exec CLI entrypoint (fail closed on metacharacters) and routed verify through cli.ts verify, whose real test runs as a child process outside the hook. (HIGH)

3. Observed: mark-milestone/clear-marker existed in the CLI but were never called by the orchestrator protocol. → Because: The marker lifecycle was never wired into the ccedit SKILL. → Therefore: Wired mark-milestone on execute and clear-marker on completion/exit, with set-status (which auto-clears on milestone completion) as the only sanctioned status write. (HIGH)


## Verification

✅ vitest (7 targeted files): 47 passed (7 files)

✅ npm run build: tsc --build OK

✅ npm run build:plugin: pre-tool-use.cjs 13.5kb; milestone+trusted-CLI logic bundled

✅ python -m workflow.verify: VERIFICATION PASSED (both success_criteria)




## Next Steps


- Optional B: cconboard-milestone-layout-20260626 (dry-run physical milestone layout) remains deferred.

- Consider adding the PreToolUse Bash matcher to the Claude plugin manifest (hooks/hooks.json) if/when the plugin guard becomes non-optional.

