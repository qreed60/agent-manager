from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_manager.adapters.generic_git import GenericGitAdapter
from agent_manager.adapters.registry import get_adapter
from agent_manager.config import load_config, get_project
from scripts import audit_portability
from scripts.write_morning_report import build_project_state_proposal


ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_thomsonlint_project_still_loads(self) -> None:
        project = get_project("thomsonlint", ROOT)
        self.assertEqual(project.project_id, "thomsonlint")
        self.assertEqual(project.validation_adapter, "thomsonlint")

    def test_sample_non_thomsonlint_project_config_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "sample_project"
            repo.mkdir()
            (root / "configs").mkdir()
            (root / "configs" / "projects.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "projects": {
                            "sample_project": {
                                "name": "Sample Project",
                                "repo_path": str(repo),
                                "project_type": "git_repo",
                                "state_mode": "central",
                                "project_state_dir": ".agent_manager",
                                "server_state_dir": "runs/sample_project",
                                "worktree_root": "worktrees/sample_project",
                                "default_branch": "main",
                                "validation_adapter": "generic_git",
                                "enabled": True,
                            }
                        },
                    }
                )
                + "\n"
            )

            config = load_config(root)
            project = config.projects["sample_project"]
            self.assertEqual(project.validation_adapter, "generic_git")
            self.assertEqual(project.repo_path, repo)

    def test_generic_git_adapter_instantiates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "sample_project"
            repo.mkdir()
            (root / "configs").mkdir()
            (root / "configs" / "projects.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "projects": {
                            "sample_project": {
                                "name": "Sample Project",
                                "repo_path": str(repo),
                                "project_type": "git_repo",
                                "state_mode": "central",
                                "project_state_dir": ".agent_manager",
                                "server_state_dir": "runs/sample_project",
                                "worktree_root": "worktrees/sample_project",
                                "default_branch": "main",
                                "validation_adapter": "generic_git",
                                "enabled": True,
                            }
                        },
                    }
                )
                + "\n"
            )
            project = get_project("sample_project", root)
            adapter = get_adapter(project)
            self.assertIsInstance(adapter, GenericGitAdapter)
            self.assertEqual(adapter.adapter_name, "generic_git")

    def test_morning_report_next_objective_is_derived(self) -> None:
        proposal = build_project_state_proposal(
            "sample_project",
            "20260605T182202Z",
            {
                "schema_version": 1,
                "project_id": "sample_project",
                "objectives": [{"id": "portable_objective", "status": "active", "write_capable": False}],
            },
            {
                "schema_version": 1,
                "project_id": "sample_project",
                "objectives": [{"id": "portable_objective", "status": "active", "write_capable": False}],
            },
            {"id": "portable_objective", "status": "active", "write_capable": False},
            "accept",
            {"status": "pass"},
            ROOT / "runs" / "sample_project" / "morning_report_test",
        )
        proposed = proposal["proposed_files"][".agent_manager/OBJECTIVE_BACKLOG.json"]
        objective_ids = [item["id"] for item in proposed["objectives"]]
        self.assertIn("review_portable_objective", objective_ids)
        self.assertNotIn("review_phase11_morning_report", objective_ids)

    def test_portability_audit_has_no_blocking_findings(self) -> None:
        report = audit_portability.audit(ROOT)
        self.assertEqual(report["counts"]["blocking_core_coupling"], 0)


if __name__ == "__main__":
    unittest.main()
