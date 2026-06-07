# Phase 20 Gate: First Overnight Write-Capable OpenHands Run

Phase 20 is the first real overnight write-capable run. It allows exactly one
bounded OpenHands task, sourced from a validated Phase 18K request, with at most
one retry.

This phase does not apply patches, commit, push, merge, create PRs, delete
worktrees, or modify the canonical repo.

## Gates

`scripts/run_overnight_openhands_write_task.py` requires all of these:

- `--allow-overnight-openhands`
- `--confirm-project <PROJECT_ID>` matching the project
- `AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS=1`
- `AGENT_MANAGER_ENABLE_OPENHANDS=1`
- `AGENT_MANAGER_OVERNIGHT_OPENHANDS_CONFIRM_PROJECT=<PROJECT_ID>`
- `--request-dir` or `AGENT_MANAGER_OVERNIGHT_OPENHANDS_REQUEST_DIR`
- a Phase 18K request with `risk_level: low`
- a clean canonical repo before execution
- safe relative allowed files with no `..`

The request must not already contain
`OVERNIGHT_OPENHANDS_REQUEST_CONSUMED.json`.

## One-Task Limit

Phase 20 runs no more than one write-capable OpenHands task in a nightly window.
It does not select a second request or continue to another write task after a
pass, block, or failure.

## One-Retry Limit

The runner performs at most two attempts total:

- attempt 1
- one retry only if the Phase 18J.1 manual gate summary says `retryable: true`

Non-retryable failures block immediately. A retry failure also blocks.

## Request Consumption

After the first live attempt begins, the runner writes:

`OVERNIGHT_OPENHANDS_REQUEST_CONSUMED.json`

into the request directory. The file records the request hash, consumed time,
project id, nightly run dir, and consumed status. Future runs refuse the same
request.

## Staging a One-Night Run

Prepare a Phase 18K request first:

```bash
python3 scripts/prepare_openhands_manual_gate_request.py thomsonlint \
  --task-text "Create docs/OPENHANDS_PHASE20_TEST.md relative to the current working directory only. Write one sentence. Do not create or modify any other files." \
  --allowed-file docs/OPENHANDS_PHASE20_TEST.md \
  --validation-command "python3 scripts/validate_agent_run.py thomsonlint" \
  --risk-level low \
  --stop-condition "Stop after creating the allowed file."
```

Then run one gated nightly:

```bash
export AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS=1
export AGENT_MANAGER_ENABLE_OPENHANDS=1
export AGENT_MANAGER_OVERNIGHT_OPENHANDS_CONFIRM_PROJECT=thomsonlint
export AGENT_MANAGER_OVERNIGHT_OPENHANDS_REQUEST_DIR="$(pwd)/runs/thomsonlint/latest_openhands_manual_gate_request"
python3 scripts/run_nightly_window.py thomsonlint
```

## Morning Report

Check:

`runs/<project_id>/latest_nightly_window/OVERNIGHT_OPENHANDS_MORNING_REPORT.md`

It includes the selected objective, OpenHands run dir, changed files, decision
recommendation, apply-check result, validation result, review findings,
recommended human action, canonical repo clean status, and the no
apply/commit/push/merge/PR/cleanup reminder.

## Pass Criteria

The overnight write summary passes only when:

- exactly one write task was attempted
- no more than one retry occurred
- the selected manual gate attempt passed
- the decision recommendation is `accept_for_manual_review`
- apply mode is `check_only`
- apply check passed
- changed files are nonempty and within allowed files
- every attempt has `applied: false`
- canonical repo remains clean

Blocked summaries must include a blocked reason and recommended human action.

## Disable After the Run

After the one-night run, remove the gates:

```bash
unset AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS
unset AGENT_MANAGER_ENABLE_OPENHANDS
unset AGENT_MANAGER_OVERNIGHT_OPENHANDS_CONFIRM_PROJECT
unset AGENT_MANAGER_OVERNIGHT_OPENHANDS_REQUEST_DIR
```

Default nightly behavior remains non-write-capable when these gates are absent.
