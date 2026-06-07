"""Regression tests for Phase 20 overnight OpenHands write task gate."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_overnight_openhands_write_task as overnight
from scripts import validate_agent_run


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


class OvernightOpenHandsWriteTaskTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str, Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        project_id = "sample_project"
        repo = root / "repo"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (repo / "README.md").write_text("sample\n")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (root / "configs").mkdir()
        _write_json(
            root / "configs" / "projects.json",
            {"schema_version": 1, "projects": {project_id: {"repo_path": str(repo), "project_state_dir": ".agent_manager"}}},
        )
        request_dir = root / "runs" / project_id / "request"
        request_dir.mkdir(parents=True)
        self.write_request(request_dir, project_id)
        return tmp, root, project_id, repo, request_dir

    def write_request(self, request_dir: Path, project_id: str, **overrides: object) -> dict:
        request = {
            "schema_version": 1,
            "generated_by": "phase18k_manager_to_openhands_task_packet_bridge",
            "project_id": project_id,
            "created_utc": "20260607T000000Z",
            "run_dir": str(request_dir),
            "objective_id": "objective",
            "objective_source": "test",
            "task_source": "task_text",
            "task_text": "Create docs/example.md.",
            "task_file": "",
            "task_sha256": "x",
            "allowed_files": ["docs/example.md"],
            "expected_changed_files": ["docs/example.md"],
            "validation_commands": ["python3 scripts/validate_agent_run.py sample_project"],
            "stop_conditions": ["Stop after creating the allowed file."],
            "risk_level": "low",
            "command_file": str(request_dir / "OPENHANDS_MANUAL_GATE_COMMAND.sh"),
            "command_markdown_file": str(request_dir / "OPENHANDS_MANUAL_GATE_COMMAND.md"),
            "status": "pass",
            "refusal_reason": "",
            "no_openhands_execution_performed": True,
            "no_apply_commit_push_merge_pr_or_cleanup_performed": True,
        }
        request.update(overrides)
        _write_json(request_dir / "OPENHANDS_MANUAL_GATE_REQUEST.json", request)
        return request

    def env(self, project_id: str, request_dir: Path) -> dict[str, str]:
        return {
            "AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS": "1",
            "AGENT_MANAGER_ENABLE_OPENHANDS": "1",
            "AGENT_MANAGER_OVERNIGHT_OPENHANDS_CONFIRM_PROJECT": project_id,
            "AGENT_MANAGER_OVERNIGHT_OPENHANDS_REQUEST_DIR": str(request_dir),
        }

    def run_script(
        self,
        root: Path,
        project_id: str,
        request_dir: Path,
        *,
        env: dict[str, str] | None = None,
        runner=None,
        confirm_project: str | None = None,
    ) -> dict:
        old_root = overnight.ROOT
        overnight.ROOT = root
        try:
            with patch.dict(os.environ, env or {}, clear=True):
                return overnight.run_overnight_write(
                    project_id,
                    request_dir_arg=str(request_dir),
                    allow_overnight_openhands=True,
                    confirm_project=confirm_project or project_id,
                    created_utc="20260607T000000Z",
                    command_runner=runner or (lambda command: subprocess.CompletedProcess(command, 0, "", "")),
                )
        finally:
            overnight.ROOT = old_root

    def fake_runner(self, root: Path, project_id: str, summaries: list[dict]):
        calls: list[list[str]] = []

        def _runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            summary = summaries[len(calls) - 1]
            run_dir = root / "runs" / project_id / f"openhands_coder_20260607T00000{len(calls)}Z"
            run_dir.mkdir(parents=True)
            _write_json(run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json", summary)
            latest = root / "runs" / project_id / "latest_openhands_coder"
            if latest.exists() or latest.is_symlink():
                latest.unlink()
            latest.symlink_to(run_dir, target_is_directory=True)
            return subprocess.CompletedProcess(command, 0 if summary["status"] == "pass" else 1, "", "")

        _runner.calls = calls  # type: ignore[attr-defined]
        return _runner

    def pass_gate_summary(self) -> dict:
        return {
            "status": "pass",
            "failure_classification": "none",
            "retryable": False,
            "changed_files": ["docs/example.md"],
            "decision_recommendation": "accept_for_manual_review",
            "apply_check_passed": True,
            "applied": False,
            "canonical_repo_clean": True,
        }

    def fail_gate_summary(self, classification: str, retryable: bool) -> dict:
        return {
            "status": "fail",
            "failure_classification": classification,
            "retryable": retryable,
            "changed_files": [],
            "decision_recommendation": None,
            "apply_check_passed": None,
            "applied": False,
            "canonical_repo_clean": True,
        }

    def test_refuses_without_env_gates(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            summary = self.run_script(root, project_id, request_dir, env={})
            self.assertEqual(summary["status"], "fail")
            self.assertIn("AGENT_MANAGER_ENABLE_OVERNIGHT_OPENHANDS", summary["blocked_reason"])

    def test_refuses_project_mismatch(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir), confirm_project="wrong")
            self.assertEqual(summary["status"], "fail")
            self.assertIn("--confirm-project", summary["blocked_reason"])

    def test_refuses_dirty_canonical_repo(self) -> None:
        tmp, root, project_id, repo, request_dir = self.make_root()
        with tmp:
            (repo / "DIRTY.txt").write_text("dirty\n")
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir))
            self.assertEqual(summary["status"], "fail")
            self.assertIn("canonical repo is dirty", summary["blocked_reason"])

    def test_refuses_high_risk_request(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            self.write_request(request_dir, project_id, risk_level="high")
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir))
            self.assertEqual(summary["status"], "fail")
            self.assertIn("low risk", summary["blocked_reason"])

    def test_refuses_consumed_request(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            _write_json(request_dir / overnight.CONSUMED_FILE, {"status": "consumed"})
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir))
            self.assertEqual(summary["status"], "fail")
            self.assertIn("already been consumed", summary["blocked_reason"])

    def test_refuses_unsafe_allowed_files(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            self.write_request(request_dir, project_id, allowed_files=["../bad.md"])
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir))
            self.assertEqual(summary["status"], "fail")
            self.assertIn("unsafe allowed file", summary["blocked_reason"])

    def test_consumes_request_before_live_attempt(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            runner = self.fake_runner(root, project_id, [self.pass_gate_summary()])
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir), runner=runner)
            self.assertEqual(summary["status"], "pass")
            self.assertTrue((request_dir / overnight.CONSUMED_FILE).exists())

    def test_one_successful_attempt_produces_pass(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            runner = self.fake_runner(root, project_id, [self.pass_gate_summary()])
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir), runner=runner)
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(len(summary["attempts"]), 1)
            self.assertEqual(summary["decision_recommendation"], "accept_for_manual_review")

    def test_retryable_first_failure_performs_exactly_one_retry(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            runner = self.fake_runner(root, project_id, [self.fail_gate_summary("exited_0_no_changes", True), self.pass_gate_summary()])
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir), runner=runner)
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(len(summary["attempts"]), 2)

    def test_non_retryable_first_failure_blocks_without_retry(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            runner = self.fake_runner(root, project_id, [self.fail_gate_summary("scope_fail", False)])
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir), runner=runner)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(len(summary["attempts"]), 1)

    def test_retry_failure_after_second_attempt_blocks(self) -> None:
        tmp, root, project_id, _repo, request_dir = self.make_root()
        with tmp:
            runner = self.fake_runner(root, project_id, [self.fail_gate_summary("exited_0_no_changes", True), self.fail_gate_summary("apply_check_fail", True)])
            summary = self.run_script(root, project_id, request_dir, env=self.env(project_id, request_dir), runner=runner)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(len(summary["attempts"]), 2)

    def test_validation_accepts_pass_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"
            _write_json(path, self.valid_summary(status="pass"))
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_overnight_openhands_write_summary(recorder, path)
            self.assertEqual(recorder.status(), "pass")

    def test_validation_accepts_blocked_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"
            data = self.valid_summary(status="blocked")
            data["blocked"] = True
            data["blocked_reason"] = "scope_fail"
            data["recommended_human_action"] = "Inspect artifacts."
            data["selected_attempt_status"] = "fail"
            _write_json(path, data)
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_overnight_openhands_write_summary(recorder, path)
            self.assertEqual(recorder.status(), "pass")

    def valid_summary(self, status: str = "pass") -> dict:
        return {
            "schema_version": 1,
            "generated_by": overnight.GENERATED_BY,
            "project_id": "sample_project",
            "created_utc": "20260607T000000Z",
            "run_dir": "/tmp/run",
            "request_dir": "/tmp/request",
            "request_sha256": "x",
            "objective_id": "objective",
            "risk_level": "low",
            "allowed_files": ["docs/example.md"],
            "expected_changed_files": ["docs/example.md"],
            "max_write_tasks": 1,
            "max_retries_per_task": 1,
            "attempts": [{**self.pass_gate_summary(), "attempt_number": 1, "run_dir": "/tmp/attempt", "canonical_repo_clean": True}],
            "selected_attempt_run_dir": "/tmp/attempt",
            "selected_attempt_status": "pass",
            "changed_files": ["docs/example.md"],
            "decision_recommendation": "accept_for_manual_review",
            "apply_mode": "check_only",
            "apply_check_passed": True,
            "applied": False,
            "canonical_repo_clean_before": True,
            "canonical_repo_clean_after": True,
            "blocked": False,
            "blocked_reason": "",
            "recommended_human_action": "Review artifacts.",
            "status": status,
            "no_apply_commit_push_merge_pr_or_cleanup_performed": True,
        }

    def test_validation_fails_applied_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"
            data = self.valid_summary()
            data["attempts"][0]["applied"] = True
            _write_json(path, data)
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_overnight_openhands_write_summary(recorder, path)
            self.assertEqual(recorder.status(), "fail")

    def test_validation_fails_more_than_two_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"
            data = self.valid_summary()
            data["attempts"] = data["attempts"] * 3
            _write_json(path, data)
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_overnight_openhands_write_summary(recorder, path)
            self.assertEqual(recorder.status(), "fail")

    def test_validation_fails_canonical_repo_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "OVERNIGHT_OPENHANDS_WRITE_SUMMARY.json"
            data = self.valid_summary()
            data["canonical_repo_clean_after"] = False
            _write_json(path, data)
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_overnight_openhands_write_summary(recorder, path)
            self.assertEqual(recorder.status(), "fail")

    def test_morning_report_contains_required_fields(self) -> None:
        report = overnight.build_morning_report(self.valid_summary(), validation_result="pass", review_findings="not run")
        for text in (
            "Selected objective",
            "OpenHands run dir",
            "Changed files",
            "Decision packet recommendation",
            "Apply check result",
            "Validation result",
            "Recommended human action",
            "Canonical repo clean after",
        ):
            self.assertIn(text, report)

    def test_no_openhands_or_model_calls_are_made_in_unit_tests(self) -> None:
        command = overnight.build_manual_gate_command(
            project_id="sample_project",
            request={"task_source": "task_text", "task_text": "text", "allowed_files": ["docs/example.md"]},
            timeout_seconds=300,
            max_prompt_chars=3000,
            env_file="/tmp/env",
        )
        self.assertEqual(command[0], "python3")
        self.assertIn("scripts/run_openhands_manual_gate.py", command)
        self.assertNotIn("openhands", command[0])


if __name__ == "__main__":
    unittest.main()
