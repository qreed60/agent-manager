#!/usr/bin/env python3
"""Guarded manual OpenHands decision-packet apply gate.

Default: check-only mode, no canonical repo writes.
Apply requires explicit flags AND an environment variable.
This does not enable OpenHands in nightly and does not commit, push, merge, or create PRs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY_APPLY = "phase18i_guarded_openhands_patch_apply"

# Required decision packet fields and their expected values for acceptance.
REQUIRED_PACKET_FIELDS: dict[str, Any] = {
    "generated_by": "phase18g_openhands_decision_packet",
    "recommendation": "accept_for_manual_review",
    "canonical_repo_clean": True,
    "patch_nonempty": True,
}

# scope_status and exit_status sub-field checks.
REQUIRED_SCOPE_STATUS: dict[str, Any] = {
    "scope_status": "pass",
}

REQUIRED_EXIT_STATUS: dict[str, Any] = {
    "status": "pass",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def is_repo_clean(cwd: Path) -> bool:
    result = run_git(["status", "--short"], cwd)
    return result.returncode == 0 and not result.stdout.strip()


def load_json_file(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, "missing file"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except OSError as exc:
        return None, f"could not read file: {exc}"


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def build_markdown_report(artifact: dict[str, Any]) -> str:
    lines = [
        "# OpenHands Apply Status Report",
        "",
        f"Project: {artifact.get('project_id', 'unknown')}",
        f"Mode: {artifact.get('mode', 'unknown')}",
        f"Recommendation: {artifact.get('packet_recommendation', 'unknown')}",
        "",
        "## Patch",
        "",
        f"- File: `{artifact.get('patch_file', '')}`",
        f"- SHA256: `{artifact.get('patch_sha256', '')}`",
        f"- Verified: {artifact.get('patch_sha256_verified', False)}",
        "",
    ]

    check_result = artifact.get('git_apply_check_passed')
    if check_result is None:
        check_str = "not_run"
    elif check_result:
        check_str = "PASS"
    else:
        check_str = "FAIL"
    lines.extend([f"- Git apply --check: {check_str}", ""])

    applied = artifact.get('applied', False)
    if applied:
        lines.append("## Apply Result")
        lines.append("")
        lines.append("- **Patch was applied to canonical repo** (no commit made)")
        rc = artifact.get('apply_returncode')
        if rc is not None:
            lines.append(f"- Return code: {rc}")
    else:
        lines.append("## Apply Result")
        lines.append("")
        lines.append("- Patch was NOT applied (check-only mode or gates not met)")

    lines.extend([
        "",
        "## Canonical Repo Status",
        "",
        f"- Before: {'clean' if artifact.get('canonical_repo_clean_before') else 'dirty'}",
    ])
    after = artifact.get('canonical_repo_status_after', {})
    if isinstance(after, dict):
        lines.append(f"- After (working tree): {len(after.get('working_tree', []))} changed file(s)")
        lines.append(f"- After (untracked): {len(after.get('untracked', []))} untracked file(s)")
    elif after:
        lines.append(f"- After: {after}")
    else:
        lines.append("- After: not recorded")

    refusal = artifact.get('refusal_reason')
    if refusal:
        lines.extend([
            "",
            "## Refusal",
            "",
            f"- Reason: {refusal}",
        ])

    lines.extend([
        "",
        "- No commit, push, merge, or PR was performed.",
        "",
    ])
    return "\n".join(lines)


def build_review_commands(artifact: dict[str, Any]) -> str:
    project_id = artifact.get("project_id", "unknown")
    run_dir = artifact.get("source_run_dir", "")
    packet_path = artifact.get("packet_path", "")
    patch_file = artifact.get("patch_file", "")
    canonical = artifact.get("canonical_repo", "")

    lines = [
        "# OpenHands Apply Review Commands",
        "",
        "Run these manually to inspect and optionally apply the OpenHands patch.",
        "",
        "## 1. Inspect Decision Packet",
        "",
        "```bash",
        f"python3 -m json.tool {packet_path}",
        "```",
        "",
        "## 2. Inspect Patch",
        "",
        "```bash",
        f"sed -n '1,240p' {patch_file}",
        "```",
        "",
        "## 3. Check Patch Against Canonical Repo",
        "",
        "```bash",
        f"git -C {canonical} apply --check {patch_file}",
        "```",
        "",
        "## 4. Explicitly-Gated Apply (requires all gates)",
        "",
        "Apply requires **all** of the following:",
        "",
        "- `--apply` flag present",
        "- `--allow-canonical-write` flag present",
        "- `--confirm-project <PROJECT_ID>` matching the project exactly",
        "- Environment variable `AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1` set",
        "",
        "```bash",
        f"AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1 \\",
        f"  python3 {ROOT / 'scripts' / 'apply_openhands_decision_packet.py'} \\",
        f"  {project_id} \\",
        f"  --run-dir {run_dir} \\",
        f"  --packet {packet_path} \\",
        f"  --apply \\",
        f"  --allow-canonical-write \\",
        f"  --confirm-project {project_id}",
        "```",
        "",
        "## Reminder",
        "",
        "- This script does **not** commit, push, merge, or create PRs.",
        "- The patch is applied via `git apply` only (no commit).",
        "- Review the diff carefully before running the apply command above.",
        "",
    ]
    return "\n".join(lines) + "\n"


def check_packet_gates(packet: dict[str, Any], project_id: str) -> list[str]:
    """Return a list of refusal reasons if packet gates fail."""
    refusals: list[str] = []

    # Check generated_by
    gen_by = packet.get("generated_by")
    if gen_by != "phase18g_openhands_decision_packet":
        refusals.append(f"generated_by mismatch: expected 'phase18g_openhands_decision_packet', got {gen_by!r}")

    # Check project_id
    pkt_pid = packet.get("project_id")
    if pkt_pid != project_id:
        refusals.append(f"project_id mismatch: packet has {pkt_pid!r}, requested {project_id!r}")

    # Check recommendation
    rec = packet.get("recommendation")
    if rec != "accept_for_manual_review":
        refusals.append(f"recommendation is not 'accept_for_manual_review': got {rec!r}")

    # Check canonical_repo_clean in packet
    crc = packet.get("canonical_repo_clean")
    if crc is not True:
        refusals.append(f"packet canonical_repo_clean is not true: got {crc!r}")

    return refusals


def check_status_gates(packet: dict[str, Any]) -> list[str]:
    """Check scope_status and exit_status sub-fields. Return refusal reasons."""
    refusals: list[str] = []

    scope = packet.get("scope_status", {})
    if not isinstance(scope, dict):
        scope = {}
    ss = scope.get("scope_status")
    if ss != "pass":
        refusals.append(f"scope_status.scope_status is not 'pass': got {ss!r}")

    exit_st = packet.get("exit_status", {})
    if not isinstance(exit_st, dict):
        exit_st = {}
    es = exit_st.get("status")
    if es != "pass":
        refusals.append(f"exit_status.status is not 'pass': got {es!r}")

    return refusals


def get_canonical_repo_status(cwd: Path) -> dict[str, list[str]]:
    """Capture working-tree and untracked status of the canonical repo."""
    wt_result = run_git(["status", "--short"], cwd)
    untracked_result = run_git(["ls-files", "--others", "--exclude-standard"], cwd)
    return {
        "working_tree": wt_result.stdout.strip().splitlines() if wt_result.returncode == 0 and wt_result.stdout.strip() else [],
        "untracked": untracked_result.stdout.strip().splitlines() if untracked_result.returncode == 0 and untracked_result.stdout.strip() else [],
    }


def resolve_run_dir(project_id: str, run_dir_arg: str | None) -> Path:
    if run_dir_arg:
        return Path(run_dir_arg).expanduser().resolve()
    return (ROOT / "runs" / project_id / "latest_openhands_coder").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Guarded manual OpenHands decision-packet apply gate.",
    )
    parser.add_argument("project_id", help="Project ID to apply the decision packet for.")
    parser.add_argument("--run-dir", default=None, help="Override the run directory path.")
    parser.add_argument("--packet", default=None, help="Override the decision packet file path.")
    parser.add_argument("--check-only", action="store_true", help="Run checks only (default behavior).")
    parser.add_argument("--apply", action="store_true", help="Apply the patch to the canonical repo.")
    parser.add_argument(
        "--allow-canonical-write",
        action="store_true",
        help="Explicitly allow writing to the canonical repository.",
    )
    parser.add_argument(
        "--confirm-project",
        default=None,
        help="Must exactly match PROJECT_ID to authorize apply.",
    )
    args = parser.parse_args()

    project_id: str = args.project_id
    mode: str
    refusal_reason: str | None = None

    # Determine mode and check apply gates.
    if args.apply:
        mode = "apply"
        # All four gates must pass for apply.
        missing_gates: list[str] = []
        if not args.allow_canonical_write:
            missing_gates.append("--allow-canonical-write")
        env_val = os.environ.get("AGENT_MANAGER_ALLOW_CANONICAL_APPLY", "")
        if env_val != "1":
            missing_gates.append("AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1")
        if not args.confirm_project or args.confirm_project != project_id:
            missing_gates.append(f"--confirm-project {project_id}")
    else:
        mode = "check_only"

    # Resolve paths.
    run_dir = resolve_run_dir(project_id, args.run_dir)
    if not args.packet:
        packet_path = run_dir / "OPENHANDS_DECISION_PACKET.json"
    else:
        packet_path = Path(args.packet).expanduser().resolve()

    patch_file_path: Path | None = None
    patch_sha256_expected: str | None = None
    canonical_repo_path: Path | None = None
    packet: dict[str, Any] = {}

    # --- Load and validate decision packet ---
    data, load_err = load_json_file(packet_path)
    if load_err:
        refusal_reason = f"decision packet error: {load_err}"
        artifact = {
            "schema_version": 1,
            "generated_by": GENERATED_BY_APPLY,
            "project_id": project_id,
            "created_utc": utc_now(),
            "mode": mode,
            "source_run_dir": str(run_dir),
            "packet_path": str(packet_path),
            "patch_file": "",
            "patch_sha256": "",
            "patch_sha256_verified": False,
            "canonical_repo": "",
            "canonical_repo_clean_before": False,
            "git_apply_check_passed": None,
            "applied": False,
            "apply_returncode": None,
            "canonical_repo_status_after": {},
            "refusal_reason": refusal_reason,
            "status": "fail",
            "no_commit_push_merge_pr_performed": True,
        }
        write_json(run_dir / "OPENHANDS_APPLY_STATUS.json", artifact)
        (run_dir / "OPENHANDS_APPLY_STATUS.md").write_text(build_markdown_report(artifact))
        (run_dir / "OPENHANDS_APPLY_REVIEW_COMMANDS.md").write_text(build_review_commands(artifact))
        print(f"Refused: {refusal_reason}")
        return 1

    packet = data if isinstance(data, dict) else {}

    # Check packet-level gates.
    packet_gates_fail = check_packet_gates(packet, project_id)
    status_gates_fail = check_status_gates(packet)
    all_refusals: list[str] = packet_gates_fail + status_gates_fail

    # Merge apply-mode gate failures into all_refusals.
    if mode == "apply" and missing_gates:
        all_refusals.append(f"apply mode refused: missing explicit gates: {'; '.join(missing_gates)}")

    if not patch_file_path:
        pf_raw = packet.get("patch_file")
        if isinstance(pf_raw, str):
            patch_file_path = Path(pf_raw).expanduser().resolve()
        else:
            patch_file_path = run_dir / "OPENHANDS_PATCH.diff"

    patch_sha256_expected = packet.get("patch_sha256")

    # Resolve canonical repo path.
    cr_raw = packet.get("canonical_repo") or ""
    if isinstance(cr_raw, str) and cr_raw:
        canonical_repo_path = Path(cr_raw).expanduser().resolve()

    # --- Check canonical repo is clean before operating ---
    repo_clean_before = False
    repo_status_after: dict[str, Any] = {}
    if canonical_repo_path and canonical_repo_path.exists():
        repo_clean_before = is_repo_clean(canonical_repo_path)
        if not repo_clean_before:
            all_refusals.append("canonical repo is currently dirty before check/apply")
    elif canonical_repo_path:
        all_refusals.append(f"canonical repo path does not exist: {canonical_repo_path}")

    # --- Check patch file exists and hash matches ---
    patch_sha256_verified = False
    if patch_file_path is None or not patch_file_path.exists():
        all_refusals.append("patch file missing")
    else:
        actual_hash = sha256_file(patch_file_path)
        if patch_sha256_expected and actual_hash != patch_sha256_expected:
            all_refusals.append(f"patch sha256 mismatch: expected {patch_sha256_expected}, got {actual_hash}")
        else:
            patch_sha256_verified = True

    # --- git apply --check ---
    git_apply_check_passed: bool | None = None
    if canonical_repo_path and patch_file_path and patch_file_path.exists():
        check_result = run_git(["apply", "--check", str(patch_file_path)], cwd=canonical_repo_path)
        git_apply_check_passed = check_result.returncode == 0
        if not git_apply_check_passed:
            stderr = (check_result.stderr or "").strip()
            stdout = (check_result.stdout or "").strip()
            msg = f"patch does not pass git apply --check: {stderr or stdout}"
            all_refusals.append(msg)

    # --- Determine status and refusal ---
    if all_refusals:
        refusal_reason = "; ".join(all_refusals)
        status = "fail"
    else:
        status = "pass"

    # --- Apply (if gates pass) ---
    applied = False
    apply_returncode: int | None = None

    if mode == "apply" and not refusal_reason and git_apply_check_passed is True and canonical_repo_path and patch_file_path:
        apply_result = run_git(["apply", str(patch_file_path)], cwd=canonical_repo_path)
        applied = apply_result.returncode == 0
        apply_returncode = apply_result.returncode
        if applied:
            status = "pass"

    # --- Capture canonical repo status after ---
    if canonical_repo_path and canonical_repo_path.exists():
        repo_status_after = get_canonical_repo_status(canonical_repo_path)

    # --- Build artifact ---
    artifact = {
        "schema_version": 1,
        "generated_by": GENERATED_BY_APPLY,
        "project_id": project_id,
        "created_utc": utc_now(),
        "mode": mode,
        "source_run_dir": str(run_dir),
        "packet_path": str(packet_path),
        "patch_file": str(patch_file_path) if patch_file_path else "",
        "patch_sha256": patch_sha256_expected or "",
        "patch_sha256_verified": patch_sha256_verified,
        "canonical_repo": str(canonical_repo_path) if canonical_repo_path else "",
        "canonical_repo_clean_before": repo_clean_before,
        "git_apply_check_passed": git_apply_check_passed,
        "applied": applied,
        "apply_returncode": apply_returncode,
        "canonical_repo_status_after": repo_status_after,
        "refusal_reason": refusal_reason,
        "status": status,
        "no_commit_push_merge_pr_performed": True,
    }

    # Include packet recommendation for markdown report.
    artifact["packet_recommendation"] = packet.get("recommendation", "")

    write_json(run_dir / "OPENHANDS_APPLY_STATUS.json", artifact)
    (run_dir / "OPENHANDS_APPLY_STATUS.md").write_text(build_markdown_report(artifact))
    (run_dir / "OPENHANDS_APPLY_REVIEW_COMMANDS.md").write_text(build_review_commands(artifact))

    if refusal_reason:
        print(f"Refused: {refusal_reason}")
    else:
        if applied:
            print("Apply succeeded. Canonical repo is now intentionally changed (no commit made).")
        else:
            print("Check-only complete. All gates passed; patch ready for manual apply.")
        print(f"Status: {status.upper()}")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
