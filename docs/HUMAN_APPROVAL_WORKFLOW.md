# Human Approval Workflow

The human approval packet is the boundary between deterministic nightly control-plane work and any future write-capable or externally visible action.

## Generate Packet

```bash
python3 scripts/prepare_human_approval_packet.py <project_id>
```

Example:

```bash
python3 scripts/prepare_human_approval_packet.py thomsonlint
```

The latest packet is available at:

```text
runs/<project_id>/latest_human_approval
```

## Review Artifacts

Read:

- `APPROVAL_PACKET.md`
- `APPROVAL_SUMMARY.md`
- `DRAFT_PR_PLAN.md`
- `PR_BODY_DRAFT.md`
- `RESUME_INSTRUCTIONS.md`
- `HUMAN_DECISION_TEMPLATE.json`

The packet summarizes validation, review-agent, model-routing, nightly-window, changed-file, and safety status.

## Draft PR Text

`DRAFT_PR_PLAN.md` includes a text-only `gh pr create --draft ...` command. The agent-manager does not execute it.

Manual PR creation remains a human action after approval and after any required branch push is explicitly performed by a human.

## Human Decision

Fill out `HUMAN_DECISION_TEMPLATE.json`:

```json
{
  "decision": "accept",
  "reviewer": "name",
  "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
  "notes": "review notes",
  "approved_for_next_phase": true,
  "approved_for_source_writes": false,
  "approved_for_model_calls": false,
  "approved_for_openhands": false
}
```

Allowed `decision` values:

- `accept`
- `revise`
- `discard`
- `hold`

The default template denies source writes, model calls, and OpenHands.

## Resume

Use `RESUME_INSTRUCTIONS.md` in the packet directory. Common commands:

```bash
python3 scripts/validate_agent_run.py <project_id>
python3 scripts/run_nightly_window.py <project_id>
scripts/check_nightly_timer.sh <project_id>
```

Proceed to the next phase only when the human decision is `accept` and `approved_for_next_phase` is true.

## Safety Contract

Phase 17 does not:

- call AI models
- run OpenHands
- modify target project source
- create a GitHub PR
- push a branch
- merge changes

Human approval remains required before any future write-capable work is accepted.
