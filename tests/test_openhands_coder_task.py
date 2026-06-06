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
        subprocess.run(["git", "add", ".agent_manager/OBJECTIVE_BACKLOG.json"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "add state"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
        openhands_help: str = "--override-with-envs --headless --file --json --exit-without-confirmation",
        task_text: str | None = None,
        task_file: str | None = None,
        smoke_task: bool = False,
        write_smoke_file: bool = False,
        write_misplaced_smoke_file: bool = False,
        timeout_on_run: bool = False,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict, MagicMock]:
        tmp, root, project_id, _repo, worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if "--help" in command:
                return subprocess.CompletedProcess(command, 0, openhands_help, "")
            if timeout_on_run:
                raise subprocess.TimeoutExpired(command, timeout=1, output="", stderr="")
            if write_smoke_file:
                cwd = Path(str(kwargs["cwd"]))
                smoke_file = cwd / run_openhands_coder_task.SMOKE_EXPECTED_FILE
                smoke_file.parent.mkdir(parents=True, exist_ok=True)
                smoke_file.write_text("OpenHands smoke task completed.\n")
            if write_misplaced_smoke_file:
                prompt_path = Path(command[command.index("--file") + 1])
                smoke_file = prompt_path.parent / run_openhands_coder_task.SMOKE_EXPECTED_FILE
                smoke_file.parent.mkdir(parents=True, exist_ok=True)
                smoke_file.write_text("OpenHands smoke task completed.\n")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        runner = MagicMock(side_effect=fake_runner)
        env_patch = {"AGENT_MANAGER_ENABLE_OPENHANDS": "1"} if enable_env else {}
        try:
            with patch.dict(os.environ, env_patch, clear=False):
                summary = run_openhands_coder_task.generate(
                    project_id,
                    created_utc="20260605T120000Z",
                    allow_openhands=allow_openhands,
                    dry_run=dry_run,
                    worktree_path=str(worktree),
                    task_text=task_text,
                    task_file=task_file,
                    smoke_task=smoke_task,
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
            self.assertEqual(summary["prompt_source"], "generated")
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
            self.assertEqual(run_record["prompt_source"], "generated")

    def test_smoke_task_generates_tiny_prompt(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(smoke_task=True)
        with tmp:
            prompt = (Path(summary["run_dir"]) / "OPENHANDS_TASK_PROMPT.md").read_text()
            self.assertIn(run_openhands_coder_task.SMOKE_EXPECTED_FILE, prompt)
            self.assertIn("current shell working directory is the isolated worktree", prompt)
            self.assertIn("relative to the current working directory only", prompt)
            self.assertIn("Do not create the file beside `OPENHANDS_TASK_PROMPT.md`.", prompt)
            self.assertIn("Do not use the run directory.", prompt)
            self.assertIn("mkdir -p .agent_manager_scratch", prompt)
            self.assertIn(
                "printf '%s\\n' 'OpenHands smoke test completed.' > .agent_manager_scratch/OPENHANDS_SMOKE_TEST.md",
                prompt,
            )
            self.assertIn("Do not run tests.", prompt)
            self.assertIn("Finish immediately after that.", prompt)
            self.assertEqual(summary["prompt_source"], "smoke_task")
            runner.assert_not_called()

    def test_task_text_overrides_generated_prompt(self) -> None:
        tmp, _root, _project_id, summary, _runner = self.run_sample(task_text="Write only this.\n")
        with tmp:
            prompt = (Path(summary["run_dir"]) / "OPENHANDS_TASK_PROMPT.md").read_text()
            self.assertEqual(prompt, "Write only this.\n")
            self.assertEqual(summary["prompt_source"], "task_text")

    def test_task_file_overrides_generated_prompt(self) -> None:
        tmp, root, project_id, _repo, worktree = self.make_sample_root()
        task_file = root / "task.md"
        task_file.write_text("File prompt.\n")
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            summary = run_openhands_coder_task.generate(
                project_id,
                created_utc="20260605T120000Z",
                worktree_path=str(worktree),
                task_file=str(task_file),
            )
            prompt = (Path(summary["run_dir"]) / "OPENHANDS_TASK_PROMPT.md").read_text()
            self.assertEqual(prompt, "File prompt.\n")
            self.assertEqual(summary["prompt_source"], "task_file")
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()

    def test_simultaneous_override_options_are_rejected(self) -> None:
        tmp, root, project_id, _repo, worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            with self.assertRaises(ValueError):
                run_openhands_coder_task.generate(
                    project_id,
                    created_utc="20260605T120000Z",
                    worktree_path=str(worktree),
                    task_text="one",
                    smoke_task=True,
                )
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()

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
            self.assertEqual(runner.call_count, 2)
            command = runner.call_args.args[0]
            forbidden = {"push", "merge", "commit", "pr"}
            self.assertTrue(forbidden.isdisjoint(set(command)))

    def test_live_command_uses_headless_file_prompt_when_supported(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(allow_openhands=True, enable_env=True)
        with tmp:
            self.assertEqual(runner.call_count, 2)
            command = runner.call_args.args[0]
            self.assertIn("--headless", command)
            self.assertIn("--file", command)
            self.assertIn("--json", command)
            self.assertIn("--exit-without-confirmation", command)
            prompt_arg = command[command.index("--file") + 1]
            self.assertTrue(prompt_arg.endswith("OPENHANDS_TASK_PROMPT.md"))
            command_text = (Path(summary["run_dir"]) / "OPENHANDS_COMMAND.txt").read_text()
            self.assertIn("--headless", command_text)
            self.assertIn("--file", command_text)

    def test_live_command_uses_task_text_when_file_is_unavailable(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            openhands_help="--override-with-envs --headless --task",
        )
        with tmp:
            self.assertEqual(runner.call_count, 2)
            command = runner.call_args.args[0]
            self.assertIn("--headless", command)
            self.assertNotIn("--file", command)
            self.assertIn("--task", command)
            task_arg = command[command.index("--task") + 1]
            self.assertIn("# OpenHands Controlled Coder Task", task_arg)
            self.assertNotEqual(Path(task_arg).name, "OPENHANDS_TASK_PROMPT.md")
            run_record = json.loads((Path(summary["run_dir"]) / "OPENHANDS_CODER_RUN.json").read_text())
            self.assertIn("--task", run_record["command_argv_redacted"])

    def test_live_execution_refuses_when_headless_is_unsupported(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            openhands_help="--override-with-envs --file --task",
        )
        with tmp:
            self.assertEqual(runner.call_count, 1)
            self.assertFalse(summary["openhands_execution_performed"])
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["status"], "fail")
            self.assertIn("--headless", summary["command_refusal_reason"])
            command_text = (Path(summary["run_dir"]) / "OPENHANDS_COMMAND.txt").read_text()
            self.assertIn("[refused:", command_text)

    def test_smoke_status_passes_when_file_exists_and_canonical_repo_is_clean(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
        with tmp:
            self.assertEqual(runner.call_count, 2)
            smoke = json.loads((Path(summary["run_dir"]) / "OPENHANDS_SMOKE_STATUS.json").read_text())
            self.assertEqual(smoke["status"], "pass")
            self.assertEqual(summary["status"], "pass")
            self.assertTrue(smoke["expected_file_exists"])
            self.assertTrue(smoke["canonical_repo_clean"])
            self.assertEqual(smoke["misplaced_file_paths"], [])
            self.assertTrue(smoke["expected_file_absolute_path"].endswith(run_openhands_coder_task.SMOKE_EXPECTED_FILE))
            self.assertEqual(smoke["returncode"], 0)
            self.assertFalse(smoke["timed_out"])

    def test_smoke_status_warns_when_file_is_misplaced_in_run_dir(self) -> None:
        tmp, _root, _project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_misplaced_smoke_file=True,
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            smoke = json.loads((run_dir / "OPENHANDS_SMOKE_STATUS.json").read_text())
            self.assertEqual(smoke["status"], "warn")
            self.assertEqual(summary["status"], "warn")
            self.assertFalse(smoke["expected_file_exists"])
            self.assertEqual(smoke["misplaced_file_paths"], [str(run_dir / run_openhands_coder_task.SMOKE_EXPECTED_FILE)])

    def test_smoke_summary_status_follows_smoke_status(self) -> None:
        tmp, _root, _project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_misplaced_smoke_file=True,
        )
        with tmp:
            summary_json = json.loads((Path(summary["run_dir"]) / "OPENHANDS_CODER_SUMMARY.json").read_text())
            self.assertEqual(summary_json["smoke_status"], "warn")
            self.assertEqual(summary_json["status"], "warn")

    def test_smoke_status_warns_when_timeout_occurs(self) -> None:
        tmp, _root, _project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            timeout_on_run=True,
        )
        with tmp:
            smoke = json.loads((Path(summary["run_dir"]) / "OPENHANDS_SMOKE_STATUS.json").read_text())
            self.assertEqual(smoke["status"], "warn")
            self.assertEqual(summary["status"], "warn")
            self.assertEqual(smoke["returncode"], 124)
            self.assertTrue(smoke["timed_out"])

    def test_default_command_does_not_use_detached_tmux_session(self) -> None:
        tmp, _root, _project_id, summary, runner = self.run_sample()
        with tmp:
            runner.assert_not_called()
            command_text = (Path(summary["run_dir"]) / "OPENHANDS_COMMAND.txt").read_text()
            self.assertNotIn("tmux", command_text)
            self.assertNotIn("new-session", command_text)

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

    def test_validation_parses_openhands_smoke_status(self) -> None:
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
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
            check_ids = {check["id"] for check in recorder.checks}
            self.assertIn("openhands_smoke_status_parse", check_ids)
            self.assertTrue(Path(summary["run_dir"]).exists())

    def test_validation_fails_if_smoke_reports_canonical_repo_dirty(self) -> None:
        tmp, root, project_id, summary, _runner = self.run_sample(smoke_task=True)
        with tmp:
            smoke_path = Path(summary["run_dir"]) / "OPENHANDS_SMOKE_STATUS.json"
            smoke = json.loads(smoke_path.read_text())
            smoke["canonical_repo_clean"] = False
            smoke["status"] = "warn"
            smoke_path.write_text(json.dumps(smoke) + "\n")
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
            failed_ids = {check["id"] for check in recorder.failures()}
            self.assertIn("openhands_smoke_canonical_repo_clean", failed_ids)

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
