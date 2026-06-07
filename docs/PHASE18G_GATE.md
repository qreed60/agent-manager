# Phase 18G Gate: OpenHands Decision Packet

Phase 18G adds a deterministic human decision packet for OpenHands runs. The
packet turns a smoke or manual write run into reviewable artifacts without
applying changes to the canonical repo.

## Purpose

OpenHands can now write inside a fresh isolated worktree, but real code tasks
still require a human gate. Phase 18G summarizes the run, changed files, scope
status, patch, validation posture, recommended action, review commands, and
manual cleanup commands.

## Generated Artifacts

Run:

```bash
python3 scripts/prepare_openhands_decision_packet.py thomsonlint
```

By default, the script reads `runs/<project_id>/latest_openhands_coder` and
writes:

- `OPENHANDS_DECISION_PACKET.json`
- `OPENHANDS_DECISION_PACKET.md`
- `OPENHANDS_PATCH.diff`
- `OPENHANDS_REVIEW_COMMANDS.md`
- `OPENHANDS_CLEANUP_PLAN.md`

`--run-dir` can select a specific OpenHands run. `--output-dir` can write the
packet somewhere else for review without changing the source run directory.

## Recommendation Meanings

- `accept_for_manual_review`: manual non-smoke task passed, scope passed, patch
  is nonempty, and the canonical repo is clean.
- `discard_worktree`: smoke passed or scope failed and the worktree should not
  be promoted.
- `hold_for_debug`: required artifacts are missing, OpenHands failed, or the run
  timed out.
- `rerun_openhands`: the run produced no worktree changes.
- `human_review_required`: the result needs manual inspection before any next
  action, especially if canonical repo cleanliness is not proven.

## Patch And Review Workflow

`OPENHANDS_PATCH.diff` is generated from the OpenHands worktree. It includes
tracked changes from `git diff --binary HEAD` and text content for untracked
files. The patch is recorded with a SHA256 hash in
`OPENHANDS_DECISION_PACKET.json`.

`OPENHANDS_REVIEW_COMMANDS.md` contains manual inspection commands for:

- the run directory
- the OpenHands worktree
- worktree status and diff
- scratch files when applicable
- the decision packet JSON
- the patch file
- an apply-check command

The manual apply sequence is explicitly labeled:

```text
Manual only. Do not run unless you intend to apply this patch.
```

## Cleanup Plan Workflow

`OPENHANDS_CLEANUP_PLAN.md` contains manual cleanup commands only:

- inspect worktree status
- remove the OpenHands worktree
- delete the OpenHands branch

Cleanup is not executed by Phase 18G. Removing the worktree discards
uncommitted worktree changes, so the cleanup commands are intentionally manual.

## Not Phase 19

Phase 18G does not enable OpenHands in `run_nightly_window.py`, does not enable
model calls in deterministic nightly, and does not auto-apply patches. It also
does not commit, push, merge, create PRs, or delete worktrees automatically.
Phase 19 can build on the decision packet once this human review gate is proven.
