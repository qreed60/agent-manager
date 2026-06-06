# Phase 16.5 Systemd Nightly Launcher Gate

Phase 16.5 adds operational scheduling for the deterministic nightly window. It does not change nightly execution semantics: no AI model calls, no OpenHands execution, no target source writes, no auto-merge, no auto-push, and `max_code_writing_tasks` remains `0`.

## Added Files

- `systemd/agent-manager-nightly@.service`
- `systemd/agent-manager-nightly@.timer`
- `scripts/install_nightly_timer.sh`
- `scripts/check_nightly_timer.sh`
- `docs/NIGHTLY_OPERATION.md`

## Install

```bash
scripts/install_nightly_timer.sh thomsonlint
```

The script installs units under the user unit directory:

```text
~/.config/systemd/user/
```

It runs:

```bash
systemctl --user daemon-reload
systemctl --user enable agent-manager-nightly@<project_id>.timer
```

It does not start an immediate nightly run unless `--run-now` is explicitly passed.

## Timer

The timer runs daily at 23:00:

```ini
OnCalendar=*-*-* 23:00:00
Persistent=true
```

`RandomizedDelaySec` is not set by default. `Persistent=true` lets user systemd catch up a missed 23:00 run after login.

## Service

The template service accepts project id as `%i` and runs:

```text
/home/qreed/agent-manager/.venv/bin/python /home/qreed/agent-manager/scripts/run_nightly_window.py %i
```

It uses:

- `WorkingDirectory=/home/qreed/agent-manager`
- `Environment=PATH=/home/qreed/agent-manager/.venv/bin:/usr/local/bin:/usr/bin:/bin`
- `AGENT_MANAGER_NO_MODEL_CALLS=1`
- `AGENT_MANAGER_NO_OPENHANDS=1`
- `AGENT_MANAGER_MAX_CODE_WRITING_TASKS=0`
- `Restart=no`

The template is installed as a `systemd --user` unit, so it does not declare
`User=` or `Group=`.

Logs are available through user journal:

```bash
journalctl --user -u agent-manager-nightly@<project_id>.service -n 100 --no-pager
```

## Validation

Run:

```bash
python3 -m py_compile scripts/run_nightly_window.py
bash -n scripts/install_nightly_timer.sh
bash -n scripts/check_nightly_timer.sh
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/run_nightly_window.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```

`scripts/validate_agent_run.py` validates the systemd unit files and scripts syntactically through repository file content. It does not require systemd to be running.
