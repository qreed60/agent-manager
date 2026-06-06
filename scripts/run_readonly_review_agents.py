#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "deterministic_scaffold"
REVIEW_AGENTS = (
    "validation_review",
    "sqa_review",
    "security_review",
    "scalability_review",
    "architecture_review",
)
MISSING_EVIDENCE_SEVERITY = "medium"
SCALABILITY_TERMS = ("large artifact", "runtime", "recomputation", "token", "prompt growth", "prompt")
RUN_PREFIX_BY_LATEST = {
    "latest_validation": "validation_",
    "latest_morning_report": "morning_report_",
    "latest_langgraph_v0": "langgraph_v0_",
    "latest_runner_v0": "runner_v0_",
    "latest_manager_plan": "manager_plan_",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def load_project(project_id: str) -> dict[str, Any]:
    config_path = ROOT / "configs" / "projects.json"
    data = load_json(config_path)
    projects = data.get("projects")
    if not isinstance(projects, dict) or not isinstance(projects.get(project_id), dict):
        raise SystemExit(f"unknown project id: {project_id}")
    return projects[project_id]


def latest_artifact_paths(project_id: str) -> dict[str, Path]:
    run_root = ROOT / "runs" / project_id
    return {
        "validation_report": run_root / "latest_validation" / "VALIDATION_REPORT.json",
        "morning_report": run_root / "latest_morning_report" / "MORNING_REPORT.json",
        "langgraph_manifest": run_root / "latest_langgraph_v0" / "LANGGRAPH_RUN_MANIFEST.json",
        "langgraph_state_final": run_root / "latest_langgraph_v0" / "LANGGRAPH_STATE_FINAL.json",
    }


def optional_artifact_paths(project_id: str) -> dict[str, Path]:
    run_root = ROOT / "runs" / project_id
    return {
        "active_objective": run_root / "latest_runner_v0" / "ACTIVE_OBJECTIVE.json",
        "manager_decision": run_root / "latest_manager_plan" / "MANAGER_DECISION.json",
        "langgraph_node_trace": run_root / "latest_langgraph_v0" / "LANGGRAPH_NODE_TRACE.json",
        "langgraph_report_md": run_root / "latest_langgraph_v0" / "LANGGRAPH_REPORT.md",
        "validation_report_md": run_root / "latest_validation" / "VALIDATION_REPORT.md",
        "morning_report_md": run_root / "latest_morning_report" / "MORNING_REPORT.md",
        "portability_audit": run_root / "latest_portability_audit" / "PORTABILITY_AUDIT.json",
    }


def load_latest_artifacts(project_id: str) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for name, path in latest_artifact_paths(project_id).items():
        try:
            artifacts[name] = load_json(path)
        except FileNotFoundError as exc:
            raise SystemExit(f"required latest artifact is missing: {path}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"required latest artifact is invalid JSON: {path}: {exc}") from exc
    artifacts["_optional_presence"] = {}
    for name, path in optional_artifact_paths(project_id).items():
        try:
            artifacts[name] = load_json(path) if path.suffix == ".json" else path.read_text()
            artifacts["_optional_presence"][name] = "present"
        except FileNotFoundError:
            artifacts["_optional_presence"][name] = "missing"
        except json.JSONDecodeError as exc:
            artifacts[name] = {"_error": f"invalid JSON: {exc}"}
            artifacts["_optional_presence"][name] = "invalid"
        except OSError as exc:
            artifacts[name] = {"_error": f"could not read file: {exc}"}
            artifacts["_optional_presence"][name] = "unreadable"
    return artifacts


def reviewed_paths(project_id: str) -> list[str]:
    paths = list(latest_artifact_paths(project_id).values())
    paths.extend(path for path in optional_artifact_paths(project_id).values() if path.exists())
    return [str(path) for path in paths]


def latest_dirs(project_id: str) -> dict[str, Path]:
    run_root = ROOT / "runs" / project_id
    dirs: dict[str, Path] = {}
    for latest_name in RUN_PREFIX_BY_LATEST:
        pointer = run_root / latest_name
        if pointer.exists() or pointer.is_symlink():
            try:
                resolved = pointer.resolve()
            except OSError:
                continue
            if resolved.is_dir():
                dirs[latest_name] = resolved
    return dirs


def file_stats(path: Path) -> dict[str, int]:
    count = 0
    total_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            count += 1
            try:
                total_bytes += child.stat().st_size
            except OSError:
                pass
    return {"file_count": count, "total_bytes": total_bytes}


def previous_run_dir(project_id: str, latest_name: str, current_dir: Path) -> Path | None:
    run_root = ROOT / "runs" / project_id
    prefix = RUN_PREFIX_BY_LATEST[latest_name]
    candidates = sorted(
        path for path in run_root.glob(f"{prefix}*") if path.is_dir() and path.resolve() != current_dir.resolve()
    )
    return candidates[-1] if candidates else None


def path_created_utc(path: Path) -> str | None:
    for part in reversed(path.parts):
        if len(part) >= 16:
            candidate = part[-16:]
            if candidate.endswith("Z") and "T" in candidate:
                return candidate
    return None


def values_text(values: Iterable[Any]) -> str:
    chunks: list[str] = []
    for value in values:
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, (dict, list)):
            chunks.append(json.dumps(value, sort_keys=True))
        elif value is not None:
            chunks.append(str(value))
    return "\n".join(chunks).lower()


def finding(
    finding_id: str,
    severity: str,
    message: str,
    *,
    source: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": finding_id,
        "severity": severity,
        "source": source,
        "message": message,
    }
    if details:
        item["details"] = details
    return item


def make_report(
    *,
    agent: str,
    project_id: str,
    created_utc: str,
    run_dir: Path,
    status: str,
    blocking: bool,
    findings: list[dict[str, Any]],
    artifacts_reviewed: list[str],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "agent": agent,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": status,
        "blocking": blocking,
        "findings": findings,
        "artifacts_reviewed": artifacts_reviewed,
        "generated_by": GENERATED_BY,
        "summary": summary or {},
    }


def validation_review(project_id: str, created_utc: str, run_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    report = artifacts["validation_report"]
    status = report.get("status") if isinstance(report, dict) else None
    failures = report.get("failures") if isinstance(report, dict) else None
    failure_count = len(failures) if isinstance(failures, list) else 0
    validation_mode = report.get("validation_mode") if isinstance(report, dict) else None
    skipped_orchestrator_artifacts = (
        validation_mode.get("skipped_orchestrator_artifacts")
        if isinstance(validation_mode, dict) and validation_mode.get("skip_orchestrator_artifacts") is True
        else []
    )
    findings = [
        finding(
            "deterministic_validation_status",
            "info" if status == "pass" else "high",
            f"Deterministic validation status is {status!r}.",
            source="latest_validation/VALIDATION_REPORT.json",
            details={"failure_count": failure_count, "skipped_orchestrator_artifacts": skipped_orchestrator_artifacts},
        )
    ]
    blocking = status != "pass"
    return make_report(
        agent="validation_review",
        project_id=project_id,
        created_utc=created_utc,
        run_dir=run_dir,
        status="pass" if status == "pass" else "fail",
        blocking=blocking,
        findings=findings,
        artifacts_reviewed=reviewed_paths(project_id),
        summary={
            "deterministic_validation_status": status,
            "failure_count": failure_count,
            "skipped_orchestrator_artifacts": skipped_orchestrator_artifacts,
        },
    )


def find_test_evidence(obj: Any) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key).lower()
                child_text = str(child).lower() if not isinstance(child, (dict, list)) else ""
                if any(token in key_text or token in child_text for token in ("unittest", "pytest", "test run", "tests_run")):
                    evidence.append({"path": f"{path}.{key}" if path else str(key), "value": child})
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                visit(child, f"{path}[{idx}]")

    visit(obj, "")
    return evidence


def sqa_review(project_id: str, created_utc: str, run_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    evidence = find_test_evidence(artifacts)
    run_evidence = [
        item for item in evidence if any(token in str(item["value"]).lower() for token in ("pass", "passed", "success", "ok", "run"))
    ]
    if run_evidence:
        status = "pass"
        severity = "info"
        message = "Recent test or unittest evidence was found in reviewed artifacts."
    else:
        status = "warn"
        severity = "medium"
        message = "No explicit recent test or unittest run evidence was found in reviewed artifacts."
    findings = [
        finding(
            "recent_test_run_evidence",
            severity,
            message,
            source="reviewed_artifacts",
            details={"evidence_count": len(evidence), "run_evidence_count": len(run_evidence)},
        )
    ]
    return make_report(
        agent="sqa_review",
        project_id=project_id,
        created_utc=created_utc,
        run_dir=run_dir,
        status=status,
        blocking=False,
        findings=findings,
        artifacts_reviewed=reviewed_paths(project_id),
        summary={"test_evidence_count": len(evidence), "test_run_evidence_count": len(run_evidence)},
    )


def flag_status(container: dict[str, Any], dotted_key: str, expected: Any) -> dict[str, Any]:
    current: Any = container
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            current = None
            break
        current = current.get(part)
    return {"key": dotted_key, "expected": expected, "actual": current, "pass": current == expected}


def security_review(project_id: str, created_utc: str, run_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    checks = [
        ("validation_report", "safety.no_openhands_execution", True),
        ("validation_report", "safety.no_model_calls", True),
        ("validation_report", "safety.target_project_source_modified", False),
        ("morning_report", "safety_status.no_openhands_execution", True),
        ("morning_report", "safety_status.no_model_calls", True),
        ("morning_report", "safety_status.auto_merge", False),
        ("morning_report", "safety_status.auto_push", False),
        ("morning_report", "safety_status.target_repo_modified_by_default", False),
        ("langgraph_manifest", "safety.no_openhands_execution", True),
        ("langgraph_manifest", "safety.no_model_calls", True),
        ("langgraph_manifest", "safety.no_auto_merge", True),
        ("langgraph_manifest", "safety.no_auto_push", True),
        ("langgraph_manifest", "safety.deterministic_validation_authority_preserved", True),
    ]
    results = []
    for artifact_name, key, expected in checks:
        result = flag_status(artifacts[artifact_name], key, expected)
        result["artifact"] = artifact_name
        results.append(result)

    failed = [item for item in results if not item["pass"]]
    findings = [
        finding(
            "safety_flags",
            "info" if not failed else "critical",
            "Safety flags preserve read-only deterministic behavior." if not failed else "One or more safety flags failed.",
            source="validation_morning_langgraph_safety",
            details={"checks": results},
        )
    ]
    return make_report(
        agent="security_review",
        project_id=project_id,
        created_utc=created_utc,
        run_dir=run_dir,
        status="pass" if not failed else "fail",
        blocking=bool(failed),
        findings=findings,
        artifacts_reviewed=reviewed_paths(project_id),
        summary={"safety_check_count": len(results), "failed_safety_check_count": len(failed)},
    )


def scalability_review(project_id: str, created_utc: str, run_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    dirs = latest_dirs(project_id)
    run_stats: dict[str, Any] = {}
    for latest_name, directory in dirs.items():
        stats = file_stats(directory)
        previous = previous_run_dir(project_id, latest_name, directory)
        item: dict[str, Any] = {"path": str(directory), **stats}
        if previous is not None:
            previous_stats = file_stats(previous)
            item["previous_path"] = str(previous)
            item["file_count_delta"] = stats["file_count"] - previous_stats["file_count"]
            item["total_bytes_delta"] = stats["total_bytes"] - previous_stats["total_bytes"]
        else:
            item["previous_path"] = None
        run_stats[latest_name] = item

    if run_stats:
        findings.append(
            finding(
                "latest_run_artifact_growth",
                "info",
                "Latest run artifact counts and byte sizes were measured.",
                source="runs_latest_directories",
                details={"directories": run_stats},
            )
        )
    else:
        findings.append(
            finding(
                "latest_run_artifact_growth",
                MISSING_EVIDENCE_SEVERITY,
                "No latest run directories were available for artifact growth measurement.",
                source="runs_latest_directories",
            )
        )
    summary["latest_run_directory_count"] = len(run_stats)

    trace = artifacts.get("langgraph_node_trace")
    if isinstance(trace, list):
        statuses = [item.get("status") for item in trace if isinstance(item, dict)]
        trace_completed = bool(trace) and all(status == "pass" for status in statuses)
        findings.append(
            finding(
                "langgraph_node_trace_completed",
                "info" if trace_completed else MISSING_EVIDENCE_SEVERITY,
                "LangGraph node trace exists and completed." if trace_completed else "LangGraph node trace exists but did not show all nodes completed.",
                source="latest_langgraph_v0/LANGGRAPH_NODE_TRACE.json",
                details={"node_count": len(trace), "statuses": statuses},
            )
        )
        summary["langgraph_trace_completed"] = trace_completed
    else:
        findings.append(
            finding(
                "langgraph_node_trace_completed",
                MISSING_EVIDENCE_SEVERITY,
                "LangGraph node trace evidence is missing or unreadable.",
                source="latest_langgraph_v0/LANGGRAPH_NODE_TRACE.json",
            )
        )
        summary["langgraph_trace_completed"] = None

    validation_created = artifacts.get("validation_report", {}).get("created_utc") if isinstance(artifacts.get("validation_report"), dict) else None
    langgraph_created = artifacts.get("langgraph_manifest", {}).get("created_utc") if isinstance(artifacts.get("langgraph_manifest"), dict) else None
    if not isinstance(validation_created, str):
        validation_dir = dirs.get("latest_validation")
        validation_created = path_created_utc(validation_dir) if validation_dir else None
    if not isinstance(langgraph_created, str):
        langgraph_dir = dirs.get("latest_langgraph_v0")
        langgraph_created = path_created_utc(langgraph_dir) if langgraph_dir else None
    if validation_created and langgraph_created:
        validation_after_langgraph = validation_created >= langgraph_created
        findings.append(
            finding(
                "validation_after_langgraph",
                "info" if validation_after_langgraph else MISSING_EVIDENCE_SEVERITY,
                "Latest validation timestamp is at or after latest LangGraph timestamp."
                if validation_after_langgraph
                else "Latest validation timestamp appears older than latest LangGraph timestamp.",
                source="latest_validation_and_latest_langgraph_v0",
                details={"validation_created_utc": validation_created, "langgraph_created_utc": langgraph_created},
            )
        )
        summary["validation_after_langgraph"] = validation_after_langgraph
    else:
        findings.append(
            finding(
                "validation_after_langgraph",
                MISSING_EVIDENCE_SEVERITY,
                "Timestamp evidence was insufficient to confirm validation completed after LangGraph.",
                source="latest_validation_and_latest_langgraph_v0",
                details={"validation_created_utc": validation_created, "langgraph_created_utc": langgraph_created},
            )
        )
        summary["validation_after_langgraph"] = None

    retry_artifacts: list[str] = []
    for directory in dirs.values():
        for child in directory.rglob("*"):
            if child.is_file() and any(token in child.name.lower() for token in ("retry", "resume", "checkpoint")):
                retry_artifacts.append(str(child))
    findings.append(
        finding(
            "retry_resume_checkpoint_artifacts",
            "info",
            "Retry, resume, or checkpoint artifacts were recorded."
            if retry_artifacts
            else "No retry, resume, or checkpoint artifacts were found in latest run directories.",
            source="runs_latest_directories",
            details={"artifacts": retry_artifacts},
        )
    )
    summary["retry_resume_checkpoint_artifact_count"] = len(retry_artifacts)

    large_artifacts_applicable = any(
        item["file_count"] >= 50 or item["total_bytes"] >= 1_000_000 for item in run_stats.values()
    )
    reviewed_text = values_text(
        [
            artifacts.get("validation_report"),
            artifacts.get("validation_report_md"),
            artifacts.get("morning_report"),
            artifacts.get("morning_report_md"),
            artifacts.get("langgraph_manifest"),
            artifacts.get("langgraph_report_md"),
        ]
    )
    mentioned_terms = [term for term in SCALABILITY_TERMS if term in reviewed_text]
    if large_artifacts_applicable and not mentioned_terms:
        severity = MISSING_EVIDENCE_SEVERITY
        message = "Large artifact handling appears applicable, but reviewed reports did not mention related scalability terms."
    elif large_artifacts_applicable:
        severity = "info"
        message = "Reviewed reports mention scalability-related terms for large artifact handling."
    else:
        severity = "info"
        message = "Large artifact handling thresholds were not reached in the latest run directories."
    findings.append(
        finding(
            "large_artifact_runtime_recomputation_token_evidence",
            severity,
            message,
            source="reviewed_reports",
            details={"large_artifacts_applicable": large_artifacts_applicable, "mentioned_terms": mentioned_terms},
        )
    )
    summary["large_artifacts_applicable"] = large_artifacts_applicable
    summary["scalability_term_count"] = len(mentioned_terms)

    status = "warn" if any(item["severity"] == MISSING_EVIDENCE_SEVERITY for item in findings) else "pass"
    return make_report(
        agent="scalability_review",
        project_id=project_id,
        created_utc=created_utc,
        run_dir=run_dir,
        status=status,
        blocking=False,
        findings=findings,
        artifacts_reviewed=reviewed_paths(project_id),
        summary=summary,
    )


def portability_evidence(artifacts: dict[str, Any]) -> tuple[bool | None, dict[str, Any] | None]:
    audit = artifacts.get("portability_audit")
    if isinstance(audit, dict):
        counts = audit.get("counts")
        if isinstance(counts, dict) and isinstance(counts.get("blocking_core_coupling"), int):
            return counts["blocking_core_coupling"] == 0, {"blocking_core_coupling": counts["blocking_core_coupling"]}

    validation = artifacts.get("validation_report")
    if isinstance(validation, dict):
        for check in validation.get("checks", []):
            if not isinstance(check, dict):
                continue
            details = check.get("details")
            if isinstance(details, dict) and isinstance(details.get("blocking_core_coupling"), int):
                return details["blocking_core_coupling"] == 0, {"blocking_core_coupling": details["blocking_core_coupling"]}
    return None, None


def architecture_review(project_id: str, created_utc: str, run_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    objective = {}
    active_objective = artifacts.get("active_objective")
    manager_decision = artifacts.get("manager_decision")
    if isinstance(active_objective, dict) and isinstance(active_objective.get("objective"), dict):
        objective = active_objective["objective"]
    elif isinstance(manager_decision, dict) and isinstance(manager_decision.get("selected_objective"), dict):
        objective = manager_decision["selected_objective"]

    objective_id = objective.get("id") if isinstance(objective, dict) else None
    objective_phase = objective.get("phase") if isinstance(objective, dict) else None
    phase_aligned = objective_id == "phase14_scalability_architecture_review_agents" and objective_phase == "Phase 14"
    findings.append(
        finding(
            "selected_objective_phase_aligned",
            "info" if phase_aligned else MISSING_EVIDENCE_SEVERITY,
            "Selected objective is aligned with Phase 14."
            if phase_aligned
            else "Selected objective evidence is missing or not aligned with Phase 14.",
            source="latest_runner_v0/ACTIVE_OBJECTIVE.json",
            details={"objective_id": objective_id, "phase": objective_phase},
        )
    )
    summary["selected_objective_phase_aligned"] = phase_aligned

    portable_project_id = isinstance(project_id, str) and bool(project_id) and project_id == project_id.lower()
    findings.append(
        finding(
            "project_id_portable",
            "info" if portable_project_id else MISSING_EVIDENCE_SEVERITY,
            "Project id is caller supplied and remains a portable lowercase identifier."
            if portable_project_id
            else "Project id evidence is missing or not a portable lowercase identifier.",
            source="configs/projects.json",
            details={"project_id": project_id},
        )
    )
    summary["project_id_portable"] = portable_project_id

    portability_ok, portability_details = portability_evidence(artifacts)
    if portability_ok is None:
        findings.append(
            finding(
                "portability_blocking_core_coupling",
                MISSING_EVIDENCE_SEVERITY,
                "Portability audit evidence was not available to confirm blocking_core_coupling == 0.",
                source="latest_portability_audit/PORTABILITY_AUDIT.json",
            )
        )
    else:
        findings.append(
            finding(
                "portability_blocking_core_coupling",
                "info" if portability_ok else "high",
                "Portability audit evidence reports blocking_core_coupling == 0."
                if portability_ok
                else "Portability audit evidence reports blocking core coupling.",
                source="portability_audit_evidence",
                details=portability_details,
            )
        )
    summary["portability_blocking_core_coupling_zero"] = portability_ok

    checks = [
        ("deterministic_validation_authoritative", "langgraph_manifest", "safety.deterministic_validation_authority_preserved", True),
        ("validation_passed", "validation_report", "status", "pass"),
        ("validation_no_openhands", "validation_report", "safety.no_openhands_execution", True),
        ("validation_no_model_calls", "validation_report", "safety.no_model_calls", True),
        ("review_agents_read_only", "validation_report", "safety.review_agents_read_only", True),
        ("no_source_behavior_modification", "validation_report", "safety.target_project_source_modified", False),
        ("morning_no_auto_merge", "morning_report", "safety_status.auto_merge", False),
        ("morning_no_auto_push", "morning_report", "safety_status.auto_push", False),
        ("langgraph_no_auto_merge", "langgraph_manifest", "safety.no_auto_merge", True),
        ("langgraph_no_auto_push", "langgraph_manifest", "safety.no_auto_push", True),
    ]
    results = []
    for check_id, artifact_name, key, expected in checks:
        result = flag_status(artifacts.get(artifact_name, {}), key, expected)
        result["id"] = check_id
        result["artifact"] = artifact_name
        results.append(result)

    failed = [item for item in results if not item["pass"] and item["actual"] is not None]
    missing = [item for item in results if item["actual"] is None]
    severity = "info" if not failed and not missing else ("high" if failed else MISSING_EVIDENCE_SEVERITY)
    findings.append(
        finding(
            "architecture_safety_contract",
            severity,
            "Architecture safety contract evidence is present and aligned."
            if severity == "info"
            else "Architecture safety contract has failed or missing evidence.",
            source="validation_morning_langgraph_safety",
            details={"checks": results, "failed_count": len(failed), "missing_count": len(missing)},
        )
    )
    summary["failed_architecture_safety_check_count"] = len(failed)
    summary["missing_architecture_safety_check_count"] = len(missing)

    status = "warn" if any(item["severity"] in {MISSING_EVIDENCE_SEVERITY, "high"} for item in findings) else "pass"
    return make_report(
        agent="architecture_review",
        project_id=project_id,
        created_utc=created_utc,
        run_dir=run_dir,
        status=status,
        blocking=False,
        findings=findings,
        artifacts_reviewed=reviewed_paths(project_id),
        summary=summary,
    )


def summary_status(reports: list[dict[str, Any]]) -> str:
    if any(report["blocking"] for report in reports):
        return "fail"
    if any(report["status"] == "warn" for report in reports):
        return "warn"
    if any(report["status"] == "fail" for report in reports):
        return "warn"
    return "pass"


def build_summary(
    project_id: str,
    created_utc: str,
    run_dir: Path,
    reports: list[dict[str, Any]],
    artifacts_reviewed: list[str],
) -> dict[str, Any]:
    status = summary_status(reports)
    return {
        "schema_version": 1,
        "agent": "review_agents_summary",
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": status,
        "blocking": any(report["blocking"] for report in reports),
        "findings": [
            finding(
                "review_agent_statuses",
                "info" if status == "pass" else "medium",
                "Read-only review agent scaffold completed.",
                source="review_agent_reports",
                details={report["agent"]: {"status": report["status"], "blocking": report["blocking"]} for report in reports},
            )
        ],
        "artifacts_reviewed": artifacts_reviewed,
        "generated_by": GENERATED_BY,
        "reports": {
            report["agent"]: {
                "status": report["status"],
                "blocking": report["blocking"],
                "path_json": str(run_dir / report_filename(report["agent"], "json")),
                "path_md": str(run_dir / report_filename(report["agent"], "md")),
            }
            for report in reports
        },
        "safety": {
            "read_only": True,
            "no_openhands_execution": True,
            "no_model_calls": True,
            "target_project_source_modified": False,
            "no_auto_merge": True,
            "no_auto_push": True,
            "deterministic_validation_authority_preserved": True,
        },
    }


def report_filename(agent: str, extension: str) -> str:
    return f"{agent.upper()}.{extension}"


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['agent'].replace('_', ' ').title()}",
        "",
        f"Project: {report['project_id']}",
        f"Created UTC: {report['created_utc']}",
        f"Status: {report['status'].upper()}",
        f"Blocking: {str(report['blocking']).lower()}",
        f"Generated by: {report['generated_by']}",
        "",
        "## Findings",
        "",
    ]
    for item in report["findings"]:
        lines.append(f"- {item['severity'].upper()}: {item['id']} - {item['message']}")
        lines.append(f"  Source: {item['source']}")
    lines.extend(["", "## Artifacts Reviewed", ""])
    for path in report["artifacts_reviewed"]:
        lines.append(f"- {path}")
    lines.append("")
    return "\n".join(lines)


def build_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Review Agents Summary",
        "",
        f"Project: {summary['project_id']}",
        f"Created UTC: {summary['created_utc']}",
        f"Status: {summary['status'].upper()}",
        f"Blocking: {str(summary['blocking']).lower()}",
        f"Generated by: {summary['generated_by']}",
        "",
        "## Agent Summaries",
        "",
    ]
    reports = summary.get("reports", {})
    if isinstance(reports, dict):
        for agent in REVIEW_AGENTS:
            item = reports.get(agent, {})
            status = item.get("status", "missing") if isinstance(item, dict) else "missing"
            blocking = item.get("blocking", "missing") if isinstance(item, dict) else "missing"
            lines.append(f"- {agent}: status={status}, blocking={blocking}")

    lines.extend(["", "## Findings", ""])
    for item in summary["findings"]:
        lines.append(f"- {item['severity'].upper()}: {item['id']} - {item['message']}")
        lines.append(f"  Source: {item['source']}")
    lines.extend(["", "## Artifacts Reviewed", ""])
    for path in summary["artifacts_reviewed"]:
        lines.append(f"- {path}")
    lines.append("")
    return "\n".join(lines)


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_review_agents"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def generate(project_id: str, created_utc: str | None = None) -> dict[str, Any]:
    load_project(project_id)
    created = created_utc or utc_now()
    run_dir = ROOT / "runs" / project_id / f"review_agents_{created}"
    artifacts = load_latest_artifacts(project_id)
    reports = [
        validation_review(project_id, created, run_dir, artifacts),
        sqa_review(project_id, created, run_dir, artifacts),
        security_review(project_id, created, run_dir, artifacts),
        scalability_review(project_id, created, run_dir, artifacts),
        architecture_review(project_id, created, run_dir, artifacts),
    ]
    for report in reports:
        write_json(run_dir / report_filename(report["agent"], "json"), report)
        (run_dir / report_filename(report["agent"], "md")).write_text(build_markdown_report(report))

    summary = build_summary(project_id, created, run_dir, reports, reviewed_paths(project_id))
    write_json(run_dir / "REVIEW_AGENTS_SUMMARY.json", summary)
    (run_dir / "REVIEW_AGENTS_SUMMARY.md").write_text(build_summary_markdown(summary))
    update_latest_symlink(run_dir, project_id)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic read-only review agent scaffolds.")
    parser.add_argument("project_id")
    args = parser.parse_args()

    summary = generate(args.project_id)
    print(f"Read-only review agents complete for {args.project_id}")
    print(f"Run dir: {summary['run_dir']}")
    print(f"Status: {summary['status']}")
    if summary["blocking"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
