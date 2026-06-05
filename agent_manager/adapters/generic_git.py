from __future__ import annotations

from agent_manager.adapters.base import ProjectAdapter


class GenericGitAdapter(ProjectAdapter):
    adapter_name = "generic_git"

    def collect_metrics(self) -> dict:
        status = self.status()
        return {
            "schema_version": 1,
            "project_id": self.project.project_id,
            "adapter": self.adapter_name,
            "repo_exists": status.repo_exists,
            "is_git_repo": status.is_git_repo,
            "current_branch": status.current_branch,
            "head_commit": status.head_commit,
            "metrics_status": "basic_git_status_only",
        }

    def validation_plan(self) -> dict:
        return {
            "schema_version": 1,
            "project_id": self.project.project_id,
            "adapter": self.adapter_name,
            "checks": [
                "repo_path_exists",
                "repo_path_is_git_work_tree",
                "current_branch_available",
                "head_commit_available",
            ],
            "validation_status": "basic_git_status_only",
        }
