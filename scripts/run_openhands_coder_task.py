#!/usr/bin/env python3
"""Phase 18B: controlled OpenHands coder execution scaffold.

Default mode writes a bounded task packet only. Live OpenHands execution requires
both --allow-openhands and AGENT_MANAGER_ENABLE_OPENHANDS=1, and it is confined
to an isolated worktree under worktrees/<project_id>/.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase18f_manual_nonsmoke_write_gate"
DEFAULT_ENV_FILE = Path.home() / ".config" / "agent-manager" / "env.local"
OPENHANDS_ENV_NAMES = [
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "MODEL",
]
SECRET_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
REQUIRED_ARTIFACTS = [
    "OPENHANDS_CODER_RUN.json",
    "OPENHANDS_CODER_RUN.md",
    "OPENHANDS_TASK_PROMPT.md",
    "OPENHANDS_COMMAND.txt",
    "OPENHANDS_STDOUT.txt",
    "OPENHANDS_STDERR.txt",
    "OPENHANDS_EXIT_STATUS.json",
    "OPENHANDS_SAFETY_STATUS.json",
    "OPENHANDS_WORKTREE_STATUS_BEFORE.txt",
    "OPENHANDS_WORKTREE_STATUS_AFTER.txt",
    "OPENHANDS_DIFF_SUMMARY.txt",
    "OPENHANDS_CODER_SUMMARY.json",
    "OPENHANDS_CODER_SUMMARY.md",
    "OPENHANDS_WORKTREE_INFO.json",
    "OPENHANDS_CHANGED_FILES.json",
    "OPENHANDS_SCOPE_STATUS.json",
]
ARTIFACT_POINTERS: dict[str, tuple[str, ...]] = {
    "latest_human_approval": ("APPROVAL_SUMMARY.json", "APPROVAL_PACKET.json"),
    "latest_ai_readonly": ("AI_READONLY_SUMMARY.json", "AI_RESPONSE_PARSED.json"),
    "latest_nightly_window": ("NIGHTLY_WINDOW_REPORT.json", "NIGHTLY_SAFETY_STATUS.json"),
    "latest_langgraph_v0": ("LANGGRAPH_RUN_MANIFEST.json", "LANGGRAPH_STATE_FINAL.json"),
    "latest_validation": ("VALIDATION_REPORT.json", "VALIDATION_SUMMARY.json"),
    "latest_review_agents": ("REVIEW_AGENTS_SUMMARY.json",),
    "latest_model_routing": ("MODEL_ROUTING_SUMMARY.json", "MODEL_ROUTING_PLAN.json"),
    "latest_morning_report": ("MORNING_REPORT.json",),
    "latest_runner_v0": ("RUN_MANIFEST.json", "ACTIVE_OBJECTIVE.json"),
    "latest_manager_plan": ("MANAGER_DECISION.json", "MANAGER_CONTEXT.json"),
    "latest_coder_worktree": ("CODER_TASK_PACKET.json", "WORKTREE_STATUS.json"),
}


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
OPENHANDS_CAPABILITY_TIMEOUT_SECONDS = 30
SMOKE_EXPECTED_FILE = ".agent_manager_scratch/OPENHANDS_SMOKE_TEST.md"
SMOKE_ALLOWED_FILES = [SMOKE_EXPECTED_FILE]


class OpenHandsCommandError(RuntimeError):
    """Raised when a safe headless OpenHands command cannot be built."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def load_project(project_id: str) -> dict[str, Any]:
    data = load_json(ROOT / "configs" / "projects.json")
    project = data.get("projects", {}).get(project_id)
    if not isinstance(project, dict):
        raise SystemExit(f"unknown project id: {project_id}")
    return project


def project_state_dir(project: dict[str, Any]) -> Path:
    repo_raw = project.get("repo_path")
    if not isinstance(repo_raw, str) or not repo_raw:
        raise SystemExit("project repo_path must be a non-empty string")
    state_dir_name = project.get("project_state_dir", ".agent_manager")
    if not isinstance(state_dir_name, str) or not state_dir_name:
        state_dir_name = ".agent_manager"
    return Path(repo_raw) / state_dir_name


def select_objective(project: dict[str, Any], objective_id: str | None) -> dict[str, Any]:
    backlog_path = project_state_dir(project) / "OBJECTIVE_BACKLOG.json"
    try:
        backlog = load_json(backlog_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"id": objective_id or "phase18b_controlled_openhands_coder_execution"}

    objectives = backlog.get("objectives") if isinstance(backlog, dict) else []
    if not isinstance(objectives, list):
        objectives = []
    if objective_id:
        for item in objectives:
            if isinstance(item, dict) and item.get("id") == objective_id:
                return item
        return {"id": objective_id}
    for item in objectives:
        if isinstance(item, dict) and item.get("status") in {"active", "queued"}:
            return item
    return {"id": "phase18b_controlled_openhands_coder_execution"}


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return values
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def build_subprocess_env(env_file: Path | None) -> tuple[dict[str, str], dict[str, Any]]:
    env = dict(os.environ)
    selected_env_file = env_file if env_file is not None else DEFAULT_ENV_FILE
    loaded = read_env_file(selected_env_file)
    for key, value in loaded.items():
        env.setdefault(key, value)
    visible = {
        key: {"present": bool(env.get(key)), "redacted": any(part in key for part in SECRET_NAME_PARTS)}
        for key in OPENHANDS_ENV_NAMES
    }
    return env, {"env_file": str(selected_env_file), "loaded_env_names": sorted(loaded), "openhands_env": visible}


def safe_json_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "schema_version",
        "status",
        "blocking",
        "generated_by",
        "run_dir",
        "selected_objective_id",
        "recommended_human_decision",
        "model_call_performed",
    ):
        if key in data and not _looks_secret(key):
            summary[key] = data[key]
    return summary


def load_artifact_summaries(project_id: str) -> dict[str, Any]:
    run_root = ROOT / "runs" / project_id
    summaries: dict[str, Any] = {}
    for pointer_name, filenames in ARTIFACT_POINTERS.items():
        pointer = run_root / pointer_name
        item: dict[str, Any] = {"present": False}
        if pointer.exists() or pointer.is_symlink():
            try:
                resolved = pointer.resolve()
            except OSError:
                resolved = pointer
            item["present"] = resolved.is_dir()
            item["path"] = str(resolved)
            files: dict[str, Any] = {}
            if resolved.is_dir():
                for filename in filenames:
                    files[filename] = safe_json_summary(resolved / filename)
            item["files"] = files
        summaries[pointer_name] = item
    return summaries


def _looks_secret(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in SECRET_NAME_PARTS)


def latest_coder_worktree_path(project_id: str) -> Path | None:
    pointer = ROOT / "runs" / project_id / "latest_coder_worktree"
    if not (pointer.exists() or pointer.is_symlink()):
        return None
    packet = safe_json_summary(pointer.resolve() / "CODER_TASK_PACKET.json")
    # safe_json_summary intentionally drops most keys; load this specific file
    # because the worktree path is central-run metadata, not target source.
    try:
        data = json.loads((pointer.resolve() / "CODER_TASK_PACKET.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    worktree = data.get("worktree") if isinstance(data, dict) else None
    if isinstance(worktree, str) and worktree:
        return Path(worktree)
    _ = packet
    return None


def resolve_worktree_path(project_id: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    latest = latest_coder_worktree_path(project_id)
    if latest is not None:
        return latest.expanduser().resolve()
    return (ROOT / "worktrees" / project_id).resolve()


def ensure_worktree_allowed(project_id: str, worktree: Path, canonical_repo: Path) -> Path:
    resolved = worktree.expanduser().resolve()
    canonical = canonical_repo.expanduser().resolve()
    allowed_root = (ROOT / "worktrees" / project_id).resolve()
    if resolved == canonical or canonical in resolved.parents:
        raise ValueError(f"OpenHands worktree must not be the canonical repo: {resolved}")
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise ValueError(f"OpenHands worktree must be under {allowed_root}: {resolved}")
    return resolved


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git_output(args: list[str], cwd: Path) -> str:
    result = run_git(args, cwd)
    if result.returncode != 0:
        return (result.stderr or result.stdout).strip()
    return result.stdout


def worktree_branch(worktree: Path) -> str:
    branch = git_output(["branch", "--show-current"], worktree).strip()
    if branch:
        return branch
    head = git_output(["rev-parse", "--short", "HEAD"], worktree).strip()
    return f"detached:{head}" if head else "unknown"


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_openhands_coder"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)


def create_fresh_openhands_worktree(
    project_id: str,
    canonical_repo: Path,
    created_utc: str,
) -> dict[str, Any]:
    """Create a fresh git worktree for this OpenHands run.

    Returns worktree metadata for artifact recording.
    """
    canonical = canonical_repo.expanduser().resolve()
    worktree_root = (ROOT / "worktrees" / project_id).resolve()
    worktree_root.mkdir(parents=True, exist_ok=True)

    timestamp = created_utc.replace("T", "_").replace("Z", "")
    worktree_dir = (worktree_root / f"openhands_coder_{created_utc}").resolve()
    branch_name = f"agent-manager/{project_id}/openhands-coder-{timestamp}"
    base_branch = git_output(["branch", "--show-current"], canonical).strip() or "HEAD"

    if worktree_dir.exists():
        raise SystemExit(f"fresh OpenHands worktree path already exists: {worktree_dir}")

    result = run_git(["worktree", "add", "-b", branch_name, str(worktree_dir), "HEAD"], canonical)
    if result.returncode != 0:
        raise SystemExit(f"could not create fresh OpenHands worktree: {result.stderr.strip() or result.stdout.strip()}")

    return {
        "worktree_path": worktree_dir,
        "worktree_branch": branch_name,
        "base_branch": base_branch,
        "worktree_head": git_output(["rev-parse", "HEAD"], worktree_dir).strip(),
        "worktree_created": True,
        "reused_existing_worktree": False,
        "status": "active",
    }


def detect_changed_files(worktree: Path) -> dict[str, Any]:
    """Detect changed files in the worktree including untracked files."""
    # git status --short --untracked-files=all
    status_result = run_git(["status", "--short", "--untracked-files=all"], worktree)
    short_status = status_result.stdout if status_result.returncode == 0 else ""

    # git diff --name-only (unstaged tracked changes)
    diff_result = run_git(["diff", "--name-only"], worktree)
    unstaged_tracked = (
        [f for f in diff_result.stdout.strip().split("\n") if f]
        if diff_result.returncode == 0
        else []
    )

    # git diff --cached --name-only (staged changes)
    staged_result = run_git(["diff", "--cached", "--name-only"], worktree)
    staged_files = (
        [f for f in staged_result.stdout.strip().split("\n") if f]
        if staged_result.returncode == 0
        else []
    )

    # Parse short status for untracked files and tracked modifications
    tracked_modified = []
    untracked = []
    for line in short_status.strip().split("\n"):
        if not line:
            continue
        # Format: XY filename (X=index, Y=working tree)
        if len(line) >= 3:
            status_chars = line[:2]
            filename = line[3:].strip()
            if status_chars == "??" and filename:
                untracked.append(filename)
            elif (status_chars[0] != " " or status_chars[1] != " ") and filename:
                tracked_modified.append(filename)

    all_changed = sorted(set(unstaged_tracked + staged_files + tracked_modified + untracked))
    worktree_changed = bool(all_changed)

    return {
        "tracked_modified_files": sorted(set(tracked_modified)),
        "staged_files": sorted(set(staged_files)),
        "untracked_files": sorted(set(untracked)),
        "all_changed_files": all_changed,
        "worktree_changed": worktree_changed,
    }


def normalize_allowed_files(paths: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in paths or []:
        path = str(raw).strip()
        if not path:
            continue
        normalized.append(path[2:] if path.startswith("./") else path)
    return sorted(set(normalized))


def task_type_for_prompt(*, task_text: str | None, task_file: str | None, smoke_task: bool) -> str:
    if smoke_task:
        return "smoke"
    if task_text is not None:
        return "manual_task_text"
    if task_file is not None:
        return "manual_task_file"
    return "generated"


def validate_allowed_file_usage(*, smoke_task: bool, task_type: str, manual_allowed_files: list[str], live_execution_allowed: bool) -> None:
    if smoke_task and manual_allowed_files and manual_allowed_files != SMOKE_ALLOWED_FILES:
        raise ValueError("--allowed-file may only be used with --smoke-task when it exactly matches the smoke file")
    if live_execution_allowed and task_type in {"manual_task_text", "manual_task_file"} and not manual_allowed_files:
        raise ValueError("live non-smoke task overrides require at least one --allowed-file")


def compute_scope_status(
    *,
    smoke_task: bool,
    objective: dict[str, Any],
    changed_files: list[str],
    canonical_repo_clean: bool,
    manual_allowed_files: list[str] | None = None,
    manual_write_task: bool = False,
) -> dict[str, Any]:
    """Compute scope guard status for the OpenHands run."""
    manual_allowed = normalize_allowed_files(manual_allowed_files)
    if smoke_task:
        allowed = manual_allowed or SMOKE_ALLOWED_FILES
        task_type = "smoke"
    elif manual_allowed:
        allowed = manual_allowed
        task_type = "manual"
    else:
        allowed_raw = objective.get("allowed_files")
        if isinstance(allowed_raw, list) and len(allowed_raw) > 0:
            allowed = normalize_allowed_files([str(f) for f in allowed_raw])
            task_type = "non-smoke"
        else:
            if not changed_files:
                status = "warn" if manual_write_task or objective.get("write_capable") is True else "pass"
                details = (
                    "manual live write task changed no files"
                    if manual_write_task
                    else "no allowed_files available for non-smoke write-capable task; scope cannot be verified"
                    if status == "warn"
                    else "no changed files detected"
                )
                return {
                    "schema_version": 1,
                    "project_id": "",
                    "created_utc": "",
                    "task_type": "manual" if manual_write_task else "non-smoke",
                    "allowed_files": [],
                    "changed_files": [],
                    "scope_status": status,
                    "details": details,
                }
            return {
                "schema_version": 1,
                "project_id": "",
                "created_utc": "",
                "task_type": "manual" if manual_write_task else "non-smoke",
                "allowed_files": [],
                "changed_files": changed_files,
                "scope_status": "warn",
                "details": "no allowed_files available for non-smoke write-capable task; scope cannot be verified",
            }

    if not changed_files:
        no_change_status = "warn" if manual_write_task else ("fail" if not canonical_repo_clean else "pass")
        no_change_details = (
            "manual live write task changed no files"
            if manual_write_task
            else "canonical repo is dirty"
            if not canonical_repo_clean
            else "no changed files detected"
        )
        return {
            "schema_version": 1,
            "project_id": "",
            "created_utc": "",
            "task_type": task_type,
            "allowed_files": allowed,
            "changed_files": [],
            "scope_status": no_change_status,
            "details": no_change_details,
        }

    violations = []
    for f in changed_files:
        matched = any(f == allowed_path or f.startswith(allowed_path + "/") for allowed_path in allowed)
        protected = (
            f == ".git"
            or f.startswith(".git/")
            or f.startswith("generated_exports/")
            or f.startswith("exports/")
            or f.startswith(".agent_manager/")
        )
        if protected and not matched:
            violations.append(f"protected path outside scope: {f}")
            continue
        if not matched:
            violations.append(f"file outside scope: {f}")

    # Determine status
    if not canonical_repo_clean:
        scope_status = "fail"
        details = "canonical repo is dirty"
    elif violations:
        scope_status = "fail"
        details = "; ".join(violations)
    else:
        scope_status = "pass"
        details = "all changed files within allowed scope"

    return {
        "schema_version": 1,
        "project_id": "",
        "created_utc": "",
        "task_type": task_type,
        "allowed_files": allowed,
        "changed_files": changed_files,
        "scope_status": scope_status,
        "details": details,
    }


def build_prompt(
    *,
    project_id: str,
    objective: dict[str, Any],
    worktree: Path,
    artifact_summaries: dict[str, Any],
    max_prompt_chars: int,
) -> str:
    objective_text = json.dumps(
        {
            "id": objective.get("id"),
            "title": objective.get("title"),
            "phase": objective.get("phase"),
            "risk_level": objective.get("risk_level"),
            "description": objective.get("description"),
        },
        indent=2,
        sort_keys=True,
    )
    summaries = json.dumps(artifact_summaries, indent=2, sort_keys=True)
    prompt = f"""# OpenHands Controlled Coder Task

Project: {project_id}
Objective ID: {objective.get('id', 'unknown')}
Worktree: {worktree}

## Execution Boundaries

- Work only inside the isolated worktree above.
- Do not modify the canonical project checkout.
- Do not stage, commit, push, merge, or create a PR.
- Leave any worktree edits unstaged for human review.
- Use deterministic validation artifacts as context.
- Keep changes scoped to the selected objective.

## Selected Objective

```json
{objective_text}
```

## Concise Latest Artifact Summaries

```json
{summaries}
```
"""
    if len(prompt) > max_prompt_chars:
        suffix = "\n\n[Prompt truncated to respect --max-prompt-chars]\n"
        prompt = prompt[: max(0, max_prompt_chars - len(suffix))] + suffix
    return prompt


def truncate_prompt(prompt: str, max_prompt_chars: int) -> str:
    if len(prompt) <= max_prompt_chars:
        return prompt
    suffix = "\n\n[Prompt truncated to respect --max-prompt-chars]\n"
    return prompt[: max(0, max_prompt_chars - len(suffix))] + suffix


def build_smoke_prompt() -> str:
    return f"""# OpenHands Smoke Task

The current shell working directory is the isolated worktree. Create the smoke
file relative to the current working directory only.

Do not create the file beside `OPENHANDS_TASK_PROMPT.md`.
Do not use the run directory.

Use this exact command or an equivalent command:

```bash
mkdir -p .agent_manager_scratch
printf '%s\\n' 'OpenHands smoke test completed.' > {SMOKE_EXPECTED_FILE}
```

Boundaries:
- Do not inspect the repository broadly.
- Do not run tests.
- Do not commit.
- Do not push.
- Finish immediately after that.
"""


def prompt_override_count(task_text: str | None, task_file: str | None, smoke_task: bool) -> int:
    return sum([task_text is not None, task_file is not None, smoke_task])


def resolve_prompt(
    *,
    generated_prompt: str,
    task_text: str | None,
    task_file: str | None,
    smoke_task: bool,
    max_prompt_chars: int,
) -> tuple[str, str]:
    count = prompt_override_count(task_text, task_file, smoke_task)
    if count > 1:
        raise ValueError("--task-text, --task-file, and --smoke-task are mutually exclusive")
    if task_text is not None:
        return truncate_prompt(task_text, max_prompt_chars), "task_text"
    if task_file is not None:
        return truncate_prompt(Path(task_file).expanduser().read_text(), max_prompt_chars), "task_file"
    if smoke_task:
        return truncate_prompt(build_smoke_prompt(), max_prompt_chars), "smoke_task"
    return generated_prompt, "generated"


def misplaced_smoke_file_paths(*, worktree: Path, run_dir: Path) -> list[str]:
    expected = (worktree / SMOKE_EXPECTED_FILE).resolve()
    candidates = [run_dir / SMOKE_EXPECTED_FILE]
    misplaced: list[str] = []
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != expected:
            misplaced.append(str(candidate))
    return misplaced


def openhands_base_command(openhands_command: str) -> list[str]:
    base = shlex.split(openhands_command)
    if not base:
        base = ["openhands"]
    return base


def build_openhands_command(openhands_command: str, prompt_path: Path) -> list[str]:
    base = openhands_base_command(openhands_command)
    return [*base, "--override-with-envs", "--task", str(prompt_path)]


def parse_openhands_help_flags(help_text: str) -> set[str]:
    return set(re.findall(r"(?<![\w-])--[A-Za-z0-9][A-Za-z0-9-]*", help_text))


def detect_openhands_supported_flags(
    openhands_command: str,
    *,
    cwd: Path,
    env: dict[str, str],
    command_runner: CommandRunner,
) -> tuple[set[str], int]:
    command = [*openhands_base_command(openhands_command), "--help"]
    result = command_runner(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=OPENHANDS_CAPABILITY_TIMEOUT_SECONDS,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return parse_openhands_help_flags(stdout + "\n" + stderr), int(result.returncode)


def build_headless_openhands_command(
    openhands_command: str,
    *,
    prompt_path: Path,
    prompt_text: str,
    supported_flags: set[str],
) -> list[str]:
    if "--headless" not in supported_flags:
        raise OpenHandsCommandError("OpenHands does not support --headless; refusing to launch the interactive CLI")

    command = [*openhands_base_command(openhands_command), "--override-with-envs", "--headless"]
    if "--json" in supported_flags:
        command.append("--json")
    if "--exit-without-confirmation" in supported_flags:
        command.append("--exit-without-confirmation")

    if "--file" in supported_flags:
        command.extend(["--file", str(prompt_path)])
    elif "--task" in supported_flags:
        command.extend(["--task", prompt_text])
    else:
        raise OpenHandsCommandError("OpenHands supports --headless but neither --file nor --task")

    validate_headless_openhands_command(command)
    return command


def validate_headless_openhands_command(command: list[str]) -> None:
    if not command:
        raise OpenHandsCommandError("empty OpenHands command")
    launcher = Path(command[0]).name
    if launcher in {"tmux", "screen"}:
        raise OpenHandsCommandError(f"refusing detached interactive launcher: {launcher}")
    if "--headless" not in command:
        raise OpenHandsCommandError("refusing OpenHands command without --headless")
    if "--override-with-envs" not in command:
        raise OpenHandsCommandError("refusing OpenHands command without --override-with-envs")
    if "--file" in command:
        index = command.index("--file")
        if index + 1 >= len(command) or not command[index + 1]:
            raise OpenHandsCommandError("OpenHands --file requires a prompt path")
        return
    if "--task" in command:
        index = command.index("--task")
        if index + 1 >= len(command) or not command[index + 1]:
            raise OpenHandsCommandError("OpenHands --task requires prompt text")
        if Path(command[index + 1]).name == "OPENHANDS_TASK_PROMPT.md":
            raise OpenHandsCommandError("refusing to pass a prompt file path through --task")
        return
    raise OpenHandsCommandError("refusing OpenHands command without --file or --task")


def refused_openhands_command(openhands_command: str, reason: str) -> list[str]:
    return [*openhands_base_command(openhands_command), "--override-with-envs", f"[refused: {reason}]"]


def build_safety_status(
    *,
    project_id: str,
    created_utc: str,
    run_dir: Path,
    allow_openhands: bool,
    dry_run: bool,
    env_enabled: bool,
) -> dict[str, Any]:
    live_allowed = allow_openhands and env_enabled and not dry_run
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "openhands_execution_allowed": live_allowed,
        "dry_run": not live_allowed,
        "canonical_repo_writes_allowed": False,
        "worktree_writes_allowed": live_allowed,
        "auto_push_allowed": False,
        "auto_merge_allowed": False,
        "pr_creation_allowed": False,
        "auto_commit_allowed": False,
        "secrets_redacted": True,
        "allow_openhands_flag": allow_openhands,
        "env_gate_enabled": env_enabled,
    }


def completed_without_run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "", "")


def run_openhands(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    command_runner: CommandRunner,
) -> subprocess.CompletedProcess[str]:
    return command_runner(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )


def generate(
    project_id: str,
    *,
    created_utc: str | None = None,
    timeout_seconds: int = 1800,
    max_prompt_chars: int = 12000,
    objective_id: str | None = None,
    worktree_path: str | None = None,
    openhands_command: str = "openhands",
    env_file: str | None = None,
    dry_run: bool = False,
    allow_openhands: bool = False,
    task_text: str | None = None,
    task_file: str | None = None,
    smoke_task: bool = False,
    allowed_files: list[str] | None = None,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    created = created_utc or utc_now()
    project = load_project(project_id)
    canonical_repo = Path(str(project["repo_path"])).expanduser().resolve()

    env_for_safety = dict(os.environ)
    env_file_resolved = Path(env_file).expanduser() if env_file else DEFAULT_ENV_FILE
    loaded_envs = read_env_file(env_file_resolved)
    for key, value in loaded_envs.items():
        env_for_safety.setdefault(key, value)
    live_execution_allowed = allow_openhands and env_for_safety.get("AGENT_MANAGER_ENABLE_OPENHANDS") == "1" and not dry_run
    task_type = task_type_for_prompt(task_text=task_text, task_file=task_file, smoke_task=smoke_task)
    task_override_used = task_type in {"smoke", "manual_task_text", "manual_task_file"}
    manual_allowed_files = normalize_allowed_files(allowed_files)
    validate_allowed_file_usage(
        smoke_task=smoke_task,
        task_type=task_type,
        manual_allowed_files=manual_allowed_files,
        live_execution_allowed=live_execution_allowed,
    )

    if live_execution_allowed:
        worktree_meta = create_fresh_openhands_worktree(project_id, canonical_repo, created)
        worktree = Path(str(worktree_meta["worktree_path"]))
    else:
        worktree = ensure_worktree_allowed(project_id, resolve_worktree_path(project_id, worktree_path), canonical_repo)
        if not worktree.exists():
            raise SystemExit(f"worktree path does not exist: {worktree}")
        worktree_meta = {
            "worktree_path": worktree,
            "worktree_branch": worktree_branch(worktree),
            "base_branch": "HEAD",
            "worktree_head": git_output(["rev-parse", "HEAD"], worktree).strip(),
            "worktree_created": False,
            "reused_existing_worktree": (latest_coder_worktree_path(project_id) is not None) and (worktree_path is None),
            "status": "dry_run",
        }
    worktree = ensure_worktree_allowed(project_id, worktree, canonical_repo)
    branch = str(worktree_meta["worktree_branch"])
    fresh_worktree_created = bool(worktree_meta["worktree_created"])
    reused_existing_worktree = bool(worktree_meta["reused_existing_worktree"])

    if Path.cwd().resolve() == canonical_repo.expanduser().resolve():
        raise SystemExit("run_openhands_coder_task.py must not be launched from the canonical target repo")

    run_dir = ROOT / "runs" / project_id / f"openhands_coder_{created}"
    run_dir.mkdir(parents=True, exist_ok=True)
    objective = select_objective(project, objective_id)
    artifact_summaries = load_artifact_summaries(project_id)
    generated_prompt = build_prompt(
        project_id=project_id,
        objective=objective,
        worktree=worktree,
        artifact_summaries=artifact_summaries,
        max_prompt_chars=max_prompt_chars,
    )
    prompt, prompt_source = resolve_prompt(
        generated_prompt=generated_prompt,
        task_text=task_text,
        task_file=task_file,
        smoke_task=smoke_task,
        max_prompt_chars=max_prompt_chars,
    )
    prompt_path = run_dir / "OPENHANDS_TASK_PROMPT.md"
    prompt_path.write_text(prompt)

    env, env_summary = build_subprocess_env(Path(env_file).expanduser() if env_file else None)
    env_enabled = env.get("AGENT_MANAGER_ENABLE_OPENHANDS") == "1"
    safety = build_safety_status(
        project_id=project_id,
        created_utc=created,
        run_dir=run_dir,
        allow_openhands=allow_openhands,
        dry_run=dry_run,
        env_enabled=env_enabled,
    )
    command = build_openhands_command(openhands_command, prompt_path)

    before_status = git_output(["status", "--short", "--untracked-files=all"], worktree)
    stdout = ""
    stderr = ""
    timed_out = False
    execution_performed = False
    returncode = 0
    command_refusal_reason: str | None = None
    openhands_supported_flags: list[str] | None = None
    openhands_help_returncode: int | None = None

    if safety["openhands_execution_allowed"]:
        try:
            supported_flags, help_returncode = detect_openhands_supported_flags(
                openhands_command,
                cwd=worktree,
                env=env,
                command_runner=command_runner,
            )
            openhands_supported_flags = sorted(supported_flags)
            openhands_help_returncode = help_returncode
            command = build_headless_openhands_command(
                openhands_command,
                prompt_path=prompt_path,
                prompt_text=prompt,
                supported_flags=supported_flags,
            )
        except (OpenHandsCommandError, subprocess.TimeoutExpired, OSError) as exc:
            command_refusal_reason = str(exc)
            command = refused_openhands_command(openhands_command, command_refusal_reason)
            stderr = f"{command_refusal_reason}\n"
            returncode = 2
            safety["openhands_execution_allowed"] = False
            safety["dry_run"] = True
            safety["worktree_writes_allowed"] = False
        if command_refusal_reason is None:
            execution_performed = True
            try:
                result = run_openhands(
                    command,
                    cwd=worktree,
                    env=env,
                    timeout_seconds=timeout_seconds,
                    command_runner=command_runner,
                )
                stdout = result.stdout or ""
                stderr = result.stderr or ""
                returncode = int(result.returncode)
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                returncode = 124
                stdout = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr = exc.stderr if isinstance(exc.stderr, str) else ""
                stderr += f"\nOpenHands timed out after {timeout_seconds} seconds.\n"
    else:
        result = completed_without_run(command)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        returncode = int(result.returncode)

    after_status = git_output(["status", "--short", "--untracked-files=all"], worktree)
    diff_summary = git_output(["diff", "--stat"], worktree)
    if not diff_summary.strip():
        diff_summary = "No unstaged diff reported.\n"
    canonical_repo_status = git_output(["status", "--short"], canonical_repo)
    canonical_repo_clean = not canonical_repo_status.strip()
    expected_smoke_file = worktree / SMOKE_EXPECTED_FILE
    expected_smoke_file_exists = expected_smoke_file.exists()
    misplaced_paths = misplaced_smoke_file_paths(worktree=worktree, run_dir=run_dir)

    # Detect changed files including untracked files
    changed_files_data = detect_changed_files(worktree) if execution_performed else {
        "tracked_modified_files": [],
        "staged_files": [],
        "untracked_files": [],
        "all_changed_files": [],
        "worktree_changed": False,
    }

    exit_status = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created,
        "execution_performed": execution_performed,
        "returncode": returncode,
        "timed_out": timed_out,
        "status": "pass" if returncode == 0 else ("fail" if command_refusal_reason else "warn"),
    }
    run_record = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created,
        "generated_by": GENERATED_BY,
        "status": exit_status["status"],
        "objective": objective,
        "canonical_repo": str(canonical_repo),
        "worktree_path": str(worktree),
        "worktree_git_branch": branch,
        "fresh_worktree_created": fresh_worktree_created,
        "reused_existing_worktree": reused_existing_worktree,
        "artifacts_read": artifact_summaries,
        "env_summary": env_summary,
        "command_argv_redacted": command,
        "prompt_source": prompt_source,
        "manual_allowed_files": manual_allowed_files,
        "task_override_used": task_override_used,
        "task_type": task_type,
        "execution_performed": execution_performed,
        "required_artifacts": REQUIRED_ARTIFACTS,
        "openhands_supported_flags": openhands_supported_flags,
        "openhands_help_returncode": openhands_help_returncode,
        "command_refusal_reason": command_refusal_reason,
    }

    # Compute scope status
    scope_status_data = compute_scope_status(
        smoke_task=smoke_task,
        objective=objective,
        changed_files=changed_files_data.get("all_changed_files", []),
        canonical_repo_clean=canonical_repo_clean,
        manual_allowed_files=manual_allowed_files if task_type in {"manual_task_text", "manual_task_file"} else None,
        manual_write_task=execution_performed and task_type in {"manual_task_text", "manual_task_file"},
    )
    scope_status_data["project_id"] = project_id
    scope_status_data["created_utc"] = created

    summary = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created,
        "generated_by": GENERATED_BY,
        "status": exit_status["status"],
        "run_dir": str(run_dir),
        "objective_id": objective.get("id"),
        "worktree_path": str(worktree),
        "worktree_git_branch": branch,
        "fresh_worktree_created": fresh_worktree_created,
        "reused_existing_worktree": reused_existing_worktree,
        "openhands_execution_performed": execution_performed,
        "dry_run": safety["dry_run"],
        "prompt_source": prompt_source,
        "manual_allowed_files": manual_allowed_files,
        "task_override_used": task_override_used,
        "task_type": task_type,
        "returncode": returncode,
        "worktree_changed": before_status != after_status or bool(after_status.strip()),
        "no_commit_push_merge_or_pr_performed": True,
        "command_refusal_reason": command_refusal_reason,
    }

    smoke_status: dict[str, Any] | None = None
    if smoke_task:
        smoke_passed = (
            execution_performed
            and returncode == 0
            and not timed_out
            and expected_smoke_file_exists
            and canonical_repo_clean
            and not misplaced_paths
            and scope_status_data.get("scope_status") == "pass"
        )
        smoke_status = {
            "schema_version": 1,
            "project_id": project_id,
            "created_utc": created,
            "smoke_task": True,
            "expected_file": SMOKE_EXPECTED_FILE,
            "worktree_path": str(worktree),
            "expected_file_absolute_path": str(expected_smoke_file),
            "run_dir": str(run_dir),
            "misplaced_file_paths": misplaced_paths,
            "expected_file_exists": expected_smoke_file_exists,
            "canonical_repo_clean": canonical_repo_clean,
            "returncode": returncode,
            "timed_out": timed_out,
            "openhands_execution_performed": execution_performed,
            "scope_status": scope_status_data.get("scope_status", "warn"),
            "status": "pass" if smoke_passed else ("fail" if not canonical_repo_clean or scope_status_data.get("scope_status") == "fail" else "warn"),
        }
        summary["smoke_status"] = smoke_status["status"]

    # Update summary status based on all factors
    final_status = exit_status["status"]
    if smoke_task:
        if scope_status_data.get("scope_status") == "fail":
            final_status = "fail"
        elif not canonical_repo_clean:
            final_status = "fail"
        elif smoke_status and smoke_status["status"] in {"warn", "fail"}:
            final_status = smoke_status["status"]
    else:
        if scope_status_data.get("scope_status") == "fail":
            final_status = "fail"
        elif not canonical_repo_clean:
            final_status = "fail"
        elif final_status == "pass" and scope_status_data.get("scope_status") == "warn":
            final_status = "warn"

    summary["status"] = final_status

    # Write new artifacts
    worktree_info = {
        "schema_version": 1,
        "project_id": project_id,
        "created_utc": created,
        "canonical_repo": str(canonical_repo),
        "worktree_path": str(worktree),
        "worktree_branch": branch,
        "worktree_created": fresh_worktree_created,
        "reused_existing_worktree": reused_existing_worktree,
        "worktree_head": str(worktree_meta["worktree_head"]),
        "base_branch": str(worktree_meta["base_branch"]),
        "status": "active" if execution_performed else str(worktree_meta["status"]),
    }

    (run_dir / "OPENHANDS_WORKTREE_INFO.json").write_text(json.dumps(worktree_info, indent=2, sort_keys=True) + "\n")
    (run_dir / "OPENHANDS_CHANGED_FILES.json").write_text(json.dumps(changed_files_data, indent=2, sort_keys=True) + "\n")
    (run_dir / "OPENHANDS_SCOPE_STATUS.json").write_text(json.dumps(scope_status_data, indent=2, sort_keys=True) + "\n")

    (run_dir / "OPENHANDS_COMMAND.txt").write_text(shlex.join(command) + "\n")
    (run_dir / "OPENHANDS_STDOUT.txt").write_text(stdout)
    (run_dir / "OPENHANDS_STDERR.txt").write_text(stderr)
    (run_dir / "OPENHANDS_WORKTREE_STATUS_BEFORE.txt").write_text(before_status)
    (run_dir / "OPENHANDS_WORKTREE_STATUS_AFTER.txt").write_text(after_status)
    (run_dir / "OPENHANDS_DIFF_SUMMARY.txt").write_text(diff_summary)
    write_json(run_dir / "OPENHANDS_CODER_RUN.json", run_record)
    write_json(run_dir / "OPENHANDS_EXIT_STATUS.json", exit_status)
    write_json(run_dir / "OPENHANDS_SAFETY_STATUS.json", safety)
    if smoke_status is not None:
        write_json(run_dir / "OPENHANDS_SMOKE_STATUS.json", smoke_status)
    write_json(run_dir / "OPENHANDS_CODER_SUMMARY.json", summary)
    (run_dir / "OPENHANDS_CODER_RUN.md").write_text(
        f"""# OpenHands Coder Run

- Project: `{project_id}`
- Objective: `{objective.get('id', 'unknown')}`
- Status: `{exit_status['status']}`
- Dry run: `{str(safety['dry_run']).lower()}`
- OpenHands executed: `{str(execution_performed).lower()}`
- Worktree: `{worktree}`
- Branch: `{branch}`
- Auto commit/push/merge/PR: `false`
"""
    )
    (run_dir / "OPENHANDS_CODER_SUMMARY.md").write_text(
        f"""# OpenHands Coder Summary

Status: `{summary['status']}`

OpenHands execution performed: `{str(execution_performed).lower()}`

Worktree changes are left unstaged for human review. No commit, push, merge, or PR creation was performed.
"""
    )
    missing = [name for name in REQUIRED_ARTIFACTS if not (run_dir / name).exists()]
    if missing:
        raise SystemExit(f"internal error: missing required artifacts: {', '.join(missing)}")
    update_latest_symlink(run_dir, project_id)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or run a controlled OpenHands coder task.")
    parser.add_argument("project_id")
    parser.add_argument("--allow-openhands", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-prompt-chars", type=int, default=12000)
    parser.add_argument("--objective-id", default=None)
    parser.add_argument("--worktree-path", default=None)
    parser.add_argument("--openhands-command", default="openhands")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--task-text", default=None)
    parser.add_argument("--task-file", default=None)
    parser.add_argument("--smoke-task", action="store_true", default=False)
    parser.add_argument("--allowed-file", action="append", default=[])
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    if prompt_override_count(args.task_text, args.task_file, args.smoke_task) > 1:
        parser.error("--task-text, --task-file, and --smoke-task are mutually exclusive")

    summary = generate(
        args.project_id,
        timeout_seconds=args.timeout_seconds,
        max_prompt_chars=args.max_prompt_chars,
        objective_id=args.objective_id,
        worktree_path=args.worktree_path,
        openhands_command=args.openhands_command,
        env_file=args.env_file,
        dry_run=args.dry_run,
        allow_openhands=args.allow_openhands,
        task_text=args.task_text,
        task_file=args.task_file,
        smoke_task=args.smoke_task,
        allowed_files=args.allowed_file,
    )
    print(f"OpenHands coder scaffold status: {summary['status']}")
    print(f"Run dir: {summary['run_dir']}")
    print(f"Dry run: {summary['dry_run']}")
    print(f"OpenHands executed: {summary['openhands_execution_performed']}")


if __name__ == "__main__":
    main()
