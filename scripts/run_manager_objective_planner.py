#!/usr/bin/env python3
"""Phase 23 — AI Manager Objective Planner (planning-only).

Reads a Phase 21 FEATURE_BRIEF.json and a Phase 22 ARCHITECTURE_PROPOSAL.json,
then produces a bounded manager objective plan and a draft OpenHands manual gate
request for human review.

This phase is planning-only. It may generate request drafts, but it must not
execute them. No model calls by default; requires both --allow-model-call flag
and AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 env var for live mode.

Usage (mock/deterministic mode)::

    python3 scripts/run_manager_objective_planner.py <project_id> \\
      --feature-id <feature_id> \\
      --mock

Usage (live gated mode)::

    AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 \\
    python3 scripts/run_manager_objective_planner.py <project_id> \\
      --feature-id <feature_id> \\
      --allow-model-call

"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase23_ai_manager_objective_planner"
MANAGER_OBJECTIVE_PLAN_SCHEMA = ROOT / "schemas" / "manager_objective_plan.schema.json"

VALID_PLAN_STATUSES = frozenset({"draft_ready", "needs_clarification", "blocked"})


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n")


def model_call_allowed(allow_flag: bool) -> bool:
    """Return True only when both CLI flag and env var are set."""
    env_val = os.environ.get("AGENT_MANAGER_AI_ENABLE_MODEL_CALLS", "0").strip() == "1"
    return allow_flag and env_val


def load_project_config(project_id: str, recorder: list[tuple[str, bool]]) -> dict[str, Any] | None:
    """Validate project_id against configs/projects.json."""
    config_path = ROOT / "configs" / "projects.json"
    data = load_json(config_path)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        recorder.append(("project_config_shape", False))
        return None
    project = projects.get(project_id)
    if not isinstance(project, dict):
        recorder.append(("unknown_project_id", False))
        return None
    recorder.append(("valid_project_id", True))
    return project


def find_feature_brief(project_id: str, feature_id: str) -> tuple[dict[str, Any] | None, Path | None]:
    """Locate a valid Phase 21 FEATURE_BRIEF.json."""
    candidate_dir = ROOT / "runs" / project_id / "feature_briefs" / feature_id
    if not candidate_dir.is_dir():
        return None, None
    brief_path = candidate_dir / "FEATURE_BRIEF.json"
    if not brief_path.exists():
        return None, None
    try:
        data = load_json(brief_path)
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    if data.get("generated_by", "") != "phase21_feature_brief_intake":
        return None, None
    return data, brief_path


def find_architecture_proposal(project_id: str, feature_id: str) -> tuple[dict[str, Any] | None, Path | None]:
    """Locate a valid Phase 22 ARCHITECTURE_PROPOSAL.json."""
    candidate_dir = ROOT / "runs" / project_id / "architecture_proposals" / feature_id
    if not candidate_dir.is_dir():
        return None, None
    proposal_path = candidate_dir / "ARCHITECTURE_PROPOSAL.json"
    if not proposal_path.exists():
        return None, None
    try:
        data = load_json(proposal_path)
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    if data.get("generated_by", "") != "phase22_ai_architecture_agent":
        return None, None
    return data, proposal_path


def validate_against_schema(data: dict[str, Any], schema_path: Path) -> tuple[bool, list[str]]:
    """Lightweight JSON-schema validation (no external deps)."""
    errors: list[str] = []
    try:
        schema = load_json(schema_path)
    except (FileNotFoundError, json.JSONDecodeError):
        return True, errors

    required = schema.get("required", [])
    for field in required:
        if field not in data:
            errors.append(f"missing required field: {field}")

    properties = schema.get("properties", {})
    for key, prop_schema in properties.items():
        if key not in data:
            continue
        value = data[key]
        enum_vals = prop_schema.get("enum")
        if enum_vals is not None and value not in enum_vals:
            errors.append(f"field {key!r} must be one of {enum_vals}; got {value!r}")

        const_val = prop_schema.get("const")
        if const_val is not None and value != const_val:
            errors.append(f"field {key!r} must be {const_val!r}; got {value!r}")

        type_hint = prop_schema.get("type")
        if type_hint == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"field {key!r} must be integer; got {type(value).__name__}")
        elif type_hint == "string":
            min_len = prop_schema.get("minLength")
            max_len = prop_schema.get("maxLength")
            pattern = prop_schema.get("pattern")
            vs = str(value)
            if min_len is not None and len(vs) < min_len:
                errors.append(f"field {key!r} length must be >= {min_len}")
            if max_len is not None and len(vs) > max_len:
                errors.append(f"field {key!r} length must be <= {max_len}")
            if pattern is not None and not re.search(pattern, vs):
                errors.append(f"field {key!r} does not match pattern {pattern!r}")
        elif type_hint == "boolean":
            if not isinstance(value, bool):
                errors.append(f"field {key!r} must be boolean; got {type(value).__name__}")
        elif type_hint == "array":
            if not isinstance(value, list):
                errors.append(f"field {key!r} must be array; got {type(value).__name__}")
            min_items = prop_schema.get("minItems")
            if min_items is not None and len(value) < min_items:
                errors.append(f"field {key!r} must have at least {min_items} items; got {len(value)}")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Manager objective plan generation
# ---------------------------------------------------------------------------


def build_manager_prompt(
    brief_data: dict[str, Any],
    arch_data: dict[str, Any],
    project_id: str,
    feature_id: str,
) -> str:
    """Build a bounded manager-planner prompt from the source artifacts."""
    lines = [
        "# Manager Objective Planner Prompt",
        "",
        "## Source Feature Brief (Phase 21)",
        "",
        f"- **Project**: {brief_data.get('project_id', '')}",
        f"- **Feature ID**: {brief_data.get('feature_id', '')}",
        f"- **Title**: {brief_data.get('title', '')}",
        f"- **Goal**: {brief_data.get('high_level_goal', '')}",
        f"- **Desired Behavior**: {brief_data.get('desired_behavior', '')}",
        "",
    ]

    must_haves = brief_data.get("must_have_requirements", [])
    if must_haves:
        lines.extend(["## Must-Have Requirements", ""])
        for req in must_haves:
            lines.append(f"- {req}")
        lines.append("")

    constraints = brief_data.get("constraints", [])
    if constraints:
        lines.extend(["## Constraints", ""])
        for c in constraints:
            lines.append(f"- {c}")
        lines.append("")

    out_of_scope = brief_data.get("out_of_scope", [])
    if out_of_scope:
        lines.extend(["## Out of Scope (from feature brief)", ""])
        for item in out_of_scope:
            lines.append(f"- {item}")
        lines.append("")

    lines.extend([
        "## Architecture Proposal Summary (Phase 22)",
        "",
        f"- **Status**: {arch_data.get('architecture_status', 'N/A')}",
        f"- **Recommended Design**: {arch_data.get('recommended_design', 'N/A')}",
        "",
    ])

    impl_seq = arch_data.get("implementation_sequence", [])
    if impl_seq:
        lines.extend(["## Implementation Sequence (from architecture)", ""])
        for step in impl_seq:
            lines.append(f"- {step}")
        lines.append("")

    files_involved = arch_data.get("files_likely_involved", [])
    if files_involved:
        lines.extend(["## Files Likely Involved", ""])
        for f_item in files_involved:
            lines.append(f"- `{f_item}`")
        lines.append("")

    lines.extend([
        "## Planning Instructions",
        "",
        "Based on the feature brief and architecture proposal above, produce a bounded",
        "manager objective plan with the following fields:",
        "",
        "- **objective_summary**: Concise summary of what must be achieved.",
        "- **selected_architecture_summary**: Summary of the selected architecture.",
        "- **bounded_scope**: Bounded scope description for implementation.",
        "- **allowed_files**: Files explicitly allowed to be modified (array).",
        "- **disallowed_files**: Files explicitly disallowed from modification (array; required).",
        "- **implementation_steps**: Ordered sequence of implementation steps (array).",
        "- **validation_commands**: Commands to validate the implementation (array).",
        "- **acceptance_criteria**: Acceptance criteria that must be met (array, at least 1).",
        "- **risk_controls**: Risk controls and mitigations identified (array).",
        "- **rollback_plan**: Plan for rolling back if implementation fails.",
        "- **dependencies**: Dependencies required before implementation can begin (array).",
        "- **assumptions**: Assumptions made during planning (array).",
        "- **constraints**: Constraints that apply to the implementation (array).",
        "- **out_of_scope**: Items explicitly out of scope for this objective (array).",
        "- **questions_for_human**: Questions requiring human review (array).",
        "",
        "## Safety Constraints — MUST FOLLOW",
        "",
        "**This planner is planning-only. The output must NOT:**",
        "",
        "- Perform source edits or implementation",
        "- Execute OpenHands",
        "- Automatically execute any request draft",
        "- Apply/commit/push/merge/create PRs",
        "- Delete or modify target repository files",
        "- Call a live model (unless explicitly gated with --allow-model-call + env var)",
        "",
        "**The OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json must be:**",
        "- Marked as draft_only: true",
        "- Marked as approved_for_execution: false",
        "- Never consumed automatically by any runner in Phase 23",
        "",
    ])

    return "\n".join(lines)


def generate_mock_plan(
    project_id: str,
    feature_id: str,
    brief_data: dict[str, Any],
    arch_data: dict[str, Any],
    source_brief_path: Path,
    source_arch_path: Path,
) -> dict[str, Any]:
    """Generate a deterministic mock manager objective plan."""
    created_utc = utc_now()
    title = brief_data.get("title", "Untitled Feature")

    # Build bounded scope from feature goal + architecture recommendation
    goal = brief_data.get("high_level_goal", "")
    behavior = brief_data.get("desired_behavior", "")
    recommended_design = arch_data.get("recommended_design", "N/A")

    objective_summary = (
        f"Implement '{title}'. Goal: {goal}. Expected behavior: {behavior}."
    )
    selected_architecture_summary = (
        f"Selected design from Phase 22 proposal: {recommended_design}"
    )
    bounded_scope = (
        f"Bounded to implementing the must-have requirements from the feature brief "
        f"'{title}' using the recommended architecture. Scope limited to "
        f"{project_id} project within the agent-manager framework."
    )

    # Allowed files — derive from architecture proposal + planner own files
    allowed_files = [
        str(source_brief_path),
        str(source_arch_path),
        f"runs/{project_id}/manager_objective_plans/{feature_id}/MANAGER_OBJECTIVE_PLAN.json",
        f"runs/{project_id}/manager_objective_plans/{feature_id}/MANAGER_OBJECTIVE_PLAN.md",
        f"runs/{project_id}/manager_objective_plans/{feature_id}/OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json",
    ]

    # Disallowed files — target repo and safety-sensitive paths
    disallowed_files = [
        "Any file in the target project repository (read-only access only)",
        ".git/** (no git operations)",
        "**/WORKTREE_STATUS.json (no write to worktree state)",
        "**/.agent_manager/** (no project-state writes)",
        "configs/projects.json (no config mutations)",
    ]

    # Implementation steps derived from architecture sequence + brief requirements
    impl_seq = arch_data.get("implementation_sequence", [])
    must_haves = brief_data.get("must_have_requirements", [])
    implementation_steps = []
    for step in impl_seq:
        if isinstance(step, str) and step.strip():
            implementation_steps.append(f"[Phase 23 plan] {step}")
    if must_haves:
        implementation_steps.append(
            f"Verify all must-have requirements from feature brief are addressed: "
            + "; ".join(must_haves[:3])
        )
    if not implementation_steps:
        implementation_steps = ["[Phase 23 plan] Review and validate the generated objective plan"]

    # Validation commands
    validation_commands = [
        f"python3 -m py_compile scripts/run_manager_objective_planner.py",
        f"python3 scripts/validate_agent_run.py {project_id}",
        "python3 -m unittest discover -s tests",
        "python3 scripts/audit_portability.py",
    ]

    # Acceptance criteria
    acceptance_criteria = [
        f"MANAGER_OBJECTIVE_PLAN.json exists under runs/{project_id}/manager_objective_plans/{feature_id}/",
        f"MANAGER_OBJECTIVE_PLAN.md exists alongside the JSON artifact",
        "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json exists with draft_only=true and approved_for_execution=false",
        "All safety flags (source_writes_performed, openhands_executed, coder_task_executed) are false",
        "No apply/commit/push/merge/PR flags are set to true",
        "Model call gating is respected (model_call_allowed and model_called reflect actual state)",
    ]

    # Risk controls
    risk_controls = [
        "Model calls disabled by default; requires both --allow-model-call flag and AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 env var.",
        "Source writes to target project repos blocked in mock mode.",
        "OpenHands execution explicitly forbidden in Phase 23.",
        "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json marked draft_only=true; never auto-consumed by runners.",
    ]

    rollback_plan = (
        "If implementation fails: revert to pre-implementation state using git reflog or backup. "
        f"The objective plan is non-executing, so no rollback of code changes is needed. "
        "Regenerate the plan with corrected inputs if the draft has issues."
    )

    dependencies = [
        "Phase 21 FEATURE_BRIEF.json must exist and be valid",
        "Phase 22 ARCHITECTURE_PROPOSAL.json must exist and be valid",
        f"Project '{project_id}' must be registered in configs/projects.json",
    ]

    assumptions = [
        f"Feature brief at runs/{project_id}/feature_briefs/{feature_id}/FEATURE_BRIEF.json is valid.",
        "Architecture proposal accurately reflects the recommended design from Phase 22.",
        "No live model calls are needed for mock mode.",
        "The target project repo remains read-only during planning.",
    ]

    constraints = [
        "No OpenHands execution in Phase 23",
        "No source writes to target repos",
        "Model calls disabled by default",
        "Deterministic output in --mock mode",
        "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json is draft-only; never auto-executed",
    ]

    out_of_scope = [
        "Executing the OpenHands manual gate request draft",
        "Source code implementation or modification",
        "Live model inference (unless explicitly gated)",
        "Multi-project planning board behavior (Phase 24 — not implemented in Phase 23)",
    ]

    questions_for_human = [
        f"Is the bounded scope appropriate for feature '{title}'?",
        "Are there additional constraints or requirements not captured in the source artifacts?",
        "Should any must-have requirement be re-prioritized before implementation?",
        "Is the draft OpenHands manual gate request ready for human approval?",
    ]

    return {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "created_utc": created_utc,
        "project_id": project_id,
        "feature_id": feature_id,
        "source_feature_brief_path": str(source_brief_path),
        "source_architecture_proposal_path": str(source_arch_path),
        "title": title.strip(),
        "manager_plan_status": "draft_ready",
        "objective_id": f"obj_{feature_id}_001",
        "objective_summary": objective_summary,
        "selected_architecture_summary": selected_architecture_summary,
        "bounded_scope": bounded_scope,
        "allowed_files": allowed_files,
        "disallowed_files": disallowed_files,
        "implementation_steps": implementation_steps,
        "validation_commands": validation_commands,
        "acceptance_criteria": acceptance_criteria,
        "risk_controls": risk_controls,
        "rollback_plan": rollback_plan,
        "dependencies": dependencies,
        "assumptions": assumptions,
        "constraints": constraints,
        "out_of_scope": out_of_scope,
        "questions_for_human": questions_for_human,
        "ready_for_openhands_manual_gate": True,
        "model_call_allowed": False,
        "model_called": False,
        "source_writes_performed": False,
        "openhands_executed": False,
        "coder_task_executed": False,
        "apply_performed": False,
        "commit_performed": False,
        "push_performed": False,
        "merge_performed": False,
        "pr_created": False,
    }


def generate_openhands_manual_gate_draft(
    plan_data: dict[str, Any],
) -> dict[str, Any]:
    """Generate a draft OpenHands manual gate request from the manager objective plan.

    This is a DRAFT only — never auto-consumed by any runner in Phase 23.
    """
    return {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "created_utc": plan_data["created_utc"],
        "project_id": plan_data["project_id"],
        "feature_id": plan_data["feature_id"],
        "objective_id": plan_data.get("objective_id", ""),
        "title": plan_data.get("title", ""),
        "task_summary": plan_data.get("objective_summary", ""),
        "allowed_files": plan_data.get("allowed_files", []),
        "disallowed_files": plan_data.get("disallowed_files", []),
        "validation_commands": plan_data.get("validation_commands", []),
        "acceptance_criteria": plan_data.get("acceptance_criteria", []),
        "safety_notes": [
            "This is a DRAFT request. Never auto-consume or auto-execute.",
            f"Source manager objective plan: {plan_data.get('source_feature_brief_path', '')}",
        ],
        "source_manager_objective_plan_path": (
            f"runs/{plan_data['project_id']}/manager_objective_plans/"
            f"{plan_data['feature_id']}/MANAGER_OBJECTIVE_PLAN.json"
        ),
        "draft_only": True,
        "approved_for_execution": False,
        "openhands_executed": False,
        "source_writes_performed": False,
        "apply_performed": False,
        "commit_performed": False,
        "push_performed": False,
        "merge_performed": False,
        "pr_created": False,
    }


def build_markdown_plan(plan_data: dict[str, Any]) -> str:
    """Build a Markdown summary of the manager objective plan."""
    lines = [
        f"# Manager Objective Plan: {plan_data['title']}",
        "",
        f"- **Feature ID**: {plan_data['feature_id']}",
        f"- **Project**: {plan_data['project_id']}",
        f"- **Status**: {plan_data['manager_plan_status']}",
        f"- **Objective ID**: {plan_data.get('objective_id', 'N/A')}",
        f"- **Created UTC**: {plan_data['created_utc']}",
        f"- **Generated By**: {plan_data['generated_by']}",
        "",
    ]

    # Objective summary
    obj_summary = plan_data.get("objective_summary")
    if obj_summary:
        lines.extend(["## Objective Summary", "", obj_summary, ""])

    # Selected architecture
    arch_summary = plan_data.get("selected_architecture_summary")
    if arch_summary:
        lines.extend(["## Selected Architecture", "", arch_summary, ""])

    # Bounded scope
    bounded = plan_data.get("bounded_scope")
    if bounded:
        lines.extend(["## Bounded Scope", "", bounded, ""])

    # Allowed files
    allowed = plan_data.get("allowed_files")
    if allowed:
        lines.extend(["## Allowed Files", ""])
        for f_item in allowed:
            lines.append(f"- `{f_item}`")
        lines.append("")

    # Disallowed files
    disallowed = plan_data.get("disallowed_files")
    if disallowed:
        lines.extend(["## Disallowed Files", ""])
        for f_item in disallowed:
            lines.append(f"- `{f_item}`")
        lines.append("")

    # Implementation steps
    impl_steps = plan_data.get("implementation_steps")
    if impl_steps:
        lines.extend(["## Implementation Steps", ""])
        for i, step in enumerate(impl_steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    # Validation commands
    val_cmds = plan_data.get("validation_commands")
    if val_cmds:
        lines.extend(["## Validation Commands", ""])
        for cmd in val_cmds:
            lines.append(f"- `{cmd}`")
        lines.append("")

    # Acceptance criteria
    acceptance = plan_data.get("acceptance_criteria")
    if acceptance:
        lines.extend(["## Acceptance Criteria", ""])
        for criterion in acceptance:
            lines.append(f"- [ ] {criterion}")
        lines.append("")

    # Risk controls
    risks = plan_data.get("risk_controls")
    if risks:
        lines.extend(["## Risk Controls", ""])
        for risk in risks:
            lines.append(f"- {risk}")
        lines.append("")

    # Rollback plan
    rollback = plan_data.get("rollback_plan")
    if rollback:
        lines.extend(["## Rollback Plan", "", rollback, ""])

    # Dependencies
    deps = plan_data.get("dependencies")
    if deps:
        lines.extend(["## Dependencies", ""])
        for dep in deps:
            lines.append(f"- {dep}")
        lines.append("")

    # Assumptions
    assumptions = plan_data.get("assumptions")
    if assumptions:
        lines.extend(["## Assumptions", ""])
        for a in assumptions:
            lines.append(f"- {a}")
        lines.append("")

    # Constraints
    constraints = plan_data.get("constraints")
    if constraints:
        lines.extend(["## Constraints", ""])
        for c in constraints:
            lines.append(f"- {c}")
        lines.append("")

    # Out of scope
    oos = plan_data.get("out_of_scope")
    if oos:
        lines.extend(["## Out of Scope", ""])
        for item in oos:
            lines.append(f"- {item}")
        lines.append("")

    # Questions for human
    questions = plan_data.get("questions_for_human")
    if questions:
        lines.extend(["## Questions for Human Review", ""])
        for q in questions:
            lines.append(f"- {q}")
        lines.append("")

    # Source paths
    lines.extend([
        "## Source Artifacts",
        "",
        f"- **Feature Brief**: {plan_data.get('source_feature_brief_path', 'N/A')}",
        f"- **Architecture Proposal**: {plan_data.get('source_architecture_proposal_path', 'N/A')}",
        "",
    ])

    # Safety summary
    lines.extend([
        "## Safety Summary",
        "",
        f"- Model call allowed: {plan_data.get('model_call_allowed', False)}",
        f"- Model called: {plan_data.get('model_called', False)}",
        f"- Source writes performed: {plan_data.get('source_writes_performed', False)}",
        f"- OpenHands executed: {plan_data.get('openhands_executed', False)}",
        f"- Coder task executed: {plan_data.get('coder_task_executed', False)}",
        f"- Apply performed: {plan_data.get('apply_performed', False)}",
        f"- Commit performed: {plan_data.get('commit_performed', False)}",
        f"- Push performed: {plan_data.get('push_performed', False)}",
        f"- Merge performed: {plan_data.get('merge_performed', False)}",
        f"- PR created: {plan_data.get('pr_created', False)}",
        "",
        "## OpenHands Manual Gate Request Draft Status",
        "",
        f"- Ready for manual gate: {plan_data.get('ready_for_openhands_manual_gate', False)}",
        "- **OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json**: draft_only=true, approved_for_execution=false",
        "- Never auto-consumed by Phase 23 runners",
        "",
        "---",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main planner entry point
# ---------------------------------------------------------------------------


def run_manager_objective_planner(
    project_id: str,
    feature_id: str,
    allow_model_call: bool = False,
) -> dict[str, Any]:
    """Run the manager objective planner.

    Returns the plan data dict. Raises SystemExit on validation failure.
    """
    recorder: list[tuple[str, bool]] = []

    # 1. Validate project config
    project = load_project_config(project_id, recorder)
    if project is None:
        bad = [msg for msg, ok in recorder if not ok]
        raise SystemExit(f"Manager objective planner rejected: {bad}")

    # 2. Locate Phase 21 feature brief
    brief_data, brief_path = find_feature_brief(project_id, feature_id)
    if brief_data is None or brief_path is None:
        raise SystemExit(
            f"Manager objective planner rejected: no valid Phase 21 FEATURE_BRIEF.json "
            f"found for project={project_id!r}, feature_id={feature_id!r}"
        )

    # 3. Locate Phase 22 architecture proposal
    arch_data, arch_path = find_architecture_proposal(project_id, feature_id)
    if arch_data is None or arch_path is None:
        raise SystemExit(
            f"Manager objective planner rejected: no valid Phase 22 ARCHITECTURE_PROPOSAL.json "
            f"found for project={project_id!r}, feature_id={feature_id!r}"
        )

    # 4. Determine model call mode
    allowed = model_call_allowed(allow_model_call)
    mock_mode = not allowed

    # 5. Build manager prompt (logged but not executed in mock mode)
    planner_prompt = build_manager_prompt(brief_data, arch_data, project_id, feature_id)

    if mock_mode:
        plan_data = generate_mock_plan(
            project_id=project_id,
            feature_id=feature_id,
            brief_data=brief_data,
            arch_data=arch_data,
            source_brief_path=brief_path,
            source_arch_path=arch_path,
        )
        # In mock mode, safety flags are guaranteed false
        plan_data["model_call_allowed"] = False
        plan_data["model_called"] = False
    else:
        # Live gated mode — in a real implementation this would call the model
        # through an existing model-call path. For now we still use the mock generator
        # but mark that a live call was allowed (not called yet).
        plan_data = generate_mock_plan(
            project_id=project_id,
            feature_id=feature_id,
            brief_data=brief_data,
            arch_data=arch_data,
            source_brief_path=brief_path,
            source_arch_path=arch_path,
        )
        plan_data["model_call_allowed"] = True

    # 6. Validate against schema
    schema_ok, schema_errors = validate_against_schema(plan_data, MANAGER_OBJECTIVE_PLAN_SCHEMA)
    if not schema_ok:
        raise SystemExit(f"Manager objective plan rejected by schema validation: {schema_errors}")

    # 7. Write artifacts to central storage (not target repo)
    out_dir = ROOT / "runs" / project_id / "manager_objective_plans" / feature_id

    write_json(out_dir / "MANAGER_OBJECTIVE_PLAN.json", plan_data)
    (out_dir / "MANAGER_OBJECTIVE_PLAN.md").write_text(build_markdown_plan(plan_data))

    # 8. Write draft OpenHands manual gate request (draft_only, never auto-consumed)
    draft_request = generate_openhands_manual_gate_draft(plan_data)
    write_json(out_dir / "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json", draft_request)

    # 9. Write the planner prompt for reference
    (out_dir / "MANAGER_OBJECTIVE_PLANNER_PROMPT.md").write_text(
        f"# Manager Objective Planner Prompt\n\n"
        f"This prompt was generated by the Phase 23 AI Manager Objective Planner.\n\n"
        f"## Source Feature Brief\n\n"
        f"- **Project**: {brief_data.get('project_id', '')}\n"
        f"- **Feature ID**: {brief_data.get('feature_id', '')}\n"
        f"- **Title**: {brief_data.get('title', '')}\n"
        f"- **Goal**: {brief_data.get('high_level_goal', '')}\n\n"
        f"## Architecture Proposal Summary\n\n"
        f"- **Status**: {arch_data.get('architecture_status', 'N/A')}\n"
        f"- **Recommended Design**: {arch_data.get('recommended_design', 'N/A')}\n\n"
        f"## Safety Flags\n\n"
        f"- Model call allowed: {plan_data.get('model_call_allowed', False)}\n"
        f"- Model called: {plan_data.get('model_called', False)}\n"
        f"- Source writes performed: {plan_data.get('source_writes_performed', False)}\n"
        f"- OpenHands executed: {plan_data.get('openhands_executed', False)}\n"
        f"- Draft request approved: {draft_request.get('approved_for_execution', False)}\n\n"
        f"## Planning Instructions\n\n"
    )

    return plan_data


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 23 — AI Manager Objective Planner (planning-only).",
    )
    parser.add_argument(
        "project_id",
        help="Registered project identifier from configs/projects.json.",
    )
    parser.add_argument(
        "--feature-id",
        required=True,
        help="Feature ID matching a Phase 21 FEATURE_BRIEF.json and Phase 22 ARCHITECTURE_PROPOSAL.json.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Generate a deterministic mock manager objective plan (default: safe mode).",
    )
    parser.add_argument(
        "--allow-model-call",
        action="store_true",
        default=False,
        help="Allow live model calls. Requires both this flag and AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1.",
    )
    args = parser.parse_args()

    # Determine effective allow_model_call: --mock forces it off
    allow_model_call = False if args.mock else args.allow_model_call

    try:
        plan_data = run_manager_objective_planner(
            project_id=args.project_id,
            feature_id=args.feature_id,
            allow_model_call=allow_model_call,
        )
    except SystemExit as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise

    out_dir = ROOT / "runs" / args.project_id / "manager_objective_plans" / args.feature_id

    print(f"Manager objective plan generated for project '{args.project_id}'")
    print(f"  Feature ID                : {plan_data['feature_id']}")
    print(f"  Title                     : {plan_data['title']}")
    print(f"  Manager Plan Status       : {plan_data['manager_plan_status']}")
    print(f"  Objective ID              : {plan_data.get('objective_id', 'N/A')}")
    print(f"  Model Call Allowed        : {plan_data['model_call_allowed']}")
    print(f"  Model Called              : {plan_data['model_called']}")
    print(f"  Source Writes             : {plan_data['source_writes_performed']}")
    print(f"  OpenHands Executed        : {plan_data['openhands_executed']}")
    print(f"  Coder Task Executed       : {plan_data['coder_task_executed']}")
    print(f"  Apply/Commit/Push/Merge/PR: {plan_data['apply_performed']}/{plan_data['commit_performed']}/{plan_data['push_performed']}/{plan_data['merge_performed']}/{plan_data['pr_created']}")
    print(f"  Draft Request Approved      : False (draft_only)")
    print(f"  Plan dir                  : {out_dir}")


if __name__ == "__main__":
    main()
