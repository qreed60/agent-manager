# Phase 18J Gate: Manual OpenHands Gate Runner

Phase 18J adds one deterministic command for the manual OpenHands gate. It chains
the existing manual OpenHands phases and writes one summary artifact in the
OpenHands coder run directory.

It does not apply patches, commit, push, merge, create PRs, delete worktrees, or
enable OpenHands in any overnight or deterministic nightly path.

## Chain

The runner executes these existing pieces in order:

1. Phase 18F: `scripts/run_openhands_coder_task.py`
   - runs a manual non-smoke task with explicit `--allowed-file` scope
   - live execution still requires `--allow-openhands` and the existing
     `AGENT_MANAGER_ENABLE_OPENHANDS=1` environment gate
2. Phase 18G: `scripts/prepare_openhands_decision_packet.py`
   - reads the OpenHands coder run and writes the decision packet and patch
3. Phase 18I: `scripts/apply_openhands_decision_packet.py`
   - runs check-only apply validation against the canonical repo
   - Phase 18J never passes `--apply` or `--allow-canonical-write`

## Dry Run

Dry run is the default when `--allow-openhands` is omitted.

```bash
unset AGENT_MANAGER_ENABLE_OPENHANDS
python3 scripts/run_openhands_manual_gate.py thomsonlint \
  --task-text "Create docs/OPENHANDS_MANUAL_GATE_TEST.md relative to the current working directory only. Write one sentence. Do not create or modify any other files." \
  --allowed-file docs/OPENHANDS_MANUAL_GATE_TEST.md \
  --timeout-seconds 300 \
  --max-prompt-chars 3000 \
  --env-file ~/.config/agent-manager/env.local
```

The dry-run summary has `status: warn`, `dry_run: true`, `applied: false`, and
`openhands_execution_performed: false` when the canonical repo remains clean.

## Live Manual Command

Live execution remains manual and opt-in. Both the CLI flag and the environment
gate are required by the underlying Phase 18F runner.

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

## Summary Artifacts

The runner writes these files into the OpenHands coder run directory:

- `OPENHANDS_MANUAL_GATE_SUMMARY.json`
- `OPENHANDS_MANUAL_GATE_SUMMARY.md`

The JSON summary records the project, run directory, dry-run/live state, coder
status, decision recommendation, apply-check mode, apply result, canonical repo
cleanliness, changed files, allowed files, and the invariant
`no_apply_commit_push_merge_pr_or_cleanup_performed: true`.

## Pass Criteria

`status: pass` is only allowed for a live run when all of these are true:

- OpenHands execution was performed.
- `OPENHANDS_CODER_SUMMARY.json` has `status: pass`.
- `OPENHANDS_DECISION_PACKET.json` recommends `accept_for_manual_review`.
- `OPENHANDS_APPLY_STATUS.json` has `status: pass`.
- Apply mode is `check_only`.
- `applied` is `false`.
- The canonical repo remains clean.

Dry-run summaries are accepted as `status: warn` only when no canonical repo
changes occurred.

## Not Overnight OpenHands

Phase 18J is a manual gate runner, not nightly automation. It is not called from
`scripts/run_nightly_window.py`, does not enable model calls in deterministic
nightly execution, and does not relax the existing OpenHands environment gate.

## Safety Boundary

Phase 18J has no flags for canonical apply. It never passes `--apply` or
`--allow-canonical-write`, never commits, never pushes, never merges, never
creates PRs, and never deletes worktrees. Cleanup and patch application remain
separate human-reviewed actions.
