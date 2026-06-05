# Phase 16 Time-boxed LangGraph Loop Gate

Phase 16 adds a deterministic top-level nightly window launcher around the existing LangGraph v0 chain. It is control-plane only: no AI model calls, no OpenHands execution, no target source writes, no auto-merge, and no auto-push.

## Run

```bash
python3 scripts/run_nightly_window.py thomsonlint
```

The script accepts any registered `project_id`; `thomsonlint` is only the first configured project.

## Policy Defaults

The defaults are stored in `configs/nightly_window_policy.json`:

- `nightly_start`: `23:00`
- `no_new_work_cutoff`: `05:30`
- `hard_stop`: `06:00`
- `max_manager_passes`: `3`
- `max_code_writing_tasks`: `0`
- `future_max_code_writing_tasks`: `1`
- `max_retries_per_task`: `1`

Phase 16 requires `max_code_writing_tasks` to remain `0`. The future `1` limit is metadata only for a later coder execution phase.

## Execution Mode

Default mode is quick deterministic mode. It does not wait until 11 PM and runs promptly for testability:

```bash
python3 scripts/run_nightly_window.py <project_id>
```

The launcher invokes:

```bash
python3 scripts/run_langgraph_v0.py <project_id>
```

The launcher is not a LangGraph node, so it does not create recursion. It wraps one or more bounded LangGraph passes and writes a morning handoff even in quick mode.

## Outputs

Each run writes:

```text
runs/<project_id>/nightly_window_<timestamp>/
```

Required artifacts:

- `NIGHTLY_WINDOW_MANIFEST.json`
- `NIGHTLY_WINDOW_TIMELINE.json`
- `NIGHTLY_PASS_SUMMARY.json`
- `MORNING_HANDOFF.md`
- `NIGHTLY_SAFETY_STATUS.json`

The latest pointer is:

```text
runs/<project_id>/latest_nightly_window
```

## Manifest Contract

`NIGHTLY_WINDOW_MANIFEST.json` includes:

- `project_id`
- `created_utc`
- `selected_objective_id`
- `policy`
- `pass_count`
- `max_manager_passes`
- `max_code_writing_tasks`
- `model_calls_allowed: false`
- `openhands_allowed: false`
- `source_writes_allowed: false`
- `status`

## Timeline Contract

`NIGHTLY_WINDOW_TIMELINE.json` includes a `passes` list. Each pass includes:

- `pass_index`
- `started_utc`
- `completed_utc`
- `decision`
- `artifacts`
- `status`

## Morning Handoff

`MORNING_HANDOFF.md` includes:

- objective
- window policy
- pass summary
- validation status
- review summary
- model routing summary
- safety status
- recommendation
- next action

## Validation

Run:

```bash
python3 -m py_compile scripts/run_nightly_window.py
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/run_nightly_window.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```

When `latest_nightly_window` is present, `scripts/validate_agent_run.py` validates all Phase 16 artifacts and checks the control-plane safety flags.
