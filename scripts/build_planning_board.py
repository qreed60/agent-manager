#!/usr/bin/env python3
"""Phase 24 — Multi-Project Agent Planning Board (aggregation only).

Reads Phase 21, 22, and 23 artifacts across registered projects and produces:
  - GLOBAL_FEATURE_QUEUE.json   -- global prioritized feature queue
  - PROJECT_FEATURE_STATUS.json -- per-project status summary
  - AGENT_MANAGER_PLANNING_BOARD.md -- human-readable planning board

This phase performs NO execution. No source writes to target repos, no OpenHands,
no coder tasks, no apply/commit/push/merge/PR behavior.

Usage::

    python3 scripts/build_planning_board.py
    python3 scripts/build_planning_board.py --project-id <project_id>
    python3 scripts/build_planning_board.py --include-archived
    python3 scripts/build_planning_board.py --fail-on-missing-artifacts

"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase24_multi_project_planning_board"
PHASE24_GENERATED_BY = GENERATED_BY  # alias for external references (validation, tests)

# Directories under runs/<project_id> that hold Phase 21/22/23 artifacts
FEATURE_BRIEFS_DIR = "feature_briefs"
ARCHITECTURE_DIR = "architecture_proposals"
MANAGER_PLANS_DIR = "manager_objective_plans"

VALID_FEATURE_STATUSES = frozenset({
    "brief_only", "needs_clarification", "ready_for_architecture",
    "architecture_ready", "manager_plan_ready", "ready_for_human_review",
    "blocked", "archived",
})

VALID_ARCHITECTURE_STATUSES = frozenset({"none", "proposal_ready", "needs_clarification", "blocked"})
VALID_MANAGER_PLAN_STATUSES = frozenset({"none", "draft_ready", "needs_clarification", "blocked"})
VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})

# Recommended next-action enum values
RECOMMENDED_ACTIONS = frozenset({
    "missing_feature_brief",
    "clarify_feature_brief",
    "run_architecture_agent_mock_or_gated",
    "clarify_architecture",
    "run_manager_objective_planner_mock_or_gated",
    "clarify_manager_plan",
    "review_openhands_manual_gate_draft",
    "resolve_blocker",
    "monitor_or_archive",
})

# Paths that indicate target repo writes (must NOT appear in artifact paths)
TARGET_REPO_INDICATORS = frozenset({"/mnt/projects/", "/home/qreed/projects/"})

SUGGESTED_OUTPUT_DIR = ROOT / "runs" / "planning_board"

# Default artifact paths (can be overridden for testing)
GLOBAL_FEATURE_QUEUE_PATH = SUGGESTED_OUTPUT_DIR / "GLOBAL_FEATURE_QUEUE.json"
PROJECT_FEATURE_STATUS_PATH = SUGGESTED_OUTPUT_DIR / "PROJECT_FEATURE_STATUS.json"
PLANNING_BOARD_MD_PATH = SUGGESTED_OUTPUT_DIR / "AGENT_MANAGER_PLANNING_BOARD.md"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n")


def load_projects_config() -> dict[str, Any]:
    return load_json(ROOT / "configs" / "projects.json")


def _resolve_server_base(project_id: str, server_state_dir: str) -> Path:
    """Resolve the central runs base directory for a project.

    Handles three cases:
      1. server_state_dir is empty or '.' → use runs/<project_id>
      2. server_state_dir starts with 'runs/' → use it directly (already absolute-ish)
      3. Otherwise → append to runs/<project_id>
    """
    if not server_state_dir or server_state_dir == ".":
        return ROOT / "runs" / project_id
    ssd = Path(server_state_dir)
    if ssd.is_absolute():
        return ssd
    if str(ssd).startswith("runs/"):
        return ROOT / ssd
    return ROOT / "runs" / project_id / ssd


# ---------------------------------------------------------------------------
# Feature scanning per project
# ---------------------------------------------------------------------------


def scan_feature_briefs(project_id: str, server_state_dir: str, include_archived: bool) -> list[dict[str, Any]]:
    """Scan runs/<project_id>/<server_state_dir>/feature_briefs/ for FEATURE_BRIEF.json files.

    Returns a list of feature data dicts with basic metadata. Each entry has at minimum:
      feature_id, title, status, risk_level, human_priority, target_project_area,
      created_utc, brief_path, brief_data (full JSON).
    """
    base_dir = _resolve_server_base(project_id, server_state_dir)
    # When server_state_dir starts with 'runs/', it IS the base (e.g. runs/thommonlint).
    # Feature briefs live directly under that: <base>/feature_briefs/
    feature_briefs_dir = base_dir / FEATURE_BRIEFS_DIR
    features: list[dict[str, Any]] = []

    if not feature_briefs_dir.is_dir():
        return features

    for feat_dir in sorted(feature_briefs_dir.iterdir()):
        if not feat_dir.is_dir():
            continue
        brief_path = feat_dir / "FEATURE_BRIEF.json"
        if not brief_path.exists():
            continue

        try:
            brief_data = load_json(brief_path)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(brief_data, dict):
            continue
        if brief_data.get("generated_by") != "phase21_feature_brief_intake":
            continue

        status = brief_data.get("status", "brief_only")
        if not include_archived and status == "archived":
            continue

        features.append({
            "feature_id": brief_data.get("feature_id", ""),
            "title": brief_data.get("title", ""),
            "status": status,
            "risk_level": brief_data.get("risk_level", "medium"),
            "human_priority": brief_data.get("human_priority", 3),
            "target_project_area": brief_data.get("target_project_area", ""),
            "created_utc": brief_data.get("created_utc", utc_now()),
            "brief_path": str(brief_path),
            "feature_dir": feat_dir,
            "brief_data": brief_data,
        })

    return features


def check_architecture_proposal(feature_id: str, project_id: str, server_state_dir: str) -> tuple[bool, dict[str, Any] | None, Path]:
    """Check if ARCHITECTURE_PROPOSAL.json exists for a feature.

    Returns (exists, proposal_data_or_none, path).
    """
    base_dir = _resolve_server_base(project_id, server_state_dir)
    # Architecture proposals live under <base>/architecture_proposals/<feature_id>/
    arch_dir = base_dir / ARCHITECTURE_DIR / feature_id
    arch_path = arch_dir / "ARCHITECTURE_PROPOSAL.json"

    if not arch_path.exists():
        return False, None, arch_path

    try:
        data = load_json(arch_path)
    except (json.JSONDecodeError, OSError):
        return True, None, arch_path

    if isinstance(data, dict) and data.get("generated_by") == "phase22_ai_architecture_agent":
        return True, data, arch_path

    return True, None, arch_path


def check_manager_objective_plan(feature_id: str, project_id: str, server_state_dir: str) -> tuple[bool, dict[str, Any] | None, Path]:
    """Check if MANAGER_OBJECTIVE_PLAN.json exists for a feature.

    Returns (exists, plan_data_or_none, path).
    """
    base_dir = _resolve_server_base(project_id, server_state_dir)
    # Manager plans live under <base>/manager_objective_plans/<feature_id>/
    plan_dir = base_dir / MANAGER_PLANS_DIR / feature_id
    plan_path = plan_dir / "MANAGER_OBJECTIVE_PLAN.json"

    if not plan_path.exists():
        return False, None, plan_path

    try:
        data = load_json(plan_path)
    except (json.JSONDecodeError, OSError):
        return True, None, plan_path

    if isinstance(data, dict) and data.get("generated_by") == "phase23_ai_manager_objective_planner":
        return True, data, plan_path

    return True, None, plan_path


def check_openhands_draft(feature_id: str, project_id: str, server_state_dir: str) -> tuple[bool, dict[str, Any] | None, Path]:
    """Check if OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json exists for a feature.

    Returns (exists, draft_data_or_none, path).
    """
    base_dir = _resolve_server_base(project_id, server_state_dir)
    # Manager plans live under <base>/manager_objective_plans/<feature_id>/
    plan_dir = base_dir / MANAGER_PLANS_DIR / feature_id
    draft_path = plan_dir / "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json"

    if not draft_path.exists():
        return False, None, draft_path

    try:
        data = load_json(draft_path)
    except (json.JSONDecodeError, OSError):
        return True, None, draft_path

    return True, data, draft_path


# ---------------------------------------------------------------------------
# Recommended next-action logic
# ---------------------------------------------------------------------------


def determine_recommended_next_action(feature: dict[str, Any]) -> str:
    """Determine the recommended next action for a feature based on its state.

    Priority order (first match wins):
      1. blocked -> resolve_blocker
      2. ready_for_human_review + draft exists -> review_openhands_manual_gate_draft
      3. no manager plan -> run_manager_objective_planner_mock_or_gated
      4. manager_plan_status needs_clarification -> clarify_manager_plan
      5. no architecture proposal -> run_architecture_agent_mock_or_gated
      6. architecture_status needs_clarification -> clarify_architecture
      7. feature_status needs_clarification -> clarify_feature_brief
      8. otherwise -> monitor_or_archive
    """
    blocked = feature.get("blocked", False)
    if blocked:
        return "resolve_blocker"

    ready_for_gate = feature.get("ready_for_openhands_manual_gate", False)
    has_draft = feature.get("has_openhands_manual_gate_request_draft", False)
    if ready_for_gate and has_draft:
        return "review_openhands_manual_gate_draft"

    has_plan = feature.get("has_manager_objective_plan", False)
    if not has_plan:
        return "run_manager_objective_planner_mock_or_gated"

    manager_status = feature.get("manager_plan_status", "none")
    if manager_status == "needs_clarification":
        return "clarify_manager_plan"

    has_arch = feature.get("has_architecture_proposal", False)
    if not has_arch:
        return "run_architecture_agent_mock_or_gated"

    arch_status = feature.get("architecture_status", "none")
    if arch_status == "needs_clarification":
        return "clarify_architecture"

    feat_status = feature.get("feature_status", "brief_only")
    if feat_status == "needs_clarification":
        return "clarify_feature_brief"

    return "monitor_or_archive"


# ---------------------------------------------------------------------------
# Determination of overall feature status and readiness
# ---------------------------------------------------------------------------


def determine_feature_status(feature: dict[str, Any]) -> str:
    """Determine the overall feature status across all phases."""
    feat_status = feature.get("status", "brief_only")

    # If archived in brief, keep it
    if feat_status == "archived":
        return "archived"

    has_arch = feature.get("has_architecture_proposal", False)
    feat_status_raw = feature.get("status", "brief_only")
    
    # Preserve blocked/needs_clarification from brief before recomputing downstream
    if feat_status_raw == "blocked":
        return "blocked"
    if feat_status_raw == "needs_clarification":
        return "needs_clarification"

    has_plan = feature.get("has_manager_objective_plan", False)
    has_draft = feature.get("has_openhands_manual_gate_request_draft", False)

    # If manager plan + draft exist, it's ready for human review
    if has_plan and has_draft:
        return "ready_for_human_review"

    # If architecture proposal exists but no manager plan
    if has_arch and not has_plan:
        return "architecture_ready"

    # Preserve blocked status from brief even when downstream artifacts exist
    if feat_status == "blocked":
        return "blocked"

    if feat_status == "needs_clarification":
        return "needs_clarification"

    # If brief only status still
    if feat_status == "brief_only":
        return "brief_only"

    # Default: ready for architecture stage
    if has_arch:
        return "architecture_ready"

    return "ready_for_architecture"


def determine_readiness_for_openhands(feature: dict[str, Any]) -> bool:
    """Determine if a feature is ready for OpenHands manual gate."""
    has_plan = feature.get("has_manager_objective_plan", False)
    has_draft = feature.get("has_openhands_manual_gate_request_draft", False)

    if not (has_plan and has_draft):
        return False

    # Check manager plan status
    plan_data = feature.get("_plan_data")
    if plan_data:
        plan_status = plan_data.get("manager_plan_status", "none")
        if plan_status == "blocked":
            return False
        ready_flag = plan_data.get("ready_for_openhands_manual_gate", False)
        if not ready_flag:
            return False

    # Check draft approval status
    draft_data = feature.get("_draft_data")
    if draft_data:
        approved = draft_data.get("approved_for_execution", False)
        if approved:
            return False  # already consumed, not a pending review item
        draft_only = draft_data.get("draft_only", True)
        if not draft_only:
            return False

    return True


def determine_blocked_status(feature: dict[str, Any]) -> tuple[bool, str]:
    """Determine if feature is blocked and why."""
    feat_status = feature.get("status", "brief_only")
    has_arch = feature.get("has_architecture_proposal", False)
    has_plan = feature.get("has_manager_objective_plan", False)

    # Brief-level blockers
    if feat_status == "blocked":
        return True, f"Feature brief is blocked (status={feat_status})"

    if not has_arch and feat_status != "archived":
        return False, ""

    arch_data = feature.get("_arch_data")
    if arch_data:
        arch_status = arch_data.get("architecture_status", "none")
        if arch_status == "blocked":
            return True, f"Architecture proposal is blocked (status={arch_status})"
        if arch_status == "needs_clarification":
            return True, f"Architecture needs clarification (status={arch_status})"

    plan_data = feature.get("_plan_data")
    if plan_data:
        plan_status = plan_data.get("manager_plan_status", "none")
        if plan_status == "blocked":
            return True, f"Manager objective plan is blocked (status={plan_status})"
        if plan_status == "needs_clarification":
            return True, f"Manager plan needs clarification (status={plan_status})"

    return False, ""


# ---------------------------------------------------------------------------
# Path safety validation
# ---------------------------------------------------------------------------


def validate_paths_safe(paths: dict[str, str | None]) -> bool:
    """Ensure artifact paths are under central runs storage, not target repos."""
    for key, path in paths.items():
        if path is None:
            continue
        # Check that the path doesn't point to a target project repo
        if any(indicator in path for indicator in TARGET_REPO_INDICATORS):
            return False
    return True


# ---------------------------------------------------------------------------
# Core aggregation logic
# ---------------------------------------------------------------------------


def build_global_feature_queue(
    projects: dict[str, Any],
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Build the global feature queue from all registered (or filtered) projects.

    Returns a list of normalized feature entries ready for output.
    """
    all_features: list[dict[str, Any]] = []

    project_ids_scanned: list[str] = []

    # Get active projects
    all_projects_cfg = projects.get("projects", {})
    if not isinstance(all_projects_cfg, dict):
        return [], []

    for proj_id in sorted(all_projects_cfg.keys()):
        proj_cfg = all_projects_cfg[proj_id]
        if not isinstance(proj_cfg, dict):
            continue
        if not proj_cfg.get("enabled", True):
            continue
        project_ids_scanned.append(proj_id)

        # Scan feature briefs
        server_state_dir = proj_cfg.get("server_state_dir", "")
        feature_list = scan_feature_briefs(proj_id, server_state_dir, include_archived)

        for feat in feature_list:
            feature_id = feat["feature_id"]

            # Check architecture proposal
            has_arch, arch_data, arch_path = check_architecture_proposal(
                feature_id, proj_id, server_state_dir
            )

            # Check manager objective plan
            has_plan, plan_data, plan_path = check_manager_objective_plan(
                feature_id, proj_id, server_state_dir
            )

            # Check OpenHands draft
            has_draft, draft_data, draft_path = check_openhands_draft(
                feature_id, proj_id, server_state_dir
            )

            # Determine blocked status
            is_blocked, blocked_reason = determine_blocked_status(feat)

            # Set internal data references for downstream logic
            feat["_arch_data"] = arch_data
            feat["_plan_data"] = plan_data
            feat["_draft_data"] = draft_data

            # Build artifact paths (relative to ROOT)
            brief_rel = str(feat["feature_dir"].relative_to(ROOT)) if feat["feature_dir"] else ""
            arch_rel = str(arch_path.relative_to(ROOT)) if arch_path and arch_path.exists() else ""
            plan_rel = str(plan_path.relative_to(ROOT)) if plan_path and plan_path.exists() else ""
            draft_rel = str(draft_path.relative_to(ROOT)) if draft_path and draft_path.exists() else ""

            paths_dict = {
                "feature_brief_path": brief_rel,
                "architecture_proposal_path": arch_rel,
                "manager_objective_plan_path": plan_rel,
                "openhands_manual_gate_draft_path": draft_rel,
            }

            # Validate path safety
            paths_safe = validate_paths_safe(paths_dict)

            # Determine architecture status
            if has_arch and arch_data:
                arch_status = arch_data.get("architecture_status", "none")
            elif has_arch:
                arch_status = "blocked"  # corrupted file
            else:
                arch_status = "none"

            # Determine manager plan status
            if has_plan and plan_data:
                mgr_status = plan_data.get("manager_plan_status", "none")
            elif has_plan:
                mgr_status = "blocked"  # corrupted file
            else:
                mgr_status = "none"

            # Determine readiness for OpenHands manual gate
            ready_for_gate = determine_readiness_for_openhands(feat)

            # Build the normalized feature entry
            entry = {
                "project_id": proj_id,
                "feature_id": feature_id,
                "title": feat["title"],
                "feature_status": "brief_only",  # placeholder; set below
                "risk_level": feat.get("risk_level", "medium"),
                "human_priority": feat.get("human_priority", 3),
                "target_project_area": feat.get("target_project_area", ""),
                "has_feature_brief": True,
                "has_architecture_proposal": has_arch,
                "has_manager_objective_plan": has_plan,
                "has_openhands_manual_gate_request_draft": has_draft,
                "architecture_status": arch_status,
                "manager_plan_status": mgr_status,
                "ready_for_openhands_manual_gate": ready_for_gate,
                "blocked": is_blocked and paths_safe,
                "blocked_reason": blocked_reason if (is_blocked and paths_safe) else "",
                "latest_artifact_paths": paths_dict,
                "recommended_next_action": "monitor_or_archive",  # placeholder; set below
            }

            all_features.append(entry)

    # Second pass: determine feature_status and recommended_next_action for each entry
    for entry in all_features:
        entry["feature_status"] = determine_feature_status(entry)
        entry["recommended_next_action"] = determine_recommended_next_action(entry)

    return all_features, project_ids_scanned


def sort_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort features by priority for the planning board.

    Sort order:
      1. blocked (True first -- needs attention)
      2. human_priority ascending (lower = higher priority)
      3. readiness descending (ready_for_human_review > manager_plan_ready > architecture_ready > ... )
      4. project_id ascending
      5. created_utc ascending
    """
    status_order = {
        "ready_for_human_review": 0,
        "manager_plan_ready": 1,
        "architecture_ready": 2,
        "needs_clarification": 3,
        "blocked": 4,
        "ready_for_architecture": 5,
        "brief_only": 6,
        "archived": 7,
    }

    def sort_key(feat: dict[str, Any]) -> tuple:
        # Negate blocked so True sorts first (needs attention)
        blocked = not feat.get("blocked", False)
        priority = feat.get("human_priority", 3)
        status_rank = status_order.get(feat.get("feature_status", "brief_only"), 6)
        project_id = feat.get("project_id", "")
        created = feat.get("created_utc", "00000000T000000Z")

        return (blocked, priority, status_rank, project_id, created)

    return sorted(features, key=sort_key)


def build_project_status(
    features: list[dict[str, Any]],
    projects_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build per-project status from the global feature queue."""
    all_projects = projects_cfg.get("projects", {})

    # Group features by project_id
    by_project: dict[str, list[dict[str, Any]]] = {}
    for feat in features:
        pid = feat.get("project_id", "")
        if pid not in by_project:
            by_project[pid] = []
        by_project[pid].append(feat)

    project_statuses: list[dict[str, Any]] = []

    for proj_id in sorted(all_projects.keys()):
        proj_cfg = all_projects.get(proj_id, {})
        if not isinstance(proj_cfg, dict):
            continue

        proj_features = by_project.get(proj_id, [])
        total = len(proj_features)
        brief_only = sum(1 for f in proj_features if f.get("feature_status") == "brief_only")
        arch_ready = sum(1 for f in proj_features if f.get("feature_status") == "architecture_ready")
        mgr_ready = sum(1 for f in proj_features if f["feature_status"] == "manager_plan_ready" or f.get("has_manager_objective_plan"))
        review_ready = sum(1 for f in proj_features if f.get("feature_status") == "ready_for_human_review")
        blocked = sum(1 for f in proj_features if f.get("blocked", False))

        # Count missing artifacts (features that have brief but no architecture or plan)
        missing = 0
        for f in proj_features:
            if not f.get("has_feature_brief", False):
                continue
            has_all = f.get("has_architecture_proposal", False) and f.get("has_manager_objective_plan", False)
            if not has_all:
                missing += 1

        # Latest feature IDs (sorted by created_utc descending)
        latest_ids = sorted(
            [f.get("feature_id") for f in proj_features],
            key=lambda fid: next(
                (ff.get("created_utc", "") for ff in proj_features if ff.get("feature_id") == fid), ""
            ),
            reverse=True,
        )

        # Recommended actions for this project
        actions = set()
        for f in proj_features:
            action = f.get("recommended_next_action", "monitor_or_archive")
            actions.add(action)

        entry = {
            "project_id": proj_id,
            "project_name": proj_cfg.get("name", proj_id),
            "registered": True,
            "repo_path": proj_cfg.get("repo_path", ""),
            "server_state_dir": proj_cfg.get("server_state_dir", ""),
            "total_features": total,
            "brief_only_count": brief_only,
            "architecture_ready_count": arch_ready,
            "manager_plan_ready_count": mgr_ready,
            "ready_for_human_review_count": review_ready,
            "blocked_count": blocked,
            "missing_artifact_count": missing,
            "latest_feature_ids": latest_ids,
            "recommended_next_actions": sorted(actions),
        }
        project_statuses.append(entry)

    return project_statuses


# ---------------------------------------------------------------------------
# Markdown planning board generation
# ---------------------------------------------------------------------------


def build_markdown_board(
    features: list[dict[str, Any]],
    project_statuses: list[dict[str, Any]],
    created_utc: str,
) -> str:
    """Build a human-readable Markdown planning board."""
    lines = [
        "# Agent Manager Planning Board",
        "",
        f"> **Generated**: {created_utc}",
        f"> **Generated by**: {GENERATED_BY}",
        "> **Safety**: This board is read-only aggregation. No execution performed.",
        "",
        "---",
        "",
    ]

    # Summary counts
    total = len(features)
    blocked_count = sum(1 for f in features if f.get("blocked"))
    review_ready_count = sum(1 for f in features if f.get("feature_status") == "ready_for_human_review")
    arch_ready_count = sum(1 for f in features if f.get("feature_status") == "architecture_ready")
    brief_only_count = sum(1 for f in features if f.get("feature_status") == "brief_only")

    lines.extend([
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | --- |",
        f"| Total Features | {total} |",
        f"| Ready for Human Review | {review_ready_count} |",
        f"| Architecture Ready | {arch_ready_count} |",
        f"| Brief Only (needs architecture) | {brief_only_count} |",
        f"| Blocked | {blocked_count} |",
        "",
        "---",
        "",
    ])

    # Summary by project
    lines.extend([
        "## Project Summary",
        "",
        "| Project | Total | Brief Only | Arch Ready | Plan Ready | Review Ready | Blocked | Missing Artifacts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ])

    for ps in project_statuses:
        lines.append(
            f"| {ps['project_name']} ({ps['project_id']}) "
            f"| {ps['total_features']} "
            f"| {ps['brief_only_count']} "
            f"| {ps['architecture_ready_count']} "
            f"| {ps['manager_plan_ready_count']} "
            f"| {ps['ready_for_human_review_count']} "
            f"| {ps['blocked_count']} "
            f"| {ps['missing_artifact_count']} |"
        )

    lines.extend(["", "---", "", ""])

    # Global prioritized feature table
    lines.extend([
        "## Global Prioritized Feature Queue",
        "",
        "| # | Project | Feature ID | Title | Status | Priority | Risk | Blocked | Next Action |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])

    for idx, feat in enumerate(features, 1):
        blocked_marker = "**YES**" if feat.get("blocked") else "no"
        lines.append(
            f"| {idx} | {feat['project_id']} | `{feat['feature_id']}` "
            f"| {feat['title']} "
            f"| {feat['feature_status']} "
            f"| {feat['human_priority']} "
            f"| {feat['risk_level']} "
            f"| {blocked_marker} "
            f"| {feat['recommended_next_action']} |"
        )

    lines.extend(["", "---", "", ""])

    # Ready for human review section
    ready_items = [f for f in features if f.get("feature_status") == "ready_for_human_review"]
    lines.extend([
        "## Ready for Human Review",
        "",
    ])
    if ready_items:
        for feat in ready_items:
            lines.append(f"- **[{feat['project_id']}]** `{feat['feature_id']}` — {feat['title']}")
            paths = feat.get("latest_artifact_paths", {})
            draft_path = paths.get("openhands_manual_gate_draft_path", "")
            if draft_path:
                lines.append(f"  - Draft request at: `{draft_path}`")
    else:
        lines.append("- No features currently ready for human review.")

    lines.extend(["", "---", "", ""])

    # Blocked or needs clarification section
    blocked_items = [f for f in features if f.get("blocked") or f.get("feature_status") == "needs_clarification"]
    lines.extend([
        "## Blocked or Needs Clarification",
        "",
    ])
    if blocked_items:
        for feat in blocked_items:
            reason = feat.get("blocked_reason", "")
            status = feat["feature_status"]
            detail = f"({reason})" if reason else f"(status: {status})"
            lines.append(f"- **[{feat['project_id']}]** `{feat['feature_id']}` — {feat['title']} {detail}")
    else:
        lines.append("- No blocked features.")

    lines.extend(["", "---", "", ""])

    # Missing artifact warnings section
    missing_items = [f for f in features if (not f.get("has_architecture_proposal", False) or not f.get("has_manager_objective_plan", False))]
    lines.extend([
        "## Missing Artifact Warnings",
        "",
    ])
    if missing_items:
        for feat in missing_items:
            parts = []
            if not feat.get("has_feature_brief", False):
                parts.append("missing feature brief")
            if not feat["has_architecture_proposal"]:
                parts.append("architecture proposal")
            if not feat["has_manager_objective_plan"]:
                parts.append("manager objective plan")
            lines.append(f"- **[{feat['project_id']}]** `{feat['feature_id']}` — missing: {', '.join(parts)}")
    else:
        lines.append("- All features have complete artifacts.")

    lines.extend(["", "---", "", ""])

    # Recommended next actions section
    lines.extend([
        "## Recommended Next Actions",
        "",
    ])

    action_groups: dict[str, list[dict[str, Any]]] = {}
    for feat in features:
        action = feat.get("recommended_next_action", "monitor_or_archive")
        if action not in action_groups:
            action_groups[action] = []
        action_groups[action].append(feat)

    action_descriptions = {
        "resolve_blocker": "Resolve blockers before proceeding.",
        "review_openhands_manual_gate_draft": "Review the OpenHands manual gate request draft for approval.",
        "run_manager_objective_planner_mock_or_gated": "Run the manager objective planner (mock or gated).",
        "clarify_manager_plan": "Clarify the manager plan with the feature author.",
        "run_architecture_agent_mock_or_gated": "Run the architecture agent (mock or gated).",
        "clarify_architecture": "Clarify the architecture proposal with the feature author.",
        "clarify_feature_brief": "Clarify the feature brief with the stakeholder.",
        "monitor_or_archive": "Monitor progress or archive if no longer relevant.",
    }

    for action, items in sorted(action_groups.items()):
        desc = action_descriptions.get(action, f"Action: {action}")
        lines.append(f"### `{action}`")
        lines.append(f"{desc}")
        lines.append("")
        for feat in items:
            lines.append(f"- **[{feat['project_id']}]** `{feat['feature_id']}` — {feat['title']}")
        lines.append("")

    # Safety note
    lines.extend([
        "---",
        "",
        "## Safety Note",
        "",
        "> **Phase 24 is planning-board only and performs no execution.**",
        "> - No source writes to target project repositories",
        "> - No OpenHands execution",
        "> - No coder task execution",
        "> - No apply/commit/push/merge/PR behavior",
        "> - All artifact paths are under central agent-manager runs storage",
        "",
        "---",
        "",
        "*End of planning board.*",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def validate_phase24_global_feature_queue(recorder=None):
    """Validate GLOBAL_FEATURE_QUEUE.json against Phase 24 requirements."""
    from validate_agent_run import CheckRecorder as _CR
    if recorder is None:
        recorder = _CR()
    return _validate_global_queue(recorder)


def _validate_global_queue(recorder):
    """Internal validation of global feature queue."""
    import json as _json
    from datetime import datetime, timezone as _tz

    p = GLOBAL_FEATURE_QUEUE_PATH
    if not p.exists():
        recorder.add("ph24_global_1", "fail", "GLOBAL_FEATURE_QUEUE.json does not exist", path=p)
        return
    recorder.add( "ph24_global_2", "pass", "GLOBAL_FEATURE_QUEUE.json exists")

    try:
        data = _json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        recorder.add( "ph24_global_3", "fail", f"Failed to parse GLOBAL_FEATURE_QUEUE.json: {exc}")
        return
    recorder.add( "ph24_global_4", "pass", "GLOBAL_FEATURE_QUEUE.json is valid JSON")

    sv = data.get("schema_version")
    if sv != 1:
        recorder.add("ph24_global_5", "fail", f"Invalid schema_version: {sv}", details={"expected": 1, "got": sv})
    else:
        recorder.add( "ph24_global_6", "pass", "schema_version is 1")

    gb = data.get("generated_by")
    if gb != PHASE24_GENERATED_BY:
        recorder.add("ph24_global_7", "fail", f"Invalid generated_by: {gb}", details={"expected": PHASE24_GENERATED_BY, "got": gb})
    else:
        recorder.add( "ph24_global_8", "pass", f"generated_by is correct ({PHASE24_GENERATED_BY})")

    cu = data.get("created_utc")
    if not isinstance(cu, str) or len(cu) < 10:
        recorder.add( "ph24_global_9", "fail", f"Invalid or missing created_utc: {cu!r}")
    else:
        try:
            datetime.strptime(cu, "%Y%m%dT%H%M%SZ")
            recorder.add( "ph24_global_10", "pass", "created_utc is valid ISO format")
        except ValueError:
            recorder.add( "ph24_global_11", "fail", f"created_utc not parseable as %Y%m%dT%H%M%SZ: {cu}")

    ps = data.get("projects_scanned")
    if not isinstance(ps, list):
        recorder.add( "ph24_global_12", "fail", f"projects_scanned is not a list: {type(ps)}")
    else:
        recorder.add( "ph24_global_13", "pass", f"projects_scanned is a list ({len(ps)} projects)")

    tf = data.get("total_features")
    if not isinstance(tf, int):
        recorder.add( "ph24_global_14", "fail", f"total_features is not an integer: {tf!r}")
    else:
        recorder.add( "ph24_global_15", "pass", f"total_features is {tf}")

    feats = data.get("features")
    if not isinstance(feats, list):
        recorder.add( "ph24_global_16", "fail", f"features is not a list: {type(feats)}")
        return
    recorder.add( "ph24_global_17", "pass", f"features is a list ({len(feats)} entries)")

    for i, feat in enumerate(feats):
        pid = feat.get("project_id")
        fid = feat.get("feature_id")
        if not pid:
            recorder.add( "ph24_global_18", "fail", f"Feature[{i}] missing project_id")
        if not fid:
            recorder.add( "ph24_global_19", "fail", f"Feature[{i}] missing feature_id")

        latest = feat.get("latest_artifact_paths", {})
        for key, pval in latest.items():
            if pval and any(ind in str(pval) for ind in TARGET_REPO_INDICATORS):
                recorder.add( "ph24_global_20", "fail", f"Feature[{i}] {key} points to target repo: {pval}")

    safety = data.get("safety_summary", {})
    required_safety_keys = [
        "source_writes_performed", "openhands_executed", "coder_task_executed",
        "apply_performed", "commit_performed", "push_performed",
        "merge_performed", "pr_created",
    ]
    has_any = any(safety.get(k, None) is not None for k in required_safety_keys)
    if not has_any:
        recorder.add("ph24_global_safe_skip", "pass", "No safety_summary to validate (skipped)")
    else:
        for key in required_safety_keys:
            val = safety.get(key, None)
            if val is not False and val is not None:
                recorder.add(f"ph24_global_{key}", "fail", f"Safety flag {key}={val}, expected False (no execution)")

        all_safe = all(safety.get(k, True) is False for k in required_safety_keys)
        if not all_safe:
            recorder.add("ph24_global_22", "fail", "Phase 24 safety flags indicate execution was performed")
        else:
            recorder.add("ph24_global_23", "pass", "All Phase 24 safety flags indicate no execution")


def validate_phase24_project_feature_status(recorder=None):
    """Validate PROJECT_FEATURE_STATUS.json against Phase 24 requirements."""
    from validate_agent_run import CheckRecorder as _CR
    if recorder is None:
        recorder = _CR()
    return _validate_project_status(recorder)


def _validate_project_status(recorder):
    """Internal validation of project feature status."""
    import json as _json

    p = PROJECT_FEATURE_STATUS_PATH
    if not p.exists():
        recorder.add( "ph24_project_1", "fail", "PROJECT_FEATURE_STATUS.json does not exist")
        return
    recorder.add( "ph24_project_2", "pass", "PROJECT_FEATURE_STATUS.json exists")

    try:
        data = _json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        recorder.add( "ph24_project_3", "fail", f"Failed to parse PROJECT_FEATURE_STATUS.json: {exc}")
        return
    recorder.add( "ph24_project_4", "pass", "PROJECT_FEATURE_STATUS.json is valid JSON")

    sv = data.get("schema_version")
    if sv != 1:
        recorder.add("ph24_project_5", "fail", f"Invalid schema_version: {sv}", details={"expected": 1, "got": sv})
    else:
        recorder.add( "ph24_project_6", "pass", "schema_version is 1")

    gb = data.get("generated_by")
    if gb != PHASE24_GENERATED_BY:
        recorder.add("ph24_project_7", "fail", f"Invalid generated_by: {gb}", details={"expected": PHASE24_GENERATED_BY, "got": gb})
    else:
        recorder.add( "ph24_project_8", "pass", f"generated_by is correct ({PHASE24_GENERATED_BY})")

    projects = data.get("projects")
    if not isinstance(projects, list):
        recorder.add( "ph24_project_9", "fail", f"projects is not a list: {type(projects)}")
        return
    recorder.add( "ph24_project_10", "pass", f"projects is a list ({len(projects)} entries)")

    required_proj_keys = [
        "project_id", "registered", "total_features",
        "brief_only_count", "architecture_ready_count",
        "manager_plan_ready_count", "ready_for_human_review_count",
        "blocked_count", "missing_artifact_count",
    ]
    for i, proj in enumerate(projects):
        pid = proj.get("project_id")
        if not pid:
            recorder.add( "ph24_project_11", "fail", f"Project[{i}] missing project_id")
        for key in required_proj_keys:
            if key not in proj:
                recorder.add( "ph24_project_12", "fail", f"Project[{pid}] missing key: {key}")

    safety = data.get("safety_summary", {})
    required_safety_keys = [
        "source_writes_performed", "openhands_executed", "coder_task_executed",
        "apply_performed", "commit_performed", "push_performed",
        "merge_performed", "pr_created",
    ]
    has_any2 = any(safety.get(k, None) is not None for k in required_safety_keys)
    if not has_any2:
        recorder.add("ph24_project_safe_skip", "pass", "No safety_summary to validate (skipped)")
    else:
        all_safe_proj = all(safety.get(k, True) is False for k in required_safety_keys)
        if not all_safe_proj:
            recorder.add("ph24_project_safe_fail", "fail", "Phase 24 safety flags indicate execution was performed")
        else:
            recorder.add("ph24_project_safe_pass", "pass", "All Phase 24 safety flags indicate no execution")




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 24 — Multi-Project Agent Planning Board (aggregation only).",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Restrict to a single registered project_id.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(SUGGESTED_OUTPUT_DIR),
        help=f"Output directory for planning board artifacts (default: {SUGGESTED_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        default=False,
        help="Include archived features in the planning board.",
    )
    parser.add_argument(
        "--fail-on-missing-artifacts",
        action="store_true",
        default=False,
        help="Exit with non-zero code if any feature is missing required artifacts.",
    )

    args = parser.parse_args()

    # Load project config
    projects_cfg = load_projects_config()
    all_projects = projects_cfg.get("projects", {})

    if not isinstance(all_projects, dict):
        print("Error: configs/projects.json has invalid shape (expected 'projects' object).", file=sys.stderr)
        sys.exit(1)

    # Filter to requested project or all enabled projects
    target_project_ids = []
    for pid in sorted(all_projects.keys()):
        proj_cfg = all_projects[pid]
        if not isinstance(proj_cfg, dict):
            continue
        if args.project_id and pid != args.project_id:
            continue
        if not proj_cfg.get("enabled", True):
            continue
        target_project_ids.append(pid)

    if not target_project_ids:
        print(f"Error: no enabled projects found. (filtered to: {args.project_id or 'all'})", file=sys.stderr)
        sys.exit(1)

    # Build global feature queue
    all_features, projects_scanned = build_global_feature_queue(
        projects_cfg, include_archived=args.include_archived
    )

    # Filter if single project requested
    if args.project_id:
        all_features = [f for f in all_features if f["project_id"] == args.project_id]
        projects_scanned = [args.project_id]

    # Sort features
    sorted_features = sort_features(all_features)

    # Build per-project status
    project_statuses = build_project_status(sorted_features, projects_cfg)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    created_utc = utc_now()

    # Build safety summary (always all-false for planning board)
    safety_summary = {
        "source_writes_performed": False,
        "openhands_executed": False,
        "coder_task_executed": False,
        "apply_performed": False,
        "commit_performed": False,
        "push_performed": False,
        "merge_performed": False,
        "pr_created": False,
    }

    # Write GLOBAL_FEATURE_QUEUE.json
    global_queue = {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "created_utc": created_utc,
        "projects_scanned": projects_scanned,
        "total_features": len(sorted_features),
        "features": sorted_features,
        "safety_summary": safety_summary,
    }

    global_queue_path = output_dir / "GLOBAL_FEATURE_QUEUE.json"
    write_json(global_queue_path, global_queue)

    # Write PROJECT_FEATURE_STATUS.json
    project_status = {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "created_utc": created_utc,
        "projects": project_statuses,
        "safety_summary": safety_summary,
    }

    project_status_path = output_dir / "PROJECT_FEATURE_STATUS.json"
    write_json(project_status_path, project_status)

    # Write AGENT_MANAGER_PLANNING_BOARD.md
    markdown_board = build_markdown_board(sorted_features, project_statuses, created_utc)
    board_md_path = output_dir / "AGENT_MANAGER_PLANNING_BOARD.md"
    board_md_path.write_text(markdown_board)

    # Print summary
    total = len(sorted_features)
    blocked_count = sum(1 for f in sorted_features if f.get("blocked"))
    review_ready = sum(1 for f in sorted_features if f.get("feature_status") == "ready_for_human_review")
    arch_ready = sum(1 for f in sorted_features if f.get("feature_status") == "architecture_ready")
    brief_only = sum(1 for f in sorted_features if f.get("feature_status") == "brief_only")

    print(f"Planning board generated ({created_utc})")
    print(f"  Projects scanned : {projects_scanned}")
    print(f"  Total features   : {total}")
    print(f"  Review ready     : {review_ready}")
    print(f"  Arch. ready      : {arch_ready}")
    print(f"  Brief only       : {brief_only}")
    print(f"  Blocked          : {blocked_count}")
    print()
    print("Artifact paths:")
    print(f"  GLOBAL_FEATURE_QUEUE.json   : {global_queue_path}")
    print(f"  PROJECT_FEATURE_STATUS.json : {project_status_path}")
    print(f"  AGENT_MANAGER_PLANNING_BOARD.md : {board_md_path}")

    # Fail-on-missing-artifacts check
    if args.fail_on_missing_artifacts:
        missing_features = [f for f in sorted_features
                           if not f["has_architecture_proposal"] or not f["has_manager_objective_plan"]]
        if missing_features:
            print(f"\nFail: {len(missing_features)} feature(s) missing required artifacts:", file=sys.stderr)
            for mf in missing_features:
                parts = []
                if not mf.get("has_feature_brief", False):
                    parts.append("feature brief")
                if not mf.get("has_architecture_proposal", False):
                    parts.append("architecture proposal")
                if not mf.get("has_manager_objective_plan", False):
                    parts.append("manager objective plan")
                print(f"  [{mf['project_id']}] {mf['feature_id']}: missing {', '.join(parts)}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
