from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_readonly_review_agents
from scripts import validate_agent_run


class ReadonlyReviewAgentsTests(unittest.TestCase):
    def assert_report_shape(self, report: dict, agent: str) -> None:
        for key in (
            "schema_version",
            "agent",
            "project_id",
            "created_utc",
            "run_dir",
            "status",
            "blocking",
            "findings",
            "artifacts_reviewed",
            "generated_by",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["agent"], agent)
        self.assertIn(report["status"], {"pass", "warn", "fail"})
        self.assertIsInstance(report["blocking"], bool)
        self.assertIsInstance(report["findings"], list)
        self.assertIsInstance(report["artifacts_reviewed"], list)
        self.assertEqual(report["generated_by"], "deterministic_scaffold")

    def make_sample_run(self, root: Path, project_id: str) -> Path:
        run_root = root / "runs" / project_id
        (root / "configs").mkdir()
        (root / "configs" / "projects.json").write_text(
            json.dumps({"schema_version": 1, "projects": {project_id: {"repo_path": str(root / "repo")}}}) + "\n"
        )
        (root / "repo").mkdir()

        validation_dir = run_root / "validation_20260605T000000Z"
        morning_dir = run_root / "morning_report_20260605T000000Z"
        langgraph_dir = run_root / "langgraph_v0_20260605T000000Z"
        runner_dir = run_root / "runner_v0_20260605T000000Z"
        manager_dir = run_root / "manager_plan_20260605T000000Z"
        validation_dir.mkdir(parents=True)
        morning_dir.mkdir()
        langgraph_dir.mkdir()
        runner_dir.mkdir()
        manager_dir.mkdir()
        (run_root / "latest_validation").symlink_to(validation_dir, target_is_directory=True)
        (run_root / "latest_morning_report").symlink_to(morning_dir, target_is_directory=True)
        (run_root / "latest_langgraph_v0").symlink_to(langgraph_dir, target_is_directory=True)
        (run_root / "latest_runner_v0").symlink_to(runner_dir, target_is_directory=True)
        (run_root / "latest_manager_plan").symlink_to(manager_dir, target_is_directory=True)

        (validation_dir / "VALIDATION_REPORT.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "created_utc": "20260605T000001Z",
                    "failures": [],
                    "checks": [],
                    "safety": {
                        "no_openhands_execution": True,
                        "no_model_calls": True,
                        "review_agents_read_only": True,
                        "target_project_source_modified": False,
                    },
                }
            )
            + "\n"
        )
        (validation_dir / "VALIDATION_REPORT.md").write_text("Validation runtime completed.\n")
        (morning_dir / "MORNING_REPORT.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "safety_status": {
                        "no_openhands_execution": True,
                        "no_model_calls": True,
                        "auto_merge": False,
                        "auto_push": False,
                        "target_repo_modified_by_default": False,
                    },
                }
            )
            + "\n"
        )
        (morning_dir / "MORNING_REPORT.md").write_text("No large artifact handling threshold reached.\n")
        (langgraph_dir / "LANGGRAPH_RUN_MANIFEST.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "created_utc": "20260605T000000Z",
                    "safety": {
                        "no_openhands_execution": True,
                        "no_model_calls": True,
                        "no_auto_merge": True,
                        "no_auto_push": True,
                        "deterministic_validation_authority_preserved": True,
                    },
                }
            )
            + "\n"
        )
        (langgraph_dir / "LANGGRAPH_STATE_FINAL.json").write_text(json.dumps({"status": "pass"}) + "\n")
        (langgraph_dir / "LANGGRAPH_NODE_TRACE.json").write_text(
            json.dumps([{"node": "validate_agent_run", "status": "pass"}, {"node": "finalize", "status": "pass"}]) + "\n"
        )
        (langgraph_dir / "LANGGRAPH_REPORT.md").write_text("LangGraph runtime completed.\n")
        (runner_dir / "ACTIVE_OBJECTIVE.json").write_text(
            json.dumps(
                {
                    "objective": {
                        "id": "phase14_scalability_architecture_review_agents",
                        "phase": "Phase 14",
                    }
                }
            )
            + "\n"
        )
        (manager_dir / "MANAGER_DECISION.json").write_text(
            json.dumps(
                {
                    "selected_objective_id": "phase14_scalability_architecture_review_agents",
                    "selected_objective": {
                        "id": "phase14_scalability_architecture_review_agents",
                        "phase": "Phase 14",
                    },
                    "safety": {"no_auto_merge": True, "no_auto_push": True},
                }
            )
            + "\n"
        )
        return run_root

    def test_generate_writes_reports_and_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            run_root = self.make_sample_run(root, project_id)

            old_root = run_readonly_review_agents.ROOT
            run_readonly_review_agents.ROOT = root
            try:
                summary = run_readonly_review_agents.generate(project_id, "20260605T010203Z")
            finally:
                run_readonly_review_agents.ROOT = old_root

            latest = run_root / "latest_review_agents"
            self.assertTrue(latest.is_symlink())
            review_dir = latest.resolve()
            self.assertEqual(summary["generated_by"], "deterministic_scaffold")
            self.assertEqual(summary["status"], "warn")
            self.assertFalse(summary["blocking"])
            for name in (
                "VALIDATION_REVIEW.json",
                "VALIDATION_REVIEW.md",
                "SQA_REVIEW.json",
                "SQA_REVIEW.md",
                "SECURITY_REVIEW.json",
                "SECURITY_REVIEW.md",
                "SCALABILITY_REVIEW.json",
                "SCALABILITY_REVIEW.md",
                "ARCHITECTURE_REVIEW.json",
                "ARCHITECTURE_REVIEW.md",
                "REVIEW_AGENTS_SUMMARY.json",
                "REVIEW_AGENTS_SUMMARY.md",
            ):
                self.assertTrue((review_dir / name).exists(), name)
            self.assertEqual(
                set(summary["reports"]),
                {
                    "validation_review",
                    "sqa_review",
                    "security_review",
                    "scalability_review",
                    "architecture_review",
                },
            )
            summary_md = (review_dir / "REVIEW_AGENTS_SUMMARY.md").read_text()
            self.assertIn("scalability_review", summary_md)
            self.assertIn("architecture_review", summary_md)

    def test_security_review_blocks_on_failed_safety_flag(self) -> None:
        report = run_readonly_review_agents.security_review(
            "sample_project",
            "20260605T010203Z",
            Path("/tmp/review_agents_test"),
            {
                "validation_report": {"safety": {"no_openhands_execution": True, "no_model_calls": False, "target_project_source_modified": False}},
                "morning_report": {
                    "safety_status": {
                        "no_openhands_execution": True,
                        "no_model_calls": True,
                        "auto_merge": False,
                        "auto_push": False,
                        "target_repo_modified_by_default": False,
                    }
                },
                "langgraph_manifest": {
                    "safety": {
                        "no_openhands_execution": True,
                        "no_model_calls": True,
                        "no_auto_merge": True,
                        "no_auto_push": True,
                        "deterministic_validation_authority_preserved": True,
                    }
                },
                "langgraph_state_final": {},
            },
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["blocking"])

    def test_validation_review_nonblocking_when_orchestrator_artifacts_were_intentionally_skipped(self) -> None:
        report = run_readonly_review_agents.validation_review(
            "sample_project",
            "20260605T010203Z",
            Path("/tmp/review_agents_test"),
            {
                "validation_report": {
                    "status": "pass",
                    "failures": [],
                    "validation_mode": {
                        "skip_orchestrator_artifacts": True,
                        "skipped_orchestrator_artifacts": ["latest_langgraph_v0", "latest_nightly_window"],
                        "skip_reason": "orchestrated mode avoids stale/current orchestrator artifact recursion",
                    },
                },
                "morning_report": {},
                "langgraph_manifest": {"status": "fail"},
                "langgraph_state_final": {"status": "fail"},
            },
        )

        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["blocking"])
        self.assertEqual(
            report["summary"]["skipped_orchestrator_artifacts"],
            ["latest_langgraph_v0", "latest_nightly_window"],
        )

    def test_scalability_review_warns_nonblocking_when_evidence_missing(self) -> None:
        old_root = run_readonly_review_agents.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            run_readonly_review_agents.ROOT = Path(tmp)
            try:
                report = run_readonly_review_agents.scalability_review(
                    "sample_project",
                    "20260605T010203Z",
                    Path(tmp) / "review_agents_test",
                    {
                        "validation_report": {"status": "pass"},
                        "morning_report": {},
                        "langgraph_manifest": {},
                        "langgraph_state_final": {},
                    },
                )
            finally:
                run_readonly_review_agents.ROOT = old_root

        self.assertEqual(report["agent"], "scalability_review")
        self.assert_report_shape(report, "scalability_review")
        self.assertEqual(report["status"], "warn")
        self.assertFalse(report["blocking"])
        self.assertTrue(any(finding["severity"] == "medium" for finding in report["findings"]))

    def test_architecture_review_warns_nonblocking_when_evidence_missing(self) -> None:
        report = run_readonly_review_agents.architecture_review(
            "sample_project",
            "20260605T010203Z",
            Path("/tmp/review_agents_test"),
            {
                "validation_report": {"status": "pass"},
                "morning_report": {},
                "langgraph_manifest": {},
                "langgraph_state_final": {},
            },
        )
        self.assertEqual(report["agent"], "architecture_review")
        self.assert_report_shape(report, "architecture_review")
        self.assertEqual(report["status"], "warn")
        self.assertFalse(report["blocking"])
        self.assertTrue(any(finding["severity"] == "medium" for finding in report["findings"]))

    def test_validation_accepts_latest_review_agents_with_five_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            run_root = self.make_sample_run(root, project_id)

            old_review_root = run_readonly_review_agents.ROOT
            run_readonly_review_agents.ROOT = root
            try:
                run_readonly_review_agents.generate(project_id, "20260605T010203Z")
            finally:
                run_readonly_review_agents.ROOT = old_review_root

            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_review_agent_artifacts(recorder, (run_root / "latest_review_agents").resolve())
            self.assertEqual(recorder.failures(), [])


if __name__ == "__main__":
    unittest.main()
