#!/usr/bin/env python3
"""Prepare a human decision packet for a controlled OpenHands coder run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase18g_openhands_decision_packet"
READ_ARTIFACTS = [
    "OPENHANDS_EXIT_STATUS.json",
    "OPENHANDS_WORKTREE_INFO.json",
    "OPENHANDS_CHANGED_FILES.json",
    "OPENHANDS_SCOPE_STATUS.json",
    "OPENHANDS_SMOKE_STATUS.json",
    "OPENHANDS_CODER_SUMMARY.json",
    "OPENHANDS_TASK_PROMPT.md",
    "OPENHANDS_DIFF_SUMMARY.txt",
    "OPENHANDS_STDOUT.txt",
    "OPENHANDS_STDERR.txt",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_text(path: Path) -> str:
    try:
        return path.read_text()
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return ""


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def resolve_run_dir(project_id: str, run_dir: str | None) -> Path:
    if run_dir:
        return Path(run_dir).expanduser().resolve()
    return (ROOT / "runs" / project_id / "latest_openhands_coder").resolve()


def is_text_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def untracked_file_patch(worktree: Path, relative_path: str) -> str:
    path = worktree / relative_path
    if not path.exists() or not path.is_file() or not is_text_file(path):
        return ""
    result = run_git(["diff", "--no-index", "--", "/dev/null", relative_path], worktree)
    return result.stdout if result.stdout else ""


def generate_patch(worktree: Path, changed_files: dict[str, Any]) -> str:
    patch_parts: list[str] = []
    if worktree.exists():
        diff = run_git(["diff", "--binary", "HEAD"], worktree)
        if diff.returncode == 0 and diff.stdout:
            patch_parts.append(diff.stdout)
    untracked = changed_files.get("untracked_files")
    if isinstance(untracked, list):
        for item in sorted(str(path) for path in untracked):
            patch = untracked_file_patch(worktree, item)
            if patch:
                if patch_parts and not patch_parts[-1].endswith("\n"):
                    patch_parts.append("\n")
                patch_parts.append(patch)
                if not patch.endswith("\n"):
                    patch_parts.append("\n")
    return "".join(patch_parts)


def missing_artifacts(run_dir: Path) -> list[str]:
    return sorted(name for name in READ_ARTIFACTS if name != "OPENHANDS_SMOKE_STATUS.json" and not (run_dir / name).exists())


def choose_recommendation(
    *,
    exit_status: dict[str, Any],
    scope_status: dict[str, Any],
    smoke_status: dict[str, Any],
    summary: dict[str, Any],
    changed_files: dict[str, Any],
    canonical_repo_clean: bool,
    missing: list[str],
) -> str:
    exit_failed = exit_status.get("status") == "fail" or exit_status.get("returncode") not in (None, 0)
    timed_out = exit_status.get("timed_out") is True
    scope_value = scope_status.get("scope_status")
    task_type = summary.get("task_type")
    worktree_changed = changed_files.get("worktree_changed") is True
    patch_nonempty = worktree_changed

    if missing:
        return "hold_for_debug"
    if exit_failed or timed_out:
        return "hold_for_debug"
    if not canonical_repo_clean:
        return "human_review_required"
    if scope_value == "fail":
        return "discard_worktree"
    if not patch_nonempty:
        return "rerun_openhands" if task_type in {"manual_task_text", "manual_task_file", "generated"} else "discard_worktree"
    if task_type == "smoke" and smoke_status.get("status") == "pass":
        return "discard_worktree"
    if task_type in {"manual_task_text", "manual_task_file"} and scope_value == "pass":
        return "accept_for_manual_review"
    return "human_review_required"


def canonical_repo_clean_from_artifacts(summary: dict[str, Any], scope_status: dict[str, Any], smoke_status: dict[str, Any]) -> bool:
    if isinstance(summary.get("canonical_repo_clean"), bool):
        return bool(summary["canonical_repo_clean"])
    if isinstance(smoke_status.get("canonical_repo_clean"), bool):
        return bool(smoke_status["canonical_repo_clean"])
    details = str(scope_status.get("details", "")).lower()
    if "canonical repo is dirty" in details:
        return False
    return True


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def build_review_commands(packet: dict[str, Any]) -> str:
    run_dir = str(packet.get("source_run_dir", ""))
    worktree = str(packet.get("worktree_path", ""))
    canonical = str(packet.get("canonical_repo", ""))
    patch = str(packet.get("patch_file", ""))
    changed = packet.get("changed_files")
    changed_files = changed if isinstance(changed, list) else []
    scratch_files = [path for path in changed_files if isinstance(path, str) and path.startswith(".agent_manager_scratch/")]
    lines = [
        "# OpenHands Review Commands",
        "",
        "Run these manually to inspect the OpenHands result.",
        "",
        "```bash",
        shell_join(["ls", "-la", run_dir]),
        shell_join(["pwd"]),
        shell_join(["git", "-C", worktree, "status", "--short", "--untracked-files=all"]),
        shell_join(["git", "-C", worktree, "diff", "--binary", "HEAD"]),
        shell_join(["python3", "-m", "json.tool", str(Path(run_dir) / "OPENHANDS_DECISION_PACKET.json")]),
        shell_join(["sed", "-n", "1,240p", patch]),
        shell_join(["git", "-C", canonical, "apply", "--check", patch]),
        "```",
    ]
    if scratch_files:
        lines.extend(["", "Scratch file inspection:", "", "```bash"])
        for item in scratch_files:
            lines.append(shell_join(["cat", str(Path(worktree) / item)]))
        lines.append("```")
    lines.extend(
        [
            "",
            "## Manual Apply Sequence",
            "",
            "Manual only. Do not run unless you intend to apply this patch.",
            "",
            "```bash",
            shell_join(["git", "-C", canonical, "apply", "--check", patch]),
            shell_join(["git", "-C", canonical, "apply", patch]),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def build_cleanup_plan(packet: dict[str, Any]) -> str:
    worktree = str(packet.get("worktree_path", ""))
    branch = str(packet.get("worktree_branch", ""))
    canonical = str(packet.get("canonical_repo", ""))
    lines = [
        "# OpenHands Cleanup Plan",
        "",
        "Manual cleanup only. No cleanup command was executed by this phase.",
        "",
        "Warning: removing the worktree discards uncommitted worktree changes.",
        "",
        "Inspect before cleanup:",
        "",
        "```bash",
        shell_join(["git", "-C", worktree, "status", "--short", "--untracked-files=all"]),
        "```",
        "",
        "Manual cleanup commands:",
        "",
        "```bash",
        shell_join(["git", "-C", canonical, "worktree", "remove", worktree]),
        shell_join(["git", "-C", canonical, "branch", "-D", branch]),
        "```",
    ]
    return "\n".join(lines) + "\n"


def build_markdown(packet: dict[str, Any]) -> str:
    return f"""# OpenHands Decision Packet

Project: {packet.get("project_id")}
Recommendation: {packet.get("recommendation")}

## Run

- Source run dir: `{packet.get("source_run_dir")}`
- Worktree: `{packet.get("worktree_path")}`
- Branch: `{packet.get("worktree_branch")}`
- Task type: `{packet.get("task_type")}`
- Prompt source: `{packet.get("prompt_source")}`

## Status

- Exit status: `{packet.get("exit_status", {}).get("status")}`
- Scope status: `{packet.get("scope_status", {}).get("scope_status")}`
- Smoke status: `{packet.get("smoke_status", {}).get("status") if packet.get("smoke_status") else "not_present"}`
- Canonical repo clean: `{packet.get("canonical_repo_clean")}`
- Patch nonempty: `{packet.get("patch_nonempty")}`

## Changed Files

```json
{json.dumps(packet.get("changed_files", []), indent=2)}
```

## Patch

- File: `{packet.get("patch_file")}`
- SHA256: `{packet.get("patch_sha256")}`

No patch was applied, no commit was created, no push was made, no merge was
performed, and no PR was created.
"""


def prepare(project_id: str, *, run_dir: str | None = None, output_dir: str | None = None, created_utc: str | None = None) -> dict[str, Any]:
    created = created_utc or utc_now()
    source_run_dir = resolve_run_dir(project_id, run_dir)
    out_dir = Path(output_dir).expanduser().resolve() if output_dir else source_run_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    exit_status = load_json(source_run_dir / "OPENHANDS_EXIT_STATUS.json")
    worktree_info = load_json(source_run_dir / "OPENHANDS_WORKTREE_INFO.json")
    changed_files = load_json(source_run_dir / "OPENHANDS_CHANGED_FILES.json")
    scope_status = load_json(source_run_dir / "OPENHANDS_SCOPE_STATUS.json")
    smoke_status = load_json(source_run_dir / "OPENHANDS_SMOKE_STATUS.json")
    summary = load_json(source_run_dir / "OPENHANDS_CODER_SUMMARY.json")

    worktree_raw = worktree_info.get("worktree_path") or summary.get("worktree_path")
    worktree_path = Path(str(worktree_raw)) if isinstance(worktree_raw, str) and worktree_raw else None
    patch_text = generate_patch(worktree_path, changed_files) if worktree_path is not None else ""
    patch_path = out_dir / "OPENHANDS_PATCH.diff"
    patch_path.write_text(patch_text)
    patch_hash = sha256_file(patch_path)
    missing = missing_artifacts(source_run_dir)

    canonical_repo_clean = canonical_repo_clean_from_artifacts(summary, scope_status, smoke_status)
    recommendation = choose_recommendation(
        exit_status=exit_status,
        scope_status=scope_status,
        smoke_status=smoke_status,
        summary=summary,
        changed_files=changed_files,
        canonical_repo_clean=canonical_repo_clean,
        missing=missing,
    )

    packet: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "project_id": project_id,
        "created_utc": created,
        "source_run_dir": str(source_run_dir),
        "canonical_repo": str(worktree_info.get("canonical_repo") or summary.get("canonical_repo") or ""),
        "worktree_path": str(worktree_info.get("worktree_path") or summary.get("worktree_path") or ""),
        "worktree_branch": str(worktree_info.get("worktree_branch") or summary.get("worktree_branch") or ""),
        "base_branch": str(worktree_info.get("base_branch") or ""),
        "worktree_head": str(worktree_info.get("worktree_head") or ""),
        "prompt_source": summary.get("prompt_source"),
        "task_type": summary.get("task_type"),
        "task_override_used": summary.get("task_override_used"),
        "manual_allowed_files": summary.get("manual_allowed_files", []),
        "exit_status": exit_status,
        "scope_status": scope_status,
        "changed_files": changed_files.get("all_changed_files", []),
        "untracked_files": changed_files.get("untracked_files", []),
        "tracked_modified_files": changed_files.get("tracked_modified_files", []),
        "staged_files": changed_files.get("staged_files", []),
        "worktree_changed": changed_files.get("worktree_changed", False),
        "canonical_repo_clean": canonical_repo_clean,
        "patch_file": str(patch_path),
        "patch_sha256": patch_hash,
        "patch_nonempty": bool(patch_text.strip()),
        "recommendation": recommendation,
        "missing_artifacts": missing,
        "artifacts_read": {name: (source_run_dir / name).exists() for name in READ_ARTIFACTS},
        "no_auto_apply_commit_push_merge_pr_or_cleanup": True,
    }
    if smoke_status:
        packet["smoke_status"] = smoke_status

    write_json(out_dir / "OPENHANDS_DECISION_PACKET.json", packet)
    (out_dir / "OPENHANDS_DECISION_PACKET.md").write_text(build_markdown(packet))
    (out_dir / "OPENHANDS_REVIEW_COMMANDS.md").write_text(build_review_commands(packet))
    (out_dir / "OPENHANDS_CLEANUP_PLAN.md").write_text(build_cleanup_plan(packet))
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a human decision packet for an OpenHands run.")
    parser.add_argument("project_id")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    packet = prepare(args.project_id, run_dir=args.run_dir, output_dir=args.output_dir)
    print(f"OpenHands decision packet recommendation: {packet['recommendation']}")
    print(f"Packet: {Path(packet['source_run_dir']) / 'OPENHANDS_DECISION_PACKET.json' if args.output_dir is None else Path(args.output_dir).expanduser().resolve() / 'OPENHANDS_DECISION_PACKET.json'}")
    print(f"Patch nonempty: {packet['patch_nonempty']}")


if __name__ == "__main__":
    main()
