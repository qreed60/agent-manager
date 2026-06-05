from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import compile_model_routing_plan
from scripts import validate_agent_run


class ModelRoutingTests(unittest.TestCase):
    def make_sample_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        project_id = "sample_project"
        repo = root / "sample_repo"
        state_dir = repo / ".agent_manager"
        state_dir.mkdir(parents=True)
        (root / "configs").mkdir()
        (root / "configs" / "projects.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": {
                        project_id: {
                            "name": "Sample Project",
                            "repo_path": str(repo),
                            "project_state_dir": ".agent_manager",
                            "server_state_dir": "runs/sample_project",
                            "worktree_root": "worktrees/sample_project",
                            "validation_adapter": "generic_git",
                            "enabled": True,
                        }
                    },
                }
            )
            + "\n"
        )
        (root / "configs" / "model_registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "long_reasoning": {
                            "role": "manager_planner_reviewer",
                            "default_model": "example/long",
                            "write_access": False,
                            "allowed_task_types": ["manager_review"],
                        },
                        "instruct": {
                            "role": "structured_summary_and_classification",
                            "default_model": "example/instruct",
                            "write_access": False,
                            "allowed_task_types": ["classification"],
                        },
                        "vision": {
                            "role": "visual_evidence_extraction",
                            "default_model": None,
                            "write_access": False,
                            "allowed_task_types": ["visual_observation"],
                        },
                        "coding_agent": {
                            "role": "repo_modification",
                            "default_model": "example/coding",
                            "write_access": True,
                            "allowed_task_types": ["bounded_implementation"],
                        },
                    },
                }
            )
            + "\n"
        )
        (root / "configs" / "routing_rules.md").write_text("# Rules\n\nNo model calls by default.\n")
        objective = {
            "id": "phase15_multi_model_routing",
            "priority": 1,
            "status": "active",
            "phase": "Phase 15",
            "write_capable": False,
        }
        (state_dir / "WEEKLY_PLAN.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )
        (state_dir / "OBJECTIVE_BACKLOG.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )
        return tmp, root, project_id

    def generate_sample(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict]:
        tmp, root, project_id = self.make_sample_root()
        old_root = compile_model_routing_plan.ROOT
        compile_model_routing_plan.ROOT = root
        try:
            summary = compile_model_routing_plan.generate(project_id, "20260605T010203Z")
        finally:
            compile_model_routing_plan.ROOT = old_root
        return tmp, root, project_id, summary

    def test_model_routing_plan_json_shape_is_valid(self) -> None:
        tmp, root, project_id, summary = self.generate_sample()
        with tmp:
            run_dir = root / "runs" / project_id / "latest_model_routing"
            plan = json.loads((run_dir / "MODEL_ROUTING_PLAN.json").read_text())
            self.assertEqual(plan["schema_version"], 1)
            self.assertEqual(plan["project_id"], project_id)
            self.assertEqual(plan["status"], "pass")
            self.assertEqual(plan["generated_by"], "deterministic_model_routing_scaffold")
            self.assertEqual(plan["selected_objective"]["id"], "phase15_multi_model_routing")
            self.assertTrue(plan["safety"]["no_model_calls"])
            self.assertTrue(plan["safety"]["deterministic_validation_authority_preserved"])
            self.assertEqual(summary["assignment_count"], 8)

    def test_task_assignments_include_required_metadata_and_permissions(self) -> None:
        tmp, root, project_id, _summary = self.generate_sample()
        with tmp:
            run_dir = root / "runs" / project_id / "latest_model_routing"
            assignments = json.loads((run_dir / "TASK_MODEL_ASSIGNMENTS.json").read_text())["assignments"]
            self.assertTrue(assignments)
            for item in assignments:
                self.assertIn("role", item)
                self.assertIn("permission", item)
                self.assertIn("model_reference", item)
                self.assertIn("rationale", item)
                self.assertFalse(item["permission"]["model_calls_enabled"])
                self.assertFalse(item["permission"]["openhands_execution_enabled"])

            for item in assignments:
                if item["role"] != "coding_agent":
                    self.assertTrue(item["permission"]["read_only"])
                    self.assertFalse(item["permission"]["write_capable"])

    def test_no_more_than_one_write_capable_assignment_is_allowed(self) -> None:
        assignments = [
            {"assignment_id": "coding_one", "role": "coding_agent", "permission": {"write_capable": True}},
            {"assignment_id": "coding_two", "role": "coding_agent", "permission": {"write_capable": True}},
        ]
        checks = compile_model_routing_plan.validate_assignment_safety(assignments)
        max_one = next(check for check in checks if check["id"] == "max_one_write_capable_assignment")
        self.assertEqual(max_one["status"], "fail")

    def test_non_coding_roles_are_read_only(self) -> None:
        assignments = [
            {"assignment_id": "review", "role": "long_reasoning", "permission": {"write_capable": True}},
        ]
        checks = compile_model_routing_plan.validate_assignment_safety(assignments)
        only_coding = next(check for check in checks if check["id"] == "only_coding_agent_write_capable")
        non_coding = next(check for check in checks if check["id"] == "non_coding_roles_read_only")
        self.assertEqual(only_coding["status"], "fail")
        self.assertEqual(non_coding["status"], "fail")

    def test_validation_accepts_latest_model_routing_artifacts(self) -> None:
        tmp, root, project_id, _summary = self.generate_sample()
        with tmp:
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_model_routing_artifacts(
                recorder,
                (root / "runs" / project_id / "latest_model_routing").resolve(),
            )
            self.assertEqual(recorder.failures(), [])

    def test_generic_non_thomson_project_path_works_for_helper_logic(self) -> None:
        tmp, root, project_id = self.make_sample_root()
        with tmp:
            old_root = compile_model_routing_plan.ROOT
            compile_model_routing_plan.ROOT = root
            try:
                project = compile_model_routing_plan.load_project(project_id)
                state_dir = compile_model_routing_plan.project_state_dir(project)
            finally:
                compile_model_routing_plan.ROOT = old_root
            self.assertEqual(state_dir, root / "sample_repo" / ".agent_manager")


if __name__ == "__main__":
    unittest.main()
