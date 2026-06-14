#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_ARTIFACT_POINTERS = ("latest_langgraph_v0", "latest_nightly_window")
OPENHANDS_MANUAL_GATE_FAILURE_CLASSIFICATIONS = {
    "none",
    "exited_0_no_changes",
    "misplaced_run_dir_write",
    "scope_fail",
    "apply_check_fail",
    "decision_not_accepted",
    "coder_failed",
    "canonical_repo_dirty",
    "applied_unexpectedly",
    "missing_required_artifact",
    "unknown",
}
OPENHANDS_MANUAL_GATE_REQUEST_GENERATED_BY = "phase18k_manager_to_openhands_task_packet_bridge"
OPENHANDS_MANUAL_GATE_REQUEST_UNSAFE_COMMAND_PATTERNS = (
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
OVERNIGHT_OPENHANDS_GENERATED_BY = "phase20_first_overnight_write_capable_run"


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def langgraph_safe_no_nonwrite_objective(data: Any) -> bool:
    try:
        payload = json.dumps(data)
    except TypeError:
        payload = str(data)
    if isinstance(data, dict) and data.get("status") not in {None, "fail"}:
        return False
    return "no safe non-write active/queued objective available" in payload


def validate_langgraph_status_or_safe_stop(
    recorder: CheckRecorder,
    check_id: str,
    data: Any,
    path: Path,
    context: Any | None = None,
) -> None:
    status = data.get("status") if isinstance(data, dict) else None
    if status == "pass":
        recorder.pass_check(check_id, f"{path.name} status is pass", path=path)
    elif langgraph_safe_no_nonwrite_objective(data) or langgraph_safe_no_nonwrite_objective(context):
        recorder.pass_check(
            check_id,
            f"{path.name} recorded an expected safe stop with no non-write objective available",
            path=path,
        )
    else:
        recorder.fail_check(
            check_id,
            f"{path.name} status must be pass or an expected safe no-non-write-objective stop; found {status!r}",
            path=path,
        )


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


def record_orchestrator_artifact_skip(
    recorder: CheckRecorder,
    pointer_name: str,
    pointer: Path,
    resolved_dirs: dict[str, str],
) -> None:
    if pointer.exists() or pointer.is_symlink():
        try:
            resolved = pointer.resolve()
        except OSError:
            resolved = pointer
        if resolved.is_dir():
            resolved_dirs[pointer_name] = str(resolved)
    recorder.pass_check(
        f"{pointer_name}_orchestrated_skip",
        f"{pointer_name} validation skipped in orchestrated mode to avoid validating stale or current orchestrator artifacts",
        path=pointer,
        details={"skip_reason": "orchestrated_mode"},
    )


def validate_langgraph_pointer(recorder: CheckRecorder, langgraph_pointer: Path, resolved_dirs: dict[str, str]) -> None:
    langgraph_dir = validate_latest_dir(recorder, "latest_langgraph_v0_dir", langgraph_pointer)
    if langgraph_dir is None:
        return

    resolved_dirs["latest_langgraph_v0"] = str(langgraph_dir)
    manifest = validate_json_artifact(
        recorder,
        "langgraph_manifest_parse",
        langgraph_dir / "LANGGRAPH_RUN_MANIFEST.json",
    )
    state = validate_json_artifact(
        recorder,
        "langgraph_state_final_parse",
        langgraph_dir / "LANGGRAPH_STATE_FINAL.json",
    )
    trace = validate_json_artifact(recorder, "langgraph_node_trace_parse", langgraph_dir / "LANGGRAPH_NODE_TRACE.json")
    if manifest is not None:
        validate_langgraph_status_or_safe_stop(
            recorder,
            "langgraph_manifest_status",
            manifest,
            langgraph_dir / "LANGGRAPH_RUN_MANIFEST.json",
            trace,
        )
    if state is not None:
        validate_langgraph_status_or_safe_stop(
            recorder,
            "langgraph_state_final_status",
            state,
            langgraph_dir / "LANGGRAPH_STATE_FINAL.json",
        )
    validate_text_artifact(recorder, "langgraph_report_readable", langgraph_dir / "LANGGRAPH_REPORT.md")
    legacy_nodes = [
        "load_project",
        "collect_metrics",
        "run_plain_runner_v0",
        "run_manager_planning_pass",
        "write_morning_report",
        "validate_agent_run",
        "finalize",
    ]
    expected_nodes = [
        "load_project",
        "collect_metrics",
        "run_plain_runner_v0",
        "run_manager_planning_pass",
        "write_morning_report",
        "validate_agent_run",
        "run_readonly_review_agents",
        "compile_model_routing_plan",
        "prepare_human_approval_packet",
        "finalize",
    ]
    phase15_nodes = [
        "load_project",
        "collect_metrics",
        "run_plain_runner_v0",
        "run_manager_planning_pass",
        "write_morning_report",
        "validate_agent_run",
        "run_readonly_review_agents",
        "compile_model_routing_plan",
        "finalize",
    ]
    phase13_nodes = [
        "load_project",
        "collect_metrics",
        "run_plain_runner_v0",
        "run_manager_planning_pass",
        "write_morning_report",
        "validate_agent_run",
        "run_readonly_review_agents",
        "finalize",
    ]
    trace_nodes = [item.get("node") for item in trace] if isinstance(trace, list) else []
    if trace_nodes in (expected_nodes, phase15_nodes, phase13_nodes, legacy_nodes):
        recorder.pass_check("langgraph_node_order", "LangGraph node trace has the expected deterministic order", path=langgraph_dir)
    else:
        recorder.fail_check(
            "langgraph_node_order",
            "LangGraph node trace must match the deterministic v0 node order",
            path=langgraph_dir / "LANGGRAPH_NODE_TRACE.json",
            details={
                "expected": expected_nodes,
                "phase15_allowed": phase15_nodes,
                "phase13_allowed": phase13_nodes,
                "legacy_allowed": legacy_nodes,
                "actual": trace_nodes,
            },
        )
    if isinstance(manifest, dict) and manifest.get("safety", {}).get("deterministic_validation_authority_preserved") is True:
        recorder.pass_check("langgraph_preserves_validation_authority", "LangGraph manifest preserves deterministic validation authority", path=langgraph_dir)
    else:
        recorder.fail_check(
            "langgraph_preserves_validation_authority",
            "LangGraph manifest must preserve deterministic validation authority",
            path=langgraph_dir / "LANGGRAPH_RUN_MANIFEST.json",
        )
    if isinstance(state, dict) and isinstance(state.get("artifacts"), dict):
        recorder.pass_check("langgraph_state_artifact_refs", "LangGraph final state carries artifact references", path=langgraph_dir)
    else:
        recorder.fail_check(
            "langgraph_state_artifact_refs",
            "LangGraph final state must carry artifact references",
            path=langgraph_dir / "LANGGRAPH_STATE_FINAL.json",
        )


def validate_run_artifacts(project_id: str, recorder: CheckRecorder, *, skip_orchestrator_artifacts: bool = False) -> dict[str, str]:
    run_root = ROOT / "runs" / project_id
    resolved_dirs: dict[str, str] = {}
    validate_systemd_artifacts(recorder)

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

    morning_report_dir = validate_latest_dir(recorder, "latest_morning_report_dir", run_root / "latest_morning_report")
    if morning_report_dir is not None:
        resolved_dirs["latest_morning_report"] = str(morning_report_dir)
        validate_text_artifact(recorder, "phase11_morning_report_readable", morning_report_dir / "MORNING_REPORT.md")
        validate_json_artifact(
            recorder,
            "phase11_morning_report_json_parse",
            morning_report_dir / "MORNING_REPORT.json",
            required_status="pass",
        )
        validate_json_artifact(
            recorder,
            "phase11_plan_update_proposal_parse",
            morning_report_dir / "PLAN_UPDATE_PROPOSAL.json",
        )
        validate_text_artifact(
            recorder,
            "phase11_next_objective_recommendation_readable",
            morning_report_dir / "NEXT_OBJECTIVE_RECOMMENDATION.md",
        )

    langgraph_pointer = run_root / "latest_langgraph_v0"
    if skip_orchestrator_artifacts:
        record_orchestrator_artifact_skip(recorder, "latest_langgraph_v0", langgraph_pointer, resolved_dirs)
    elif langgraph_pointer.exists() or langgraph_pointer.is_symlink():
        validate_langgraph_pointer(recorder, langgraph_pointer, resolved_dirs)
    else:
        recorder.pass_check("latest_langgraph_v0_optional", "latest_langgraph_v0 is absent; optional Phase 12 artifacts not validated", path=langgraph_pointer)

    review_pointer = run_root / "latest_review_agents"
    if review_pointer.exists() or review_pointer.is_symlink():
        review_dir = validate_latest_dir(recorder, "latest_review_agents_dir", review_pointer)
        if review_dir is not None:
            resolved_dirs["latest_review_agents"] = str(review_dir)
            validate_review_agent_artifacts(
                recorder,
                review_dir,
                allow_stale_validation_review_blocking=skip_orchestrator_artifacts,
            )
    else:
        recorder.pass_check("latest_review_agents_optional", "latest_review_agents is absent; optional Phase 13 artifacts not validated", path=review_pointer)

    model_routing_pointer = run_root / "latest_model_routing"
    if model_routing_pointer.exists() or model_routing_pointer.is_symlink():
        model_routing_dir = validate_latest_dir(recorder, "latest_model_routing_dir", model_routing_pointer)
        if model_routing_dir is not None:
            resolved_dirs["latest_model_routing"] = str(model_routing_dir)
            validate_model_routing_artifacts(recorder, model_routing_dir)
    else:
        recorder.pass_check("latest_model_routing_optional", "latest_model_routing is absent; optional Phase 15 artifacts not validated", path=model_routing_pointer)

    nightly_window_pointer = run_root / "latest_nightly_window"
    if skip_orchestrator_artifacts:
        record_orchestrator_artifact_skip(recorder, "latest_nightly_window", nightly_window_pointer, resolved_dirs)
    elif nightly_window_pointer.exists() or nightly_window_pointer.is_symlink():
        nightly_window_dir = validate_latest_dir(recorder, "latest_nightly_window_dir", nightly_window_pointer)
        if nightly_window_dir is not None:
            resolved_dirs["latest_nightly_window"] = str(nightly_window_dir)
            validate_nightly_window_artifacts(recorder, nightly_window_dir)
    else:
        recorder.pass_check("latest_nightly_window_optional", "latest_nightly_window is absent; optional Phase 16 artifacts not validated", path=nightly_window_pointer)

    human_approval_pointer = run_root / "latest_human_approval"
    if human_approval_pointer.exists() or human_approval_pointer.is_symlink():
        human_approval_dir = validate_latest_dir(recorder, "latest_human_approval_dir", human_approval_pointer)
        if human_approval_dir is not None:
            resolved_dirs["latest_human_approval"] = str(human_approval_dir)
            nightly_window_dir = Path(resolved_dirs["latest_nightly_window"]) if "latest_nightly_window" in resolved_dirs else None
            validate_human_approval_artifacts(recorder, human_approval_dir, nightly_window_dir=nightly_window_dir)
    else:
        recorder.pass_check("latest_human_approval_optional", "latest_human_approval is absent; optional Phase 17 artifacts not validated", path=human_approval_pointer)

    ai_readonly_pointer = run_root / "latest_ai_readonly"
    if ai_readonly_pointer.exists() or ai_readonly_pointer.is_symlink():
        ai_readonly_dir = validate_latest_dir(recorder, "latest_ai_readonly_dir", ai_readonly_pointer)
        if ai_readonly_dir is not None:
            resolved_dirs["latest_ai_readonly"] = str(ai_readonly_dir)
            validate_ai_readonly_artifacts(recorder, ai_readonly_dir)
    else:
        recorder.pass_check("latest_ai_readonly_optional", "latest_ai_readonly is absent; optional Phase 18A artifacts not validated", path=ai_readonly_pointer)

    openhands_coder_pointer = run_root / "latest_openhands_coder"
    if openhands_coder_pointer.exists() or openhands_coder_pointer.is_symlink():
        openhands_coder_dir = validate_latest_dir(recorder, "latest_openhands_coder_dir", openhands_coder_pointer)
        if openhands_coder_dir is not None:
            resolved_dirs["latest_openhands_coder"] = str(openhands_coder_dir)
            validate_openhands_coder_artifacts(recorder, openhands_coder_dir)
            validate_openhands_apply_status(recorder, openhands_coder_dir)
            validate_openhands_manual_gate_summary(recorder, openhands_coder_dir)
    else:
        recorder.pass_check(
            "latest_openhands_coder_optional",
            "latest_openhands_coder is absent; optional Phase 18B artifacts not validated",
            path=openhands_coder_pointer,
        )

    openhands_manual_gate_request_pointer = run_root / "latest_openhands_manual_gate_request"
    if openhands_manual_gate_request_pointer.exists() or openhands_manual_gate_request_pointer.is_symlink():
        request_dir = validate_latest_dir(
            recorder,
            "latest_openhands_manual_gate_request_dir",
            openhands_manual_gate_request_pointer,
        )
        if request_dir is not None:
            resolved_dirs["latest_openhands_manual_gate_request"] = str(request_dir)
            validate_openhands_manual_gate_request(recorder, request_dir)
    else:
        recorder.pass_check(
            "latest_openhands_manual_gate_request_optional",
            "latest_openhands_manual_gate_request is absent; optional Phase 18K artifacts not validated",
            path=openhands_manual_gate_request_pointer,
        )

    # Phase 21: Feature brief intake validation (intake only — no execution)
    feature_queue_pointer = run_root / "feature_queue"
    if feature_queue_pointer.exists() or feature_queue_pointer.is_symlink():
        queue_dir = validate_latest_dir(recorder, "latest_feature_queue_dir", feature_queue_pointer)
        if queue_dir is not None:
            resolved_dirs["latest_feature_queue"] = str(queue_dir)
            validate_phase21_feature_artifacts(recorder, queue_dir)

    # Phase 21: Feature briefs directory validation
    feature_briefs_pointer = run_root / "feature_briefs"
    if feature_briefs_pointer.exists() or feature_briefs_pointer.is_symlink():
        briefs_dir = validate_latest_dir(recorder, "latest_feature_briefs_dir", feature_briefs_pointer)
        if briefs_dir is not None:
            resolved_dirs["latest_feature_briefs"] = str(briefs_dir)
            validate_phase21_feature_briefs_directory(recorder, briefs_dir)

    return resolved_dirs


# ---------------------------------------------------------------------------
# Phase 21 Feature Brief Validation
# ---------------------------------------------------------------------------

PHASE21_GENERATED_BY = "phase21_feature_brief_intake"
PHASE21_VALID_STATUSES = frozenset({"brief_only", "needs_clarification", "ready_for_architecture", "blocked", "archived"})
PHASE21_VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})


def validate_phase21_feature_artifacts(recorder: CheckRecorder, queue_dir: Path) -> None:
    """Validate FEATURE_QUEUE.json in the feature queue directory."""
    queue_path = queue_dir / "FEATURE_QUEUE.json"
    queue_data = validate_json_artifact(recorder, "phase21_queue_parse", queue_path)
    if not isinstance(queue_data, dict):
        recorder.fail_check("phase21_queue_object", "FEATURE_QUEUE.json must be a JSON object", path=queue_path)
        return

    # Check schema_version
    sv = queue_data.get("schema_version")
    if sv == 1:
        recorder.pass_check("phase21_queue_schema_version", "FEATURE_QUEUE.json has schema_version 1", path=queue_path)
    else:
        recorder.fail_check("phase21_queue_schema_version", f"FEATURE_QUEUE.json schema_version must be 1; found {sv!r}", path=queue_path)

    # Check generated_by
    gen = queue_data.get("generated_by")
    if gen == PHASE21_GENERATED_BY:
        recorder.pass_check("phase21_queue_generated_by", "FEATURE_QUEUE.json generated_by is correct", path=queue_path)
    else:
        recorder.fail_check("phase21_queue_generated_by", f"FEATURE_QUEUE.json generated_by must be {PHASE21_GENERATED_BY}; found {gen!r}", path=queue_path)

    # Check project_id matches the validated project
    queue_project = queue_data.get("project_id")
    if isinstance(queue_project, str):
        recorder.pass_check("phase21_queue_has_project_id", f"FEATURE_QUEUE.json references project {queue_project!r}", path=queue_path)
    else:
        recorder.fail_check("phase21_queue_has_project_id", "FEATURE_QUEUE.json must have a string project_id field", path=queue_path)

    # Check features list is present and non-empty when queue exists
    features = queue_data.get("features")
    if isinstance(features, list):
        recorder.pass_check("phase21_queue_features_is_list", "FEATURE_QUEUE.json features is an array", path=queue_path)
        for idx, feat in enumerate(features):
            if not isinstance(feat, dict):
                recorder.fail_check(f"phase21_queue_feature_{idx}_object", f"features[{idx}] must be a JSON object", path=queue_path)
                continue
            fid = feat.get("feature_id")
            status = feat.get("status")
            brief_path = feat.get("brief_path", "")

            if isinstance(fid, str) and fid:
                recorder.pass_check(f"phase21_queue_feature_{idx}_has_id", f"features[{idx}] has feature_id {fid!r}", path=queue_path)
            else:
                recorder.fail_check(f"phase21_queue_feature_{idx}_has_id", f"features[{idx}] must have a non-empty feature_id", path=queue_path)

            if status in PHASE21_VALID_STATUSES:
                recorder.pass_check(f"phase21_queue_feature_{idx}_valid_status", f"features[{idx}] status {status!r} is valid", path=queue_path)
            else:
                recorder.fail_check(
                    f"phase21_queue_feature_{idx}_valid_status",
                    f"features[{idx}] status must be one of {sorted(PHASE21_VALID_STATUSES)}; found {status!r}",
                    path=queue_path,
                )

            if isinstance(brief_path, str) and brief_path:
                full_brief_dir = ROOT / brief_path
                brief_json = full_brief_dir / "FEATURE_BRIEF.json"
                if brief_json.exists():
                    recorder.pass_check(f"phase21_queue_feature_{idx}_brief_exists", f"features[{idx}] brief artifact exists at {brief_json}", path=queue_path)
                    _validate_phase21_brief(recorder, f"phase21_queue_feature_{idx}_brief", brief_json, queue_project)
                else:
                    recorder.fail_check(f"phase21_queue_feature_{idx}_brief_exists", f"features[{idx}] brief artifact not found at {brief_json}", path=queue_path)

        if len(features) >= 1:
            recorder.pass_check("phase21_queue_has_features", "FEATURE_QUEUE.json contains feature entries", path=queue_path)
    else:
        recorder.fail_check("phase21_queue_features_is_list", "FEATURE_QUEUE.json must have a features array", path=queue_path)


def _validate_phase21_brief(recorder: CheckRecorder, check_prefix: str, brief_path: Path, expected_project: str | None = None) -> dict[str, Any] | None:
    """Validate an individual FEATURE_BRIEF.json."""
    brief_data = validate_json_artifact(recorder, f"{check_prefix}_parse", brief_path)
    if not isinstance(brief_data, dict):
        return None

    recorder.pass_check(f"{check_prefix}_shape", "FEATURE_BRIEF.json is a valid JSON object", path=brief_path)

    required_fields = [
        "schema_version",
        "generated_by",
        "created_utc",
        "project_id",
        "feature_id",
        "title",
        "high_level_goal",
        "desired_behavior",
        "must_have_requirements",
        "risk_level",
        "target_project_area",
        "human_priority",
        "status",
    ]
    missing = [f for f in required_fields if f not in brief_data]
    if not missing:
        recorder.pass_check(f"{check_prefix}_required_fields", "FEATURE_BRIEF.json has all required fields", path=brief_path)
    else:
        recorder.fail_check(f"{check_prefix}_required_fields", f"FEATURE_BRIEF.json missing required fields: {missing}", path=brief_path, details={"missing": missing})

    sv = brief_data.get("schema_version")
    if sv == 1:
        recorder.pass_check(f"{check_prefix}_schema_version", "FEATURE_BRIEF.json has schema_version 1", path=brief_path)
    else:
        recorder.fail_check(f"{check_prefix}_schema_version", f"FEATURE_BRIEF.json schema_version must be 1; found {sv!r}", path=brief_path)

    gen = brief_data.get("generated_by")
    if gen == PHASE21_GENERATED_BY:
        recorder.pass_check(f"{check_prefix}_generated_by", "FEATURE_BRIEF.json generated_by is correct", path=brief_path)
    else:
        recorder.fail_check(f"{check_prefix}_generated_by", f"FEATURE_BRIEF.json generated_by must be {PHASE21_GENERATED_BY}; found {gen!r}", path=brief_path)

    if expected_project and isinstance(expected_project, str):
        brief_pid = brief_data.get("project_id")
        if brief_pid == expected_project:
            recorder.pass_check(f"{check_prefix}_project_match", f"FEATURE_BRIEF.json project_id {brief_pid!r} matches queue project", path=brief_path)
        else:
            recorder.fail_check(
                f"{check_prefix}_project_mismatch",
                f"FEATURE_BRIEF.json project_id {brief_pid!r} does not match expected {expected_project!r}",
                path=brief_path,
            )

    status = brief_data.get("status")
    if status in PHASE21_VALID_STATUSES:
        recorder.pass_check(f"{check_prefix}_valid_status", f"FEATURE_BRIEF.json status {status!r} is valid", path=brief_path)
    else:
        recorder.fail_check(
            f"{check_prefix}_invalid_status",
            f"FEATURE_BRIEF.json status must be one of {sorted(PHASE21_VALID_STATUSES)}; found {status!r}",
            path=brief_path,
        )

    risk = brief_data.get("risk_level")
    if risk in PHASE21_VALID_RISK_LEVELS:
        recorder.pass_check(f"{check_prefix}_valid_risk", f"FEATURE_BRIEF.json risk_level {risk!r} is valid", path=brief_path)
    else:
        recorder.fail_check(
            f"{check_prefix}_invalid_risk",
            f"FEATURE_BRIEF.json risk_level must be one of {sorted(PHASE21_VALID_RISK_LEVELS)}; found {risk!r}",
            path=brief_path,
        )

    hp = brief_data.get("human_priority")
    if isinstance(hp, (int, float)):
        recorder.pass_check(f"{check_prefix}_numeric_priority", f"FEATURE_BRIEF.json human_priority {hp!r} is numeric", path=brief_path)
    else:
        recorder.fail_check(
            f"{check_prefix}_priority_type",
            f"FEATURE_BRIEF.json human_priority must be numeric; found {type(hp).__name__!r}",
            path=brief_path,
        )

    return brief_data


def validate_phase21_feature_briefs_directory(recorder: CheckRecorder, briefs_dir: Path) -> None:
    """Validate that FEATURE_BRIEF.md exists alongside each FEATURE_BRIEF.json."""
    for json_file in sorted(briefs_dir.glob("*/FEATURE_BRIEF.json")):
        md_file = json_file.parent / "FEATURE_BRIEF.md"
        if md_file.exists():
            recorder.pass_check(f"phase21_brief_md_exists_for_{json_file.parent.name}", f"FEATURE_BRIEF.md exists alongside {json_file.name}", path=md_file)
        else:
            recorder.fail_check(f"phase21_brief_md_missing_for_{json_file.parent.name}", f"FEATURE_BRIEF.md missing for {json_file.name}", path=json_file)


def validate_phase21_no_execution_safety(recorder: CheckRecorder, resolved_dirs: dict[str, str]) -> None:
    """Verify Phase 21 paths do not enable model calls, OpenHands execution, or source writes."""
    for dir_name in ("latest_feature_queue", "latest_feature_briefs"):
        if dir_name not in resolved_dirs:
            continue
        dir_path = Path(resolved_dirs[dir_name])
        for json_file in dir_path.rglob("*.json"):
            text = json_file.read_text()
            unsafe_flags = [
                "model_calls_enabled",
                "execution_enabled",
                "source_writes_enabled",
                "auto_merge_enabled",
                "auto_push_enabled",
                "apply_canonical_write",
                "allow_canonical_write",
                "commit_enabled",
                "push_enabled",
                "merge_enabled",
                "pr_creation_enabled",
            ]
            found_unsafe = [flag for flag in unsafe_flags if flag in text]
            if found_unsafe:
                recorder.fail_check(
                    f"phase21_no_execution_{json_file.name}",
                    f"{json_file.name} contains execution-enabling flags: {found_unsafe}",
                    path=json_file,
                    details={"flags": found_unsafe},
                )
            else:
                recorder.pass_check(f"phase21_no_execution_flag_{json_file.stem}", f"No execution-enabling flags in {json_file.name}", path=json_file)

    recorder.pass_check(
        "phase21_intake_only",
        "Phase 21 is intake-only: no model calls, no OpenHands execution, no source writes to target project repos",
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Phase 22 — AI Architecture Agent Validation
# ---------------------------------------------------------------------------

PHASE22_GENERATED_BY = "phase22_ai_architecture_agent"


def validate_phase22_architecture_proposals(recorder: CheckRecorder, arch_dir: Path) -> None:
    """Validate ARCHITECTURE_PROPOSAL.json and related artifacts in the architecture proposal directory."""
    # Check for ARCHITECTURE_PROPOSAL.json
    proposal_path = arch_dir / "ARCHITECTURE_PROPOSAL.json"
    if not proposal_path.exists():
        recorder.fail_check(
            "phase22_arch_proposal_json_exists",
            f"ARCHITECTURE_PROPOSAL.json is missing in {arch_dir}",
            path=proposal_path,
        )
        return

    proposal_data = validate_json_artifact(recorder, "phase22_arch_proposal_parse", proposal_path)
    if not isinstance(proposal_data, dict):
        recorder.fail_check("phase22_arch_proposal_shape", f"ARCHITECTURE_PROPOSAL.json must be a JSON object", path=proposal_path)
        return

    # Validate generated_by
    gen = proposal_data.get("generated_by")
    if gen == PHASE22_GENERATED_BY:
        recorder.pass_check(
            "phase22_arch_proposal_generated_by",
            f"ARCHITECTURE_PROPOSAL.json generated_by is {PHASE22_GENERATED_BY}",
            path=proposal_path,
        )
    else:
        recorder.fail_check(
            "phase22_arch_proposal_generated_by",
            f"ARCHITECTURE_PROPOSAL.json generated_by must be {PHASE22_GENERATED_BY}; found {gen!r}",
            path=proposal_path,
        )

    # Validate schema_version
    sv = proposal_data.get("schema_version")
    if sv == 1:
        recorder.pass_check(
            "phase22_arch_proposal_schema_version",
            "ARCHITECTURE_PROPOSAL.json schema_version is 1",
            path=proposal_path,
        )
    else:
        recorder.fail_check(
            "phase22_arch_proposal_schema_version",
            f"ARCHITECTURE_PROPOSAL.json schema_version must be 1; found {sv!r}",
            path=proposal_path,
        )

    # Validate architecture_status
    status = proposal_data.get("architecture_status")
    if status in {"proposal_ready", "needs_clarification", "blocked"}:
        recorder.pass_check(
            "phase22_arch_proposal_status",
            f"ARCHITECTURE_PROPOSAL.json architecture_status is valid ({status})",
            path=proposal_path,
        )
    else:
        recorder.fail_check(
            "phase22_arch_proposal_status",
            f"ARCHITECTURE_PROPOSAL.json architecture_status must be one of proposal_ready, needs_clarification, blocked; found {status!r}",
            path=proposal_path,
        )

    # Validate project_id and feature_id are present and non-empty
    pid = proposal_data.get("project_id")
    fid = proposal_data.get("feature_id")
    if isinstance(pid, str) and pid:
        recorder.pass_check(
            "phase22_arch_proposal_project_id",
            f"ARCHITECTURE_PROPOSAL.json project_id is present ({pid!r})",
            path=proposal_path,
        )
    else:
        recorder.fail_check(
            "phase22_arch_proposal_project_id",
            "ARCHITECTURE_PROPOSAL.json must have a non-empty project_id field",
            path=proposal_path,
        )

    if isinstance(fid, str) and fid:
        recorder.pass_check(
            "phase22_arch_proposal_feature_id",
            f"ARCHITECTURE_PROPOSAL.json feature_id is present ({fid!r})",
            path=proposal_path,
        )
    else:
        recorder.fail_check(
            "phase22_arch_proposal_feature_id",
            "ARCHITECTURE_PROPOSAL.json must have a non-empty feature_id field",
            path=proposal_path,
        )

    # Validate safety flags in mock mode are all false
    model_call_allowed = proposal_data.get("model_call_allowed")
    model_called = proposal_data.get("model_called")
    source_writes = proposal_data.get("source_writes_performed")
    openhands_executed = proposal_data.get("openhands_executed")

    if model_call_allowed is False:
        recorder.pass_check("phase22_arch_safety_model_call_allowed", "model_call_allowed is false", path=proposal_path)
    else:
        recorder.fail_check(
            "phase22_arch_safety_model_call_allowed",
            f"model_call_allowed must be false; found {model_call_allowed!r}",
            path=proposal_path,
        )

    if model_called is False:
        recorder.pass_check("phase22_arch_safety_model_called", "model_called is false", path=proposal_path)
    else:
        recorder.fail_check(
            "phase22_arch_safety_model_called",
            f"model_called must be false; found {model_called!r}",
            path=proposal_path,
        )

    if source_writes is False:
        recorder.pass_check("phase22_arch_safety_source_writes", "source_writes_performed is false", path=proposal_path)
    else:
        recorder.fail_check(
            "phase22_arch_safety_source_writes",
            f"source_writes_performed must be false; found {source_writes!r}",
            path=proposal_path,
        )

    if openhands_executed is False:
        recorder.pass_check("phase22_arch_safety_openhands", "openhands_executed is false", path=proposal_path)
    else:
        recorder.fail_check(
            "phase22_arch_safety_openhands",
            f"openhands_executed must be false; found {openhands_executed!r}",
            path=proposal_path,
        )

    # Validate required text fields are non-empty strings
    for field_name in ("title", "problem_summary", "recommended_design", "test_strategy"):
        val = proposal_data.get(field_name)
        if isinstance(val, str) and val.strip():
            recorder.pass_check(
                f"phase22_arch_field_{field_name}",
                f"{field_name} is a non-empty string",
                path=proposal_path,
            )
        else:
            recorder.fail_check(
                f"phase22_arch_field_{field_name}",
                f"{field_name} must be a non-empty string; found {val!r}",
                path=proposal_path,
            )

    # Validate list fields are lists (or absent but allowed)
    for field_name in ("alternative_designs", "files_likely_involved", "interfaces_and_contracts",
                       "data_artifacts", "safety_risks", "implementation_sequence",
                       "assumptions", "constraints", "out_of_scope", "questions_for_human"):
        val = proposal_data.get(field_name)
        if isinstance(val, list):
            recorder.pass_check(
                f"phase22_arch_field_{field_name}_is_list",
                f"{field_name} is a list ({len(val)} items)",
                path=proposal_path,
            )
        elif val is None:
            recorder.pass_check(
                f"phase22_arch_field_{field_name}_absent_ok",
                f"{field_name} absent (optional)",
                path=proposal_path,
            )
        else:
            recorder.fail_check(
                f"phase22_arch_field_{field_name}_is_list",
                f"{field_name} must be a list; found {type(val).__name__}",
                path=proposal_path,
            )

    # Check for ARCHITECTURE_PROPOSAL.md
    md_path = arch_dir / "ARCHITECTURE_PROPOSAL.md"
    validate_text_artifact(recorder, "phase22_arch_proposal_md_exists", md_path)

    # Check for ARCHITECTURE_AGENT_PROMPT.md
    prompt_path = arch_dir / "ARCHITECTURE_AGENT_PROMPT.md"
    validate_text_artifact(recorder, "phase22_arch_prompt_exists", prompt_path)




def path_has_parent_traversal(path: str) -> bool:
    return ".." in Path(path).parts


def command_unsafe_reasons(text: str) -> list[str]:
    lowered = text.lower()
    return [pattern for pattern in OPENHANDS_MANUAL_GATE_REQUEST_UNSAFE_COMMAND_PATTERNS if pattern in lowered]


def validate_openhands_manual_gate_request(recorder: CheckRecorder, request_dir: Path) -> None:
    request_path = request_dir / "OPENHANDS_MANUAL_GATE_REQUEST.json"
    request = validate_json_artifact(recorder, "openhands_manual_gate_request_parse", request_path)
    if request is None:
        return
    if not isinstance(request, dict):
        recorder.fail_check("openhands_manual_gate_request_object", "OPENHANDS_MANUAL_GATE_REQUEST.json must be an object", path=request_path)
        return

    gen_by = request.get("generated_by")
    if gen_by == OPENHANDS_MANUAL_GATE_REQUEST_GENERATED_BY:
        recorder.pass_check(
            "openhands_manual_gate_request_generated_by",
            "OPENHANDS_MANUAL_GATE_REQUEST.json generated_by is phase18k_manager_to_openhands_task_packet_bridge",
            path=request_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_request_generated_by",
            f"OPENHANDS_MANUAL_GATE_REQUEST.json generated_by must be {OPENHANDS_MANUAL_GATE_REQUEST_GENERATED_BY}; found {gen_by!r}",
            path=request_path,
        )

    if request.get("no_openhands_execution_performed") is True:
        recorder.pass_check("openhands_manual_gate_request_no_openhands", "OPENHANDS_MANUAL_GATE_REQUEST.json records no OpenHands execution", path=request_path)
    else:
        recorder.fail_check(
            "openhands_manual_gate_request_no_openhands",
            f"OPENHANDS_MANUAL_GATE_REQUEST.json no_openhands_execution_performed must be true; found {request.get('no_openhands_execution_performed')!r}",
            path=request_path,
        )

    if request.get("no_apply_commit_push_merge_pr_or_cleanup_performed") is True:
        recorder.pass_check(
            "openhands_manual_gate_request_no_apply_commit_push",
            "OPENHANDS_MANUAL_GATE_REQUEST.json records no apply/commit/push/merge/PR/cleanup",
            path=request_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_request_no_apply_commit_push",
            f"OPENHANDS_MANUAL_GATE_REQUEST.json no_apply_commit_push_merge_pr_or_cleanup_performed must be true; found {request.get('no_apply_commit_push_merge_pr_or_cleanup_performed')!r}",
            path=request_path,
        )

    status = request.get("status")
    if status in {"pass", "warn"}:
        recorder.pass_check("openhands_manual_gate_request_status", f"OPENHANDS_MANUAL_GATE_REQUEST.json status accepted: {status}", path=request_path)
    else:
        recorder.fail_check(
            "openhands_manual_gate_request_status",
            f"OPENHANDS_MANUAL_GATE_REQUEST.json status must be pass or warn; found {status!r}",
            path=request_path,
        )

    task_source = request.get("task_source")
    task_text = request.get("task_text")
    task_file = request.get("task_file")
    if task_source == "task_text" and isinstance(task_text, str) and task_text.strip() and not task_file:
        recorder.pass_check("openhands_manual_gate_request_task_source", "OPENHANDS_MANUAL_GATE_REQUEST.json task_text source is valid", path=request_path)
    elif task_source == "task_file" and isinstance(task_text, str) and task_text.strip() and isinstance(task_file, str) and task_file:
        recorder.pass_check("openhands_manual_gate_request_task_source", "OPENHANDS_MANUAL_GATE_REQUEST.json task_file source is valid", path=request_path)
    else:
        recorder.fail_check(
            "openhands_manual_gate_request_task_source",
            f"OPENHANDS_MANUAL_GATE_REQUEST.json task source is invalid: task_source={task_source!r}, task_file={task_file!r}",
            path=request_path,
        )

    allowed = request.get("allowed_files")
    if isinstance(allowed, list) and allowed and all(isinstance(item, str) for item in allowed):
        recorder.pass_check("openhands_manual_gate_request_allowed_files_present", "OPENHANDS_MANUAL_GATE_REQUEST.json allowed_files is populated", path=request_path)
        for item in allowed:
            if Path(item).is_absolute() or path_has_parent_traversal(item):
                recorder.fail_check(
                    "openhands_manual_gate_request_allowed_file_safe",
                    f"allowed file must be relative and must not contain parent traversal: {item!r}",
                    path=request_path,
                )
                break
        else:
            recorder.pass_check("openhands_manual_gate_request_allowed_file_safe", "OPENHANDS_MANUAL_GATE_REQUEST.json allowed_files are relative and traversal-free", path=request_path)
    else:
        recorder.fail_check("openhands_manual_gate_request_allowed_files_present", "OPENHANDS_MANUAL_GATE_REQUEST.json allowed_files must be a non-empty string list", path=request_path)

    command_file = request.get("command_file")
    command_markdown_file = request.get("command_markdown_file")
    command_paths: list[Path] = []
    for check_id, raw in (
        ("openhands_manual_gate_request_command_file_readable", command_file),
        ("openhands_manual_gate_request_command_markdown_readable", command_markdown_file),
    ):
        path = Path(str(raw)) if isinstance(raw, str) and raw else request_dir / "__missing__"
        validate_text_artifact(recorder, check_id, path)
        if path.exists():
            command_paths.append(path)

    for path in command_paths:
        try:
            content = path.read_text()
        except OSError as exc:
            recorder.fail_check("openhands_manual_gate_request_command_safe", f"{path.name} could not be inspected: {exc}", path=path)
            continue
        reasons = command_unsafe_reasons(content)
        if reasons:
            recorder.fail_check(
                "openhands_manual_gate_request_command_safe",
                f"{path.name} contains unsafe command content: {', '.join(reasons)}",
                path=path,
            )
        else:
            recorder.pass_check("openhands_manual_gate_request_command_safe", f"{path.name} contains no apply/commit/push/merge/PR/cleanup commands", path=path)

    validate_text_artifact(recorder, "openhands_manual_gate_request_md_readable", request_dir / "OPENHANDS_MANUAL_GATE_REQUEST.md")


def validate_openhands_manual_gate_summary(recorder: CheckRecorder, coder_dir: Path) -> None:
    """Validate OPENHANDS_MANUAL_GATE_SUMMARY.json when present."""
    gate_path = coder_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json"

    if not gate_path.exists():
        recorder.pass_check(
            "openhands_manual_gate_summary_optional",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json is absent; manual gate summary not validated",
            path=gate_path,
        )
        return

    data = validate_json_artifact(
        recorder,
        "openhands_manual_gate_summary_parse",
        gate_path,
    )
    if data is None:
        return  # already recorded as fail above.

    # Check generated_by must be phase18j_openhands_manual_gate_runner.
    gen_by = data.get("generated_by")
    if gen_by == "phase18j_openhands_manual_gate_runner":
        recorder.pass_check(
            "openhands_manual_gate_generated_by",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json generated_by is phase18j_openhands_manual_gate_runner",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_generated_by",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json generated_by must be phase18j_openhands_manual_gate_runner; found {gen_by!r}",
            path=gate_path,
        )

    # Check no_apply_commit_push_merge_pr_or_cleanup_performed is true.
    nap = data.get("no_apply_commit_push_merge_pr_or_cleanup_performed")
    if nap is True:
        recorder.pass_check(
            "openhands_manual_gate_no_apply_commit_push",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json no_apply_commit_push_merge_pr_or_cleanup_performed is true",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_no_apply_commit_push",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json no_apply_commit_push_merge_pr_or_cleanup_performed must be true; found {nap!r}",
            path=gate_path,
        )

    # Check applied is false.
    applied = data.get("applied")
    if applied is False:
        recorder.pass_check(
            "openhands_manual_gate_applied_false",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json applied is false",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_applied_false",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json applied must be false; found {applied!r}",
            path=gate_path,
        )

    # Check canonical_repo_clean is true.
    crc = data.get("canonical_repo_clean")
    if crc is True:
        recorder.pass_check(
            "openhands_manual_gate_canonical_clean",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json canonical_repo_clean is true",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_canonical_clean",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json canonical_repo_clean must be true; found {crc!r}",
            path=gate_path,
        )

    # Check status rules.
    status = data.get("status")
    dry_run = data.get("dry_run")
    openhands_executed = data.get("openhands_execution_performed")
    failure_classification = data.get("failure_classification")
    retryable = data.get("retryable")
    misplaced_paths = data.get("misplaced_run_dir_paths")

    if failure_classification in OPENHANDS_MANUAL_GATE_FAILURE_CLASSIFICATIONS:
        recorder.pass_check(
            "openhands_manual_gate_failure_classification",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json failure_classification is {failure_classification}",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_failure_classification",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json failure_classification must be one of {sorted(OPENHANDS_MANUAL_GATE_FAILURE_CLASSIFICATIONS)}; found {failure_classification!r}",
            path=gate_path,
        )

    if isinstance(retryable, bool):
        recorder.pass_check(
            "openhands_manual_gate_retryable_bool",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json retryable is boolean",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_retryable_bool",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json retryable must be boolean; found {retryable!r}",
            path=gate_path,
        )

    if isinstance(misplaced_paths, list):
        recorder.pass_check(
            "openhands_manual_gate_misplaced_paths_list",
            "OPENHANDS_MANUAL_GATE_SUMMARY.json misplaced_run_dir_paths is a list",
            path=gate_path,
        )
    else:
        recorder.fail_check(
            "openhands_manual_gate_misplaced_paths_list",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json misplaced_run_dir_paths must be a list; found {misplaced_paths!r}",
            path=gate_path,
        )

    if dry_run is True and openhands_executed is not True:
        # Dry-run warn is acceptable.
        if status == "warn":
            recorder.pass_check(
                "openhands_manual_gate_dryrun_warn",
                f"OPENHANDS_MANUAL_GATE_SUMMARY.json dry-run warn accepted (dry_run={dry_run}, openhands_execution_performed={openhands_executed})",
                path=gate_path,
            )
        else:
            recorder.fail_check(
                "openhands_manual_gate_dryrun_warn",
                f"OPENHANDS_MANUAL_GATE_SUMMARY.json dry-run summary should have status warn; found {status!r}",
                path=gate_path,
            )
    elif openhands_executed is True:
        # Live run: accept pass only.
        if status == "pass":
            recorder.pass_check(
                "openhands_manual_gate_live_pass",
                f"OPENHANDS_MANUAL_GATE_SUMMARY.json live pass accepted (dry_run={dry_run}, openhands_execution_performed={openhands_executed})",
                path=gate_path,
            )
            if failure_classification == "none":
                recorder.pass_check(
                    "openhands_manual_gate_live_pass_classification_none",
                    "OPENHANDS_MANUAL_GATE_SUMMARY.json live pass classification is none",
                    path=gate_path,
                )
            else:
                recorder.fail_check(
                    "openhands_manual_gate_live_pass_classification_none",
                    f"OPENHANDS_MANUAL_GATE_SUMMARY.json live pass classification must be none; found {failure_classification!r}",
                    path=gate_path,
                )
            if retryable is False:
                recorder.pass_check(
                    "openhands_manual_gate_live_pass_not_retryable",
                    "OPENHANDS_MANUAL_GATE_SUMMARY.json live pass retryable is false",
                    path=gate_path,
                )
            else:
                recorder.fail_check(
                    "openhands_manual_gate_live_pass_not_retryable",
                    f"OPENHANDS_MANUAL_GATE_SUMMARY.json live pass retryable must be false; found {retryable!r}",
                    path=gate_path,
                )
        else:
            recorder.fail_check(
                "openhands_manual_gate_live_fail",
                f"OPENHANDS_MANUAL_GATE_SUMMARY.json live run status must be pass; found {status!r}; failure_classification={failure_classification!r}",
                path=gate_path,
            )
    else:
        # Neither dry-run nor live execution detected.
        recorder.fail_check(
            "openhands_manual_gate_status_unknown",
            f"OPENHANDS_MANUAL_GATE_SUMMARY.json unexpected state: dry_run={dry_run}, openhands_execution_performed={openhands_executed}",
            path=gate_path,
        )

    # Validate markdown artifact when JSON is present.
    validate_text_artifact(recorder, "openhands_manual_gate_summary_md_readable", coder_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.md")


def validate_openhands_coder_artifacts(recorder: CheckRecorder, coder_dir: Path) -> None:
    """Validate Phase 18B/E controlled OpenHands coder artifacts."""
    required_json = [
        ("openhands_coder_run_parse", "OPENHANDS_CODER_RUN.json"),
        ("openhands_exit_status_parse", "OPENHANDS_EXIT_STATUS.json"),
        ("openhands_safety_status_parse", "OPENHANDS_SAFETY_STATUS.json"),
        ("openhands_coder_summary_parse", "OPENHANDS_CODER_SUMMARY.json"),
    ]
    required_text = [
        "OPENHANDS_CODER_RUN.md",
        "OPENHANDS_TASK_PROMPT.md",
        "OPENHANDS_COMMAND.txt",
        "OPENHANDS_STDOUT.txt",
        "OPENHANDS_STDERR.txt",
        "OPENHANDS_WORKTREE_STATUS_BEFORE.txt",
        "OPENHANDS_WORKTREE_STATUS_AFTER.txt",
        "OPENHANDS_DIFF_SUMMARY.txt",
        "OPENHANDS_CODER_SUMMARY.md",
    ]

    parsed: dict[str, Any] = {}
    for check_id, filename in required_json:
        data = validate_json_artifact(recorder, check_id, coder_dir / filename)
        if data is not None:
            parsed[filename] = data
    
    # Validate new Phase 18E artifacts
    worktree_info = validate_json_artifact(recorder, "openhands_worktree_info_parse", coder_dir / "OPENHANDS_WORKTREE_INFO.json")
    if worktree_info is not None:
        parsed["OPENHANDS_WORKTREE_INFO.json"] = worktree_info
    
    changed_files = validate_json_artifact(recorder, "openhands_changed_files_parse", coder_dir / "OPENHANDS_CHANGED_FILES.json")
    if changed_files is not None:
        parsed["OPENHANDS_CHANGED_FILES.json"] = changed_files
    
    scope_status = validate_json_artifact(recorder, "openhands_scope_status_parse", coder_dir / "OPENHANDS_SCOPE_STATUS.json")
    if scope_status is not None:
        parsed["OPENHANDS_SCOPE_STATUS.json"] = scope_status

    smoke_path = coder_dir / "OPENHANDS_SMOKE_STATUS.json"
    if smoke_path.exists():
        data = validate_json_artifact(recorder, "openhands_smoke_status_parse", smoke_path)
        if data is not None:
            parsed["OPENHANDS_SMOKE_STATUS.json"] = data
    for filename in required_text:
        validate_text_artifact(recorder, f"{filename}_readable", coder_dir / filename)

    safety = parsed.get("OPENHANDS_SAFETY_STATUS.json")
    if isinstance(safety, dict):
        dangerous_checks = [
            ("canonical_repo_writes_allowed", False),
            ("auto_push_allowed", False),
            ("auto_merge_allowed", False),
            ("auto_commit_allowed", False),
            ("pr_creation_allowed", False),
        ]
        for key, expected in dangerous_checks:
            actual = safety.get(key)
            if actual == expected:
                recorder.pass_check(
                    f"openhands_safety_{key}",
                    f"safety_status.{key} is {expected}",
                    path=coder_dir / "OPENHANDS_SAFETY_STATUS.json",
                )
            else:
                recorder.fail_check(
                    f"openhands_safety_{key}",
                    f"safety_status.{key} must be {expected}; found {actual!r}. This is a blocking safety violation.",
                    path=coder_dir / "OPENHANDS_SAFETY_STATUS.json",
                )
        dry_run = safety.get("dry_run")
        if isinstance(dry_run, bool):
            recorder.pass_check(
                "openhands_safety_dry_run_bool",
                f"safety_status.dry_run is {dry_run}",
                path=coder_dir / "OPENHANDS_SAFETY_STATUS.json",
            )
        else:
            recorder.fail_check(
                "openhands_safety_dry_run_bool",
                f"safety_status.dry_run must be boolean; found {dry_run!r}",
                path=coder_dir / "OPENHANDS_SAFETY_STATUS.json",
            )
        if safety.get("secrets_redacted") is True:
            recorder.pass_check("openhands_safety_secrets_redacted", "safety_status.secrets_redacted is true", path=coder_dir / "OPENHANDS_SAFETY_STATUS.json")
        else:
            recorder.fail_check("openhands_safety_secrets_redacted", "safety_status.secrets_redacted must be true", path=coder_dir / "OPENHANDS_SAFETY_STATUS.json")

    run_record = parsed.get("OPENHANDS_CODER_RUN.json")
    if isinstance(run_record, dict):
        required = {"project_id", "created_utc", "generated_by", "worktree_path", "worktree_git_branch", "command_argv_redacted"}
        missing = sorted(required - set(run_record))
        if not missing:
            recorder.pass_check("openhands_run_required_fields", "OPENHANDS_CODER_RUN.json has required fields", path=coder_dir / "OPENHANDS_CODER_RUN.json")
        else:
            recorder.fail_check(
                "openhands_run_required_fields",
                "OPENHANDS_CODER_RUN.json is missing required fields",
                path=coder_dir / "OPENHANDS_CODER_RUN.json",
                details={"missing": missing},
            )
        command = run_record.get("command_argv_redacted")
        if isinstance(command, list) and "--override-with-envs" in command:
            recorder.pass_check("openhands_command_override_envs", "OpenHands command includes --override-with-envs", path=coder_dir / "OPENHANDS_CODER_RUN.json")
        else:
            recorder.fail_check("openhands_command_override_envs", "OpenHands command must include --override-with-envs", path=coder_dir / "OPENHANDS_CODER_RUN.json")
        manual_allowed = run_record.get("manual_allowed_files")
        if isinstance(manual_allowed, list):
            recorder.pass_check("openhands_run_manual_allowed_files_parse", "OPENHANDS_CODER_RUN.json manual_allowed_files is a list", path=coder_dir / "OPENHANDS_CODER_RUN.json")
        elif "manual_allowed_files" in run_record:
            recorder.fail_check("openhands_run_manual_allowed_files_parse", "OPENHANDS_CODER_RUN.json manual_allowed_files must be a list", path=coder_dir / "OPENHANDS_CODER_RUN.json")

    exit_status = parsed.get("OPENHANDS_EXIT_STATUS.json")
    if isinstance(exit_status, dict):
        status = exit_status.get("status")
        if status in {"pass", "warn", "fail"}:
            recorder.pass_check("openhands_exit_status_value", f"OPENHANDS_EXIT_STATUS.json status is {status!r}", path=coder_dir / "OPENHANDS_EXIT_STATUS.json")
        else:
            recorder.fail_check("openhands_exit_status_value", f"OPENHANDS_EXIT_STATUS.json status must be pass, warn, or fail; found {status!r}", path=coder_dir / "OPENHANDS_EXIT_STATUS.json")

    summary = parsed.get("OPENHANDS_CODER_SUMMARY.json")
    if isinstance(summary, dict):
        gen_by = summary.get("generated_by")
        if gen_by == "phase18f_manual_nonsmoke_write_gate":
            recorder.pass_check("openhands_summary_generated_by", "OPENHANDS_CODER_SUMMARY.json generated_by is phase18f", path=coder_dir / "OPENHANDS_CODER_SUMMARY.json")
        else:
            recorder.fail_check("openhands_summary_generated_by", f"OPENHANDS_CODER_SUMMARY.json generated_by must be phase18f_manual_nonsmoke_write_gate; found {gen_by!r}", path=coder_dir / "OPENHANDS_CODER_SUMMARY.json")

    smoke = parsed.get("OPENHANDS_SMOKE_STATUS.json")
    if isinstance(smoke, dict):
        required_fields = {
            "smoke_task",
            "expected_file",
            "worktree_path",
            "expected_file_absolute_path",
            "run_dir",
            "misplaced_file_paths",
            "expected_file_exists",
            "canonical_repo_clean",
            "returncode",
            "timed_out",
            "status",
        }
        missing = sorted(required_fields - set(smoke))
        if not missing:
            recorder.pass_check("openhands_smoke_required_fields", "OPENHANDS_SMOKE_STATUS.json has required fields", path=coder_dir / "OPENHANDS_SMOKE_STATUS.json")
        else:
            recorder.fail_check(
                "openhands_smoke_required_fields",
                "OPENHANDS_SMOKE_STATUS.json is missing required fields",
                path=coder_dir / "OPENHANDS_SMOKE_STATUS.json",
                details={"missing": missing},
            )
        field_types = {
            "smoke_task": bool,
            "expected_file": str,
            "worktree_path": str,
            "expected_file_absolute_path": str,
            "run_dir": str,
            "misplaced_file_paths": list,
            "expected_file_exists": bool,
            "canonical_repo_clean": bool,
            "returncode": int,
            "timed_out": bool,
        }
        bad_types = sorted(
            key for key, expected_type in field_types.items() if key in smoke and not isinstance(smoke.get(key), expected_type)
        )
        if not bad_types:
            recorder.pass_check("openhands_smoke_field_types", "OPENHANDS_SMOKE_STATUS.json field types are valid", path=coder_dir / "OPENHANDS_SMOKE_STATUS.json")
        else:
            recorder.fail_check(
                "openhands_smoke_field_types",
                "OPENHANDS_SMOKE_STATUS.json has invalid field types",
                path=coder_dir / "OPENHANDS_SMOKE_STATUS.json",
                details={"bad_types": bad_types},
            )
        if smoke.get("status") in {"pass", "warn"}:
            recorder.pass_check("openhands_smoke_status_value", f"OPENHANDS_SMOKE_STATUS.json status is {smoke.get('status')!r}", path=coder_dir / "OPENHANDS_SMOKE_STATUS.json")
        else:
            recorder.fail_check("openhands_smoke_status_value", f"OPENHANDS_SMOKE_STATUS.json status must be pass or warn; found {smoke.get('status')!r}", path=coder_dir / "OPENHANDS_SMOKE_STATUS.json")
        if smoke.get("canonical_repo_clean") is True:
            recorder.pass_check("openhands_smoke_canonical_repo_clean", "Smoke task reports canonical repo clean", path=coder_dir / "OPENHANDS_SMOKE_STATUS.json")
        else:
            recorder.fail_check(
                "openhands_smoke_canonical_repo_clean",
                "Smoke task must not write to the canonical repo; canonical_repo_clean must be true",
                path=coder_dir / "OPENHANDS_SMOKE_STATUS.json",
            )
        misplaced = smoke.get("misplaced_file_paths")
        if isinstance(misplaced, list) and misplaced:
            recorder.pass_check(
                "openhands_smoke_misplaced_file_paths",
                "Smoke task reported misplaced smoke files for review",
                path=coder_dir / "OPENHANDS_SMOKE_STATUS.json",
                details={"misplaced_file_paths": misplaced},
            )
        elif isinstance(misplaced, list):
            recorder.pass_check("openhands_smoke_no_misplaced_file_paths", "Smoke task reported no misplaced smoke files", path=coder_dir / "OPENHANDS_SMOKE_STATUS.json")

    # Validate OPENHANDS_WORKTREE_INFO.json fields
    wt_info = parsed.get("OPENHANDS_WORKTREE_INFO.json")
    if isinstance(wt_info, dict):
        wt_required = {"schema_version", "project_id", "created_utc", "canonical_repo", "worktree_path", "worktree_branch", "worktree_created", "reused_existing_worktree", "worktree_head", "base_branch", "status"}
        wt_missing = sorted(wt_required - set(wt_info))
        if not wt_missing:
            recorder.pass_check("openhands_worktree_info_fields", "OPENHANDS_WORKTREE_INFO.json has required fields", path=coder_dir / "OPENHANDS_WORKTREE_INFO.json")
        else:
            recorder.fail_check(
                "openhands_worktree_info_fields",
                "OPENHANDS_WORKTREE_INFO.json is missing required fields",
                path=coder_dir / "OPENHANDS_WORKTREE_INFO.json",
                details={"missing": wt_missing},
            )

    # Validate OPENHANDS_CHANGED_FILES.json fields
    cf = parsed.get("OPENHANDS_CHANGED_FILES.json")
    if isinstance(cf, dict):
        cf_required = {"tracked_modified_files", "staged_files", "untracked_files", "all_changed_files", "worktree_changed"}
        cf_missing = sorted(cf_required - set(cf))
        if not cf_missing:
            recorder.pass_check("openhands_changed_files_fields", "OPENHANDS_CHANGED_FILES.json has required fields", path=coder_dir / "OPENHANDS_CHANGED_FILES.json")
        else:
            recorder.fail_check(
                "openhands_changed_files_fields",
                "OPENHANDS_CHANGED_FILES.json is missing required fields",
                path=coder_dir / "OPENHANDS_CHANGED_FILES.json",
                details={"missing": cf_missing},
            )

    # Validate OPENHANDS_SCOPE_STATUS.json and apply scope guard logic
    ss = parsed.get("OPENHANDS_SCOPE_STATUS.json")
    if isinstance(ss, dict):
        ss_required = {"schema_version", "project_id", "created_utc", "task_type", "allowed_files", "changed_files", "scope_status", "details"}
        ss_missing = sorted(ss_required - set(ss))
        if not ss_missing:
            recorder.pass_check("openhands_scope_status_fields", "OPENHANDS_SCOPE_STATUS.json has required fields", path=coder_dir / "OPENHANDS_SCOPE_STATUS.json")
        else:
            recorder.fail_check(
                "openhands_scope_status_fields",
                "OPENHANDS_SCOPE_STATUS.json is missing required fields",
                path=coder_dir / "OPENHANDS_SCOPE_STATUS.json",
                details={"missing": ss_missing},
            )
        scope_val = ss.get("scope_status")
        if scope_val == "fail":
            recorder.fail_check(
                "openhands_scope_guard_fail",
                f"Scope guard status is fail: {ss.get('details', 'unknown')}",
                path=coder_dir / "OPENHANDS_SCOPE_STATUS.json",
            )
        elif scope_val == "warn":
            recorder.pass_check(
                "openhands_scope_guard_warn",
                f"Scope guard status is warn (non-blocking): {ss.get('details', 'unknown')}",
                path=coder_dir / "OPENHANDS_SCOPE_STATUS.json",
            )
        else:
            recorder.pass_check("openhands_scope_guard_pass", f"Scope guard status is pass", path=coder_dir / "OPENHANDS_SCOPE_STATUS.json")

    # Smoke warn acceptance rule
    if smoke and isinstance(smoke, dict):
        if smoke.get("status") == "warn":
            # Accept smoke warn only if canonical repo clean and scope status not fail
            smoke_canonical_clean = smoke.get("canonical_repo_clean") is True
            scope_not_fail = (ss is None) or ss.get("scope_status") != "fail"
            if smoke_canonical_clean and scope_not_fail:
                recorder.pass_check(
                    "smoke_warn_accepted",
                    "Smoke warn accepted: canonical repo clean and scope status not fail",
                    path=coder_dir / "OPENHANDS_SMOKE_STATUS.json",
                )
            else:
                recorder.fail_check(
                    "smoke_warn_rejected",
                    "Smoke warn rejected: canonical repo dirty or scope status is fail",
                    path=coder_dir / "OPENHANDS_SMOKE_STATUS.json",
                )

    # Fresh worktree requirement for executed live runs
    run_rec = parsed.get("OPENHANDS_CODER_RUN.json")
    if isinstance(run_rec, dict) and run_rec.get("execution_performed") is True:
        fresh = run_rec.get("fresh_worktree_created")
        if fresh is True:
            recorder.pass_check(
                "fresh_worktree_required",
                "Executed live OpenHands run created a fresh worktree",
                path=coder_dir / "OPENHANDS_CODER_RUN.json",
            )
        else:
            recorder.fail_check(
                "fresh_worktree_required",
                "Executed live OpenHands run must have fresh_worktree_created=true; add --reuse-worktree flag to override in future",
                path=coder_dir / "OPENHANDS_CODER_RUN.json",
            )
        task_type = run_rec.get("task_type")
        manual_allowed = run_rec.get("manual_allowed_files")
        if task_type in {"manual_task_text", "manual_task_file"}:
            if isinstance(manual_allowed, list) and manual_allowed:
                recorder.pass_check(
                    "manual_task_allowed_files_present",
                    "Live manual OpenHands task has explicit allowed files",
                    path=coder_dir / "OPENHANDS_CODER_RUN.json",
                )
            else:
                recorder.fail_check(
                    "manual_task_allowed_files_present",
                    "Live non-smoke manual OpenHands task must include manual_allowed_files",
                    path=coder_dir / "OPENHANDS_CODER_RUN.json",
                )
            cf = parsed.get("OPENHANDS_CHANGED_FILES.json")
            if isinstance(cf, dict) and cf.get("worktree_changed") is False:
                recorder.pass_check(
                    "manual_task_no_file_change_warn",
                    "Live manual OpenHands task changed no files; review as warning",
                    path=coder_dir / "OPENHANDS_CHANGED_FILES.json",
                )

    if (coder_dir / "OPENHANDS_DECISION_PACKET.json").exists():
        validate_openhands_decision_packet_artifacts(recorder, coder_dir)


def validate_openhands_decision_packet_artifacts(recorder: CheckRecorder, packet_dir: Path) -> None:
    packet_path = packet_dir / "OPENHANDS_DECISION_PACKET.json"
    packet = validate_json_artifact(recorder, "openhands_decision_packet_parse", packet_path)
    if not isinstance(packet, dict):
        return

    required = {
        "schema_version",
        "generated_by",
        "project_id",
        "created_utc",
        "source_run_dir",
        "canonical_repo",
        "worktree_path",
        "worktree_branch",
        "base_branch",
        "worktree_head",
        "prompt_source",
        "task_type",
        "task_override_used",
        "manual_allowed_files",
        "exit_status",
        "scope_status",
        "changed_files",
        "untracked_files",
        "tracked_modified_files",
        "staged_files",
        "worktree_changed",
        "canonical_repo_clean",
        "patch_file",
        "patch_sha256",
        "patch_nonempty",
        "recommendation",
    }
    missing = sorted(required - set(packet))
    if not missing:
        recorder.pass_check("openhands_decision_packet_required_fields", "Decision packet has required fields", path=packet_path)
    else:
        recorder.fail_check(
            "openhands_decision_packet_required_fields",
            "Decision packet is missing required fields",
            path=packet_path,
            details={"missing": missing},
        )

    if packet.get("generated_by") == "phase18g_openhands_decision_packet":
        recorder.pass_check("openhands_decision_packet_generated_by", "Decision packet generated_by is phase18g", path=packet_path)
    else:
        recorder.fail_check(
            "openhands_decision_packet_generated_by",
            f"Decision packet generated_by must be phase18g_openhands_decision_packet; found {packet.get('generated_by')!r}",
            path=packet_path,
        )

    patch_raw = packet.get("patch_file")
    patch_path = Path(patch_raw) if isinstance(patch_raw, str) and patch_raw else packet_dir / "OPENHANDS_PATCH.diff"
    if not patch_path.is_absolute():
        patch_path = packet_dir / patch_path
    if patch_path.exists():
        recorder.pass_check("openhands_decision_patch_exists", "Decision packet patch file exists", path=patch_path)
        actual_hash = sha256_file(patch_path)
        if packet.get("patch_sha256") == actual_hash:
            recorder.pass_check("openhands_decision_patch_sha256", "Decision packet patch_sha256 matches patch file", path=patch_path)
        else:
            recorder.fail_check(
                "openhands_decision_patch_sha256",
                "Decision packet patch_sha256 does not match patch file",
                path=patch_path,
                details={"expected": packet.get("patch_sha256"), "actual": actual_hash},
            )
    else:
        recorder.fail_check("openhands_decision_patch_exists", "Decision packet patch file is missing", path=patch_path)

    if packet.get("canonical_repo_clean") is True:
        recorder.pass_check("openhands_decision_canonical_repo_clean", "Decision packet reports canonical repo clean", path=packet_path)
    else:
        recorder.fail_check(
            "openhands_decision_canonical_repo_clean",
            "Decision packet must not report canonical repo writes; canonical_repo_clean must be true",
            path=packet_path,
        )

    scope = packet.get("scope_status") if isinstance(packet.get("scope_status"), dict) else {}
    scope_value = scope.get("scope_status") if isinstance(scope, dict) else None
    if scope_value == "fail":
        recorder.fail_check(
            "openhands_decision_scope_status_not_fail",
            f"Decision packet scope_status is fail: {scope.get('details', 'unknown') if isinstance(scope, dict) else 'unknown'}",
            path=packet_path,
        )
    elif scope_value in {"pass", "warn"}:
        recorder.pass_check("openhands_decision_scope_status_not_fail", f"Decision packet scope_status is {scope_value}", path=packet_path)
    else:
        recorder.fail_check(
            "openhands_decision_scope_status_value",
            f"Decision packet scope_status must be pass, warn, or fail; found {scope_value!r}",
            path=packet_path,
        )

    recommendation = packet.get("recommendation")
    allowed_recommendations = {
        "accept_for_manual_review",
        "discard_worktree",
        "hold_for_debug",
        "rerun_openhands",
        "human_review_required",
    }
    if recommendation in allowed_recommendations:
        recorder.pass_check("openhands_decision_recommendation_value", f"Decision packet recommendation is {recommendation!r}", path=packet_path)
    else:
        recorder.fail_check(
            "openhands_decision_recommendation_value",
            f"Decision packet recommendation is invalid: {recommendation!r}",
            path=packet_path,
        )

    if recommendation == "accept_for_manual_review":
        exit_status = packet.get("exit_status") if isinstance(packet.get("exit_status"), dict) else {}
        exit_pass = isinstance(exit_status, dict) and exit_status.get("status") == "pass" and exit_status.get("returncode") == 0 and exit_status.get("timed_out") is False
        accept_ok = (
            scope_value == "pass"
            and exit_pass
            and packet.get("patch_nonempty") is True
            and packet.get("canonical_repo_clean") is True
        )
        if accept_ok:
            recorder.pass_check("openhands_decision_accept_consistency", "accept_for_manual_review is consistent with pass/scope/patch/clean status", path=packet_path)
        else:
            recorder.fail_check(
                "openhands_decision_accept_consistency",
                "accept_for_manual_review requires exit pass, scope pass, nonempty patch, and clean canonical repo",
                path=packet_path,
            )


def validate_openhands_apply_status(recorder: CheckRecorder, coder_dir: Path) -> None:
    """Validate Phase 18I guarded OpenHands apply status artifacts."""
    apply_status_path = coder_dir / "OPENHANDS_APPLY_STATUS.json"

    if not apply_status_path.exists():
        recorder.pass_check(
            "openhands_apply_status_optional",
            "OPENHANDS_APPLY_STATUS.json is absent; optional Phase 18I apply gate artifacts not validated",
            path=apply_status_path,
        )
        return

    data = validate_json_artifact(
        recorder,
        "openhands_apply_status_parse",
        apply_status_path,
    )
    if data is None:
        return  # already recorded as fail above.

    # Check generated_by.
    gen_by = data.get("generated_by")
    if gen_by == "phase18i_guarded_openhands_patch_apply":
        recorder.pass_check(
            "openhands_apply_status_generated_by",
            "OPENHANDS_APPLY_STATUS.json generated_by is phase18i_guarded_openhands_patch_apply",
            path=apply_status_path,
        )
    else:
        recorder.fail_check(
            "openhands_apply_status_generated_by",
            f"OPENHANDS_APPLY_STATUS.json generated_by must be phase18i_guarded_openhands_patch_apply; found {gen_by!r}",
            path=apply_status_path,
        )

    # Check status is not fail.
    status = data.get("status")
    if status == "fail":
        recorder.fail_check(
            "openhands_apply_status_not_fail",
            f"OPENHANDS_APPLY_STATUS.json status must not be 'fail'; found {status!r}",
            path=apply_status_path,
        )
    elif status in ("pass", "warn"):
        recorder.pass_check(
            "openhands_apply_status_not_fail",
            f"OPENHANDS_APPLY_STATUS.json status is {status!r} (not fail)",
            path=apply_status_path,
        )

    # Check no_commit_push_merge_pr_performed.
    nc = data.get("no_commit_push_merge_pr_performed")
    if nc is True:
        recorder.pass_check(
            "openhands_apply_no_commit_push_merge_pr",
            "OPENHANDS_APPLY_STATUS.json no_commit_push_merge_pr_performed is true",
            path=apply_status_path,
        )
    else:
        recorder.fail_check(
            "openhands_apply_no_commit_push_merge_pr",
            f"OPENHANDS_APPLY_STATUS.json no_commit_push_merge_pr_performed must be true; found {nc!r}",
            path=apply_status_path,
        )

    # Check patch_sha256_verified.
    psv = data.get("patch_sha256_verified")
    if psv is True:
        recorder.pass_check(
            "openhands_apply_patch_sha_verified",
            "OPENHANDS_APPLY_STATUS.json patch sha256 verified",
            path=apply_status_path,
        )
    else:
        recorder.fail_check(
            "openhands_apply_patch_sha_verified",
            f"OPENHANDS_APPLY_STATUS.json patch sha256 must be verified; found {psv!r}",
            path=apply_status_path,
        )

    # Mode-specific checks.
    mode = data.get("mode")
    applied = data.get("applied", False)

    if mode == "check_only":
        # check-only pass requires canonical repo clean before and git_apply_check_passed true.
        crcb = data.get("canonical_repo_clean_before")
        if crcb is True:
            recorder.pass_check(
                "openhands_apply_check_only_clean_before",
                "OPENHANDS_APPLY_STATUS.json canonical_repo_clean_before is true (check-only)",
                path=apply_status_path,
            )
        else:
            recorder.fail_check(
                "openhands_apply_check_only_clean_before",
                f"check-only pass requires canonical_repo_clean_before=true; found {crcb!r}",
                path=apply_status_path,
            )

        gap = data.get("git_apply_check_passed")
        if gap is True:
            recorder.pass_check(
                "openhands_apply_check_only_git_apply_pass",
                "OPENHANDS_APPLY_STATUS.json git_apply_check_passed is true (check-only)",
                path=apply_status_path,
            )
        else:
            recorder.fail_check(
                "openhands_apply_check_only_git_apply_pass",
                f"check-only pass requires git_apply_check_passed=true; found {gap!r}",
                path=apply_status_path,
            )

    elif mode == "apply":
        # applied=true is allowed in apply mode; no extra requirement on canonical repo dirty state.
        if applied:
            recorder.pass_check(
                "openhands_apply_mode_applied",
                "OPENHANDS_APPLY_STATUS.json applied=true (apply mode)",
                path=apply_status_path,
            )

    # Validate markdown artifacts when JSON is present.
    validate_text_artifact(recorder, "openhands_apply_status_md_readable", coder_dir / "OPENHANDS_APPLY_STATUS.md")
    validate_text_artifact(
        recorder,
        "openhands_apply_review_commands_md_readable",
        coder_dir / "OPENHANDS_APPLY_REVIEW_COMMANDS.md",
    )


def validate_ai_readonly_artifacts(recorder: CheckRecorder, ai_dir: Path) -> None:
    """Validate Phase 18A AI read-only agent artifacts."""
    required_json = [
        ("ai_review_parse", "AI_READONLY_REVIEW.json"),
        ("ai_response_parsed_parse", "AI_RESPONSE_PARSED.json"),
        ("ai_safety_status_parse", "AI_SAFETY_STATUS.json"),
        ("ai_readonly_summary_parse", "AI_READONLY_SUMMARY.json"),
    ]
    required_text = [
        "AI_READONLY_REVIEW.md",
        "AI_PROMPT.md",
        "AI_RESPONSE_RAW.txt",
        "AI_READONLY_SUMMARY.md",
    ]

    parsed: dict[str, Any] = {}
    for check_id, filename in required_json:
        data = validate_json_artifact(recorder, check_id, ai_dir / filename)
        if data is not None:
            parsed[filename] = data

    for filename in required_text:
        validate_text_artifact(recorder, f"{filename}_readable", ai_dir / filename)

    # Validate AI_READONLY_REVIEW.json shape
    review = parsed.get("AI_READONLY_REVIEW.json")
    if isinstance(review, dict):
        recorder.pass_check(
            "ai_review_agent_role",
            f"AI_READONLY_REVIEW.json agent is {review.get('agent', 'unknown')!r}",
            path=ai_dir / "AI_READONLY_REVIEW.json",
        )
        status = review.get("status") if isinstance(review, dict) else None
        # The review itself doesn't have a top-level status field in the same way;
        # its recommendation is advisory. Check generated_by instead.
        gen_by = review.get("generated_by")
        if gen_by == "deterministic_scaffold":
            recorder.pass_check(
                "ai_review_generated_by",
                "AI_READONLY_REVIEW.json generated_by is deterministic_scaffold",
                path=ai_dir / "AI_READONLY_REVIEW.json",
            )

    # Validate AI_RESPONSE_PARSED.json shape
    parsed_resp = parsed.get("AI_RESPONSE_PARSED.json")
    if isinstance(parsed_resp, dict):
        resp_status = parsed_resp.get("status")
        if resp_status in ("pass", "warn", "fail"):
            recorder.pass_check(
                "ai_response_parsed_status_valid",
                f"AI_RESPONSE_PARSED.json status is {resp_status!r}",
                path=ai_dir / "AI_RESPONSE_PARSED.json",
            )
        else:
            recorder.fail_check(
                "ai_response_parsed_status_valid",
                f"AI_RESPONSE_PARSED.json status must be pass, warn, or fail; found {resp_status!r}",
                path=ai_dir / "AI_RESPONSE_PARSED.json",
            )

    # Validate AI_SAFETY_STATUS.json — deny dangerous operations
    safety = parsed.get("AI_SAFETY_STATUS.json")
    if isinstance(safety, dict):
        dangerous_checks = [
            ("source_writes_allowed", False),
            ("openhands_execution_allowed", False),
            ("auto_push_allowed", False),
            ("auto_merge_allowed", False),
            ("pr_creation_allowed", False),
        ]
        for key, expected in dangerous_checks:
            actual = safety.get(key)
            if actual == expected:
                recorder.pass_check(
                    f"ai_safety_{key}",
                    f"safety_status.{key} is {expected}",
                    path=ai_dir / "AI_SAFETY_STATUS.json",
                )
            else:
                recorder.fail_check(
                    f"ai_safety_{key}",
                    f"safety_status.{key} must be {expected}; found {actual!r}. This is a blocking safety violation.",
                    path=ai_dir / "AI_SAFETY_STATUS.json",
                )

        # Validate model_call_performed is boolean or null
        mcp = safety.get("model_call_performed")
        if isinstance(mcp, bool):
            recorder.pass_check(
                "ai_safety_model_call_performed_bool",
                f"safety_status.model_call_performed is {mcp}",
                path=ai_dir / "AI_SAFETY_STATUS.json",
            )
        else:
            recorder.fail_check(
                "ai_safety_model_call_performed_bool",
                f"safety_status.model_call_performed must be boolean; found {mcp!r}",
                path=ai_dir / "AI_SAFETY_STATUS.json",
            )

    # Validate AI_READONLY_SUMMARY.json shape
    summary = parsed.get("AI_READONLY_SUMMARY.json")
    if isinstance(summary, dict):
        gen_by = summary.get("generated_by")
        if gen_by == "phase18a_ai_readonly_agent":
            recorder.pass_check(
                "ai_summary_generated_by",
                "AI_READONLY_SUMMARY.json generated_by is phase18a_ai_readonly_agent",
                path=ai_dir / "AI_READONLY_SUMMARY.json",
            )
        else:
            recorder.fail_check(
                "ai_summary_generated_by",
                f"AI_READONLY_SUMMARY.json generated_by must be 'phase18a_ai_readonly_agent'; found {gen_by!r}",
                path=ai_dir / "AI_READONLY_SUMMARY.json",
            )

        # Model call is optional — just validate it's boolean if present
        mcp = summary.get("model_call_performed")
        if isinstance(mcp, bool):
            recorder.pass_check(
                "ai_summary_model_call_performed_bool",
                f"summary model_call_performed is {mcp}",
                path=ai_dir / "AI_READONLY_SUMMARY.json",
            )


def phase20_overnight_summary_allows_gated_code_writing(data: Any) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not isinstance(data, dict):
        return False, ["summary is not an object"]
    if data.get("generated_by") != OVERNIGHT_OPENHANDS_GENERATED_BY:
        failures.append("generated_by is not Phase 20")
    if data.get("max_write_tasks") != 1:
        failures.append("max_write_tasks is not 1")
    if data.get("max_retries_per_task") != 1:
        failures.append("max_retries_per_task is not 1")

    attempts = data.get("attempts")
    if not isinstance(attempts, list):
        failures.append("attempts is not a list")
        attempts = []
    elif len(attempts) > 2:
        failures.append("attempts has more than 2 entries")

    if data.get("applied") is not False:
        failures.append("summary applied is not false")
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            failures.append(f"attempt {index} is not an object")
            continue
        if attempt.get("applied") is not False:
            failures.append(f"attempt {index} applied is not false")

    if data.get("apply_mode") != "check_only":
        failures.append("apply_mode is not check_only")
    if data.get("canonical_repo_clean_after") is not True:
        failures.append("canonical_repo_clean_after is not true")
    if data.get("no_apply_commit_push_merge_pr_or_cleanup_performed") is not True:
        failures.append("no apply/commit/push/merge/PR/cleanup invariant is not true")

    allowed_files = data.get("allowed_files")
    changed_files = data.get("changed_files")
    if not isinstance(allowed_files, list) or not all(isinstance(path, str) for path in allowed_files):
        failures.append("allowed_files is not a string list")
        allowed = set()
    else:
        allowed = set(allowed_files)
    if not isinstance(changed_files, list) or not all(isinstance(path, str) for path in changed_files):
        failures.append("changed_files is not a string list")
        changed: list[str] = []
    else:
        changed = changed_files
    outside_allowed = sorted(path for path in changed if path not in allowed)
    if outside_allowed:
        failures.append(f"changed_files outside allowed_files: {outside_allowed}")
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            continue
        attempt_changed = attempt.get("changed_files", [])
        if not isinstance(attempt_changed, list) or not all(isinstance(path, str) for path in attempt_changed):
            failures.append(f"attempt {index} changed_files is not a string list")
            continue
        attempt_outside_allowed = sorted(path for path in attempt_changed if path not in allowed)
        if attempt_outside_allowed:
            failures.append(f"attempt {index} changed_files outside allowed_files: {attempt_outside_allowed}")

    status = data.get("status")
    if status == "pass":
        if data.get("decision_recommendation") != "accept_for_manual_review":
            failures.append("pass summary decision_recommendation is not accept_for_manual_review")
        if data.get("apply_check_passed") is not True:
            failures.append("pass summary apply_check_passed is not true")
    elif status == "blocked":
        if data.get("blocked") is not True:
            failures.append("blocked summary blocked is not true")
        action = data.get("recommended_human_action")
        if not isinstance(action, str) or not action.strip():
            failures.append("blocked summary recommended_human_action is empty")
    else:
        failures.append("status is not pass or blocked")

    return not failures, failures


def phase20_overnight_summary_paths_for_approval(approval_dir: Path, nightly_window_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    if nightly_window_dir is not None:
        paths.append(nightly_window_dir / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json")
    run_root = approval_dir.parent
    latest_nightly = run_root / "latest_nightly_window"
    if latest_nightly.exists() or latest_nightly.is_symlink():
        paths.append(latest_nightly / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json")
    paths.extend(sorted(run_root.glob("nightly_window_*/OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"), reverse=True))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def approval_packet_safety_status_is_strict(safety: Any) -> bool:
    if not isinstance(safety, dict):
        return False
    return (
        safety.get("model_calls_allowed") is False
        and safety.get("openhands_allowed") is False
        and safety.get("source_writes_allowed") is False
        and safety.get("github_pr_created") is False
        and safety.get("branch_pushed") is False
        and safety.get("merge_performed") is False
        and safety.get("auto_merge_allowed") is False
        and safety.get("auto_push_allowed") is False
        and safety.get("auto_apply_allowed", False) is False
        and safety.get("cleanup_allowed", False) is False
        and safety.get("worktree_cleanup_allowed", False) is False
        and safety.get("max_code_writing_tasks") == 0
    )


def approval_packet_safety_status_is_phase20_gated(safety: Any, approval_dir: Path, nightly_window_dir: Path | None) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    if not isinstance(safety, dict):
        return False, {"reason": "safety_status is not an object"}
    non_code_denials = (
        safety.get("model_calls_allowed") is False
        and safety.get("source_writes_allowed") is False
        and safety.get("github_pr_created") is False
        and safety.get("branch_pushed") is False
        and safety.get("merge_performed") is False
        and safety.get("auto_merge_allowed") is False
        and safety.get("auto_push_allowed") is False
        and safety.get("auto_apply_allowed", False) is False
        and safety.get("cleanup_allowed", False) is False
        and safety.get("worktree_cleanup_allowed", False) is False
    )
    if not non_code_denials:
        return False, {"reason": "non-code write safety flags are not denied"}
    if safety.get("openhands_allowed") not in {False, True} or safety.get("max_code_writing_tasks") != 1:
        return False, {"reason": "Phase 20 requires max_code_writing_tasks 1 and bounded OpenHands allowance"}

    summary_paths = phase20_overnight_summary_paths_for_approval(approval_dir, nightly_window_dir)
    if not summary_paths:
        return False, {"reason": "no nightly window is available"}
    checked: list[dict[str, Any]] = []
    for summary_path in summary_paths:
        data, error = load_json_file(summary_path)
        if error is not None:
            checked.append({"summary_path": str(summary_path), "failure": error})
            continue
        ok, failures = phase20_overnight_summary_allows_gated_code_writing(data)
        if ok:
            details["summary_path"] = str(summary_path)
            if summary_path != summary_paths[0]:
                details["summary_source"] = "historical_phase20_nightly_window"
            return True, details
        checked.append({"summary_path": str(summary_path), "failures": failures})
    return False, {"checked_summaries": checked}


def validate_human_approval_artifacts(recorder: CheckRecorder, approval_dir: Path, nightly_window_dir: Path | None = None) -> None:
    packet = validate_json_artifact(recorder, "approval_packet_parse", approval_dir / "APPROVAL_PACKET.json")
    summary = validate_json_artifact(
        recorder,
        "approval_summary_parse",
        approval_dir / "APPROVAL_SUMMARY.json",
        required_status="pass",
    )
    decision = validate_json_artifact(recorder, "human_decision_template_parse", approval_dir / "HUMAN_DECISION_TEMPLATE.json")
    validate_text_artifact(recorder, "approval_packet_markdown_readable", approval_dir / "APPROVAL_PACKET.md")
    validate_text_artifact(recorder, "draft_pr_plan_readable", approval_dir / "DRAFT_PR_PLAN.md")
    validate_text_artifact(recorder, "pr_body_draft_readable", approval_dir / "PR_BODY_DRAFT.md")
    validate_text_artifact(recorder, "resume_instructions_readable", approval_dir / "RESUME_INSTRUCTIONS.md")
    validate_text_artifact(recorder, "approval_summary_markdown_readable", approval_dir / "APPROVAL_SUMMARY.md")

    if isinstance(packet, dict):
        required = {
            "schema_version",
            "project_id",
            "created_utc",
            "selected_objective",
            "latest_validation_status",
            "latest_review_agent_status",
            "latest_model_routing_status",
            "nightly_window_status",
            "safety_status",
            "generated_artifacts",
            "changed_files",
            "recommended_human_decision",
            "no_merge_push_or_pr_created",
        }
        missing = sorted(required - set(packet))
        if not missing:
            recorder.pass_check("approval_packet_required_fields", "Approval packet has required fields", path=approval_dir / "APPROVAL_PACKET.json")
        else:
            recorder.fail_check(
                "approval_packet_required_fields",
                "Approval packet is missing required fields",
                path=approval_dir / "APPROVAL_PACKET.json",
                details={"missing": missing},
            )
        if packet.get("generated_by") == "deterministic_human_approval_scaffold":
            recorder.pass_check("approval_packet_generated_by", "Approval packet generated_by is deterministic", path=approval_dir / "APPROVAL_PACKET.json")
        else:
            recorder.fail_check("approval_packet_generated_by", "Approval packet generated_by must be deterministic_human_approval_scaffold", path=approval_dir / "APPROVAL_PACKET.json")
        safety = packet.get("safety_status")
        if approval_packet_safety_status_is_strict(safety):
            recorder.pass_check("approval_packet_safety_flags", "Approval packet preserves default safety flags", path=approval_dir / "APPROVAL_PACKET.json")
        else:
            phase20_ok, phase20_details = approval_packet_safety_status_is_phase20_gated(safety, approval_dir, nightly_window_dir)
            if phase20_ok:
                recorder.pass_check(
                    "approval_packet_safety_flags",
                    "Approval packet allows only the gated Phase 20 OpenHands write task and denies apply/commit/push/merge/PR/cleanup",
                    path=approval_dir / "APPROVAL_PACKET.json",
                    details=phase20_details,
                )
            else:
                recorder.fail_check(
                    "approval_packet_safety_flags",
                    "Approval packet must deny models, source writes, PR creation, push, merge, auto-apply, cleanup, and code writing unless a safe Phase 20 overnight summary bounds the single OpenHands write task",
                    path=approval_dir / "APPROVAL_PACKET.json",
                    details=phase20_details,
                )
        if packet.get("recommended_human_decision") in {"accept", "revise", "discard", "hold"}:
            recorder.pass_check("approval_packet_decision_value", "Approval packet recommended decision is valid", path=approval_dir / "APPROVAL_PACKET.json")
        else:
            recorder.fail_check("approval_packet_decision_value", "Approval packet recommended decision must be accept, revise, discard, or hold", path=approval_dir / "APPROVAL_PACKET.json")
        if packet.get("no_merge_push_or_pr_created") is True:
            recorder.pass_check("approval_packet_no_pr_push_merge", "Approval packet states no PR, push, or merge occurred", path=approval_dir / "APPROVAL_PACKET.json")
        else:
            recorder.fail_check("approval_packet_no_pr_push_merge", "Approval packet must state no PR, push, or merge occurred", path=approval_dir / "APPROVAL_PACKET.json")

    if isinstance(decision, dict):
        denied = (
            decision.get("approved_for_source_writes") is False
            and decision.get("approved_for_model_calls") is False
            and decision.get("approved_for_openhands") is False
        )
        if denied:
            recorder.pass_check("human_decision_template_denies_future_capabilities", "Human decision template denies source writes, model calls, and OpenHands by default", path=approval_dir / "HUMAN_DECISION_TEMPLATE.json")
        else:
            recorder.fail_check("human_decision_template_denies_future_capabilities", "Human decision template must deny source writes, model calls, and OpenHands by default", path=approval_dir / "HUMAN_DECISION_TEMPLATE.json")
        if decision.get("decision") in {"accept", "revise", "discard", "hold"}:
            recorder.pass_check("human_decision_template_decision_value", "Human decision template default decision is valid", path=approval_dir / "HUMAN_DECISION_TEMPLATE.json")
        else:
            recorder.fail_check("human_decision_template_decision_value", "Human decision template decision must be accept, revise, discard, or hold", path=approval_dir / "HUMAN_DECISION_TEMPLATE.json")

    try:
        draft = (approval_dir / "DRAFT_PR_PLAN.md").read_text()
    except OSError:
        draft = ""
    if "gh pr create --draft" in draft and "No GitHub command was executed" in draft:
        recorder.pass_check("draft_pr_text_only", "Draft PR plan contains text-only gh command", path=approval_dir / "DRAFT_PR_PLAN.md")
    else:
        recorder.fail_check("draft_pr_text_only", "Draft PR plan must contain a text-only gh pr create --draft command", path=approval_dir / "DRAFT_PR_PLAN.md")

    if isinstance(summary, dict) and isinstance(packet, dict):
        if summary.get("recommended_human_decision") == packet.get("recommended_human_decision"):
            recorder.pass_check("approval_summary_matches_packet", "Approval summary matches packet recommendation", path=approval_dir / "APPROVAL_SUMMARY.json")
        else:
            recorder.fail_check(
                "approval_summary_matches_packet",
                "Approval summary must match packet recommendation",
                path=approval_dir / "APPROVAL_SUMMARY.json",
                details={"summary": summary.get("recommended_human_decision"), "packet": packet.get("recommended_human_decision")},
            )


def validate_systemd_artifacts(recorder: CheckRecorder) -> None:
    service_path = ROOT / "systemd" / "agent-manager-nightly@.service"
    timer_path = ROOT / "systemd" / "agent-manager-nightly@.timer"
    install_path = ROOT / "scripts" / "install_nightly_timer.sh"
    check_path = ROOT / "scripts" / "check_nightly_timer.sh"
    policy_path = ROOT / "configs" / "nightly_window_policy.json"

    validate_text_artifact(recorder, "systemd_nightly_service_readable", service_path)
    validate_text_artifact(recorder, "systemd_nightly_timer_readable", timer_path)
    validate_text_artifact(recorder, "install_nightly_timer_readable", install_path)
    validate_text_artifact(recorder, "check_nightly_timer_readable", check_path)
    policy = validate_json_artifact(recorder, "nightly_window_policy_parse", policy_path)

    try:
        service = service_path.read_text()
        timer = timer_path.read_text()
        install = install_path.read_text()
        check = check_path.read_text()
    except OSError:
        return

    active_service_lines = [
        line.strip()
        for line in service.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    service_checks = {
        "systemd_service_no_user": not any(line.startswith("User=") for line in active_service_lines),
        "systemd_service_no_group": not any(line.startswith("Group=") for line in active_service_lines),
        "systemd_service_workdir": "WorkingDirectory=/home/qreed/agent-manager" in service,
        "systemd_service_venv_path": "Environment=PATH=/home/qreed/agent-manager/.venv/bin:/usr/local/bin:/usr/bin:/bin" in service,
        "systemd_service_project_template": "run_nightly_window.py %i" in service,
        "systemd_service_venv_python": "/home/qreed/agent-manager/.venv/bin/python" in service,
        "systemd_service_no_model_calls": "AGENT_MANAGER_NO_MODEL_CALLS=1" in service,
        "systemd_service_no_openhands": "AGENT_MANAGER_NO_OPENHANDS=1" in service,
        "systemd_service_no_code_writing": "AGENT_MANAGER_MAX_CODE_WRITING_TASKS=0" in service,
        "systemd_service_no_indefinite_restart": "Restart=no" in service,
    }
    for check_id, passed in service_checks.items():
        if passed:
            recorder.pass_check(check_id, f"{check_id} is present", path=service_path)
        else:
            recorder.fail_check(check_id, f"{check_id} is missing", path=service_path)
    if "User=root" not in service:
        recorder.pass_check("systemd_service_not_root", "Nightly service does not run as root", path=service_path)
    else:
        recorder.fail_check("systemd_service_not_root", "Nightly service must not run as root", path=service_path)

    timer_checks = {
        "systemd_timer_2300": "OnCalendar=*-*-* 23:00:00" in timer,
        "systemd_timer_no_random_delay": "RandomizedDelaySec" not in "\n".join(
            line for line in timer.splitlines() if not line.strip().startswith("#")
        ),
        "systemd_timer_persistent_documented": "Persistent=true" in timer and "Persistent=true lets user systemd" in timer,
    }
    for check_id, passed in timer_checks.items():
        if passed:
            recorder.pass_check(check_id, f"{check_id} is present", path=timer_path)
        else:
            recorder.fail_check(check_id, f"{check_id} is missing", path=timer_path)

    install_checks = {
        "install_user_unit_dir": ".config}/systemd/user" in install or ".config/systemd/user" in install,
        "install_daemon_reload_user": "systemctl --user daemon-reload" in install,
        "install_enable_timer": "systemctl --user enable \"$TIMER_NAME\"" in install,
        "install_no_default_run_now": "RUN_NOW=0" in install and "No immediate nightly run was started" in install,
        "install_validates_runner": "scripts/run_nightly_window.py" in install and "Missing nightly runner" in install,
        "install_validates_python": ".venv/bin/python" in install and "Missing executable venv python" in install,
    }
    for check_id, passed in install_checks.items():
        if passed:
            recorder.pass_check(check_id, f"{check_id} is present", path=install_path)
        else:
            recorder.fail_check(check_id, f"{check_id} is missing", path=install_path)

    check_script_checks = {
        "check_status_timer": "systemctl --user status \"$TIMER_NAME\"" in check,
        "check_list_timers": "systemctl --user list-timers" in check,
        "check_journal_logs": "journalctl --user -u \"$SERVICE_NAME\"" in check,
    }
    for check_id, passed in check_script_checks.items():
        if passed:
            recorder.pass_check(check_id, f"{check_id} is present", path=check_path)
        else:
            recorder.fail_check(check_id, f"{check_id} is missing", path=check_path)

    if isinstance(policy, dict) and policy.get("max_code_writing_tasks") == 0:
        recorder.pass_check("nightly_policy_code_writing_disabled", "Nightly policy keeps max_code_writing_tasks at 0", path=policy_path)
    elif isinstance(policy, dict):
        recorder.fail_check("nightly_policy_code_writing_disabled", "Nightly policy must keep max_code_writing_tasks at 0", path=policy_path)


def validate_nightly_window_artifacts(recorder: CheckRecorder, nightly_window_dir: Path) -> None:
    manifest = validate_json_artifact(
        recorder,
        "nightly_window_manifest_parse",
        nightly_window_dir / "NIGHTLY_WINDOW_MANIFEST.json",
        required_status="pass",
    )
    timeline = validate_json_artifact(recorder, "nightly_window_timeline_parse", nightly_window_dir / "NIGHTLY_WINDOW_TIMELINE.json")
    pass_summary = validate_json_artifact(
        recorder,
        "nightly_pass_summary_parse",
        nightly_window_dir / "NIGHTLY_PASS_SUMMARY.json",
        required_status="pass",
    )
    safety = validate_json_artifact(
        recorder,
        "nightly_safety_status_parse",
        nightly_window_dir / "NIGHTLY_SAFETY_STATUS.json",
        required_status="pass",
    )
    validate_text_artifact(recorder, "morning_handoff_readable", nightly_window_dir / "MORNING_HANDOFF.md")

    if isinstance(manifest, dict):
        required = {
            "project_id",
            "created_utc",
            "selected_objective_id",
            "policy",
            "pass_count",
            "max_manager_passes",
            "max_code_writing_tasks",
            "model_calls_allowed",
            "openhands_allowed",
            "source_writes_allowed",
            "status",
        }
        missing = sorted(required - set(manifest))
        if not missing:
            recorder.pass_check("nightly_window_manifest_required_fields", "Nightly window manifest has required fields", path=nightly_window_dir / "NIGHTLY_WINDOW_MANIFEST.json")
        else:
            recorder.fail_check(
                "nightly_window_manifest_required_fields",
                "Nightly window manifest is missing required fields",
                path=nightly_window_dir / "NIGHTLY_WINDOW_MANIFEST.json",
                details={"missing": missing},
            )
        policy = manifest.get("policy")
        write_task_count = manifest.get("overnight_write_task_count", 0)
        if (
            isinstance(policy, dict)
            and policy.get("max_code_writing_tasks") == 0
            and (
                (manifest.get("max_code_writing_tasks") == 0 and write_task_count == 0)
                or (manifest.get("max_code_writing_tasks") == 1 and write_task_count == 1)
            )
        ):
            recorder.pass_check("nightly_window_no_code_writing_tasks", "Nightly window write-task count is within allowed Phase 20 bounds", path=nightly_window_dir)
        else:
            recorder.fail_check("nightly_window_no_code_writing_tasks", "Nightly window permits too many write-capable tasks", path=nightly_window_dir)
        if (
            manifest.get("model_calls_allowed") is False
            and manifest.get("openhands_allowed") in {False, True}
            and manifest.get("source_writes_allowed") is False
            and manifest.get("auto_merge_allowed") is False
            and manifest.get("auto_push_allowed") is False
            and write_task_count in {0, 1}
        ):
            recorder.pass_check("nightly_window_safety_flags", "Nightly window safety flags keep models disabled and write task count bounded", path=nightly_window_dir)
        else:
            recorder.fail_check("nightly_window_safety_flags", "Nightly window safety flags are outside Phase 20 bounds", path=nightly_window_dir)
        if write_task_count <= 1:
            recorder.pass_check("nightly_window_write_task_limit", "Nightly manifest has no more than one write-capable OpenHands task", path=nightly_window_dir)
        else:
            recorder.fail_check("nightly_window_write_task_limit", "Nightly manifest must not contain more than one write-capable OpenHands task", path=nightly_window_dir)

    if isinstance(timeline, dict):
        passes = timeline.get("passes")
        if isinstance(passes, list) and all(isinstance(item, dict) for item in passes):
            recorder.pass_check("nightly_window_timeline_passes", "Nightly window timeline has pass entries", path=nightly_window_dir / "NIGHTLY_WINDOW_TIMELINE.json")
        else:
            recorder.fail_check("nightly_window_timeline_passes", "Nightly window timeline must contain a passes list", path=nightly_window_dir / "NIGHTLY_WINDOW_TIMELINE.json")
    if isinstance(manifest, dict) and isinstance(pass_summary, dict):
        if manifest.get("pass_count") == pass_summary.get("pass_count"):
            recorder.pass_check("nightly_window_pass_count_consistent", "Nightly window pass counts are consistent", path=nightly_window_dir)
        else:
            recorder.fail_check(
                "nightly_window_pass_count_consistent",
                "Nightly window manifest and pass summary counts must match",
                path=nightly_window_dir,
                details={"manifest": manifest.get("pass_count"), "summary": pass_summary.get("pass_count")},
            )
    if isinstance(safety, dict):
        if (
            safety.get("model_calls_allowed") is False
            and safety.get("openhands_allowed") in {False, True}
            and safety.get("source_writes_allowed") is False
            and safety.get("max_code_writing_tasks") in {0, 1}
        ):
            recorder.pass_check("nightly_safety_status_control_plane_only", "Nightly safety status stays within Phase 20 write-task bounds", path=nightly_window_dir / "NIGHTLY_SAFETY_STATUS.json")
        else:
            recorder.fail_check("nightly_safety_status_control_plane_only", "Nightly safety status exceeds Phase 20 bounds", path=nightly_window_dir / "NIGHTLY_SAFETY_STATUS.json")

    overnight_summary_path = nightly_window_dir / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"
    if overnight_summary_path.exists():
        validate_overnight_openhands_write_summary(recorder, overnight_summary_path)
        validate_text_artifact(recorder, "overnight_openhands_morning_report_readable", nightly_window_dir / "OVERNIGHT_OPENHANDS_MORNING_REPORT.md")


def validate_overnight_openhands_write_summary(recorder: CheckRecorder, summary_path: Path) -> None:
    data = validate_json_artifact(recorder, "overnight_openhands_write_summary_parse", summary_path)
    if not isinstance(data, dict):
        recorder.fail_check("overnight_openhands_write_summary_object", "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json must be an object", path=summary_path)
        return
    if data.get("generated_by") == OVERNIGHT_OPENHANDS_GENERATED_BY:
        recorder.pass_check("overnight_openhands_generated_by", "Overnight OpenHands summary generated_by is Phase 20", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_generated_by", f"Overnight OpenHands summary generated_by is invalid: {data.get('generated_by')!r}", path=summary_path)
    if data.get("max_write_tasks") == 1:
        recorder.pass_check("overnight_openhands_max_write_tasks", "max_write_tasks is 1", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_max_write_tasks", f"max_write_tasks must be 1; found {data.get('max_write_tasks')!r}", path=summary_path)
    if data.get("max_retries_per_task") == 1:
        recorder.pass_check("overnight_openhands_max_retries", "max_retries_per_task is 1", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_max_retries", f"max_retries_per_task must be 1; found {data.get('max_retries_per_task')!r}", path=summary_path)
    attempts = data.get("attempts")
    if isinstance(attempts, list) and len(attempts) <= 2:
        recorder.pass_check("overnight_openhands_attempt_count", "attempt count is no more than 2", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_attempt_count", "attempts must be a list with no more than 2 entries", path=summary_path)
        attempts = attempts if isinstance(attempts, list) else []
    for attempt in attempts:
        if isinstance(attempt, dict) and attempt.get("applied") is False:
            recorder.pass_check("overnight_openhands_attempt_not_applied", f"attempt {attempt.get('attempt_number')} did not apply a patch", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_attempt_not_applied", "every overnight OpenHands attempt must have applied false", path=summary_path)
    if data.get("no_apply_commit_push_merge_pr_or_cleanup_performed") is True:
        recorder.pass_check("overnight_openhands_no_apply_commit_push", "No apply/commit/push/merge/PR/cleanup invariant is true", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_no_apply_commit_push", "No apply/commit/push/merge/PR/cleanup invariant must be true", path=summary_path)
    if data.get("canonical_repo_clean_after") is True:
        recorder.pass_check("overnight_openhands_canonical_clean_after", "canonical repo clean after is true", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_canonical_clean_after", "canonical repo must be clean after overnight OpenHands run", path=summary_path)
    if data.get("applied") is False:
        recorder.pass_check("overnight_openhands_not_applied", "summary applied is false", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_not_applied", "summary applied must be false", path=summary_path)

    safe_for_approval, safety_failures = phase20_overnight_summary_allows_gated_code_writing(data)
    if safe_for_approval:
        recorder.pass_check("overnight_openhands_phase20_gated_safety", "Phase 20 overnight summary is safe for gated approval-packet code-writing allowance", path=summary_path)
    else:
        recorder.fail_check(
            "overnight_openhands_phase20_gated_safety",
            "Phase 20 overnight summary is not safe for gated approval-packet code-writing allowance",
            path=summary_path,
            details={"failures": safety_failures},
        )

    status = data.get("status")
    if status == "pass":
        allowed = set(str(path) for path in data.get("allowed_files", []) if isinstance(path, str))
        changed = [str(path) for path in data.get("changed_files", []) if isinstance(path, str)]
        if data.get("selected_attempt_status") == "pass":
            recorder.pass_check("overnight_openhands_pass_selected_attempt", "selected attempt status is pass", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_pass_selected_attempt", "pass summary requires selected attempt status pass", path=summary_path)
        if data.get("decision_recommendation") == "accept_for_manual_review":
            recorder.pass_check("overnight_openhands_pass_decision", "decision recommendation is accept_for_manual_review", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_pass_decision", "pass summary requires accept_for_manual_review", path=summary_path)
        if data.get("apply_mode") == "check_only":
            recorder.pass_check("overnight_openhands_pass_apply_mode", "apply mode is check_only", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_pass_apply_mode", "pass summary requires apply_mode check_only", path=summary_path)
        if data.get("apply_check_passed") is True:
            recorder.pass_check("overnight_openhands_pass_apply_check", "apply check passed", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_pass_apply_check", "pass summary requires apply_check_passed true", path=summary_path)
        if changed and all(path in allowed for path in changed):
            recorder.pass_check("overnight_openhands_pass_changed_files", "changed files are nonempty and within allowed files", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_pass_changed_files", "pass summary requires nonempty changed_files within allowed_files", path=summary_path)
    elif status == "blocked":
        if data.get("blocked") is True and data.get("blocked_reason") and data.get("recommended_human_action"):
            recorder.pass_check("overnight_openhands_blocked_shape", "blocked summary has reason and recommended action", path=summary_path)
        else:
            recorder.fail_check("overnight_openhands_blocked_shape", "blocked summary requires blocked true, blocked_reason, and recommended_human_action", path=summary_path)
    else:
        recorder.fail_check("overnight_openhands_status", f"Overnight OpenHands summary status must be pass or blocked; found {status!r}", path=summary_path)


def validate_model_routing_plan(
    recorder: CheckRecorder,
    check_id: str,
    path: Path,
) -> dict[str, Any] | None:
    data = validate_json_artifact(recorder, check_id, path)
    if not isinstance(data, dict):
        recorder.fail_check(f"{check_id}_shape", f"{path.name} must be a JSON object", path=path)
        return None

    required = {
        "schema_version": 1,
        "generated_by": "deterministic_model_routing_scaffold",
    }
    for key, expected in required.items():
        actual = data.get(key)
        if actual == expected:
            recorder.pass_check(f"{check_id}_{key}", f"{path.name} {key} is {expected!r}", path=path)
        else:
            recorder.fail_check(f"{check_id}_{key}", f"{path.name} {key} must be {expected!r}; found {actual!r}", path=path)

    status = data.get("status")
    if status in {"pass", "warn", "fail"}:
        recorder.pass_check(f"{check_id}_status_value", f"{path.name} status is valid", path=path)
    else:
        recorder.fail_check(f"{check_id}_status_value", f"{path.name} status must be pass, warn, or fail; found {status!r}", path=path)

    return data


def validate_model_routing_assignments(recorder: CheckRecorder, path: Path) -> dict[str, Any] | None:
    data = validate_model_routing_plan(recorder, "task_model_assignments_parse", path)
    if not isinstance(data, dict):
        return None

    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        recorder.fail_check("task_model_assignments_list", "TASK_MODEL_ASSIGNMENTS.json assignments must be a list", path=path)
        return data
    recorder.pass_check("task_model_assignments_list", "TASK_MODEL_ASSIGNMENTS.json assignments is a list", path=path)

    write_capable = []
    non_coding_write = []
    non_coding_not_read_only = []
    missing_fields = []
    execution_violations = []
    for item in assignments:
        if not isinstance(item, dict):
            missing_fields.append({"assignment": item, "missing": ["object"]})
            continue
        required_keys = {"role", "permission", "model_reference", "rationale"}
        missing = sorted(required_keys - set(item))
        if missing:
            missing_fields.append({"assignment_id": item.get("assignment_id"), "missing": missing})
        permission = item.get("permission")
        if not isinstance(permission, dict):
            missing_fields.append({"assignment_id": item.get("assignment_id"), "missing": ["permission_object"]})
            continue
        if permission.get("write_capable") is True:
            write_capable.append(item)
            if item.get("role") != "coding_agent":
                non_coding_write.append(item)
        if item.get("role") != "coding_agent" and permission.get("read_only") is not True:
            non_coding_not_read_only.append(item)
        if any(
            permission.get(key) is True
            for key in (
                "execution_enabled",
                "model_calls_enabled",
                "openhands_execution_enabled",
                "source_writes_enabled",
                "auto_merge_enabled",
                "auto_push_enabled",
                "permission_expansion_allowed",
            )
        ):
            execution_violations.append(item)

    if not missing_fields:
        recorder.pass_check("model_assignment_required_fields", "Every model assignment has required fields", path=path)
    else:
        recorder.fail_check("model_assignment_required_fields", "Model assignments are missing required fields", path=path, details={"missing": missing_fields})

    if len(write_capable) <= 1:
        recorder.pass_check("model_assignment_max_one_write_capable", "At most one assignment is write-capable", path=path, details={"count": len(write_capable)})
    else:
        recorder.fail_check("model_assignment_max_one_write_capable", "More than one assignment is write-capable", path=path, details={"count": len(write_capable)})

    if not non_coding_write:
        recorder.pass_check("model_assignment_only_coding_write_capable", "Only coding_agent can be write-capable", path=path)
    else:
        recorder.fail_check(
            "model_assignment_only_coding_write_capable",
            "A non-coding role is write-capable",
            path=path,
            details={"assignment_ids": [item.get("assignment_id") for item in non_coding_write]},
        )

    if not non_coding_not_read_only:
        recorder.pass_check("model_assignment_non_coding_read_only", "Non-coding model roles are read-only", path=path)
    else:
        recorder.fail_check(
            "model_assignment_non_coding_read_only",
            "A non-coding role is not read-only",
            path=path,
            details={"assignment_ids": [item.get("assignment_id") for item in non_coding_not_read_only]},
        )

    if not execution_violations:
        recorder.pass_check("model_assignment_no_execution", "Model routing assignments do not enable execution or permission expansion", path=path)
    else:
        recorder.fail_check(
            "model_assignment_no_execution",
            "One or more model routing assignments enables execution or permission expansion",
            path=path,
            details={"assignment_ids": [item.get("assignment_id") for item in execution_violations]},
        )

    return data


def validate_model_routing_artifacts(recorder: CheckRecorder, model_routing_dir: Path) -> None:
    plan = validate_model_routing_plan(recorder, "model_routing_plan_parse", model_routing_dir / "MODEL_ROUTING_PLAN.json")
    assignments = validate_model_routing_assignments(recorder, model_routing_dir / "TASK_MODEL_ASSIGNMENTS.json")
    summary = validate_model_routing_plan(recorder, "model_routing_summary_parse", model_routing_dir / "MODEL_ROUTING_SUMMARY.json")
    validate_text_artifact(recorder, "model_routing_plan_markdown_readable", model_routing_dir / "MODEL_ROUTING_PLAN.md")
    validate_text_artifact(recorder, "model_routing_summary_markdown_readable", model_routing_dir / "MODEL_ROUTING_SUMMARY.md")

    if isinstance(plan, dict) and isinstance(summary, dict):
        if plan.get("safety", {}).get("deterministic_validation_authority_preserved") is True and summary.get("deterministic_validation_authority_preserved") is True:
            recorder.pass_check("model_routing_preserves_validation_authority", "Model routing preserves deterministic validation authority", path=model_routing_dir)
        else:
            recorder.fail_check("model_routing_preserves_validation_authority", "Model routing must preserve deterministic validation authority", path=model_routing_dir)

    if isinstance(assignments, dict) and isinstance(summary, dict):
        assignment_count = len(assignments.get("assignments", [])) if isinstance(assignments.get("assignments"), list) else None
        if summary.get("assignment_count") == assignment_count:
            recorder.pass_check("model_routing_summary_assignment_count", "Model routing summary assignment count matches assignments", path=model_routing_dir)
        else:
            recorder.fail_check(
                "model_routing_summary_assignment_count",
                "Model routing summary assignment count must match assignments",
                path=model_routing_dir,
                details={"summary": summary.get("assignment_count"), "assignments": assignment_count},
            )


def validate_review_agent_report(
    recorder: CheckRecorder,
    check_id: str,
    path: Path,
    *,
    expected_agent: str,
) -> dict[str, Any] | None:
    data = validate_json_artifact(recorder, check_id, path)
    if not isinstance(data, dict):
        recorder.fail_check(f"{check_id}_shape", f"{path.name} must be a JSON object", path=path)
        return None

    required = {
        "agent": expected_agent,
        "generated_by": "deterministic_scaffold",
    }
    for key, expected in required.items():
        actual = data.get(key)
        if actual == expected:
            recorder.pass_check(f"{check_id}_{key}", f"{path.name} {key} is {expected!r}", path=path)
        else:
            recorder.fail_check(f"{check_id}_{key}", f"{path.name} {key} must be {expected!r}; found {actual!r}", path=path)

    status = data.get("status")
    if status in {"pass", "warn", "fail"}:
        recorder.pass_check(f"{check_id}_status_value", f"{path.name} status is valid", path=path)
    else:
        recorder.fail_check(f"{check_id}_status_value", f"{path.name} status must be pass, warn, or fail; found {status!r}", path=path)

    if isinstance(data.get("blocking"), bool):
        recorder.pass_check(f"{check_id}_blocking_bool", f"{path.name} blocking is boolean", path=path)
    else:
        recorder.fail_check(f"{check_id}_blocking_bool", f"{path.name} blocking must be boolean", path=path)

    if isinstance(data.get("findings"), list):
        recorder.pass_check(f"{check_id}_findings_list", f"{path.name} findings is a list", path=path)
    else:
        recorder.fail_check(f"{check_id}_findings_list", f"{path.name} findings must be a list", path=path)

    if isinstance(data.get("artifacts_reviewed"), list):
        recorder.pass_check(f"{check_id}_artifacts_reviewed_list", f"{path.name} artifacts_reviewed is a list", path=path)
    else:
        recorder.fail_check(f"{check_id}_artifacts_reviewed_list", f"{path.name} artifacts_reviewed must be a list", path=path)

    return data


def review_summary_blocks_only_validation_review(summary: dict[str, Any]) -> bool:
    reports = summary.get("reports")
    if not isinstance(reports, dict):
        return False
    blocking_agents = [
        agent
        for agent, report in reports.items()
        if isinstance(report, dict) and report.get("blocking") is True
    ]
    return blocking_agents == ["validation_review"]


def validate_review_agent_artifacts(
    recorder: CheckRecorder,
    review_dir: Path,
    *,
    allow_stale_validation_review_blocking: bool = False,
) -> None:
    reports = [
        ("validation_review_parse", "VALIDATION_REVIEW", "validation_review"),
        ("sqa_review_parse", "SQA_REVIEW", "sqa_review"),
        ("security_review_parse", "SECURITY_REVIEW", "security_review"),
        ("scalability_review_parse", "SCALABILITY_REVIEW", "scalability_review"),
        ("architecture_review_parse", "ARCHITECTURE_REVIEW", "architecture_review"),
        ("review_agents_summary_parse", "REVIEW_AGENTS_SUMMARY", "review_agents_summary"),
    ]
    parsed: dict[str, dict[str, Any]] = {}
    for check_id, stem, expected_agent in reports:
        data = validate_review_agent_report(recorder, check_id, review_dir / f"{stem}.json", expected_agent=expected_agent)
        if data is not None:
            parsed[expected_agent] = data
        validate_text_artifact(recorder, f"{check_id}_markdown_readable", review_dir / f"{stem}.md")

    summary = parsed.get("review_agents_summary")
    if isinstance(summary, dict) and summary.get("blocking") is False:
        recorder.pass_check("review_agents_summary_nonblocking", "Review agents summary is nonblocking", path=review_dir / "REVIEW_AGENTS_SUMMARY.json")
    elif (
        allow_stale_validation_review_blocking
        and isinstance(summary, dict)
        and summary.get("blocking") is True
        and review_summary_blocks_only_validation_review(summary)
    ):
        recorder.pass_check(
            "review_agents_summary_nonblocking",
            "Stale review agents summary blocked only on validation_review; accepted in orchestrated validation mode",
            path=review_dir / "REVIEW_AGENTS_SUMMARY.json",
            details={"accepted_stale_validation_review_blocking": True},
        )
    elif isinstance(summary, dict):
        recorder.fail_check("review_agents_summary_nonblocking", "Review agents summary must not be blocking for a valid run", path=review_dir / "REVIEW_AGENTS_SUMMARY.json")

    expected_agents = {
        "validation_review",
        "sqa_review",
        "security_review",
        "scalability_review",
        "architecture_review",
    }
    if isinstance(summary, dict):
        reports_obj = summary.get("reports")
        actual_agents = set(reports_obj) if isinstance(reports_obj, dict) else set()
        if expected_agents.issubset(actual_agents):
            recorder.pass_check(
                "review_agents_summary_all_agents",
                "Review agents summary includes all Phase 14 reports",
                path=review_dir / "REVIEW_AGENTS_SUMMARY.json",
                details={"agents": sorted(actual_agents)},
            )
        else:
            recorder.fail_check(
                "review_agents_summary_all_agents",
                "Review agents summary must include all Phase 14 reports",
                path=review_dir / "REVIEW_AGENTS_SUMMARY.json",
                details={"expected": sorted(expected_agents), "actual": sorted(actual_agents)},
            )


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Run Validation Report",
        "",
        f"Project: {report['project_id']}",
        f"Created UTC: {report['created_utc']}",
        f"Status: {report['status'].upper()}",
        "",
        "## Safety",
        "",
        "- No OpenHands execution: true",
        "- No model calls: true",
        "- LangGraph runtime allowed only for deterministic Phase 12 orchestration: true",
        "- Review agents read-only: true",
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
    parser.add_argument(
        "--skip-orchestrator-artifacts",
        action="store_true",
        help="Skip latest_langgraph_v0 and latest_nightly_window checks for in-orchestrator validation.",
    )
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

    artifact_sources = validate_run_artifacts(
        args.project_id,
        recorder,
        skip_orchestrator_artifacts=args.skip_orchestrator_artifacts,
    )
    validation_mode = {
        "skip_orchestrator_artifacts": args.skip_orchestrator_artifacts,
        "skipped_orchestrator_artifacts": list(ORCHESTRATOR_ARTIFACT_POINTERS) if args.skip_orchestrator_artifacts else [],
        "skip_reason": "orchestrated mode avoids stale/current orchestrator artifact recursion"
        if args.skip_orchestrator_artifacts
        else None,
    }

    report = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": recorder.status(),
        "checks": recorder.checks,
        "failures": recorder.failures(),
        "artifact_sources": artifact_sources,
        "validation_mode": validation_mode,
        "safety": {
            "no_openhands_execution": True,
            "no_model_calls": True,
            "no_langgraph_runtime": True,
            "review_agents_read_only": True,
            "target_project_source_modified": False,
        },
    }

    write_json(run_dir / "VALIDATION_REPORT.json", report)
    (run_dir / "VALIDATION_REPORT.md").write_text(build_markdown_report(report))
    update_latest_validation(run_dir, args.project_id)

    print(f"Agent run validation complete for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Status: {report['status']}")
    if report["failures"]:
        print("Failures:")
        for failure in report["failures"]:
            print(f"  - {failure['id']}: {failure['message']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
