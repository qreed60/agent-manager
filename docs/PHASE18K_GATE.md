# Phase 18K Gate: Manager-to-OpenHands Manual Request Bridge

Phase 18K is an artifact bridge from manager intent to a human-reviewed
OpenHands manual gate command. It does not run OpenHands.

The flow is:

1. A manager or human supplies a bounded manual task request.
2. `scripts/prepare_openhands_manual_gate_request.py` validates the request.
3. The script writes request and command artifacts.
4. A human reviews and manually runs the generated command.
5. Normal Phase 18J/18J.1 validation handles the manual gate result.

This is not Phase 19. Phase 18K does not add autonomous write execution,
overnight OpenHands, model calls, PR creation, patch application, or cleanup.

## Generated Artifacts

The script writes a timestamped directory:

`runs/<project_id>/openhands_manual_gate_request_<timestamp>/`

It also updates:

`runs/<project_id>/latest_openhands_manual_gate_request`

Artifacts:

- `OPENHANDS_MANUAL_GATE_REQUEST.json`
- `OPENHANDS_MANUAL_GATE_REQUEST.md`
- `OPENHANDS_MANUAL_GATE_COMMAND.sh`
- `OPENHANDS_MANUAL_GATE_COMMAND.md`

## Request Schema

The JSON request records:

- project and objective metadata
- task source, task text, task file, and task hash
- allowed files
- expected changed files
- validation commands
- stop conditions
- risk level
- generated command artifact paths
- request status and refusal reason
- `no_openhands_execution_performed: true`
- `no_apply_commit_push_merge_pr_or_cleanup_performed: true`

`--expected-changed-file` defaults to the allowed file list when omitted.

## Prepare Command

Example request generation:

```bash
python3 scripts/prepare_openhands_manual_gate_request.py thomsonlint \
  --task-text "Create docs/OPENHANDS_PHASE18K_REQUEST_TEST.md relative to the current working directory only. Write one sentence. Do not create or modify any other files." \
  --allowed-file docs/OPENHANDS_PHASE18K_REQUEST_TEST.md \
  --validation-command "python3 scripts/validate_agent_run.py thomsonlint" \
  --risk-level low \
  --stop-condition "Stop after creating the allowed file."
```

## Dry-Run Command

The generated command markdown includes a dry-run command:

```bash
python3 scripts/run_openhands_manual_gate.py thomsonlint \
  --task-text "<validated task text>" \
  --allowed-file docs/OPENHANDS_PHASE18K_REQUEST_TEST.md
```

Dry run does not enable OpenHands.

## Live Manual Command

The generated command markdown also includes a live manual variant. It requires
the human to explicitly set `AGENT_MANAGER_ENABLE_OPENHANDS=1` and pass
`--allow-openhands`.

The request script never sets that environment variable and never calls the
manual gate runner.

## Validation Commands

The generated markdown includes post-run validation commands supplied with
`--validation-command`. If no validation commands are supplied, the request is a
`warn` rather than a `fail`.

## Pass Criteria

The request is `pass` only when:

- exactly one task source is supplied
- at least one allowed file is supplied
- allowed files are relative and contain no `..`
- expected changed files are within the allowed file list
- high-risk requests include at least one stop condition
- task text is non-empty
- command artifacts contain no apply/commit/push/merge/PR/cleanup commands

Low- and medium-risk requests without validation commands or stop conditions may
produce `warn` artifacts for human review.

## Safety Boundary

Phase 18K is standalone for this phase. LangGraph integration remains manual:
the generated artifacts can be reviewed by a human, but LangGraph does not run
OpenHands and `scripts/run_nightly_window.py` is not changed to run OpenHands.

The bridge never applies patches, commits, pushes, merges, creates PRs, or
deletes worktrees.
