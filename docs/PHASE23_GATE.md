# Phase 23 — AI Manager Objective Planner Gate

## Overview

Phase 23 adds the **AI Manager Objective Planner** to the agent-manager framework. It consumes a Phase 21 Feature Brief and a Phase 22 Architecture Proposal, then produces a bounded manager objective plan and a draft OpenHands manual gate request for human review.

**This phase is planning-only.** It may generate request drafts, but it must not execute them. No model calls by default; requires both `--allow-model-call` flag and `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1` env var for live mode.

## Scope

### In scope
- `scripts/run_manager_objective_planner.py` — Core manager-planner entry point
- `schemas/manager_objective_plan.schema.json` — Manager objective plan JSON schema
- `tests/test_manager_objective_planner.py` — Unit and integration tests
- `docs/PHASE23_GATE.md` — This gate document

### Out of scope (explicitly excluded)
- Multi-project planning board behavior (Phase 24 — not implemented in Phase 23)
- Executing the OpenHands manual gate request draft
- Source code implementation or modification
- Live model inference / model calls by default
- Coder task execution
- Writing to target project repositories
- Enabling live model calls without explicit approval

## Gate Criteria

| Criterion | Status |
|-----------|--------|
| `scripts/run_manager_objective_planner.py` exists and compiles | PASS |
| `schemas/manager_objective_plan.schema.json` validates plans | PASS |
| `tests/test_manager_objective_planner.py` passes all tests | PASS |
| Mock mode generates MANAGER_OBJECTIVE_PLAN.json + .md + draft request | PASS |
| Missing feature brief fails safely (SystemExit) | PASS |
| Missing architecture proposal fails safely (SystemExit) | PASS |
| Invalid project_id fails safely (SystemExit) | PASS |
| Model calls refused without --allow-model-call AND env var | PASS |
| Plan JSON validates against schema | PASS |
| Plan Markdown is created and readable | PASS |
| OpenHands manual gate request draft is created with draft_only=true | PASS |
| Draft request has approved_for_execution=false | PASS |
| Proposal references correct project_id and feature_id | PASS |
| No source writes / no OpenHands flags are false in mock mode | PASS |
| Malformed manager objective plan fails validation | PASS |
| Execution-enabled draft request fails validation checks | PASS |
| Target repo remains untouched during Phase 23 planning | PASS |

## Usage

### Mock mode (default safe)

```bash
python3 scripts/run_manager_objective_planner.py <project_id> \
  --feature-id <feature_id> \
  --mock
```

Example:

```bash
python3 scripts/run_manager_objective_planner.py thomsonlint \
  --feature-id feat_manager_planner_smoke \
  --mock
```

### With explicit model-call allowance (requires BOTH conditions)

```bash
AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 \
python3 scripts/run_manager_objective_planner.py <project_id> \
  --feature-id <feature_id> \
  --allow-model-call
```

## Generated Artifacts

Artifacts are stored under central agent-manager run/state storage, not in target project repos:

```
runs/<project_id>/manager_objective_plans/<feature_id>/
├── MANAGER_OBJECTIVE_PLAN.json          # Bounded manager objective plan (JSON)
├── MANAGER_OBJECTIVE_PLAN.md            # Human-readable plan summary
├── OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json  # Draft request for human review
└── MANAGER_OBJECTIVE_PLANNER_PROMPT.md  # Generated planner prompt reference
```

### MANAGER_OBJECTIVE_PLAN.json fields

| Field | Type | Description |
|-------|------|-------------|
| schema_version | int (const: 1) | Schema version |
| generated_by | string | Always "phase23_ai_manager_objective_planner" |
| created_utc | string | UTC timestamp YYYYMMDDTHHMMSSZ |
| project_id | string | Registered project identifier |
| feature_id | string | Feature ID from source brief |
| source_feature_brief_path | string | Path to FEATURE_BRIEF.json |
| source_architecture_proposal_path | string | Path to ARCHITECTURE_PROPOSAL.json |
| title | string | Plan title |
| manager_plan_status | enum | draft_ready / needs_clarification / blocked |
| objective_id | string | Unique objective identifier |
| objective_summary | string | What must be achieved |
| selected_architecture_summary | string | Selected architecture summary |
| bounded_scope | string | Implementation scope description |
| allowed_files | array[] | Files explicitly allowed to modify |
| disallowed_files | array[] | Files explicitly disallowed from modification |
| implementation_steps | array[] | Ordered implementation steps |
| validation_commands | array[] | Commands to validate implementation |
| acceptance_criteria | array[] | Criteria that must be met (at least 1) |
| risk_controls | array[] | Risk controls and mitigations |
| rollback_plan | string | Rollback plan if implementation fails |
| dependencies | array[] | Dependencies before implementation can begin |
| assumptions | array[] | Assumptions made during planning |
| constraints | array[] | Constraints on the implementation |
| out_of_scope | array[] | Items explicitly out of scope |
| questions_for_human | array[] | Questions requiring human review |
| ready_for_openhands_manual_gate | bool | Whether plan is ready for gate review |
| model_call_allowed | bool | Whether a model call was allowed |
| model_called | bool | Whether a live model was called |
| source_writes_performed | bool | Always false (planning-only) |
| openhands_executed | bool | Always false (planning-only) |
| coder_task_executed | bool | Always false (planning-only) |
| apply_performed | bool | Always false (planning-only) |
| commit_performed | bool | Always false (planning-only) |
| push_performed | bool | Always false (planning-only) |
| merge_performed | bool | Always false (planning-only) |
| pr_created | bool | Always false (planning-only) |

### OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json fields

| Field | Type | Description |
|-------|------|-------------|
| schema_version | int (const: 1) | Schema version |
| generated_by | string | "phase23_ai_manager_objective_planner" |
| created_utc | string | UTC timestamp |
| project_id | string | Project identifier |
| feature_id | string | Feature ID |
| objective_id | string | Objective identifier |
| title | string | Plan title |
| task_summary | string | Task summary from plan |
| allowed_files | array[] | Allowed files from plan |
| disallowed_files | array[] | Disallowed files from plan |
| validation_commands | array[] | Validation commands from plan |
| acceptance_criteria | array[] | Acceptance criteria from plan |
| safety_notes | array[] | Safety notes for human review |
| source_manager_objective_plan_path | string | Path to the source plan JSON |
| draft_only | bool | Always true (never auto-consumed) |
| approved_for_execution | bool | Always false (needs human approval) |
| openhands_executed | bool | False |
| source_writes_performed | bool | False |
| apply_performed | bool | False |
| commit_performed | bool | False |
| push_performed | bool | False |
| merge_performed | bool | False |
| pr_created | bool | False |

## Safety Guarantees

**Phase 23 is planning-only and draft-only.** The following guarantees are enforced:

1. **No OpenHands execution** — `openhands_executed` is always false
2. **No coder task execution** — `coder_task_executed` is always false
3. **No source writes to target repos** — `source_writes_performed` is always false
4. **No apply/commit/push/merge/PR behavior** — all corresponding flags are always false
5. **Model calls disabled by default** — requires both `--allow-model-call` flag AND `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1` env var
6. **OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json is draft-only** — marked `draft_only=true`, never auto-consumed by any runner in Phase 23
7. **Draft request not approved for execution** — marked `approved_for_execution=false`
8. **Artifacts stored in central runs/ storage** — not written to target project repos

## Validation

Run the following validation commands after Phase 23 planning:

```bash
# Python syntax check
python3 -m py_compile scripts/run_manager_objective_planner.py

# Unit tests
python3 -m unittest discover -s tests

# Portability audit
python3 scripts/audit_portibility.py

# Agent run validation (requires prior Phase 21 + 22 artifacts)
python3 scripts/validate_agent_run.py <project_id>
```

## Model-Call Gating

The script enforces a dual-gate for live model calls:

| `--allow-model-call` | `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS` | Result |
|----------------------|---------------------------------------|--------|
| (not set) | (not set) | Mock mode (safe default) |
| (not set) | 1 | Mock mode (flag not provided) |
| --allow-model-call | (not set) | Mock mode (env var not set) |
| --allow-model-call | 1 | Live gated mode |

In mock mode, `model_call_allowed` and `model_called` are both guaranteed to be false.

## Dependencies on Previous Phases

Phase 23 depends on artifacts from:

- **Phase 21** (Feature Brief Intake): FEATURE_BRIEF.json must exist for the given feature_id
- **Phase 22** (AI Architecture Agent): ARCHITECTURE_PROPOSAL.json must exist for the given feature_id

Both source artifacts are validated before generating the manager objective plan. If either is missing or invalid, the planner exits with a clear SystemExit error.

## Explicit Statements

- **Phase 23 is planning-only and draft-only.** No execution, no implementation, no code changes.
- **OpenHands execution remains forbidden in Phase 23.** The draft request must be reviewed by a human before any downstream execution.
- **No live model call unless explicitly gated with both --allow-model-call flag AND AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 env var.**
