#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


ROOT = Path.home() / "agent-manager"


def fail(msg: str) -> None:
    raise SystemExit(f"run_nightly_v0 failed: {msg}")


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        fail(f"could not load JSON {path}: {exc}")


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def load_project(project_id: str) -> dict:
    data = load_json(ROOT / "configs" / "projects.json")
    try:
        return data["projects"][project_id]
    except KeyError:
        fail(f"unknown project_id: {project_id}")


def collect_metrics(project_id: str) -> Path:
    result = run(["python3", "scripts/collect_project_metrics.py", project_id], ROOT)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        fail("metrics collector failed")

    latest = ROOT / "runs" / project_id / "latest"
    if not latest.exists():
        fail(f"metrics collector did not create latest symlink: {latest}")

    return latest.resolve()


def select_objective(backlog: dict) -> dict:
    objectives = backlog.get("objectives", [])
    if not isinstance(objectives, list):
        fail("OBJECTIVE_BACKLOG.json field objectives must be a list")

    candidates = []
    for obj in objectives:
        if obj.get("status") not in {"active", "queued"}:
            continue
        if obj.get("write_capable") is True:
            continue
        candidates.append(obj)

    if not candidates:
        fail("no safe non-write active/queued objective available")

    candidates.sort(key=lambda x: x.get("priority", 999))
    return candidates[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    args = ap.parse_args()

    project = load_project(args.project_id)
    repo = Path(project["repo_path"])
    state_dir = repo / ".agent_manager"

    if not repo.exists():
        fail(f"missing repo: {repo}")
    if not state_dir.exists():
        fail(f"missing project state dir: {state_dir}")

    metrics_run = collect_metrics(args.project_id)

    validation_summary = load_json(metrics_run / "VALIDATION_SUMMARY.json")
    if validation_summary.get("status") != "pass":
        fail(f"validation summary is not pass: {metrics_run / 'VALIDATION_SUMMARY.json'}")

    backlog = load_json(state_dir / "OBJECTIVE_BACKLOG.json")
    objective = select_objective(backlog)

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / args.project_id / f"runner_v0_{now}"
    run_dir.mkdir(parents=True, exist_ok=True)

    active_objective = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "runner": "plain_python_v0",
        "objective": objective,
        "permission": {
            "write_capable": False,
            "target_repo_read_only": True,
            "openhands_execution_allowed": False,
            "model_calls_allowed": False,
            "langgraph_execution_allowed": False
        },
        "source_backlog": str(state_dir / "OBJECTIVE_BACKLOG.json"),
        "metrics_source": str(metrics_run)
    }

    task_graph = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "runner": "plain_python_v0",
        "nodes": [
            {
                "id": "collect_metrics",
                "kind": "deterministic",
                "status": "complete",
                "writes": [str(metrics_run)]
            },
            {
                "id": "select_active_objective",
                "kind": "deterministic",
                "status": "complete",
                "selected_objective_id": objective.get("id")
            },
            {
                "id": "write_runner_artifacts",
                "kind": "deterministic",
                "status": "complete",
                "writes": [
                    "ACTIVE_OBJECTIVE.json",
                    "TASK_GRAPH.json",
                    "RUN_MANIFEST.json",
                    "MORNING_REPORT.md"
                ]
            }
        ],
        "edges": [
            ["collect_metrics", "select_active_objective"],
            ["select_active_objective", "write_runner_artifacts"]
        ],
        "blocked_future_nodes": [
            {
                "id": "run_openhands_coder",
                "reason": "Blocked until isolated coder execution phase."
            },
            {
                "id": "run_langgraph_manager",
                "reason": "Blocked until LangGraph migration phase."
            },
            {
                "id": "run_model_planning",
                "reason": "Blocked until manager planning pass phase."
            }
        ]
    }

    manifest = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "runner": "plain_python_v0",
        "repo_path": str(repo),
        "project_state_dir": str(state_dir),
        "metrics_run_dir": str(metrics_run),
        "run_dir": str(run_dir),
        "selected_objective_id": objective.get("id"),
        "status": "pass",
        "safety": {
            "no_model_calls": True,
            "no_openhands_execution": True,
            "no_langgraph_execution": True,
            "target_repo_read_only": True,
            "no_auto_merge": True,
            "no_auto_push": True
        }
    }

    report = f"""# Morning Report

Project: {args.project_id}
Runner: plain_python_v0
Created UTC: {now}

## Status

PASS

## Selected objective

- ID: {objective.get("id")}
- Title: {objective.get("title", objective.get("description", "n/a"))}
- Phase: {objective.get("phase", "n/a")}
- Write-capable: {objective.get("write_capable")}

## Safety result

- No model calls: true
- No OpenHands execution: true
- No LangGraph execution: true
- Target repo read-only: true
- No auto-merge: true
- No auto-push: true

## Artifacts

- ACTIVE_OBJECTIVE.json
- TASK_GRAPH.json
- RUN_MANIFEST.json
- MORNING_REPORT.md

## Metrics source

{metrics_run}
"""

    write_json(run_dir / "ACTIVE_OBJECTIVE.json", active_objective)
    write_json(run_dir / "TASK_GRAPH.json", task_graph)
    write_json(run_dir / "RUN_MANIFEST.json", manifest)
    (run_dir / "MORNING_REPORT.md").write_text(report)

    latest_runner = ROOT / "runs" / args.project_id / "latest_runner_v0"
    if latest_runner.exists() or latest_runner.is_symlink():
        latest_runner.unlink()
    latest_runner.symlink_to(run_dir, target_is_directory=True)

    print(f"Nightly runner v0 complete for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Selected objective: {objective.get('id')}")
    print("Status: pass")


if __name__ == "__main__":
    main()
