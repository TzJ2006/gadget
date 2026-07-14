# Review: Fix verify.py crash on no spec + add hooks deployment to install.py
Date: 2026-05-12 21:42 UTC
Duration: 0 min
Task ID: fix-verify-and-install-hooks

## Plan (Intent)

1. Fix verify.py to gracefully handle missing spec (workflow/verify.py)

2. Add hooks/ copy and PreToolUse config to install.py (workflow/install.py)


## Changes
| File | Lines | Change | Reason |
|------|-------|--------|--------|

| workflow/verify.py | L75,76,77,78,79,80,81 | Wrap run_verification() in try/except SpecNotFoundError, exit 0 with message | because Stop hook runs verify.py after every session, but no spec exists between tasks, therefore Gracefully exit with informational message instead of crashing |

| workflow/install.py | L28,34,40,60 | Add hooks/ directory copy + PreToolUse hook config to install_workflow() | because Other repos need the confirmation gate (check_spec.py) deployed automatically, therefore install.py now copies hooks/ dir and registers PreToolUse hook in settings.json |


## Reasoning Chain

1. Observed: Stop hook crashes with SpecNotFoundError when no task is active → Because: verify.py calls load_spec() unconditionally, which raises if file missing → Therefore: Added try/except at __main__ level to catch SpecNotFoundError and exit 0 (HIGH)

2. Observed: install.py only deployed Stop hook, not PreToolUse confirmation gate → Because: The hooks/ directory and PreToolUse config were added after initial install.py → Therefore: Added hooks/ copytree and PreToolUse entry to settings.json generation (HIGH)


## Verification

✅ pytest workflow/tests/ -q: 33 passed

✅ verify.py no-spec graceful exit: No active spec — nothing to verify.




## Next Steps


- Re-install workflow to TokenMonitor and LifeCopilot to deploy hooks

