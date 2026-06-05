# Phase 9 Gate

Phase 9 is complete when:

- `scripts/prepare_coder_worktree.py` exists.
- It creates a detached isolated worktree under `worktrees/<project_id>/`.
- It writes central coder scaffold artifacts under `runs/<project_id>/coder_worktree_<timestamp>/`.
- It creates or updates `runs/<project_id>/latest_coder_worktree`.
- Generated artifacts include:
  - `CODER_TASK_PACKET.json`
  - `WORKTREE_STATUS.json`
  - `CODER_PROMPT.md`
  - `OPENHANDS_DRY_RUN_COMMANDS.md`
- Generated JSON parses.
- Original target repo remains clean.
- New worktree is clean.
- No OpenHands run occurs.
- No model calls occur.
- No LangGraph runtime occurs.
- No auto-merge or auto-push occurs.
