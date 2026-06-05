from __future__ import annotations

from pathlib import Path

from agent_manager.adapters.base import ProjectAdapter


class ThomsonLintAdapter(ProjectAdapter):
    adapter_name = "thomsonlint"

    def likely_paths(self) -> dict[str, bool]:
        repo = self.project.repo_path
        candidates = {
            "PLAN.md": repo / "PLAN.md",
            "OPENHANDS_REVIEW.md": repo / "OPENHANDS_REVIEW.md",
            "scripts": repo / "scripts",
            "tests": repo / "tests",
            "pyproject.toml": repo / "pyproject.toml",
        }
        return {name: path.exists() for name, path in candidates.items()}

    def collect_metrics(self) -> dict:
        status = self.status()
        return {
            "schema_version": 1,
            "project_id": self.project.project_id,
            "adapter": self.adapter_name,
            "implemented_phase": "Phase 2 stub",
            "repo_exists": status.repo_exists,
            "is_git_repo": status.is_git_repo,
            "current_branch": status.current_branch,
            "head_commit": status.head_commit,
            "likely_paths": self.likely_paths() if status.repo_exists else {},
            "metrics_status": "stub_only",
            "message": "Full ThomsonLint metrics collection will be implemented in Phase 6."
        }

    def validation_plan(self) -> dict:
        return {
            "schema_version": 1,
            "project_id": self.project.project_id,
            "adapter": self.adapter_name,
            "validation_status": "stub_only",
            "planned_future_checks": [
                "pytest targeted tests",
                "schema validation",
                "phase-driver status",
                "blocker_count",
                "core-write checks",
                "artifact diff checks",
                "changed-file scope checks"
            ]
        }
