# Phase 15 Deterministic Multi-model Routing Gate

Phase 15 adds deterministic model-role routing metadata only. The default implementation does not call models, does not run OpenHands, does not modify target project source, does not auto-merge, and does not auto-push. Deterministic validation remains the authority.

## Run

```bash
python3 scripts/compile_model_routing_plan.py thomsonlint
```

The script accepts any registered `project_id`; `thomsonlint` is only the first configured project.

## Inputs

The compiler reads central routing inputs:

- `configs/projects.json`
- `configs/model_registry.json`
- `configs/routing_rules.md`

It reads project-local planning state:

- `<repo>/<project_state_dir>/WEEKLY_PLAN.json`
- `<repo>/<project_state_dir>/OBJECTIVE_BACKLOG.json`

It also reads latest central artifacts when present:

- `runs/<project_id>/latest_runner_v0/ACTIVE_OBJECTIVE.json`
- `runs/<project_id>/latest_runner_v0/TASK_GRAPH.json`
- `runs/<project_id>/latest_manager_plan/MANAGER_DECISION.json`
- `runs/<project_id>/latest_review_agents/REVIEW_AGENTS_SUMMARY.json`
- `runs/<project_id>/latest_validation/VALIDATION_REPORT.json`
- `runs/<project_id>/latest_morning_report/MORNING_REPORT.json`
- `runs/<project_id>/latest_langgraph_v0/LANGGRAPH_RUN_MANIFEST.json`

Missing latest artifacts are recorded as metadata presence, not treated as execution triggers.

## Outputs

Each run writes:

```text
runs/<project_id>/model_routing_<timestamp>/
```

Required artifacts:

- `MODEL_ROUTING_PLAN.json`
- `MODEL_ROUTING_PLAN.md`
- `TASK_MODEL_ASSIGNMENTS.json`
- `MODEL_ROUTING_SUMMARY.json`
- `MODEL_ROUTING_SUMMARY.md`

The latest pointer is:

```text
runs/<project_id>/latest_model_routing
```

## Role Scaffold

- `long_reasoning`: manager planning, risk review, architecture review
- `instruct`: structured summaries, classification, report condensation
- `vision`: image/visual evidence extraction only
- `coding_agent`: isolated worktree code edits only
- `embedding`: retrieval/indexing support only if configured

All assignments set `execution_enabled: false`, `model_calls_enabled: false`, `openhands_execution_enabled: false`, `source_writes_enabled: false`, `auto_merge_enabled: false`, and `auto_push_enabled: false`.

Only `coding_agent` can be write-capable in metadata. The compiler enforces at most one write-capable assignment. Phase 15 does not execute the coding agent.

## LangGraph Integration

`scripts/run_langgraph_v0.py` runs `compile_model_routing_plan` after `run_readonly_review_agents` and before `finalize`. The node invokes:

```bash
python3 scripts/compile_model_routing_plan.py <project_id>
```

The node is recorded in `LANGGRAPH_NODE_TRACE.json` and produces `runs/<project_id>/latest_model_routing`.

## Validation

Run:

```bash
python3 -m py_compile scripts/compile_model_routing_plan.py
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/compile_model_routing_plan.py thomsonlint
python3 scripts/run_langgraph_v0.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```

When `latest_model_routing` is present, `scripts/validate_agent_run.py` validates all Phase 15 artifacts and checks model assignment safety invariants.
