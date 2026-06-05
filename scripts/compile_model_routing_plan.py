#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "deterministic_model_routing_scaffold"
ROLE_PURPOSES = {
    "long_reasoning": [
        "manager_planning",
        "risk_review",
        "architecture_review",
    ],
    "instruct": [
        "structured_summaries",
        "classification",
        "report_condensation",
    ],
    "vision": [
        "image_visual_evidence_extraction_only",
    ],
    "coding_agent": [
        "isolated_worktree_code_edits_only",
    ],
    "embedding": [
        "retrieval_indexing_support_only",
    ],
}
READ_ONLY_ROLES = {"long_reasoning", "instruct", "vision", "embedding"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def load_project(project_id: str) -> dict[str, Any]:
    config_path = ROOT / "configs" / "projects.json"
    data = load_json(config_path)
    projects = data.get("projects")
    if not isinstance(projects, dict) or not isinstance(projects.get(project_id), dict):
        raise SystemExit(f"unknown project id: {project_id}")
    return projects[project_id]


def project_state_dir(project: dict[str, Any]) -> Path:
    repo_raw = project.get("repo_path")
    if not isinstance(repo_raw, str) or not repo_raw:
        raise SystemExit("project repo_path must be a non-empty string")
    state_dir_name = project.get("project_state_dir", ".agent_manager")
    if not isinstance(state_dir_name, str) or not state_dir_name:
        state_dir_name = ".agent_manager"
    return Path(repo_raw) / state_dir_name


def latest_artifact_paths(project_id: str) -> dict[str, Path]:
    run_root = ROOT / "runs" / project_id
    return {
        "active_objective": run_root / "latest_runner_v0" / "ACTIVE_OBJECTIVE.json",
        "task_graph": run_root / "latest_runner_v0" / "TASK_GRAPH.json",
        "manager_decision": run_root / "latest_manager_plan" / "MANAGER_DECISION.json",
        "review_agents_summary": run_root / "latest_review_agents" / "REVIEW_AGENTS_SUMMARY.json",
        "validation_report": run_root / "latest_validation" / "VALIDATION_REPORT.json",
        "morning_report": run_root / "latest_morning_report" / "MORNING_REPORT.json",
        "langgraph_manifest": run_root / "latest_langgraph_v0" / "LANGGRAPH_RUN_MANIFEST.json",
    }


def load_optional_json(paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, str]]:
    loaded: dict[str, Any] = {}
    presence: dict[str, str] = {}
    for name, path in paths.items():
        try:
            loaded[name] = load_json(path)
            presence[name] = "present"
        except FileNotFoundError:
            presence[name] = "missing"
        except json.JSONDecodeError as exc:
            loaded[name] = {"_error": f"invalid JSON: {exc}"}
            presence[name] = "invalid"
        except OSError as exc:
            loaded[name] = {"_error": f"could not read file: {exc}"}
            presence[name] = "unreadable"
    return loaded, presence


def selected_objective(weekly_plan: dict[str, Any], backlog: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = []
    manager_decision = latest.get("manager_decision")
    if isinstance(manager_decision, dict):
        candidates.append(manager_decision.get("selected_objective"))
    active_objective = latest.get("active_objective")
    if isinstance(active_objective, dict):
        candidates.append(active_objective.get("objective"))
    for source in (weekly_plan, backlog):
        objectives = source.get("objectives") if isinstance(source, dict) else None
        if isinstance(objectives, list):
            candidates.extend(
                obj
                for obj in objectives
                if isinstance(obj, dict) and obj.get("status") in {"active", "queued"}
            )

    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("id"), str):
            return candidate
    return {}


def model_reference(role: str, registry: dict[str, Any]) -> dict[str, Any]:
    models = registry.get("models") if isinstance(registry, dict) else {}
    entry = models.get(role) if isinstance(models, dict) else None
    if not isinstance(entry, dict):
        return {
            "role": role,
            "configured": False,
            "default_model": None,
            "profile_ref": None,
        }
    return {
        "role": role,
        "configured": entry.get("default_model") is not None or role == "coding_agent",
        "default_model": entry.get("default_model"),
        "profile_ref": entry.get("role"),
        "allowed_task_types": entry.get("allowed_task_types", []),
        "registry_write_access": bool(entry.get("write_access")),
    }


def assignment(
    *,
    role: str,
    task_type: str,
    project_id: str,
    objective: dict[str, Any],
    registry: dict[str, Any],
    write_capable: bool,
    rationale: str,
) -> dict[str, Any]:
    return {
        "assignment_id": f"{role}_{task_type}",
        "project_id": project_id,
        "objective_id": objective.get("id"),
        "role": role,
        "task_type": task_type,
        "permission": {
            "read_only": not write_capable,
            "write_capable": write_capable,
            "execution_enabled": False,
            "model_calls_enabled": False,
            "openhands_execution_enabled": False,
            "source_writes_enabled": False,
            "auto_merge_enabled": False,
            "auto_push_enabled": False,
            "permission_expansion_allowed": False,
        },
        "model_reference": model_reference(role, registry),
        "rationale": rationale,
    }


def build_assignments(project_id: str, objective: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, Any]]:
    objective_write_capable = objective.get("write_capable") is True
    assignments: list[dict[str, Any]] = []
    for role in ("long_reasoning", "instruct", "vision"):
        for task_type in ROLE_PURPOSES[role]:
            assignments.append(
                assignment(
                    role=role,
                    task_type=task_type,
                    project_id=project_id,
                    objective=objective,
                    registry=registry,
                    write_capable=False,
                    rationale=f"{role} is metadata-only and read-only for {task_type}.",
                )
            )

    assignments.append(
        assignment(
            role="coding_agent",
            task_type="isolated_worktree_code_edits_only",
            project_id=project_id,
            objective=objective,
            registry=registry,
            write_capable=objective_write_capable,
            rationale=(
                "coding_agent is the only role allowed to be write-capable in metadata; execution remains disabled."
                if objective_write_capable
                else "Selected objective is not write-capable; coding_agent is represented as blocked metadata only."
            ),
        )
    )

    models = registry.get("models") if isinstance(registry, dict) else {}
    if isinstance(models, dict) and "embedding" in models:
        for task_type in ROLE_PURPOSES["embedding"]:
            assignments.append(
                assignment(
                    role="embedding",
                    task_type=task_type,
                    project_id=project_id,
                    objective=objective,
                    registry=registry,
                    write_capable=False,
                    rationale="embedding is read-only retrieval/indexing support and only included because it is configured.",
                )
            )
    return assignments


def validate_assignment_safety(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    write_capable = [item for item in assignments if item.get("permission", {}).get("write_capable") is True]
    checks.append(
        {
            "id": "max_one_write_capable_assignment",
            "status": "pass" if len(write_capable) <= 1 else "fail",
            "details": {"write_capable_assignment_count": len(write_capable)},
        }
    )
    checks.append(
        {
            "id": "only_coding_agent_write_capable",
            "status": "pass" if all(item.get("role") == "coding_agent" for item in write_capable) else "fail",
            "details": {"write_capable_roles": [item.get("role") for item in write_capable]},
        }
    )
    non_coding_write = [
        item
        for item in assignments
        if item.get("role") in READ_ONLY_ROLES and item.get("permission", {}).get("write_capable") is True
    ]
    checks.append(
        {
            "id": "non_coding_roles_read_only",
            "status": "pass" if not non_coding_write else "fail",
            "details": {"violations": [item.get("assignment_id") for item in non_coding_write]},
        }
    )
    execution_violations = [
        item
        for item in assignments
        if any(
            item.get("permission", {}).get(key) is True
            for key in (
                "execution_enabled",
                "model_calls_enabled",
                "openhands_execution_enabled",
                "source_writes_enabled",
                "auto_merge_enabled",
                "auto_push_enabled",
                "permission_expansion_allowed",
            )
        )
    ]
    checks.append(
        {
            "id": "no_execution_or_permission_expansion",
            "status": "pass" if not execution_violations else "fail",
            "details": {"violations": [item.get("assignment_id") for item in execution_violations]},
        }
    )
    return checks


def build_plan(
    *,
    project_id: str,
    created_utc: str,
    run_dir: Path,
    project: dict[str, Any],
    weekly_plan: dict[str, Any],
    backlog: dict[str, Any],
    registry: dict[str, Any],
    routing_rules: str,
    latest: dict[str, Any],
    latest_presence: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    objective = selected_objective(weekly_plan, backlog, latest)
    assignments = build_assignments(project_id, objective, registry)
    safety_checks = validate_assignment_safety(assignments)
    phase_aligned = objective.get("id") == "phase15_multi_model_routing"
    status = "pass" if phase_aligned and all(check["status"] == "pass" for check in safety_checks) else "warn"

    safety = {
        "no_model_calls": True,
        "no_openhands_execution": True,
        "target_project_source_modified": False,
        "no_source_writes": True,
        "no_auto_merge": True,
        "no_auto_push": True,
        "no_permission_expansion": True,
        "coding_agent_execution_enabled": False,
        "deterministic_validation_authority_preserved": True,
    }
    artifacts_read = {
        "projects_config": str(ROOT / "configs" / "projects.json"),
        "model_registry": str(ROOT / "configs" / "model_registry.json"),
        "routing_rules": str(ROOT / "configs" / "routing_rules.md"),
        "weekly_plan": str(project_state_dir(project) / "WEEKLY_PLAN.json"),
        "objective_backlog": str(project_state_dir(project) / "OBJECTIVE_BACKLOG.json"),
    }
    artifacts_read.update({name: str(path) for name, path in latest_artifact_paths(project_id).items() if path.exists()})

    assignment_report = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": "pass" if all(check["status"] == "pass" for check in safety_checks) else "fail",
        "generated_by": GENERATED_BY,
        "assignments": assignments,
        "safety_checks": safety_checks,
    }
    plan = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": status,
        "generated_by": GENERATED_BY,
        "selected_objective": objective,
        "role_scaffold": ROLE_PURPOSES,
        "model_registry_schema_version": registry.get("schema_version") if isinstance(registry, dict) else None,
        "routing_rules_excerpt": "\n".join(routing_rules.splitlines()[:12]),
        "latest_artifact_presence": latest_presence,
        "task_model_assignments_path": str(run_dir / "TASK_MODEL_ASSIGNMENTS.json"),
        "safety": safety,
        "safety_checks": safety_checks,
        "artifacts_read": artifacts_read,
    }
    summary = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": status,
        "generated_by": GENERATED_BY,
        "selected_objective_id": objective.get("id"),
        "assignment_count": len(assignments),
        "write_capable_assignment_count": sum(
            1 for item in assignments if item.get("permission", {}).get("write_capable") is True
        ),
        "roles": sorted({item["role"] for item in assignments}),
        "safety": safety,
        "safety_checks": safety_checks,
        "deterministic_validation_authority_preserved": True,
    }
    return plan, assignment_report, summary


def build_markdown_plan(plan: dict[str, Any], assignments: dict[str, Any]) -> str:
    lines = [
        "# Model Routing Plan",
        "",
        f"Project: {plan['project_id']}",
        f"Created UTC: {plan['created_utc']}",
        f"Status: {plan['status'].upper()}",
        f"Generated by: {plan['generated_by']}",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(plan["safety"].items()):
        lines.append(f"- {key}: {str(value).lower()}")
    lines.extend(["", "## Assignments", ""])
    for item in assignments["assignments"]:
        permission = item["permission"]
        lines.append(
            f"- {item['assignment_id']}: role={item['role']}, task={item['task_type']}, "
            f"write_capable={str(permission['write_capable']).lower()}, execution_enabled=false"
        )
    lines.extend(["", "## Artifacts Read", ""])
    for name, path in sorted(plan["artifacts_read"].items()):
        lines.append(f"- {name}: {path}")
    lines.append("")
    return "\n".join(lines)


def build_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Model Routing Summary",
        "",
        f"Project: {summary['project_id']}",
        f"Created UTC: {summary['created_utc']}",
        f"Status: {summary['status'].upper()}",
        f"Selected objective: {summary.get('selected_objective_id') or 'n/a'}",
        f"Assignments: {summary['assignment_count']}",
        f"Write-capable assignments: {summary['write_capable_assignment_count']}",
        "",
        "## Roles",
        "",
    ]
    for role in summary["roles"]:
        lines.append(f"- {role}")
    lines.extend(["", "## Safety Checks", ""])
    for check in summary["safety_checks"]:
        lines.append(f"- {check['status'].upper()}: {check['id']}")
    lines.append("")
    return "\n".join(lines)


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_model_routing"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def generate(project_id: str, created_utc: str | None = None) -> dict[str, Any]:
    created = created_utc or utc_now()
    project = load_project(project_id)
    state_dir = project_state_dir(project)
    weekly_plan = load_json(state_dir / "WEEKLY_PLAN.json")
    backlog = load_json(state_dir / "OBJECTIVE_BACKLOG.json")
    registry = load_json(ROOT / "configs" / "model_registry.json")
    routing_rules = (ROOT / "configs" / "routing_rules.md").read_text()
    latest, latest_presence = load_optional_json(latest_artifact_paths(project_id))
    run_dir = ROOT / "runs" / project_id / f"model_routing_{created}"

    plan, assignments, summary = build_plan(
        project_id=project_id,
        created_utc=created,
        run_dir=run_dir,
        project=project,
        weekly_plan=weekly_plan,
        backlog=backlog,
        registry=registry,
        routing_rules=routing_rules,
        latest=latest,
        latest_presence=latest_presence,
    )
    write_json(run_dir / "MODEL_ROUTING_PLAN.json", plan)
    (run_dir / "MODEL_ROUTING_PLAN.md").write_text(build_markdown_plan(plan, assignments))
    write_json(run_dir / "TASK_MODEL_ASSIGNMENTS.json", assignments)
    write_json(run_dir / "MODEL_ROUTING_SUMMARY.json", summary)
    (run_dir / "MODEL_ROUTING_SUMMARY.md").write_text(build_markdown_summary(summary))
    update_latest_symlink(run_dir, project_id)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile deterministic model-role routing metadata.")
    parser.add_argument("project_id")
    args = parser.parse_args()

    summary = generate(args.project_id)
    print(f"Model routing plan complete for {args.project_id}")
    print(f"Run dir: {summary['run_dir']}")
    print(f"Status: {summary['status']}")
    if any(check["status"] == "fail" for check in summary["safety_checks"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
