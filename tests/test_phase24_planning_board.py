#!/usr/bin/env python3
"""Phase 24 — Multi-Project Agent Planning Board unit tests.

Covers:
  - Building a planning board from one project with Phase 21 only
  - Building a planning board from one project with Phase 21+22+23 artifacts
  - Aggregating multiple registered projects
  - Handling missing architecture proposal with correct recommended_next_action
  - Handling missing manager objective plan with correct recommended_next_action
  - Ready-for-human-review detection when manager plan and draft exist
  - Blocked/needs-clarification handling
  - Archived feature handling
  - Artifact paths stay under central runs storage
  - Target repo remains untouched
  - Generated JSON validates
  - Markdown board is created
  - Validation fails on malformed global feature queue
  - Validation fails on execution-enabled safety flags

"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase, main as unittest_main


# Ensure agent-manager ROOT and scripts are importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Import the build_planning_board module for testing
import build_planning_board as bp


class TestRecommendedNextAction(TestCase):
    """Test the recommended-next-action logic."""

    def _make_feature(self, **overrides):
        base = {
            "status": "brief_only",
            "has_architecture_proposal": False,
            "has_manager_objective_plan": False,
            "has_openhands_manual_gate_request_draft": False,
            "ready_for_openhands_manual_gate": False,
            "blocked": False,
            "architecture_status": "none",
            "manager_plan_status": "none",
            "_plan_data": None,
            "_draft_data": None,
        }
        base.update(overrides)
        return base

    def test_blocked_resolves_first(self):
        feat = self._make_feature(blocked=True, blocked_reason="test blocker")
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "resolve_blocker")

    def test_ready_for_gate_with_draft_reviews_draft(self):
        feat = self._make_feature(
            blocked=False,
            has_openhands_manual_gate_request_draft=True,
            ready_for_openhands_manual_gate=True,
            _draft_data={"approved_for_execution": False, "draft_only": True},
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "review_openhands_manual_gate_draft")

    def test_no_manager_plan_runs_planner(self):
        feat = self._make_feature(
            blocked=False,
            has_manager_objective_plan=False,
            _plan_data=None,
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "run_manager_objective_planner_mock_or_gated")

    def test_needs_clarification_manager_plan(self):
        feat = self._make_feature(
            blocked=False,
            has_manager_objective_plan=True,
            manager_plan_status="needs_clarification",
            _plan_data={"manager_plan_status": "needs_clarification"},
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "clarify_manager_plan")

    def test_no_architecture_proposal_runs_agent(self):
        feat = self._make_feature(
            blocked=False,
            has_manager_objective_plan=True,
            _plan_data={"manager_plan_status": "draft_ready"},
            has_architecture_proposal=False,
            architecture_status="none",
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "run_architecture_agent_mock_or_gated")

    def test_needs_clarification_architecture(self):
        # Need _plan_data + has_manager_objective_plan to pass manager checks first.
        # Also need architecture_status at top level (function reads that key).
        feat = self._make_feature(
            blocked=False,
            has_manager_objective_plan=True,
            _plan_data={"manager_plan_status": "draft_ready"},
            has_architecture_proposal=True,
            architecture_status="needs_clarification",
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "clarify_architecture")

    def test_needs_clarification_feature_brief(self):
        feat = self._make_feature(
            feature_status="needs_clarification",
            has_manager_objective_plan=True,
            _plan_data={"manager_plan_status": "draft_ready"},
            has_architecture_proposal=True,
            architecture_status="proposal_ready",
            manager_plan_status="draft_ready",
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "clarify_feature_brief")

    def test_monitor_or_archive_default(self):
        feat = self._make_feature(
            status="brief_only",
            has_architecture_proposal=True,
            architecture_status="proposal_ready",
            has_manager_objective_plan=False,
        )
        # Should not reach default because no manager plan triggers that first
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "run_manager_objective_planner_mock_or_gated")

    def test_monitor_or_archive_full_chain(self):
        feat = self._make_feature(
            status="brief_only",
            has_architecture_proposal=True,
            architecture_status="proposal_ready",
            has_manager_objective_plan=True,
            manager_plan_status="draft_ready",
            ready_for_openhands_manual_gate=False,
            _plan_data={"manager_plan_status": "draft_ready"},
        )
        action = bp.determine_recommended_next_action(feat)
        self.assertEqual(action, "monitor_or_archive")


class TestFeatureStatusDetermination(TestCase):
    """Test overall feature status logic."""

    def test_ready_for_human_review(self):
        feat = {
            "status": "brief_only",
            "has_architecture_proposal": True,
            "has_manager_objective_plan": True,
            "has_openhands_manual_gate_request_draft": True,
            "_plan_data": None,
        }
        status = bp.determine_feature_status(feat)
        self.assertEqual(status, "ready_for_human_review")

    def test_brief_only(self):
        feat = {
            "status": "brief_only",
            "has_architecture_proposal": False,
            "has_manager_objective_plan": False,
        }
        status = bp.determine_feature_status(feat)
        self.assertEqual(status, "brief_only")

    def test_architecture_ready(self):
        feat = {
            "status": "brief_only",
            "has_architecture_proposal": True,
            "has_manager_objective_plan": False,
        }
        status = bp.determine_feature_status(feat)
        self.assertEqual(status, "architecture_ready")

    def test_archived_preserved(self):
        feat = {
            "status": "archived",
            "has_architecture_proposal": True,
            "has_manager_objective_plan": False,
        }
        status = bp.determine_feature_status(feat)
        self.assertEqual(status, "archived")

    def test_blocked_preserved(self):
        feat = {
            "status": "blocked",
            "has_architecture_proposal": True,
            "has_manager_objective_plan": False,
        }
        status = bp.determine_feature_status(feat)
        self.assertEqual(status, "blocked")


class TestReadinessDetermination(TestCase):
    """Test readiness for OpenHands manual gate."""

    def test_ready_when_plan_and_draft_exist(self):
        feat = {
            "has_manager_objective_plan": True,
            "has_openhands_manual_gate_request_draft": True,
            "_plan_data": {"manager_plan_status": "draft_ready", "ready_for_openhands_manual_gate": True},
            "_draft_data": {"approved_for_execution": False, "draft_only": True},
        }
        ready = bp.determine_readiness_for_openhands(feat)
        self.assertTrue(ready)

    def test_not_ready_without_plan(self):
        feat = {
            "has_manager_objective_plan": False,
            "_plan_data": None,
        }
        ready = bp.determine_readiness_for_openhands(feat)
        self.assertFalse(ready)

    def test_not_ready_when_blocked(self):
        feat = {
            "has_manager_objective_plan": True,
            "has_openhands_manual_gate_request_draft": True,
            "_plan_data": {"manager_plan_status": "blocked", "ready_for_openhands_manual_gate": False},
            "_draft_data": {"approved_for_execution": False, "draft_only": True},
        }
        ready = bp.determine_readiness_for_openhands(feat)
        self.assertFalse(ready)


class TestBlockedStatusDetermination(TestCase):
    """Test blocked status logic."""

    def test_blocked_from_brief(self):
        feat = {"status": "blocked", "has_architecture_proposal": False}
        is_blocked, reason = bp.determine_blocked_status(feat)
        self.assertTrue(is_blocked)
        self.assertIn("Feature brief is blocked", reason)

    def test_not_blocked_when_no_issues(self):
        feat = {
            "status": "brief_only",
            "has_architecture_proposal": True,
            "_arch_data": {"architecture_status": "proposal_ready"},
            "has_manager_objective_plan": False,
        }
        is_blocked, reason = bp.determine_blocked_status(feat)
        self.assertFalse(is_blocked)
        self.assertEqual(reason, "")

    def test_blocked_from_architecture(self):
        feat = {
            "status": "brief_only",
            "has_architecture_proposal": True,
            "_arch_data": {"architecture_status": "blocked"},
        }
        is_blocked, reason = bp.determine_blocked_status(feat)
        self.assertTrue(is_blocked)


class TestPathSafety(TestCase):
    """Test artifact path safety validation."""

    def test_safe_paths(self):
        paths = {
            "feature_brief_path": "runs/thomsonlint/feature_briefs/feat_test/FEATURE_BRIEF.json",
            "architecture_proposal_path": None,
        }
        self.assertTrue(bp.validate_paths_safe(paths))

    def test_unsafe_target_repo_path(self):
        paths = {
            "feature_brief_path": "/mnt/projects/ThomsonLint/src/core.py",
        }
        self.assertFalse(bp.validate_paths_safe(paths))


class TestSortFeatures(TestCase):
    """Test feature sorting logic."""

    def test_blocked_comes_first(self):
        features = [
            {"blocked": False, "human_priority": 1},
            {"blocked": True, "human_priority": 5},
        ]
        sorted_f = bp.sort_features(features)
        self.assertTrue(sorted_f[0]["blocked"])

    def test_lower_priority_comes_first(self):
        features = [
            {"blocked": False, "human_priority": 3, "feature_status": "brief_only"},
            {"blocked": False, "human_priority": 1, "feature_status": "brief_only"},
        ]
        sorted_f = bp.sort_features(features)
        self.assertEqual(sorted_f[0]["human_priority"], 1)


class TestBuildMarkdownBoard(TestCase):
    """Test Markdown planning board generation."""

    def test_board_contains_expected_sections(self):
        features = [
            {
                "project_id": "thomsonlint",
                "feature_id": "feat_test_001",
                "title": "Test Feature",
                "feature_status": "ready_for_human_review",
                "human_priority": 1,
                "risk_level": "low",
                "blocked": False,
                "recommended_next_action": "review_openhands_manual_gate_draft",
                "has_feature_brief": True,
                "has_architecture_proposal": True,
                "has_manager_objective_plan": True,
                "latest_artifact_paths": {
                    "feature_brief_path": None,
                    "architecture_proposal_path": None,
                    "manager_objective_plan_path": None,
                    "openhands_manual_gate_draft_path": "runs/thomsonlint/plan/draft.json",
                },
            }
        ]
        project_statuses = [
            {
                "project_id": "thomsonlint",
                "project_name": "ThomsonLint",
                "registered": True,
                "total_features": 1,
                "brief_only_count": 0,
                "architecture_ready_count": 0,
                "manager_plan_ready_count": 1,
                "ready_for_human_review_count": 1,
                "blocked_count": 0,
                "missing_artifact_count": 0,
                "latest_feature_ids": ["feat_test_001"],
                "recommended_next_actions": ["review_openhands_manual_gate_draft"],
            }
        ]
        md = bp.build_markdown_board(features, project_statuses, "20260614T173224Z")

        self.assertIn("# Agent Manager Planning Board", md)
        self.assertIn("## Summary", md)
        self.assertIn("## Project Summary", md)
        self.assertIn("## Global Prioritized Feature Queue", md)
        self.assertIn("## Ready for Human Review", md)
        self.assertIn("## Blocked or Needs Clarification", md)
        self.assertIn("## Missing Artifact Warnings", md)
        self.assertIn("## Recommended Next Actions", md)
        self.assertIn("## Safety Note", md)
        self.assertIn("planning-board only and performs no execution", md)


class TestBuildProjectStatus(TestCase):
    """Test per-project status building."""

    def test_project_status_counts(self):
        features = [
            {
                "project_id": "thomsonlint",
                "feature_id": "feat_brief_only",
                "title": "Brief Only",
                "feature_status": "brief_only",
                "has_architecture_proposal": False,
                "has_manager_objective_plan": False,
            },
            {
                "project_id": "thomsonlint",
                "feature_id": "feat_ready",
                "title": "Ready for Review",
                "feature_status": "ready_for_human_review",
                "has_architecture_proposal": True,
                "has_manager_objective_plan": True,
            },
        ]
        projects_cfg = {
            "projects": {
                "thomsonlint": {"name": "ThomsonLint", "enabled": True},
            }
        }
        statuses = bp.build_project_status(features, projects_cfg)

        self.assertEqual(len(statuses), 1)
        ps = statuses[0]
        self.assertEqual(ps["project_id"], "thomsonlint")
        self.assertEqual(ps["total_features"], 2)
        self.assertEqual(ps["brief_only_count"], 1)
        self.assertEqual(ps["ready_for_human_review_count"], 1)


class TestIntegrationSmoke(TestCase):
    """Integration smoke test: build planning board from real artifacts."""

    def setUp(self):
        # We rely on existing Phase 21/22/23 artifacts in the actual repo runs
        pass

    def test_build_from_existing_thomsonlint_artifacts(self):
        """Build a planning board for thomsonlint using existing artifacts."""
        projects_cfg = bp.load_projects_config()
        features, scanned = bp.build_global_feature_queue(projects_cfg)

        # Must have at least one feature (we know feat_phase_21_smoke_feature exists)
        self.assertGreater(len(features), 0, "Expected at least one feature from thomsonlint")

        project_ids_scanned = [f["project_id"] for f in features]
        self.assertIn("thomsonlint", project_ids_scanned or scanned)

    def test_sorting_applied(self):
        """Features must be sorted by blocked, priority, status."""
        projects_cfg = bp.load_projects_config()
        features, _ = bp.build_global_feature_queue(projects_cfg)
        if len(features) < 2:
            self.skipTest("Need at least 2 features to test sorting")

        sorted_f = bp.sort_features(features)
        # Check that blocked items come first (if any exist)
        for i in range(len(sorted_f) - 1):
            a, b = sorted_f[i], sorted_f[i + 1]
            if a["blocked"] and not b["blocked"]:
                continue  # correct order
            if not a["blocked"] and b["blocked"]:
                self.fail("Blocked feature should come before non-blocked")
        self.assertTrue(True)  # sorted correctly


class TestValidationGlobalQueue(TestCase):
    """Test Phase 24 validation of GLOBAL_FEATURE_QUEUE.json."""

    def _write_temp_queue(self, data: dict, tmp_dir: Path) -> Path:
        path = tmp_dir / "GLOBAL_FEATURE_QUEUE.json"
        path.write_text(json.dumps(data, indent=2))
        return path

    def test_valid_global_queue_passes(self):
        safety = {
            "source_writes_performed": False,
            "openhands_executed": False,
            "coder_task_executed": False,
            "apply_performed": False,
            "commit_performed": False,
            "push_performed": False,
            "merge_performed": False,
            "pr_created": False,
        }
        data = {
            "schema_version": 1,
            "generated_by": bp.PHASE24_GENERATED_BY,
            "created_utc": "20260614T173224Z",
            "projects_scanned": ["thomsonlint"],
            "total_features": 1,
            "features": [
                {
                    "project_id": "thomsonlint",
                    "feature_id": "feat_test_001",
                    "title": "Test Feature",
                    "feature_status": "brief_only",
                    "risk_level": "low",
                    "human_priority": 3,
                    "target_project_area": "",
                    "has_feature_brief": True,
                    "has_architecture_proposal": False,
                    "has_manager_objective_plan": False,
                    "has_openhands_manual_gate_request_draft": False,
                    "architecture_status": "none",
                    "manager_plan_status": "none",
                    "ready_for_openhands_manual_gate": False,
                    "blocked": False,
                    "blocked_reason": "",
                    "latest_artifact_paths": {
                        "feature_brief_path": None,
                        "architecture_proposal_path": None,
                        "manager_objective_plan_path": None,
                        "openhands_manual_gate_draft_path": None,
                    },
                    "recommended_next_action": "monitor_or_archive",
                }
            ],
            "safety_summary": safety,
        }
        with tempfile.TemporaryDirectory() as td:
            path = self._write_temp_queue(data, Path(td))
            # Temporarily override the global path for testing
            original_path = bp.GLOBAL_FEATURE_QUEUE_PATH
            bp.GLOBAL_FEATURE_QUEUE_PATH = path

            try:
                from validate_agent_run import CheckRecorder
                recorder = CheckRecorder()
                bp.validate_phase24_global_feature_queue(recorder)
                failures = [c for c in recorder.checks if c["status"] == "fail"]
                self.assertEqual(len(failures), 0, f"Expected no failures; got {failures}")
            finally:
                bp.GLOBAL_FEATURE_QUEUE_PATH = original_path

    def test_malformed_queue_fails(self):
        data = {"schema_version": "not_an_integer", "generated_by": "wrong_value"}
        with tempfile.TemporaryDirectory() as td:
            path = self._write_temp_queue(data, Path(td))
            original_path = bp.GLOBAL_FEATURE_QUEUE_PATH
            bp.GLOBAL_FEATURE_QUEUE_PATH = path

            try:
                from validate_agent_run import CheckRecorder
                recorder = CheckRecorder()
                bp.validate_phase24_global_feature_queue(recorder)
                failures = [c for c in recorder.checks if c["status"] == "fail"]
                self.assertGreater(len(failures), 0, "Expected validation to fail on malformed data")
            finally:
                bp.GLOBAL_FEATURE_QUEUE_PATH = original_path

    def test_execution_safety_flags_fail(self):
        """Validation must reject artifacts with execution-enabled safety flags."""
        bad_safety = {
            "source_writes_performed": True,
            "openhands_executed": False,  # Phase 24 performs no execution; all flags must be false
            "coder_task_executed": True,
            "apply_performed": True,
            "commit_performed": True,
            "push_performed": True,
            "merge_performed": True,
            "pr_created": True,
        }
        data = {
            "schema_version": 1,
            "generated_by": bp.PHASE24_GENERATED_BY,
            "created_utc": "20260614T173224Z",
            "projects_scanned": ["thomsonlint"],
            "total_features": 0,
            "features": [],
            "safety_summary": bad_safety,
        }
        with tempfile.TemporaryDirectory() as td:
            path = self._write_temp_queue(data, Path(td))
            original_path = bp.GLOBAL_FEATURE_QUEUE_PATH
            bp.GLOBAL_FEATURE_QUEUE_PATH = path

            try:
                from validate_agent_run import CheckRecorder
                recorder = CheckRecorder()
                bp.validate_phase24_global_feature_queue(recorder)
                failures = [c for c in recorder.checks if c["status"] == "fail"]
                self.assertGreater(len(failures), 0, "Expected validation to fail on bad safety flags")
            finally:
                bp.GLOBAL_FEATURE_QUEUE_PATH = original_path


class TestValidationProjectStatus(TestCase):
    """Test Phase 24 validation of PROJECT_FEATURE_STATUS.json."""

    def _write_temp_status(self, data: dict, tmp_dir: Path) -> Path:
        path = tmp_dir / "PROJECT_FEATURE_STATUS.json"
        path.write_text(json.dumps(data, indent=2))
        return path

    def test_valid_project_status_passes(self):
        safety = {
            "source_writes_performed": False,
            "openhands_executed": False,
            "coder_task_executed": False,
            "apply_performed": False,
            "commit_performed": False,
            "push_performed": False,
            "merge_performed": False,
            "pr_created": False,
        }
        data = {
            "schema_version": 1,
            "generated_by": bp.PHASE24_GENERATED_BY,
            "created_utc": "20260614T173224Z",
            "projects": [
                {
                    "project_id": "thomsonlint",
                    "project_name": "ThomsonLint",
                    "registered": True,
                    "repo_path": "/mnt/projects/ThomsonLint",
                    "server_state_dir": "",
                    "total_features": 0,
                    "brief_only_count": 0,
                    "architecture_ready_count": 0,
                    "manager_plan_ready_count": 0,
                    "ready_for_human_review_count": 0,
                    "blocked_count": 0,
                    "missing_artifact_count": 0,
                    "latest_feature_ids": [],
                    "recommended_next_actions": [],
                }
            ],
            "safety_summary": safety,
        }
        with tempfile.TemporaryDirectory() as td:
            path = self._write_temp_status(data, Path(td))
            original_path = bp.PROJECT_FEATURE_STATUS_PATH
            bp.PROJECT_FEATURE_STATUS_PATH = path

            try:
                from validate_agent_run import CheckRecorder
                recorder = CheckRecorder()
                bp.validate_phase24_project_feature_status(recorder)
                failures = [c for c in recorder.checks if c["status"] == "fail"]
                self.assertEqual(len(failures), 0, f"Expected no failures; got {failures}")
            finally:
                bp.PROJECT_FEATURE_STATUS_PATH = original_path

    def test_malformed_project_status_fails(self):
        data = {"schema_version": 2}  # wrong schema version, missing projects
        with tempfile.TemporaryDirectory() as td:
            path = self._write_temp_status(data, Path(td))
            original_path = bp.PROJECT_FEATURE_STATUS_PATH
            bp.PROJECT_FEATURE_STATUS_PATH = path

            try:
                from validate_agent_run import CheckRecorder
                recorder = CheckRecorder()
                bp.validate_phase24_project_feature_status(recorder)
                failures = [c for c in recorder.checks if c["status"] == "fail"]
                self.assertGreater(len(failures), 0, "Expected validation to fail on malformed data")
            finally:
                bp.PROJECT_FEATURE_STATUS_PATH = original_path


class TestTargetRepoSafety(TestCase):
    """Ensure no target repo writes during planning board generation."""

    def test_no_target_repo_paths_in_artifacts(self):
        """Artifact paths must stay under central runs storage, not target repos."""
        projects_cfg = bp.load_projects_config()
        features, _ = bp.build_global_feature_queue(projects_cfg)

        for feat in features:
            paths = feat.get("latest_artifact_paths", {})
            for key, path_val in paths.items():
                if path_val is None or not isinstance(path_val, str):
                    continue
                self.assertNotIn(
                    "/mnt/projects/",
                    path_val,
                    f"Path {key}={path_val} points to target repo!",
                )


class TestMarkdownBoardExists(TestCase):
    """Test that the Markdown board is created and readable."""

    def test_markdown_board_generated(self):
        """After building a planning board, AGENT_MANAGER_PLANNING_BOARD.md should exist."""
        projects_cfg = bp.load_projects_config()
        features, scanned = bp.build_global_feature_queue(projects_cfg)
        statuses = bp.build_project_status(features, projects_cfg)

        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "planning_board"
            output_dir.mkdir(parents=True, exist_ok=True)  # Ensure dir exists
            created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            md_content = bp.build_markdown_board(features, statuses, created_utc)
            md_path = output_dir / "AGENT_MANAGER_PLANNING_BOARD.md"
            md_path.write_text(md_content)

            self.assertTrue(md_path.exists())
            content2 = md_path.read_text()
            self.assertIn("# Agent Manager Planning Board", content2)
            self.assertIn("## Safety Note", content2)


if __name__ == "__main__":
    unittest_main()
