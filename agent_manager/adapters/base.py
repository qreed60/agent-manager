from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from agent_manager.config import ProjectConfig


@dataclass
class AdapterStatus:
    project_id: str
    adapter: str
    repo_exists: bool
    is_git_repo: bool
    current_branch: str | None
    head_commit: str | None
    project_state_exists: bool | None
    warnings: list[str]


class ProjectAdapter:
    adapter_name = "base"

    def __init__(self, project: ProjectConfig):
        self.project = project

    def status(self) -> AdapterStatus:
        repo = self.project.repo_path
        warnings: list[str] = []

        repo_exists = repo.exists()
        is_git_repo = (repo / ".git").exists() if repo_exists else False

        if not repo_exists:
            warnings.append(f"Repo path does not exist: {repo}")

        if repo_exists and not is_git_repo:
            warnings.append(f"Repo path exists but is not a git repo: {repo}")

        current_branch = None
        head_commit = None

        if is_git_repo:
            current_branch = self._git(["branch", "--show-current"])
            head_commit = self._git(["rev-parse", "--short", "HEAD"])

        project_state_exists = None
        if self.project.project_state_path is not None:
            project_state_exists = self.project.project_state_path.exists()

        return AdapterStatus(
            project_id=self.project.project_id,
            adapter=self.adapter_name,
            repo_exists=repo_exists,
            is_git_repo=is_git_repo,
            current_branch=current_branch,
            head_commit=head_commit,
            project_state_exists=project_state_exists,
            warnings=warnings,
        )

    def _git(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.project.repo_path,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return result.stdout.strip() or None
        except subprocess.CalledProcessError:
            return None

    def collect_metrics(self) -> dict:
        return {
            "status": "not_implemented",
            "message": "Metrics collection is implemented in a later phase."
        }

    def validation_plan(self) -> dict:
        return {
            "status": "not_implemented",
            "message": "Validation plan is implemented in a later phase."
        }
