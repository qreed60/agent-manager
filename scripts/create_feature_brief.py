#!/usr/bin/env python3
"""Phase 21 — Feature Brief Intake and Queue (intake only).

Creates deterministic feature brief artifacts (JSON + Markdown) and updates a
per-project feature queue. No model calls, no OpenHands execution, no source
writes to target project repos.

Usage example::

    python3 scripts/create_feature_brief.py <project_id> \\
      --title "Feature intake system" \\
      --goal "Let me define high-level features and have agents plan them" \\
      --behavior "Store structured briefs that later agents can consume" \\
      --must "Support multiple projects" \\
      --must "Generate JSON and Markdown artifacts" \\
      --nice "Support constraints and out-of-scope fields" \\
      --constraint "No OpenHands execution in Phase 21" \\
      --out-of-scope "Architecture-agent design generation" \\
      --risk-level low \\
      --target-project-area "agent planning" \\
      --human-priority 1

"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase21_feature_brief_intake"
VALID_STATUSES = frozenset({"brief_only", "needs_clarification", "ready_for_architecture", "blocked", "archived"})
VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})
REQUIRED_FIELDS = (
    "schema_version",
    "generated_by",
    "created_utc",
    "project_id",
    "feature_id",
    "title",
    "high_level_goal",
    "desired_behavior",
    "must_have_requirements",
    "risk_level",
    "target_project_area",
    "human_priority",
    "status",
)

FEATURE_BRIEF_SCHEMA = ROOT / "schemas" / "feature_brief.schema.json"
FEATURE_QUEUE_SCHEMA = ROOT / "schemas" / "feature_queue.schema.json"


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


def slug_from_title(title: str) -> str:
    """Generate a stable slug from a title for use as feature_id suffix."""
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "untitled"
    return f"feat_{slug}"


def validate_project_id(project_id: str, recorder: list[tuple[str, bool]]) -> dict[str, Any] | None:
    """Validate project_id against configs/projects.json. Returns project config or None."""
    config_path = ROOT / "configs" / "projects.json"
    data = load_json(config_path)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        recorder.append(("project_config_shape", False))
        return None
    project = projects.get(project_id)
    if not isinstance(project, dict):
        recorder.append(("unknown_project_id", False))
        return None
    recorder.append(("valid_project_id", True))
    return project


def load_schema(path: Path) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except FileNotFoundError:
        return None


def validate_against_schema(data: dict[str, Any], schema_path: Path) -> tuple[bool, list[str]]:
    """Lightweight schema validation (no external deps)."""
    errors: list[str] = []
    schema = load_schema(schema_path)
    if schema is None:
        return True, errors  # no schema file to validate against

    required = schema.get("required", [])
    for field in required:
        if field not in data:
            errors.append(f"missing required field: {field}")

    properties = schema.get("properties", {})
    for key, prop_schema in properties.items():
        if key not in data:
            continue
        value = data[key]
        enum_vals = prop_schema.get("enum")
        if enum_vals is not None and value not in enum_vals:
            errors.append(f"field {key!r} must be one of {enum_vals}; got {value!r}")

    type_hint = prop_schema.get("type")
    if type_hint == "integer" and key in data:
        if not isinstance(data[key], int):
            errors.append(f"field {key!r} must be integer; got {type(data[key]).__name__}")

    type_hint = prop_schema.get("type")
    if type_hint == "string" and key in data:
        min_len = prop_schema.get("minLength")
        max_len = prop_schema.get("maxLength")
        pattern = prop_schema.get("pattern")
        if min_len is not None and len(data[key]) < min_len:
            errors.append(f"field {key!r} length must be >= {min_len}")
        if max_len is not None and len(data[key]) > max_len:
            errors.append(f"field {key!r} length must be <= {max_len}")
        if pattern is not None and not re.search(pattern, data[key]):
            errors.append(f"field {key!r} does not match pattern {pattern!r}")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def create_feature_brief(
    project_id: str,
    title: str,
    goal: str,
    behavior: str,
    must_haves: list[str],
    nice_to_haves: list[str] | None = None,
    constraints: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    risk_level: str = "medium",
    target_project_area: str = "",
    human_priority: int = 3,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Create a feature brief and update the per-project queue.

    Returns (brief_data, queue_entry, brief_dir).
    Raises SystemExit on validation failure.
    """
    validation: list[tuple[str, bool]] = []

    # Validate project_id
    project = validate_project_id(project_id, validation)
    if project is None:
        bad = [msg for msg, ok in validation if not ok]
        raise SystemExit(f"Feature brief creation rejected: {bad}")

    # Validate required fields
    if not title or not title.strip():
        raise SystemExit("Feature brief creation rejected: --title is required and must be non-empty")
    if not goal or not goal.strip():
        raise SystemExit("Feature brief creation rejected: --goal (--high-level-goal) is required and must be non-empty")
    if not behavior or not behavior.strip():
        raise SystemExit("Feature brief creation rejected: --behavior (--desired-behavior) is required and must be non-empty")

    # Validate risk_level
    if risk_level not in VALID_RISK_LEVELS:
        raise SystemExit(f"Feature brief creation rejected: --risk-level must be one of {sorted(VALID_RISK_LEVELS)}; got {risk_level!r}")

    feature_id = slug_from_title(title)
    created_utc = utc_now()

    brief_data = {
        "schema_version": 1,
        "generated_by": GENERATED_BY,
        "created_utc": created_utc,
        "project_id": project_id,
        "feature_id": feature_id,
        "title": title.strip(),
        "high_level_goal": goal.strip(),
        "desired_behavior": behavior.strip(),
        "must_have_requirements": must_haves,
        "nice_to_have_requirements": nice_to_haves or [],
        "constraints": constraints or [],
        "out_of_scope": out_of_scope or [],
        "risk_level": risk_level,
        "target_project_area": target_project_area.strip() if target_project_area else "",
        "human_priority": human_priority,
        "status": "brief_only",
    }

    # Validate against schema
    schema_ok, schema_errors = validate_against_schema(brief_data, FEATURE_BRIEF_SCHEMA)
    if not schema_ok:
        raise SystemExit(f"Feature brief rejected by schema validation: {schema_errors}")

    # Write brief artifacts
    brief_dir = ROOT / "runs" / project_id / "feature_briefs" / feature_id
    write_json(brief_dir / "FEATURE_BRIEF.json", brief_data)
    (brief_dir / "FEATURE_BRIEF.md").write_text(build_markdown_brief(brief_data))

    # Update or create the per-project queue
    queue_path = ROOT / "runs" / project_id / "feature_queue" / "FEATURE_QUEUE.json"
    queue: dict[str, Any] | None = None
    if queue_path.exists():
        queue = load_json(queue_path)
        if not isinstance(queue, dict):
            queue = None

    if queue is None or queue.get("project_id") != project_id:
        queue = {
            "schema_version": 1,
            "generated_by": GENERATED_BY,
            "created_utc": utc_now(),
            "project_id": project_id,
            "features": [],
        }

    # Check for duplicate feature_id (same slug) — update if exists
    existing_idx = None
    for idx, feat in enumerate(queue.get("features", [])):
        if isinstance(feat, dict) and feat.get("feature_id") == feature_id:
            existing_idx = idx
            break

    brief_relative_path = f"runs/{project_id}/feature_briefs/{feature_id}"
    queue_entry = {
        "feature_id": feature_id,
        "title": brief_data["title"],
        "status": brief_data["status"],
        "created_utc": created_utc,
        "brief_path": brief_relative_path,
    }

    if existing_idx is not None:
        queue["features"][existing_idx] = queue_entry
    else:
        queue["features"].append(queue_entry)

    queue["created_utc"] = utc_now()
    write_json(queue_path, queue)

    return brief_data, queue_entry, brief_dir


def build_markdown_brief(data: dict[str, Any]) -> str:
    """Build a Markdown summary of the feature brief."""
    lines = [
        f"# Feature Brief: {data['title']}",
        "",
        f"- **Feature ID**: {data['feature_id']}",
        f"- **Project**: {data['project_id']}",
        f"- **Status**: {data['status']}",
        f"- **Risk Level**: {data['risk_level']}",
        f"- **Human Priority**: {data['human_priority']}",
        f"- **Target Area**: {data.get('target_project_area', '')}",
        f"- **Created UTC**: {data['created_utc']}",
        f"- **Generated By**: {data['generated_by']}",
        "",
        "## High-Level Goal",
        "",
        data["high_level_goal"],
        "",
        "## Desired Behavior",
        "",
        data["desired_behavior"],
        "",
    ]

    if data.get("must_have_requirements"):
        lines.extend(["## Must-Have Requirements", ""])
        for req in data["must_have_requirements"]:
            lines.append(f"- {req}")
        lines.append("")

    if data.get("nice_to_have_requirements"):
        lines.extend(["## Nice-to-Have Requirements", ""])
        for req in data["nice_to_have_requirements"]:
            lines.append(f"- {req}")
        lines.append("")

    if data.get("constraints"):
        lines.extend(["## Constraints", ""])
        for c in data["constraints"]:
            lines.append(f"- {c}")
        lines.append("")

    if data.get("out_of_scope"):
        lines.extend(["## Out of Scope", ""])
        for item in data["out_of_scope"]:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_repeatable_args(args: list[str], flag: str) -> list[str]:
    """Parse repeated --flag value arguments from the arg list."""
    results: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == flag and i + 1 < len(args):
            results.append(args[i + 1])
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 21 — Create a deterministic feature brief and update the project queue.",
    )
    parser.add_argument("project_id", help="Registered project identifier from configs/projects.json.")

    # Required fields
    parser.add_argument("--title", required=True, help="Short descriptive title for the feature.")
    parser.add_argument("--goal", "--high-level-goal", dest="high_level_goal", required=True, help="High-level goal statement.")
    parser.add_argument("--behavior", "--desired-behavior", dest="desired_behavior", required=True, help="Desired behavior description.")

    # Repeatable fields
    parser.add_argument("--must", action="append", default=[], dest="must_haves", help="Must-have requirement (repeatable).")
    parser.add_argument("--nice", action="append", default=[], dest="nice_to_haves", help="Nice-to-have requirement (repeatable).")
    parser.add_argument("--constraint", action="append", default=[], help="Constraint (repeatable).")
    parser.add_argument("--out-of-scope", "--out_of_scope", action="append", default=[], dest="out_of_scope", help="Out-of-scope item (repeatable).")

    # Optional single-value fields
    parser.add_argument("--risk-level", default="medium", choices=["low", "medium", "high"], help="Risk level (default: medium).")
    parser.add_argument("--target-project-area", "--target_project_area", dest="target_project_area", default="", help="Target project area.")
    parser.add_argument("--human-priority", "--human_priority", type=int, default=3, help="Human priority score 1-5 (default: 3).")

    args = parser.parse_args()

    try:
        brief_data, queue_entry, brief_dir = create_feature_brief(
            project_id=args.project_id,
            title=args.title,
            goal=args.high_level_goal,
            behavior=args.desired_behavior,
            must_haves=args.must_haves,
            nice_to_haves=args.nice_to_haves if args.nice_to_haves else None,
            constraints=args.constraint if args.constraint else None,
            out_of_scope=args.out_of_scope if args.out_of_scope else None,
            risk_level=args.risk_level,
            target_project_area=args.target_project_area,
            human_priority=args.human_priority,
        )
    except SystemExit as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise

    print(f"Feature brief created for project '{args.project_id}'")
    print(f"  Feature ID : {queue_entry['feature_id']}")
    print(f"  Title      : {queue_entry['title']}")
    print(f"  Status     : {queue_entry['status']}")
    print(f"  Risk Level : {brief_data['risk_level']}")
    print(f"  Priority   : {brief_data['human_priority']}")
    print(f"  Brief dir  : {brief_dir}")
    print(f"  Queue file : {(ROOT / 'runs' / args.project_id / 'feature_queue' / 'FEATURE_QUEUE.json')}")


if __name__ == "__main__":
    main()
