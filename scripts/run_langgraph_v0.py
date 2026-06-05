#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, TypedDict


ROOT = Path(__file__).resolve().parents[1]
INSTALL_HINT = "python -m pip install -U langgraph"
NODE_ORDER = [
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


class LangGraphState(TypedDict, total=False):
    schema_version: int
    project_id: str
    created_utc: str
    run_dir: str
    status: str
    failure: str | None
    artifacts: dict[str, str]
    project: dict[str, Any]
    trace: list[dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def tail_text(text: str, *, max_lines: int = 40, max_chars: int = 4000) -> str:
    lines = text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    if len(tail) > max_chars:
        return tail[-max_chars:]
    return tail


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_langgraph_v0"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def trace_path(state: LangGraphState) -> Path:
    return Path(state["run_dir"]) / "LANGGRAPH_NODE_TRACE.json"


def append_trace(state: LangGraphState, entry: dict[str, Any]) -> LangGraphState:
    trace = list(state.get("trace", []))
    trace.append(entry)
    state["trace"] = trace
    write_json(trace_path(state), trace)
    return state


def new_trace_entry(
    node: str,
    status: str,
    started_utc: str,
    completed_utc: str,
    *,
    command: list[str] | None = None,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
    artifacts_read: list[str] | None = None,
    artifacts_produced: list[str] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "node": node,
        "status": status,
        "started_utc": started_utc,
        "completed_utc": completed_utc,
        "artifacts_read": artifacts_read or [],
        "artifacts_produced": artifacts_produced or [],
    }
    if command is not None:
        entry["command"] = command
    if returncode is not None:
        entry["returncode"] = returncode
    if stdout:
        entry["stdout_tail"] = tail_text(stdout)
    if stderr:
        entry["stderr_tail"] = tail_text(stderr)
    if message:
        entry["message"] = message
    return entry


def mark_skipped(state: LangGraphState, node: str) -> LangGraphState:
    started = utc_now()
    return append_trace(
        state,
        new_trace_entry(
            node,
            "skipped",
            started,
            utc_now(),
            message=f"Skipped because graph status is {state.get('status')!r}.",
        ),
    )


def latest_artifact(project_id: str, name: str) -> str:
    return str((ROOT / "runs" / project_id / name).resolve())


def run_command_node(
    state: LangGraphState,
    node: str,
    command: list[str],
    *,
    artifacts_read: list[str],
    produced_latest_names: list[str],
) -> LangGraphState:
    if state.get("status") != "running":
        return mark_skipped(state, node)

    started = utc_now()
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    produced = [latest_artifact(state["project_id"], name) for name in produced_latest_names]
    status = "pass" if result.returncode == 0 else "fail"
    state = append_trace(
        state,
        new_trace_entry(
            node,
            status,
            started,
            utc_now(),
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            artifacts_read=artifacts_read,
            artifacts_produced=produced,
        ),
    )
    artifacts = dict(state.get("artifacts", {}))
    for name, path in zip(produced_latest_names, produced):
        artifacts[name] = path
    state["artifacts"] = artifacts
    if result.returncode != 0:
        state["status"] = "fail"
        state["failure"] = f"{node} failed with return code {result.returncode}"
    return state


def node_load_project(state: LangGraphState) -> LangGraphState:
    if state.get("status") != "running":
        return mark_skipped(state, "load_project")

    started = utc_now()
    config_path = ROOT / "configs" / "projects.json"
    try:
        data = load_json(config_path)
        project = data["projects"][state["project_id"]]
        repo = Path(project["repo_path"])
        state_dir_name = project.get("project_state_dir", ".agent_manager")
        if not isinstance(state_dir_name, str) or not state_dir_name:
            state_dir_name = ".agent_manager"
        state["project"] = project
        state["artifacts"] = {
            "project_config": str(config_path),
            "target_repo": str(repo),
            "project_state_dir": str(repo / state_dir_name),
        }
        status = "pass"
        message = None
    except Exception as exc:
        state["status"] = "fail"
        state["failure"] = f"load_project failed: {exc}"
        status = "fail"
        message = str(exc)

    return append_trace(
        state,
        new_trace_entry(
            "load_project",
            status,
            started,
            utc_now(),
            artifacts_read=[str(config_path)],
            artifacts_produced=[],
            message=message,
        ),
    )


def make_command_node(
    node: str,
    script: str,
    *,
    reads: Callable[[LangGraphState], list[str]],
    produces: list[str],
) -> Callable[[LangGraphState], LangGraphState]:
    def _node(state: LangGraphState) -> LangGraphState:
        command = ["python3", script, state["project_id"]]
        return run_command_node(state, node, command, artifacts_read=reads(state), produced_latest_names=produces)

    return _node


def node_finalize(state: LangGraphState) -> LangGraphState:
    started = utc_now()
    run_dir = Path(state["run_dir"])
    status = "pass" if state.get("status") == "running" else str(state.get("status", "fail"))
    state["status"] = status
    artifacts = dict(state.get("artifacts", {}))
    artifacts.update(
        {
            "LANGGRAPH_RUN_MANIFEST.json": str(run_dir / "LANGGRAPH_RUN_MANIFEST.json"),
            "LANGGRAPH_STATE_FINAL.json": str(run_dir / "LANGGRAPH_STATE_FINAL.json"),
            "LANGGRAPH_NODE_TRACE.json": str(run_dir / "LANGGRAPH_NODE_TRACE.json"),
            "LANGGRAPH_REPORT.md": str(run_dir / "LANGGRAPH_REPORT.md"),
        }
    )
    state["artifacts"] = artifacts
    state = append_trace(
        state,
        new_trace_entry(
            "finalize",
            status,
            started,
            utc_now(),
            artifacts_read=[str(run_dir / "LANGGRAPH_NODE_TRACE.json")],
            artifacts_produced=[
                str(run_dir / "LANGGRAPH_RUN_MANIFEST.json"),
                str(run_dir / "LANGGRAPH_STATE_FINAL.json"),
                str(run_dir / "LANGGRAPH_REPORT.md"),
            ],
        ),
    )

    manifest = {
        "schema_version": 1,
        "project_id": state["project_id"],
        "created_utc": state["created_utc"],
        "run_dir": state["run_dir"],
        "orchestrator": "langgraph_v0",
        "graph_nodes": NODE_ORDER,
        "status": state["status"],
        "failure": state.get("failure"),
        "artifact_refs": state.get("artifacts", {}),
        "safety": {
            "no_openhands_execution": True,
            "no_model_calls": True,
            "target_project_source_behavior_modified": False,
            "no_auto_merge": True,
            "no_auto_push": True,
            "deterministic_validation_authority_preserved": True,
        },
    }
    write_json(run_dir / "LANGGRAPH_RUN_MANIFEST.json", manifest)
    write_json(run_dir / "LANGGRAPH_STATE_FINAL.json", state)
    (run_dir / "LANGGRAPH_REPORT.md").write_text(build_report(state))
    update_latest_symlink(run_dir, state["project_id"])
    return state


def build_report(state: LangGraphState) -> str:
    lines = [
        "# LangGraph v0 Report",
        "",
        f"Project: {state['project_id']}",
        f"Created UTC: {state['created_utc']}",
        f"Status: {str(state.get('status', 'unknown')).upper()}",
        "",
        "## Safety",
        "",
        "- No OpenHands execution: true",
        "- No model calls: true",
        "- Target project source behavior modified: false",
        "- Auto-merge: false",
        "- Auto-push: false",
        "- Deterministic validation remains authority: true",
        "",
        "## Node Trace",
        "",
    ]
    for entry in state.get("trace", []):
        line = f"- {entry['node']}: {entry['status']}"
        if entry.get("returncode") is not None:
            line += f" (returncode {entry['returncode']})"
        lines.append(line)
    if state.get("failure"):
        lines.extend(["", "## Failure", "", str(state["failure"])])
    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(state.get("artifacts", {}).items()):
        lines.append(f"- {name}: {path}")
    lines.append("")
    return "\n".join(lines)


def require_langgraph() -> Any:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise SystemExit(
            "run_langgraph_v0 failed: LangGraph is not installed.\n"
            f"Install with: {INSTALL_HINT}"
        ) from exc
    return END, StateGraph


def build_graph() -> Any:
    END, StateGraph = require_langgraph()
    graph = StateGraph(LangGraphState)
    graph.add_node("load_project", node_load_project)
    graph.add_node(
        "collect_metrics",
        make_command_node(
            "collect_metrics",
            "scripts/collect_project_metrics.py",
            reads=lambda state: [state.get("artifacts", {}).get("project_config", "")],
            produces=["latest"],
        ),
    )
    graph.add_node(
        "run_plain_runner_v0",
        make_command_node(
            "run_plain_runner_v0",
            "scripts/run_nightly_v0.py",
            reads=lambda state: [state.get("artifacts", {}).get("latest", "")],
            produces=["latest_runner_v0"],
        ),
    )
    graph.add_node(
        "run_manager_planning_pass",
        make_command_node(
            "run_manager_planning_pass",
            "scripts/manager_planning_pass.py",
            reads=lambda state: [
                state.get("artifacts", {}).get("latest", ""),
                state.get("artifacts", {}).get("latest_runner_v0", ""),
            ],
            produces=["latest_manager_plan"],
        ),
    )
    graph.add_node(
        "write_morning_report",
        make_command_node(
            "write_morning_report",
            "scripts/write_morning_report.py",
            reads=lambda state: [
                state.get("artifacts", {}).get("latest", ""),
                state.get("artifacts", {}).get("latest_runner_v0", ""),
                state.get("artifacts", {}).get("latest_manager_plan", ""),
                latest_artifact(state["project_id"], "latest_coder_worktree"),
                latest_artifact(state["project_id"], "latest_validation"),
            ],
            produces=["latest_morning_report"],
        ),
    )
    graph.add_node(
        "validate_agent_run",
        make_command_node(
            "validate_agent_run",
            "scripts/validate_agent_run.py",
            reads=lambda state: [
                state.get("artifacts", {}).get("latest", ""),
                state.get("artifacts", {}).get("latest_runner_v0", ""),
                state.get("artifacts", {}).get("latest_manager_plan", ""),
                state.get("artifacts", {}).get("latest_morning_report", ""),
            ],
            produces=["latest_validation"],
        ),
    )
    graph.add_node(
        "run_readonly_review_agents",
        make_command_node(
            "run_readonly_review_agents",
            "scripts/run_readonly_review_agents.py",
            reads=lambda state: [
                state.get("artifacts", {}).get("latest_validation", ""),
                state.get("artifacts", {}).get("latest_morning_report", ""),
                latest_artifact(state["project_id"], "latest_langgraph_v0"),
            ],
            produces=["latest_review_agents"],
        ),
    )
    graph.add_node(
        "compile_model_routing_plan",
        make_command_node(
            "compile_model_routing_plan",
            "scripts/compile_model_routing_plan.py",
            reads=lambda state: [
                state.get("artifacts", {}).get("project_config", ""),
                state.get("artifacts", {}).get("latest_runner_v0", ""),
                state.get("artifacts", {}).get("latest_manager_plan", ""),
                state.get("artifacts", {}).get("latest_validation", ""),
                state.get("artifacts", {}).get("latest_review_agents", ""),
            ],
            produces=["latest_model_routing"],
        ),
    )
    graph.add_node(
        "prepare_human_approval_packet",
        make_command_node(
            "prepare_human_approval_packet",
            "scripts/prepare_human_approval_packet.py",
            reads=lambda state: [
                state.get("artifacts", {}).get("latest_runner_v0", ""),
                state.get("artifacts", {}).get("latest_manager_plan", ""),
                state.get("artifacts", {}).get("latest_morning_report", ""),
                state.get("artifacts", {}).get("latest_validation", ""),
                state.get("artifacts", {}).get("latest_review_agents", ""),
                state.get("artifacts", {}).get("latest_model_routing", ""),
                latest_artifact(state["project_id"], "latest_nightly_window"),
            ],
            produces=["latest_human_approval"],
        ),
    )
    graph.add_node("finalize", node_finalize)
    graph.set_entry_point("load_project")
    for left, right in zip(NODE_ORDER, NODE_ORDER[1:]):
        graph.add_edge(left, right)
    graph.add_edge("finalize", END)
    return graph.compile()


def initial_state(project_id: str, created_utc: str, run_dir: Path) -> LangGraphState:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "status": "running",
        "failure": None,
        "artifacts": {},
        "trace": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic v0 flow through LangGraph orchestration.")
    parser.add_argument("project_id")
    args = parser.parse_args()

    created_utc = utc_now()
    run_dir = ROOT / "runs" / args.project_id / f"langgraph_v0_{created_utc}"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = initial_state(args.project_id, created_utc, run_dir)
    write_json(run_dir / "LANGGRAPH_NODE_TRACE.json", [])

    app = build_graph()
    final_state = app.invoke(state)
    print(f"LangGraph v0 complete for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Status: {final_state['status']}")
    if final_state["status"] != "pass":
        print(f"Failure: {final_state.get('failure')}")
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("run_langgraph_v0 interrupted")
