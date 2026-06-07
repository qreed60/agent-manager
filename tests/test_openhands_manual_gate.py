"""Regression tests for Phase 18J manual OpenHands gate runner."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import run_openhands_manual_gate
from scripts import validate_agent_run


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


class OpenHandsManualGateTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str, Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        project_id = "sample_project"
        repo = root / "canonical_repo"
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
        return tmp, root, project_id, repo

    def test_task_source_must_be_exactly_one(self) -> None:
        self.assertIsNotNone(run_openhands_manual_gate.validate_inputs(None, None, ["README.md"]))
        self.assertIsNotNone(run_openhands_manual_gate.validate_inputs("text", "task.md", ["README.md"]))
        self.assertIsNone(run_openhands_manual_gate.validate_inputs("text", None, ["README.md"]))

    def test_allowed_file_is_required(self) -> None:
        reason = run_openhands_manual_gate.validate_inputs("text", None, [])
        self.assertEqual(reason, "at least one --allowed-file is required")

    def test_dry_run_summary_is_warn_and_applied_false(self) -> None:
        tmp, root, project_id, _repo = self.make_root()
        old_root = run_openhands_manual_gate.ROOT
        run_openhands_manual_gate.ROOT = root
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(cmd)
            if "run_openhands_coder_task.py" in str(cmd[1]):
                run_dir = root / "runs" / project_id / "openhands_coder_20260607T000000Z"
                run_dir.mkdir(parents=True)
                _write_json(
                    run_dir / "OPENHANDS_CODER_SUMMARY.json",
                    {
                        "status": "warn",
                        "dry_run": True,
                        "openhands_execution_performed": False,
                        "run_dir": str(run_dir),
                    },
                )
                _write_json(run_dir / "OPENHANDS_CHANGED_FILES.json", {"all_changed_files": []})
            return subprocess.CompletedProcess(cmd, 0, "", "")

        try:
            with tmp, patch.object(run_openhands_manual_gate, "run_subprocess", side_effect=fake_run):
                argv = [
                    "run_openhands_manual_gate.py",
                    project_id,
                    "--task-text",
                    "write one file",
                    "--allowed-file",
                    "docs/example.md",
                ]
                with patch.object(sys, "argv", argv):
                    run_openhands_manual_gate.main()
                summary_path = root / "runs" / project_id / "openhands_coder_20260607T000000Z" / "OPENHANDS_MANUAL_GATE_SUMMARY.json"
                summary = json.loads(summary_path.read_text())
                self.assertEqual(summary["status"], "warn")
                self.assertTrue(summary["dry_run"])
                self.assertFalse(summary["applied"])
                self.assertFalse(summary["openhands_execution_performed"])
                self.assertTrue(summary["no_apply_commit_push_merge_pr_or_cleanup_performed"])
                self.assertFalse(any(cmd and Path(cmd[0]).name == "openhands" for cmd in commands))
        finally:
            run_openhands_manual_gate.ROOT = old_root

    def test_live_synthetic_pass_requires_decision_accept_and_check_only_apply_pass(self) -> None:
        tmp, root, project_id, _repo = self.make_root()
        old_root = run_openhands_manual_gate.ROOT
        run_openhands_manual_gate.ROOT = root
        run_dir = root / "runs" / project_id / "openhands_coder_20260607T000100Z"

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if "run_openhands_coder_task.py" in str(cmd[1]):
                run_dir.mkdir(parents=True)
                _write_json(
                    run_dir / "OPENHANDS_CODER_SUMMARY.json",
                    {
                        "status": "pass",
                        "dry_run": False,
                        "openhands_execution_performed": True,
                        "run_dir": str(run_dir),
                    },
                )
                _write_json(run_dir / "OPENHANDS_CHANGED_FILES.json", {"all_changed_files": ["docs/example.md"]})
            elif "prepare_openhands_decision_packet.py" in str(cmd[1]):
                _write_json(run_dir / "OPENHANDS_DECISION_PACKET.json", {"recommendation": "accept_for_manual_review"})
            elif "apply_openhands_decision_packet.py" in str(cmd[1]):
                self.assertIn("--check-only", cmd)
                _write_json(
                    run_dir / "OPENHANDS_APPLY_STATUS.json",
                    {
                        "status": "pass",
                        "mode": "check_only",
                        "git_apply_check_passed": True,
                        "applied": False,
                    },
                )
            return subprocess.CompletedProcess(cmd, 0, "", "")

        try:
            with tmp, patch.object(run_openhands_manual_gate, "run_subprocess", side_effect=fake_run):
                argv = [
                    "run_openhands_manual_gate.py",
                    project_id,
                    "--task-text",
                    "write one file",
                    "--allowed-file",
                    "docs/example.md",
                    "--allow-openhands",
                ]
                with patch.object(sys, "argv", argv):
                    run_openhands_manual_gate.main()
                summary = json.loads((run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json").read_text())
                self.assertEqual(summary["status"], "pass")
                self.assertEqual(summary["decision_recommendation"], "accept_for_manual_review")
                self.assertEqual(summary["apply_mode"], "check_only")
                self.assertTrue(summary["apply_check_passed"])
                self.assertFalse(summary["applied"])
        finally:
            run_openhands_manual_gate.ROOT = old_root

    def test_summary_fails_if_apply_status_says_applied_true(self) -> None:
        status, reason = run_openhands_manual_gate.compute_gate_status_and_refusal(
            dry_run=False,
            openhands_execution_performed=True,
            coder_status="pass",
            decision_packet_present=True,
            decision_recommendation="accept_for_manual_review",
            apply_status_present=True,
            apply_status="pass",
            apply_mode="check_only",
            apply_check_passed=True,
            applied=True,
            canonical_repo_clean=True,
        )
        self.assertEqual(status, "fail")
        self.assertIn("applied", reason)

    def test_summary_fails_if_canonical_repo_dirty(self) -> None:
        status, reason = run_openhands_manual_gate.compute_gate_status_and_refusal(
            dry_run=False,
            openhands_execution_performed=True,
            coder_status="pass",
            decision_packet_present=True,
            decision_recommendation="accept_for_manual_review",
            apply_status_present=True,
            apply_status="pass",
            apply_mode="check_only",
            apply_check_passed=True,
            applied=False,
            canonical_repo_clean=False,
        )
        self.assertEqual(status, "fail")
        self.assertIn("canonical repo is dirty", reason)

    def write_gate_summary(self, run_dir: Path, **overrides: object) -> None:
        summary = {
            "schema_version": 1,
            "generated_by": "phase18j_openhands_manual_gate_runner",
            "project_id": "sample_project",
            "created_utc": "20260607T000000Z",
            "run_dir": str(run_dir),
            "dry_run": False,
            "openhands_execution_performed": True,
            "coder_status": "pass",
            "decision_packet_present": True,
            "decision_recommendation": "accept_for_manual_review",
            "apply_status_present": True,
            "apply_mode": "check_only",
            "apply_check_passed": True,
            "applied": False,
            "canonical_repo_clean": True,
            "changed_files": ["docs/example.md"],
            "allowed_files": ["docs/example.md"],
            "status": "pass",
            "refusal_reason": "",
            "no_apply_commit_push_merge_pr_or_cleanup_performed": True,
        }
        summary.update(overrides)
        _write_json(run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.json", summary)
        (run_dir / "OPENHANDS_MANUAL_GATE_SUMMARY.md").write_text("# summary\n")

    def validate_gate_summary(self, run_dir: Path) -> validate_agent_run.CheckRecorder:
        recorder = validate_agent_run.CheckRecorder()
        validate_agent_run.validate_openhands_manual_gate_summary(recorder, run_dir)
        return recorder

    def test_validation_accepts_live_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.write_gate_summary(run_dir)
            self.assertEqual(self.validate_gate_summary(run_dir).status(), "pass")

    def test_validation_accepts_dry_run_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.write_gate_summary(
                run_dir,
                dry_run=True,
                openhands_execution_performed=False,
                decision_packet_present=False,
                apply_status_present=False,
                status="warn",
            )
            self.assertEqual(self.validate_gate_summary(run_dir).status(), "pass")

    def test_validation_fails_when_applied_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.write_gate_summary(run_dir, applied=True)
            recorder = self.validate_gate_summary(run_dir)
            self.assertEqual(recorder.status(), "fail")
            self.assertTrue(any(check["id"] == "openhands_manual_gate_applied_false" for check in recorder.failures()))

    def test_validation_fails_when_generated_by_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.write_gate_summary(run_dir, generated_by="wrong")
            recorder = self.validate_gate_summary(run_dir)
            self.assertEqual(recorder.status(), "fail")
            self.assertTrue(any(check["id"] == "openhands_manual_gate_generated_by" for check in recorder.failures()))

    def test_unit_tests_patch_subprocess_so_no_openhands_or_model_calls_are_made(self) -> None:
        runner = MagicMock(return_value=subprocess.CompletedProcess(["python3"], 0, "", ""))
        with patch.object(run_openhands_manual_gate, "run_subprocess", runner):
            run_openhands_manual_gate.run_decision_packet("sample_project", Path("/tmp/nonexistent"))
        called_commands = [call.args[0] for call in runner.call_args_list]
        self.assertFalse(any(command and Path(command[0]).name == "openhands" for command in called_commands))


if __name__ == "__main__":
    unittest.main()
