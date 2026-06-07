# Phase 18F Gate: Manual Non-Smoke OpenHands Write Task

Phase 18F adds a manual write-task path for controlled, non-smoke OpenHands
testing. It accepts an explicit task override and an explicit allowed-file list,
then runs OpenHands in a fresh isolated worktree when the existing live gates are
enabled.

## Purpose

The smoke task proves OpenHands can start and write one known file. Phase 18F is
the next manual gate: it lets an operator ask OpenHands to perform a tiny
non-smoke write while proving that changed-file detection and scope validation
work for ordinary task overrides.

## Safety Model

- Live execution still requires both `--allow-openhands` and
  `AGENT_MANAGER_ENABLE_OPENHANDS=1`.
- Every live run uses a fresh worktree under
  `worktrees/<project_id>/openhands_coder_<timestamp>/`.
- The canonical project checkout must remain clean.
- No commit, push, merge, or PR creation is performed.
- OpenHands is not part of `run_nightly_window.py`.
- Deterministic nightly model-call behavior is unchanged.

## Dry Run

```bash
python3 scripts/run_openhands_coder_task.py thomsonlint \
  --task-text "Create .agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md with one sentence." \
  --allowed-file .agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md
```

Without the live gates, this writes artifacts only.

## Live Manual Command

```bash
AGENT_MANAGER_ENABLE_OPENHANDS=1 python3 scripts/run_openhands_coder_task.py thomsonlint \
  --allow-openhands \
  --task-text "Create .agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md with one sentence." \
  --allowed-file .agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md
```

`--task-file <path>` may be used instead of `--task-text`. For live non-smoke
manual task overrides, at least one `--allowed-file` is required.

## Allowed-File Model

`--allowed-file` is repeatable. Scope passes only when every tracked, staged, or
untracked changed file is listed by `--allowed-file`. Extra files fail scope.

`--allowed-file` is not needed for `--smoke-task`. If used with smoke, it must
exactly match:

```text
.agent_manager_scratch/OPENHANDS_SMOKE_TEST.md
```

Default generated tasks still use `allowed_files` from the active objective or
task packet when available.

## Pass Criteria

For a live manual non-smoke task, summary status is `pass` only when:

- OpenHands executed and returned `0`.
- The run did not time out.
- The fresh worktree was created.
- Every changed file is listed in `manual_allowed_files`.
- At least one file changed.
- The canonical repo is clean.

Summary status is `warn` when a live manual write task changes no files. Summary
status is `fail` when scope fails or the canonical repo is dirty.

## Not Phase 19

Phase 18F is still a manual gate. It does not enable OpenHands in nightly, does
not add model calls to deterministic nightly, and does not automate commits,
pushes, merges, or PRs. Phase 19 can build on these artifacts once manual write
scope has been proven.
