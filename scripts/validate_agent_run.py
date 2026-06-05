#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class CheckRecorder:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(
        self,
        check_id: str,
        status: str,
        message: str,
        *,
        path: Path | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "id": check_id,
            "status": status,
            "message": message,
        }
        if path is not None:
            item["path"] = str(path)
        if details:
            item["details"] = details
        self.checks.append(item)

    def pass_check(self, check_id: str, message: str, *, path: Path | None = None, details: dict[str, Any] | None = None) -> None:
        self.add(check_id, "pass", message, path=path, details=details)

    def fail_check(self, check_id: str, message: str, *, path: Path | None = None, details: dict[str, Any] | None = None) -> None:
        self.add(check_id, "fail", message, path=path, details=details)

    def status(self) -> str:
        return "fail" if any(check["status"] == "fail" for check in self.checks) else "pass"

    def failures(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if check["status"] == "fail"]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def load_json_file(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, "missing file"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except OSError as exc:
        return None, f"could not read file: {exc}"


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def validate_json_artifact(
    recorder: CheckRecorder,
    check_id: str,
    path: Path,
    *,
    required_status: str | None = None,
    clean_required: bool = False,
) -> Any | None:
    data, err = load_json_file(path)
    if err:
        recorder.fail_check(check_id, f"{path.name} did not parse: {err}", path=path)
        return None

    recorder.pass_check(check_id, f"{path.name} parses as JSON", path=path)

    if required_status is not None:
        status = data.get("status") if isinstance(data, dict) else None
        if status == required_status:
            recorder.pass_check(f"{check_id}_status", f"{path.name} status is {required_status}", path=path)
        else:
            recorder.fail_check(
                f"{check_id}_status",
                f"{path.name} status must be {required_status}; found {status!r}",
                path=path,
            )

    if clean_required:
        clean = data.get("clean") if isinstance(data, dict) else None
        if clean is True:
            recorder.pass_check(f"{check_id}_clean", f"{path.name} clean is true", path=path)
        else:
            recorder.fail_check(
                f"{check_id}_clean",
                f"{path.name} clean must be true; found {clean!r}",
                path=path,
            )

    return data


def validate_text_artifact(recorder: CheckRecorder, check_id: str, path: Path) -> None:
    try:
        path.read_text()
    except FileNotFoundError:
        recorder.fail_check(check_id, f"{path.name} is missing", path=path)
    except OSError as exc:
        recorder.fail_check(check_id, f"{path.name} could not be read: {exc}", path=path)
    else:
        recorder.pass_check(check_id, f"{path.name} is readable", path=path)


def validate_latest_dir(recorder: CheckRecorder, check_id: str, path: Path) -> Path | None:
    if not path.exists():
        recorder.fail_check(check_id, f"latest artifact pointer is missing: {path}", path=path)
        return None
    if not path.is_dir():
        recorder.fail_check(check_id, f"latest artifact pointer is not a directory: {path}", path=path)
        return None
    resolved = path.resolve()
    recorder.pass_check(check_id, f"latest artifact directory exists: {resolved}", path=path)
    return resolved


def load_project(project_id: str, recorder: CheckRecorder) -> dict[str, Any] | None:
    config_path = ROOT / "configs" / "projects.json"
    data, err = load_json_file(config_path)
    if err:
        recorder.fail_check("projects_config_parse", f"configs/projects.json did not parse: {err}", path=config_path)
        return None

    recorder.pass_check("projects_config_parse", "configs/projects.json parses", path=config_path)
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        recorder.fail_check("projects_config_shape", "configs/projects.json must contain a projects object", path=config_path)
        return None

    project = data["projects"].get(project_id)
    if not isinstance(project, dict):
        recorder.fail_check("project_config_exists", f"unknown project id: {project_id}", path=config_path)
        return None

    recorder.pass_check("project_config_exists", f"project id {project_id!r} exists", path=config_path)
    return project


def validate_target_repo(project: dict[str, Any], recorder: CheckRecorder) -> Path | None:
    repo_raw = project.get("repo_path")
    if not isinstance(repo_raw, str) or not repo_raw:
        recorder.fail_check("target_repo_config", "project repo_path must be a non-empty string")
        return None

    repo = Path(repo_raw)
    if not repo.exists():
        recorder.fail_check("target_repo_exists", f"target repo does not exist: {repo}", path=repo)
        return None
    recorder.pass_check("target_repo_exists", f"target repo exists: {repo}", path=repo)

    git_dir = repo / ".git"
    git_check = run(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if git_check.returncode != 0 or git_check.stdout.strip() != "true":
        recorder.fail_check(
            "target_repo_git",
            f"target repo is not a git work tree: {git_check.stderr.strip() or git_check.stdout.strip()}",
            path=repo,
        )
    else:
        recorder.pass_check("target_repo_git", "target repo is a git work tree", path=git_dir)

    status = run(["git", "status", "--short"], repo)
    if status.returncode != 0:
        recorder.fail_check(
            "target_repo_clean",
            f"could not read target repo status: {status.stderr.strip() or status.stdout.strip()}",
            path=repo,
        )
    elif status.stdout.strip():
        recorder.fail_check(
            "target_repo_clean",
            "target repo must be clean; uncommitted changes were found",
            path=repo,
            details={"status_short": status.stdout.splitlines()},
        )
    else:
        recorder.pass_check("target_repo_clean", "target repo is clean", path=repo)

    return repo


def validate_project_state(repo: Path, project: dict[str, Any], recorder: CheckRecorder) -> None:
    state_dir_name = project.get("project_state_dir", ".agent_manager")
    if not isinstance(state_dir_name, str) or not state_dir_name:
        state_dir_name = ".agent_manager"

    state_dir = repo / state_dir_name
    if not state_dir.exists():
        recorder.fail_check("project_state_dir", f"project state directory is missing: {state_dir}", path=state_dir)
        return
    recorder.pass_check("project_state_dir", f"project state directory exists: {state_dir}", path=state_dir)

    validate_json_artifact(recorder, "weekly_plan_parse", state_dir / "WEEKLY_PLAN.json")
    validate_json_artifact(recorder, "objective_backlog_parse", state_dir / "OBJECTIVE_BACKLOG.json")


def validate_run_artifacts(project_id: str, recorder: CheckRecorder) -> dict[str, str]:
    run_root = ROOT / "runs" / project_id
    resolved_dirs: dict[str, str] = {}

    metrics_dir = validate_latest_dir(recorder, "latest_metrics_dir", run_root / "latest")
    if metrics_dir is not None:
        resolved_dirs["latest_metrics"] = str(metrics_dir)
        validate_json_artifact(recorder, "run_metrics_parse", metrics_dir / "RUN_METRICS.json")
        validate_json_artifact(recorder, "unknown_analysis_parse", metrics_dir / "UNKNOWN_ANALYSIS.json")
        validate_json_artifact(
            recorder,
            "validation_summary_parse",
            metrics_dir / "VALIDATION_SUMMARY.json",
            required_status="pass",
        )

    runner_dir = validate_latest_dir(recorder, "latest_runner_v0_dir", run_root / "latest_runner_v0")
    if runner_dir is not None:
        resolved_dirs["latest_runner_v0"] = str(runner_dir)
        validate_json_artifact(recorder, "active_objective_parse", runner_dir / "ACTIVE_OBJECTIVE.json")
        validate_json_artifact(recorder, "task_graph_parse", runner_dir / "TASK_GRAPH.json")
        validate_json_artifact(recorder, "run_manifest_parse", runner_dir / "RUN_MANIFEST.json", required_status="pass")
        validate_text_artifact(recorder, "morning_report_readable", runner_dir / "MORNING_REPORT.md")

    manager_dir = validate_latest_dir(recorder, "latest_manager_plan_dir", run_root / "latest_manager_plan")
    if manager_dir is not None:
        resolved_dirs["latest_manager_plan"] = str(manager_dir)
        validate_json_artifact(recorder, "manager_context_parse", manager_dir / "MANAGER_CONTEXT.json")
        validate_json_artifact(
            recorder,
            "manager_decision_parse",
            manager_dir / "MANAGER_DECISION.json",
            required_status="pass",
        )
        validate_text_artifact(recorder, "manager_plan_readable", manager_dir / "MANAGER_PLAN.md")
        validate_text_artifact(recorder, "next_action_readable", manager_dir / "NEXT_ACTION.md")

    coder_dir = validate_latest_dir(recorder, "latest_coder_worktree_dir", run_root / "latest_coder_worktree")
    if coder_dir is not None:
        resolved_dirs["latest_coder_worktree"] = str(coder_dir)
        validate_json_artifact(recorder, "coder_task_packet_parse", coder_dir / "CODER_TASK_PACKET.json")
        validate_json_artifact(
            recorder,
            "worktree_status_parse",
            coder_dir / "WORKTREE_STATUS.json",
            clean_required=True,
        )
        validate_text_artifact(recorder, "coder_prompt_readable", coder_dir / "CODER_PROMPT.md")
        validate_text_artifact(recorder, "openhands_dry_run_commands_readable", coder_dir / "OPENHANDS_DRY_RUN_COMMANDS.md")

    return resolved_dirs


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 10 Validation Report",
        "",
        f"Project: {report['project_id']}",
        f"Created UTC: {report['created_utc']}",
        f"Status: {report['status'].upper()}",
        "",
        "## Safety",
        "",
        "- No OpenHands execution: true",
        "- No model calls: true",
        "- No LangGraph runtime: true",
        "- Target project source modified: false",
        "",
        "## Checks",
        "",
    ]

    for check in report["checks"]:
        marker = "PASS" if check["status"] == "pass" else "FAIL"
        lines.append(f"- {marker}: {check['id']} - {check['message']}")
        if check.get("path"):
            lines.append(f"  Path: {check['path']}")

    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        for failure in report["failures"]:
            lines.append(f"- {failure['id']}: {failure['message']}")
            if failure.get("details"):
                lines.append(f"  Details: {json.dumps(failure['details'], sort_keys=True)}")

    lines.extend([
        "",
        "## Artifact Sources",
        "",
    ])
    for name, path in sorted(report["artifact_sources"].items()):
        lines.append(f"- {name}: {path}")

    lines.append("")
    return "\n".join(lines)


def update_latest_validation(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_validation"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate deterministic agent-manager run artifacts.")
    parser.add_argument("project_id")
    args = parser.parse_args()

    created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / args.project_id / f"validation_{created_utc}"
    recorder = CheckRecorder()

    project = load_project(args.project_id, recorder)
    repo: Path | None = None
    if project is not None:
        repo = validate_target_repo(project, recorder)
    if repo is not None and project is not None:
        validate_project_state(repo, project, recorder)

    artifact_sources = validate_run_artifacts(args.project_id, recorder)

    report = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": recorder.status(),
        "checks": recorder.checks,
        "failures": recorder.failures(),
        "artifact_sources": artifact_sources,
        "safety": {
            "no_openhands_execution": True,
            "no_model_calls": True,
            "no_langgraph_runtime": True,
            "target_project_source_modified": False,
        },
    }

    write_json(run_dir / "VALIDATION_REPORT.json", report)
    (run_dir / "VALIDATION_REPORT.md").write_text(build_markdown_report(report))
    update_latest_validation(run_dir, args.project_id)

    print(f"Phase 10 validation complete for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Status: {report['status']}")
    if report["failures"]:
        print("Failures:")
        for failure in report["failures"]:
            print(f"  - {failure['id']}: {failure['message']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
