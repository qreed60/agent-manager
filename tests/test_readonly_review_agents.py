from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_readonly_review_agents


class ReadonlyReviewAgentsTests(unittest.TestCase):
    def test_generate_writes_reports_and_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            run_root = root / "runs" / project_id
            (root / "configs").mkdir()
            (root / "configs" / "projects.json").write_text(
                json.dumps({"schema_version": 1, "projects": {project_id: {"repo_path": str(root / "repo")}}}) + "\n"
            )
            (root / "repo").mkdir()

            validation_dir = run_root / "validation_20260605T000000Z"
            morning_dir = run_root / "morning_20260605T000000Z"
            langgraph_dir = run_root / "langgraph_v0_20260605T000000Z"
            validation_dir.mkdir(parents=True)
            morning_dir.mkdir()
            langgraph_dir.mkdir()
            (run_root / "latest_validation").symlink_to(validation_dir, target_is_directory=True)
            (run_root / "latest_morning_report").symlink_to(morning_dir, target_is_directory=True)
            (run_root / "latest_langgraph_v0").symlink_to(langgraph_dir, target_is_directory=True)

            (validation_dir / "VALIDATION_REPORT.json").write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "failures": [],
                        "safety": {
                            "no_openhands_execution": True,
                            "no_model_calls": True,
                            "target_project_source_modified": False,
                        },
                    }
                )
                + "\n"
            )
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
            (langgraph_dir / "LANGGRAPH_RUN_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "status": "pass",
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
                "REVIEW_AGENTS_SUMMARY.json",
                "REVIEW_AGENTS_SUMMARY.md",
            ):
                self.assertTrue((review_dir / name).exists(), name)

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


if __name__ == "__main__":
    unittest.main()
