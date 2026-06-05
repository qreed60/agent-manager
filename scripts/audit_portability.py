#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "runs", "worktrees", "tmp", "__pycache__", ".pytest_cache"}
PROJECT_PATTERNS = [
    "thomsonlint",
    "ThomsonLint",
    "/mnt/projects/ThomsonLint",
    "agent-manager-project-state",
]
GENERATED_OBJECTIVE_PATTERNS = ["review_phase11_morning_report"]
PHASE_PREFIXES = ("phase9_", "phase10_", "phase11_", "phase12_", "phase13_", "phase14_", "phase15_", "phase16_")
CATEGORIES = [
    "allowed_project_config",
    "allowed_project_adapter",
    "allowed_docs_example",
    "allowed_phase_label",
    "questionable_core_coupling",
    "blocking_core_coupling",
]


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS for part in relative_parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def line_matches(text: str, patterns: list[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        found = [pattern for pattern in patterns if pattern in line]
        if found:
            matches.append({"line": line_no, "patterns": found, "text": line.strip()})
    return matches


def classify(path: Path, patterns: list[str], line_text: str) -> str:
    rel = path.as_posix()

    if rel == "configs/projects.json":
        return "allowed_project_config"
    if rel in {"agent_manager/adapters/thomsonlint.py", "agent_manager/adapters/registry.py"}:
        return "allowed_project_adapter"
    if rel.startswith("docs/") and rel.endswith(".md"):
        return "allowed_docs_example"
    if rel in {"scripts/audit_portability.py", "tests/test_portability.py"}:
        return "allowed_phase_label"

    if any(pattern.startswith(PHASE_PREFIXES) for pattern in patterns):
        return "allowed_phase_label"

    if "review_phase11_morning_report" in patterns:
        return "blocking_core_coupling"

    if rel == "scripts/phase2_smoke.sh" and ("${PROJECT_ID}" in line_text or "AGENT_MANAGER_PROJECT_ID" in line_text):
        return "questionable_core_coupling"

    if rel.startswith("tests/"):
        return "questionable_core_coupling"
    if rel.startswith("scripts/") or rel.startswith("agent_manager/"):
        return "blocking_core_coupling"

    return "questionable_core_coupling"


def audit(root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    patterns = PROJECT_PATTERNS + GENERATED_OBJECTIVE_PATTERNS

    for path in iter_files(root):
        text = read_text(path)
        if text is None:
            continue
        rel_path = path.relative_to(root)

        for match in line_matches(text, patterns):
            category = classify(rel_path, match["patterns"], match["text"])
            findings.append(
                {
                    "category": category,
                    "path": rel_path.as_posix(),
                    "line": match["line"],
                    "patterns": match["patterns"],
                    "text": match["text"],
                }
            )

        phase_matches = line_matches(text, list(PHASE_PREFIXES))
        for match in phase_matches:
            if any(item["path"] == rel_path.as_posix() and item["line"] == match["line"] for item in findings):
                continue
            findings.append(
                {
                    "category": "allowed_phase_label",
                    "path": rel_path.as_posix(),
                    "line": match["line"],
                    "patterns": match["patterns"],
                    "text": match["text"],
                }
            )

    counts = {category: 0 for category in CATEGORIES}
    for finding in findings:
        counts[finding["category"]] += 1

    return {
        "schema_version": 1,
        "root": str(root),
        "ignored_dirs": sorted(IGNORED_DIRS),
        "patterns": {
            "project_assumptions": PROJECT_PATTERNS,
            "generated_objective_assumptions": GENERATED_OBJECTIVE_PATTERNS,
            "phase_prefixes_informational": list(PHASE_PREFIXES),
        },
        "counts": counts,
        "findings": findings,
        "status": "fail" if counts["blocking_core_coupling"] else "pass",
    }


def print_text_report(report: dict[str, Any]) -> None:
    print("Portability Audit")
    print(f"Root: {report['root']}")
    print(f"Status: {report['status']}")
    print("")
    print("Counts:")
    for category in CATEGORIES:
        print(f"  {category}: {report['counts'][category]}")
    print("")

    for category in CATEGORIES:
        items = [finding for finding in report["findings"] if finding["category"] == category]
        if not items:
            continue
        print(category)
        for item in items:
            patterns = ", ".join(item["patterns"])
            print(f"  - {item['path']}:{item['line']} [{patterns}] {item['text']}")
        print("")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit central repo portability assumptions.")
    parser.add_argument("--json", action="store_true", help="Write machine-readable audit output.")
    args = parser.parse_args()

    report = audit(ROOT)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text_report(report)

    if report["counts"]["blocking_core_coupling"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
