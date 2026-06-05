#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path.home() / "agent-manager"


def fail(msg: str) -> None:
    raise SystemExit(f"collect_project_metrics failed: {msg}")


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def load_project(project_id: str) -> dict:
    data = json.loads((ROOT / "configs" / "projects.json").read_text())
    try:
        return data["projects"][project_id]
    except KeyError:
        fail(f"unknown project_id: {project_id}")


def git_value(repo: Path, args: list[str]) -> str | None:
    r = run(["git", *args], repo)
    return r.stdout.strip() if r.returncode == 0 else None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def list_files(repo: Path) -> list[Path]:
    r = run(["git", "ls-files"], repo)
    if r.returncode != 0:
        fail(r.stderr.strip() or "git ls-files failed")
    return [repo / p for p in r.stdout.splitlines() if p.strip()]


def json_ok(path: Path) -> tuple[bool, str | None]:
    try:
        json.loads(path.read_text())
        return True, None
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    args = ap.parse_args()

    project = load_project(args.project_id)
    repo = Path(project["repo_path"])
    if not repo.exists():
        fail(f"missing repo: {repo}")
    if not (repo / ".git").exists():
        fail(f"not a git repo: {repo}")

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / args.project_id / now
    run_dir.mkdir(parents=True, exist_ok=True)

    files = list_files(repo)
    rels = [str(p.relative_to(repo)) for p in files]

    status_short = git_value(repo, ["status", "--short"]) or ""
    branch = git_value(repo, ["branch", "--show-current"])
    head = git_value(repo, ["rev-parse", "--short", "HEAD"])

    key_paths = [
        "README.md",
        "PLAN.md",
        "OPENHANDS_REVIEW.md",
        "TODO.md",
        "THOMSONLINT_AUDIT_REPORT.md",
        "AGENTS.md",
        "CLAUDE.md",
        ".agent_manager/README.md",
        ".agent_manager/WEEKLY_PLAN.json",
        ".agent_manager/OBJECTIVE_BACKLOG.json",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements.txt",
    ]

    extensions: dict[str, int] = {}
    total_lines = 0
    large_files = []

    for p in files:
        ext = p.suffix.lower() or "<no_ext>"
        extensions[ext] = extensions.get(ext, 0) + 1
        size = p.stat().st_size if p.exists() else 0
        if size > 1_000_000:
            large_files.append({
                "path": str(p.relative_to(repo)),
                "size_bytes": size,
                "sha256": sha256_file(p)
            })
        if p.suffix.lower() in {".py", ".md", ".json", ".sh", ".txt", ".yml", ".yaml"}:
            total_lines += count_lines(p)

    json_checks = {}
    for path in [
        repo / ".agent_manager" / "WEEKLY_PLAN.json",
        repo / ".agent_manager" / "OBJECTIVE_BACKLOG.json",
    ]:
        ok, err = json_ok(path) if path.exists() else (False, "missing")
        json_checks[str(path.relative_to(repo))] = {"ok": ok, "error": err}

    likely_paths = {
        "scripts": (repo / "scripts").is_dir(),
        "tests": (repo / "tests").is_dir(),
        "schemas": (repo / "schemas").is_dir(),
        "input": (repo / "input").is_dir(),
        "datasheets": (repo / "datasheets").is_dir(),
        "docs": (repo / "docs").is_dir(),
        "examples": (repo / "examples").is_dir(),
        "ontology": (repo / "ontology").is_dir(),
    }

    run_metrics = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "repo_path": str(repo),
        "git": {
            "branch": branch,
            "head": head,
            "status_short": status_short.splitlines(),
            "is_clean": status_short.strip() == "",
        },
        "counts": {
            "tracked_files": len(files),
            "estimated_text_lines": total_lines,
            "python_files": sum(1 for r in rels if r.endswith(".py")),
            "test_files": sum(1 for r in rels if r.startswith("tests/")),
            "script_files": sum(1 for r in rels if r.startswith("scripts/")),
            "markdown_files": sum(1 for r in rels if r.endswith(".md")),
            "json_files": sum(1 for r in rels if r.endswith(".json")),
            "shell_files": sum(1 for r in rels if r.endswith(".sh")),
        },
        "extensions": dict(sorted(extensions.items())),
        "key_paths": {p: (repo / p).exists() for p in key_paths},
        "likely_paths": likely_paths,
        "large_files": large_files,
    }

    unknowns = []
    if not run_metrics["git"]["is_clean"]:
        unknowns.append({
            "id": "repo_dirty",
            "severity": "blocker",
            "question": "Why does the target repo have uncommitted changes?",
            "evidence": run_metrics["git"]["status_short"],
        })

    if not (repo / "pyproject.toml").exists():
        unknowns.append({
            "id": "python_project_metadata_missing",
            "severity": "warn",
            "question": "No pyproject.toml found. Is requirements-dev.txt the intended dependency source?",
            "evidence": ["pyproject.toml missing", f"requirements-dev.txt exists: {(repo / 'requirements-dev.txt').exists()}"],
        })

    if not (repo / ".agent_manager").exists():
        unknowns.append({
            "id": "project_state_missing",
            "severity": "blocker",
            "question": "Project-local .agent_manager state is missing.",
            "evidence": [".agent_manager missing"],
        })

    unknown_analysis = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "unknowns": unknowns,
    }

    validation_checks = {
        "repo_exists": repo.exists(),
        "git_repo": (repo / ".git").exists(),
        "git_clean": run_metrics["git"]["is_clean"],
        "project_state_exists": (repo / ".agent_manager").exists(),
        "project_state_json_valid": all(v["ok"] for v in json_checks.values()),
        "no_model_calls": True,
        "no_openhands_execution": True,
        "no_langgraph_execution": True,
        "writes_limited_to_central_run_dir": True,
    }

    validation_summary = {
        "schema_version": 1,
        "project_id": args.project_id,
        "created_utc": now,
        "run_dir": str(run_dir),
        "checks": validation_checks,
        "json_checks": json_checks,
        "status": "pass" if all(validation_checks.values()) else "fail",
        "blocking_failures": [
            k for k, v in validation_checks.items()
            if not v and k in {"repo_exists", "git_repo", "git_clean", "project_state_exists", "project_state_json_valid"}
        ],
    }

    (run_dir / "RUN_METRICS.json").write_text(json.dumps(run_metrics, indent=2) + "\n")
    (run_dir / "UNKNOWN_ANALYSIS.json").write_text(json.dumps(unknown_analysis, indent=2) + "\n")
    (run_dir / "VALIDATION_SUMMARY.json").write_text(json.dumps(validation_summary, indent=2) + "\n")

    latest = ROOT / "runs" / args.project_id / "latest"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir, target_is_directory=True)

    print(f"Metrics collected for {args.project_id}")
    print(f"Run dir: {run_dir}")
    print(f"Status: {validation_summary['status']}")
    if validation_summary["blocking_failures"]:
        print("Blocking failures:")
        for item in validation_summary["blocking_failures"]:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
