#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "deterministic_nightly_window_scaffold"
DEFAULT_POLICY = {
    "schema_version": 1,
    "nightly_start": "23:00",
    "no_new_work_cutoff": "05:30",
    "hard_stop": "06:00",
    "max_manager_passes": 3,
    "max_code_writing_tasks": 0,
    "future_max_code_writing_tasks": 1,
    "max_retries_per_task": 1,
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


def load_policy() -> dict[str, Any]:
    path = ROOT / "configs" / "nightly_window_policy.json"
    try:
        policy = load_json(path)
    except FileNotFoundError:
        policy = dict(DEFAULT_POLICY)
    merged = dict(DEFAULT_POLICY)
    if isinstance(policy, dict):
        merged.update(policy)
    if merged["max_code_writing_tasks"] != 0:
        raise SystemExit("Phase 16 requires max_code_writing_tasks to remain 0")
    return merged


def project_state_dir(project: dict[str, Any]) -> Path:
    repo_raw = project.get("repo_path")
    if not isinstance(repo_raw, str) or not repo_raw:
        raise SystemExit("project repo_path must be a non-empty string")
    state_dir_name = project.get("project_state_dir", ".agent_manager")
    if not isinstance(state_dir_name, str) or not state_dir_name:
        state_dir_name = ".agent_manager"
    return Path(repo_raw) / state_dir_name


def selected_objective(weekly_plan: dict[str, Any], backlog: dict[str, Any]) -> dict[str, Any]:
    for source in (weekly_plan, backlog):
        objectives = source.get("objectives") if isinstance(source, dict) else None
        if isinstance(objectives, list):
            for item in objectives:
                if isinstance(item, dict) and item.get("status") in {"active", "queued"}:
                    return item
    return {}


def parse_hhmm(value: str) -> int:
    hours_text, minutes_text = value.split(":", 1)
    hours = int(hours_text)
    minutes = int(minutes_text)
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        raise ValueError(f"invalid HH:MM time: {value}")
    return hours * 60 + minutes


def time_in_window(now_minute: int, start_minute: int, hard_stop_minute: int) -> bool:
    if start_minute <= hard_stop_minute:
        return start_minute <= now_minute < hard_stop_minute
    return now_minute >= start_minute or now_minute < hard_stop_minute


def at_or_after_hard_stop(now_hhmm: str, policy: dict[str, Any]) -> bool:
    now_minute = parse_hhmm(now_hhmm)
    start_minute = parse_hhmm(str(policy["nightly_start"]))
    hard_stop_minute = parse_hhmm(str(policy["hard_stop"]))
    if start_minute <= hard_stop_minute:
        return now_minute >= hard_stop_minute
    return hard_stop_minute <= now_minute < start_minute


def before_no_new_work_cutoff(now_hhmm: str, policy: dict[str, Any]) -> bool:
    now_minute = parse_hhmm(now_hhmm)
    start_minute = parse_hhmm(str(policy["nightly_start"]))
    cutoff_minute = parse_hhmm(str(policy["no_new_work_cutoff"]))
    hard_stop_minute = parse_hhmm(str(policy["hard_stop"]))
    if not time_in_window(now_minute, start_minute, hard_stop_minute):
        return False
    if start_minute <= cutoff_minute:
        return now_minute < cutoff_minute
    return now_minute >= start_minute or now_minute < cutoff_minute


def can_start_new_pass(now_hhmm: str, policy: dict[str, Any], pass_count: int) -> bool:
    return (
        pass_count < int(policy["max_manager_passes"])
        and not at_or_after_hard_stop(now_hhmm, policy)
        and before_no_new_work_cutoff(now_hhmm, policy)
        and int(policy["max_code_writing_tasks"]) == 0
    )


def latest_artifact(project_id: str, name: str) -> Path:
    return ROOT / "runs" / project_id / name


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        data = load_json(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def summarize_latest_artifacts(project_id: str) -> dict[str, Any]:
    validation = load_optional_json(latest_artifact(project_id, "latest_validation") / "VALIDATION_REPORT.json")
    review = load_optional_json(latest_artifact(project_id, "latest_review_agents") / "REVIEW_AGENTS_SUMMARY.json")
    model_routing = load_optional_json(latest_artifact(project_id, "latest_model_routing") / "MODEL_ROUTING_SUMMARY.json")
    langgraph = load_optional_json(latest_artifact(project_id, "latest_langgraph_v0") / "LANGGRAPH_RUN_MANIFEST.json")
    return {
        "validation_status": validation.get("status"),
        "review_status": review.get("status"),
        "model_routing_status": model_routing.get("status"),
        "langgraph_status": langgraph.get("status"),
        "validation_run_dir": validation.get("run_dir"),
        "review_run_dir": review.get("run_dir"),
        "model_routing_run_dir": model_routing.get("run_dir"),
        "langgraph_run_dir": langgraph.get("run_dir"),
    }


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_langgraph_pass(project_id: str, pass_index: int, command_runner: CommandRunner) -> dict[str, Any]:
    started = utc_now()
    command = ["python3", "scripts/run_langgraph_v0.py", project_id]
    result = command_runner(command)
    completed = utc_now()
    status = "pass" if result.returncode == 0 else "fail"
    return {
        "pass_index": pass_index,
        "started_utc": started,
        "completed_utc": completed,
        "decision": "run_langgraph_v0",
        "command": command,
        "returncode": result.returncode,
        "artifacts": {
            "latest_langgraph_v0": str(latest_artifact(project_id, "latest_langgraph_v0").resolve()),
            "latest_validation": str(latest_artifact(project_id, "latest_validation").resolve()),
            "latest_review_agents": str(latest_artifact(project_id, "latest_review_agents").resolve()),
            "latest_model_routing": str(latest_artifact(project_id, "latest_model_routing").resolve()),
        },
        "status": status,
    }


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_nightly_window"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def build_safety_status(project_id: str, created_utc: str, run_dir: Path, policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": "pass",
        "model_calls_allowed": False,
        "openhands_allowed": False,
        "source_writes_allowed": False,
        "auto_merge_allowed": False,
        "auto_push_allowed": False,
        "permission_expansion_allowed": False,
        "max_code_writing_tasks": policy["max_code_writing_tasks"],
        "deterministic_validation_authority_preserved": True,
    }


def build_manifest(
    *,
    project_id: str,
    created_utc: str,
    run_dir: Path,
    objective: dict[str, Any],
    policy: dict[str, Any],
    timeline: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "selected_objective_id": objective.get("id"),
        "policy": policy,
        "pass_count": len(timeline),
        "max_manager_passes": policy["max_manager_passes"],
        "max_code_writing_tasks": policy["max_code_writing_tasks"],
        "model_calls_allowed": False,
        "openhands_allowed": False,
        "source_writes_allowed": False,
        "auto_merge_allowed": False,
        "auto_push_allowed": False,
        "status": status,
        "generated_by": GENERATED_BY,
    }


def build_pass_summary(
    project_id: str,
    created_utc: str,
    run_dir: Path,
    timeline: list[dict[str, Any]],
    latest_summary: dict[str, Any],
) -> dict[str, Any]:
    failed = [item for item in timeline if item["status"] != "pass"]
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": "pass" if not failed else "fail",
        "pass_count": len(timeline),
        "failed_pass_count": len(failed),
        "passes": timeline,
        "latest_artifact_summary": latest_summary,
    }


def build_timeline(project_id: str, created_utc: str, run_dir: Path, timeline: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "passes": timeline,
    }


def build_handoff(
    *,
    project_id: str,
    created_utc: str,
    objective: dict[str, Any],
    policy: dict[str, Any],
    pass_summary: dict[str, Any],
    latest_summary: dict[str, Any],
    safety_status: dict[str, Any],
) -> str:
    recommendation = "accept" if pass_summary["status"] == "pass" and safety_status["status"] == "pass" else "review"
    next_action = "Review latest validation and model routing artifacts before starting new work."
    lines = [
        "# Morning Handoff",
        "",
        f"Project: {project_id}",
        f"Created UTC: {created_utc}",
        "",
        "## Objective",
        "",
        f"- ID: {objective.get('id', 'n/a')}",
        f"- Title: {objective.get('title', objective.get('description', 'n/a'))}",
        "",
        "## Window Policy",
        "",
        f"- Nightly start: {policy['nightly_start']}",
        f"- No new work cutoff: {policy['no_new_work_cutoff']}",
        f"- Hard stop: {policy['hard_stop']}",
        f"- Max manager passes: {policy['max_manager_passes']}",
        f"- Max code-writing tasks: {policy['max_code_writing_tasks']}",
        f"- Future max code-writing tasks: {policy['future_max_code_writing_tasks']}",
        f"- Max retries per task: {policy['max_retries_per_task']}",
        "",
        "## Pass Summary",
        "",
        f"- Pass count: {pass_summary['pass_count']}",
        f"- Failed passes: {pass_summary['failed_pass_count']}",
        f"- Status: {pass_summary['status']}",
        "",
        "## Validation Status",
        "",
        f"- Status: {latest_summary.get('validation_status') or 'missing'}",
        "",
        "## Review Summary",
        "",
        f"- Status: {latest_summary.get('review_status') or 'missing'}",
        "",
        "## Model Routing Summary",
        "",
        f"- Status: {latest_summary.get('model_routing_status') or 'missing'}",
        "",
        "## Safety Status",
        "",
    ]
    for key, value in sorted(safety_status.items()):
        if key in {"schema_version", "project_id", "created_utc", "run_dir"}:
            continue
        lines.append(f"- {key}: {str(value).lower() if isinstance(value, bool) else value}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            recommendation,
            "",
            "## Next Action",
            "",
            next_action,
            "",
        ]
    )
    return "\n".join(lines)


def run_window(
    project_id: str,
    *,
    created_utc: str | None = None,
    quick_passes: int = 1,
    window_mode: str = "quick",
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    project = load_project(project_id)
    state_dir = project_state_dir(project)
    weekly_plan = load_json(state_dir / "WEEKLY_PLAN.json")
    backlog = load_json(state_dir / "OBJECTIVE_BACKLOG.json")
    objective = selected_objective(weekly_plan, backlog)
    policy = load_policy()
    created = created_utc or utc_now()
    run_dir = ROOT / "runs" / project_id / f"nightly_window_{created}"
    run_dir.mkdir(parents=True, exist_ok=True)

    timeline: list[dict[str, Any]] = []
    requested_passes = min(quick_passes, int(policy["max_manager_passes"]))
    status = "pass"
    for index in range(1, requested_passes + 1):
        now_hhmm = str(policy["nightly_start"]) if window_mode == "quick" else datetime.now().strftime("%H:%M")
        if not can_start_new_pass(now_hhmm, policy, len(timeline)):
            break
        entry = run_langgraph_pass(project_id, index, command_runner)
        timeline.append(entry)
        if entry["status"] != "pass":
            status = "fail"
            break

    latest_summary = summarize_latest_artifacts(project_id)
    pass_summary = build_pass_summary(project_id, created, run_dir, timeline, latest_summary)
    if pass_summary["status"] == "fail":
        status = "fail"
    safety_status = build_safety_status(project_id, created, run_dir, policy)
    manifest = build_manifest(
        project_id=project_id,
        created_utc=created,
        run_dir=run_dir,
        objective=objective,
        policy=policy,
        timeline=timeline,
        status=status,
    )
    timeline_report = build_timeline(project_id, created, run_dir, timeline)
    handoff = build_handoff(
        project_id=project_id,
        created_utc=created,
        objective=objective,
        policy=policy,
        pass_summary=pass_summary,
        latest_summary=latest_summary,
        safety_status=safety_status,
    )

    write_json(run_dir / "NIGHTLY_WINDOW_MANIFEST.json", manifest)
    write_json(run_dir / "NIGHTLY_WINDOW_TIMELINE.json", timeline_report)
    write_json(run_dir / "NIGHTLY_PASS_SUMMARY.json", pass_summary)
    write_json(run_dir / "NIGHTLY_SAFETY_STATUS.json", safety_status)
    (run_dir / "MORNING_HANDOFF.md").write_text(handoff)
    update_latest_symlink(run_dir, project_id)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic time-boxed nightly LangGraph window.")
    parser.add_argument("project_id")
    parser.add_argument("--window-mode", choices=["quick", "real-time"], default="quick")
    parser.add_argument("--quick-passes", type=int, default=1)
    args = parser.parse_args()

    manifest = run_window(args.project_id, window_mode=args.window_mode, quick_passes=args.quick_passes)
    print(f"Nightly window complete for {args.project_id}")
    print(f"Run dir: {manifest['run_dir']}")
    print(f"Passes: {manifest['pass_count']}")
    print(f"Status: {manifest['status']}")
    if manifest["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
