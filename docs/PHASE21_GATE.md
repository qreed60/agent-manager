# Phase 21 Gate: Feature Brief Intake and Queue

Phase 21 introduces a central **feature-intake system** where the user can define
high-level features across registered projects. The feature brief captures enough
structured information for later architecture and manager agents, but this phase
remains **deterministic and non-executing**.

This phase is **intake only**. It does not apply patches, commit, push, merge,
create PRs, delete worktrees, modify the canonical repo, invoke model calls, or
execute OpenHands.

## Gates

Phase 21 introduces no new environment variable gates beyond what is required for
the intake script itself. The following safety constraints are enforced:

- `--title` is required and must be non-empty
- `--goal` (--high-level-goal) is required and must be non-empty
- `--behavior` (--desired-behavior) is required and must be non-empty
- `project_id` must match a registered project in `configs/projects.json`
- `risk_level` must be one of: `low`, `medium`, `high`
- `human_priority` must be numeric (1-5 conventionally)
- All generated artifacts are validated against JSON schemas
- Queue entries reference existing brief artifact paths
- No execution-enabling flags may appear in Phase 21 artifacts

## Commands

### Create a feature brief

```bash
python3 scripts/create_feature_brief.py <project_id> \
  --title "Feature title" \
  --goal "High-level goal statement" \
  --behavior "Desired behavior description" \
  --must "Must-have requirement one" \
  --must "Must-have requirement two" \
  --nice "Nice-to-have requirement" \
  --constraint "Constraint description" \
  --out-of-scope "Out of scope item" \
  --risk-level low \
  --target-project-area "agent planning" \
  --human-priority 1
```

### Create a minimal feature brief (only required fields)

```bash
python3 scripts/create_feature_brief.py <project_id> \
  --title "Quick Feature" \
  --goal "Simple goal" \
  --behavior "Simple behavior" \
  --must "Must have one requirement"
```

### Validate Phase 21 artifacts

Run the full validation suite which includes Phase 21 checks:

```bash
python3 scripts/validate_agent_run.py <project_id>
```

## Artifact Locations

Feature briefs and queues are stored under central agent-manager run/state storage, **not** target project source repos.

| Artifact | Location |
|----------|----------|
| Latest feature queue | `runs/<project_id>/feature_queue/FEATURE_QUEUE.json` |
| Individual feature brief (JSON) | `runs/<project_id>/feature_briefs/<feature_id>/FEATURE_BRIEF.json` |
| Individual feature brief (Markdown) | `runs/<project_id>/feature_briefs/<feature_id>/FEATURE_BRIEF.md` |

### JSON Schemas

| Schema | Location |
|--------|----------|
| Feature Brief schema | `schemas/feature_brief.schema.json` |
| Feature Queue schema | `schemas/feature_queue.schema.json` |

## Data Model

### FEATURE_BRIEF.json

```jsonc
{
  "schema_version": 1,            // Must be 1
  "generated_by": "phase21_feature_brief_intake",
  "created_utc": "YYYYMMDDTHHMMSSZ",
  "project_id": "<registered_project>",
  "feature_id": "feat_<slug_from_title>",
  "title": "<short descriptive title>",
  "high_level_goal": "...",       // Required
  "desired_behavior": "...",      // Required
  "must_have_requirements": ["..."],  // Required, non-empty array
  "nice_to_have_requirements": ["..."],
  "constraints": ["..."],
  "out_of_scope": ["..."],
  "risk_level": "low|medium|high",  // Must be one of these three
  "target_project_area": "...",
  "human_priority": 1,            // Numeric (1-5 conventionally)
  "status": "brief_only"          // See status values below
}
```

### FEATURE_QUEUE.json

```jsonc
{
  "schema_version": 1,
  "generated_by": "phase21_feature_brief_intake",
  "created_utc": "YYYYMMDDTHHMMSSZ",
  "project_id": "<registered_project>",
  "features": [                  // Non-empty array of feature entries
    {
      "feature_id": "feat_...",
      "title": "...",
      "status": "brief_only|needs_clarification|ready_for_architecture|blocked|archived",
      "created_utc": "YYYYMMDDTHHMMSSZ",
      "brief_path": "runs/<project>/feature_briefs/feat_..."
    }
  ]
}
```

### Suggested Status Values

| Status | Meaning |
|--------|---------|
| `brief_only` | Initial state — brief has been created but not yet reviewed |
| `needs_clarification` | Brief requires additional information or clarification |
| `ready_for_architecture` | Brief is complete and ready for architecture-agent consumption |
| `blocked` | Brief cannot proceed due to external dependencies |
| `archived` | Brief has been closed without further action |

### Suggested Risk Levels

| Level | Meaning |
|-------|---------|
| `low` | Minimal risk — no source writes, no external dependencies |
| `medium` | Moderate risk — may involve cross-project coordination |
| `high` | High risk — involves sensitive operations or significant scope |

## Safety Guarantees

Phase 21 is **strictly intake-only**. The following safety guarantees are enforced:

- **No model calls**: Feature brief creation uses only deterministic Python logic.
  No LLM, API, or remote service invocation occurs.
- **No OpenHands execution**: The script does not invoke OpenHands, start any agent,
  or trigger external execution environments.
- **No source writes to target project repos**: All artifacts are written under
  `runs/<project_id>/` within the agent-manager repository itself, never into
  `/mnt/projects/ThomsonLint` or any other target project's canonical repository.
- **No apply/commit/push/merge/PR behavior**: Phase 21 performs no git operations.
- **Deterministic validation authority preserved**: All artifacts are validated against
  JSON schemas before and after creation. The `validate_agent_run.py` script includes
  dedicated Phase 21 checks that verify schema compliance, required fields, valid
  project_id, valid status values, valid risk levels, numeric human_priority, queue
  references to existing brief artifacts, and absence of execution-enabling flags.
- **No permission expansion**: Feature briefs carry no execution permissions or
  capability grants. They are advisory documents only.

## Validation Commands

### Syntax check

```bash
python3 -m py_compile scripts/create_feature_brief.py
python3 -m py_compile scripts/validate_agent_run.py
```

### Run unit tests

```bash
python3 -m unittest discover -s tests
```

Focused test coverage includes:

- Creating a minimal valid feature brief
- Creating a full feature brief with must/nice/constraints/out-of-scope fields
- Rejecting invalid project ID
- Rejecting missing title, goal, or behavior
- Stable slug/feature_id generation (same title produces same ID)
- Queue includes created feature
- Multiple projects can have separate feature queues
- Validation fails on malformed queue/brief JSON
- No Phase 21 path enables model calls or OpenHands execution

### Run portability audit

```bash
python3 scripts/audit_portability.py
```

### Full validation with Phase 21 artifacts present

```bash
python3 scripts/validate_agent_run.py <project_id>
```

This validates:
- FEATURE_QUEUE.json parses as valid JSON
- Queue has schema_version and generated_by fields
- Queue project_id matches the validated project
- Each queue feature entry has valid status and references existing brief
- Each FEATURE_BRIEF.json has all required fields, valid status, valid risk_level
- human_priority is numeric in each brief
- No execution-enabling flags in Phase 21 artifacts
- FEATURE_BRIEF.md exists alongside each FEATURE_BRIEF.json

### Run orchestrator scripts (should remain safe with Phase 21 present)

```bash
python3 scripts/run_langgraph_v0.py <project_id>
python3 scripts/run_nightly_window.py <project_id>
python3 scripts/validate_agent_run.py <project_id>
```

## Explicit Statement: Intake Only

**Phase 21 is intake only.** It does not and must not:

- Generate architecture-agent behavior or plans
- Perform manager objective planning
- Draft OpenHands requests
- Execute OpenHands tasks
- Make model calls (LLM, API, remote services)
- Execute coder agents
- Implement multi-project planning boards
- Apply patches, commit code, push to remotes, merge branches, or create PRs
- Modify canonical target project repositories
- Enable any execution permissions or capability grants

Phase 21's sole purpose is to capture structured feature briefs in a deterministic,
schema-validatable format that later phases can consume as input. All artifact
generation is local to the agent-manager run directory structure.

## Multi-Project Support

Each registered project maintains its own feature queue at:

```
runs/<project_id>/feature_queue/FEATURE_QUEUE.json
```

Feature briefs for different projects are stored in separate directories under their
respective `runs/<project_id>/` trees. The CLI requires a valid `--project_id` that
matches an entry in `configs/projects.json`.

## Updating Brief Status

To update a feature brief's status (e.g., moving from `brief_only` to
`ready_for_architecture`), edit the `FEATURE_BRIEF.json` directly and ensure the
corresponding entry in `FEATURE_QUEUE.json` reflects the new status. Future phases
may automate this through agent workflows, but Phase 21 does not include such
automation — it remains a manual, deterministic update process.
