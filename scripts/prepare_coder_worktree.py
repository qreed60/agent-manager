#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path.home() / "agent-manager"


def fail(msg: str) -> None:
    raise SystemExit(f"prepare_coder_worktree failed: {msg}")


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


def ensure_clean(repo: Path) -> None:
    status = git_value(repo, ["status", "--short"])
    if status.strip():
        fail("repo must be clean before worktree scaffold:\n" + status)


def select_objective(backlog: dict, requested_id: str | None) -> dict:
    objectives = backlog.get("objectives", [])
    if requested_id:
        for obj in objectives:
            if obj.get("id") == requested_id:
                return obj
        fail(f"objective not found: {requested_id}")

    candidates = [
        obj for obj in objectives
        if obj.get("status") in {"active", "queued"}
        and obj.get("write_capable") is not True
    ]
    if not candidates:
        fail("no active/queued non-write objective found")
    candidates.sort(key=lambda x: x.get("priority", 999))
    return candidates[0]


def copy_info_attributes(repo: Path, worktree: Path) -> None:
    src = repo / ".git" / "info" / "attributes"
    git_file = worktree / ".git"
    if not src.exists() or not git_file.exists() or not git_file.is_file():
        return
    text = git_file.read_text().strip()
    if not text.startswith("gitdir:"):
        return
    gitdir = Path(text.split("gitdir:", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (worktree / gitdir).resolve()
    dst = gitdir / "info" / "attributes"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--objective-id", default=None)
    parser.add_argument("--force-clean-existing", action="store_true")
    args = parser.parse_args()

    project = load_project(args.project_id)
    repo = Path(project["repo_path"])
    state_dir = repo / ".agent_manager"

    if not repo.exists():
        fail(f"missing repo: {repo}")
    if not state_dir.exists():
        fail(f"missing project state: {state_dir}")

    ensure_clean(repo)

    backlog = load_json(state_dir / "OBJECTIVE_BACKLOG.json")
    objective = select_objective(backlog, args.objective_id)

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / args.project_id / f"coder_worktree_{now}"
    worktree_dir = ROOT / "worktrees" / args.project_id / f"coder_worktree_{now}"

    if worktree_dir.exists():
        fail(f"worktree path already exists: {worktree_dir}")

    run_dir.mkdir(parents=True, exist_ok=True)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)

    head = git_value(repo, ["rev-parse", "--short", "HEAD"])
    branch = git_value(repo, ["branch", "--show-current"])

    result = run(["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"], repo)
    if result.returncode != 0:
        fail(result.stderr.strip() or "git worktree add failed")

    copy_info_attributes(repo, worktree_dir)

    wt_status = git_value(worktree_dir, ["status", "--short"])
    wt_head = git_value(worktree_dir, ["rev-parse", "--short", "HEAD"])
    if wt_status.strip():
        fail("new worktree is dirty:\n" + wt_status)

    task_packet = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "profile": "openhands/coder",
        "mode": "scaffold_only",
        "objective": objective,
        "target_repo": str(repo),
        "source_branch": branch,
        "source_head": head,
        "worktree": str(worktree_dir),
        "worktree_head": wt_head,
        "permissions": {
            "run_openhands": False,
            "model_calls": False,
            "modify_main": False,
            "auto_merge": False,
            "auto_push": False,
            "write_capable_execution": False,
        },
    }

    worktree_status = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "worktree": str(worktree_dir),
        "status_short": wt_status.splitlines(),
        "clean": wt_status.strip() == "",
        "head": wt_head,
        "source_repo_status": git_value(repo, ["status", "--short"]).splitlines(),
    }

    prompt = f"""# Coder Task Packet

Project: {args.project_id}
Profile: openhands/coder
Mode: scaffold only
Created UTC: {now}

## Objective

{objective.get('id')}: {objective.get('title', objective.get('description', ''))}

## Worktree

{worktree_dir}

## Hard stops

- Do not run OpenHands in Phase 9.
- Do not call a model.
- Do not edit main.
- Do not merge.
- Do not push.
- Do not modify files outside the assigned future objective scope.
- Deterministic validation remains authority.
"""

    commands = f"""# Dry-run Commands

These commands are documented only. They were not executed by Phase 9.

```bash
cd ~/agent-manager
python3 scripts/apply_openhands_profile.py --profile coder

# Future phase only:
# python3 scripts/apply_openhands_profile.py --profile coder --apply
# openhands --workspace {worktree_dir}
```
"""

    write_json(run_dir / "CODER_TASK_PACKET.json", task_packet)
    write_json(run_dir / "WORKTREE_STATUS.json", worktree_status)
    (run_dir / "CODER_PROMPT.md").write_text(prompt)
    (run_dir / "OPENHANDS_DRY_RUN_COMMANDS.md").write_text(commands)

    latest = ROOT / "runs" / args.project_id / "latest_coder_worktree"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)

    print(f"Prepared coder worktree scaffold for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Worktree: {worktree_dir}")
    print(f"Objective: {objective.get('id')}")
    print("Status: pass")


if __name__ == "__main__":
    main()
