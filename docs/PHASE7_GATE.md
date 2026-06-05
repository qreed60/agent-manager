# Phase 7 Gate

Phase 7 is complete when:

- `scripts/run_nightly_v0.py` exists.
- It calls the deterministic metrics collector.
- It selects one non-write objective from project-local `OBJECTIVE_BACKLOG.json`.
- It writes central runner artifacts under `runs/<project_id>/runner_v0_<timestamp>/`.
- It creates or updates `runs/<project_id>/latest_runner_v0`.
- Generated artifacts include:
  - `ACTIVE_OBJECTIVE.json`
  - `TASK_GRAPH.json`
  - `RUN_MANIFEST.json`
  - `MORNING_REPORT.md`
- Generated JSON parses.
- The target repo remains clean.
- No OpenHands run occurs.
- No model calls occur.
- No LangGraph runtime occurs.
- No target project source behavior is modified.
