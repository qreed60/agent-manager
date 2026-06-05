# Phase 17 Human Approval and Draft PR Support Gate

Phase 17 adds deterministic human approval packaging, draft PR text generation, and resume instructions. It remains control-plane only: no AI model calls, no OpenHands execution, no target source writes, no GitHub PR creation, no push, and no merge.

## Run

```bash
python3 scripts/prepare_human_approval_packet.py thomsonlint
```

The script accepts any registered `project_id`; `thomsonlint` is only the first configured project.

## Inputs

The script reads latest artifacts when present:

- `latest_nightly_window`
- `latest_langgraph_v0`
- `latest_validation`
- `latest_review_agents`
- `latest_model_routing`
- `latest_morning_report`
- `latest_runner_v0`
- `latest_manager_plan`

It also reads the registered project config and project-local planning state to identify the selected objective.

## Outputs

Each run writes:

```text
runs/<project_id>/human_approval_<timestamp>/
```

Required artifacts:

- `APPROVAL_PACKET.json`
- `APPROVAL_PACKET.md`
- `DRAFT_PR_PLAN.md`
- `PR_BODY_DRAFT.md`
- `RESUME_INSTRUCTIONS.md`
- `HUMAN_DECISION_TEMPLATE.json`
- `APPROVAL_SUMMARY.json`
- `APPROVAL_SUMMARY.md`

The latest pointer is:

```text
runs/<project_id>/latest_human_approval
```

## Draft PR Support

`DRAFT_PR_PLAN.md` contains a text-only command such as:

```bash
gh pr create --draft --title ... --body-file ...
```

The script does not require `gh`, does not execute `gh`, does not push a branch, and does not create a PR.

## Human Decision Template

`HUMAN_DECISION_TEMPLATE.json` includes:

- `decision`: `accept`, `revise`, `discard`, or `hold`
- `reviewer`
- `timestamp`
- `notes`
- `approved_for_next_phase`
- `approved_for_source_writes: false`
- `approved_for_model_calls: false`
- `approved_for_openhands: false`

Future phases may request additional approval, but Phase 17 does not enable source writes, model calls, or OpenHands.

## LangGraph Integration

`scripts/run_langgraph_v0.py` includes `prepare_human_approval_packet` as the final deterministic handoff node before `finalize`. This does not create recursion with `run_nightly_window.py`; the nightly window remains a top-level launcher around LangGraph v0.

## Validation

Run:

```bash
python3 -m py_compile scripts/prepare_human_approval_packet.py
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/prepare_human_approval_packet.py thomsonlint
python3 scripts/run_langgraph_v0.py thomsonlint
python3 scripts/run_nightly_window.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```

When `latest_human_approval` is present, `scripts/validate_agent_run.py` validates all Phase 17 artifacts and checks the default deny safety posture.
