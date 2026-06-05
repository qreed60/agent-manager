#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


ROOT = Path.home() / "agent-manager"


def fail(msg: str) -> None:
    raise SystemExit(f"manager_planning_pass failed: {msg}")


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


def git_value(repo: Path, args: list[str]) -> str:
    r = run(["git", *args], repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def select_next_objective(backlog: dict) -> dict:
    objectives = backlog.get("objectives", [])
    candidates = []
    for obj in objectives:
        if obj.get("write_capable") is True:
            continue
        if obj.get("status") not in {"queued", "active"}:
            continue
        candidates.append(obj)

    if not candidates:
        fail("no eligible non-write objective found")

    candidates.sort(key=lambda x: x.get("priority", 999))
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    args = parser.parse_args()

    project = load_project(args.project_id)
    repo = Path(project["repo_path"])
    state_dir = repo / ".agent_manager"

    if not repo.exists():
        fail(f"missing repo: {repo}")
    if not state_dir.exists():
        fail(f"missing project state: {state_dir}")

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / args.project_id / f"manager_plan_{now}"
    run_dir.mkdir(parents=True, exist_ok=True)

    weekly_plan = load_json(state_dir / "WEEKLY_PLAN.json")
    backlog = load_json(state_dir / "OBJECTIVE_BACKLOG.json")

    metrics_dir = (ROOT / "runs" / args.project_id / "latest").resolve()
    runner_dir = (ROOT / "runs" / args.project_id / "latest_runner_v0").resolve()

    run_metrics = load_json(metrics_dir / "RUN_METRICS.json")
    validation_summary = load_json(metrics_dir / "VALIDATION_SUMMARY.json")
    runner_manifest = load_json(runner_dir / "RUN_MANIFEST.json")

    status_short = git_value(repo, ["status", "--short"])
    branch = git_value(repo, ["branch", "--show-current"])
    head = git_value(repo, ["rev-parse", "--short", "HEAD"])

    if status_short.strip():
        fail("target repo is dirty; manager planning pass requires clean repo:\n" + status_short)

    if validation_summary.get("status") != "pass":
        fail("latest validation summary is not pass")

    selected = select_next_objective(backlog)

    context = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "repo": {
            "path": str(repo),
            "branch": branch,
            "head": head,
            "clean": True
        },
        "sources": {
            "weekly_plan": str(state_dir / "WEEKLY_PLAN.json"),
            "objective_backlog": str(state_dir / "OBJECTIVE_BACKLOG.json"),
            "metrics_dir": str(metrics_dir),
            "runner_dir": str(runner_dir)
        },
        "current_weekly_plan": weekly_plan,
        "latest_metrics_summary": {
            "tracked_files": run_metrics.get("counts", {}).get("tracked_files"),
            "estimated_text_lines": run_metrics.get("counts", {}).get("estimated_text_lines"),
            "python_files": run_metrics.get("counts", {}).get("python_files"),
            "test_files": run_metrics.get("counts", {}).get("test_files"),
            "script_files": run_metrics.get("counts", {}).get("script_files"),
            "markdown_files": run_metrics.get("counts", {}).get("markdown_files"),
            "json_files": run_metrics.get("counts", {}).get("json_files"),
            "shell_files": run_metrics.get("counts", {}).get("shell_files")
        },
        "validation_status": validation_summary,
        "previous_runner_status": runner_manifest,
        "eligible_objective": selected
    }

    decision = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "decision_type": "deterministic_manager_planning_v0",
        "selected_objective_id": selected.get("id"),
        "selected_objective": selected,
        "rationale": [
            "Latest deterministic validation passed.",
            "Target repository is clean.",
            "Objective is active or queued.",
            "Objective is not write-capable.",
            "Objective has the highest priority among eligible non-write objectives."
        ],
        "blocked_actions": [
            {
                "action": "run_openhands_coder",
                "reason": "Blocked until isolated coder execution phase."
            },
            {
                "action": "run_model_manager",
                "reason": "Blocked until model-driven manager planning is explicitly enabled."
            },
            {
                "action": "run_langgraph",
                "reason": "Blocked until LangGraph migration phase."
            },
            {
                "action": "modify_target_repo",
                "reason": "Phase 8 is central-artifact-only."
            }
        ],
        "safety": {
            "no_model_calls": True,
            "no_openhands_execution": True,
            "no_langgraph_execution": True,
            "target_repo_read_only": True,
            "no_auto_merge": True,
            "no_auto_push": True
        },
        "status": "pass"
    }

    plan_md = f"""# Manager Plan

Project: {args.project_id}
Created UTC: {now}
Manager mode: deterministic planning v0

## Status

PASS

## Repository

- Path: {repo}
- Branch: {branch}
- HEAD: {head}
- Clean: true

## Selected objective

- ID: {selected.get("id")}
- Title: {selected.get("title", selected.get("description", "n/a"))}
- Phase: {selected.get("phase", "n/a")}
- Priority: {selected.get("priority")}
- Write-capable: {selected.get("write_capable")}

## Rationale

1. Latest deterministic validation passed.
2. Target repository is clean.
3. The selected objective is active or queued.
4. The selected objective is not write-capable.
5. No write-capable agent execution is allowed in Phase 8.

## Blocked

- OpenHands coder execution.
- Model-driven manager planning.
- LangGraph runtime.
- Target project source edits.
- Auto-merge.
- Auto-push.

## Next recommended phase

Phase 9 should introduce isolated coder execution scaffolding, but still dry-run first.
"""

    next_action = f"""# Next Action

Proceed to Phase 9 only after review.

Recommended next objective:
{selected.get("id")}

Phase 9 should create isolated worktree execution scaffolding and dry-run validation. It should not yet allow broad autonomous coding.

Safety gates remain:
- no direct main edits
- no auto-merge
- no auto-push
- deterministic validation is authority
"""

    write_json(run_dir / "MANAGER_CONTEXT.json", context)
    write_json(run_dir / "MANAGER_DECISION.json", decision)
    (run_dir / "MANAGER_PLAN.md").write_text(plan_md)
    (run_dir / "NEXT_ACTION.md").write_text(next_action)

    latest = ROOT / "runs" / args.project_id / "latest_manager_plan"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)

    print(f"Manager planning pass complete for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Selected objective: {selected.get('id')}")
    print("Status: pass")


if __name__ == "__main__":
    main()
