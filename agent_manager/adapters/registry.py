from __future__ import annotations

from agent_manager.config import ProjectConfig
from agent_manager.errors import AdapterError
from agent_manager.adapters.base import ProjectAdapter
from agent_manager.adapters.thomsonlint import ThomsonLintAdapter


ADAPTERS: dict[str, type[ProjectAdapter]] = {
    "thomsonlint": ThomsonLintAdapter,
}


def get_adapter(project: ProjectConfig) -> ProjectAdapter:
    adapter_cls = ADAPTERS.get(project.validation_adapter)
    if adapter_cls is None:
        known = ", ".join(sorted(ADAPTERS)) or "<none>"
        raise AdapterError(
            f"Unknown adapter {project.validation_adapter!r} for project "
            f"{project.project_id!r}. Known adapters: {known}"
        )
    return adapter_cls(project)
