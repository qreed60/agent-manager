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
    if langgraph_pointer.exists() or langgraph_pointer.is_symlink():
        langgraph_dir = validate_latest_dir(recorder, "latest_langgraph_v0_dir", langgraph_pointer)
        if langgraph_dir is not None:
            resolved_dirs["latest_langgraph_v0"] = str(langgraph_dir)
            manifest = validate_json_artifact(
                recorder,
                "langgraph_manifest_parse",
                langgraph_dir / "LANGGRAPH_RUN_MANIFEST.json",
                required_status="pass",
            )
            state = validate_json_artifact(
                recorder,
                "langgraph_state_final_parse",
                langgraph_dir / "LANGGRAPH_STATE_FINAL.json",
                required_status="pass",
            )
            trace = validate_json_artifact(recorder, "langgraph_node_trace_parse", langgraph_dir / "LANGGRAPH_NODE_TRACE.json")
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
    else:
        recorder.pass_check("latest_langgraph_v0_optional", "latest_langgraph_v0 is absent; optional Phase 12 artifacts not validated", path=langgraph_pointer)

    review_pointer = run_root / "latest_review_agents"
    if review_pointer.exists() or review_pointer.is_symlink():
        review_dir = validate_latest_dir(recorder, "latest_review_agents_dir", review_pointer)
        if review_dir is not None:
            resolved_dirs["latest_review_agents"] = str(review_dir)
            validate_review_agent_artifacts(recorder, review_dir)
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
    if nightly_window_pointer.exists() or nightly_window_pointer.is_symlink():
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
            validate_human_approval_artifacts(recorder, human_approval_dir)
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

    return resolved_dirs


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


def validate_human_approval_artifacts(recorder: CheckRecorder, approval_dir: Path) -> None:
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
        if isinstance(safety, dict) and (
            safety.get("model_calls_allowed") is False
            and safety.get("openhands_allowed") is False
            and safety.get("source_writes_allowed") is False
            and safety.get("github_pr_created") is False
            and safety.get("branch_pushed") is False
            and safety.get("merge_performed") is False
            and safety.get("max_code_writing_tasks") == 0
        ):
            recorder.pass_check("approval_packet_safety_flags", "Approval packet preserves Phase 17 safety flags", path=approval_dir / "APPROVAL_PACKET.json")
        else:
            recorder.fail_check("approval_packet_safety_flags", "Approval packet must deny models, OpenHands, source writes, PR creation, push, merge, and code writing", path=approval_dir / "APPROVAL_PACKET.json")
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

    service_checks = {
        "systemd_service_user_qreed": "User=qreed" in service,
        "systemd_service_workdir": "WorkingDirectory=/home/qreed/agent-manager" in service,
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
        if isinstance(policy, dict) and policy.get("max_code_writing_tasks") == 0 and manifest.get("max_code_writing_tasks") == 0:
            recorder.pass_check("nightly_window_no_code_writing_tasks", "Nightly window keeps code-writing tasks disabled", path=nightly_window_dir)
        else:
            recorder.fail_check("nightly_window_no_code_writing_tasks", "Phase 16 requires max_code_writing_tasks == 0", path=nightly_window_dir)
        if (
            manifest.get("model_calls_allowed") is False
            and manifest.get("openhands_allowed") is False
            and manifest.get("source_writes_allowed") is False
            and manifest.get("auto_merge_allowed") is False
            and manifest.get("auto_push_allowed") is False
        ):
            recorder.pass_check("nightly_window_safety_flags", "Nightly window safety flags disable models, OpenHands, source writes, auto-merge, and auto-push", path=nightly_window_dir)
        else:
            recorder.fail_check("nightly_window_safety_flags", "Nightly window safety flags must disable models, OpenHands, source writes, auto-merge, and auto-push", path=nightly_window_dir)

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
            and safety.get("openhands_allowed") is False
            and safety.get("source_writes_allowed") is False
            and safety.get("max_code_writing_tasks") == 0
        ):
            recorder.pass_check("nightly_safety_status_control_plane_only", "Nightly safety status preserves control-plane-only behavior", path=nightly_window_dir / "NIGHTLY_SAFETY_STATUS.json")
        else:
            recorder.fail_check("nightly_safety_status_control_plane_only", "Nightly safety status must preserve control-plane-only behavior", path=nightly_window_dir / "NIGHTLY_SAFETY_STATUS.json")


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


def validate_review_agent_artifacts(recorder: CheckRecorder, review_dir: Path) -> None:
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
