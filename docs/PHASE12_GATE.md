# Phase 12 LangGraph Migration Gate

Phase 12 wraps the proven deterministic flow in LangGraph without changing the authority model. LangGraph is used only to express node order and checkpoint-compatible state. It must not call models, run OpenHands, modify target project source behavior, auto-merge, or auto-push.

## Dependency

LangGraph is an external Python dependency and is not vendored in this repository.

Install or update it in the active environment with:

```bash
python -m pip install -U langgraph
```

If LangGraph is unavailable, `scripts/run_langgraph_v0.py` fails clearly and prints the same install hint. Unit tests avoid requiring real LangGraph execution.

## Deterministic Flow

The graph preserves this existing sequence:

1. `scripts/collect_project_metrics.py <project_id>`
2. `scripts/run_nightly_v0.py <project_id>`
3. `scripts/manager_planning_pass.py <project_id>`
4. `scripts/write_morning_report.py <project_id>`
5. `scripts/validate_agent_run.py <project_id>`
6. `scripts/run_readonly_review_agents.py <project_id>` in Phase 13 and later

The graph nodes are:

- `load_project`
- `collect_metrics`
- `run_plain_runner_v0`
- `run_manager_planning_pass`
- `write_morning_report`
- `validate_agent_run`
- `run_readonly_review_agents` in Phase 13 and later
- `finalize`

## Run

```bash
python3 scripts/run_langgraph_v0.py thomsonlint
```

The script accepts any registered `project_id`; `thomsonlint` is only the first real configured project.

## Artifacts

Each run writes central artifacts under:

```text
runs/<project_id>/langgraph_v0_<timestamp>/
```

Required artifacts:

- `LANGGRAPH_RUN_MANIFEST.json`
- `LANGGRAPH_STATE_FINAL.json`
- `LANGGRAPH_NODE_TRACE.json`
- `LANGGRAPH_REPORT.md`

The latest pointer is:

```text
runs/<project_id>/latest_langgraph_v0
```

The graph state carries artifact references and command tails, not large file contents.

## Validation

Run:

```bash
python3 -m py_compile scripts/run_langgraph_v0.py
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/run_langgraph_v0.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```

`scripts/validate_agent_run.py` remains the deterministic validation authority. When `latest_langgraph_v0` is present, it validates the Phase 12 manifest, final state, node trace, report readability, expected node order, and validation-authority safety flag.
