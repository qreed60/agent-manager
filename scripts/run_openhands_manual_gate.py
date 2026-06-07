#!/usr/bin/env python3
"""Phase 18J: Manual OpenHands gate runner.

Orchestrates a manual non-smoke OpenHands task through the existing Phase 18F/G/I
pipeline and produces a single deterministic gate summary.

This script does NOT apply, commit, push, merge, create PRs, delete worktrees, or
enable nightly OpenHands execution. It is strictly check-only for the canonical repo.

Usage:
    python3 scripts/run_openhands_manual_gate.py PROJECT_ID \\
        --task-text "Do something" \\
        --allowed-file src/ \\
        --allow-openhands

    python3 scripts/run_openhands_manual_gate.py PROJECT_ID \\
        --task-file task.md \\
        --allowed-file file.txt \\
        --timeout-seconds 600

Dry-run (default when --allow-openhands is omitted):
    python3 scripts/run_openhands_manual_gate.py PROJECT_ID \\
        --task-text "Review this" \\
        --allowed-file src/

The dry run produces a gate summary with status=warn and dry_run=true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase18j_openhands_manual_gate_runner"
DEFAULT_ENV_FILE = Path.home() / ".config" / "agent-manager" / "env.local"
FAILURE_CLASSIFICATIONS = {
    "none",
    "exited_0_no_changes",
    "misplaced_run_dir_write",
    "scope_fail",
    "apply_check_fail",
    "decision_not_accepted",
    "coder_failed",
    "canonical_repo_dirty",
    "applied_unexpectedly",
    "missing_required_artifact",
    "unknown",
}
RETRYABLE_FAILURES = {"exited_0_no_changes", "misplaced_run_dir_write", "apply_check_fail"}
NON_RETRYABLE_FAILURES = {"canonical_repo_dirty", "applied_unexpectedly", "scope_fail"}


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


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_latest_openhands_coder_run_dir(project_id: str) -> Path | None:
    """Resolve the latest OpenHands coder run directory for a project."""
    runs_base = ROOT / "runs" / project_id
    if not runs_base.exists():
        return None

    # Check symlink first
    latest_link = runs_base / "latest_openhands_coder"
    if latest_link.is_symlink() and latest_link.exists():
        return latest_link.resolve()

    # Fall back to scanning for openhands_coder_* dirs
    candidates = []
    for entry in runs_base.iterdir():
        if entry.is_dir() and entry.name.startswith("openhands_coder_"):
            candidates.append(entry)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name).resolve()


def run_subprocess(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        text=True,
        capture_output=True,
    )


def build_gate_summary_json(
    *,
    project_id: str,
    run_dir: Path | None,
    dry_run: bool,
    openhands_execution_performed: bool,
    coder_status: str | None,
    decision_packet_present: bool,
    decision_recommendation: str | None,
    apply_status_present: bool,
    apply_mode: str | None,
    apply_check_passed: bool | None,
    applied: bool,
    canonical_repo_clean: bool,
    changed_files: list[str],
    allowed_files: list[str],
    misplaced_run_dir_paths: list[str],
    failure_classification: str,
    retryable: bool,
    diagnostic_details: dict[str, Any],
    original_task_source: str,
    original_task_text: str,
    status: str,
    refusal_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "project_id": project_id,
        "created_utc": utc_now(),
        "run_dir": str(run_dir) if run_dir else "",
        "dry_run": dry_run,
        "openhands_execution_performed": openhands_execution_performed,
        "coder_status": coder_status,
        "decision_packet_present": decision_packet_present,
        "decision_recommendation": decision_recommendation,
        "apply_status_present": apply_status_present,
        "apply_mode": apply_mode,
        "apply_check_passed": apply_check_passed,
        "applied": applied,
        "canonical_repo_clean": canonical_repo_clean,
        "changed_files": changed_files,
        "allowed_files": allowed_files,
        "misplaced_run_dir_paths": misplaced_run_dir_paths,
        "failure_classification": failure_classification,
        "retryable": retryable,
        "diagnostic_details": diagnostic_details,
        "original_task_source": original_task_source,
        "original_task_text": original_task_text,
        "original_task_sha256": sha256_text(original_task_text),
        "status": status,
        "refusal_reason": refusal_reason or "",
        "no_apply_commit_push_merge_pr_or_cleanup_performed": True,
    }


def build_gate_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# OpenHands Manual Gate Summary",
        "",
        f"**Status:** `{summary['status']}`",
        f"**Failure classification:** `{summary.get('failure_classification', 'unknown')}`",
        f"**Retryable:** `{str(summary.get('retryable', False)).lower()}`",
        f"**Generated by:** {summary['generated_by']}",
        f"**Project:** `{summary['project_id']}`",
        f"**Run dir:** `{summary['run_dir']}`",
        "",
        "## Execution Details",
        "",
        f"- OpenHands execution performed: `{str(summary['openhands_execution_performed']).lower()}`",
        f"- Dry run: `{str(summary['dry_run']).lower()}`",
        f"- Coder status: `{summary.get('coder_status', 'N/A')}`",
        "",
    ]

    lines.extend([
        "## Decision Packet",
        "",
        f"- Present: `{str(summary.get('decision_packet_present', False)).lower()}`",
        f"- Recommendation: `{summary.get('decision_recommendation', 'N/A')}`",
        "",
        "## Apply Status (check-only)",
        "",
        f"- Present: `{str(summary.get('apply_status_present', False)).lower()}`",
        f"- Mode: `{summary.get('apply_mode', 'N/A')}`",
        f"- Check passed: `{str(summary.get('apply_check_passed', False)).lower()}`",
        f"- Applied: `{str(summary['applied']).lower()}`",
        "",
    ])

    lines.extend([
        "## Safety",
        "",
        f"- Canonical repo clean: `{str(summary['canonical_repo_clean']).lower()}`",
        f"- Changed files: {json.dumps(summary.get('changed_files', []))}",
        f"- Allowed files: {json.dumps(summary.get('allowed_files', []))}",
        f"- Misplaced run-dir paths: {json.dumps(summary.get('misplaced_run_dir_paths', []))}",
        f"- No apply/commit/push/merge/PR/cleanup performed: `true`",
    ])

    if summary.get("refusal_reason"):
        lines.extend(["\n## Refusal", "", f"- Reason: `{summary['refusal_reason']}`"])

    lines.append("")
    return "\n".join(lines)


def read_original_task(*, task_text: str | None, task_file: str | None) -> tuple[str, str]:
    if task_text is not None:
        return "task_text", task_text
    if task_file is not None:
        return "task_file", Path(task_file).expanduser().read_text()
    raise ValueError("exactly one task source is required")


def build_hardened_task_prompt(*, project_id: str, original_task_text: str, allowed_files: list[str]) -> str:
    allowed_lines = "\n".join(f"- {path}" for path in allowed_files)
    return f"""# OpenHands Manual Gate Instructions

Use the terminal for file creation/modification.
The current shell working directory is the isolated project worktree.
Create or modify files relative to the current working directory only.
Do not write beside `OPENHANDS_TASK_PROMPT.md`.
Do not write into the run directory.
Do not use absolute paths under `runs/{project_id}/openhands_coder_*`.
Do not create or modify files outside the allowed file list.
If a parent directory is needed for an allowed file, creating that directory is permitted.
Do not inspect the repository broadly.
Do not run tests unless explicitly requested.
Do not commit.
Do not push.
Finish immediately after completing the requested file change.

## Allowed Files

{allowed_lines}

## Original User Task

{original_task_text}

Before finishing, verify that each requested allowed file exists or was modified in the current working directory.
"""


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def compute_gate_status_and_refusal(
    *,
    dry_run: bool,
    openhands_execution_performed: bool,
    coder_status: str | None,
    decision_packet_present: bool,
    decision_recommendation: str | None,
    apply_status_present: bool,
    apply_status: str | None,
    apply_mode: str | None,
    apply_check_passed: bool | None,
    applied: bool,
    canonical_repo_clean: bool,
) -> tuple[str, str]:
    """Compute the gate summary status and a concise refusal reason."""
    refusals: list[str] = []

    if applied:
        refusals.append("apply status indicates a patch was applied")
    if not canonical_repo_clean:
        refusals.append("canonical repo is dirty")

    if dry_run and not openhands_execution_performed:
        if refusals:
            return "fail", "; ".join(refusals)
        return "warn", "dry run only; OpenHands was not explicitly enabled"

    if not openhands_execution_performed:
        refusals.append("OpenHands execution was not performed")

    if coder_status != "pass":
        refusals.append(f"coder summary status is not pass: {coder_status!r}")
    if not decision_packet_present:
        refusals.append("decision packet is missing")
    elif decision_recommendation != "accept_for_manual_review":
        refusals.append(f"decision recommendation is not accept_for_manual_review: {decision_recommendation!r}")
    if not apply_status_present:
        refusals.append("apply status is missing")
    else:
        if apply_status != "pass":
            refusals.append(f"apply status is not pass: {apply_status!r}")
        if apply_mode != "check_only":
            refusals.append(f"apply mode is not check_only: {apply_mode!r}")
        if apply_check_passed is not True:
            refusals.append(f"apply check did not pass: {apply_check_passed!r}")

    if refusals:
        return "fail", "; ".join(refusals)
    return "pass", ""


def safe_load_json_dict(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_scope_status(run_dir: Path | None) -> str | None:
    if run_dir is None:
        return None
    data = safe_load_json_dict(run_dir / "OPENHANDS_SCOPE_STATUS.json")
    value = data.get("scope_status")
    return value if isinstance(value, str) else None


def get_coder_returncode(coder_summary: dict[str, Any]) -> int | None:
    value = coder_summary.get("returncode")
    return value if isinstance(value, int) else None


def required_live_artifacts_missing(run_dir: Path | None) -> list[str]:
    if run_dir is None:
        return ["run_dir"]
    required = [
        "OPENHANDS_CODER_SUMMARY.json",
        "OPENHANDS_CHANGED_FILES.json",
        "OPENHANDS_SCOPE_STATUS.json",
        "OPENHANDS_DECISION_PACKET.json",
        "OPENHANDS_APPLY_STATUS.json",
    ]
    return [name for name in required if not (run_dir / name).exists()]


def detect_misplaced_run_dir_paths(run_dir: Path | None, allowed_files: list[str], changed_files: list[str]) -> list[str]:
    if run_dir is None or not run_dir.exists():
        return []
    changed_set = set(changed_files)
    found: list[str] = []
    seen: set[str] = set()
    for allowed in allowed_files:
        exact = run_dir / allowed
        if exact.exists() and allowed not in changed_set:
            rel = exact.relative_to(run_dir).as_posix()
            if rel not in seen:
                seen.add(rel)
                found.append(rel)
        basename = Path(allowed).name
        if not basename:
            continue
        for path in run_dir.rglob(basename):
            if not path.is_file():
                continue
            rel = path.relative_to(run_dir).as_posix()
            if rel in changed_set or rel in seen:
                continue
            seen.add(rel)
            found.append(rel)
    return found


def classify_failure(
    *,
    status: str,
    openhands_execution_performed: bool,
    coder_status: str | None,
    coder_returncode: int | None,
    changed_files: list[str],
    misplaced_run_dir_paths: list[str],
    scope_status: str | None,
    decision_packet_present: bool,
    decision_recommendation: str | None,
    apply_status_present: bool,
    apply_status: str | None,
    apply_check_passed: bool | None,
    applied: bool,
    canonical_repo_clean: bool,
    missing_required_artifacts: list[str],
) -> tuple[str, bool]:
    if status == "pass":
        return "none", False
    if applied:
        return "applied_unexpectedly", False
    if not canonical_repo_clean:
        return "canonical_repo_dirty", False
    if openhands_execution_performed and misplaced_run_dir_paths:
        return "misplaced_run_dir_write", True
    if openhands_execution_performed and coder_returncode == 0 and not changed_files:
        return "exited_0_no_changes", True
    if scope_status == "fail":
        return "scope_fail", False
    if apply_status_present and (apply_status == "fail" or apply_check_passed is False):
        return "apply_check_fail", True
    if decision_packet_present and decision_recommendation != "accept_for_manual_review":
        return "decision_not_accepted", False
    if coder_status == "fail":
        return "coder_failed", False
    if openhands_execution_performed and missing_required_artifacts:
        return "missing_required_artifact", False
    if status == "warn":
        return "none", False
    return "unknown", False


def run_coder_task(
    project_id: str,
    *,
    task_text: str | None = None,
    task_file: str | None = None,
    allowed_files: list[str],
    allow_openhands: bool = False,
    timeout_seconds: int = 300,
    max_prompt_chars: int = 3000,
    env_file: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Run scripts/run_openhands_coder_task.py and return (run_dir, summary)."""
    coder_script = ROOT / "scripts" / "run_openhands_coder_task.py"

    cmd = [sys.executable, str(coder_script), project_id]

    if task_text is not None:
        cmd.extend(["--task-text", task_text])
    if task_file is not None:
        cmd.extend(["--task-file", str(task_file)])
    for f in allowed_files:
        cmd.extend(["--allowed-file", f])
    if allow_openhands:
        cmd.append("--allow-openhands")
    cmd.extend(["--timeout-seconds", str(timeout_seconds)])
    cmd.extend(["--max-prompt-chars", str(max_prompt_chars)])
    if env_file is not None:
        cmd.extend(["--env-file", str(env_file)])

    run_subprocess(cmd)

    # Parse the summary from the coder task output or artifacts
    run_dir = resolve_latest_openhands_coder_run_dir(project_id)

    if not run_dir or not (run_dir / "OPENHANDS_CODER_SUMMARY.json").exists():
        return run_dir, {
            "status": "fail",
            "dry_run": True,
            "openhands_execution_performed": False,
        }

    coder_summary = load_json(run_dir / "OPENHANDS_CODER_SUMMARY.json")
    return run_dir, coder_summary


def run_decision_packet(
    project_id: str,
    run_dir: Path,
) -> tuple[bool, str | None]:
    """Run scripts/prepare_openhands_decision_packet.py and return (present, recommendation)."""
    packet_script = ROOT / "scripts" / "prepare_openhands_decision_packet.py"

    cmd = [sys.executable, str(packet_script), project_id, "--run-dir", str(run_dir)]
    result = run_subprocess(cmd)

    if result.returncode != 0:
        return False, None

    packet_path = run_dir / "OPENHANDS_DECISION_PACKET.json"
    if not packet_path.exists():
        return False, None

    packet = load_json(packet_path)
    recommendation = packet.get("recommendation")
    return True, recommendation


def run_apply_check(
    project_id: str,
    run_dir: Path,
) -> tuple[bool, str | None, str | None, bool | None, bool]:
    """Run scripts/apply_openhands_decision_packet.py in check-only mode.

    Returns (status_present, apply_status, apply_mode, apply_check_passed, applied).
    """
    apply_script = ROOT / "scripts" / "apply_openhands_decision_packet.py"

    cmd = [sys.executable, str(apply_script), project_id, "--run-dir", str(run_dir), "--check-only"]
    run_subprocess(cmd)

    apply_status_path = run_dir / "OPENHANDS_APPLY_STATUS.json"
    if not apply_status_path.exists():
        return False, None, None, None, False

    apply_data = load_json(apply_status_path)
    status = apply_data.get("status")
    mode = apply_data.get("mode", "")
    check_passed = apply_data.get("git_apply_check_passed")
    applied_flag = bool(apply_data.get("applied", False))

    return True, status, mode, check_passed, applied_flag


def get_canonical_repo_clean_status(project_id: str, run_dir: Path | None) -> bool:
    """Check if the canonical repo is clean (no uncommitted changes)."""
    project = load_project(project_id)
    repo_path = Path(str(project["repo_path"])).expanduser().resolve()

    if not repo_path.exists():
        return True  # No repo to check

    result = run_subprocess(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
    )
    return result.returncode == 0 and not result.stdout.strip()


def get_changed_files(run_dir: Path | None) -> list[str]:
    """Get the list of changed files from the coder run."""
    if run_dir is None:
        return []

    changed_path = run_dir / "OPENHANDS_CHANGED_FILES.json"
    if not changed_path.exists():
        return []

    data = load_json(changed_path)
    all_files = data.get("all_changed_files", [])
    if isinstance(all_files, list):
        return all_files
    return []


def validate_inputs(
    task_text: str | None,
    task_file: str | None,
    allowed_files: list[str],
) -> str | None:
    """Validate CLI inputs. Returns refusal_reason or None."""
    # Exactly one of --task-text or --task-file required
    sources = sum(1 for v in [task_text, task_file] if v is not None)
    if sources != 1:
        return "exactly one of --task-text or --task-file is required"

    # At least one --allowed-file required
    if not allowed_files:
        return "at least one --allowed-file is required"

    return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 18J: Manual OpenHands gate runner. Chains Phase 18F/G/I for a single deterministic gate summary."
    )
    parser.add_argument("project_id", help="Project ID from configs/projects.json")
    parser.add_argument("--task-text", default=None, help="Override task text (mutually exclusive with --task-file)")
    parser.add_argument("--task-file", default=None, help="Path to file containing task text (mutually exclusive with --task-text)")
    parser.add_argument("--allowed-file", action="append", default=[], help="Allowed file scope path (repeatable, at least one required)")
    parser.add_argument("--allow-openhands", action="store_true", help="Enable live OpenHands execution")
    parser.add_argument("--timeout-seconds", type=int, default=300, help="Timeout in seconds for coder task (default: 300)")
    parser.add_argument("--max-prompt-chars", type=int, default=3000, help="Max prompt characters (default: 3000)")
    parser.add_argument("--env-file", default=None, help="Path to env file for LLM credentials")
    parser.add_argument("--dry-run-ok", action="store_true", help="Allow dry-run summary without erroring out")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # Validate inputs
    refusal_reason = validate_inputs(args.task_text, args.task_file, args.allowed_file)
    if refusal_reason is not None:
        print(f"ERROR: {refusal_reason}", file=sys.stderr)
        sys.exit(1)

    project_id = args.project_id
    allowed_files = unique_preserve_order(list(args.allowed_file))
    original_task_source, original_task_text = read_original_task(task_text=args.task_text, task_file=args.task_file)
    wrapped_task_text = build_hardened_task_prompt(
        project_id=project_id,
        original_task_text=original_task_text,
        allowed_files=allowed_files,
    )

    # Step 1: Run the coder task (Phase 18F)
    allow_openhands = args.allow_openhands
    run_dir, coder_summary = run_coder_task(
        project_id,
        task_text=wrapped_task_text,
        task_file=None,
        allowed_files=allowed_files,
        allow_openhands=allow_openhands,
        timeout_seconds=args.timeout_seconds,
        max_prompt_chars=args.max_prompt_chars,
        env_file=args.env_file,
    )

    coder_status = coder_summary.get("status")
    openhands_execution_performed = bool(coder_summary.get("openhands_execution_performed"))
    dry_run = bool(coder_summary.get("dry_run", True))
    coder_returncode = get_coder_returncode(coder_summary)

    # If OpenHands did not actually execute, the underlying runner produced a
    # dry run. Allow it to complete and do not run decision/apply gates.
    if not openhands_execution_performed:
        canonical_clean = get_canonical_repo_clean_status(project_id, run_dir)
        changed_files = get_changed_files(run_dir)
        misplaced_paths = detect_misplaced_run_dir_paths(run_dir, allowed_files, changed_files)
        if run_dir is None:
            run_dir = ROOT / "runs" / project_id / f"manual_gate_{utc_now()}"
        gate_status, gate_refusal = compute_gate_status_and_refusal(
            dry_run=True,
            openhands_execution_performed=False,
            coder_status=coder_status,
            decision_packet_present=False,
            decision_recommendation=None,
            apply_status_present=False,
            apply_status=None,
            apply_mode=None,
            apply_check_passed=None,
            applied=False,
            canonical_repo_clean=canonical_clean,
        )
        failure_classification, retryable = classify_failure(
            status=gate_status,
            openhands_execution_performed=False,
            coder_status=coder_status,
            coder_returncode=coder_returncode,
            changed_files=changed_files,
            misplaced_run_dir_paths=misplaced_paths,
            scope_status=get_scope_status(run_dir),
            decision_packet_present=False,
            decision_recommendation=None,
            apply_status_present=False,
            apply_status=None,
            apply_check_passed=None,
            applied=False,
            canonical_repo_clean=canonical_clean,
            missing_required_artifacts=[],
        )
        diagnostic_details = {
            "coder_returncode": coder_returncode,
            "scope_status": get_scope_status(run_dir),
            "missing_required_artifacts": [],
            "prompt_wrapped": True,
        }

        gate_summary = build_gate_summary_json(
            project_id=project_id,
            run_dir=run_dir,
            dry_run=True,
            openhands_execution_performed=False,
            coder_status=coder_status,
            decision_packet_present=False,
            decision_recommendation=None,
            apply_status_present=False,
            apply_mode=None,
            apply_check_passed=None,
            applied=False,
            canonical_repo_clean=canonical_clean,
            changed_files=changed_files,
            allowed_files=allowed_files,
            misplaced_run_dir_paths=misplaced_paths,
            failure_classification=failure_classification,
            retryable=retryable,
            diagnostic_details=diagnostic_details,
            original_task_source=original_task_source,
            original_task_text=original_task_text,
            status=gate_status,
            refusal_reason=gate_refusal,
        )

        write_json(run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json", gate_summary)
        (run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.md").write_text(build_gate_summary_md(gate_summary))

        print(f"Gate status: {gate_summary['status']}")
        print(f"Dry run: true (OpenHands execution was not performed)")
        print(f"Run dir: {run_dir}")
        if gate_summary["status"] == "fail":
            sys.exit(1)
        return

    # Step 2: Live OpenHands execution path
    # Resolve the latest_openhands_coder run dir after coder task completes
    resolved_run_dir = resolve_latest_openhands_coder_run_dir(project_id) or run_dir
    if not resolved_run_dir:
        print("ERROR: no OpenHands run directory found after coder task", file=sys.stderr)
        sys.exit(1)

    # Step 3: Generate decision packet (Phase 18G)
    dp_present, dp_recommendation = run_decision_packet(project_id, resolved_run_dir)

    # Step 4: Run guarded check-only apply validation (Phase 18I)
    ap_present, ap_status, ap_mode, ap_check_passed, applied_flag = run_apply_check(project_id, resolved_run_dir)

    canonical_clean = get_canonical_repo_clean_status(project_id, resolved_run_dir)
    changed_files = get_changed_files(resolved_run_dir)
    misplaced_paths = detect_misplaced_run_dir_paths(resolved_run_dir, allowed_files, changed_files)
    scope_status = get_scope_status(resolved_run_dir)
    missing_artifacts = required_live_artifacts_missing(resolved_run_dir)

    # Compute gate status
    gate_status, gate_refusal = compute_gate_status_and_refusal(
        dry_run=dry_run,
        openhands_execution_performed=openhands_execution_performed,
        coder_status=coder_status,
        decision_packet_present=dp_present,
        decision_recommendation=dp_recommendation,
        apply_status_present=ap_present,
        apply_status=ap_status,
        apply_mode=ap_mode,
        apply_check_passed=ap_check_passed,
        applied=applied_flag,
        canonical_repo_clean=canonical_clean,
    )
    failure_classification, retryable = classify_failure(
        status=gate_status,
        openhands_execution_performed=openhands_execution_performed,
        coder_status=coder_status,
        coder_returncode=coder_returncode,
        changed_files=changed_files,
        misplaced_run_dir_paths=misplaced_paths,
        scope_status=scope_status,
        decision_packet_present=dp_present,
        decision_recommendation=dp_recommendation,
        apply_status_present=ap_present,
        apply_status=ap_status,
        apply_check_passed=ap_check_passed,
        applied=applied_flag,
        canonical_repo_clean=canonical_clean,
        missing_required_artifacts=missing_artifacts,
    )
    diagnostic_details = {
        "coder_returncode": coder_returncode,
        "scope_status": scope_status,
        "apply_status": ap_status,
        "missing_required_artifacts": missing_artifacts,
        "prompt_wrapped": True,
    }

    # Build and write summary artifacts
    gate_summary = build_gate_summary_json(
        project_id=project_id,
        run_dir=resolved_run_dir,
        dry_run=dry_run,
        openhands_execution_performed=openhands_execution_performed,
        coder_status=coder_status,
        decision_packet_present=dp_present,
        decision_recommendation=dp_recommendation,
        apply_status_present=ap_present,
        apply_mode=ap_mode,
        apply_check_passed=ap_check_passed,
        applied=applied_flag,
        canonical_repo_clean=canonical_clean,
        changed_files=changed_files,
        allowed_files=allowed_files,
        misplaced_run_dir_paths=misplaced_paths,
        failure_classification=failure_classification,
        retryable=retryable,
        diagnostic_details=diagnostic_details,
        original_task_source=original_task_source,
        original_task_text=original_task_text,
        status=gate_status,
        refusal_reason=gate_refusal,
    )

    write_json(resolved_run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json", gate_summary)
    (resolved_run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.md").write_text(build_gate_summary_md(gate_summary))

    print(f"Gate status: {gate_status}")
    print(f"Run dir: {resolved_run_dir}")
    print(f"Dry run: {str(dry_run).lower()}")
    print(f"OpenHands executed: {str(openhands_execution_performed).lower()}")
    print(f"Failure classification: {failure_classification}")
    print(f"Retryable: {str(retryable).lower()}")
    if dp_present:
        print(f"Decision packet recommendation: {dp_recommendation}")
    if ap_present:
        print(f"Apply mode: {ap_mode}, check passed: {str(ap_check_passed).lower() if ap_check_passed is not None else 'N/A'}")
    print(f"No apply/commit/push/merge/PR/cleanup performed: true")

    if gate_status == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
