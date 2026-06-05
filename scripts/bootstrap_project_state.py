#!/usr/bin/env python3
from pathlib import Path
from datetime import date
import argparse
import json
import subprocess

ROOT = Path.home() / "agent-manager"

def fail(msg):
    raise SystemExit(f"bootstrap_project_state failed: {msg}")

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def load_project(project_id):
    path = ROOT / "configs" / "projects.json"
    data = json.loads(path.read_text())
    try:
        return data["projects"][project_id]
    except KeyError:
        fail(f"unknown project_id: {project_id}")

def git_value(repo, args):
    r = run(["git", *args], repo)
    return r.stdout.strip() if r.returncode == 0 else None

def ensure_clean_except_state(repo):
    r = run(["git", "status", "--short"], repo)
    dirty = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:] if len(line) > 3 else line
        if not path.startswith(".agent_manager/"):
            dirty.append(line)
    if dirty:
        fail("repo has non-.agent_manager changes:\n" + "\n".join(dirty))

def write(path, text, overwrite):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    path.write_text(text)

def write_json(path, obj, overwrite):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    path.write_text(json.dumps(obj, indent=2) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    project = load_project(args.project_id)
    repo = Path(project["repo_path"])
    if not repo.exists():
        fail(f"missing repo: {repo}")
    if not (repo / ".git").exists():
        fail(f"not a git repo: {repo}")

    ensure_clean_except_state(repo)

    state = repo / ".agent_manager"
    today = date.today().isoformat()
    week_id = date.today().strftime("%G-W%V")
    branch = git_value(repo, ["branch", "--show-current"])
    head = git_value(repo, ["rev-parse", "--short", "HEAD"])

    write(state / "README.md", f"""# Project Agent Manager State

Project-local control state for the central overnight agent-manager framework.

Project ID: `{args.project_id}`
Project name: `{project.get("name", args.project_id)}`
Central manager: `~/agent-manager`

This directory stores project-specific plan, safety, and objective state.
Reusable orchestration code remains in `~/agent-manager`.

Phase 5 creates control files only. It does not run OpenHands, models, LangGraph, or agents.
""", args.overwrite)

    write(state / "PROJECT.md", f"""# Project

Project ID: {args.project_id}
Project name: {project.get("name", args.project_id)}
Repo path: {repo}
Current branch at bootstrap: {branch}
HEAD at bootstrap: {head}
Created: {today}

## Status

Project-local control state bootstrap.
No write-capable agent execution is enabled.
""", args.overwrite)

    write(state / "CURRENT_PHASE.md", """# Current Phase

Phase 5: Project-local control state bootstrap

## Allowed

- Create `.agent_manager/` control files.
- Store project plan, safety, and backlog state.

## Forbidden

- Running OpenHands.
- Running model-driven planning.
- Running LangGraph.
- Modifying source behavior.
- Auto-merging.
- Auto-pushing.
""", args.overwrite)

    write(state / "SAFETY_RULES.md", """# Project Safety Rules

1. Do not modify `main` directly.
2. Do not auto-merge.
3. Do not auto-push.
4. Do not weaken validators.
5. Do not promote AI-generated data without approval artifacts.
6. Stop on blocker_count increase.
7. Stop on unexpected core writes.
8. Stop on schema drift.
9. Stop if changed files exceed objective scope.
10. Stop if secrets or credentials appear in logs or artifacts.

Manager and review agents are read-only.
The coder agent is write-capable only in a later isolated-worktree phase.
Deterministic validation remains the authority layer.
""", args.overwrite)

    write_json(state / "WEEKLY_PLAN.json", {
        "schema_version": 1,
        "week_id": week_id,
        "created_date": today,
        "project_id": args.project_id,
        "current_phase": "Phase 5: Project-local control state bootstrap",
        "primary_goal": "Create project-local control state without running agents.",
        "hard_gates": {
            "no_model_calls": True,
            "no_openhands_execution": True,
            "no_langgraph_execution": True,
            "no_source_behavior_changes": True,
            "no_auto_merge": True,
            "no_auto_push": True
        },
        "objectives": [
            {
                "id": "phase5_project_state_bootstrap",
                "priority": 1,
                "status": "active",
                "description": "Create project-local .agent_manager control files.",
                "write_capable": False
            },
            {
                "id": "phase6_deterministic_metrics_collector",
                "priority": 2,
                "status": "queued",
                "description": "Build read-only deterministic metrics collection.",
                "write_capable": False
            }
        ]
    }, args.overwrite)

    write_json(state / "OBJECTIVE_BACKLOG.json", {
        "schema_version": 1,
        "project_id": args.project_id,
        "objectives": [
            {
                "id": "phase5_project_state_bootstrap",
                "title": "Create project-local agent manager state",
                "priority": 1,
                "status": "active",
                "phase": "Phase 5",
                "risk_level": "low",
                "write_capable": False,
                "allowed_files": [
                    ".agent_manager/README.md",
                    ".agent_manager/PROJECT.md",
                    ".agent_manager/CURRENT_PHASE.md",
                    ".agent_manager/SAFETY_RULES.md",
                    ".agent_manager/WEEKLY_PLAN.json",
                    ".agent_manager/OBJECTIVE_BACKLOG.json"
                ]
            },
            {
                "id": "phase6_project_metrics_collector",
                "title": "Collect deterministic project metrics",
                "priority": 2,
                "status": "queued",
                "phase": "Phase 6",
                "risk_level": "medium",
                "write_capable": False
            }
        ]
    }, args.overwrite)

    print(f"Bootstrapped project state for {args.project_id}")
    print(f"Repo: {repo}")
    print(f"State dir: {state}")
    print(f"Branch: {branch}")
    print(f"HEAD: {head}")

if __name__ == "__main__":
    main()
