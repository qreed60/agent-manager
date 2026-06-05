# Phase 10 Gate

Phase 10 is complete when:

- `scripts/validate_agent_run.py` exists.
- It accepts a project id argument, for example:

```bash
python3 scripts/validate_agent_run.py thomsonlint
```

- It reads `configs/projects.json`.
- It validates the configured target repository exists.
- It validates the configured target repository is a git work tree.
- It validates the configured target repository is clean.
- It validates project-local `.agent_manager/WEEKLY_PLAN.json` parses.
- It validates project-local `.agent_manager/OBJECTIVE_BACKLOG.json` parses.
- It validates latest metrics artifacts from `runs/<project_id>/latest` parse:
  - `RUN_METRICS.json`
  - `UNKNOWN_ANALYSIS.json`
  - `VALIDATION_SUMMARY.json`
- It requires latest metrics `VALIDATION_SUMMARY.json` status to be `pass`.
- It validates latest runner artifacts from `runs/<project_id>/latest_runner_v0` parse or are readable:
  - `ACTIVE_OBJECTIVE.json`
  - `TASK_GRAPH.json`
  - `RUN_MANIFEST.json`
  - `MORNING_REPORT.md`
- It requires latest runner `RUN_MANIFEST.json` status to be `pass`.
- It validates latest manager artifacts from `runs/<project_id>/latest_manager_plan` parse or are readable:
  - `MANAGER_CONTEXT.json`
  - `MANAGER_DECISION.json`
  - `MANAGER_PLAN.md`
  - `NEXT_ACTION.md`
- It requires latest manager `MANAGER_DECISION.json` status to be `pass`.
- It validates latest coder worktree artifacts from `runs/<project_id>/latest_coder_worktree` parse or are readable:
  - `CODER_TASK_PACKET.json`
  - `WORKTREE_STATUS.json`
  - `CODER_PROMPT.md`
  - `OPENHANDS_DRY_RUN_COMMANDS.md`
- It requires latest coder `WORKTREE_STATUS.json` field `clean` to be `true`.
- It writes:
  - `runs/<project_id>/validation_<timestamp>/VALIDATION_REPORT.json`
  - `runs/<project_id>/validation_<timestamp>/VALIDATION_REPORT.md`
- It creates or updates `runs/<project_id>/latest_validation`.
- Failure output includes clear check ids and messages.
- The validator exits non-zero when any required check fails.
- No OpenHands run occurs.
- No model calls occur.
- No LangGraph runtime occurs.
- No target project source modifications occur.
- No auto-merge or auto-push occurs.
