from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import prepare_human_approval_packet
from scripts import validate_agent_run


class HumanApprovalPacketTests(unittest.TestCase):
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
        objective = {
            "id": "phase17_human_approval_draft_pr_support",
            "priority": 1,
            "status": "active",
            "phase": "Phase 17",
            "write_capable": False,
            "description": "Prepare human approval packet and draft PR text only.",
        }
        (state_dir / "WEEKLY_PLAN.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )
        (state_dir / "OBJECTIVE_BACKLOG.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )

        run_root = root / "runs" / project_id
        self.write_latest(run_root, "latest_validation", "validation_20260605T000000Z", "VALIDATION_REPORT.json", {"status": "pass", "run_dir": "validation"})
        self.write_latest(run_root, "latest_review_agents", "review_agents_20260605T000000Z", "REVIEW_AGENTS_SUMMARY.json", {"status": "warn", "run_dir": "review"})
        self.write_latest(run_root, "latest_model_routing", "model_routing_20260605T000000Z", "MODEL_ROUTING_SUMMARY.json", {"status": "pass", "run_dir": "routing", "safety": {"max_code_writing_tasks": 0}})
        self.write_latest(run_root, "latest_nightly_window", "nightly_window_20260605T000000Z", "NIGHTLY_WINDOW_MANIFEST.json", {"status": "pass", "run_dir": "nightly"})
        (run_root / "latest_nightly_window" / "NIGHTLY_SAFETY_STATUS.json").write_text(
            json.dumps({"status": "pass", "max_code_writing_tasks": 0}) + "\n"
        )
        self.write_latest(run_root, "latest_runner_v0", "runner_v0_20260605T000000Z", "ACTIVE_OBJECTIVE.json", {"objective": objective})
        self.write_latest(run_root, "latest_manager_plan", "manager_plan_20260605T000000Z", "MANAGER_DECISION.json", {"selected_objective": objective})
        self.write_latest(run_root, "latest_morning_report", "morning_report_20260605T000000Z", "MORNING_REPORT.json", {"status": "pass"})
        self.write_latest(run_root, "latest_langgraph_v0", "langgraph_v0_20260605T000000Z", "LANGGRAPH_RUN_MANIFEST.json", {"status": "pass"})
        return tmp, root, project_id

    def write_latest(self, run_root: Path, pointer_name: str, dir_name: str, filename: str, data: dict) -> None:
        target = run_root / dir_name
        target.mkdir(parents=True, exist_ok=True)
        (target / filename).write_text(json.dumps(data) + "\n")
        pointer = run_root / pointer_name
        if pointer.exists() or pointer.is_symlink():
            pointer.unlink()
        pointer.symlink_to(target, target_is_directory=True)

    def generate_sample(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict]:
        tmp, root, project_id = self.make_sample_root()
        old_root = prepare_human_approval_packet.ROOT
        prepare_human_approval_packet.ROOT = root
        try:
            with mock.patch.object(prepare_human_approval_packet.subprocess, "run") as mocked_run:
                mocked_run.return_value = subprocess.CompletedProcess(["git", "status", "--short"], 0, "", "")
                summary = prepare_human_approval_packet.generate(project_id, "20260605T010203Z")
                calls = [call.args[0] for call in mocked_run.call_args_list]
        finally:
            prepare_human_approval_packet.ROOT = old_root
        self.assertEqual(calls, [["git", "status", "--short"]])
        return tmp, root, project_id, summary

    def test_approval_packet_json_shape_is_valid(self) -> None:
        tmp, root, project_id, summary = self.generate_sample()
        with tmp:
            run_dir = root / "runs" / project_id / "latest_human_approval"
            packet = json.loads((run_dir / "APPROVAL_PACKET.json").read_text())
            self.assertEqual(packet["schema_version"], 1)
            self.assertEqual(packet["project_id"], project_id)
            self.assertEqual(packet["generated_by"], "deterministic_human_approval_scaffold")
            self.assertEqual(packet["selected_objective"]["id"], "phase17_human_approval_draft_pr_support")
            self.assertEqual(packet["latest_validation_status"], "pass")
            self.assertEqual(packet["recommended_human_decision"], "accept")
            self.assertTrue(packet["no_merge_push_or_pr_created"])
            self.assertEqual(summary["recommended_human_decision"], "accept")

    def test_human_decision_template_defaults_deny_capabilities(self) -> None:
        tmp, root, project_id, _summary = self.generate_sample()
        with tmp:
            template = json.loads((root / "runs" / project_id / "latest_human_approval" / "HUMAN_DECISION_TEMPLATE.json").read_text())
            self.assertFalse(template["approved_for_source_writes"])
            self.assertFalse(template["approved_for_model_calls"])
            self.assertFalse(template["approved_for_openhands"])
            self.assertFalse(template["approved_for_next_phase"])
            self.assertEqual(template["decision"], "hold")

    def test_pr_command_is_text_only_and_no_gh_executes(self) -> None:
        tmp, root, project_id, _summary = self.generate_sample()
        with tmp:
            plan = (root / "runs" / project_id / "latest_human_approval" / "DRAFT_PR_PLAN.md").read_text()
            self.assertIn("gh pr create --draft", plan)
            self.assertIn("No GitHub command was executed", plan)

    def test_validation_accepts_latest_human_approval_artifacts(self) -> None:
        tmp, root, project_id, _summary = self.generate_sample()
        with tmp:
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_human_approval_artifacts(
                recorder,
                (root / "runs" / project_id / "latest_human_approval").resolve(),
            )
            self.assertEqual(recorder.failures(), [])

    def test_generic_non_thomson_project_path_works_for_helper_logic(self) -> None:
        tmp, root, project_id = self.make_sample_root()
        with tmp:
            old_root = prepare_human_approval_packet.ROOT
            prepare_human_approval_packet.ROOT = root
            try:
                project = prepare_human_approval_packet.load_project(project_id)
                state_dir = prepare_human_approval_packet.project_state_dir(project)
            finally:
                prepare_human_approval_packet.ROOT = old_root
            self.assertEqual(state_dir, root / "sample_repo" / ".agent_manager")


if __name__ == "__main__":
    unittest.main()
