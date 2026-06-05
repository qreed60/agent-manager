# Phase 11 Gate

Phase 11 is complete when:

- `scripts/write_morning_report.py` exists.
- It accepts a project id argument, for example:

```bash
python3 scripts/write_morning_report.py thomsonlint
```

- Default mode is safe and central-artifact-only.
- Default mode does not modify the target project repository.
- It reads `configs/projects.json`.
- It reads project-local state from the configured target repo:
  - `.agent_manager/WEEKLY_PLAN.json`
  - `.agent_manager/OBJECTIVE_BACKLOG.json`
- It reads latest central artifacts:
  - `runs/<project_id>/latest/RUN_METRICS.json`
  - `runs/<project_id>/latest/VALIDATION_SUMMARY.json`
  - `runs/<project_id>/latest_runner_v0/RUN_MANIFEST.json`
  - `runs/<project_id>/latest_runner_v0/MORNING_REPORT.md`
  - `runs/<project_id>/latest_manager_plan/MANAGER_DECISION.json`
  - `runs/<project_id>/latest_manager_plan/MANAGER_PLAN.md`
  - `runs/<project_id>/latest_coder_worktree/CODER_TASK_PACKET.json`
  - `runs/<project_id>/latest_coder_worktree/WORKTREE_STATUS.json`
  - `runs/<project_id>/latest_validation/VALIDATION_REPORT.json`
  - `runs/<project_id>/latest_validation/VALIDATION_REPORT.md`
- It writes central artifacts under `runs/<project_id>/morning_report_<timestamp>/`.
- Generated artifacts include:
  - `MORNING_REPORT.md`
  - `MORNING_REPORT.json`
  - `PLAN_UPDATE_PROPOSAL.json`
  - `NEXT_OBJECTIVE_RECOMMENDATION.md`
- It creates or updates `runs/<project_id>/latest_morning_report`.
- `MORNING_REPORT.md` includes:
  - objective
  - why selected
  - artifacts reviewed
  - validation result
  - safety status
  - worktree status
  - files changed, if any
  - recommendation: accept / revise / discard / hold
  - proposed weekly plan changes
  - next suggested objective
- `PLAN_UPDATE_PROPOSAL.json` proposes project-state changes but does not apply them by default.
- It supports optional `--apply-project-state`.
- With `--apply-project-state`, only these target project files may be edited:
  - `.agent_manager/WEEKLY_PLAN.json`
  - `.agent_manager/OBJECTIVE_BACKLOG.json`
  - `.agent_manager/VALIDATION_HISTORY.jsonl`
  - `.agent_manager/PLAN_REVISIONS.md`
- `--apply-project-state` is not run during Phase 11 implementation unless explicitly requested.
- No OpenHands run occurs.
- No model calls occur.
- No LangGraph runtime occurs.
- No target project source behavior is modified.
- No auto-merge or auto-push occurs.
- `runs/`, `worktrees/`, and `tmp/` remain ignored.
