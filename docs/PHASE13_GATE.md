# Phase 13 Read-only Review Agent Scaffold Gate

Phase 13 adds deterministic read-only review agent scaffolding. The default implementation does not call models, does not run OpenHands, does not modify target project source, does not auto-merge, and does not auto-push. Deterministic validation remains the authority.

## Run

```bash
python3 scripts/run_readonly_review_agents.py thomsonlint
```

The script accepts any registered `project_id`; `thomsonlint` is only the first configured project.

## Inputs

The scaffold reads the latest central artifacts:

- `runs/<project_id>/latest_validation/VALIDATION_REPORT.json`
- `runs/<project_id>/latest_morning_report/MORNING_REPORT.json`
- `runs/<project_id>/latest_langgraph_v0/LANGGRAPH_RUN_MANIFEST.json`
- `runs/<project_id>/latest_langgraph_v0/LANGGRAPH_STATE_FINAL.json`

## Outputs

Each run writes:

```text
runs/<project_id>/review_agents_<timestamp>/
```

Required artifacts:

- `VALIDATION_REVIEW.json`
- `VALIDATION_REVIEW.md`
- `SQA_REVIEW.json`
- `SQA_REVIEW.md`
- `SECURITY_REVIEW.json`
- `SECURITY_REVIEW.md`
- `REVIEW_AGENTS_SUMMARY.json`
- `REVIEW_AGENTS_SUMMARY.md`

The latest pointer is:

```text
runs/<project_id>/latest_review_agents
```

## JSON Shape

The central JSON schema is `schemas/review_agent_report.schema.json`. The review agents are:

- `validation_review`
- `sqa_review`
- `security_review`

Every JSON report, including `review_agents_summary`, includes:

- `agent`
- `status`: `pass`, `warn`, or `fail`
- `blocking`: `true` or `false`
- `findings`: list
- `artifacts_reviewed`: list
- `generated_by`: `deterministic_scaffold`

## Deterministic Scaffold Behavior

- `validation_review` summarizes deterministic validation status from `VALIDATION_REPORT.json`.
- `sqa_review` checks whether recent test or unittest evidence is available in the reviewed artifacts.
- `security_review` checks safety flags from validation, morning report, and LangGraph reports.

Warnings are nonblocking. Blocking failures exit nonzero.

## LangGraph Integration

`scripts/run_langgraph_v0.py` now runs `run_readonly_review_agents` after `validate_agent_run` and before `finalize`. The node invokes:

```bash
python3 scripts/run_readonly_review_agents.py <project_id>
```

The node is recorded in `LANGGRAPH_NODE_TRACE.json` and produces `runs/<project_id>/latest_review_agents`.

## Validation

Run:

```bash
python3 -m py_compile scripts/run_readonly_review_agents.py
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/run_readonly_review_agents.py thomsonlint
python3 scripts/run_langgraph_v0.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```

When `latest_review_agents` is present, `scripts/validate_agent_run.py` validates all Phase 13 JSON and Markdown artifacts.
