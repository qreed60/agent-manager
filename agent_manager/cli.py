from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

from agent_manager.config import load_config, get_project
from agent_manager.adapters.registry import get_adapter


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    return value


def cmd_list_projects(args) -> int:
    config = load_config()
    for project_id, project in sorted(config.projects.items()):
        enabled = "enabled" if project.enabled else "disabled"
        print(f"{project_id}\t{enabled}\t{project.name}\t{project.repo_path}")
    return 0


def cmd_show_project(args) -> int:
    project = get_project(args.project_id)
    print(json.dumps(asdict(project), indent=2, default=_json_default))
    return 0


def cmd_doctor(args) -> int:
    config = load_config()
    exit_code = 0

    for project_id, project in sorted(config.projects.items()):
        adapter = get_adapter(project)
        status = adapter.status()

        print(f"Project: {project_id}")
        print(f"  Name: {project.name}")
        print(f"  Adapter: {status.adapter}")
        print(f"  Repo: {project.repo_path}")
        print(f"  Repo exists: {status.repo_exists}")
        print(f"  Git repo: {status.is_git_repo}")
        print(f"  Branch: {status.current_branch}")
        print(f"  HEAD: {status.head_commit}")
        print(f"  Project state exists: {status.project_state_exists}")

        if status.warnings:
            exit_code = 1
            print("  Warnings:")
            for warning in status.warnings:
                print(f"    - {warning}")

    return exit_code


def cmd_adapter_info(args) -> int:
    project = get_project(args.project_id)
    adapter = get_adapter(project)
    payload = {
        "status": asdict(adapter.status()),
        "metrics_stub": adapter.collect_metrics(),
        "validation_plan_stub": adapter.validation_plan(),
    }
    print(json.dumps(payload, indent=2, default=_json_default))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-projects")
    p.set_defaults(func=cmd_list_projects)

    p = sub.add_parser("show-project")
    p.add_argument("project_id")
    p.set_defaults(func=cmd_show_project)

    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("adapter-info")
    p.add_argument("project_id")
    p.set_defaults(func=cmd_adapter_info)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
