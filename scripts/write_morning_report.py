#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def fail(msg: str) -> None:
    raise SystemExit(f"write_morning_report failed: {msg}")


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"missing JSON artifact: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except OSError as exc:
        fail(f"could not read JSON {path}: {exc}")


def load_text(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        fail(f"missing text artifact: {path}")
    except OSError as exc:
        fail(f"could not read text artifact {path}: {exc}")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def load_project(project_id: str) -> dict[str, Any]:
    config_path = ROOT / "configs" / "projects.json"
    data = load_json(config_path)
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        fail(f"configs/projects.json must contain a projects object: {config_path}")

    project = data["projects"].get(project_id)
    if not isinstance(project, dict):
        fail(f"unknown project_id: {project_id}")
    return project


def git_value(repo: Path, args: list[str]) -> str:
    result = run(["git", *args], repo)
    return result.stdout.strip() if result.returncode == 0 else ""


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_morning_report"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def find_objective(backlog: dict[str, Any], objective_id: str | None) -> dict[str, Any] | None:
    objectives = backlog.get("objectives", [])
    if not isinstance(objectives, list):
        return None
    if objective_id:
        for objective in objectives:
            if isinstance(objective, dict) and objective.get("id") == objective_id:
                return objective
    candidates = [
        objective
        for objective in objectives
        if isinstance(objective, dict)
        and objective.get("status") in {"active", "queued"}
        and objective.get("write_capable") is not True
    ]
    candidates.sort(key=lambda item: item.get("priority", 999))
    return candidates[0] if candidates else None


def status_of(data: Any) -> str | None:
    return data.get("status") if isinstance(data, dict) and isinstance(data.get("status"), str) else None


def list_from(data: Any, key: str) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return []
    return [str(item) for item in data[key]]


def select_recommendation(
    validation_summary: dict[str, Any],
    runner_manifest: dict[str, Any],
    manager_decision: dict[str, Any],
    worktree_status: dict[str, Any],
    validation_report: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []

    if worktree_status.get("clean") is not True:
        return "hold", ["Coder worktree status is not clean."]

    required_passes = {
        "latest validation summary": status_of(validation_summary),
        "runner manifest": status_of(runner_manifest),
        "manager decision": status_of(manager_decision),
        "latest validation report": status_of(validation_report),
    }
    failures = [f"{name} status is {value!r}" for name, value in required_passes.items() if value != "pass"]
    if failures:
        return "revise", failures

    reasons.extend(
        [
            "Latest validation summary passed.",
            "Runner manifest passed.",
            "Manager decision passed.",
            "Latest validation report passed.",
            "Coder worktree is clean.",
        ]
    )
    return "accept", reasons


def build_project_state_proposal(
    project_id: str,
    created_utc: str,
    weekly_plan: dict[str, Any],
    backlog: dict[str, Any],
    objective: dict[str, Any] | None,
    recommendation: str,
    validation_report: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    proposed_weekly_plan = deepcopy(weekly_plan)
    proposed_backlog = deepcopy(backlog)
    objective_id = objective.get("id") if isinstance(objective, dict) else None
    validation_status = status_of(validation_report)
    updated_date = datetime.strptime(created_utc, "%Y%m%dT%H%M%SZ").date().isoformat()

    changes: list[dict[str, Any]] = []
    next_objective_id = f"review_{objective_id}" if objective_id else "review_latest_morning_report"
    next_objective = {
        "id": next_objective_id,
        "title": f"Review morning report for {objective_id}" if objective_id else "Review latest morning report",
        "phase": "Morning report follow-up",
        "priority": 1,
        "status": "queued",
        "risk_level": "low",
        "write_capable": False,
        "description": "Review the central morning report and apply the proposed project-state update only after approval.",
    }

    if recommendation == "accept":
        proposed_weekly_plan["current_phase"] = "Phase 11: morning report ready for review"
        proposed_weekly_plan["primary_goal"] = "Review deterministic morning report and decide whether to apply project-state changes."
        proposed_weekly_plan["updated_date"] = updated_date
        weekly_objectives = proposed_weekly_plan.get("objectives", [])
        if isinstance(weekly_objectives, list):
            for item in weekly_objectives:
                if isinstance(item, dict) and item.get("id") == objective_id:
                    item["status"] = "complete"
                    item["completed_utc"] = created_utc
                    break
            if not any(isinstance(item, dict) and item.get("id") == next_objective["id"] for item in weekly_objectives):
                weekly_objectives.append(
                    {
                        "id": next_objective["id"],
                        "priority": next_objective["priority"],
                        "status": next_objective["status"],
                        "description": next_objective["description"],
                        "success_metric": "Project-state changes are applied only after explicit approval.",
                        "write_capable": next_objective["write_capable"],
                    }
                )
        changes.extend(
            [
                {
                    "file": ".agent_manager/WEEKLY_PLAN.json",
                    "operation": "replace_fields",
                    "fields": {
                        "current_phase": proposed_weekly_plan["current_phase"],
                        "primary_goal": proposed_weekly_plan["primary_goal"],
                        "updated_date": proposed_weekly_plan["updated_date"],
                    },
                }
            ]
        )
        if isinstance(weekly_objectives, list):
            changes.append(
                {
                    "file": ".agent_manager/WEEKLY_PLAN.json",
                    "operation": "update_objectives",
                    "objective_id": objective_id,
                }
            )

        objectives = proposed_backlog.setdefault("objectives", [])
        if isinstance(objectives, list):
            for item in objectives:
                if isinstance(item, dict) and item.get("id") == objective_id:
                    item["status"] = "complete"
                    item["completed_utc"] = created_utc
                    changes.append(
                        {
                            "file": ".agent_manager/OBJECTIVE_BACKLOG.json",
                            "operation": "mark_objective_complete",
                            "objective_id": objective_id,
                        }
                    )
                    break
            if not any(isinstance(item, dict) and item.get("id") == next_objective["id"] for item in objectives):
                objectives.append(next_objective)
                changes.append(
                    {
                        "file": ".agent_manager/OBJECTIVE_BACKLOG.json",
                        "operation": "append_objective",
                        "objective_id": next_objective["id"],
                    }
                )
    else:
        changes.append(
            {
                "file": ".agent_manager/WEEKLY_PLAN.json",
                "operation": "no_change",
                "reason": f"Recommendation is {recommendation}.",
            }
        )

    history_entry = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "source": "write_morning_report.py",
        "morning_report_dir": str(run_dir),
        "objective_id": objective_id,
        "recommendation": recommendation,
        "validation_status": validation_status,
    }
    plan_revision_entry = (
        f"\n## {created_utc} - Phase 11 morning report\n\n"
        f"- Recommendation: {recommendation}\n"
        f"- Objective: {objective_id or 'n/a'}\n"
        f"- Validation status: {validation_status or 'unknown'}\n"
        f"- Central report: {run_dir}\n"
    )
    changes.extend(
        [
            {
                "file": ".agent_manager/VALIDATION_HISTORY.jsonl",
                "operation": "append_jsonl",
                "entry": history_entry,
            },
            {
                "file": ".agent_manager/PLAN_REVISIONS.md",
                "operation": "append_markdown",
                "entry": plan_revision_entry.strip(),
            },
        ]
    )

    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "mode": "proposal_only",
        "recommendation": recommendation,
        "objective_id": objective_id,
        "changes": changes,
        "proposed_files": {
            ".agent_manager/WEEKLY_PLAN.json": proposed_weekly_plan,
            ".agent_manager/OBJECTIVE_BACKLOG.json": proposed_backlog,
            ".agent_manager/VALIDATION_HISTORY.jsonl": history_entry,
            ".agent_manager/PLAN_REVISIONS.md": plan_revision_entry,
        },
        "apply_safety": {
            "default_applies_project_state": False,
            "apply_requires_flag": "--apply-project-state",
            "allowed_files": [
                ".agent_manager/WEEKLY_PLAN.json",
                ".agent_manager/OBJECTIVE_BACKLOG.json",
                ".agent_manager/VALIDATION_HISTORY.jsonl",
                ".agent_manager/PLAN_REVISIONS.md",
            ],
        },
    }


def assert_allowed_project_state_path(state_dir: Path, path: Path) -> None:
    allowed = {
        (state_dir / "WEEKLY_PLAN.json").resolve(),
        (state_dir / "OBJECTIVE_BACKLOG.json").resolve(),
        (state_dir / "VALIDATION_HISTORY.jsonl").resolve(),
        (state_dir / "PLAN_REVISIONS.md").resolve(),
    }
    resolved = path.resolve()
    if resolved not in allowed:
        fail(f"refusing to edit disallowed project-state path: {path}")


def apply_project_state(state_dir: Path, proposal: dict[str, Any]) -> list[str]:
    proposed_files = proposal.get("proposed_files")
    if not isinstance(proposed_files, dict):
        fail("proposal has no proposed_files object")

    written: list[str] = []
    weekly_plan_path = state_dir / "WEEKLY_PLAN.json"
    backlog_path = state_dir / "OBJECTIVE_BACKLOG.json"
    history_path = state_dir / "VALIDATION_HISTORY.jsonl"
    revisions_path = state_dir / "PLAN_REVISIONS.md"

    for path in [weekly_plan_path, backlog_path, history_path, revisions_path]:
        assert_allowed_project_state_path(state_dir, path)

    write_json(weekly_plan_path, proposed_files[".agent_manager/WEEKLY_PLAN.json"])
    written.append(str(weekly_plan_path))
    write_json(backlog_path, proposed_files[".agent_manager/OBJECTIVE_BACKLOG.json"])
    written.append(str(backlog_path))
    history_existing = history_path.read_text() if history_path.exists() else ""
    history_line = json.dumps(proposed_files[".agent_manager/VALIDATION_HISTORY.jsonl"], sort_keys=True) + "\n"
    history_path.write_text(history_existing + history_line)
    written.append(str(history_path))
    revisions_existing = revisions_path.read_text() if revisions_path.exists() else ""
    revision_entry = proposed_files[".agent_manager/PLAN_REVISIONS.md"]
    revisions_path.write_text(revisions_existing + revision_entry if revisions_existing else revision_entry.lstrip())
    written.append(str(revisions_path))
    return written


def build_markdown_report(report: dict[str, Any], proposal: dict[str, Any], next_objective_md: str) -> str:
    objective = report["objective"]
    reviewed = report["artifacts_reviewed"]
    repo = report["target_repo"]
    files_changed = report["files_changed"]

    lines = [
        "# Morning Report",
        "",
        f"Project: {report['project_id']}",
        f"Created UTC: {report['created_utc']}",
        "Mode: deterministic central-artifact-only",
        "",
        "## Objective",
        "",
        f"- ID: {objective.get('id', 'n/a')}",
        f"- Title: {objective.get('title', objective.get('description', 'n/a'))}",
        f"- Phase: {objective.get('phase', 'n/a')}",
        f"- Status: {objective.get('status', 'n/a')}",
        f"- Write-capable: {objective.get('write_capable', 'n/a')}",
        "",
        "## Why Selected",
        "",
    ]
    for reason in report["why_selected"]:
        lines.append(f"- {reason}")

    lines.extend(["", "## Artifacts Reviewed", ""])
    for name, path in reviewed.items():
        lines.append(f"- {name}: {path}")

    lines.extend(
        [
            "",
            "## Validation Result",
            "",
            f"- Latest validation summary: {report['validation_result']['summary_status']}",
            f"- Latest validation report: {report['validation_result']['report_status']}",
            f"- Failure count: {report['validation_result']['failure_count']}",
            "",
            "## Safety Status",
            "",
        ]
    )
    for key, value in sorted(report["safety_status"].items()):
        lines.append(f"- {key}: {str(value).lower()}")

    lines.extend(
        [
            "",
            "## Worktree Status",
            "",
            f"- Target repo: {repo['path']}",
            f"- Branch: {repo['branch'] or 'unknown'}",
            f"- HEAD: {repo['head'] or 'unknown'}",
            f"- Target repo status entries: {len(repo['status_short'])}",
            f"- Coder worktree clean: {str(report['worktree_status'].get('clean')).lower()}",
            "",
            "## Files Changed",
            "",
        ]
    )
    if files_changed:
        for item in files_changed:
            lines.append(f"- {item}")
    else:
        lines.append("- None reported.")

    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            report["recommendation"],
            "",
        ]
    )
    for reason in report["recommendation_reasons"]:
        lines.append(f"- {reason}")

    lines.extend(["", "## Proposed Weekly Plan Changes", ""])
    for change in proposal["changes"]:
        lines.append(f"- {change['file']}: {change['operation']}")
        if change.get("objective_id"):
            lines.append(f"  Objective: {change['objective_id']}")
        if change.get("reason"):
            lines.append(f"  Reason: {change['reason']}")

    lines.extend(["", "## Next Suggested Objective", "", next_objective_md.strip(), ""])
    return "\n".join(lines)


def build_next_objective_markdown(proposal: dict[str, Any]) -> str:
    proposed_backlog = proposal["proposed_files"][".agent_manager/OBJECTIVE_BACKLOG.json"]
    objectives = proposed_backlog.get("objectives", []) if isinstance(proposed_backlog, dict) else []
    queued = [
        item
        for item in objectives
        if isinstance(item, dict)
        and item.get("status") in {"queued", "active"}
        and item.get("write_capable") is not True
    ]
    queued.sort(key=lambda item: item.get("priority", 999))
    if not queued:
        return "No queued non-write objective is currently proposed."
    selected = queued[0]
    return (
        f"- ID: {selected.get('id')}\n"
        f"- Title: {selected.get('title', selected.get('description', 'n/a'))}\n"
        f"- Phase: {selected.get('phase', 'n/a')}\n"
        f"- Priority: {selected.get('priority', 'n/a')}\n"
        f"- Write-capable: {selected.get('write_capable')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Write deterministic morning report and project-state update proposal.")
    parser.add_argument("project_id")
    parser.add_argument("--apply-project-state", action="store_true")
    args = parser.parse_args()

    project = load_project(args.project_id)
    repo = Path(project.get("repo_path", ""))
    if not repo.exists():
        fail(f"missing target repo: {repo}")

    state_dir_name = project.get("project_state_dir", ".agent_manager")
    if not isinstance(state_dir_name, str) or not state_dir_name:
        state_dir_name = ".agent_manager"
    state_dir = repo / state_dir_name
    if not state_dir.exists():
        fail(f"missing project state dir: {state_dir}")

    created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = ROOT / "runs" / args.project_id
    run_dir = run_root / f"morning_report_{created_utc}"
    run_dir.mkdir(parents=True, exist_ok=True)

    weekly_plan = load_json(state_dir / "WEEKLY_PLAN.json")
    backlog = load_json(state_dir / "OBJECTIVE_BACKLOG.json")

    artifacts = {
        "weekly_plan": state_dir / "WEEKLY_PLAN.json",
        "objective_backlog": state_dir / "OBJECTIVE_BACKLOG.json",
        "run_metrics": run_root / "latest" / "RUN_METRICS.json",
        "validation_summary": run_root / "latest" / "VALIDATION_SUMMARY.json",
        "runner_manifest": run_root / "latest_runner_v0" / "RUN_MANIFEST.json",
        "runner_morning_report": run_root / "latest_runner_v0" / "MORNING_REPORT.md",
        "manager_decision": run_root / "latest_manager_plan" / "MANAGER_DECISION.json",
        "manager_plan": run_root / "latest_manager_plan" / "MANAGER_PLAN.md",
        "coder_task_packet": run_root / "latest_coder_worktree" / "CODER_TASK_PACKET.json",
        "worktree_status": run_root / "latest_coder_worktree" / "WORKTREE_STATUS.json",
        "validation_report_json": run_root / "latest_validation" / "VALIDATION_REPORT.json",
        "validation_report_md": run_root / "latest_validation" / "VALIDATION_REPORT.md",
    }

    run_metrics = load_json(artifacts["run_metrics"])
    validation_summary = load_json(artifacts["validation_summary"])
    runner_manifest = load_json(artifacts["runner_manifest"])
    runner_morning_report = load_text(artifacts["runner_morning_report"])
    manager_decision = load_json(artifacts["manager_decision"])
    manager_plan = load_text(artifacts["manager_plan"])
    coder_task_packet = load_json(artifacts["coder_task_packet"])
    worktree_status = load_json(artifacts["worktree_status"])
    validation_report_json = load_json(artifacts["validation_report_json"])
    validation_report_md = load_text(artifacts["validation_report_md"])

    selected_objective_id = (
        manager_decision.get("selected_objective_id")
        or runner_manifest.get("selected_objective_id")
        or (coder_task_packet.get("objective") or {}).get("id")
    )
    objective = find_objective(backlog, selected_objective_id) or manager_decision.get("selected_objective") or {}
    if not isinstance(objective, dict):
        objective = {}

    recommendation, recommendation_reasons = select_recommendation(
        validation_summary,
        runner_manifest,
        manager_decision,
        worktree_status,
        validation_report_json,
    )

    proposal = build_project_state_proposal(
        args.project_id,
        created_utc,
        weekly_plan,
        backlog,
        objective,
        recommendation,
        validation_report_json,
        run_dir,
    )

    next_objective_md = build_next_objective_markdown(proposal)
    why_selected = []
    rationale = manager_decision.get("rationale") if isinstance(manager_decision, dict) else None
    if isinstance(rationale, list) and rationale:
        why_selected = [str(item) for item in rationale]
    else:
        why_selected = [
            "Selected from latest deterministic manager decision or active project backlog.",
            "Objective is active or queued.",
            "Objective is not write-capable.",
        ]

    target_status = git_value(repo, ["status", "--short"]).splitlines()
    files_changed = sorted(set(target_status + list_from(worktree_status, "status_short") + list_from(worktree_status, "source_repo_status")))

    report = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "mode": "deterministic_central_artifact_only",
        "apply_project_state": args.apply_project_state,
        "objective": objective,
        "why_selected": why_selected,
        "artifacts_reviewed": {name: str(path) for name, path in artifacts.items()},
        "artifact_summaries": {
            "run_metrics_counts": run_metrics.get("counts", {}) if isinstance(run_metrics, dict) else {},
            "runner_morning_report_bytes": len(runner_morning_report.encode()),
            "manager_plan_bytes": len(manager_plan.encode()),
            "validation_report_md_bytes": len(validation_report_md.encode()),
        },
        "validation_result": {
            "summary_status": status_of(validation_summary),
            "report_status": status_of(validation_report_json),
            "failure_count": len(validation_report_json.get("failures", [])) if isinstance(validation_report_json, dict) else None,
        },
        "safety_status": {
            "no_openhands_execution": True,
            "no_model_calls": True,
            "no_langgraph_execution": True,
            "target_repo_modified_by_default": False,
            "source_behavior_modified": False,
            "auto_merge": False,
            "auto_push": False,
        },
        "target_repo": {
            "path": str(repo),
            "branch": git_value(repo, ["branch", "--show-current"]),
            "head": git_value(repo, ["rev-parse", "--short", "HEAD"]),
            "status_short": target_status,
        },
        "worktree_status": worktree_status,
        "files_changed": files_changed,
        "recommendation": recommendation,
        "recommendation_reasons": recommendation_reasons,
        "plan_update_proposal": str(run_dir / "PLAN_UPDATE_PROPOSAL.json"),
        "next_objective_recommendation": str(run_dir / "NEXT_OBJECTIVE_RECOMMENDATION.md"),
        "status": "pass",
    }

    applied_files: list[str] = []
    if args.apply_project_state:
        applied_files = apply_project_state(state_dir, proposal)
        report["applied_project_state_files"] = applied_files

    write_json(run_dir / "MORNING_REPORT.json", report)
    write_json(run_dir / "PLAN_UPDATE_PROPOSAL.json", proposal)
    (run_dir / "NEXT_OBJECTIVE_RECOMMENDATION.md").write_text("# Next Objective Recommendation\n\n" + next_objective_md.strip() + "\n")
    (run_dir / "MORNING_REPORT.md").write_text(build_markdown_report(report, proposal, next_objective_md))
    update_latest_symlink(run_dir, args.project_id)

    print(f"Morning report complete for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Recommendation: {recommendation}")
    print(f"Applied project state: {str(args.apply_project_state).lower()}")
    if applied_files:
        print("Applied files:")
        for path in applied_files:
            print(f"  - {path}")


if __name__ == "__main__":
    main()
