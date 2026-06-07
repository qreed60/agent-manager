"""Regression tests for Phase 18K OpenHands manual gate request bridge."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_openhands_manual_gate_request as request_script
from scripts import validate_agent_run


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


class OpenHandsManualGateRequestTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        project_id = "sample_project"
        repo = root / "sample_repo"
        state_dir = repo / ".agent_manager"
        state_dir.mkdir(parents=True)
        (root / "configs").mkdir()
        _write_json(
            root / "configs" / "projects.json",
            {
                "schema_version": 1,
                "projects": {
                    project_id: {
                        "repo_path": str(repo),
                        "project_state_dir": ".agent_manager",
                        "server_state_dir": f"runs/{project_id}",
                        "worktree_root": f"worktrees/{project_id}",
                        "validation_adapter": "generic_git",
                        "enabled": True,
                    }
                },
            },
        )
        _write_json(
            state_dir / "OBJECTIVE_BACKLOG.json",
            {
                "schema_version": 1,
                "project_id": project_id,
                "objectives": [{"id": "active_objective", "status": "active"}],
            },
        )
        return tmp, root, project_id

    def run_request(self, root: Path, project_id: str, **kwargs: object) -> dict:
        old_root = request_script.ROOT
        request_script.ROOT = root
        try:
            return request_script.prepare_request(project_id, created_utc="20260607T000000Z", **kwargs)
        finally:
            request_script.ROOT = old_root

    def test_request_generation_with_task_text(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="Create docs/example.md.",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            self.assertEqual(request["status"], "pass")
            self.assertEqual(request["task_source"], "task_text")
            self.assertEqual(request["expected_changed_files"], ["docs/example.md"])
            self.assertEqual(request["objective_id"], "active_objective")
            self.assertTrue(Path(request["command_file"]).exists())
            self.assertTrue((root / "runs" / project_id / "latest_openhands_manual_gate_request").exists())

    def test_request_generation_with_task_file(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            task_file = root / "task.md"
            task_file.write_text("Create docs/example.md.\n")
            request = self.run_request(
                root,
                project_id,
                task_file_arg=str(task_file),
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            self.assertEqual(request["status"], "pass")
            self.assertEqual(request["task_source"], "task_file")
            self.assertEqual(request["task_text"], "Create docs/example.md.\n")
            self.assertEqual(request["task_file"], str(task_file))

    def test_exactly_one_task_source_required(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(root, project_id, allowed_files=["docs/example.md"])
            self.assertEqual(request["status"], "fail")
            self.assertIn("exactly one", request["refusal_reason"])
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                task_file_arg=str(root / "task.md"),
                allowed_files=["docs/example.md"],
            )
            self.assertEqual(request["status"], "fail")
            self.assertIn("exactly one", request["refusal_reason"])

    def test_allowed_files_required(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(root, project_id, task_text_arg="text")
            self.assertEqual(request["status"], "fail")
            self.assertIn("at least one --allowed-file", request["refusal_reason"])

    def test_absolute_allowed_file_rejected(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(root, project_id, task_text_arg="text", allowed_files=["/tmp/example.md"])
            self.assertEqual(request["status"], "fail")
            self.assertIn("must be relative", request["refusal_reason"])

    def test_parent_traversal_allowed_file_rejected(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(root, project_id, task_text_arg="text", allowed_files=["../example.md"])
            self.assertEqual(request["status"], "fail")
            self.assertIn("parent traversal", request["refusal_reason"])

    def test_expected_changed_file_outside_allowed_files_rejected(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                expected_changed_files=["docs/other.md"],
            )
            self.assertEqual(request["status"], "fail")
            self.assertIn("expected changed file", request["refusal_reason"])

    def test_high_risk_without_stop_condition_fails(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                risk_level="high",
            )
            self.assertEqual(request["status"], "fail")
            self.assertIn("high risk", request["refusal_reason"])

    def test_low_without_validation_commands_warns_but_does_not_fail(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                stop_conditions=["Stop after the allowed file is changed."],
                risk_level="low",
            )
            self.assertEqual(request["status"], "warn")
            self.assertIn("validation_commands is empty", request["refusal_reason"])

    def test_medium_without_validation_commands_warns_but_does_not_fail(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                stop_conditions=["Stop after the allowed file is changed."],
                risk_level="medium",
            )
            self.assertEqual(request["status"], "warn")

    def test_generated_command_contains_manual_gate_runner(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            command = Path(request["command_file"]).read_text()
            self.assertIn("scripts/run_openhands_manual_gate.py", command)

    def test_generated_command_does_not_contain_apply_commit_push_merge_pr_cleanup(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            command = Path(request["command_file"]).read_text().lower()
            for forbidden in ("git apply", "git commit", "git push", "git merge", "gh pr", "--apply", "--allow-canonical-write", "worktree remove"):
                self.assertNotIn(forbidden, command)

    def validate_request_dir(self, request: dict) -> validate_agent_run.CheckRecorder:
        recorder = validate_agent_run.CheckRecorder()
        validate_agent_run.validate_openhands_manual_gate_request(recorder, Path(request["run_dir"]))
        return recorder

    def test_validation_accepts_pass_request(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            self.assertEqual(self.validate_request_dir(request).status(), "pass")

    def test_validation_accepts_warn_request(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            self.assertEqual(request["status"], "warn")
            self.assertEqual(self.validate_request_dir(request).status(), "pass")

    def test_validation_fails_bad_generated_by(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            path = Path(request["run_dir"]) / "OPENHANDS_MANUAL_GATE_REQUEST.json"
            data = json.loads(path.read_text())
            data["generated_by"] = "wrong"
            _write_json(path, data)
            recorder = self.validate_request_dir(request)
            self.assertEqual(recorder.status(), "fail")
            self.assertTrue(any(check["id"] == "openhands_manual_gate_request_generated_by" for check in recorder.failures()))

    def test_validation_fails_unsafe_command_content(self) -> None:
        tmp, root, project_id = self.make_root()
        with tmp:
            request = self.run_request(
                root,
                project_id,
                task_text_arg="text",
                allowed_files=["docs/example.md"],
                validation_commands=["python3 scripts/validate_agent_run.py sample_project"],
                stop_conditions=["Stop after the allowed file is changed."],
            )
            Path(request["command_file"]).write_text("python3 scripts/run_openhands_manual_gate.py sample_project\ngit push\n")
            recorder = self.validate_request_dir(request)
            self.assertEqual(recorder.status(), "fail")
            self.assertTrue(any(check["id"] == "openhands_manual_gate_request_command_safe" for check in recorder.failures()))

    def test_no_openhands_or_model_calls_are_made_in_tests(self) -> None:
        self.assertFalse(hasattr(request_script, "subprocess"))
        shell_text, _markdown = request_script.build_command_files(
            project_id="sample_project",
            task_source="task_text",
            task_file="",
            task_text="text",
            allowed_files=["docs/example.md"],
            validation_commands=[],
        )
        self.assertIn("scripts/run_openhands_manual_gate.py", shell_text)
        self.assertNotIn("OPENAI_API_KEY", shell_text)


if __name__ == "__main__":
    unittest.main()
