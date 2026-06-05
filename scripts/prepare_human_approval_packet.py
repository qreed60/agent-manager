#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "deterministic_human_approval_scaffold"
LATEST_ARTIFACTS = {
    "latest_nightly_window": {
        "manifest": "NIGHTLY_WINDOW_MANIFEST.json",
        "handoff": "MORNING_HANDOFF.md",
        "safety": "NIGHTLY_SAFETY_STATUS.json",
    },
    "latest_langgraph_v0": {"manifest": "LANGGRAPH_RUN_MANIFEST.json"},
    "latest_validation": {"report": "VALIDATION_REPORT.json"},
    "latest_review_agents": {"summary": "REVIEW_AGENTS_SUMMARY.json"},
    "latest_model_routing": {"summary": "MODEL_ROUTING_SUMMARY.json"},
    "latest_morning_report": {"report": "MORNING_REPORT.json"},
    "latest_runner_v0": {"active_objective": "ACTIVE_OBJECTIVE.json", "task_graph": "TASK_GRAPH.json"},
    "latest_manager_plan": {"decision": "MANAGER_DECISION.json"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def load_project(project_id: str) -> dict[str, Any]:
    data = load_json(ROOT / "configs" / "projects.json")
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


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        data = load_json(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def latest_dir(project_id: str, name: str) -> Path:
    return ROOT / "runs" / project_id / name


def load_latest_artifacts(project_id: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for latest_name, files in LATEST_ARTIFACTS.items():
        pointer = latest_dir(project_id, latest_name)
        latest[latest_name] = {
            "path": str(pointer),
            "present": pointer.exists() or pointer.is_symlink(),
            "artifacts": {},
        }
        for label, filename in files.items():
            path = pointer / filename
            latest[latest_name]["artifacts"][label] = {
                "path": str(path),
                "data": load_optional_json(path),
                "present": path.exists(),
            }
    return latest


def selected_objective(latest: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    runner_obj = (
        latest.get("latest_runner_v0", {})
        .get("artifacts", {})
        .get("active_objective", {})
        .get("data", {})
        .get("objective")
    )
    if isinstance(runner_obj, dict) and runner_obj.get("id"):
        return runner_obj
    manager_obj = (
        latest.get("latest_manager_plan", {})
        .get("artifacts", {})
        .get("decision", {})
        .get("data", {})
        .get("selected_objective")
    )
    if isinstance(manager_obj, dict) and manager_obj.get("id"):
        return manager_obj
    state_dir = project_state_dir(project)
    for filename in ("WEEKLY_PLAN.json", "OBJECTIVE_BACKLOG.json"):
        data = load_optional_json(state_dir / filename)
        objectives = data.get("objectives")
        if isinstance(objectives, list):
            for item in objectives:
                if isinstance(item, dict) and item.get("status") in {"active", "queued"}:
                    return item
    return {}


def status_from(latest: dict[str, Any], latest_name: str, artifact_label: str, key: str = "status") -> Any:
    return latest.get(latest_name, {}).get("artifacts", {}).get(artifact_label, {}).get("data", {}).get(key)


def collect_changed_files(project: dict[str, Any]) -> list[dict[str, str]]:
    repo_raw = project.get("repo_path")
    if not isinstance(repo_raw, str) or not repo_raw:
        return []
    repo = Path(repo_raw)
    try:
        result = subprocess.run(["git", "status", "--short"], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return []
    if result.returncode != 0:
        return [{"status": "unknown", "path": result.stderr.strip() or result.stdout.strip()}]
    changed = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        changed.append({"status": line[:2].strip() or "modified", "path": line[3:] if len(line) > 3 else line})
    return changed


def safety_status(latest: dict[str, Any]) -> dict[str, Any]:
    nightly_safety = (
        latest.get("latest_nightly_window", {})
        .get("artifacts", {})
        .get("safety", {})
        .get("data", {})
    )
    if not isinstance(nightly_safety, dict):
        nightly_safety = {}
    model_routing = (
        latest.get("latest_model_routing", {})
        .get("artifacts", {})
        .get("summary", {})
        .get("data", {})
        .get("safety", {})
    )
    if not isinstance(model_routing, dict):
        model_routing = {}
    max_code = nightly_safety.get("max_code_writing_tasks", model_routing.get("max_code_writing_tasks", 0))
    return {
        "model_calls_allowed": False,
        "openhands_allowed": False,
        "source_writes_allowed": False,
        "auto_merge_allowed": False,
        "auto_push_allowed": False,
        "github_pr_created": False,
        "branch_pushed": False,
        "merge_performed": False,
        "max_code_writing_tasks": max_code,
        "human_approval_required_for_future_write_capable_work": True,
    }


def recommended_decision(packet: dict[str, Any]) -> str:
    if packet["safety_status"].get("max_code_writing_tasks") != 0:
        return "hold"
    if packet.get("latest_validation_status") == "pass":
        review_status = packet.get("latest_review_agent_status")
        routing_status = packet.get("latest_model_routing_status")
        nightly_status = packet.get("nightly_window_status")
        if review_status in {"pass", "warn", None} and routing_status in {"pass", "warn", None} and nightly_status in {"pass", None}:
            return "accept"
    if packet.get("latest_validation_status") == "fail":
        return "revise"
    return "hold"


def human_decision_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "decision": "hold",
        "allowed_decisions": ["accept", "revise", "discard", "hold"],
        "reviewer": "",
        "timestamp": "",
        "notes": "",
        "approved_for_next_phase": False,
        "approved_for_source_writes": False,
        "approved_for_model_calls": False,
        "approved_for_openhands": False,
    }


def draft_pr_command(title: str, body_file: Path) -> str:
    return " ".join(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            shlex.quote(title),
            "--body-file",
            shlex.quote(str(body_file)),
        ]
    )


def build_packet(project_id: str, created_utc: str, run_dir: Path, project: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    objective = selected_objective(latest, project)
    generated_artifacts = {
        name: {
            "path": info.get("path"),
            "present": info.get("present"),
            "files": {label: artifact.get("path") for label, artifact in info.get("artifacts", {}).items() if artifact.get("present")},
        }
        for name, info in latest.items()
    }
    packet = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "generated_by": GENERATED_BY,
        "selected_objective": objective,
        "latest_validation_status": status_from(latest, "latest_validation", "report"),
        "latest_review_agent_status": status_from(latest, "latest_review_agents", "summary"),
        "latest_model_routing_status": status_from(latest, "latest_model_routing", "summary"),
        "nightly_window_status": status_from(latest, "latest_nightly_window", "manifest"),
        "safety_status": safety_status(latest),
        "generated_artifacts": generated_artifacts,
        "changed_files": collect_changed_files(project),
        "recommended_human_decision": "hold",
        "no_merge_push_or_pr_created": True,
        "explicit_non_actions": [
            "No GitHub PR was created.",
            "No branch was pushed.",
            "No merge was performed.",
            "No AI model calls were made.",
            "No OpenHands execution was started.",
            "No target project source writes were made.",
        ],
    }
    packet["recommended_human_decision"] = recommended_decision(packet)
    return packet


def build_summary(packet: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": packet["project_id"],
        "created_utc": packet["created_utc"],
        "run_dir": str(run_dir),
        "status": "pass",
        "generated_by": GENERATED_BY,
        "selected_objective_id": packet.get("selected_objective", {}).get("id"),
        "recommended_human_decision": packet["recommended_human_decision"],
        "latest_validation_status": packet.get("latest_validation_status"),
        "latest_review_agent_status": packet.get("latest_review_agent_status"),
        "latest_model_routing_status": packet.get("latest_model_routing_status"),
        "nightly_window_status": packet.get("nightly_window_status"),
        "changed_file_count": len(packet.get("changed_files", [])),
        "no_merge_push_or_pr_created": True,
        "safety_status": packet["safety_status"],
    }


def build_approval_markdown(packet: dict[str, Any]) -> str:
    objective = packet.get("selected_objective", {})
    lines = [
        "# Human Approval Packet",
        "",
        f"Project: {packet['project_id']}",
        f"Created UTC: {packet['created_utc']}",
        "",
        "## Objective",
        "",
        f"- ID: {objective.get('id', 'n/a')}",
        f"- Title: {objective.get('title', objective.get('description', 'n/a'))}",
        "",
        "## Status",
        "",
        f"- Validation: {packet.get('latest_validation_status') or 'missing'}",
        f"- Review agents: {packet.get('latest_review_agent_status') or 'missing'}",
        f"- Model routing: {packet.get('latest_model_routing_status') or 'missing'}",
        f"- Nightly window: {packet.get('nightly_window_status') or 'missing'}",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(packet["safety_status"].items()):
        lines.append(f"- {key}: {str(value).lower() if isinstance(value, bool) else value}")
    lines.extend(["", "## Changed Files", ""])
    if packet["changed_files"]:
        for item in packet["changed_files"]:
            lines.append(f"- {item['status']}: {item['path']}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Recommended Human Decision",
            "",
            packet["recommended_human_decision"],
            "",
            "## Explicit Non-actions",
            "",
        ]
    )
    for item in packet["explicit_non_actions"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def build_pr_body(packet: dict[str, Any]) -> str:
    objective = packet.get("selected_objective", {})
    return "\n".join(
        [
            "# Draft PR Body",
            "",
            "This is a generated draft body only. No PR was created by the agent-manager.",
            "",
            "## Objective",
            "",
            f"- ID: {objective.get('id', 'n/a')}",
            f"- Summary: {objective.get('description', objective.get('title', 'n/a'))}",
            "",
            "## Validation",
            "",
            f"- Status: {packet.get('latest_validation_status') or 'missing'}",
            "",
            "## Safety",
            "",
            "- No model calls were made.",
            "- No OpenHands execution was performed.",
            "- No branch was pushed.",
            "- No PR was created.",
            "- No merge was performed.",
            "",
        ]
    )


def build_draft_pr_plan(packet: dict[str, Any], pr_body_path: Path) -> str:
    objective = packet.get("selected_objective", {})
    title = f"{packet['project_id']}: {objective.get('id', 'human approval handoff')}"
    command = draft_pr_command(title, pr_body_path)
    return "\n".join(
        [
            "# Draft PR Plan",
            "",
            "No GitHub command was executed. This plan is text only.",
            "",
            "## Draft Command",
            "",
            "```bash",
            command,
            "```",
            "",
            "Before running this manually, push an approved branch yourself and confirm human approval.",
            "",
        ]
    )


def build_resume_instructions(project_id: str) -> str:
    return "\n".join(
        [
            "# Resume Instructions",
            "",
            "## Rerun Validation",
            "",
            f"```bash\npython3 scripts/validate_agent_run.py {project_id}\n```",
            "",
            "## Rerun Nightly Window",
            "",
            f"```bash\npython3 scripts/run_nightly_window.py {project_id}\n```",
            "",
            "## Inspect Logs",
            "",
            f"```bash\nscripts/check_nightly_timer.sh {project_id}\n```",
            "",
            "## Resume From Latest Artifacts",
            "",
            f"Use `runs/{project_id}/latest_*` symlinks, especially `latest_human_approval`, `latest_nightly_window`, `latest_validation`, `latest_review_agents`, and `latest_model_routing`.",
            "",
            "## Proceed After Human Approval",
            "",
            "Fill out `HUMAN_DECISION_TEMPLATE.json`. Proceed to the next phase only when `decision` is `accept` and `approved_for_next_phase` is true.",
            "",
            "Future source-write, model-call, or OpenHands phases require separate explicit approvals. This phase does not enable them.",
            "",
        ]
    )


def build_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Approval Summary",
        "",
        f"Project: {summary['project_id']}",
        f"Created UTC: {summary['created_utc']}",
        f"Status: {summary['status'].upper()}",
        f"Selected objective: {summary.get('selected_objective_id') or 'n/a'}",
        f"Recommended decision: {summary['recommended_human_decision']}",
        "",
        "## Artifact Status",
        "",
        f"- Validation: {summary.get('latest_validation_status') or 'missing'}",
        f"- Review agents: {summary.get('latest_review_agent_status') or 'missing'}",
        f"- Model routing: {summary.get('latest_model_routing_status') or 'missing'}",
        f"- Nightly window: {summary.get('nightly_window_status') or 'missing'}",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(summary["safety_status"].items()):
        lines.append(f"- {key}: {str(value).lower() if isinstance(value, bool) else value}")
    lines.append("")
    return "\n".join(lines)


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_human_approval"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def generate(project_id: str, created_utc: str | None = None) -> dict[str, Any]:
    project = load_project(project_id)
    created = created_utc or utc_now()
    run_dir = ROOT / "runs" / project_id / f"human_approval_{created}"
    latest = load_latest_artifacts(project_id)
    packet = build_packet(project_id, created, run_dir, project, latest)
    summary = build_summary(packet, run_dir)
    pr_body_path = run_dir / "PR_BODY_DRAFT.md"

    write_json(run_dir / "APPROVAL_PACKET.json", packet)
    (run_dir / "APPROVAL_PACKET.md").write_text(build_approval_markdown(packet))
    (run_dir / "PR_BODY_DRAFT.md").write_text(build_pr_body(packet))
    (run_dir / "DRAFT_PR_PLAN.md").write_text(build_draft_pr_plan(packet, pr_body_path))
    (run_dir / "RESUME_INSTRUCTIONS.md").write_text(build_resume_instructions(project_id))
    write_json(run_dir / "HUMAN_DECISION_TEMPLATE.json", human_decision_template())
    write_json(run_dir / "APPROVAL_SUMMARY.json", summary)
    (run_dir / "APPROVAL_SUMMARY.md").write_text(build_summary_markdown(summary))
    update_latest_symlink(run_dir, project_id)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare deterministic human approval and draft PR packet.")
    parser.add_argument("project_id")
    args = parser.parse_args()

    summary = generate(args.project_id)
    print(f"Human approval packet complete for {args.project_id}")
    print(f"Run dir: {summary['run_dir']}")
    print(f"Recommended decision: {summary['recommended_human_decision']}")
    print("No PR was created, no branch was pushed, and no merge was performed.")


if __name__ == "__main__":
    main()
