# Phase 18E Gate: Fresh OpenHands Worktree per Live Run + Scope Guard

## Why Fresh Worktrees Are Required

Phase 18D smoke test passed but revealed a critical issue: the smoke run reused an older detached worktree at `/home/qreed/agent-manager/worktrees/thomsonlint/coder_worktree_20260605T181506Z` instead of creating a fresh one. This means OpenHands could potentially see stale state from previous runs, leading to:

- **Non-reproducible results**: Changes from prior runs pollute the working directory
- **Scope guard bypass**: Untracked files from earlier runs appear as "new" changes
- **Cross-contamination**: Multiple concurrent or sequential runs interfere with each other

Every live OpenHands run must now create a fresh isolated worktree under:
```
worktrees/<project_id>/openhands_coder_<timestamp>/
```

with a deterministic branch name like `agent-manager/<project_id>/openhands-coder-<timestamp>`.

## Scope Guard Behavior

The scope guard (`OPENHANDS_SCOPE_STATUS.json`) validates that OpenHands only changed allowed files:

### Smoke Task
For `--smoke-task`, the **only** allowed changed file is:
```
.agent_manager_scratch/OPENHANDS_SMOKE_TEST.md
```

If any other file appears in the changed-files list, scope status is **fail**.

### Non-Smoke Tasks
- Allowed files come from the active objective / task packet `allowed_files` field.
- If no `allowed_files` are available for a write-capable non-smoke task: scope status = **warn** (non-blocking).
- Scope status = **fail** if any changed file is outside the allowed list.
- Scope status = **fail** if canonical repo is dirty.

### Protected Paths
Scope guard must fail if changes appear under:
- `.git/` (unless explicitly allowed)
- Generated exports
- Project control files (unless explicitly allowed)

## Changed-File Detection Including Untracked Files

Phase 18E adds detection of **untracked** files, not just staged/tracked diffs. The runner uses three git commands:

```bash
git -C <worktree> status --short --untracked-files=all
git -C <worktree> diff --name-only
git -C <worktree> diff --cached --name-only
```

`OPENHANDS_CHANGED_FILES.json` includes:
- `tracked_modified_files`: Modified tracked files
- `staged_files`: Files staged for commit
- `untracked_files`: New untracked files (NEW in Phase 18E)
- `all_changed_files`: Union of all above
- `worktree_changed`: Boolean indicating any changes exist

## Dry-Run Command

Dry runs do **not** create a fresh worktree. They only generate artifacts:

```bash
unset AGENT_MANAGER_ENABLE_OPENHANDS
python3 scripts/run_openhands_coder_task.py thomsonlint
```

Output: `OpenHands coder scaffold status: warn` (dry-run mode).

## Live Smoke Command

To run the live smoke test with a fresh worktree:

```bash
AGENT_MANAGER_ENABLE_OPENHANDS=1 python3 scripts/run_openhands_coder_task.py thomsonlint --smoke-task --allow-openhands
```

This will:
1. Create a fresh git worktree under `worktrees/thomsonlint/openhands_coder_<timestamp>/`
2. Run OpenHands with its working directory set to the fresh worktree
3. Write `.agent_manager_scratch/OPENHANDS_SMOKE_TEST.md` inside the fresh worktree (not canonical repo)
4. Generate all Phase 18E artifacts including `OPENHANDS_WORKTREE_INFO.json`, `OPENHANDS_CHANGED_FILES.json`, and `OPENHANDS_SCOPE_STATUS.json`

## Pass Criteria

### Smoke Status Pass Requires All:
- OpenHands executed (`execution_performed == true`)
- `returncode == 0`
- `timed_out == false`
- Expected file exists in the fresh OpenHands worktree
- `misplaced_file_paths` is empty
- Canonical repo clean (no changes to thomsonlint source)
- Scope status pass

### Summary Status:
- **pass**: exit status pass + smoke status pass (if smoke task) + scope status pass + canonical repo clean
- **warn**: smoke/scope status is warn
- **fail**: scope status fails OR canonical repo is dirty

## Why This Is Still Not Phase 19

Phase 18E solves isolation and scope detection but does not address:

1. **No auto-commit/push/merge/PR**: The runner still does not commit, push, merge, or open PRs on behalf of OpenHands
2. **No model call gating for live runs**: Live execution requires `--allow-openhands` flag; no automatic model invocation
3. **No review agents integration**: Phase 18E artifacts are not consumed by the review agent pipeline
4. **No nightly window integration**: OpenHands is not enabled in the nightly window (Phase 16)
5. **No auto-cleanup of stale worktrees**: Old worktrees accumulate without automated pruning
6. **No scope enforcement at git level**: Scope guard is a post-hoc check, not a pre-commit hook

Phase 19 will address these gaps by adding safe commit workflows, review integration, and automated lifecycle management for isolated worktrees.
