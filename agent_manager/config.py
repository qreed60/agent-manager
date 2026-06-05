from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from .errors import ProjectConfigError


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    name: str
    repo_path: Path
    project_type: str
    state_mode: str
    project_state_dir: str | None
    server_state_dir: Path
    worktree_root: Path
    default_branch: str
    validation_adapter: str
    enabled: bool

    @property
    def project_state_path(self) -> Path | None:
        if not self.project_state_dir:
            return None
        return self.repo_path / self.project_state_dir


@dataclass(frozen=True)
class AgentManagerConfig:
    root: Path
    projects: dict[str, ProjectConfig]


def load_config(root: Path | None = None) -> AgentManagerConfig:
    root = root or Path.home() / "agent-manager"
    config_path = root / "configs" / "projects.json"

    if not config_path.exists():
        raise ProjectConfigError(f"Missing project registry: {config_path}")

    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        raise ProjectConfigError(f"Invalid JSON in {config_path}: {exc}") from exc

    if raw.get("schema_version") != 1:
        raise ProjectConfigError("Unsupported projects.json schema_version")

    projects_raw = raw.get("projects")
    if not isinstance(projects_raw, dict):
        raise ProjectConfigError("projects.json must contain object field: projects")

    projects: dict[str, ProjectConfig] = {}

    for project_id, item in projects_raw.items():
        required = [
            "name",
            "repo_path",
            "project_type",
            "state_mode",
            "server_state_dir",
            "worktree_root",
            "default_branch",
            "validation_adapter",
            "enabled",
        ]
        missing = [key for key in required if key not in item]
        if missing:
            raise ProjectConfigError(f"Project {project_id} missing required fields: {missing}")

        projects[project_id] = ProjectConfig(
            project_id=project_id,
            name=item["name"],
            repo_path=Path(item["repo_path"]).expanduser(),
            project_type=item["project_type"],
            state_mode=item["state_mode"],
            project_state_dir=item.get("project_state_dir"),
            server_state_dir=root / item["server_state_dir"],
            worktree_root=root / item["worktree_root"],
            default_branch=item["default_branch"],
            validation_adapter=item["validation_adapter"],
            enabled=bool(item["enabled"]),
        )

    return AgentManagerConfig(root=root, projects=projects)


def get_project(project_id: str, root: Path | None = None) -> ProjectConfig:
    config = load_config(root)
    try:
        return config.projects[project_id]
    except KeyError as exc:
        known = ", ".join(sorted(config.projects)) or "<none>"
        raise ProjectConfigError(f"Unknown project_id: {project_id}. Known projects: {known}") from exc
