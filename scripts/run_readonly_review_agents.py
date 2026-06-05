#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "deterministic_scaffold"
REVIEW_AGENTS = ("validation_review", "sqa_review", "security_review")


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


def load_latest_artifacts(project_id: str) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for name, path in latest_artifact_paths(project_id).items():
        try:
            artifacts[name] = load_json(path)
        except FileNotFoundError as exc:
            raise SystemExit(f"required latest artifact is missing: {path}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"required latest artifact is invalid JSON: {path}: {exc}") from exc
    return artifacts


def reviewed_paths(project_id: str) -> list[str]:
    return [str(path) for path in latest_artifact_paths(project_id).values()]


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
    findings = [
        finding(
            "deterministic_validation_status",
            "info" if status == "pass" else "high",
            f"Deterministic validation status is {status!r}.",
            source="latest_validation/VALIDATION_REPORT.json",
            details={"failure_count": failure_count},
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
        summary={"deterministic_validation_status": status, "failure_count": failure_count},
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
    ]
    for report in reports:
        write_json(run_dir / report_filename(report["agent"], "json"), report)
        (run_dir / report_filename(report["agent"], "md")).write_text(build_markdown_report(report))

    summary = build_summary(project_id, created, run_dir, reports, reviewed_paths(project_id))
    write_json(run_dir / "REVIEW_AGENTS_SUMMARY.json", summary)
    (run_dir / "REVIEW_AGENTS_SUMMARY.md").write_text(build_markdown_report(summary))
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
