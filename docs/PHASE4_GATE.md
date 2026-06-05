# Phase 4 Gate

Phase 4 is complete when:

- `scripts/sync_openhands_prompt_sources.py` works.
- `scripts/apply_openhands_profile.py --profile coder` dry-runs without modifying real OpenHands settings.
- `scripts/phase4_smoke.sh` passes using `/tmp`.
- Coder profile uses the prompt source from the OpenHands prompt project.
- The profile switcher creates backups when `--apply` is used.
- No real OpenHands run is started.
- No model calls are made.
- No target project source files are modified.

Important:
- Applying a profile only changes OpenHands configuration files.
- It does not launch OpenHands.
- It does not run an agent.
- It does not modify target repos.
