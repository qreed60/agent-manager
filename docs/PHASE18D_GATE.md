# Phase 18D Gate: OpenHands Smoke Task Override

Phase 18D adds a tiny prompt override for controlled OpenHands live testing. It is
intended to prove that OpenHands can start headless, write one harmless file in
the isolated coder worktree, and exit cleanly without touching the canonical
project checkout.

## Safety Model

- Default `scripts/run_openhands_coder_task.py <project_id>` behavior remains a
  dry-run task packet only.
- Live OpenHands execution still requires both `--allow-openhands` and
  `AGENT_MANAGER_ENABLE_OPENHANDS=1`.
- Writes remain limited to the isolated worktree under `worktrees/<project_id>/`.
- Canonical repo writes, auto-commit, auto-push, auto-merge, and PR creation stay
  disabled.
- Systemd nightly behavior and deterministic nightly model-call policy are not
  changed.
- The smoke task does not print or require secrets.

## Dry Run

```bash
python3 scripts/run_openhands_coder_task.py thomsonlint --smoke-task
```

This writes the smoke prompt and artifacts under
`runs/thomsonlint/openhands_coder_<timestamp>/` without launching OpenHands.

## Live Smoke

```bash
AGENT_MANAGER_ENABLE_OPENHANDS=1 python3 scripts/run_openhands_coder_task.py thomsonlint --smoke-task --allow-openhands
```

The prompt asks OpenHands to create only:

```text
.agent_manager_scratch/OPENHANDS_SMOKE_TEST.md
```

and then finish immediately.

## Pass Criteria

`OPENHANDS_SMOKE_STATUS.json` reports `pass` only when:

- OpenHands executed.
- The return code is `0`.
- The run did not time out.
- `.agent_manager_scratch/OPENHANDS_SMOKE_TEST.md` exists in the isolated
  worktree.
- The canonical project repo is clean.

Validation accepts smoke `pass` and `warn` states for general review, but fails
if the smoke artifact reports that the canonical repo is not clean.

## Not Phase 19

This is not Phase 19 because it does not authorize overnight OpenHands work,
does not change `run_nightly_window.py`, does not alter systemd units or timers,
and does not enable model calls in deterministic nightly runs. It is a bounded
manual smoke probe for the Phase 18B execution path.
