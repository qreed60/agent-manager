# Phase 14 Scalability and Architecture Review Agents Gate

Phase 14 extends the deterministic read-only review agent scaffold with advisory scalability and architecture reviews. The default implementation does not call models, does not run OpenHands, does not modify target project source, does not auto-merge, and does not auto-push. Deterministic validation remains the authority.

## Run

```bash
python3 scripts/run_readonly_review_agents.py thomsonlint
```

The script accepts any registered `project_id`; `thomsonlint` is only the first configured project.

## Inputs

The scaffold requires the Phase 13 latest artifacts:

- `runs/<project_id>/latest_validation/VALIDATION_REPORT.json`
- `runs/<project_id>/latest_morning_report/MORNING_REPORT.json`
- `runs/<project_id>/latest_langgraph_v0/LANGGRAPH_RUN_MANIFEST.json`
- `runs/<project_id>/latest_langgraph_v0/LANGGRAPH_STATE_FINAL.json`

It also reads optional evidence when present:

- `runs/<project_id>/latest_runner_v0/ACTIVE_OBJECTIVE.json`
- `runs/<project_id>/latest_manager_plan/MANAGER_DECISION.json`
- `runs/<project_id>/latest_langgraph_v0/LANGGRAPH_NODE_TRACE.json`
- latest validation, morning report, and LangGraph Markdown reports
- `runs/<project_id>/latest_portability_audit/PORTABILITY_AUDIT.json`

Missing optional evidence is reported as a nonblocking warning.

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
- `SCALABILITY_REVIEW.json`
- `SCALABILITY_REVIEW.md`
- `ARCHITECTURE_REVIEW.json`
- `ARCHITECTURE_REVIEW.md`
- `REVIEW_AGENTS_SUMMARY.json`
- `REVIEW_AGENTS_SUMMARY.md`

The latest pointer remains:

```text
runs/<project_id>/latest_review_agents
```

## Review Agents

`REVIEW_AGENTS_SUMMARY.json` and `REVIEW_AGENTS_SUMMARY.md` include all five advisory reports:

- `validation_review`
- `sqa_review`
- `security_review`
- `scalability_review`
- `architecture_review`

`scalability_review` checks latest run directory artifact counts and byte sizes, LangGraph node trace completion, whether validation timestamp evidence follows LangGraph timestamp evidence, retry/resume/checkpoint artifact presence, and report mentions of large artifact handling, runtime, recomputation, or token/prompt growth when applicable.

`architecture_review` checks Phase 14 objective alignment, portable project id shape, portability audit evidence when available, deterministic validation authority, read-only review behavior, no target source modification, and no auto-merge or auto-push evidence.

Warnings are advisory and nonblocking. Blocking authority remains with deterministic validation and the existing safety checks.

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

When `latest_review_agents` is present, `scripts/validate_agent_run.py` validates all Phase 14 JSON and Markdown artifacts and checks that the summary includes all five reports.
