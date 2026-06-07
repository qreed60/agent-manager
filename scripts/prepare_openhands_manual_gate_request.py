#!/usr/bin/env python3
"""Phase 18K: manager-to-OpenHands manual gate request bridge.

This script only prepares a validated request packet and human-run command for
scripts/run_openhands_manual_gate.py. It does not run OpenHands and does not call
the manual gate runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase18k_manager_to_openhands_task_packet_bridge"
RISK_LEVELS = {"low", "medium", "high"}
UNSAFE_COMMAND_PATTERNS = (
    " --apply",
    "--allow-canonical-write",
    "git apply",
    "git commit",
    "git push",
    "git merge",
    "gh pr",
    "hub pull-request",
    "worktree remove",
    "branch -D",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def load_project(project_id: str) -> dict[str, Any]:
    data = load_json(ROOT / "configs" / "projects.json")
    project = data.get("projects", {}).get(project_id)
    if not isinstance(project, dict):
        raise SystemExit(f"unknown project id: {project_id}")
    return project


def project_state_dir(project: dict[str, Any]) -> Path:
    repo_path = project.get("repo_path")
    if not isinstance(repo_path, str) or not repo_path:
        raise SystemExit("project repo_path must be a non-empty string")
    state_dir = project.get("project_state_dir", ".agent_manager")
    if not isinstance(state_dir, str) or not state_dir:
        state_dir = ".agent_manager"
    return Path(repo_path).expanduser() / state_dir


def select_objective_id(project: dict[str, Any], explicit_objective_id: str | None) -> tuple[str, str]:
    if explicit_objective_id:
        return explicit_objective_id, "cli"
    backlog_path = project_state_dir(project) / "OBJECTIVE_BACKLOG.json"
    try:
        backlog = load_json(backlog_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "", "none"
    objectives = backlog.get("objectives") if isinstance(backlog, dict) else []
    if not isinstance(objectives, list):
        return "", "none"
    for item in objectives:
        if isinstance(item, dict) and item.get("status") in {"active", "queued"}:
            objective_id = item.get("id")
            if isinstance(objective_id, str):
                return objective_id, "active_objective"
    return "", "none"


def read_task_source(task_text: str | None, task_file: str | None) -> tuple[str | None, str, str]:
    if task_text is not None:
        return None, "task_text", task_text
    if task_file is not None:
        path = Path(task_file).expanduser()
        try:
            text = path.read_text()
        except (FileNotFoundError, OSError):
            text = ""
        return str(path), "task_file", text
    return None, "", ""


def validate_request_inputs(
    *,
    task_text_arg: str | None,
    task_file_arg: str | None,
    task_text: str,
    allowed_files: list[str],
    expected_changed_files: list[str],
    validation_commands: list[str],
    stop_conditions: list[str],
    risk_level: str,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    source_count = sum(1 for value in (task_text_arg, task_file_arg) if value is not None)
    if source_count != 1:
        failures.append("exactly one of --task-text or --task-file is required")
    if task_file_arg is not None and not Path(task_file_arg).expanduser().exists():
        failures.append(f"task_file does not exist: {task_file_arg}")
    if not task_text.strip():
        failures.append("task text is empty")
    if not allowed_files:
        failures.append("at least one --allowed-file is required")
    for path in allowed_files:
        parts = Path(path).parts
        if Path(path).is_absolute():
            failures.append(f"allowed file must be relative: {path}")
        if ".." in parts:
            failures.append(f"allowed file must not contain parent traversal: {path}")
    allowed_set = set(allowed_files)
    for path in expected_changed_files:
        if path not in allowed_set:
            failures.append(f"expected changed file is not listed as allowed: {path}")
    if risk_level == "high" and not stop_conditions:
        failures.append("high risk requests require at least one stop condition")
    if not validation_commands:
        warnings.append("validation_commands is empty")
    if risk_level in {"low", "medium"} and not stop_conditions:
        warnings.append(f"{risk_level} risk request has no stop conditions")
    return failures, warnings


def shell_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def build_manual_gate_command_parts(project_id: str, task_source: str, task_file: str, task_text: str, allowed_files: list[str]) -> list[str]:
    parts = ["python3", "scripts/run_openhands_manual_gate.py", project_id]
    if task_source == "task_file":
        parts.extend(["--task-file", task_file])
    else:
        parts.extend(["--task-text", task_text])
    for path in allowed_files:
        parts.extend(["--allowed-file", path])
    return parts


def unsafe_command_reasons(text: str) -> list[str]:
    lowered = text.lower()
    return [pattern for pattern in UNSAFE_COMMAND_PATTERNS if pattern in lowered]


def build_command_files(
    *,
    project_id: str,
    task_source: str,
    task_file: str,
    task_text: str,
    allowed_files: list[str],
    validation_commands: list[str],
) -> tuple[str, str]:
    dry_parts = build_manual_gate_command_parts(project_id, task_source, task_file, task_text, allowed_files)
    live_parts = [*dry_parts, "--allow-openhands"]
    dry_command = shell_command(dry_parts)
    live_command = f"AGENT_MANAGER_ENABLE_OPENHANDS=1 {shell_command(live_parts)}"
    validation_lines = validation_commands or ["python3 scripts/validate_agent_run.py " + shlex.quote(project_id)]

    shell_text = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "# Dry-run review command. This does not enable OpenHands.",
            dry_command,
            "",
            "# Live manual variant. Review first, then uncomment both lines together.",
            f"# {live_command}",
            "",
        ]
    )
    md_lines = [
        "# OpenHands Manual Gate Command",
        "",
        "## Dry Run",
        "",
        "```bash",
        dry_command,
        "```",
        "",
        "## Live Manual Command",
        "",
        "Requires explicit `AGENT_MANAGER_ENABLE_OPENHANDS=1` in the human shell.",
        "",
        "```bash",
        live_command,
        "```",
        "",
        "## Validation Commands",
        "",
        "```bash",
        *validation_lines,
        "```",
        "",
        "This request bridge only writes artifacts. It does not run the command.",
        "",
    ]
    return shell_text, "\n".join(md_lines)


def build_request_markdown(request: dict[str, Any]) -> str:
    lines = [
        "# OpenHands Manual Gate Request",
        "",
        f"Project: `{request['project_id']}`",
        f"Status: `{request['status']}`",
        f"Risk level: `{request['risk_level']}`",
        f"Objective: `{request.get('objective_id', '')}`",
        "",
        "## Task",
        "",
        f"Task source: `{request['task_source']}`",
        "",
        "```text",
        request["task_text"],
        "```",
        "",
        "## Allowed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in request["allowed_files"])
    lines.extend(["", "## Expected Changed Files", ""])
    lines.extend(f"- `{path}`" for path in request["expected_changed_files"])
    lines.extend(["", "## Stop Conditions", ""])
    if request["stop_conditions"]:
        lines.extend(f"- {item}" for item in request["stop_conditions"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Human Command Artifacts",
            "",
            f"- `{request['command_file']}`",
            f"- `{request['command_markdown_file']}`",
            "",
            "No OpenHands execution, apply, commit, push, merge, PR creation, or cleanup was performed.",
            "",
        ]
    )
    if request.get("refusal_reason"):
        lines.extend(["## Refusal", "", request["refusal_reason"], ""])
    return "\n".join(lines)


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_openhands_manual_gate_request"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def prepare_request(
    project_id: str,
    *,
    task_text_arg: str | None = None,
    task_file_arg: str | None = None,
    allowed_files: list[str] | None = None,
    validation_commands: list[str] | None = None,
    expected_changed_files: list[str] | None = None,
    risk_level: str = "low",
    stop_conditions: list[str] | None = None,
    objective_id_arg: str | None = None,
    output_dir: str | None = None,
    created_utc: str | None = None,
) -> dict[str, Any]:
    project = load_project(project_id)
    created = created_utc or utc_now()
    run_dir = Path(output_dir).expanduser().resolve() if output_dir else ROOT / "runs" / project_id / f"openhands_manual_gate_request_{created}"
    run_dir.mkdir(parents=True, exist_ok=True)

    allowed = unique_preserve_order(allowed_files or [])
    validation = list(validation_commands or [])
    stops = list(stop_conditions or [])
    expected = unique_preserve_order(expected_changed_files or allowed)

    task_file, task_source, task_text = read_task_source(task_text_arg, task_file_arg)
    objective_id, objective_source = select_objective_id(project, objective_id_arg)

    failures, warnings = validate_request_inputs(
        task_text_arg=task_text_arg,
        task_file_arg=task_file_arg,
        task_text=task_text,
        allowed_files=allowed,
        expected_changed_files=expected,
        validation_commands=validation,
        stop_conditions=stops,
        risk_level=risk_level,
    )
    status = "fail" if failures else ("warn" if warnings else "pass")
    refusal_reason = "; ".join(failures or warnings)

    shell_text, command_md = build_command_files(
        project_id=project_id,
        task_source=task_source or "task_text",
        task_file=task_file or "",
        task_text=task_text,
        allowed_files=allowed,
        validation_commands=validation,
    )
    unsafe_reasons = unsafe_command_reasons(shell_text)
    if unsafe_reasons:
        status = "fail"
        message = f"generated command contains unsafe command content: {', '.join(unsafe_reasons)}"
        refusal_reason = f"{refusal_reason}; {message}" if refusal_reason else message

    command_file = run_dir / "OPENHANDS_MANUAL_GATE_COMMAND.sh"
    command_markdown_file = run_dir / "OPENHANDS_MANUAL_GATE_COMMAND.md"
    command_file.write_text(shell_text)
    command_file.chmod(0o755)
    command_markdown_file.write_text(command_md)

    request = {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "project_id": project_id,
        "created_utc": created,
        "run_dir": str(run_dir),
        "objective_id": objective_id,
        "objective_source": objective_source,
        "task_source": task_source,
        "task_text": task_text,
        "task_file": task_file or "",
        "task_sha256": sha256_text(task_text),
        "allowed_files": allowed,
        "expected_changed_files": expected,
        "validation_commands": validation,
        "stop_conditions": stops,
        "risk_level": risk_level,
        "command_file": str(command_file),
        "command_markdown_file": str(command_markdown_file),
        "status": status,
        "refusal_reason": refusal_reason,
        "no_openhands_execution_performed": True,
        "no_apply_commit_push_merge_pr_or_cleanup_performed": True,
    }
    write_json(run_dir / "OPENHANDS_MANUAL_GATE_REQUEST.json", request)
    (run_dir / "OPENHANDS_MANUAL_GATE_REQUEST.md").write_text(build_request_markdown(request))
    update_latest_symlink(run_dir, project_id)
    return request


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a Phase 18K OpenHands manual gate request packet.")
    parser.add_argument("project_id")
    parser.add_argument("--task-text", default=None)
    parser.add_argument("--task-file", default=None)
    parser.add_argument("--allowed-file", action="append", default=[])
    parser.add_argument("--validation-command", action="append", default=[])
    parser.add_argument("--expected-changed-file", action="append", default=[])
    parser.add_argument("--risk-level", choices=sorted(RISK_LEVELS), default="low")
    parser.add_argument("--stop-condition", action="append", default=[])
    parser.add_argument("--objective-id", default=None)
    parser.add_argument("--output-dir", default=None)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    request = prepare_request(
        args.project_id,
        task_text_arg=args.task_text,
        task_file_arg=args.task_file,
        allowed_files=args.allowed_file,
        validation_commands=args.validation_command,
        expected_changed_files=args.expected_changed_file,
        risk_level=args.risk_level,
        stop_conditions=args.stop_condition,
        objective_id_arg=args.objective_id,
        output_dir=args.output_dir,
    )
    print(f"OpenHands manual gate request status: {request['status']}")
    print(f"Run dir: {request['run_dir']}")
    print(f"Command: {request['command_file']}")
    if request["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
