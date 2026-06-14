# Phase 22 — AI Architecture Agent Gate

## Overview

Phase 22 adds the **AI Architecture Agent** layer to the agent-manager framework. It reads a Phase 21 Feature Brief and generates a deterministic mock architecture proposal artifact without executing any model calls, OpenHands tasks, or source writes by default.

## Scope

### In scope
- `scripts/run_architecture_agent.py` — Core architecture-agent entry point
- `schemas/architecture_proposal.schema.json` — Architecture proposal JSON schema (already exists)
- `tests/test_architecture_agent.py` — Unit and integration tests
- `docs/PHASE22_GATE.md` — This gate document

### Out of scope (explicitly excluded)
- Manager objective planning
- OpenHands request drafting
- Live model inference / model calls by default
- Coder task execution
- Writing to target project repositories
- Enabling live model calls without explicit approval

## Gate Criteria

| Criterion | Status |
|-----------|--------|
| `scripts/run_architecture_agent.py` exists and compiles | PASS |
| `schemas/architecture_proposal.schema.json` validates proposals | PASS |
| `tests/test_architecture_agent.py` passes all tests | PASS |
| Mock mode generates ARCHITECTURE_PROPOSAL.json + .md + prompt | PASS |
| Missing feature brief fails safely (SystemExit) | PASS |
| Invalid project_id fails safely (SystemExit) | PASS |
| Model calls refused without --allow-model-call AND env var | PASS |
| proposal JSON validates against schema | PASS |
| Proposal Markdown is created and readable | PASS |
| Proposal references correct project_id and feature_id | PASS |
| No source writes / no OpenHands flags are false in mock mode | PASS |
| Malformed architecture proposal fails validation | PASS |

## Usage

### Mock mode (default safe)
```bash
python3 scripts/run_architecture_agent.py <project_id> \
  --feature-id feat_my_feature --mock
```

### With explicit model-call allowance (requires BOTH conditions)
```bash
AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 \
  python3 scripts/run_architecture_agent.py <project_id> \
  --feature-id feat_my_feature --allow-model-call
```

## Generated Artifacts

Under `runs/<project_id>/architecture_proposals/<feature_id>/`:

| Artifact | Description |
|----------|-------------|
| ARCHITECTURE_PROPOSAL.json | Structured architecture proposal (schema-validated) |
| ARCHITECTURE_PROPOSAL.md | Human-readable Markdown summary |
| ARCHITECTURE_AGENT_PROMPT.md | Agent prompt derived from the feature brief + proposal |

## Safety Guarantees

1. **No model calls by default** — Requires both `--allow-model-call` flag AND `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1`.
2. **No source writes** — `source_writes_performed` is always `false` in mock mode.
3. **No OpenHands execution** — `openhands_executed` is always `false` in mock mode.
4. **Deterministic output** — `--mock` produces identical structure given the same feature brief input.
5. **Schema validation** — All generated JSON must pass the architecture proposal schema before being written.

## Validation

Run Phase 22 validation as part of the standard agent run:
```bash
python3 scripts/validate_agent_run.py <project_id>
```

The validator checks for the presence and integrity of architecture proposal artifacts alongside other phase artifacts.

## Dependencies on Previous Phases

- **Phase 21** (Feature Brief Intake): Architecture agent reads `FEATURE_BRIEF.json` from Phase 21 output directory. The brief must have `generated_by: "phase21_feature_brief_intake"`.
