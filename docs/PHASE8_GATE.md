# Phase 8 Gate

Phase 8 is complete when:

- `scripts/manager_planning_pass.py` exists.
- It reads project-local weekly plan and objective backlog.
- It reads latest deterministic metrics and runner artifacts.
- It selects one safe non-write objective.
- It writes central manager artifacts under `runs/<project_id>/manager_plan_<timestamp>/`.
- It creates or updates `runs/<project_id>/latest_manager_plan`.
- Generated artifacts include:
  - `MANAGER_CONTEXT.json`
  - `MANAGER_DECISION.json`
  - `MANAGER_PLAN.md`
  - `NEXT_ACTION.md`
- Generated JSON parses.
- Target repo remains clean.
- No OpenHands run occurs.
- No model calls occur.
- No LangGraph runtime occurs.
- No target project source behavior is modified.
