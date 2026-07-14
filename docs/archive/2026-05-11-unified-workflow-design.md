# Unified Agentic Workflow Design

**Date:** 2026-05-11
**Status:** Approved
**Scope:** Cross-agent, cross-repo workflow protocol

---

## Goal

A unified end-to-end workflow that any AI agent (Claude Code, Codex, Cursor) can follow in any repo: structured spec → detailed plan → implement → verify → review log. Enforced by hooks, portable via install script.

---

## Architecture

### Component Mapping

| Component | Solution | Type |
|-----------|----------|------|
| Spec/Plan | Spec Kit (GitHub official) | Community |
| Session audit | Entire CLI | Community |
| Changelog | git-cliff | Community |
| Verification enforcement | Claude Code hooks (PostToolUse/Stop) | Built-in |
| Debug mode | Custom (pause + visualize + hypothesis reasoning) | Custom |
| Dual-format review log | Custom (human .md + agent .json) | Custom |
| Glue layer (AGENTS.md protocol + orchestration) | Custom | Custom |
| Install script | Custom (deploy to any repo/machine) | Custom |

### Flow

```
Spec Kit (/speckit.specify → /speckit.plan → /speckit.tasks)
    │
    │  plan output includes success_criteria (= acceptance test)
    ▼
Implement (agent executes plan, Entire CLI records session)
    │
    ▼
Verify (hooks enforce: run acceptance test from success_criteria)
    │
    ├── PASS → Review Log (auto-generate dual format)
    │
    └── FAIL → Debug Mode
                 1. Pause, show failure summary (terminal)
                 2. Generate detailed HTML report (browser)
                 3. Structured hypothesis reasoning (because → therefore)
                 4. Wait for user confirmation
                 5. Fix → re-verify
```

---

## Component Specifications

### 1. Spec Kit Integration

**Install:** `uv tool install specify-cli --from git+https://github.com/github/spec-kit.git`

**Workflow commands:**
- `/speckit.specify` — define what/why, constraints, non-goals
- `/speckit.plan` — detailed step-by-step plan with success criteria
- `/speckit.tasks` — break plan into actionable tasks
- `/speckit.implement` — execute tasks

**Customization needed:**
- Spec template must include a mandatory `success_criteria` field
- Success criteria must be executable (a command + expected result)
- Plan must be detailed enough to serve as the "intent" section of review log

### 2. Entire CLI Integration

**Install:** Follow https://github.com/entireio/cli

**What it captures automatically:**
- Full prompt/response transcripts
- Files modified with diffs
- Timestamps, token usage, tool calls
- Checkpoint snapshots

**Storage:** Separate git branch (`entire/checkpoints/v1`), does not clutter main history.

**Multi-agent:** Works with Claude Code, Codex, Cursor, Copilot CLI.

**Role in workflow:** Raw data source. The custom review log generator consumes Entire CLI's session data to produce human/agent summaries.

### 3. git-cliff Integration

**Install:** `cargo install git-cliff` or `pip install git-cliff`

**Config:** `cliff.toml` at repo root.

**Role:** Generate human-readable changelog from conventional commits. Supplements (not replaces) the per-task review log.

### 4. Verification Gate (Hooks)

**Mechanism:** Claude Code Stop hook that runs acceptance test before session ends.

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "python workflow/verify.py"
        }]
      }
    ]
  }
}
```

**verify.py logic:**
1. Read current task's spec (from `workflow/active-spec.json`)
2. Extract `success_criteria` commands
3. Execute each command
4. If any fails: exit code 1 (blocks session end), print failure summary
5. If all pass: exit code 0, trigger review log generation

**For non-Claude agents:** AGENTS.md instructs them to run verification manually before considering task complete.

### 5. Debug Mode (Custom)

**Trigger:** Verification fails.

**Terminal output (immediate):**

```
━━━ VERIFICATION FAILED ━━━
Test: <test_name>
Expected: <expected>
Actual: <actual>

Hypothesis 1: <short description>
  Because: <observation/evidence>
  Therefore: <conclusion>
  Confidence: HIGH|MEDIUM|LOW
  Evidence: <file:line> → <relevant code>

Hypothesis 2: ...

━━━ Awaiting your direction ━━━
```

**HTML report (generated to `outputs/debug/YYYY-MM-DD-<topic>.html`):**
- Data comparison charts (expected vs actual)
- Execution flow diagram with failure point highlighted
- Relevant log lines with context
- Full hypothesis reasoning chain
- Related code snippets with annotations

**Behavior:**
- Agent MUST pause after showing hypotheses
- Agent MUST NOT auto-fix without user confirmation
- User picks a hypothesis or provides direction
- Agent enters fix cycle → re-verify
- All debug attempts recorded in review log's `debug_history`

### 6. Dual-Format Review Log (Custom)

**Location:** `reviews/` directory at repo root.

**Timing:**
- Auto-generated when verification passes (default)
- Manually triggered via `/review` command (if skipped or for ad-hoc review)

#### Human Version: `reviews/YYYY-MM-DD-<topic>.md`

```markdown
# Review: <goal summary>
Date: YYYY-MM-DD HH:MM
Duration: X min
Task ID: <id>

## Plan (Intent)
<numbered steps from spec plan — what was supposed to happen>

## Changes
| File | Lines | Change | Reason |
|------|-------|--------|--------|
| path | L42-45 | description | because X, therefore Y |

## Reasoning Chain
1. Observed: <observation> → Because: <reason> → Therefore: <action>
2. ...

## Verification
✅/❌ <test_name>: <result>

## Debug History (if any)
- Attempt 1: Hypothesis X → CONFIRMED/REJECTED
- Attempt 2: ...

## Next Steps
- <any follow-up work identified>
```

#### Agent Version: `reviews/YYYY-MM-DD-<topic>.agent.json`

```json
{
  "schema_version": "1.0",
  "task_id": "<unique-id>",
  "timestamp": "ISO-8601",
  "duration_seconds": 720,
  "spec": {
    "goal": "<one-line goal>",
    "scope": ["<file patterns allowed>"],
    "constraints": ["<things not to do>"],
    "non_goals": ["<explicitly excluded>"],
    "success_criteria": [
      { "command": "python -m pytest tests/test_x.py", "expected": "all pass" }
    ]
  },
  "plan": [
    { "step": 1, "description": "...", "files": ["..."] }
  ],
  "changes": [
    {
      "file": "path",
      "lines": [42, 43, 44, 45],
      "type": "modify|add|delete",
      "description": "...",
      "reason": { "because": "...", "therefore": "..." }
    }
  ],
  "reasoning_chain": [
    { "observation": "...", "because": "...", "therefore": "...", "confidence": "HIGH" }
  ],
  "verification": {
    "status": "pass|fail",
    "tests": [
      { "name": "...", "status": "pass|fail", "output": "..." }
    ]
  },
  "debug_history": [
    {
      "attempt": 1,
      "hypothesis": "...",
      "result": "confirmed|rejected",
      "evidence": "..."
    }
  ],
  "next_steps": [],
  "entire_session_ref": "<entire-cli-session-id>"
}
```

### 7. AGENTS.md Protocol

Lives at repo root. Read by all agents. Defines:

1. **Workflow stages** (spec → plan → implement → verify → review)
2. **Mandatory behaviors:**
   - Never implement without an approved spec
   - Always include success_criteria that are executable
   - On verification failure: pause, hypothesize with reasons, wait for confirmation
   - All decisions must have explicit `because → therefore` reasoning
   - Generate review log on completion (or note why skipped)
3. **File conventions:** where specs, reviews, debug reports live
4. **Agent-specific notes:** Claude reads CLAUDE.md, Codex reads AGENTS.md, Cursor reads .cursorrules — all point back to the same protocol

### 8. Install Script

**Location:** `workflow/install.py`

**Usage:**
```bash
python workflow/install.py /path/to/target-repo
```

**What it does (idempotent):**
1. Creates `reviews/` directory
2. Creates/updates `AGENTS.md` with workflow protocol
3. Installs Claude Code hooks to `.claude/settings.json` (if Claude Code detected)
4. Creates `.cursorrules` stub pointing to AGENTS.md (if Cursor detected)
5. Copies `workflow/verify.py` and `workflow/review_generator.py`
6. Adds `reviews/` and `outputs/debug/` to `.gitignore` patterns (or not — user choice)
7. Prints setup summary

---

## File Structure in gadget/

```
gadget/
├── workflow/
│   ├── install.py              # Deploy workflow to any repo
│   ├── verify.py               # Verification gate (runs success_criteria)
│   ├── review_generator.py     # Generates dual-format review logs
│   ├── debug_report.py         # HTML debug report generator
│   ├── templates/
│   │   ├── spec-template.md    # Spec Kit customization
│   │   ├── review-human.md     # Human review template
│   │   └── review-agent.json   # Agent review JSON schema
│   └── README.md               # Workflow documentation
├── reviews/                    # Generated review logs (per-task)
│   ├── 2026-05-11-fix-pipeline.md
│   └── 2026-05-11-fix-pipeline.agent.json
├── AGENTS.md                   # Cross-agent protocol (source of truth)
└── cliff.toml                  # git-cliff configuration
```

---

## Dependencies

| Tool | Install | Required |
|------|---------|----------|
| Spec Kit | `uv tool install specify-cli` | Yes |
| Entire CLI | See entireio/cli docs | Yes |
| git-cliff | `cargo install git-cliff` or `pip install git-cliff` | Optional (changelog only) |
| Python 3.10+ | Already present | Yes |
| pytest | `pip install pytest` | For verification |
| plotly/matplotlib | Already in gadget deps | For debug HTML reports |

---

## Success Criteria for This Spec

1. `python workflow/install.py .` runs without error on gadget repo
2. A sample task can go through full cycle: spec → plan → implement → verify pass → review generated
3. A deliberately failing task triggers debug mode with terminal + HTML output
4. `reviews/` contains both .md and .agent.json after a completed task
5. AGENTS.md is readable and actionable by a fresh Claude/Codex/Cursor session
6. `python workflow/install.py /tmp/test-repo` successfully sets up a blank repo

---

## Non-Goals

- No CI/CD integration (local workflow only, for now)
- No cloud storage of review logs (local files, git-tracked)
- No real-time collaboration features
- No custom Spec Kit extensions (use vanilla Spec Kit commands)
- git-cliff is optional — review logs are the primary record
