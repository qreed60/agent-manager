#!/usr/bin/env python3
"""Phase 20: first real overnight write-capable OpenHands run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase20_first_overnight_write_capable_run"
REQUEST_GENERATED_BY = "phase18k_manager_to_openhands_task_packet_bridge"
DEFAULT_ENV_FILE = Path.home() / ".config" / "agent-manager" / "env.local"
MAX_WRITE_TASKS = 1
MAX_RETRIES_PER_TASK = 1
CONSUMED_FILE = "OVERNIGHT_OPENHANDS_REQUEST_CONSUMED.json"

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_project(project_id: str) -> dict[str, Any]:
    data = load_json(ROOT / "configs" / "projects.json")
    project = data.get("projects", {}).get(project_id)
    if not isinstance(project, dict):
        raise SystemExit(f"unknown project id: {project_id}")
    return project


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git_status_clean(repo: Path) -> bool:
    result = subprocess.run(["git", "status", "--short"], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0 and not result.stdout.strip()


def resolve_request_dir(arg_value: str | None) -> Path | None:
    raw = arg_value or os.environ.get("AGENT_MANAGER_OVERNIGHT_OPENHANDS_REQUEST_DIR")
    return Path(raw).expanduser().resolve() if raw else None


def latest_openhands_coder_run_dir(project_id: str) -> Path | None:
    pointer = ROOT / "runs" / project_id / "latest_openhands_coder"
    if pointer.exists() or pointer.is_symlink():
        resolved = pointer.resolve()
        if resolved.is_dir():
            return resolved
    run_root = ROOT / "runs" / project_id
    if not run_root.exists():
        return None
    candidates = [path for path in run_root.iterdir() if path.is_dir() and path.name.startswith("openhands_coder_")]
    return max(candidates, key=lambda path: path.name) if candidates else None


def path_is_unsafe(path: str) -> bool:
    return not path or Path(path).is_absolute() or ".." in Path(path).parts


def load_request(request_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = request_dir / "OPENHANDS_MANUAL_GATE_REQUEST.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None, "missing OPENHANDS_MANUAL_GATE_REQUEST.json"
    except json.JSONDecodeError as exc:
        return None, f"invalid request JSON: line {exc.lineno}: {exc.msg}"
    except OSError as exc:
        return None, f"could not read request: {exc}"
    return (data if isinstance(data, dict) else None), None if isinstance(data, dict) else "request JSON must be an object"


def validate_hard_gates(
    *,
    project_id: str,
    allow_overnight_openhands: bool,
    confirm_project: str | None,
    request_dir: Path | None,
    request: dict[str, Any] | None,
    request_load_error: str | None,
    canonical_clean_before: bool,
) -> list[str]:
    failures: list[str] = []
    if not allow_overnight_openhands:
        failures.append("--allow-overnight-openhands is required")
    if confirm_project != project_id:
        failures.append(f"--confirm-project must exactly match {project_id}")
    if os.environ.get("AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS") != "1":
        failures.append("AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS=1 is required")
    if os.environ.get("AGENT_MANAGER_ENABLE_OPENHANDS") != "1":
        failures.append("AGENT_MANAGER_ENABLE_OPENHANDS=1 is required")
    if os.environ.get("AGENT_MANAGER_OVERNIGHT_OPENHANDS_CONFIRM_PROJECT") != project_id:
        failures.append(f"AGENT_MANAGER_OVERNIGHT_OPENHANDS_CONFIRM_PROJECT must exactly match {project_id}")
    if request_dir is None:
        failures.append("--request-dir or AGENT_MANAGER_OVERNIGHT_OPENHANDS_REQUEST_DIR is required")
    elif (request_dir / CONSUMED_FILE).exists():
        failures.append("request has already been consumed")
    if not canonical_clean_before:
        failures.append("canonical repo is dirty before execution")
    if request_load_error:
        failures.append(request_load_error)
    if request:
        if request.get("generated_by") != REQUEST_GENERATED_BY:
            failures.append("request generated_by is not phase18k_manager_to_openhands_task_packet_bridge")
        if request.get("project_id") != project_id:
            failures.append("request project_id mismatch")
        if request.get("risk_level") != "low":
            failures.append("Phase 20 only accepts low risk requests")
        if request.get("status") == "fail":
            failures.append("request status is fail")
        if request.get("no_openhands_execution_performed") is not True:
            failures.append("request no_openhands_execution_performed must be true")
        if request.get("no_apply_commit_push_merge_pr_or_cleanup_performed") is not True:
            failures.append("request no_apply_commit_push_merge_pr_or_cleanup_performed must be true")
        allowed = request.get("allowed_files")
        if not isinstance(allowed, list) or not allowed:
            failures.append("request allowed_files must be non-empty")
        else:
            for item in allowed:
                if not isinstance(item, str) or path_is_unsafe(item):
                    failures.append(f"unsafe allowed file: {item!r}")
                    break
    return failures


def build_manual_gate_command(
    *,
    project_id: str,
    request: dict[str, Any],
    timeout_seconds: int,
    max_prompt_chars: int,
    env_file: str,
) -> list[str]:
    command = ["python3", "scripts/run_openhands_manual_gate.py", project_id]
    if request.get("task_source") == "task_file":
        command.extend(["--task-file", str(request.get("task_file", ""))])
    else:
        command.extend(["--task-text", str(request.get("task_text", ""))])
    for path in request.get("allowed_files", []):
        command.extend(["--allowed-file", str(path)])
    command.extend(
        [
            "--allow-openhands",
            "--timeout-seconds",
            str(timeout_seconds),
            "--max-prompt-chars",
            str(max_prompt_chars),
            "--env-file",
            env_file,
        ]
    )
    return command


def consume_request(request_dir: Path, *, request_sha256: str, project_id: str, nightly_run_dir: Path) -> None:
    write_json(
        request_dir / CONSUMED_FILE,
        {
            "schema_version": 1,
            "request_sha256": request_sha256,
            "consumed_utc": utc_now(),
            "project_id": project_id,
            "nightly_run_dir": str(nightly_run_dir),
            "status": "consumed",
        },
    )


def attempt_from_summary(attempt_number: int, summary: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "attempt_number": attempt_number,
        "run_dir": str(run_dir),
        "status": summary.get("status", "fail"),
        "failure_classification": summary.get("failure_classification", "unknown"),
        "retryable": bool(summary.get("retryable")),
        "changed_files": summary.get("changed_files", []),
        "decision_recommendation": summary.get("decision_recommendation"),
        "apply_check_passed": summary.get("apply_check_passed"),
        "applied": bool(summary.get("applied")),
        "canonical_repo_clean": bool(summary.get("canonical_repo_clean")),
    }


def run_attempt(
    *,
    attempt_number: int,
    project_id: str,
    request: dict[str, Any],
    timeout_seconds: int,
    max_prompt_chars: int,
    env_file: str,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    command = build_manual_gate_command(
        project_id=project_id,
        request=request,
        timeout_seconds=timeout_seconds,
        max_prompt_chars=max_prompt_chars,
        env_file=env_file,
    )
    command_runner(command)
    run_dir = latest_openhands_coder_run_dir(project_id)
    if run_dir is None:
        return {
            "attempt_number": attempt_number,
            "run_dir": "",
            "status": "fail",
            "failure_classification": "missing_required_artifact",
            "retryable": False,
            "changed_files": [],
            "decision_recommendation": None,
            "apply_check_passed": None,
            "applied": False,
            "canonical_repo_clean": False,
        }
    summary_path = run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json"
    try:
        summary = json.loads(summary_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        summary = {"status": "fail", "failure_classification": "missing_required_artifact", "retryable": False}
    return attempt_from_summary(attempt_number, summary if isinstance(summary, dict) else {}, run_dir)


def summary_status_from_attempts(attempts: list[dict[str, Any]]) -> tuple[str, bool, str, str]:
    if attempts and attempts[-1].get("status") == "pass":
        return "pass", False, "", "Review the OpenHands worktree, decision packet, and check-only apply result."
    if attempts:
        reason = str(attempts[-1].get("failure_classification") or "unknown")
    else:
        reason = "no execution attempt completed"
    return "blocked", True, reason, "Human should inspect the request, OpenHands run artifacts, and decide whether to prepare a new request."


def build_morning_report(summary: dict[str, Any], validation_result: str = "not run", review_findings: str = "not run") -> str:
    lines = [
        "# Overnight OpenHands Morning Report",
        "",
        f"Project: {summary['project_id']}",
        f"Selected objective: {summary.get('objective_id') or 'n/a'}",
        f"Status: {summary['status']}",
        "",
        "## OpenHands Result",
        "",
        f"- OpenHands run dir: {summary.get('selected_attempt_run_dir') or 'not run'}",
        f"- Changed files: {json.dumps(summary.get('changed_files', []))}",
        f"- Decision packet recommendation: {summary.get('decision_recommendation') or 'missing'}",
        f"- Apply check result: {summary.get('apply_check_passed')}",
        f"- Validation result: {validation_result}",
        f"- Review findings: {review_findings}",
        f"- Recommended human action: {summary.get('recommended_human_action') or 'missing'}",
        f"- Canonical repo clean after: {summary.get('canonical_repo_clean_after')}",
        "",
        "## Safety",
        "",
        "- No apply/commit/push/merge/PR/cleanup performed: true",
        "",
    ]
    return "\n".join(lines)


def build_summary_md(summary: dict[str, Any]) -> str:
    return build_morning_report(summary)


def write_summary(run_dir: Path, summary: dict[str, Any]) -> None:
    write_json(run_dir / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json", summary)
    (run_dir / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.md").write_text(build_summary_md(summary))
    (run_dir / "OVERNIGHT_OPENHANDS_MORNING_REPORT.md").write_text(build_morning_report(summary))


def run_overnight_write(
    project_id: str,
    *,
    request_dir_arg: str | None,
    allow_overnight_openhands: bool,
    confirm_project: str | None,
    timeout_seconds: int = 300,
    max_prompt_chars: int = 3000,
    env_file: str | None = None,
    nightly_run_dir: str | None = None,
    created_utc: str | None = None,
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    created = created_utc or utc_now()
    project = load_project(project_id)
    canonical_repo = Path(str(project["repo_path"])).expanduser().resolve()
    run_dir = Path(nightly_run_dir).expanduser().resolve() if nightly_run_dir else ROOT / "runs" / project_id / f"overnight_openhands_write_{created}"
    run_dir.mkdir(parents=True, exist_ok=True)
    request_dir = resolve_request_dir(request_dir_arg)
    request, request_error = load_request(request_dir) if request_dir else (None, None)
    request_path = request_dir / "OPENHANDS_MANUAL_GATE_REQUEST.json" if request_dir else None
    request_sha = sha256_file(request_path) if request_path and request_path.exists() else ""
    canonical_clean_before = git_status_clean(canonical_repo)
    env_file_value = env_file or os.environ.get("AGENT_MANAGER_OPENHANDS_ENV_FILE") or str(DEFAULT_ENV_FILE)
    failures = validate_hard_gates(
        project_id=project_id,
        allow_overnight_openhands=allow_overnight_openhands,
        confirm_project=confirm_project,
        request_dir=request_dir,
        request=request,
        request_load_error=request_error,
        canonical_clean_before=canonical_clean_before,
    )

    allowed_files = request.get("allowed_files", []) if isinstance(request, dict) else []
    expected_changed = request.get("expected_changed_files", []) if isinstance(request, dict) else []
    objective_id = request.get("objective_id", "") if isinstance(request, dict) else ""
    risk_level = request.get("risk_level", "") if isinstance(request, dict) else ""
    attempts: list[dict[str, Any]] = []

    if failures:
        summary = build_summary(
            project_id=project_id,
            created_utc=created,
            request_dir=str(request_dir) if request_dir else "",
            run_dir=str(run_dir),
            request_sha=request_sha,
            objective_id=str(objective_id or ""),
            risk_level=str(risk_level or ""),
            allowed_files=allowed_files if isinstance(allowed_files, list) else [],
            expected_changed_files=expected_changed if isinstance(expected_changed, list) else [],
            attempts=attempts,
            canonical_clean_before=canonical_clean_before,
            canonical_clean_after=git_status_clean(canonical_repo),
            status="fail",
            blocked=False,
            blocked_reason="; ".join(failures),
            recommended_human_action="Fix Phase 20 hard gate failures before retrying.",
        )
        write_summary(run_dir, summary)
        return summary

    assert request_dir is not None
    assert request is not None
    consume_request(request_dir, request_sha256=request_sha, project_id=project_id, nightly_run_dir=run_dir)
    first = run_attempt(
        attempt_number=1,
        project_id=project_id,
        request=request,
        timeout_seconds=timeout_seconds,
        max_prompt_chars=max_prompt_chars,
        env_file=env_file_value,
        command_runner=command_runner,
    )
    attempts.append(first)
    if first.get("status") != "pass" and first.get("retryable") is True:
        attempts.append(
            run_attempt(
                attempt_number=2,
                project_id=project_id,
                request=request,
                timeout_seconds=timeout_seconds,
                max_prompt_chars=max_prompt_chars,
                env_file=env_file_value,
                command_runner=command_runner,
            )
        )

    status, blocked, blocked_reason, human_action = summary_status_from_attempts(attempts)
    summary = build_summary(
        project_id=project_id,
        created_utc=created,
        request_dir=str(request_dir),
        run_dir=str(run_dir),
        request_sha=request_sha,
        objective_id=str(request.get("objective_id", "")),
        risk_level=str(request.get("risk_level", "")),
        allowed_files=list(request.get("allowed_files", [])),
        expected_changed_files=list(request.get("expected_changed_files", [])),
        attempts=attempts,
        canonical_clean_before=canonical_clean_before,
        canonical_clean_after=git_status_clean(canonical_repo),
        status=status,
        blocked=blocked,
        blocked_reason=blocked_reason,
        recommended_human_action=human_action,
    )
    write_summary(run_dir, summary)
    return summary


def build_summary(
    *,
    project_id: str,
    created_utc: str,
    request_dir: str,
    run_dir: str,
    request_sha: str,
    objective_id: str,
    risk_level: str,
    allowed_files: list[Any],
    expected_changed_files: list[Any],
    attempts: list[dict[str, Any]],
    canonical_clean_before: bool,
    canonical_clean_after: bool,
    status: str,
    blocked: bool,
    blocked_reason: str,
    recommended_human_action: str,
) -> dict[str, Any]:
    selected = attempts[-1] if attempts else {}
    return {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": run_dir,
        "request_dir": request_dir,
        "request_sha256": request_sha,
        "objective_id": objective_id,
        "risk_level": risk_level,
        "allowed_files": allowed_files,
        "expected_changed_files": expected_changed_files,
        "max_write_tasks": MAX_WRITE_TASKS,
        "max_retries_per_task": MAX_RETRIES_PER_TASK,
        "attempts": attempts,
        "selected_attempt_run_dir": selected.get("run_dir", ""),
        "selected_attempt_status": selected.get("status"),
        "changed_files": selected.get("changed_files", []),
        "decision_recommendation": selected.get("decision_recommendation"),
        "apply_mode": "check_only" if attempts else None,
        "apply_check_passed": selected.get("apply_check_passed"),
        "applied": bool(selected.get("applied", False)),
        "canonical_repo_clean_before": canonical_clean_before,
        "canonical_repo_clean_after": canonical_clean_after,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "recommended_human_action": recommended_human_action,
        "status": status,
        "no_apply_commit_push_merge_pr_or_cleanup_performed": True,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one gated overnight OpenHands write task.")
    parser.add_argument("project_id")
    parser.add_argument("--request-dir", default=None)
    parser.add_argument("--allow-overnight-openhands", action="store_true")
    parser.add_argument("--confirm-project", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-prompt-chars", type=int, default=3000)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--nightly-run-dir", default=None)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    summary = run_overnight_write(
        args.project_id,
        request_dir_arg=args.request_dir,
        allow_overnight_openhands=args.allow_overnight_openhands,
        confirm_project=args.confirm_project,
        timeout_seconds=args.timeout_seconds,
        max_prompt_chars=args.max_prompt_chars,
        env_file=args.env_file,
        nightly_run_dir=args.nightly_run_dir,
    )
    print(f"Overnight OpenHands write status: {summary['status']}")
    print(f"Run dir: {args.nightly_run_dir or summary.get('selected_attempt_run_dir') or summary['request_dir']}")
    if summary["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
