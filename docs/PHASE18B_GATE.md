# Phase 18B Gate: Controlled OpenHands Coder Execution

Phase 18B adds the first scaffold that may run a code-writing OpenHands agent, but execution remains controlled and opt-in.

## Default Behavior

- `python3 scripts/run_openhands_coder_task.py thomsonlint` is dry-run only.
- Dry-run writes the same control artifacts and a bounded task prompt.
- OpenHands is not invoked unless both gates are present:
  - `--allow-openhands`
  - `AGENT_MANAGER_ENABLE_OPENHANDS=1`

## Safety Boundaries

- OpenHands may only run inside `worktrees/<project_id>/`.
- The canonical project repo must never be used as the execution worktree.
- The script records pre-run and post-run git status from the worktree.
- The script does not stage, commit, push, merge, or create a PR.
- Any worktree edits remain unstaged for human review.
- No OpenHands execution is added to the nightly timer or default nightly window.

## Required Artifacts

Artifacts are written under `runs/<project_id>/openhands_coder_<timestamp>/` and `runs/<project_id>/latest_openhands_coder` is updated.

- `OPENHANDS_CODER_RUN.json`
- `OPENHANDS_CODER_RUN.md`
- `OPENHANDS_TASK_PROMPT.md`
- `OPENHANDS_COMMAND.txt`
- `OPENHANDS_STDOUT.txt`
- `OPENHANDS_STDERR.txt`
- `OPENHANDS_EXIT_STATUS.json`
- `OPENHANDS_SAFETY_STATUS.json`
- `OPENHANDS_WORKTREE_STATUS_BEFORE.txt`
- `OPENHANDS_WORKTREE_STATUS_AFTER.txt`
- `OPENHANDS_DIFF_SUMMARY.txt`
- `OPENHANDS_CODER_SUMMARY.json`
- `OPENHANDS_CODER_SUMMARY.md`

## Validation

`scripts/validate_agent_run.py` validates `latest_openhands_coder` when present. Validation permits dry-run artifacts and fails if safety status allows canonical repo writes, auto-push, auto-merge, auto-commit, or PR creation.
