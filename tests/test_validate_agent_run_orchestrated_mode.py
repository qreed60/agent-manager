from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import validate_agent_run


class ValidateAgentRunOrchestratedModeTests(unittest.TestCase):
    def write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n")

    def write_latest(self, run_root: Path, latest_name: str, run_name: str, files: dict[str, object | str]) -> Path:
        run_dir = run_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            path = run_dir / filename
            if isinstance(content, str):
                path.write_text(content)
            else:
                self.write_json(path, content)
        pointer = run_root / latest_name
        if pointer.exists() or pointer.is_symlink():
            pointer.unlink()
        pointer.symlink_to(run_dir, target_is_directory=True)
        return run_dir

    def make_run_root_with_broken_orchestrators(self, root: Path, project_id: str = "sample_project") -> Path:
        run_root = root / "runs" / project_id
        self.write_latest(
            run_root,
            "latest",
            "metrics_20260605T000000Z",
            {
                "RUN_METRICS.json": {},
                "UNKNOWN_ANALYSIS.json": {},
                "VALIDATION_SUMMARY.json": {"status": "pass"},
            },
        )
        self.write_latest(
            run_root,
            "latest_runner_v0",
            "runner_v0_20260605T000000Z",
            {
                "ACTIVE_OBJECTIVE.json": {},
                "TASK_GRAPH.json": {},
                "RUN_MANIFEST.json": {"status": "pass"},
                "MORNING_REPORT.md": "runner report\n",
            },
        )
        self.write_latest(
            run_root,
            "latest_manager_plan",
            "manager_plan_20260605T000000Z",
            {
                "MANAGER_CONTEXT.json": {},
                "MANAGER_DECISION.json": {"status": "pass"},
                "MANAGER_PLAN.md": "manager plan\n",
                "NEXT_ACTION.md": "next action\n",
            },
        )
        self.write_latest(
            run_root,
            "latest_coder_worktree",
            "coder_worktree_20260605T000000Z",
            {
                "CODER_TASK_PACKET.json": {},
                "WORKTREE_STATUS.json": {"clean": True},
                "CODER_PROMPT.md": "prompt\n",
                "OPENHANDS_DRY_RUN_COMMANDS.md": "dry-run only\n",
            },
        )
        self.write_latest(
            run_root,
            "latest_morning_report",
            "morning_report_20260605T000000Z",
            {
                "MORNING_REPORT.md": "morning report\n",
                "MORNING_REPORT.json": {"status": "pass"},
                "PLAN_UPDATE_PROPOSAL.json": {},
                "NEXT_OBJECTIVE_RECOMMENDATION.md": "next\n",
            },
        )
        self.write_latest(
            run_root,
            "latest_langgraph_v0",
            "langgraph_v0_20260605T000000Z",
            {
                "LANGGRAPH_RUN_MANIFEST.json": {"status": "fail", "safety": {}},
                "LANGGRAPH_STATE_FINAL.json": {"status": "fail"},
                "LANGGRAPH_NODE_TRACE.json": [{"node": "validate_agent_run", "status": "fail"}],
                "LANGGRAPH_REPORT.md": "failed graph\n",
            },
        )
        self.write_latest(
            run_root,
            "latest_nightly_window",
            "nightly_window_20260605T000000Z",
            {
                "NIGHTLY_WINDOW_MANIFEST.json": {"status": "fail"},
                "NIGHTLY_WINDOW_TIMELINE.json": {"passes": []},
                "NIGHTLY_PASS_SUMMARY.json": {"status": "fail"},
                "NIGHTLY_SAFETY_STATUS.json": {"status": "fail"},
                "MORNING_HANDOFF.md": "failed nightly\n",
            },
        )
        return run_root

    def add_blocking_review_agents(self, run_root: Path, *, blocking_agent: str) -> None:
        review_dir = run_root / "review_agents_20260605T000000Z"
        review_dir.mkdir(parents=True, exist_ok=True)
        agents = [
            "validation_review",
            "sqa_review",
            "security_review",
            "scalability_review",
            "architecture_review",
        ]
        for agent in agents:
            stem = agent.upper()
            self.write_json(
                review_dir / f"{stem}.json",
                {
                    "schema_version": 1,
                    "agent": agent,
                    "project_id": "sample_project",
                    "created_utc": "20260605T000000Z",
                    "run_dir": str(review_dir),
                    "status": "fail" if agent == blocking_agent else "pass",
                    "blocking": agent == blocking_agent,
                    "findings": [],
                    "artifacts_reviewed": [],
                    "generated_by": "deterministic_scaffold",
                },
            )
            (review_dir / f"{stem}.md").write_text(f"{agent}\n")
        self.write_json(
            review_dir / "REVIEW_AGENTS_SUMMARY.json",
            {
                "schema_version": 1,
                "agent": "review_agents_summary",
                "project_id": "sample_project",
                "created_utc": "20260605T000000Z",
                "run_dir": str(review_dir),
                "status": "fail",
                "blocking": True,
                "findings": [],
                "artifacts_reviewed": [],
                "generated_by": "deterministic_scaffold",
                "reports": {
                    agent: {"status": "fail" if agent == blocking_agent else "pass", "blocking": agent == blocking_agent}
                    for agent in agents
                },
            },
        )
        (review_dir / "REVIEW_AGENTS_SUMMARY.md").write_text("summary\n")
        pointer = run_root / "latest_review_agents"
        if pointer.exists() or pointer.is_symlink():
            pointer.unlink()
        pointer.symlink_to(review_dir, target_is_directory=True)

    def validate_run_artifacts(self, root: Path, project_id: str, *, skip: bool) -> validate_agent_run.CheckRecorder:
        old_root = validate_agent_run.ROOT
        validate_agent_run.ROOT = root
        recorder = validate_agent_run.CheckRecorder()
        try:
            with mock.patch.object(validate_agent_run, "validate_systemd_artifacts") as systemd:
                systemd.side_effect = lambda rec: rec.pass_check("systemd_artifacts_mocked", "systemd validation mocked")
                validate_agent_run.validate_run_artifacts(project_id, recorder, skip_orchestrator_artifacts=skip)
        finally:
            validate_agent_run.ROOT = old_root
        return recorder

    def test_standalone_validation_checks_orchestrator_artifacts_strictly_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self.make_run_root_with_broken_orchestrators(root, project_id)

            recorder = self.validate_run_artifacts(root, project_id, skip=False)
            failure_ids = {failure["id"] for failure in recorder.failures()}

            self.assertIn("langgraph_manifest_status", failure_ids)
            self.assertIn("nightly_window_manifest_parse_status", failure_ids)
            self.assertNotIn("latest_langgraph_v0_orchestrated_skip", failure_ids)
            self.assertNotIn("latest_nightly_window_orchestrated_skip", failure_ids)

    def test_orchestrated_validation_skips_only_langgraph_and_nightly_window_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self.make_run_root_with_broken_orchestrators(root, project_id)

            recorder = self.validate_run_artifacts(root, project_id, skip=True)
            check_ids = {check["id"] for check in recorder.checks}
            failure_ids = {failure["id"] for failure in recorder.failures()}

            self.assertIn("latest_langgraph_v0_orchestrated_skip", check_ids)
            self.assertIn("latest_nightly_window_orchestrated_skip", check_ids)
            self.assertNotIn("langgraph_manifest_status", check_ids)
            self.assertNotIn("nightly_window_manifest_parse_status", check_ids)
            self.assertNotIn("run_manifest_parse_status", failure_ids)
            self.assertNotIn("manager_decision_parse_status", failure_ids)
            self.assertEqual(failure_ids, set())

    def test_orchestrated_validation_accepts_stale_review_agents_blocking_only_on_validation_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            run_root = self.make_run_root_with_broken_orchestrators(root, project_id)
            self.add_blocking_review_agents(run_root, blocking_agent="validation_review")

            recorder = self.validate_run_artifacts(root, project_id, skip=True)
            failure_ids = {failure["id"] for failure in recorder.failures()}
            nonblocking_checks = [
                check
                for check in recorder.checks
                if check["id"] == "review_agents_summary_nonblocking"
            ]

            self.assertEqual(failure_ids, set())
            self.assertEqual(nonblocking_checks[0]["status"], "pass")
            self.assertTrue(nonblocking_checks[0]["details"]["accepted_stale_validation_review_blocking"])

    def test_orchestrated_validation_still_fails_real_review_agent_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            run_root = self.make_run_root_with_broken_orchestrators(root, project_id)
            self.add_blocking_review_agents(run_root, blocking_agent="security_review")

            recorder = self.validate_run_artifacts(root, project_id, skip=True)
            failure_ids = {failure["id"] for failure in recorder.failures()}

            self.assertIn("review_agents_summary_nonblocking", failure_ids)


if __name__ == "__main__":
    unittest.main()
