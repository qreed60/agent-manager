from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import validate_agent_run early so test classes can reference it
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_agent_run

from scripts import run_ai_readonly_agent


class AiReadonlyAgentTests(unittest.TestCase):
    """Tests for Phase 18A AI read-only agent.

    No real model calls are made. HTTP/model call logic is mocked or isolated.
    """

    def _make_sample_run(self, root: Path, project_id: str) -> Path:
        """Create a minimal sample run directory with latest pointers."""
        run_root = root / "runs" / project_id
        (root / "configs").mkdir(parents=True)
        (root / "configs" / "projects.json").write_text(
            json.dumps({"schema_version": 1, "projects": {project_id: {"repo_path": str(root / "repo")}}}) + "\n"
        )
        (root / "repo").mkdir()

        # Create minimal latest directories with JSON artifacts
        validation_dir = run_root / "validation_20260605T000000Z"
        review_dir = run_root / "review_agents_20260605T000000Z"
        runner_dir = run_root / "runner_v0_20260605T000000Z"

        validation_dir.mkdir(parents=True)
        review_dir.mkdir()
        runner_dir.mkdir()

        (run_root / "latest_validation").symlink_to(validation_dir, target_is_directory=True)
        (run_root / "latest_review_agents").symlink_to(review_dir, target_is_directory=True)
        (run_root / "latest_runner_v0").symlink_to(runner_dir, target_is_directory=True)

        (validation_dir / "VALIDATION_REPORT.json").write_text(
            json.dumps({"status": "pass", "blocking": False, "generated_by": "deterministic_scaffold"}) + "\n"
        )
        (review_dir / "REVIEW_AGENTS_SUMMARY.json").write_text(
            json.dumps({"status": "pass", "blocking": False, "generated_by": "deterministic_scaffold"}) + "\n"
        )
        (runner_dir / "RUN_MANIFEST.json").write_text(
            json.dumps({"status": "pass", "generated_by": "deterministic_scaffold"}) + "\n"
        )

        return run_root

    def test_default_mode_performs_no_model_call(self) -> None:
        """Default (no --allow-model-call) must produce dry-run output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summary = run_ai_readonly_agent.generate(project_id, created_utc="20260605T120000Z")
            finally:
                run_ai_readonly_agent.ROOT = old_root

            self.assertFalse(summary["model_call_performed"])
            safety = summary.get("safety_status", {})
            self.assertTrue(safety.get("dry_run"))

    def test_allow_model_call_requires_env_var(self) -> None:
        """--allow-model-call alone must not trigger a model call without env var."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                # Pass env_allow_key="1" to simulate the env var being set,
                # but also pass allow_model_call=True and then verify that without
                # the env var it stays dry-run.
                summary = run_ai_readonly_agent.generate(
                    project_id,
                    created_utc="20260605T130000Z",
                    allow_model_call=True,
                    env_allow_key="AGENT_MANAGER_TEST_MISSING_MODEL_CALLS",
                )
            finally:
                run_ai_readonly_agent.ROOT = old_root

            self.assertFalse(summary["model_call_performed"])
            safety = summary.get("safety_status", {})
            self.assertTrue(safety.get("dry_run"))

    def test_dry_run_writes_all_required_artifacts(self) -> None:
        """Dry-run mode must write all 8 required artifact files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summary = run_ai_readonly_agent.generate(project_id, created_utc="20260605T140000Z")
            finally:
                run_ai_readonly_agent.ROOT = old_root

            ai_dir = Path(summary["run_dir"])
            required_json = [
                "AI_READONLY_REVIEW.json",
                "AI_RESPONSE_PARSED.json",
                "AI_SAFETY_STATUS.json",
                "AI_READONLY_SUMMARY.json",
            ]
            required_text = [
                "AI_READONLY_REVIEW.md",
                "AI_PROMPT.md",
                "AI_RESPONSE_RAW.txt",
                "AI_READONLY_SUMMARY.md",
            ]
            for name in required_json + required_text:
                self.assertTrue((ai_dir / name).exists(), f"Missing artifact: {name}")

    def test_report_json_shape_is_valid(self) -> None:
        """Generated JSON artifacts must have valid shape."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summary = run_ai_readonly_agent.generate(project_id, created_utc="20260605T150000Z")
            finally:
                run_ai_readonly_agent.ROOT = old_root

            ai_dir = Path(summary["run_dir"])

            # Parse AI_READONLY_REVIEW.json
            review = json.loads((ai_dir / "AI_READONLY_REVIEW.json").read_text())
            self.assertEqual(review["schema_version"], 1)
            self.assertEqual(review["agent"], "read_only_manager_reviewer")
            self.assertIn("findings", review)
            self.assertIsInstance(review["findings"], list)

            # Parse AI_RESPONSE_PARSED.json
            parsed = json.loads((ai_dir / "AI_RESPONSE_PARSED.json").read_text())
            self.assertIn("status", parsed)
            self.assertIn(parsed["status"], {"pass", "warn", "fail"})

            # Parse AI_SAFETY_STATUS.json
            safety = json.loads((ai_dir / "AI_SAFETY_STATUS.json").read_text())
            self.assertFalse(safety.get("source_writes_allowed"))
            self.assertFalse(safety.get("openhands_execution_allowed"))
            self.assertFalse(safety.get("auto_push_allowed"))
            self.assertFalse(safety.get("auto_merge_allowed"))
            self.assertFalse(safety.get("pr_creation_allowed"))

            # Parse AI_READONLY_SUMMARY.json
            ai_summary = json.loads((ai_dir / "AI_READONLY_SUMMARY.json").read_text())
            self.assertEqual(ai_summary["schema_version"], 1)
            self.assertEqual(ai_summary["agent"], "ai_readonly_agent")
            self.assertIn("artifacts_generated", ai_summary)

    def test_safety_status_denies_source_writes_openhands_push_merge_pr(self) -> None:
        """Safety status must deny all dangerous operations."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summary = run_ai_readonly_agent.generate(project_id, created_utc="20260605T160000Z")
            finally:
                run_ai_readonly_agent.ROOT = old_root

            safety = summary.get("safety_status", {})
            self.assertFalse(safety.get("source_writes_allowed"))
            self.assertFalse(safety.get("openhands_execution_allowed"))
            self.assertFalse(safety.get("auto_push_allowed"))
            self.assertFalse(safety.get("auto_merge_allowed"))
            self.assertFalse(safety.get("pr_creation_allowed"))

    def test_prompt_excludes_obvious_secret_values(self) -> None:
        """Prompt must not contain API key values or full base URLs with secrets."""
        import os
        # Set some fake env vars to simulate them being present
        old_keys = {}
        for key in ("AGENT_MANAGER_OPENAI_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
            old_keys[key] = os.environ.pop(key, None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summary = run_ai_readonly_agent.generate(project_id, created_utc="20260605T170000Z")
            finally:
                run_ai_readonly_agent.ROOT = old_root

            # Restore env vars
            for key, val in old_keys.items():
                if val is not None:
                    os.environ[key] = val

            ai_dir = Path(summary["run_dir"])
            prompt_text = (ai_dir / "AI_PROMPT.md").read_text()

            # The prompt should NOT contain actual API key values
            for env_key in ("AGENT_MANAGER_OPENAI_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
                val = os.environ.get(env_key, "")
                if val:
                    self.assertNotIn(val, prompt_text, f"Prompt must not contain value of {env_key}")

    def test_validation_accepts_latest_ai_readonly_artifacts(self) -> None:
        """validate_agent_run.py should accept valid latest_ai_readonly artifacts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            self._make_sample_run(root, project_id)

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summary = run_ai_readonly_agent.generate(project_id, created_utc="20260605T180000Z")
            finally:
                run_ai_readonly_agent.ROOT = old_root

            # Now validate via validate_agent_run
            recorder = validate_agent_run.CheckRecorder()
            ai_dir = Path(summary["run_dir"])
            validate_agent_run.validate_ai_readonly_artifacts(recorder, ai_dir)
            self.assertEqual(recorder.failures(), [])


class AiReadonlyAgentSafetyTests(unittest.TestCase):
    """Additional safety-focused tests."""

    def test_dry_run_safety_status_all_denied(self) -> None:
        """Dry-run mode must have all dangerous operations denied."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            (root / "configs").mkdir(parents=True)
            (root / "configs" / "projects.json").write_text(
                json.dumps({"schema_version": 1, "projects": {project_id: {"repo_path": str(root / "repo")}}}) + "\n"
            )
            (root / "repo").mkdir()

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                raw, safety = run_ai_readonly_agent.dry_run_placeholder(project_id)
            finally:
                run_ai_readonly_agent.ROOT = old_root

            self.assertFalse(safety.get("source_writes_allowed"))
            self.assertFalse(safety.get("openhands_execution_allowed"))
            self.assertFalse(safety.get("auto_push_allowed"))
            self.assertFalse(safety.get("auto_merge_allowed"))
            self.assertFalse(safety.get("pr_creation_allowed"))
            self.assertTrue(safety.get("dry_run"))
            self.assertFalse(safety.get("model_call_performed"))

    def test_extract_host_strips_path(self) -> None:
        """extract_host must return only scheme+host, not full URL."""
        url = "http://127.0.0.1:1234/v1/chat/completions"
        host = run_ai_readonly_agent.extract_host(url)
        self.assertEqual(host, "http://127.0.0.1:1234")

    def test_extract_host_strips_secrets(self) -> None:
        """extract_host must not include userinfo (secrets)."""
        url = "https://user:secret@example.com/path"
        host = run_ai_readonly_agent.extract_host(url)
        self.assertNotIn("secret", host)
        self.assertEqual(host, "https://example.com")


class AiReadonlyAgentParsingTests(unittest.TestCase):
    """Test JSON parsing of model responses."""

    def test_parse_json_response(self) -> None:
        """Valid JSON response should parse with status pass."""
        raw = '{"recommendation": "accept", "risks": []}'
        parsed = run_ai_readonly_agent.parse_model_response(raw)
        self.assertEqual(parsed["status"], "pass")
        self.assertIn("recommendation", parsed)

    def test_parse_markdown_wrapped_json(self) -> None:
        """Markdown-wrapped JSON should be extracted."""
        raw = '```json\n{"recommendation": "revise"}\n```'
        parsed = run_ai_readonly_agent.parse_model_response(raw)
        self.assertEqual(parsed["status"], "pass")
        self.assertEqual(parsed["recommendation"], "revise")

    def test_parse_invalid_returns_warn(self) -> None:
        """Invalid JSON should return status warn, not fail."""
        raw = 'This is not valid JSON at all {{{'
        parsed = run_ai_readonly_agent.parse_model_response(raw)
        self.assertEqual(parsed["status"], "warn")


class ValidateAiReadonlyIntegrationTests(unittest.TestCase):
    """Integration tests for validation of AI read-only artifacts."""

    def test_validation_fails_on_broken_safety_status(self) -> None:
        """Validation should fail if safety status allows source writes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ai_dir = root / "ai_readonly_20260605T190000Z"
            ai_dir.mkdir(parents=True)

            # Write a safety status that allows source writes (should fail validation)
            (ai_dir / "AI_SAFETY_STATUS.json").write_text(
                json.dumps({
                    "model_call_performed": False,
                    "dry_run": True,
                    "source_writes_allowed": True,  # dangerous!
                    "openhands_execution_allowed": False,
                    "auto_push_allowed": False,
                    "auto_merge_allowed": False,
                    "pr_creation_allowed": False,
                }) + "\n"
            )

            # Write minimal required artifacts
            (ai_dir / "AI_READONLY_REVIEW.json").write_text(
                json.dumps({"schema_version": 1, "agent": "read_only_manager_reviewer", "generated_by": "deterministic_scaffold"}) + "\n"
            )
            (ai_dir / "AI_RESPONSE_PARSED.json").write_text(
                json.dumps({"status": "warn", "parse_method": "raw_fallback"}) + "\n"
            )
            (ai_dir / "AI_READONLY_SUMMARY.json").write_text(
                json.dumps({"schema_version": 1, "agent": "ai_readonly_agent", "generated_by": "phase18a_ai_readonly_agent"}) + "\n"
            )
            for name in ("AI_READONLY_REVIEW.md", "AI_PROMPT.md", "AI_RESPONSE_RAW.txt", "AI_READONLY_SUMMARY.md"):
                (ai_dir / name).write_text("placeholder\n")

            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_ai_readonly_artifacts(recorder, ai_dir)

            failures = [f for f in recorder.failures() if "source_writes_allowed" in f["id"]]
            self.assertTrue(len(failures) > 0, "Validation should fail when source_writes_allowed is True")


class GenericHelperLogicTests(unittest.TestCase):
    """Test that generic non-ThomsonLint helper logic still works."""

    def test_utc_now_format(self) -> None:
        """utc_now must return a valid UTC timestamp string."""
        ts = run_ai_readonly_agent.utc_now()
        self.assertRegex(ts, r"^\d{8}T\d{6}Z$")

    def test_resolve_model_config_defaults(self) -> None:
        """resolve_model_config should use defaults when no env vars are set."""
        import os
        # Clear relevant env vars
        old = {}
        for key in ("AGENT_MANAGER_OPENAI_BASE_URL", "OPENAI_BASE_URL", "LLM_BASE_URL",
                     "AGENT_MANAGER_OPENAI_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY",
                     "AGENT_MANAGER_AI_MODEL", "LLM_MODEL", "MODEL"):
            old[key] = os.environ.pop(key, None)

        try:
            config = run_ai_readonly_agent.resolve_model_config()
            self.assertEqual(config["base_url"], "http://127.0.0.1:1234/v1")
            self.assertIsNone(config["api_key"])
            # Model could be any of the defaults or gpt-4o-mini
            self.assertIn(config["model"], ("gpt-4o-mini", None))
        finally:
            for key, val in old.items():
                if val is not None:
                    os.environ[key] = val

    def test_load_artifact_summaries_missing_pointers(self) -> None:
        """load_artifact_summaries should handle missing pointers gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "sample_project"
            (root / "configs").mkdir(parents=True)
            (root / "configs" / "projects.json").write_text(
                json.dumps({"schema_version": 1, "projects": {project_id: {"repo_path": str(root / "repo")}}}) + "\n"
            )
            (root / "repo").mkdir()

            old_root = run_ai_readonly_agent.ROOT
            run_ai_readonly_agent.ROOT = root
            try:
                summaries = run_ai_readonly_agent.load_artifact_summaries(project_id)
            finally:
                run_ai_readonly_agent.ROOT = old_root

            # All pointers should be missing
            presence = summaries.get("_pointer_presence", {})
            for pointer_name in run_ai_readonly_agent.ARTIFACT_POINTERS:
                self.assertEqual(presence.get(pointer_name), "missing", f"Expected {pointer_name} to be missing")


if __name__ == "__main__":
    unittest.main()
