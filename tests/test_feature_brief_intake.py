#!/usr/bin/env python3
"""Phase 21 — Feature Brief Intake and Queue unit tests."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest


# Ensure agent-manager root is on the path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_feature_brief import (
    FEATURE_BRIEF_SCHEMA,
    FEATURE_QUEUE_SCHEMA,
    GENERATED_BY,
    create_feature_brief,
    slug_from_title,
)

PHASE21_VALID_STATUSES = frozenset({"brief_only", "needs_clarification", "ready_for_architecture", "blocked", "archived"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class TestSlugFromTitle(unittest.TestCase):
    """Test stable slug generation from titles."""

    def test_simple_title(self):
        result = slug_from_title("Feature intake system")
        self.assertEqual(result, "feat_feature_intake_system")

    def test_special_characters(self):
        result = slug_from_title("Feature: Test! @#$%^&*()")
        self.assertIn("feat_feature_test", result)

    def test_spaces_to_underscores(self):
        result = slug_from_title("Multiple   spaces   here")
        self.assertEqual(result, "feat_multiple_spaces_here")

    def test_empty_title_defaults_to_untitled(self):
        result = slug_from_title("")
        self.assertEqual(result, "feat_untitled")

    def test_uppercase_normalized(self):
        result = slug_from_title("UPPERCASE Title")
        self.assertIn("feat_uppercase_title", result)

    def test_stable_id_generation(self):
        """Same title produces same feature_id."""
        id1 = f"feat_{slug_from_title('My Feature')}"
        id2 = f"feat_{slug_from_title('My Feature')}"
        self.assertEqual(id1, id2)


class TestCreateFeatureBriefMinimal(unittest.TestCase):
    """Test creating a minimal valid feature brief."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Temporarily override ROOT for this test by patching the module's paths
        import scripts.create_feature_brief as mod
        self._orig_root = mod.ROOT
        self._tmp_configs = Path(self.tmpdir) / "configs"
        self._tmp_runs = Path(self.tmpdir) / "runs"
        self._tmp_schemas = Path(self.tmpdir) / "schemas"

        # Copy projects.json
        self._tmp_configs.mkdir(parents=True, exist_ok=True)
        orig_projects = ROOT / "configs" / "projects.json"
        shutil.copy2(orig_projects, self._tmp_configs / "projects.json")

        # Create a test project entry in our temp config
        proj_data = json.loads((self._tmp_configs / "projects.json").read_text())
        proj_data["projects"]["testproject"] = {
            "name": "TestProject",
            "repo_path": str(self.tmpdir),
            "project_type": "test_repo",
            "enabled": True,
        }
        (self._tmp_configs / "projects.json").write_text(json.dumps(proj_data))

        # Create temp schemas
        self._tmp_schemas.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FEATURE_BRIEF_SCHEMA, self._tmp_schemas / "feature_brief.schema.json")
        shutil.copy2(FEATURE_QUEUE_SCHEMA, self._tmp_schemas / "feature_queue.schema.json")

        mod.ROOT = Path(self.tmpdir)
        mod.FEATURE_BRIEF_SCHEMA = self._tmp_schemas / "feature_brief.schema.json"
        mod.FEATURE_QUEUE_SCHEMA = self._tmp_schemas / "feature_queue.schema.json"

    def tearDown(self):
        import scripts.create_feature_brief as mod
        mod.ROOT = self._orig_root
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_minimal_brief_creation(self):
        """A minimal brief with only required args should succeed."""
        brief_data, queue_entry, brief_dir = create_feature_brief(
            project_id="testproject",
            title="Minimal Feature",
            goal="Test goal",
            behavior="Test behavior",
            must_haves=["Must have one"],
        )
        self.assertEqual(brief_data["project_id"], "testproject")
        self.assertEqual(brief_data["title"], "Minimal Feature")
        self.assertEqual(brief_data["high_level_goal"], "Test goal")
        self.assertEqual(brief_data["desired_behavior"], "Test behavior")
        self.assertIn("feat_minimal_feature", brief_data["feature_id"])
        self.assertEqual(brief_data["status"], "brief_only")
        self.assertEqual(queue_entry["title"], "Minimal Feature")

    def test_full_brief_creation(self):
        """A full brief with all optional fields should succeed."""
        brief_data, queue_entry, brief_dir = create_feature_brief(
            project_id="testproject",
            title="Full Featured Test",
            goal="Test full feature",
            behavior="All behaviors work",
            must_haves=["Must one", "Must two"],
            nice_to_haves=["Nice one"],
            constraints=["Constraint A"],
            out_of_scope=["Out scope B"],
            risk_level="low",
            target_project_area="agent planning",
            human_priority=1,
        )
        self.assertEqual(brief_data["risk_level"], "low")
        self.assertEqual(brief_data["human_priority"], 1)
        self.assertEqual(brief_data["target_project_area"], "agent planning")
        self.assertEqual(len(brief_data["must_have_requirements"]), 2)
        self.assertEqual(len(brief_data["nice_to_have_requirements"]), 1)
        self.assertEqual(len(brief_data["constraints"]), 1)
        self.assertEqual(len(brief_data["out_of_scope"]), 1)

    def test_rejects_invalid_project_id(self):
        """Creating a brief with an unknown project should raise SystemExit."""
        with self.assertRaises(SystemExit) as ctx:
            create_feature_brief(
                project_id="nonexistentproject",
                title="Bad Project",
                goal="Goal",
                behavior="Behavior",
                must_haves=["Must"],
            )
        self.assertIn("unknown_project_id", str(ctx.exception))

    def test_rejects_missing_title(self):
        """Creating a brief with empty title should raise SystemExit."""
        with self.assertRaises(SystemExit) as ctx:
            create_feature_brief(
                project_id="testproject",
                title="",
                goal="Goal",
                behavior="Behavior",
                must_haves=["Must"],
            )
        self.assertIn("--title", str(ctx.exception))

    def test_rejects_missing_goal(self):
        """Creating a brief with empty goal should raise SystemExit."""
        with self.assertRaises(SystemExit) as ctx:
            create_feature_brief(
                project_id="testproject",
                title="Has Title",
                goal="",
                behavior="Behavior",
                must_haves=["Must"],
            )
        self.assertIn("--goal", str(ctx.exception))

    def test_rejects_missing_behavior(self):
        """Creating a brief with empty behavior should raise SystemExit."""
        with self.assertRaises(SystemExit) as ctx:
            create_feature_brief(
                project_id="testproject",
                title="Has Title",
                goal="Goal",
                behavior="",
                must_haves=["Must"],
            )
        self.assertIn("--behavior", str(ctx.exception))

    def test_artifacts_written_to_disk(self):
        """Brief artifacts should be written to the expected paths."""
        brief_data, queue_entry, brief_dir = create_feature_brief(
            project_id="testproject",
            title="Disk Write Test",
            goal="Test goal",
            behavior="Test behavior",
            must_haves=["Must"],
        )
        self.assertTrue((brief_dir / "FEATURE_BRIEF.json").exists())
        self.assertTrue((brief_dir / "FEATURE_BRIEF.md").exists())

    def test_queue_includes_created_feature(self):
        """The feature queue should include the newly created feature."""
        _, queue_entry, _ = create_feature_brief(
            project_id="testproject",
            title="Queue Test Feature",
            goal="Goal",
            behavior="Behavior",
            must_haves=["Must"],
        )
        import scripts.create_feature_brief as mod
        queue_path = Path(self.tmpdir) / "runs" / "testproject" / "feature_queue" / "FEATURE_QUEUE.json"
        self.assertTrue(queue_path.exists())
        queue_data = json.loads(queue_path.read_text())
        feature_ids = [f["feature_id"] for f in queue_data.get("features", [])]
        self.assertIn(queue_entry["feature_id"], feature_ids)


class TestMultiProjectSupport(unittest.TestCase):
    """Test that multiple projects can have separate feature queues."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import scripts.create_feature_brief as mod
        self._orig_root = mod.ROOT

        self._tmp_configs = Path(self.tmpdir) / "configs"
        self._tmp_runs = Path(self.tmpdir) / "runs"
        self._tmp_schemas = Path(self.tmpdir) / "schemas"
        self._tmp_configs.mkdir(parents=True, exist_ok=True)
        self._tmp_schemas.mkdir(parents=True, exist_ok=True)

        orig_projects = ROOT / "configs" / "projects.json"
        shutil.copy2(orig_projects, self._tmp_configs / "projects.json")

        proj_data = json.loads((self._tmp_configs / "projects.json").read_text())
        proj_data["projects"]["multi_a"] = {
            "name": "ProjectA",
            "repo_path": str(self.tmpdir),
            "project_type": "test_repo",
            "enabled": True,
        }
        proj_data["projects"]["multi_b"] = {
            "name": "ProjectB",
            "repo_path": str(self.tmpdir),
            "project_type": "test_repo",
            "enabled": True,
        }
        (self._tmp_configs / "projects.json").write_text(json.dumps(proj_data))

        shutil.copy2(FEATURE_BRIEF_SCHEMA, self._tmp_schemas / "feature_brief.schema.json")
        shutil.copy2(FEATURE_QUEUE_SCHEMA, self._tmp_schemas / "feature_queue.schema.json")

        mod.ROOT = Path(self.tmpdir)
        mod.FEATURE_BRIEF_SCHEMA = self._tmp_schemas / "feature_brief.schema.json"
        mod.FEATURE_QUEUE_SCHEMA = self._tmp_schemas / "feature_queue.schema.json"

    def tearDown(self):
        import scripts.create_feature_brief as mod
        mod.ROOT = self._orig_root
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_separate_queues_per_project(self):
        """Each project should have its own feature queue."""
        create_feature_brief(
            project_id="multi_a",
            title="Project A Feature",
            goal="Goal A",
            behavior="Behavior A",
            must_haves=["Must A"],
        )
        create_feature_brief(
            project_id="multi_b",
            title="Project B Feature",
            goal="Goal B",
            behavior="Behavior B",
            must_haves=["Must B"],
        )

        import scripts.create_feature_brief as mod
        queue_a = Path(self.tmpdir) / "runs" / "multi_a" / "feature_queue" / "FEATURE_QUEUE.json"
        queue_b = Path(self.tmpdir) / "runs" / "multi_b" / "feature_queue" / "FEATURE_QUEUE.json"

        self.assertTrue(queue_a.exists())
        self.assertTrue(queue_b.exists())

        data_a = json.loads(queue_a.read_text())
        data_b = json.loads(queue_b.read_text())

        self.assertEqual(data_a["project_id"], "multi_a")
        self.assertEqual(data_b["project_id"], "multi_b")

        titles_a = [f["title"] for f in data_a.get("features", [])]
        titles_b = [f["title"] for f in data_b.get("features", [])]

        self.assertIn("Project A Feature", titles_a)
        self.assertNotIn("Project B Feature", titles_a)
        self.assertIn("Project B Feature", titles_b)
        self.assertNotIn("Project A Feature", titles_b)


class TestQueueStatusBehavior(unittest.TestCase):
    """Test queue status behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import scripts.create_feature_brief as mod
        self._orig_root = mod.ROOT

        self._tmp_configs = Path(self.tmpdir) / "configs"
        self._tmp_schemas = Path(self.tmpdir) / "schemas"
        self._tmp_configs.mkdir(parents=True, exist_ok=True)
        self._tmp_schemas.mkdir(parents=True, exist_ok=True)

        orig_projects = ROOT / "configs" / "projects.json"
        shutil.copy2(orig_projects, self._tmp_configs / "projects.json")

        proj_data = json.loads((self._tmp_configs / "projects.json").read_text())
        proj_data["projects"]["statetest"] = {
            "name": "StateTest",
            "repo_path": str(self.tmpdir),
            "project_type": "test_repo",
            "enabled": True,
        }
        (self._tmp_configs / "projects.json").write_text(json.dumps(proj_data))

        shutil.copy2(FEATURE_BRIEF_SCHEMA, self._tmp_schemas / "feature_brief.schema.json")
        shutil.copy2(FEATURE_QUEUE_SCHEMA, self._tmp_schemas / "feature_queue.schema.json")

        mod.ROOT = Path(self.tmpdir)
        mod.FEATURE_BRIEF_SCHEMA = self._tmp_schemas / "feature_brief.schema.json"
        mod.FEATURE_QUEUE_SCHEMA = self._tmp_schemas / "feature_queue.schema.json"

    def tearDown(self):
        import scripts.create_feature_brief as mod
        mod.ROOT = self._orig_root
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_new_brief_has_brief_only_status(self):
        """Newly created briefs should default to brief_only status."""
        brief_data, _, _ = create_feature_brief(
            project_id="statetest",
            title="Status Test",
            goal="Goal",
            behavior="Behavior",
            must_haves=["Must"],
        )
        self.assertEqual(brief_data["status"], "brief_only")

    def test_queue_status_matches_brief(self):
        """Queue entry status should match the brief's status."""
        import scripts.create_feature_brief as mod
        _, queue_entry, _ = create_feature_brief(
            project_id="statetest",
            title="Queue Status Test",
            goal="Goal",
            behavior="Behavior",
            must_haves=["Must"],
        )
        self.assertEqual(queue_entry["status"], "brief_only")


class TestMalformedArtifacts(unittest.TestCase):
    """Test that validation fails on malformed queue/brief artifacts."""

    def setUp(self):
        import scripts.create_feature_brief as mod
        self._orig_root = mod.ROOT
        self.tmpdir = tempfile.mkdtemp()

        self._tmp_configs = Path(self.tmpdir) / "configs"
        self._tmp_schemas = Path(self.tmpdir) / "schemas"
        self._tmp_configs.mkdir(parents=True, exist_ok=True)
        self._tmp_schemas.mkdir(parents=True, exist_ok=True)

        orig_projects = ROOT / "configs" / "projects.json"
        shutil.copy2(orig_projects, self._tmp_configs / "projects.json")

        proj_data = json.loads((self._tmp_configs / "projects.json").read_text())
        proj_data["projects"]["malformedtest"] = {
            "name": "MalformedTest",
            "repo_path": str(self.tmpdir),
            "project_type": "test_repo",
            "enabled": True,
        }
        (self._tmp_configs / "projects.json").write_text(json.dumps(proj_data))

        shutil.copy2(FEATURE_BRIEF_SCHEMA, self._tmp_schemas / "feature_brief.schema.json")
        shutil.copy2(FEATURE_QUEUE_SCHEMA, self._tmp_schemas / "feature_queue.schema.json")

        mod.ROOT = Path(self.tmpdir)
        mod.FEATURE_BRIEF_SCHEMA = self._tmp_schemas / "feature_brief.schema.json"
        mod.FEATURE_QUEUE_SCHEMA = self._tmp_schemas / "feature_queue.schema.json"

    def tearDown(self):
        import scripts.create_feature_brief as mod
        mod.ROOT = self._orig_root
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invalid_json_queue_rejected_by_validation(self):
        """Malformed JSON in FEATURE_QUEUE.json should fail validation."""
        # Create a valid brief first so we have the queue file
        create_feature_brief(
            project_id="malformedtest",
            title="Test Brief",
            goal="Goal",
            behavior="Behavior",
            must_haves=["Must"],
        )

        import scripts.create_feature_brief as mod
        queue_path = Path(self.tmpdir) / "runs" / "malformedtest" / "feature_queue" / "FEATURE_QUEUE.json"

        # Corrupt the JSON
        queue_path.write_text("{invalid json content")

        from scripts.validate_agent_run import CheckRecorder, validate_phase21_feature_artifacts
        recorder = CheckRecorder()
        try:
            validate_phase21_feature_artifacts(recorder, Path(self.tmpdir) / "runs" / "malformedtest" / "feature_queue")
        except Exception:
            pass  # We expect failures

        failures = [c for c in recorder.checks if c["status"] == "fail"]
        self.assertTrue(len(failures) > 0, "Validation should fail on malformed JSON")

    def test_missing_required_fields_rejected_by_validation(self):
        """Brief with missing required fields should fail validation."""
        create_feature_brief(
            project_id="malformedtest",
            title="Test Brief",
            goal="Goal",
            behavior="Behavior",
            must_haves=["Must"],
        )

        import scripts.create_feature_brief as mod
        brief_dir = Path(self.tmpdir) / "runs" / "malformedtest" / "feature_briefs" / "feat_test_brief"
        brief_json = brief_dir / "FEATURE_BRIEF.json"
        data = json.loads(brief_json.read_text())

        # Remove required fields
        del data["title"]
        del data["high_level_goal"]
        brief_json.write_text(json.dumps(data))

        from scripts.validate_agent_run import CheckRecorder, _validate_phase21_brief
        recorder = CheckRecorder()
        try:
            _validate_phase21_brief(recorder, "test_prefix", brief_json)
        except Exception:
            pass  # We expect failures

        failures = [c for c in recorder.checks if c["status"] == "fail"]
        self.assertTrue(len(failures) > 0, "Validation should fail on missing required fields")


class TestNoPhase21Execution(unittest.TestCase):
    """Test that Phase 21 path does not enable model calls or OpenHands execution."""

    def test_created_brief_has_no_execution_flags(self):
        """A created feature brief must not contain any execution-enabling flags."""
        tmpdir = tempfile.mkdtemp()
        try:
            import scripts.create_feature_brief as mod
            orig_root = mod.ROOT

            tmp_configs = Path(tmpdir) / "configs"
            tmp_schemas = Path(tmpdir) / "schemas"
            tmp_configs.mkdir(parents=True, exist_ok=True)
            tmp_schemas.mkdir(parents=True, exist_ok=True)

            orig_projects = ROOT / "configs" / "projects.json"
            shutil.copy2(orig_projects, tmp_configs / "projects.json")

            proj_data = json.loads((tmp_configs / "projects.json").read_text())
            proj_data["projects"]["noinctest"] = {
                "name": "NoExecTest",
                "repo_path": str(tmpdir),
                "project_type": "test_repo",
                "enabled": True,
            }
            (tmp_configs / "projects.json").write_text(json.dumps(proj_data))

            shutil.copy2(FEATURE_BRIEF_SCHEMA, tmp_schemas / "feature_brief.schema.json")
            shutil.copy2(FEATURE_QUEUE_SCHEMA, tmp_schemas / "feature_queue.schema.json")

            mod.ROOT = Path(tmpdir)
            mod.FEATURE_BRIEF_SCHEMA = tmp_schemas / "feature_brief.schema.json"
            mod.FEATURE_QUEUE_SCHEMA = tmp_schemas / "feature_queue.schema.json"

            _, _, brief_dir = create_feature_brief(
                project_id="noinctest",
                title="No Exec Test",
                goal="Goal",
                behavior="Behavior",
                must_haves=["Must"],
            )

            # Check FEATURE_BRIEF.json for execution flags
            unsafe_flags = [
                "model_calls_enabled",
                "execution_enabled",
                "source_writes_enabled",
                "auto_merge_enabled",
                "auto_push_enabled",
                "apply_canonical_write",
                "allow_canonical_write",
                "commit_enabled",
                "push_enabled",
                "merge_enabled",
                "pr_creation_enabled",
            ]

            brief_json_text = (brief_dir / "FEATURE_BRIEF.json").read_text()
            queue_path = Path(tmpdir) / "runs" / "noinctest" / "feature_queue" / "FEATURE_QUEUE.json"
            queue_json_text = queue_path.read_text()

            for flag in unsafe_flags:
                self.assertNotIn(flag, brief_json_text, f"FEATURE_BRIEF.json should not contain '{flag}'")
                self.assertNotIn(flag, queue_json_text, f"FEATURE_QUEUE.json should not contain '{flag}'")

            mod.ROOT = orig_root
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestStableSlugIds(unittest.TestCase):
    """Test stable feature_id generation."""

    def test_same_title_produces_same_slug(self):
        slug1 = slug_from_title("My Feature Brief")
        slug2 = slug_from_title("My Feature Brief")
        self.assertEqual(slug1, slug2)

    def test_different_titles_produce_different_slugs(self):
        slug1 = slug_from_title("Feature A")
        slug2 = slug_from_title("Feature B")
        self.assertNotEqual(slug1, slug2)

    def test_slug_is_reproducible_across_runs(self):
        """Multiple calls in different contexts produce same result."""
        import scripts.create_feature_brief as mod
        tmpdir = tempfile.mkdtemp()
        try:
            orig_root = mod.ROOT
            tmp_configs = Path(tmpdir) / "configs"
            tmp_configs.mkdir(parents=True, exist_ok=True)

            orig_projects = ROOT / "configs" / "projects.json"
            shutil.copy2(orig_projects, tmp_configs / "projects.json")

            proj_data = json.loads((tmp_configs / "projects.json").read_text())
            proj_data["projects"]["slugtest"] = {
                "name": "SlugTest",
                "repo_path": str(tmpdir),
                "project_type": "test_repo",
                "enabled": True,
            }
            (tmp_configs / "projects.json").write_text(json.dumps(proj_data))

            mod.ROOT = Path(tmpdir)

            # Create two briefs with same title — second should overwrite/update first
            _, entry1, _ = create_feature_brief(
                project_id="slugtest",
                title="Duplicate Slug Test",
                goal="Goal 1",
                behavior="Behavior 1",
                must_haves=["Must"],
            )
            feature_id_1 = entry1["feature_id"]

            _, entry2, _ = create_feature_brief(
                project_id="slugtest",
                title="Duplicate Slug Test",
                goal="Goal 2",
                behavior="Behavior 2",
                must_haves=["Must"],
            )
            feature_id_2 = entry2["feature_id"]

            self.assertEqual(feature_id_1, feature_id_2)

            # Queue should still have exactly one entry for this title
            queue_path = Path(tmpdir) / "runs" / "slugtest" / "feature_queue" / "FEATURE_QUEUE.json"
            queue_data = json.loads(queue_path.read_text())
            matching = [f for f in queue_data.get("features", []) if f["title"] == "Duplicate Slug Test"]
            self.assertEqual(len(matching), 1)

            mod.ROOT = orig_root
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
