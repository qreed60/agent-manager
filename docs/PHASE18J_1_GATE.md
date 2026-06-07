# Phase 18J.1 Gate: Manual OpenHands Prompt Hardening

Phase 18J.1 hardens the Phase 18J manual gate after the first live run failed
safely: OpenHands exited 0, changed no worktree files, and wrote near the prompt
artifact in the run directory instead of the isolated worktree. The fix keeps
the same manual gate surface and adds stronger prompt instructions plus
machine-readable failure classifications.

It does not add a new automation phase and does not enable OpenHands in nightly.

## Prompt Wrapper

`scripts/run_openhands_manual_gate.py` now wraps every manual task before passing
it to `scripts/run_openhands_coder_task.py`. The wrapper tells OpenHands to:

- use the terminal for file creation/modification
- treat the current shell working directory as the isolated project worktree
- create or modify files relative to the current working directory only
- avoid writing beside `OPENHANDS_TASK_PROMPT.md`
- avoid writing into the run directory
- avoid absolute paths under `runs/<project_id>/openhands_coder_*`
- stay inside the allowed file list
- create parent directories only when needed for allowed files
- avoid broad repository inspection
- avoid running tests unless explicitly requested
- avoid commits and pushes
- finish immediately after the requested file change

The wrapper includes the allowed file list, the original user task text or
task-file contents, and a final instruction to verify that the allowed file
exists or was modified in the current working directory before finishing.

The original task text is preserved in `OPENHANDS_MANUAL_GATE_SUMMARY.json` for
auditability.

## Failure Classifications

`OPENHANDS_MANUAL_GATE_SUMMARY.json` includes:

- `failure_classification`
- `retryable`
- `diagnostic_details`
- `misplaced_run_dir_paths`

Allowed classifications:

- `none`
- `exited_0_no_changes`
- `misplaced_run_dir_write`
- `scope_fail`
- `apply_check_fail`
- `decision_not_accepted`
- `coder_failed`
- `canonical_repo_dirty`
- `applied_unexpectedly`
- `missing_required_artifact`
- `unknown`

Retryable classifications are `exited_0_no_changes`,
`misplaced_run_dir_write`, and `apply_check_fail`. Non-retryable classifications
include `canonical_repo_dirty`, `applied_unexpectedly`, and `scope_fail`.

## Misplaced Run-Dir Detection

The manual gate scans the OpenHands run directory for:

- each allowed file path exactly under the run directory
- each allowed file basename anywhere under the run directory

Matches are recorded in `misplaced_run_dir_paths`. This makes the common prompt
misinterpretation visible without applying or cleaning anything automatically.

## Live Pass Command

Live execution remains manual and opt-in. Both `--allow-openhands` and
`AGENT_MANAGER_ENABLE_OPENHANDS=1` are required by the underlying Phase 18F
runner.

```bash
AGENT_MANAGER_ENABLE_OPENHANDS=1 \
python3 scripts/run_openhands_manual_gate.py thomsonlint \
  --task-text "Create docs/OPENHANDS_MANUAL_GATE_TEST.md relative to the current working directory only. Write one sentence. Do not create or modify any other files." \
  --allowed-file docs/OPENHANDS_MANUAL_GATE_TEST.md \
  --allow-openhands \
  --timeout-seconds 300 \
  --max-prompt-chars 3000 \
  --env-file ~/.config/agent-manager/env.local
```

## Pass Criteria

`status: pass` is only allowed when:

- OpenHands executed
- the coder summary status is `pass`
- the decision recommendation is `accept_for_manual_review`
- the apply status is `pass`
- apply mode is `check_only`
- `applied` is `false`
- the canonical repo remains clean
- `failure_classification` is `none`
- `retryable` is `false`

Dry-run summaries remain accepted as `status: warn`.

## Safety Boundary

Phase 18J.1 is still not overnight OpenHands. It is not called from
`scripts/run_nightly_window.py`, does not enable model calls in deterministic
nightly execution, and does not relax the existing OpenHands environment gate.

It never applies patches, commits, pushes, merges, creates PRs, or deletes
worktrees. Cleanup and patch application remain separate human-reviewed actions.
