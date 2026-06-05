from agent_manager.config import load_config, get_project
from agent_manager.adapters.registry import get_adapter


def test_load_config():
    config = load_config()
    assert "thomsonlint" in config.projects


def test_get_project():
    project = get_project("thomsonlint")
    assert project.project_id == "thomsonlint"
    assert project.validation_adapter == "thomsonlint"


def test_get_adapter():
    project = get_project("thomsonlint")
    adapter = get_adapter(project)
    assert adapter.adapter_name == "thomsonlint"
