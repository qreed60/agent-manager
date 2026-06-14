#!/usr/bin/env python3
"""Phase 22 — AI Architecture Agent unit tests."""
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

from scripts.run_architecture_agent import (
    ARCHITECTURE_PROPOSAL_SCHEMA,
    GENERATED_BY,
    build_agent_prompt,
    build_markdown_proposal,
    find_feature_brief,
    generate_mock_proposal,
    load_project_config,
    model_call_allowed,
    run_architecture_agent,
    validate_against_schema,
)

VALID_STATUS = {"proposal_ready", "needs_clarification", "blocked"}


def _mktemp_tree():
    tmpdir = Path(tempfile.mkdtemp(prefix="arch_test_"))
    # Create a fake project config
    configs_dir = tmpdir / "configs"
    configs_dir.mkdir()
    projects_json = {
        "projects": {
            "thomsonlint": {
                "name": "Thomson Lint",
                "path": str(tmpdir / "repos" / "thomsonlint"),
            }
        }
    }
    (configs_dir / "projects.json").write_text(json.dumps(projects_json))

    # Create a fake feature brief
    runs_dir = tmpdir / "runs" / "thomsonlint"
    briefs_dir = runs_dir / "feature_briefs" / "feat_smoke_test"
    briefs_dir.mkdir(parents=True)
    brief_data = {
        "schema_version": 1,
        "generated_by": "phase21_feature_brief_intake",
        "created_utc": "20260614T120000Z",
        "project_id": "thomsonlint",
        "feature_id": "feat_smoke_test",
        "title": "Smoke Test Feature",
        "high_level_goal": "Verify architecture agent pipeline works.",
        "desired_behavior": "Should produce a valid mock proposal.",
        "must_have_requirements": ["Deterministic output in mock mode"],
        "risk_level": "low",
        "target_project_area": "scripts",
        "human_priority": "normal",
        "status": "brief_only",
    }
    (briefs_dir / "FEATURE_BRIEF.json").write_text(json.dumps(brief_data))

    # Create a minimal schema file
    schemas_dir = tmpdir / "schemas"
    schemas_dir.mkdir()
    schemas_dir.joinpath("architecture_proposal.schema.json").write_text(
        json.dumps({
            "": "http://json-schema.org/draft-07/schema#",
            "title": "ArchitectureProposal",
            "type": "object",
            "required": ["schema_version", "generated_by", "created_utc", "project_id", "feature_id"],
            "properties": {
                "schema_version": {"type": "integer", "const": 1},
                "generated_by": {"type": "string", "enum": ["phase22_ai_architecture_agent"]},
                "created_utc": {"type": "string", "pattern": r"^\d{8}T\d{6}Z$"},
                "project_id": {"type": "string", "minLength": 1},
                "feature_id": {"type": "string", "minLength": 1},
            },
        })
    )

    return tmpdir


def _patch_root(test, tmpdir):
    """Temporarily patch scripts.run_architecture_agent.ROOT."""
    import scripts.run_architecture_agent as mod
    test._orig_root = mod.ROOT
    mod.ROOT = tmpdir
    # Also patch the schema path constant
    mod.ARCHITECTURE_PROPOSAL_SCHEMA = tmpdir / "schemas" / "architecture_proposal.schema.json"
    return mod


def _restore_root(test, mod):
    import scripts.run_architecture_agent as m
    m.ROOT = test._orig_root
    m.ARCHITECTURE_PROPOSAL_SCHEMA = ROOT / "schemas" / "architecture_proposal.schema.json"



class TestMockProposalGeneration(unittest.TestCase):
    """Test mock proposal generation from a valid feature brief."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mock_proposal_generation_from_valid_feature_brief(self):
        """Mock proposal generation from a valid feature brief produces expected output."""
        mod = _patch_root(self, self.tmpdir)
        try:
            project_id = "thomsonlint"
            feature_id = "feat_smoke_test"

            result = run_architecture_agent(
                project_id=project_id,
                feature_id=feature_id,
                allow_model_call=False,
            )

            # Check all required fields are present and correct type
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["generated_by"], "phase22_ai_architecture_agent")
            self.assertIsInstance(result["created_utc"], str)
            self.assertEqual(result["project_id"], project_id)
            self.assertEqual(result["feature_id"], feature_id)
            self.assertIn("FEATURE_BRIEF.json", result["source_feature_brief_path"])

            # Check text fields are non-empty strings
            for field in ("title", "problem_summary", "recommended_design", "test_strategy"):
                self.assertIsInstance(result[field], str)
                self.assertTrue(len(result[field].strip()) > 0, f"{field} should be non-empty")

            # Check list fields are lists
            for field in ("alternative_designs", "files_likely_involved",
                         "interfaces_and_contracts", "data_artifacts", "safety_risks",
                         "implementation_sequence", "assumptions", "constraints",
                         "out_of_scope", "questions_for_human"):
                self.assertIsInstance(result[field], list)

            # Check architecture_status is valid
            self.assertIn(result["architecture_status"], VALID_STATUS)

            # Check safety flags are all False in mock mode
            self.assertFalse(result["model_call_allowed"])
            self.assertFalse(result["model_called"])
            self.assertFalse(result["source_writes_performed"])
            self.assertFalse(result["openhands_executed"])

            # Check artifacts were written
            out_dir = mod.ROOT / "runs" / project_id / "architecture_proposals" / feature_id
            self.assertTrue((out_dir / "ARCHITECTURE_PROPOSAL.json").exists())
            self.assertTrue((out_dir / "ARCHITECTURE_PROPOSAL.md").exists())
            self.assertTrue((out_dir / "ARCHITECTURE_AGENT_PROMPT.md").exists())

        finally:
            _restore_root(self, mod)

    def test_proposal_json_validates(self):
        """Generated proposal JSON validates against schema."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_architecture_agent(
                project_id="thomsonlint",
                feature_id="feat_smoke_test",
                allow_model_call=False,
            )

            out_dir = mod.ROOT / "runs" / "thomsonlint" / "architecture_proposals" / "feat_smoke_test"
            proposal_path = out_dir / "ARCHITECTURE_PROPOSAL.json"
            with open(proposal_path) as f:
                data = json.load(f)

            ok, errors = validate_against_schema(data, mod.ARCHITECTURE_PROPOSAL_SCHEMA)
            self.assertTrue(ok, f"Schema validation failed: {errors}")
        finally:
            _restore_root(self, mod)


class TestMissingFeatureBrief(unittest.TestCase):
    """Test that missing feature brief fails safely."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_feature_brief_fails_safely(self):
        """Architecture agent rejects with clear error when feature brief is missing."""
        mod = _patch_root(self, self.tmpdir)
        try:
            with self.assertRaises(SystemExit) as ctx:
                run_architecture_agent(
                    project_id="thomsonlint",
                    feature_id="feat_nonexistent",
                    allow_model_call=False,
                )
            self.assertIn("FEATURE_BRIEF.json", str(ctx.exception))

        finally:
            _restore_root(self, mod)


class TestInvalidProjectId(unittest.TestCase):
    """Test that invalid project ID fails safely."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invalid_project_id_fails_safely(self):
        """Architecture agent rejects with clear error when project ID is invalid."""
        mod = _patch_root(self, self.tmpdir)
        try:
            with self.assertRaises(SystemExit) as ctx:
                run_architecture_agent(
                    project_id="nonexistent_project",
                    feature_id="feat_smoke_test",
                    allow_model_call=False,
                )
            self.assertIn("rejected", str(ctx.exception).lower())

        finally:
            _restore_root(self, mod)


class TestModelCallGating(unittest.TestCase):
    """Test that live model calls are refused without both env var and flag."""

    def setUp(self):
        # Save original env and clear it for a clean slate
        self._orig_env = os.environ.pop("AGENT_MANAGER_AI_ENABLE_MODEL_CALLS", None)

    def tearDown(self):
        # Restore original env
        if self._orig_env is not None:
            os.environ["AGENT_MANAGER_AI_ENABLE_MODEL_CALLS"] = self._orig_env

    def test_live_model_call_refuses_without_env_var_and_flag(self):
        """Live model call refuses when env var is not set even with --allow-model-call flag."""
        # Ensure env var is NOT set
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



class TestProposalMarkdownCreated(unittest.TestCase):
    """Test that proposal Markdown is created with correct content."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proposal_markdown_is_created(self):
        """ARCHITECTURE_PROPOSAL.md is created when running in mock mode."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_architecture_agent(
                project_id="thomsonlint",
                feature_id="feat_smoke_test",
                allow_model_call=False,
            )
            out_dir = mod.ROOT / "runs" / "thomsonlint" / "architecture_proposals" / "feat_smoke_test"
            md_path = out_dir / "ARCHITECTURE_PROPOSAL.md"
            self.assertTrue(md_path.exists(), "ARCHITECTURE_PROPOSAL.md should exist")

        finally:
            _restore_root(self, mod)


class TestProposalReferencesCorrectProject(unittest.TestCase):
    """Test that proposal references correct project_id and feature_id."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proposal_references_correct_project_id_and_feature_id(self):
        """Proposal JSON references the correct project_id and feature_id."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_architecture_agent(
                project_id="thomsonlint",
                feature_id="feat_smoke_test",
                allow_model_call=False,
            )

            self.assertEqual(result["project_id"], "thomsonlint")
            self.assertEqual(result["feature_id"], "feat_smoke_test")

        finally:
            _restore_root(self, mod)


class TestNoSourceWritesAndNoOpenHandsFlags(unittest.TestCase):
    """Test that no source writes and no OpenHands flags are false."""

    def setUp(self):
        self.tmpdir = _mktemp_tree()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_source_writes_and_no_openhands_flags_are_false_in_mock_mode(self):
        """All safety flags are false in mock mode."""
        mod = _patch_root(self, self.tmpdir)
        try:
            result = run_architecture_agent(
                project_id="thomsonlint",
                feature_id="feat_smoke_test",
                allow_model_call=False,
            )

            self.assertFalse(result["model_call_allowed"])
            self.assertFalse(result["model_called"])
            self.assertFalse(result["source_writes_performed"])
            self.assertFalse(result["openhands_executed"])

        finally:
            _restore_root(self, mod)


class TestMalformedProposalFailsValidation(unittest.TestCase):
    """Test that malformed architecture proposal fails validation."""

    def test_malformed_architecture_proposal_fails_validation(self):
        """Malformed architecture proposal JSON fails schema validation."""
        # Create a malformed proposal that violates the schema
        malformed = {
            "schema_version": 2,  # must be 1 (const)
            "generated_by": "wrong_generator",  # not in enum
            "created_utc": "not-a-timestamp",  # wrong pattern
            "project_id": "",  # minLength 1 violation
        }
        schema_path = ROOT / "schemas" / "architecture_proposal.schema.json"
        ok, errors = validate_against_schema(malformed, schema_path)
        self.assertFalse(ok, "Malformed proposal should fail validation")
        self.assertTrue(len(errors) > 0, "Should have at least one error")

    def test_malformed_proposal_missing_required_fields_fails(self):
        """Proposal missing required fields fails schema validation."""
        malformed = {
            "schema_version": 1,
            # missing generated_by, created_utc, project_id, feature_id
        }
        schema_path = ROOT / "schemas" / "architecture_proposal.schema.json"
        ok, errors = validate_against_schema(malformed, schema_path)
        self.assertFalse(ok, "Proposal with missing required fields should fail")

    def test_malformed_proposal_wrong_status_fails(self):
        """Proposal with invalid architecture_status fails schema validation."""
        malformed = {
            "schema_version": 1,
            "generated_by": "phase22_ai_architecture_agent",
            "created_utc": "20260614T120000Z",
            "project_id": "test",
            "feature_id": "feat_test",
            "architecture_status": "invalid_status_value",
        }
        schema_path = ROOT / "schemas" / "architecture_proposal.schema.json"
        ok, errors = validate_against_schema(malformed, schema_path)
        self.assertFalse(ok, "Proposal with invalid architecture_status should fail")


if __name__ == "__main__":
    unittest.main()

