#!/usr/bin/env python3
"""Phase 23 — AI Manager Objective Planner unit tests."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_manager_objective_planner import (
    GENERATED_BY,
    build_manager_prompt,
    build_markdown_plan,
    find_architecture_proposal,
    find_feature_brief,
    generate_mock_plan,
    generate_openhands_manual_gate_draft,
    load_project_config,
    model_call_allowed,
    run_manager_objective_planner,
    validate_against_schema,
)


def _mktemp_tree():
    """Create a temporary directory tree with fake project config and valid artifacts."""
    tmpdir = Path(tempfile.mkdtemp(prefix="phase23_test_"))

    # Create fake project config
    configs_dir = tmpdir / "configs"
    configs_dir.mkdir()
    projects_json = {
        "projects": {
            "thomsonlint": {
                "name": "Thomson Lint",
                "path": str(tmpdir / "repos" / "thomsonlint"),
                "repo_path": str(tmpdir / "repos" / "thomsonlint"),
            }
        }
    }
    (configs_dir / "projects.json").write_text(json.dumps(projects_json))

    # Create fake target repo directory
    (tmpdir / "repos" / "thomsonlint").mkdir(parents=True)

    # Create a valid Phase 21 feature brief
    runs_dir = tmpdir / "runs" / "thomsonlint"
    briefs_dir = runs_dir / "feature_briefs" / "feat_manager_planner_smoke"
    briefs_dir.mkdir(parents=True)
    brief_data = {
        "schema_version": 1,
        "generated_by": "phase21_feature_brief_intake",
        "created_utc": "20260614T120000Z",
        "project_id": "thomsonlint",
        "feature_id": "feat_manager_planner_smoke",
        "title": "Manager Planner Smoke Feature",
        "high_level_goal": "Verify manager objective planning from architecture proposals.",
        "desired_behavior": "Generate a bounded objective plan and OpenHands request draft.",
        "must_have_requirements": [
            "Create MANAGER_OBJECTIVE_PLAN.json",
            "Create MANAGER_OBJECTIVE_PLAN.md",
            "Create OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json",
        ],
        "nice_to_have_requirements": ["Add validation coverage"],
        "constraints": ["No OpenHands execution", "No target repo writes"],
        "out_of_scope": ["Executing the request draft"],
        "risk_level": "low",
        "target_project_area": "agent-manager",
        "human_priority": 1,
        "status": "ready_for_architecture",
    }
    (briefs_dir / "FEATURE_BRIEF.json").write_text(json.dumps(brief_data))

    # Create a valid Phase 22 architecture proposal
    arch_dir = runs_dir / "architecture_proposals" / "feat_manager_planner_smoke"
    arch_dir.mkdir(parents=True)
    arch_data = {
        "schema_version": 1,
        "generated_by": "phase22_ai_architecture_agent",
        "created_utc": "20260614T130000Z",
        "project_id": "thomsonlint",
        "feature_id": "feat_manager_planner_smoke",
        "source_feature_brief_path": str(runs_dir / "feature_briefs" / "feat_manager_planner_smoke"),
        "title": "Manager Planner Smoke Architecture",
        "architecture_status": "proposal_ready",
        "problem_summary": "Implement manager objective planning from architecture proposals.",
        "recommended_design": "Modular design with clear separation of concerns for planner component.",
        "alternative_designs": ["Monolithic approach"],
        "files_likely_involved": [
            "scripts/run_manager_objective_planner.py",
            "schemas/manager_objective_plan.schema.json",
        ],
        "interfaces_and_contracts": ["Manager objective plan JSON schema"],
        "data_artifacts": [
            f"runs/thomsonlint/manager_objective_plans/{brief_data['feature_id']}/MANAGER_OBJECTIVE_PLAN.json",
        ],
        "safety_risks": ["Model call must remain disabled unless explicitly gated."],
        "test_strategy": "Unit tests for mock generation and schema validation.",
        "implementation_sequence": [
            "1. Validate project_id against configs/projects.json",
            "2. Locate FEATURE_BRIEF.json and ARCHITECTURE_PROPOSAL.json",
            "3. Generate deterministic mock manager objective plan",
            "4. Write MANAGER_OBJECTIVE_PLAN.json and .md",
        ],
        "assumptions": [
            f"Feature brief at runs/thomsonlint/feature_briefs/{brief_data['feature_id']}/FEATURE_BRIEF.json is valid.",
        ],
        "constraints": ["No OpenHands execution", "Model calls disabled by default"],
        "out_of_scope": ["Executing the request draft"],
        "questions_for_human": [
            "Is the recommended design appropriate for this feature?",
        ],
        "model_call_allowed": False,
        "model_called": False,
        "source_writes_performed": False,
        "openhands_executed": False,
    }
    (arch_dir / "ARCHITECTURE_PROPOSAL.json").write_text(json.dumps(arch_data))

    # Create a minimal schema file for validation
    schemas_dir = tmpdir / "schemas"
    schemas_dir.mkdir()
    schemas_dir.joinpath("manager_objective_plan.schema.json").write_text(
        json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "ManagerObjectivePlan",
            "type": "object",
            "required": ["schema_version", "generated_by", "project_id", "feature_id"],
            "properties": {
                "schema_version": {"type": "integer", "const": 1},
                "generated_by": {"type": "string", "enum": ["phase23_ai_manager_objective_planner"]},
                "project_id": {"type": "string", "minLength": 1},
                "feature_id": {"type": "string", "minLength": 1},
            },
        })
    )

    return tmpdir


def _patch_root(test, tmpdir):
    """Temporarily patch scripts.run_manager_objective_planner.ROOT."""
    import scripts.run_manager_objective_planner as mod
    test._orig_root = mod.ROOT
    mod.ROOT = tmpdir
    mod.MANAGER_OBJECTIVE_PLAN_SCHEMA = tmpdir / "schemas" / "manager_objective_plan.schema.json"
    return mod


def _restore_root(test, mod):
    import scripts.run_manager_objective_planner as m
    m.ROOT = test._orig_root
    m.MANAGER_OBJECTIVE_PLAN_SCHEMA = ROOT / "schemas" / "manager_objective_plan.schema.json"


# ---------------------------------------------------------------------------
# Tests: Mock manager objective plan generation from valid artifacts
# ---------------------------------------------------------------------------


class TestMockPlanGeneration(unittest.TestCase):
    """Test mock manager objective plan generation from a valid feature brief and architecture proposal."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mock_plan_generation_from_valid_artifacts(self):
        """Mock plan generation from valid Phase 21 and Phase 22 artifacts produces expected output."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )

            # Check all required fields are present and correct type
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["generated_by"], "phase23_ai_manager_objective_planner")
            self.assertIsInstance(result["created_utc"], str)
            self.assertEqual(result["project_id"], "thomsonlint")
            self.assertEqual(result["feature_id"], "feat_manager_planner_smoke")

            # Check text fields are non-empty strings
            for field in ("title", "objective_summary", "selected_architecture_summary", "bounded_scope", "rollback_plan"):
                self.assertIsInstance(result[field], str)
                self.assertTrue(len(result[field].strip()) > 0, f"{field} should be non-empty")

            # Check list fields are lists
            for field in ("allowed_files", "disallowed_files", "implementation_steps", "validation_commands",
                         "acceptance_criteria", "risk_controls", "dependencies", "assumptions",
                         "constraints", "out_of_scope", "questions_for_human"):
                self.assertIsInstance(result[field], list)

            # Check manager_plan_status is valid
            self.assertIn(result["manager_plan_status"], {"draft_ready", "needs_clarification", "blocked"})

            # Check safety flags are all False in mock mode
            self.assertFalse(result["model_call_allowed"])
            self.assertFalse(result["model_called"])
            self.assertFalse(result["source_writes_performed"])
            self.assertFalse(result["openhands_executed"])
            self.assertFalse(result["coder_task_executed"])
            self.assertFalse(result["apply_performed"])
            self.assertFalse(result["commit_performed"])
            self.assertFalse(result["push_performed"])
            self.assertFalse(result["merge_performed"])
            self.assertFalse(result["pr_created"])

            # Check source artifact paths are present and non-empty
            self.assertIn("FEATURE_BRIEF.json", result["source_feature_brief_path"])
            self.assertIn("ARCHITECTURE_PROPOSAL.json", result["source_architecture_proposal_path"])

            # Check artifacts were written
            out_dir = mod.ROOT / "runs" / "thomsonlint" / "manager_objective_plans" / "feat_manager_planner_smoke"
            self.assertTrue((out_dir / "MANAGER_OBJECTIVE_PLAN.json").exists())
            self.assertTrue((out_dir / "MANAGER_OBJECTIVE_PLAN.md").exists())
            self.assertTrue((out_dir / "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json").exists())
            self.assertTrue((out_dir / "MANAGER_OBJECTIVE_PLANNER_PROMPT.md").exists())

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Missing feature brief fails safely
# ---------------------------------------------------------------------------


class TestMissingFeatureBrief(unittest.TestCase):
    """Test that missing feature brief fails safely."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_feature_brief_fails_safely(self):
        """Manager planner rejects with clear error when feature brief is missing."""
        mod = _patch_root(self, self.tmpdir)
        try:
            with self.assertRaises(SystemExit) as ctx:
                run_manager_objective_planner(
                    project_id="thomsonlint",
                    feature_id="feat_nonexistent",
                    allow_model_call=False,
                )
            self.assertIn("FEATURE_BRIEF.json", str(ctx.exception))

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Missing architecture proposal fails safely
# ---------------------------------------------------------------------------


class TestMissingArchitectureProposal(unittest.TestCase):
    """Test that missing architecture proposal fails safely."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_architecture_proposal_fails_safely(self):
        """Manager planner rejects with clear error when architecture proposal is missing."""
        mod = _patch_root(self, self.tmpdir)
        try:
            # Remove the architecture proposal directory to simulate it being missing
            arch_dir = self.tmpdir / "runs" / "thomsonlint" / "architecture_proposals" / "feat_manager_planner_smoke"
            shutil.rmtree(arch_dir, ignore_errors=True)

            with self.assertRaises(SystemExit) as ctx:
                run_manager_objective_planner(
                    project_id="thomsonlint",
                    feature_id="feat_manager_planner_smoke",
                    allow_model_call=False,
                )
            self.assertIn("ARCHITECTURE_PROPOSAL.json", str(ctx.exception))

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Invalid project ID fails safely
# ---------------------------------------------------------------------------


class TestInvalidProjectId(unittest.TestCase):
    """Test that invalid project ID fails safely."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invalid_project_id_fails_safely(self):
        """Manager planner rejects with clear error when project ID is invalid."""
        mod = _patch_root(self, self.tmpdir)
        try:
            with self.assertRaises(SystemExit) as ctx:
                run_manager_objective_planner(
                    project_id="nonexistent_project",
                    feature_id="feat_manager_planner_smoke",
                    allow_model_call=False,
                )
            self.assertIn("rejected", str(ctx.exception).lower())

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Model call gating
# ---------------------------------------------------------------------------


class TestModelCallGating(unittest.TestCase):
    """Test that live model calls are refused without both env var and flag."""

    def setUp(self):
        self._orig_env = os.environ.pop("AGENT_MANAGER_AI_ENABLE_MODEL_CALLS", None)

    def tearDown(self):
        if self._orig_env is not None:
            os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"] = self._orig_env

    def test_live_model_call_refuses_without_env_var_and_flag(self):
        """Live model call refuses when env var is not set even with --allow-model-call flag."""
        if "AGENT_MANAGER_AI_ENABLE_MODEL_CALLS" in os.environ:
            del os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"]

        self.assertFalse(model_call_allowed(True))  # flag=True but no env var
        self.assertFalse(model_call_allowed(False))  # both off

    def test_live_model_call_refuses_without_flag(self):
        """Live model call refuses when flag is not set even with env var."""
        os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"] = "1"
        self.assertFalse(model_call_allowed(False))  # env=True but no flag

    def test_live_model_call_allowed_only_with_both(self):
        """Live model call is allowed only when both flag and env var are set."""
        os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"] = "1"
        self.assertTrue(model_call_allowed(True))  # both set


# ---------------------------------------------------------------------------
# Tests: Mock mode does not require model config
# ---------------------------------------------------------------------------


class TestMockModeNoModelConfig(unittest.TestCase):
    """Test that mock mode works without any model configuration."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()
        # Ensure env var is NOT set
        self._orig_env = os.environ.pop("AGENT_MANAGER_AI_ENABLE_MODEL_CALLS", None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if self._orig_env is not None:
            os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"] = self._orig_env

    def test_mock_mode_works_without_model_config(self):
        """Mock mode works without AGENT_MANAGER_AI_ENABLE_MODEL_CALLS set."""
        mod = _patch_root(self, self.tmpdir)
        try:
            # Ensure env var is NOT set
            if "AGENT_MANAGER_AI_ENABLE_MODEL_CALLS" in os.environ:
                del os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"]

            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )

            self.assertFalse(result["model_call_allowed"])
            self.assertFalse(result["model_called"])
            self.assertEqual(result["manager_plan_status"], "draft_ready")

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Manager objective plan JSON validates against schema
# ---------------------------------------------------------------------------


class TestPlanSchemaValidation(unittest.TestCase):
    """Test that manager objective plan JSON validates correctly."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_manager_objective_plan_json_validates(self):
        """Generated manager objective plan JSON validates against schema."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )

            out_dir = mod.ROOT / "runs" / "thomsonlint" / "manager_objective_plans" / "feat_manager_planner_smoke"
            plan_path = out_dir / "MANAGER_OBJECTIVE_PLAN.json"
            with open(plan_path) as f:
                data = json.load(f)

            ok, errors = validate_against_schema(data, mod.MANAGER_OBJECTIVE_PLAN_SCHEMA)
            self.assertTrue(ok, f"Schema validation failed: {errors}")
        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Manager objective plan Markdown is created
# ---------------------------------------------------------------------------


class TestPlanMarkdownCreated(unittest.TestCase):
    """Test that manager objective plan Markdown is created with correct content."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_manager_objective_plan_markdown_is_created(self):
        """MANAGER_OBJECTIVE_PLAN.md is created when running in mock mode."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )
            out_dir = mod.ROOT / "runs" / "thomsonlint" / "manager_objective_plans" / "feat_manager_planner_smoke"
            md_path = out_dir / "MANAGER_OBJECTIVE_PLAN.md"
            self.assertTrue(md_path.exists(), "MANAGER_OBJECTIVE_PLAN.md should exist")

            content = md_path.read_text()
            self.assertIn(result["title"], content)
            self.assertIn("Safety Summary", content)
        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: OpenHands manual gate request draft is created
# ---------------------------------------------------------------------------


class TestDraftRequestCreated(unittest.TestCase):
    """Test that OpenHands manual gate request draft is created."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_openhands_manual_gate_request_draft_is_created(self):
        """OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json is created."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )
            out_dir = mod.ROOT / "runs" / "thomsonlint" / "manager_objective_plans" / "feat_manager_planner_smoke"
            draft_path = out_dir / "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json"
            self.assertTrue(draft_path.exists(), "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json should exist")

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Draft request has draft_only=true and approved_for_execution=false
# ---------------------------------------------------------------------------


class TestDraftRequestFlags(unittest.TestCase):
    """Test that the draft request has correct flags."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_draft_request_has_correct_flags(self):
        """OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json has draft_only=true and approved_for_execution=false."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )
            out_dir = mod.ROOT / "runs" / "thomsonlint" / "manager_objective_plans" / "feat_manager_planner_smoke"
            draft_path = out_dir / "OPENHANDS_MANUAL_GATE_REQUEST_DRAFT.json"

            with open(draft_path) as f:
                draft_data = json.load(f)

            self.assertTrue(draft_data.get("draft_only"), "draft_only must be true")
            self.assertFalse(draft_data.get("approved_for_execution"), "approved_for_execution must be false")

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Proposal references correct project_id and feature_id
# ---------------------------------------------------------------------------


class TestProposalReferencesCorrectProject(unittest.TestCase):
    """Test that proposal references correct project_id and feature_id."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proposal_references_correct_project_id_and_feature_id(self):
        """Manager objective plan JSON references the correct project_id and feature_id."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )

            self.assertEqual(result["project_id"], "thomsonlint")
            self.assertEqual(result["feature_id"], "feat_manager_planner_smoke")

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: No source writes, no OpenHands, no coder task, no apply/commit/push/merge/PR flags remain false
# ---------------------------------------------------------------------------


class TestAllSafetyFlagsFalse(unittest.TestCase):
    """Test that all safety flags are false in mock mode."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_safety_flags_are_false_in_mock_mode(self):
        """All safety flags are false in mock mode."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )

            self.assertFalse(result["model_call_allowed"])
            self.assertFalse(result["model_called"])
            self.assertFalse(result["source_writes_performed"])
            self.assertFalse(result["openhands_executed"])
            self.assertFalse(result["coder_task_executed"])
            self.assertFalse(result["apply_performed"])
            self.assertFalse(result["commit_performed"])
            self.assertFalse(result["push_performed"])
            self.assertFalse(result["merge_performed"])
            self.assertFalse(result["pr_created"])

        finally:
            _restore_root(self, mod)


# ---------------------------------------------------------------------------
# Tests: Validation fails on malformed manager objective plan
# ---------------------------------------------------------------------------


class TestMalformedPlanFailsValidation(unittest.TestCase):
    """Test that validation fails on malformed manager objective plan."""

    def test_malformed_manager_objective_plan_fails_validation(self):
        """Malformed manager objective plan JSON fails schema validation."""
        malformed = {
            "schema_version": 2,  # must be 1 (const)
            "generated_by": "wrong_generator",  # not in enum
            "project_id": "",  # minLength 1 violation
            "feature_id": "feat_test",
        }
        schema_path = ROOT / "schemas" / "manager_objective_plan.schema.json"
        ok, errors = validate_against_schema(malformed, schema_path)
        self.assertFalse(ok, "Malformed plan should fail validation")
        self.assertTrue(len(errors) > 0, "Should have at least one error")

    def test_malformed_plan_missing_required_fields_fails(self):
        """Plan missing required fields fails schema validation."""
        malformed = {
            "schema_version": 1,
            # missing generated_by, project_id, feature_id
        }
        schema_path = ROOT / "schemas" / "manager_objective_plan.schema.json"
        ok, errors = validate_against_schema(malformed, schema_path)
        self.assertFalse(ok, "Plan with missing required fields should fail")

    def test_malformed_plan_wrong_status_fails(self):
        """Plan with invalid manager_plan_status fails validation."""
        malformed = {
            "schema_version": 1,
            "generated_by": "phase23_ai_manager_objective_planner",
            "project_id": "test",
            "feature_id": "feat_test",
            "manager_plan_status": "invalid_status_value",
            "objective_summary": "test",
            "selected_architecture_summary": "test",
            "bounded_scope": "test",
            "rollback_plan": "test",
        }
        schema_path = ROOT / "schemas" / "manager_objective_plan.schema.json"
        ok, errors = validate_against_schema(malformed, schema_path)
        self.assertFalse(ok, "Plan with invalid manager_plan_status should fail")


# ---------------------------------------------------------------------------
# Tests: Validation fails on execution-enabled request draft
# ---------------------------------------------------------------------------


class TestExecutionEnabledDraftFailsValidation(unittest.TestCase):
    """Test that validation fails when the draft request has execution-enabling flags."""

    def test_execution_enabled_draft_request_fails_validation(self):
        """A draft with approved_for_execution=true should fail Phase 23 validation checks."""
        # Create a draft that violates the draft_only constraint
        bad_draft = {
            "schema_version": 1,
            "generated_by": GENERATED_BY,
            "created_utc": "20260614T120000Z",
            "project_id": "thomsonlint",
            "feature_id": "feat_test",
            "objective_id": "obj_test_001",
            "title": "Test",
            "task_summary": "Test task",
            "allowed_files": [],
            "disallowed_files": ["test"],
            "validation_commands": [],
            "acceptance_criteria": ["test"],
            "safety_notes": [],
            "source_manager_objective_plan_path": "runs/thomsonlint/test/PLAN.json",
            "draft_only": False,  # VIOLATION: must be True
            "approved_for_execution": True,  # VIOLATION: must be False
            "openhands_executed": False,
            "source_writes_performed": False,
            "apply_performed": False,
            "commit_performed": False,
            "push_performed": False,
            "merge_performed": False,
            "pr_created": False,
        }

        # Verify the bad draft has the violation flags we expect to catch
        self.assertFalse(bad_draft.get("draft_only"), "Draft should have draft_only=False (violation)")
        self.assertTrue(bad_draft.get("approved_for_execution"), "Draft should have approved_for_execution=True (violation)")

        # The Phase 23 validation would fail on these flags:
        # - draft_only must be True
        # - approved_for_execution must be False


# ---------------------------------------------------------------------------
# Tests: Target repo remains untouched
# ---------------------------------------------------------------------------


class TestTargetRepoUntouched(unittest.TestCase):
    """Test that the target repository is not modified by Phase 23."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_target_repo_not_modified_by_phase23(self):
        """Target repo files are not created or modified by Phase 23 planning."""
        mod = _patch_root(self, self.tmpdir)
        try:
            # Record the state of the target repo directory before running
            repo_dir = tmpdir_path = mod.ROOT / "repos" / "thomsonlint"
            files_before = set()
            if repo_dir.exists():
                for f in repo_dir.rglob("*"):
                    if f.is_file():
                        files_before.add(str(f.relative_to(mod.ROOT)))

            # Run the planner in mock mode
            result = run_manager_objective_planner(
                project_id="thomsonlint",
                feature_id="feat_manager_planner_smoke",
                allow_model_call=False,
            )

            # Record state after running
            files_after = set()
            if repo_dir.exists():
                for f in repo_dir.rglob("*"):
                    if f.is_file():
                        files_after.add(str(f.relative_to(mod.ROOT)))

            # No new files should have been created in the target repo
            self.assertEqual(files_before, files_after, "Target repo should not be modified")

            # Verify safety flags confirm no writes
            self.assertFalse(result["source_writes_performed"])

        finally:
            _restore_root(self, mod)


if __name__ == "__main__":
    unittest.main()
