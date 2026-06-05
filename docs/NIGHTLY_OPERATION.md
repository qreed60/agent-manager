# Nightly Operation

The Agent Manager nightly launcher is a user-level systemd timer around `scripts/run_nightly_window.py`.

## Install Timer

```bash
scripts/install_nightly_timer.sh <project_id>
```

Example:

```bash
scripts/install_nightly_timer.sh thomsonlint
```

The install script copies unit templates to `~/.config/systemd/user/`, reloads the user daemon, and enables `agent-manager-nightly@<project_id>.timer`.

It does not start an immediate full nightly run by default.

## Run Once Explicitly

```bash
scripts/install_nightly_timer.sh --run-now <project_id>
```

## Check Timer

```bash
scripts/check_nightly_timer.sh <project_id>
```

The check script shows timer status, matching user timers, and recent service logs.

Manual equivalents:

```bash
systemctl --user status agent-manager-nightly@<project_id>.timer
systemctl --user list-timers 'agent-manager-nightly@*.timer'
journalctl --user -u agent-manager-nightly@<project_id>.service -n 100 --no-pager
```

## Safety Contract

The service sets:

```text
AGENT_MANAGER_NO_MODEL_CALLS=1
AGENT_MANAGER_NO_OPENHANDS=1
AGENT_MANAGER_MAX_CODE_WRITING_TASKS=0
```

The nightly window remains deterministic/control-plane only:

- no AI model calls
- no OpenHands execution
- no target source writes
- no auto-merge
- no auto-push
- `max_code_writing_tasks` remains `0`

## Disable Timer

```bash
systemctl --user disable --now agent-manager-nightly@<project_id>.timer
```

## Inspect Unit Files

Installed user unit files live under:

```text
~/.config/systemd/user/
```

Source templates live under:

```text
systemd/
```
