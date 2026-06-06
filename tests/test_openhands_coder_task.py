from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import run_openhands_coder_task
from scripts import validate_agent_run


class OpenHandsCoderTaskTests(unittest.TestCase):
    def make_sample_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str, Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        project_id = "sample_project"
        repo = root / "sample_repo"
        state_dir = repo / ".agent_manager"
        worktree = root / "worktrees" / project_id / "coder_wt"
        state_dir.mkdir(parents=True)
        worktree.mkdir(parents=True)
        (root / "configs").mkdir()
        (root / "runs" / project_id).mkdir(parents=True)
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
        subprocess.run(["git", "init"], cwd=worktree, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (worktree / "README.md").write_text("worktree\n")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"],
            cwd=worktree,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        (root / "configs" / "projects.json").write_text(
            json.dumps(
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
                }
            )
            + "\n"
        )
        objective = {
            "id": "phase18b_controlled_openhands_coder_execution",
            "status": "active",
            "title": "Add controlled OpenHands coder execution",
            "write_capable": True,
        }
        (state_dir / "OBJECTIVE_BACKLOG.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )
        coder_dir = root / "runs" / project_id / "coder_worktree_20260605T000000Z"
        coder_dir.mkdir()
        (coder_dir / "CODER_TASK_PACKET.json").write_text(json.dumps({"worktree": str(worktree), "objective": objective}) + "\n")
        (coder_dir / "WORKTREE_STATUS.json").write_text(json.dumps({"clean": True}) + "\n")
        (root / "runs" / project_id / "latest_coder_worktree").symlink_to(coder_dir, target_is_directory=True)
        return tmp, root, project_id, repo, worktree

    def run_sample(
        self,
        *,
        allow_openhands: bool = False,
        enable_env: bool = False,
        dry_run: bool = False,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict, MagicMock]:
        tmp, root, project_id, _repo, worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        runner = MagicMock(return_value=subprocess.CompletedProcess(["openhands"], 0, "ok", ""))
        env_patch = {"AGENT_MANAGER_ENABLE_OPENHANDS": "1"} if enable_env else {}
        try:
            with patch.dict(os.environ, env_patch, clear=False):
                summary = run_openhands_coder_task.generate(
                    project_id,
                    created_utc="20260605T120000Z",
                    allow_openhands=allow_openhands,
                    dry_run=dry_run,
                    worktree_path=str(worktree),
                    command_runner=runner,
                )
        finally:
            run_openhands_coder_task.ROOT = old_root
        return tmp, root, project_id, summary, runner

    def test_default_mode_does_not_run_openhands(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample()
        with tmp:
            self.assertTrue(summary["dry_run"])
            self.assertFalse(summary["openhands_execution_performed"])
            runner.assert_not_called()

    def test_allow_openhands_still_requires_env_gate(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(allow_openhands=True, enable_env=False)
        with tmp:
            self.assertTrue(summary["dry_run"])
            self.assertFalse(summary["openhands_execution_performed"])
            runner.assert_not_called()

    def test_dry_run_writes_all_required_artifacts(self) -> None:
        tmp, _root, _project_id, summary, _runner = self.run_sample(dry_run=True)
        with tmp:
            run_dir = Path(summary["run_dir"])
            for name in run_openhands_coder_task.REQUIRED_ARTIFACTS:
                self.assertTrue((run_dir / name).exists(), f"missing {name}")

    def test_openhands_command_includes_override_with_envs(self) -> None:
        tmp, _root, _project_id, summary, _runner = self.run_sample()
        with tmp:
            run_record = json.loads((Path(summary["run_dir"]) / "OPENHANDS_CODER_RUN.json").read_text())
            self.assertIn("--override-with-envs", run_record["command_argv_redacted"])

    def test_canonical_repo_path_is_rejected_as_worktree(self) -> None:
        tmp, root, project_id, repo, _worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            with self.assertRaises(ValueError):
                run_openhands_coder_task.generate(
                    project_id,
                    created_utc="20260605T130000Z",
                    worktree_path=str(repo),
                )
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()

    def test_worktree_under_project_worktrees_is_accepted(self) -> None:
        tmp, root, project_id, repo, worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            accepted = run_openhands_coder_task.ensure_worktree_allowed(project_id, worktree, repo)
            self.assertEqual(accepted, worktree.resolve())
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()

    def test_live_mock_performs_no_push_merge_pr_or_commit(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(allow_openhands=True, enable_env=True)
        with tmp:
            self.assertFalse(summary["dry_run"])
            self.assertTrue(summary["openhands_execution_performed"])
            runner.assert_called_once()
            command = runner.call_args.args[0]
            forbidden = {"push", "merge", "commit", "pr"}
            self.assertTrue(forbidden.isdisjoint(set(command)))

    def test_validation_accepts_latest_openhands_coder_dry_run_artifacts(self) -> None:
        tmp, root, project_id, summary, _runner = self.run_sample()
        with tmp:
            old_root = validate_agent_run.ROOT
            validate_agent_run.ROOT = root
            try:
                recorder = validate_agent_run.CheckRecorder()
                validate_agent_run.validate_openhands_coder_artifacts(
                    recorder,
                    (root / "runs" / project_id / "latest_openhands_coder").resolve(),
                )
            finally:
                validate_agent_run.ROOT = old_root
            self.assertEqual(recorder.failures(), [], json.dumps(recorder.failures(), indent=2))
            self.assertTrue(Path(summary["run_dir"]).exists())

    def test_generic_non_thomsonlint_helper_logic_still_works(self) -> None:
        tmp, root, project_id, repo, worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            project = run_openhands_coder_task.load_project(project_id)
            self.assertEqual(Path(project["repo_path"]), repo)
            self.assertEqual(run_openhands_coder_task.project_state_dir(project), repo / ".agent_manager")
            self.assertEqual(
                run_openhands_coder_task.ensure_worktree_allowed(project_id, worktree, repo),
                worktree.resolve(),
            )
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
