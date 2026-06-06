# Phase 18A Model-Backed Read-Only AI Agent Gate

Phase 18A introduces the first model-backed agent in the framework. It is **read-only and advisory only**. It does not execute OpenHands, write target project source, auto-push, auto-merge, or create PRs.

## Safety Design

Live model calls require **both** of the following:

1. `--allow-model-call` CLI flag
2. `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1` environment variable

If either is missing, the agent runs in dry-run mode with deterministic placeholder output and performs no model call.

## Run

```bash
# Dry-run (default — no model call)
python3 scripts/run_ai_readonly_agent.py thomsonlint

# Live model call (requires both flag AND env var)
AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 python3 scripts/run_ai_readonly_agent.py thomsonlint --allow-model-call
```

### Optional flags

| Flag | Default | Description |
|------|---------|-------------|
| `--timeout-seconds` | 60 | HTTP timeout for model call |
| `--max-input-chars` | 12000 | Max prompt input size |
| `--model` | (env fallback) | Override model name |
| `--base-url` | (env fallback) | Override base URL |

## Environment Variables

### Primary (AGENT_MANAGER_*)

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MANAGER_OPENAI_BASE_URL` | `http://127.0.0.1:1234/v1` | OpenAI-compatible API base URL |
| `AGENT_MANAGER_OPENAI_API_KEY` | (none) | API key for the endpoint |
| `AGENT_MANAGER_AI_MODEL` | `gpt-4o-mini` | Model name to use |
| `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS` | (unset) | Must be `1` to enable live calls |

### Fallback (legacy names, lower precedence)

- `OPENAI_BASE_URL`, `OPENAI_API_KEY`
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
- `MODEL`

The agent prefers `AGENT_MANAGER_*` variables when present.

## Inputs

The script reads latest deterministic artifacts when present:

- `latest_human_approval`
- `latest_nightly_window`
- `latest_langgraph_v0`
- `latest_validation`
- `latest_review_agents`
- `latest_model_routing`
- `latest_morning_report`
- `latest_runner_v0`
- `latest_manager_plan`

It carries artifact references and concise summaries (not full file contents). It respects `--max-input-chars`. It does not read arbitrary source files or modify target project files.

## Outputs

Each run writes:

```text
runs/<project_id>/ai_readonly_<timestamp>/
```

### Required artifacts

| File | Type | Description |
|------|------|-------------|
| `AI_READONLY_REVIEW.json` | JSON | AI review report (advisory) |
| `AI_READONLY_REVIEW.md` | Markdown | Human-readable review |
| `AI_PROMPT.md` | Markdown | The prompt sent to the model (or dry-run placeholder) |
| `AI_RESPONSE_RAW.txt` | Text | Raw model response or dry-run placeholder |
| `AI_RESPONSE_PARSED.json` | JSON | Parsed model response (warn if unparseable, not fail) |
| `AI_SAFETY_STATUS.json` | JSON | Safety posture record |
| `AI_READONLY_SUMMARY.json` | JSON | Run summary with safety status |
| `AI_READONLY_SUMMARY.md` | Markdown | Human-readable summary |

### Symlink

```text
runs/<project_id>/latest_ai_readonly -> ai_readonly_<timestamp>
```

## AI Review Scope

- **Role**: `read_only_manager_reviewer` (advisory)
- Summarizes current objective from latest artifacts
- Assesses latest validation, review-agent, model-routing, nightly-window, and human-approval status
- Identifies risks
- Recommends one of: `accept`, `revise`, `discard`, `hold`
- Explicitly states the AI agent cannot approve its own work
- Explicitly states deterministic validation remains authoritative

## Safety Guarantees

| Guarantee | Status |
|-----------|--------|
| No OpenHands execution | Enforced |
| No source writes | Enforced |
| No auto-push | Enforced |
| No auto-merge | Enforced |
| No PR creation | Enforced |
| No shell/tool access for model | Enforced (no tools granted) |
| Secrets excluded from prompts | Enforced (API keys never written to artifacts) |
| Reports store only base URL host | Enforced (not full URLs with paths/secrets) |

## Dry-Run Mode

When `--allow-model-call` is not provided or `AGENT_MANAGER_AI_ENABLE_MODEL_CALLS != 1`:

- `AI_RESPONSE_RAW.txt` contains a deterministic placeholder
- `AI_SAFETY_STATUS.json` records: `model_call_performed=false`, `dry_run=true`
- `AI_RESPONSE_PARSED.json` contains valid deterministic JSON with status `warn`
- All other artifacts are generated normally

## Validation Integration

`scripts/validate_agent_run.py` validates `latest_ai_readonly` when present:

- Requires all 8 required files exist and parse correctly
- Parses `AI_READONLY_REVIEW.json`, `AI_RESPONSE_PARSED.json`, `AI_SAFETY_STATUS.json`, `AI_READONLY_SUMMARY.json`
- Fails if safety status indicates source writes, OpenHands execution, push, merge, or PR creation were allowed
- Does **not** require that a model call was performed

## Nightly Timer

This phase is **not** added to the default nightly timer (`run_nightly_window.py`) or `run_langgraph_v0.py` default execution. It must be opted in manually.

## Validation

Run:

```bash
python3 -m py_compile scripts/run_ai_readonly_agent.py
python3 -m unittest discover -s tests
python3 scripts/audit_portability.py
python3 scripts/run_ai_readonly_agent.py thomsonlint
python3 scripts/validate_agent_run.py thomsonlint
```
