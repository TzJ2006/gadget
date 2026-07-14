# Unified Agentic Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable, cross-agent workflow system (spec → plan → implement → verify → debug → review) enforced by hooks and deployable to any repo via install script.

**Architecture:** Community tools handle spec (Spec Kit), session capture (Entire CLI), and changelog (git-cliff). Custom Python scripts handle verification gate, debug mode with HTML reports, and dual-format review log generation. AGENTS.md is the cross-agent protocol. An install script deploys everything.

**Tech Stack:** Python 3.10+, pytest, plotly (HTML reports), Jinja2 (templates), JSON schema validation

---

## File Structure

```
gadget/
├── workflow/
│   ├── __init__.py                 # Package marker
│   ├── verify.py                   # Verification gate — reads active-spec, runs criteria
│   ├── review_generator.py         # Produces .md + .agent.json from session data
│   ├── debug_report.py             # Terminal summary + HTML report with charts
│   ├── active_spec.py              # Manages workflow/active-spec.json lifecycle
│   ├── install.py                  # Deploy workflow to any repo (idempotent)
│   ├── templates/
│   │   ├── review-human.md.j2     # Jinja2 template for human review
│   │   ├── review-agent.schema.json  # JSON Schema for agent review format
│   │   └── debug-report.html.j2   # Jinja2 template for HTML debug report
│   └── tests/
│       ├── __init__.py
│       ├── test_verify.py          # Unit tests for verification gate
│       ├── test_review_generator.py # Unit tests for review log generation
│       ├── test_debug_report.py    # Unit tests for debug report
│       ├── test_active_spec.py     # Unit tests for spec lifecycle
│       └── test_install.py         # Unit tests for install script
├── reviews/                        # Generated review logs (gitignored or tracked — user choice)
├── AGENTS.md                       # Cross-agent workflow protocol
└── cliff.toml                      # git-cliff configuration
```

---

## Task 1: Active Spec Manager

The spec lifecycle manager — creates, reads, and clears the `workflow/active-spec.json` file that all other components depend on.

**Files:**
- Create: `workflow/__init__.py`
- Create: `workflow/active_spec.py`
- Create: `workflow/tests/__init__.py`
- Create: `workflow/tests/test_active_spec.py`

- [ ] **Step 1: Write failing tests for active spec lifecycle**

```python
# workflow/tests/test_active_spec.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.active_spec import (
    create_spec,
    load_spec,
    clear_spec,
    SpecNotFoundError,
    SPEC_SCHEMA,
)


@pytest.fixture
def spec_dir(tmp_path):
    with patch("workflow.active_spec.WORKFLOW_DIR", tmp_path):
        yield tmp_path


def test_create_spec_writes_valid_json(spec_dir):
    spec = {
        "task_id": "fix-pipeline-20260511",
        "goal": "Fix pipeline to generate 1000 records",
        "scope": ["pipeline.py", "config.json"],
        "constraints": ["Do not modify the output schema"],
        "non_goals": ["Performance optimization"],
        "success_criteria": [
            {"command": "python -m pytest tests/test_pipeline.py", "expected": "all pass"}
        ],
        "plan": [
            {"step": 1, "description": "Update config batch size", "files": ["config.json"]},
            {"step": 2, "description": "Fix loop condition", "files": ["pipeline.py"]},
        ],
    }
    path = create_spec(spec)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["task_id"] == "fix-pipeline-20260511"
    assert loaded["goal"] == "Fix pipeline to generate 1000 records"
    assert len(loaded["success_criteria"]) == 1
    assert "timestamp" in loaded


def test_create_spec_rejects_missing_fields(spec_dir):
    incomplete = {"goal": "something"}
    with pytest.raises(ValueError, match="missing required fields"):
        create_spec(incomplete)


def test_create_spec_rejects_empty_success_criteria(spec_dir):
    spec = {
        "task_id": "t1",
        "goal": "x",
        "scope": [],
        "constraints": [],
        "non_goals": [],
        "success_criteria": [],
        "plan": [{"step": 1, "description": "d", "files": []}],
    }
    with pytest.raises(ValueError, match="success_criteria cannot be empty"):
        create_spec(spec)


def test_load_spec_returns_dict(spec_dir):
    spec = {
        "task_id": "t1",
        "goal": "x",
        "scope": [],
        "constraints": [],
        "non_goals": [],
        "success_criteria": [{"command": "echo ok", "expected": "ok"}],
        "plan": [{"step": 1, "description": "d", "files": []}],
    }
    create_spec(spec)
    loaded = load_spec()
    assert loaded["task_id"] == "t1"


def test_load_spec_raises_when_no_active_spec(spec_dir):
    with pytest.raises(SpecNotFoundError):
        load_spec()


def test_clear_spec_removes_file(spec_dir):
    spec = {
        "task_id": "t1",
        "goal": "x",
        "scope": [],
        "constraints": [],
        "non_goals": [],
        "success_criteria": [{"command": "echo ok", "expected": "ok"}],
        "plan": [{"step": 1, "description": "d", "files": []}],
    }
    create_spec(spec)
    clear_spec()
    with pytest.raises(SpecNotFoundError):
        load_spec()


def test_clear_spec_is_idempotent(spec_dir):
    clear_spec()  # Should not raise even if no file exists
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_active_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workflow'`

- [ ] **Step 3: Implement active_spec.py**

```python
# workflow/__init__.py
"""Unified Agentic Workflow package."""

# workflow/active_spec.py
"""Manages the active-spec.json lifecycle."""

import json
from datetime import datetime, timezone
from pathlib import Path

WORKFLOW_DIR = Path(__file__).parent
ACTIVE_SPEC_PATH = WORKFLOW_DIR / "active-spec.json"

REQUIRED_FIELDS = ("task_id", "goal", "scope", "constraints", "non_goals", "success_criteria", "plan")


class SpecNotFoundError(FileNotFoundError):
    """No active spec found."""


def create_spec(spec: dict) -> Path:
    missing = [f for f in REQUIRED_FIELDS if f not in spec]
    if missing:
        raise ValueError(f"missing required fields: {missing}")

    if not spec["success_criteria"]:
        raise ValueError("success_criteria cannot be empty")

    spec_with_meta = {
        **spec,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    ACTIVE_SPEC_PATH.write_text(
        json.dumps(spec_with_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return ACTIVE_SPEC_PATH


def load_spec() -> dict:
    if not ACTIVE_SPEC_PATH.exists():
        raise SpecNotFoundError(f"No active spec at {ACTIVE_SPEC_PATH}")
    return json.loads(ACTIVE_SPEC_PATH.read_text(encoding="utf-8"))


def clear_spec() -> None:
    if ACTIVE_SPEC_PATH.exists():
        ACTIVE_SPEC_PATH.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_active_spec.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add workflow/__init__.py workflow/active_spec.py workflow/tests/__init__.py workflow/tests/test_active_spec.py
git commit -m "feat(workflow): add active spec lifecycle manager"
```

---

## Task 2: Verification Gate

Reads `active-spec.json`, runs each `success_criteria` command, reports results. Exit code 0 = all pass, 1 = any fail.

**Files:**
- Create: `workflow/verify.py`
- Create: `workflow/tests/test_verify.py`

- [ ] **Step 1: Write failing tests for verification gate**

```python
# workflow/tests/test_verify.py
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from workflow.verify import run_verification, VerificationResult


@pytest.fixture
def spec_dir(tmp_path):
    with patch("workflow.active_spec.WORKFLOW_DIR", tmp_path), \
         patch("workflow.verify.WORKFLOW_DIR", tmp_path):
        yield tmp_path


def _write_spec(spec_dir, criteria):
    spec = {
        "task_id": "test-task",
        "goal": "test",
        "scope": [],
        "constraints": [],
        "non_goals": [],
        "success_criteria": criteria,
        "plan": [{"step": 1, "description": "d", "files": []}],
        "timestamp": "2026-05-11T00:00:00Z",
    }
    (spec_dir / "active-spec.json").write_text(json.dumps(spec), encoding="utf-8")


def test_all_criteria_pass(spec_dir):
    _write_spec(spec_dir, [
        {"command": "echo hello", "expected": "hello"},
    ])
    result = run_verification()
    assert result.passed is True
    assert len(result.results) == 1
    assert result.results[0]["status"] == "pass"


def test_criteria_fail_when_output_mismatch(spec_dir):
    _write_spec(spec_dir, [
        {"command": "echo wrong", "expected": "right"},
    ])
    result = run_verification()
    assert result.passed is False
    assert result.results[0]["status"] == "fail"
    assert "wrong" in result.results[0]["actual"]


def test_criteria_fail_when_command_errors(spec_dir):
    _write_spec(spec_dir, [
        {"command": "python -c \"raise SystemExit(1)\"", "expected": "all pass"},
    ])
    result = run_verification()
    assert result.passed is False
    assert result.results[0]["status"] == "fail"


def test_multiple_criteria_partial_failure(spec_dir):
    _write_spec(spec_dir, [
        {"command": "echo ok", "expected": "ok"},
        {"command": "echo bad", "expected": "good"},
    ])
    result = run_verification()
    assert result.passed is False
    assert result.results[0]["status"] == "pass"
    assert result.results[1]["status"] == "fail"


def test_no_active_spec_raises(spec_dir):
    from workflow.active_spec import SpecNotFoundError
    with pytest.raises(SpecNotFoundError):
        run_verification()


def test_expected_all_pass_checks_exit_code(spec_dir):
    _write_spec(spec_dir, [
        {"command": "python -c \"print('ok')\"", "expected": "all pass"},
    ])
    result = run_verification()
    assert result.passed is True


def test_result_has_summary_string(spec_dir):
    _write_spec(spec_dir, [
        {"command": "echo hello", "expected": "hello"},
    ])
    result = run_verification()
    summary = result.terminal_summary()
    assert "PASS" in summary
    assert "hello" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workflow.verify'`

- [ ] **Step 3: Implement verify.py**

```python
# workflow/verify.py
"""Verification gate — runs success_criteria from active spec."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from workflow.active_spec import load_spec, WORKFLOW_DIR


@dataclass
class VerificationResult:
    passed: bool
    results: list = field(default_factory=list)

    def terminal_summary(self) -> str:
        lines = []
        status_icon = "VERIFICATION PASSED" if self.passed else "VERIFICATION FAILED"
        lines.append(f"━━━ {status_icon} ━━━")
        for r in self.results:
            icon = "✅" if r["status"] == "pass" else "❌"
            lines.append(f"{icon} {r['command']}")
            if r["status"] == "fail":
                lines.append(f"   Expected: {r['expected']}")
                lines.append(f"   Actual:   {r['actual']}")
        return "\n".join(lines)


def _check_criterion(criterion: dict) -> dict:
    command = criterion["command"]
    expected = criterion["expected"]

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "expected": expected,
            "actual": "TIMEOUT (300s)",
            "status": "fail",
            "exit_code": -1,
        }

    actual_output = proc.stdout.strip()

    if expected == "all pass":
        passed = proc.returncode == 0
    else:
        passed = expected.strip() in actual_output

    return {
        "command": command,
        "expected": expected,
        "actual": actual_output if actual_output else proc.stderr.strip(),
        "status": "pass" if passed else "fail",
        "exit_code": proc.returncode,
    }


def run_verification() -> VerificationResult:
    spec = load_spec()
    criteria = spec["success_criteria"]

    results = [_check_criterion(c) for c in criteria]
    all_passed = all(r["status"] == "pass" for r in results)

    return VerificationResult(passed=all_passed, results=results)


if __name__ == "__main__":
    import sys
    result = run_verification()
    print(result.terminal_summary())
    sys.exit(0 if result.passed else 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_verify.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add workflow/verify.py workflow/tests/test_verify.py
git commit -m "feat(workflow): add verification gate with success criteria runner"
```

---

## Task 3: Debug Report Generator

Generates terminal summary (structured hypotheses) and HTML report (charts + flow diagram + log).

**Files:**
- Create: `workflow/debug_report.py`
- Create: `workflow/templates/debug-report.html.j2`
- Create: `workflow/tests/test_debug_report.py`

- [ ] **Step 1: Write failing tests for debug report**

```python
# workflow/tests/test_debug_report.py
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.debug_report import (
    DebugSession,
    Hypothesis,
    generate_terminal_report,
    generate_html_report,
)


def test_hypothesis_creation():
    h = Hypothesis(
        description="batch_size config limits output",
        because="config.json has batch_size=100",
        therefore="pipeline stops after first batch",
        confidence="HIGH",
        evidence="config.json:12",
    )
    assert h.confidence == "HIGH"
    assert "batch_size" in h.because


def test_terminal_report_contains_failure_info():
    session = DebugSession(
        test_name="test_pipeline_generates_1000",
        expected="1000 valid records",
        actual="100 records",
        hypotheses=[
            Hypothesis(
                description="batch_size config",
                because="config.json batch_size=100",
                therefore="only one batch runs",
                confidence="HIGH",
                evidence="config.json:12 → batch_size: 100",
            ),
        ],
    )
    output = generate_terminal_report(session)
    assert "VERIFICATION FAILED" in output
    assert "test_pipeline_generates_1000" in output
    assert "1000 valid records" in output
    assert "100 records" in output
    assert "Hypothesis 1" in output
    assert "batch_size config" in output
    assert "Because:" in output
    assert "Therefore:" in output
    assert "HIGH" in output
    assert "Awaiting your direction" in output


def test_html_report_generates_file(tmp_path):
    session = DebugSession(
        test_name="test_pipeline",
        expected="1000 records",
        actual="100 records",
        hypotheses=[
            Hypothesis(
                description="config limit",
                because="batch_size=100",
                therefore="early stop",
                confidence="HIGH",
                evidence="config.json:12",
            ),
        ],
        log_lines=["INFO: Starting pipeline", "INFO: Batch 1 complete", "INFO: Done"],
    )
    output_path = generate_html_report(session, output_dir=tmp_path)
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "test_pipeline" in content
    assert "1000 records" in content
    assert "config limit" in content
    assert "Batch 1 complete" in content


def test_html_report_contains_chart_placeholder(tmp_path):
    session = DebugSession(
        test_name="test_x",
        expected="100",
        actual="50",
        hypotheses=[],
    )
    output_path = generate_html_report(session, output_dir=tmp_path)
    content = output_path.read_text(encoding="utf-8")
    assert "Expected vs Actual" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_debug_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workflow.debug_report'`

- [ ] **Step 3: Create HTML template**

```html
{# workflow/templates/debug-report.html.j2 #}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Debug Report: {{ session.test_name }}</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #1a1a2e; color: #e0e0e0; }
        h1 { color: #ff6b6b; }
        h2 { color: #4ecdc4; border-bottom: 1px solid #333; padding-bottom: 0.5rem; }
        .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1rem 0; }
        .comparison > div { padding: 1rem; border-radius: 8px; }
        .expected { background: #1b4332; border: 1px solid #2d6a4f; }
        .actual { background: #3d0000; border: 1px solid #6b0000; }
        .hypothesis { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
        .hypothesis .confidence { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold; }
        .confidence-HIGH { background: #ff6b6b; color: #1a1a2e; }
        .confidence-MEDIUM { background: #ffd93d; color: #1a1a2e; }
        .confidence-LOW { background: #6c757d; color: white; }
        .log-lines { background: #0d1117; padding: 1rem; border-radius: 8px; font-family: monospace; font-size: 0.85em; max-height: 400px; overflow-y: auto; }
        .log-lines .line { padding: 2px 0; border-bottom: 1px solid #21262d; }
        .evidence { font-family: monospace; background: #21262d; padding: 4px 8px; border-radius: 4px; }
        .meta { color: #8b949e; font-size: 0.9em; }
    </style>
</head>
<body>
    <h1>Debug Report</h1>
    <p class="meta">Test: <strong>{{ session.test_name }}</strong> | Generated: {{ timestamp }}</p>

    <h2>Expected vs Actual</h2>
    <div class="comparison">
        <div class="expected">
            <strong>Expected:</strong>
            <pre>{{ session.expected }}</pre>
        </div>
        <div class="actual">
            <strong>Actual:</strong>
            <pre>{{ session.actual }}</pre>
        </div>
    </div>

    <h2>Hypotheses</h2>
    {% for h in session.hypotheses %}
    <div class="hypothesis">
        <h3>Hypothesis {{ loop.index }}: {{ h.description }}
            <span class="confidence confidence-{{ h.confidence }}">{{ h.confidence }}</span>
        </h3>
        <p><strong>Because:</strong> {{ h.because }}</p>
        <p><strong>Therefore:</strong> {{ h.therefore }}</p>
        {% if h.evidence %}
        <p><strong>Evidence:</strong> <span class="evidence">{{ h.evidence }}</span></p>
        {% endif %}
    </div>
    {% endfor %}

    {% if session.log_lines %}
    <h2>Relevant Logs</h2>
    <div class="log-lines">
        {% for line in session.log_lines %}
        <div class="line">{{ line }}</div>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
```

- [ ] **Step 4: Implement debug_report.py**

```python
# workflow/debug_report.py
"""Debug mode — terminal summary + HTML report with charts."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class Hypothesis:
    description: str
    because: str
    therefore: str
    confidence: str  # HIGH, MEDIUM, LOW
    evidence: str = ""


@dataclass
class DebugSession:
    test_name: str
    expected: str
    actual: str
    hypotheses: list[Hypothesis] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)


def generate_terminal_report(session: DebugSession) -> str:
    lines = [
        "━━━ VERIFICATION FAILED ━━━",
        f"Test: {session.test_name}",
        f"Expected: {session.expected}",
        f"Actual: {session.actual}",
        "",
    ]

    for i, h in enumerate(session.hypotheses, 1):
        lines.append(f"Hypothesis {i}: {h.description}")
        lines.append(f"  Because: {h.because}")
        lines.append(f"  Therefore: {h.therefore}")
        lines.append(f"  Confidence: {h.confidence}")
        if h.evidence:
            lines.append(f"  Evidence: {h.evidence}")
        lines.append("")

    lines.append("━━━ Awaiting your direction ━━━")
    return "\n".join(lines)


def generate_html_report(session: DebugSession, output_dir: Path | None = None) -> Path:
    from jinja2 import Template

    if output_dir is None:
        output_dir = Path("outputs/debug")
    output_dir.mkdir(parents=True, exist_ok=True)

    template_path = TEMPLATES_DIR / "debug-report.html.j2"
    template_text = template_path.read_text(encoding="utf-8")
    template = Template(template_text)

    html = template.render(
        session=session,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe_name = session.test_name.replace(" ", "-").replace("/", "-")
    output_path = output_dir / f"{date_str}-{safe_name}.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_debug_report.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add workflow/debug_report.py workflow/templates/debug-report.html.j2 workflow/tests/test_debug_report.py
git commit -m "feat(workflow): add debug report generator with terminal + HTML output"
```

---

## Task 4: Dual-Format Review Log Generator

Generates `reviews/YYYY-MM-DD-<topic>.md` and `reviews/YYYY-MM-DD-<topic>.agent.json` from spec + changes + verification results.

**Files:**
- Create: `workflow/review_generator.py`
- Create: `workflow/templates/review-human.md.j2`
- Create: `workflow/templates/review-agent.schema.json`
- Create: `workflow/tests/test_review_generator.py`

- [ ] **Step 1: Write failing tests for review generator**

```python
# workflow/tests/test_review_generator.py
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from workflow.review_generator import (
    ReviewData,
    ChangeEntry,
    generate_review,
)


@pytest.fixture
def review_dir(tmp_path):
    d = tmp_path / "reviews"
    d.mkdir()
    return d


def _sample_review_data():
    return ReviewData(
        task_id="fix-pipeline-20260511",
        goal="Fix pipeline to generate 1000 records",
        plan=[
            {"step": 1, "description": "Update config", "files": ["config.json"]},
            {"step": 2, "description": "Fix loop", "files": ["pipeline.py"]},
        ],
        changes=[
            ChangeEntry(
                file="config.json",
                lines=[12],
                change_type="modify",
                description="batch_size: 100 → total_records: 1000",
                reason_because="batch_size was incorrectly used as total count",
                reason_therefore="renamed to total_records with value 1000",
            ),
            ChangeEntry(
                file="pipeline.py",
                lines=[45, 46],
                change_type="modify",
                description="while i < batch_size → while i < total_records",
                reason_because="loop condition used batch size not target total",
                reason_therefore="changed to iterate until total_records reached",
            ),
        ],
        reasoning_chain=[
            {
                "observation": "Output has exactly 100 records",
                "because": "batch_size=100 is used as loop bound",
                "therefore": "Renaming and updating the bound fixes the issue",
                "confidence": "HIGH",
            },
        ],
        verification_status="pass",
        verification_tests=[
            {"name": "test_pipeline_generates_1000", "status": "pass", "output": "1000 records generated"},
        ],
        debug_history=[],
        duration_seconds=720,
    )


def test_generate_review_creates_both_files(review_dir):
    data = _sample_review_data()
    md_path, json_path = generate_review(data, output_dir=review_dir)
    assert md_path.exists()
    assert json_path.exists()
    assert md_path.suffix == ".md"
    assert json_path.name.endswith(".agent.json")


def test_human_review_contains_required_sections(review_dir):
    data = _sample_review_data()
    md_path, _ = generate_review(data, output_dir=review_dir)
    content = md_path.read_text(encoding="utf-8")
    assert "# Review:" in content
    assert "## Plan (Intent)" in content
    assert "## Changes" in content
    assert "## Reasoning Chain" in content
    assert "## Verification" in content
    assert "fix-pipeline-20260511" in content
    assert "config.json" in content
    assert "because" in content.lower()


def test_agent_review_is_valid_json(review_dir):
    data = _sample_review_data()
    _, json_path = generate_review(data, output_dir=review_dir)
    agent_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert agent_data["schema_version"] == "1.0"
    assert agent_data["task_id"] == "fix-pipeline-20260511"
    assert agent_data["verification"]["status"] == "pass"
    assert len(agent_data["changes"]) == 2
    assert agent_data["changes"][0]["reason"]["because"] != ""
    assert agent_data["duration_seconds"] == 720


def test_agent_review_includes_reasoning_chain(review_dir):
    data = _sample_review_data()
    _, json_path = generate_review(data, output_dir=review_dir)
    agent_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(agent_data["reasoning_chain"]) == 1
    assert agent_data["reasoning_chain"][0]["confidence"] == "HIGH"


def test_review_with_debug_history(review_dir):
    data = _sample_review_data()
    data.debug_history = [
        {"attempt": 1, "hypothesis": "off-by-one error", "result": "rejected", "evidence": "loop bound is correct"},
        {"attempt": 2, "hypothesis": "config limit", "result": "confirmed", "evidence": "batch_size=100"},
    ]
    md_path, json_path = generate_review(data, output_dir=review_dir)
    md_content = md_path.read_text(encoding="utf-8")
    assert "## Debug History" in md_content
    assert "off-by-one" in md_content
    agent_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(agent_data["debug_history"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_review_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workflow.review_generator'`

- [ ] **Step 3: Create human review Jinja2 template**

```markdown
{# workflow/templates/review-human.md.j2 #}
# Review: {{ data.goal }}
Date: {{ timestamp }}
Duration: {{ (data.duration_seconds // 60) }} min
Task ID: {{ data.task_id }}

## Plan (Intent)
{% for step in data.plan %}
{{ step.step }}. {{ step.description }} ({{ step.files | join(", ") }})
{% endfor %}

## Changes
| File | Lines | Change | Reason |
|------|-------|--------|--------|
{% for c in data.changes %}
| {{ c.file }} | L{{ c.lines | join(",") }} | {{ c.description }} | Because {{ c.reason_because }}, therefore {{ c.reason_therefore }} |
{% endfor %}

## Reasoning Chain
{% for r in data.reasoning_chain %}
{{ loop.index }}. Observed: {{ r.observation }} → Because: {{ r.because }} → Therefore: {{ r.therefore }} ({{ r.confidence }})
{% endfor %}

## Verification
{% for t in data.verification_tests %}
{{ "✅" if t.status == "pass" else "❌" }} {{ t.name }}: {{ t.output }}
{% endfor %}

{% if data.debug_history %}
## Debug History
{% for d in data.debug_history %}
- Attempt {{ d.attempt }}: {{ d.hypothesis }} → {{ d.result | upper }}
{% endfor %}
{% endif %}

## Next Steps
{% if data.next_steps %}
{% for ns in data.next_steps %}
- {{ ns }}
{% endfor %}
{% else %}
- None identified
{% endif %}
```

- [ ] **Step 4: Create JSON schema for agent review**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Agent Review Log",
  "type": "object",
  "required": ["schema_version", "task_id", "timestamp", "spec", "plan", "changes", "verification"],
  "properties": {
    "schema_version": { "const": "1.0" },
    "task_id": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "duration_seconds": { "type": "integer" },
    "spec": {
      "type": "object",
      "required": ["goal", "success_criteria"],
      "properties": {
        "goal": { "type": "string" },
        "scope": { "type": "array", "items": { "type": "string" } },
        "constraints": { "type": "array", "items": { "type": "string" } },
        "non_goals": { "type": "array", "items": { "type": "string" } },
        "success_criteria": { "type": "array", "items": { "type": "object" } }
      }
    },
    "plan": { "type": "array", "items": { "type": "object" } },
    "changes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file", "type", "reason"],
        "properties": {
          "file": { "type": "string" },
          "lines": { "type": "array", "items": { "type": "integer" } },
          "type": { "enum": ["modify", "add", "delete"] },
          "description": { "type": "string" },
          "reason": {
            "type": "object",
            "required": ["because", "therefore"],
            "properties": {
              "because": { "type": "string" },
              "therefore": { "type": "string" }
            }
          }
        }
      }
    },
    "reasoning_chain": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "observation": { "type": "string" },
          "because": { "type": "string" },
          "therefore": { "type": "string" },
          "confidence": { "enum": ["HIGH", "MEDIUM", "LOW"] }
        }
      }
    },
    "verification": {
      "type": "object",
      "required": ["status", "tests"],
      "properties": {
        "status": { "enum": ["pass", "fail"] },
        "tests": { "type": "array" }
      }
    },
    "debug_history": { "type": "array" },
    "next_steps": { "type": "array", "items": { "type": "string" } },
    "entire_session_ref": { "type": "string" }
  }
}
```

- [ ] **Step 5: Implement review_generator.py**

```python
# workflow/review_generator.py
"""Generates dual-format review logs (human .md + agent .json)."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class ChangeEntry:
    file: str
    lines: list[int]
    change_type: str  # modify, add, delete
    description: str
    reason_because: str
    reason_therefore: str


@dataclass
class ReviewData:
    task_id: str
    goal: str
    plan: list[dict]
    changes: list[ChangeEntry]
    reasoning_chain: list[dict]
    verification_status: str  # pass, fail
    verification_tests: list[dict]
    debug_history: list[dict] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    duration_seconds: int = 0
    spec: dict | None = None
    entire_session_ref: str = ""


def generate_review(data: ReviewData, output_dir: Path | None = None) -> tuple[Path, Path]:
    from jinja2 import Template

    if output_dir is None:
        output_dir = Path("reviews")
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    date_str = now.strftime("%Y-%m-%d")
    safe_id = data.task_id.replace(" ", "-").replace("/", "-")

    # Human version (.md)
    template_path = TEMPLATES_DIR / "review-human.md.j2"
    template_text = template_path.read_text(encoding="utf-8")
    template = Template(template_text)
    md_content = template.render(data=data, timestamp=timestamp)

    md_path = output_dir / f"{date_str}-{safe_id}.md"
    md_path.write_text(md_content, encoding="utf-8")

    # Agent version (.agent.json)
    agent_data = {
        "schema_version": "1.0",
        "task_id": data.task_id,
        "timestamp": now.isoformat(),
        "duration_seconds": data.duration_seconds,
        "spec": data.spec or {"goal": data.goal, "success_criteria": []},
        "plan": data.plan,
        "changes": [
            {
                "file": c.file,
                "lines": c.lines,
                "type": c.change_type,
                "description": c.description,
                "reason": {
                    "because": c.reason_because,
                    "therefore": c.reason_therefore,
                },
            }
            for c in data.changes
        ],
        "reasoning_chain": data.reasoning_chain,
        "verification": {
            "status": data.verification_status,
            "tests": data.verification_tests,
        },
        "debug_history": data.debug_history,
        "next_steps": data.next_steps,
        "entire_session_ref": data.entire_session_ref,
    }

    json_path = output_dir / f"{date_str}-{safe_id}.agent.json"
    json_path.write_text(
        json.dumps(agent_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return md_path, json_path
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_review_generator.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add workflow/review_generator.py workflow/templates/review-human.md.j2 workflow/templates/review-agent.schema.json workflow/tests/test_review_generator.py
git commit -m "feat(workflow): add dual-format review log generator"
```

---

## Task 5: AGENTS.md Protocol

The cross-agent instruction file that any AI agent reads and follows.

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 1: Write AGENTS.md**

```markdown
# AGENTS.md — Unified Agentic Workflow Protocol

This file defines the mandatory workflow for ALL AI agents (Claude Code, Codex, Cursor, Copilot) working in this repository. Read this before taking any action.

## Workflow Stages

Every feature or bug fix MUST follow this sequence:

```
1. SPEC    → Define goal, scope, constraints, success criteria
2. PLAN    → Detailed step-by-step implementation plan
3. IMPLEMENT → Execute plan
4. VERIFY  → Run success criteria (acceptance tests)
5. REVIEW  → Generate dual-format review log
```

## Stage 1: Spec

Before writing any code, create a specification with ALL of these fields:

- **task_id**: Unique identifier (e.g., `fix-pipeline-20260511`)
- **goal**: One sentence — what, not how
- **scope**: Which files/modules may be modified
- **constraints**: What must NOT be changed, libraries not to use, compatibility requirements
- **non_goals**: Explicitly excluded work
- **success_criteria**: Executable verification commands with expected results
  - Each criterion: `{"command": "...", "expected": "..."}`
  - `"expected": "all pass"` means exit code 0 is sufficient
  - Otherwise, expected string must appear in stdout
- **plan**: Numbered steps with file targets

Save to: `workflow/active-spec.json` (via `workflow/active_spec.py` or manually)

**MANDATORY**: Do NOT proceed to implementation without user approval of spec.

## Stage 2: Plan

The plan must be detailed enough that:
1. Another agent could execute it without additional context
2. It serves as the "intent" record in the review log
3. Each step names specific files and describes the change

## Stage 3: Implement

Execute the plan. All decisions during implementation MUST have explicit reasoning:

```
Because: <observation or evidence>
Therefore: <action taken>
```

This reasoning is recorded in the review log.

## Stage 4: Verify

Run all `success_criteria` commands from the spec.

- **If ALL pass**: Proceed to Review (Stage 5)
- **If ANY fail**: Enter Debug Mode

### Debug Mode

When verification fails:

1. **STOP** — Do not attempt automatic fixes
2. **Report** — Show terminal summary:
   - Which test failed, expected vs actual
   - 1-3 hypotheses with `Because → Therefore` reasoning
   - Confidence level (HIGH/MEDIUM/LOW) with evidence
3. **Generate HTML report** to `outputs/debug/` with:
   - Data comparison visualization
   - Relevant log lines
   - Hypothesis chain
4. **WAIT** for user direction — do not proceed without confirmation
5. After user confirms direction: fix → re-verify

## Stage 5: Review

Generate two files in `reviews/`:

### Human version (`reviews/YYYY-MM-DD-<task_id>.md`)
- Plan (what was intended)
- Changes table (file, lines, change, reason)
- Reasoning chain (observation → because → therefore)
- Verification results
- Debug history (if any)

### Agent version (`reviews/YYYY-MM-DD-<task_id>.agent.json`)
- Structured JSON following `workflow/templates/review-agent.schema.json`
- Machine-parseable by any agent in future sessions
- Includes spec, plan, changes with reasons, verification, debug history

## Mandatory Behaviors

1. **Never implement without an approved spec** — ask for approval first
2. **Success criteria must be executable** — a command that returns pass/fail
3. **On verification failure: PAUSE** — hypothesize with reasons, wait for user
4. **All decisions need `because → therefore`** — no unexplained changes
5. **Generate review log on completion** — both formats, every time

## File Conventions

| Purpose | Location |
|---------|----------|
| Active task spec | `workflow/active-spec.json` |
| Review logs (human) | `reviews/YYYY-MM-DD-<id>.md` |
| Review logs (agent) | `reviews/YYYY-MM-DD-<id>.agent.json` |
| Debug reports (HTML) | `outputs/debug/YYYY-MM-DD-<name>.html` |
| Verification gate | `workflow/verify.py` |
| Review generator | `workflow/review_generator.py` |

## Agent-Specific Integration

- **Claude Code**: Hooks enforce verify + review (see `.claude/settings.json`)
- **Codex / Cursor / Copilot**: Follow this protocol manually. Run `python workflow/verify.py` before considering task complete.
- **All agents**: Read `reviews/*.agent.json` for prior session context when resuming work.
```

- [ ] **Step 2: Verify AGENTS.md is readable and complete**

Run: `cd D:/Github/gadget && python -c "from pathlib import Path; content = Path('AGENTS.md').read_text(); assert 'success_criteria' in content; assert 'Debug Mode' in content; assert 'PAUSE' in content; print('AGENTS.md valid')"`
Expected: `AGENTS.md valid`

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "feat(workflow): add AGENTS.md cross-agent protocol"
```

---

## Task 6: Install Script

Deploys the workflow to any repo — creates directories, copies files, updates agent configs.

**Files:**
- Create: `workflow/install.py`
- Create: `workflow/tests/test_install.py`

- [ ] **Step 1: Write failing tests for install script**

```python
# workflow/tests/test_install.py
import json
from pathlib import Path

import pytest

from workflow.install import install_workflow


@pytest.fixture
def target_repo(tmp_path):
    (tmp_path / ".git").mkdir()  # Simulate a git repo
    return tmp_path


def test_install_creates_reviews_dir(target_repo):
    install_workflow(target_repo)
    assert (target_repo / "reviews").is_dir()


def test_install_creates_agents_md(target_repo):
    install_workflow(target_repo)
    agents_md = target_repo / "AGENTS.md"
    assert agents_md.exists()
    content = agents_md.read_text(encoding="utf-8")
    assert "Unified Agentic Workflow Protocol" in content
    assert "success_criteria" in content


def test_install_copies_workflow_files(target_repo):
    install_workflow(target_repo)
    assert (target_repo / "workflow" / "verify.py").exists()
    assert (target_repo / "workflow" / "review_generator.py").exists()
    assert (target_repo / "workflow" / "debug_report.py").exists()
    assert (target_repo / "workflow" / "active_spec.py").exists()
    assert (target_repo / "workflow" / "__init__.py").exists()


def test_install_copies_templates(target_repo):
    install_workflow(target_repo)
    assert (target_repo / "workflow" / "templates" / "debug-report.html.j2").exists()
    assert (target_repo / "workflow" / "templates" / "review-human.md.j2").exists()
    assert (target_repo / "workflow" / "templates" / "review-agent.schema.json").exists()


def test_install_creates_claude_hooks_if_claude_dir(target_repo):
    (target_repo / ".claude").mkdir()
    install_workflow(target_repo)
    settings_path = target_repo / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" in settings
    assert "Stop" in settings["hooks"]


def test_install_creates_cursorrules_if_absent(target_repo):
    install_workflow(target_repo)
    cursorrules = target_repo / ".cursorrules"
    assert cursorrules.exists()
    content = cursorrules.read_text(encoding="utf-8")
    assert "AGENTS.md" in content


def test_install_is_idempotent(target_repo):
    install_workflow(target_repo)
    install_workflow(target_repo)  # Should not raise
    assert (target_repo / "AGENTS.md").exists()


def test_install_preserves_existing_claude_settings(target_repo):
    claude_dir = target_repo / ".claude"
    claude_dir.mkdir()
    existing = {"permissions": {"allow": ["Read"]}, "model": "opus"}
    (claude_dir / "settings.json").write_text(json.dumps(existing), encoding="utf-8")
    install_workflow(target_repo)
    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Read"]
    assert settings["model"] == "opus"
    assert "Stop" in settings["hooks"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_install.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workflow.install'`

- [ ] **Step 3: Implement install.py**

```python
# workflow/install.py
"""Deploy the unified workflow to any repository."""

import json
import shutil
from pathlib import Path

WORKFLOW_SRC = Path(__file__).parent
GADGET_ROOT = WORKFLOW_SRC.parent


def install_workflow(target: Path) -> None:
    target = Path(target).resolve()

    # 1. Create reviews/ directory
    (target / "reviews").mkdir(exist_ok=True)

    # 2. Create/update AGENTS.md
    agents_src = GADGET_ROOT / "AGENTS.md"
    agents_dst = target / "AGENTS.md"
    if agents_src.exists():
        shutil.copy2(agents_src, agents_dst)

    # 3. Copy workflow/ files
    target_workflow = target / "workflow"
    target_workflow.mkdir(exist_ok=True)

    files_to_copy = [
        "__init__.py",
        "active_spec.py",
        "verify.py",
        "review_generator.py",
        "debug_report.py",
    ]
    for f in files_to_copy:
        src = WORKFLOW_SRC / f
        if src.exists():
            shutil.copy2(src, target_workflow / f)

    # 4. Copy templates/
    templates_src = WORKFLOW_SRC / "templates"
    templates_dst = target_workflow / "templates"
    if templates_src.exists():
        if templates_dst.exists():
            shutil.rmtree(templates_dst)
        shutil.copytree(templates_src, templates_dst)

    # 5. Install Claude Code hooks (if .claude/ exists)
    claude_dir = target / ".claude"
    if claude_dir.exists():
        settings_path = claude_dir / "settings.json"
        settings = {}
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8"))

        if "hooks" not in settings:
            settings["hooks"] = {}

        settings["hooks"]["Stop"] = [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python workflow/verify.py",
                        "timeout": 60,
                    }
                ],
            }
        ]

        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # 6. Create .cursorrules stub
    cursorrules = target / ".cursorrules"
    if not cursorrules.exists():
        cursorrules.write_text(
            "# Cursor Rules\n\n"
            "Read and follow AGENTS.md for the mandatory workflow protocol.\n"
            "All stages (spec → plan → implement → verify → review) are required.\n",
            encoding="utf-8",
        )

    print(f"✓ Workflow installed to {target}")
    print(f"  - reviews/ directory: created")
    print(f"  - AGENTS.md: {'updated' if agents_dst.exists() else 'created'}")
    print(f"  - workflow/ scripts: copied")
    if claude_dir.exists():
        print(f"  - .claude/settings.json: hooks added")
    print(f"  - .cursorrules: {'exists' if cursorrules.exists() else 'created'}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python workflow/install.py <target-repo-path>")
        print("Example: python workflow/install.py .")
        sys.exit(1)

    target_path = Path(sys.argv[1])
    if not (target_path / ".git").exists():
        print(f"Error: {target_path} is not a git repository (no .git/ found)")
        sys.exit(1)

    install_workflow(target_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_install.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add workflow/install.py workflow/tests/test_install.py
git commit -m "feat(workflow): add install script for cross-repo deployment"
```

---

## Task 7: git-cliff Configuration

Minimal `cliff.toml` for generating changelogs from conventional commits.

**Files:**
- Create: `cliff.toml`

- [ ] **Step 1: Write cliff.toml**

```toml
# cliff.toml — git-cliff configuration
# Generate changelog: git-cliff -o CHANGELOG.md

[changelog]
header = "# Changelog\n\n"
body = """
{% for group, commits in commits | group_by(attribute="group") %}
    ## {{ group | upper_first }}
    {% for commit in commits %}
        - {{ commit.message | upper_first }} ({{ commit.id | truncate(length=7, end="") }})\
    {% endfor %}
{% endfor %}\n
"""
trim = true

[git]
conventional_commits = true
filter_unconventional = true
split_commits = false

commit_parsers = [
    { message = "^feat", group = "Features" },
    { message = "^fix", group = "Bug Fixes" },
    { message = "^refactor", group = "Refactoring" },
    { message = "^perf", group = "Performance" },
    { message = "^docs", group = "Documentation" },
    { message = "^test", group = "Testing" },
    { message = "^chore", group = "Miscellaneous" },
]

filter_commits = false
tag_pattern = "v[0-9]*"
skip_tags = ""
ignore_tags = ""
topo_order = false
sort_commits = "newest"
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:/Github/gadget && python -c "import tomllib; tomllib.loads(open('cliff.toml').read()); print('cliff.toml valid')"`
Expected: `cliff.toml valid`

- [ ] **Step 3: Commit**

```bash
git add cliff.toml
git commit -m "chore(workflow): add git-cliff changelog configuration"
```

---

## Task 8: Integration Test — Full Cycle

End-to-end test proving the workflow works: create spec → verify pass → review generated.

**Files:**
- Create: `workflow/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# workflow/tests/test_integration.py
"""End-to-end integration test for the full workflow cycle."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.active_spec import create_spec, load_spec, clear_spec
from workflow.verify import run_verification
from workflow.review_generator import ReviewData, ChangeEntry, generate_review
from workflow.debug_report import DebugSession, Hypothesis, generate_terminal_report, generate_html_report


@pytest.fixture
def workflow_env(tmp_path):
    """Set up isolated workflow environment."""
    with patch("workflow.active_spec.WORKFLOW_DIR", tmp_path), \
         patch("workflow.active_spec.ACTIVE_SPEC_PATH", tmp_path / "active-spec.json"), \
         patch("workflow.verify.WORKFLOW_DIR", tmp_path):
        # Also patch load_spec in verify to use our tmp path
        import workflow.verify
        original_load = workflow.verify.load_spec

        def patched_load():
            from workflow.active_spec import ACTIVE_SPEC_PATH
            if not (tmp_path / "active-spec.json").exists():
                from workflow.active_spec import SpecNotFoundError
                raise SpecNotFoundError("no spec")
            return json.loads((tmp_path / "active-spec.json").read_text(encoding="utf-8"))

        workflow.verify.load_spec = patched_load
        yield tmp_path
        workflow.verify.load_spec = original_load


def test_full_pass_cycle(workflow_env, tmp_path):
    """Spec → Verify PASS → Review generated."""
    # Stage 1: Create spec
    spec = {
        "task_id": "integration-test-pass",
        "goal": "Verify full cycle works",
        "scope": ["test_file.py"],
        "constraints": [],
        "non_goals": [],
        "success_criteria": [
            {"command": "echo success", "expected": "success"},
        ],
        "plan": [
            {"step": 1, "description": "Run echo command", "files": ["test_file.py"]},
        ],
    }
    create_spec(spec)

    # Stage 4: Verify
    result = run_verification()
    assert result.passed is True

    # Stage 5: Generate review
    review_data = ReviewData(
        task_id="integration-test-pass",
        goal="Verify full cycle works",
        plan=spec["plan"],
        changes=[
            ChangeEntry(
                file="test_file.py",
                lines=[1],
                change_type="add",
                description="Added test file",
                reason_because="integration test requires a file change",
                reason_therefore="created minimal test file",
            ),
        ],
        reasoning_chain=[
            {
                "observation": "Need to verify full workflow",
                "because": "this is an integration test",
                "therefore": "created a passing scenario",
                "confidence": "HIGH",
            },
        ],
        verification_status="pass",
        verification_tests=[{"name": "echo success", "status": "pass", "output": "success"}],
        duration_seconds=60,
    )

    reviews_dir = tmp_path / "reviews"
    md_path, json_path = generate_review(review_data, output_dir=reviews_dir)

    assert md_path.exists()
    assert json_path.exists()
    assert "integration-test-pass" in md_path.read_text(encoding="utf-8")

    # Cleanup
    clear_spec()


def test_full_fail_cycle_with_debug(workflow_env, tmp_path):
    """Spec → Verify FAIL → Debug Mode → terminal + HTML report."""
    # Stage 1: Create spec with failing criterion
    spec = {
        "task_id": "integration-test-fail",
        "goal": "Test debug mode triggers",
        "scope": [],
        "constraints": [],
        "non_goals": [],
        "success_criteria": [
            {"command": "echo actual_value", "expected": "expected_value"},
        ],
        "plan": [
            {"step": 1, "description": "Deliberately fail", "files": []},
        ],
    }
    create_spec(spec)

    # Stage 4: Verify — should fail
    result = run_verification()
    assert result.passed is False

    # Stage 4b: Debug mode
    session = DebugSession(
        test_name="echo actual_value",
        expected="expected_value",
        actual="actual_value",
        hypotheses=[
            Hypothesis(
                description="Command outputs wrong value",
                because="echo prints its argument literally",
                therefore="the command itself is the problem",
                confidence="HIGH",
                evidence="echo actual_value → 'actual_value'",
            ),
        ],
        log_lines=["$ echo actual_value", "actual_value"],
    )

    terminal_output = generate_terminal_report(session)
    assert "VERIFICATION FAILED" in terminal_output
    assert "Awaiting your direction" in terminal_output

    debug_dir = tmp_path / "debug"
    html_path = generate_html_report(session, output_dir=debug_dir)
    assert html_path.exists()
    assert "expected_value" in html_path.read_text(encoding="utf-8")

    # Cleanup
    clear_spec()
```

- [ ] **Step 2: Run integration tests**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/test_integration.py -v`
Expected: Both tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd D:/Github/gadget && python -m pytest workflow/tests/ -v`
Expected: All tests PASS (approximately 22 tests across all files)

- [ ] **Step 4: Commit**

```bash
git add workflow/tests/test_integration.py
git commit -m "test(workflow): add end-to-end integration tests"
```

---

## Task 9: Install to Gadget Repo (Self-Deploy)

Run the install script on gadget itself and verify everything works.

**Files:**
- Modify: `.gitignore` (add `workflow/active-spec.json`, `outputs/debug/`)
- Create: `reviews/.gitkeep`

- [ ] **Step 1: Create reviews directory**

```bash
mkdir -p D:/Github/gadget/reviews
touch D:/Github/gadget/reviews/.gitkeep
```

- [ ] **Step 2: Update .gitignore**

Add these lines to `.gitignore`:

```
# Workflow
workflow/active-spec.json
outputs/debug/
```

- [ ] **Step 3: Run install on self**

Run: `cd D:/Github/gadget && python workflow/install.py .`
Expected output:
```
✓ Workflow installed to D:\Github\gadget
  - reviews/ directory: created
  - AGENTS.md: updated
  - workflow/ scripts: copied
  - .cursorrules: created
```

- [ ] **Step 4: Verify the full cycle manually**

Run: `cd D:/Github/gadget && python -c "
from workflow.active_spec import create_spec, clear_spec
from workflow.verify import run_verification

spec = {
    'task_id': 'self-test',
    'goal': 'Verify install works',
    'scope': [],
    'constraints': [],
    'non_goals': [],
    'success_criteria': [{'command': 'echo installed', 'expected': 'installed'}],
    'plan': [{'step': 1, 'description': 'test', 'files': []}],
}
create_spec(spec)
result = run_verification()
assert result.passed, result.terminal_summary()
clear_spec()
print('✓ Self-test passed')
"`
Expected: `✓ Self-test passed`

- [ ] **Step 5: Commit**

```bash
git add reviews/.gitkeep .gitignore .cursorrules
git commit -m "chore(workflow): self-deploy workflow to gadget repo"
```

---

## Task 10: Dependencies

Ensure Jinja2 is available (needed by review_generator and debug_report).

**Files:**
- Modify: `requirements.txt` or `pyproject.toml` (add jinja2)

- [ ] **Step 1: Check if jinja2 is already available**

Run: `cd D:/Github/gadget && python -c "import jinja2; print(f'jinja2 {jinja2.__version__} available')"`

If available: skip Step 2, proceed to Step 3.
If not: proceed to Step 2.

- [ ] **Step 2: Install jinja2 (if needed)**

Run: `pip install jinja2`

- [ ] **Step 3: Add to project dependencies**

Add `jinja2` to the appropriate requirements or pyproject.toml under the workflow extra:

```toml
# In pyproject.toml [project.optional-dependencies]
workflow = ["jinja2>=3.1", "pytest>=7.0"]
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(workflow): add jinja2 dependency for templates"
```

---

## Post-Implementation Verification

After all tasks are complete, run the spec's own success criteria:

1. `python workflow/install.py .` — runs without error ✓
2. Full cycle test — `python -m pytest workflow/tests/test_integration.py -v` passes ✓
3. Debug mode test — integration test covers failing verification ✓
4. `reviews/` has dual format — integration test verifies both files ✓
5. AGENTS.md readable — `grep "success_criteria" AGENTS.md` returns matches ✓
6. Install to blank repo — `python workflow/install.py /tmp/test-repo` (after `git init /tmp/test-repo`) ✓

---

Plan complete and saved to `docs/superpowers/plans/2026-05-11-unified-workflow.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
