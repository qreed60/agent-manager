from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import prepare_openhands_decision_packet
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
        write_files: list[str] | None = None,
        timeout_on_run: bool = False,
        allowed_files: list[str] | None = None,
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
            for relative_path in write_files or []:
                target = Path(str(kwargs["cwd"])) / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("OpenHands manual write completed.\n")
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
                    allowed_files=allowed_files,
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

    def test_allowed_file_repeatable_parsing(self) -> None:
        parser = run_openhands_coder_task.build_arg_parser()
        args = parser.parse_args(
            [
                "sample_project",
                "--task-text",
                "Do work",
                "--allowed-file",
                "one.txt",
                "--allowed-file",
                "two.txt",
            ]
        )
        self.assertEqual(args.allowed_file, ["one.txt", "two.txt"])

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

    def test_live_execution_creates_fresh_worktree(self) -> None:
        """Live execution must create a fresh worktree path per run."""
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            worktree_info = json.loads((run_dir / "OPENHANDS_WORKTREE_INFO.json").read_text())
            self.assertTrue(worktree_info.get("worktree_created"), "fresh_worktree_created must be true for live runs")
            wt_path = Path(worktree_info["worktree_path"])
            # Must be under worktrees/<project_id>/openhands_coder_<timestamp>
            self.assertIn(f"openhands_coder_20260605T120000Z", str(wt_path))

    def test_live_execution_does_not_reuse_latest_coder_worktree(self) -> None:
        """Live execution must not reuse the latest_coder_worktree symlink target."""
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            coder_run = json.loads((run_dir / "OPENHANDS_CODER_RUN.json").read_text())
            self.assertFalse(coder_run.get("reused_existing_worktree"), "live runs must not reuse existing worktrees")

    def test_changed_file_detection_includes_untracked_files(self) -> None:
        """detect_changed_files must include untracked files in all_changed_files."""
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "worktree"
            wt.mkdir()
            subprocess.run(["git", "init"], cwd=wt, check=True, capture_output=True)
            (wt / "existing.txt").write_text("existing\n")
            subprocess.run(["git", "add", "existing.txt"], cwd=wt, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t.com", "-c", "user.name=T", "commit", "-m", "init"],
                cwd=wt, check=True, capture_output=True,
            )
            # Create untracked file
            (wt / "new_file.txt").write_text("untracked\n")
            changed = run_openhands_coder_task.detect_changed_files(wt)
            self.assertIn("new_file.txt", changed["untracked_files"])
            self.assertIn("new_file.txt", changed["all_changed_files"])

    def test_smoke_scope_allows_only_expected_file(self) -> None:
        """Smoke scope guard must allow only .agent_manager_scratch/OPENHANDS_SMOKE_TEST.md."""
        scope = run_openhands_coder_task.compute_scope_status(
            smoke_task=True,
            objective={},
            changed_files=[".agent_manager_scratch/OPENHANDS_SMOKE_TEST.md"],
            canonical_repo_clean=True,
        )
        self.assertEqual(scope["scope_status"], "pass")

    def test_scope_status_fails_on_extra_untracked_file(self) -> None:
        """Scope status must fail if any changed file is outside the allowed list."""
        scope = run_openhands_coder_task.compute_scope_status(
            smoke_task=True,
            objective={},
            changed_files=[".agent_manager_scratch/OPENHANDS_SMOKE_TEST.md", "extra_file.txt"],
            canonical_repo_clean=True,
        )
        self.assertEqual(scope["scope_status"], "fail")

    def test_summary_status_follows_scope_status(self) -> None:
        """Summary status must follow scope guard status."""
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            scope_status = json.loads((run_dir / "OPENHANDS_SCOPE_STATUS.json").read_text())
            summary_json = json.loads((run_dir / "OPENHANDS_CODER_SUMMARY.json").read_text())
            if scope_status.get("scope_status") == "fail":
                self.assertEqual(summary_json["status"], "fail")

    def test_validation_fails_on_scope_fail(self) -> None:
        """Validation must fail when scope status is fail."""
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            scope_path = run_dir / "OPENHANDS_SCOPE_STATUS.json"
            scope = json.loads(scope_path.read_text())
            scope["scope_status"] = "fail"
            scope["details"] = "file outside scope: extra.txt"
            scope_path.write_text(json.dumps(scope) + "\n")

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
            self.assertIn("openhands_scope_guard_fail", failed_ids)

    def test_validation_passes_on_smoke_pass_with_fresh_worktree(self) -> None:
        """Validation must pass when smoke passes and fresh worktree was created."""
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

    def test_live_manual_task_text_requires_allowed_file(self) -> None:
        tmp, root, project_id, _repo, worktree = self.make_sample_root()
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            with patch.dict(os.environ, {"AGENT_MANAGER_ENABLE_OPENHANDS": "1"}, clear=False):
                with self.assertRaises(ValueError):
                    run_openhands_coder_task.generate(
                        project_id,
                        created_utc="20260605T120000Z",
                        allow_openhands=True,
                        worktree_path=str(worktree),
                        task_text="Write a manual file.",
                    )
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()

    def test_live_manual_task_file_requires_allowed_file(self) -> None:
        tmp, root, project_id, _repo, worktree = self.make_sample_root()
        task_file = root / "manual_task.md"
        task_file.write_text("Write a manual file.\n")
        old_root = run_openhands_coder_task.ROOT
        run_openhands_coder_task.ROOT = root
        try:
            with patch.dict(os.environ, {"AGENT_MANAGER_ENABLE_OPENHANDS": "1"}, clear=False):
                with self.assertRaises(ValueError):
                    run_openhands_coder_task.generate(
                        project_id,
                        created_utc="20260605T120000Z",
                        allow_openhands=True,
                        worktree_path=str(worktree),
                        task_file=str(task_file),
                    )
        finally:
            run_openhands_coder_task.ROOT = old_root
            tmp.cleanup()

    def test_manual_scope_passes_when_only_allowed_file_changes(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, _root, _project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            scope = json.loads((run_dir / "OPENHANDS_SCOPE_STATUS.json").read_text())
            changed = json.loads((run_dir / "OPENHANDS_CHANGED_FILES.json").read_text())
            summary_json = json.loads((run_dir / "OPENHANDS_CODER_SUMMARY.json").read_text())
            self.assertEqual(scope["scope_status"], "pass")
            self.assertEqual(scope["allowed_files"], [allowed])
            self.assertIn(allowed, changed["untracked_files"])
            self.assertEqual(summary_json["status"], "pass")
            self.assertEqual(summary_json["task_type"], "manual_task_text")

    def test_manual_scope_fails_when_extra_untracked_file_changes(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, _root, _project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed, "extra.txt"],
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            scope = json.loads((run_dir / "OPENHANDS_SCOPE_STATUS.json").read_text())
            summary_json = json.loads((run_dir / "OPENHANDS_CODER_SUMMARY.json").read_text())
            self.assertEqual(scope["scope_status"], "fail")
            self.assertIn("extra.txt", scope["details"])
            self.assertEqual(summary_json["status"], "fail")

    def test_manual_live_no_file_change_produces_warn_summary(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, _root, _project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            scope = json.loads((run_dir / "OPENHANDS_SCOPE_STATUS.json").read_text())
            summary_json = json.loads((run_dir / "OPENHANDS_CODER_SUMMARY.json").read_text())
            self.assertEqual(scope["scope_status"], "warn")
            self.assertEqual(summary_json["status"], "warn")

    def test_validation_fails_for_live_manual_task_with_no_allowed_files(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            run_dir = Path(summary["run_dir"])
            run_path = run_dir / "OPENHANDS_CODER_RUN.json"
            run_record = json.loads(run_path.read_text())
            run_record["manual_allowed_files"] = []
            run_path.write_text(json.dumps(run_record) + "\n")
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
            self.assertIn("manual_task_allowed_files_present", failed_ids)

    def test_default_dry_run_behavior_unchanged(self) -> None:
        """Default dry-run must not create a fresh worktree."""
        tmp, root, project_id, summary, _runner = self.run_sample(dry_run=True)
        with tmp:
            run_dir = Path(summary["run_dir"])
            coder_run = json.loads((run_dir / "OPENHANDS_CODER_RUN.json").read_text())
            self.assertFalse(coder_run.get("fresh_worktree_created"), "dry runs must not create fresh worktrees")

    def test_decision_packet_generation_from_successful_manual_run(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id, created_utc="20260605T121000Z")
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            run_dir = Path(summary["run_dir"])
            self.assertTrue((run_dir / "OPENHANDS_DECISION_PACKET.json").exists())
            self.assertTrue((run_dir / "OPENHANDS_DECISION_PACKET.md").exists())
            self.assertTrue((run_dir / "OPENHANDS_PATCH.diff").exists())
            self.assertEqual(packet["generated_by"], "phase18g_openhands_decision_packet")
            self.assertEqual(packet["recommendation"], "accept_for_manual_review")

    def test_decision_packet_smoke_recommends_discard_worktree(self) -> None:
        tmp, root, project_id, _summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            smoke_task=True,
            write_smoke_file=True,
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            self.assertEqual(packet["task_type"], "smoke")
            self.assertEqual(packet["recommendation"], "discard_worktree")

    def test_decision_packet_manual_scoped_changes_recommend_accept(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, _summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            self.assertEqual(packet["recommendation"], "accept_for_manual_review")
            self.assertTrue(packet["patch_nonempty"])

    def test_decision_packet_timeout_recommends_hold_for_debug(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, _summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            timeout_on_run=True,
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            self.assertEqual(packet["recommendation"], "hold_for_debug")

    def test_decision_packet_scope_failure_recommends_discard_worktree(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, _summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed, "extra.txt"],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            self.assertEqual(packet["recommendation"], "discard_worktree")

    def test_decision_packet_dirty_canonical_recommends_human_review_required(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            scope_path = Path(summary["run_dir"]) / "OPENHANDS_SCOPE_STATUS.json"
            scope = json.loads(scope_path.read_text())
            scope["scope_status"] = "pass"
            scope["details"] = "canonical repo is dirty"
            scope_path.write_text(json.dumps(scope) + "\n")
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            self.assertFalse(packet["canonical_repo_clean"])
            self.assertEqual(packet["recommendation"], "human_review_required")

    def test_decision_packet_patch_file_created_and_sha256_recorded(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, _summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            patch_path = Path(packet["patch_file"])
            self.assertTrue(patch_path.exists())
            self.assertEqual(packet["patch_sha256"], prepare_openhands_decision_packet.sha256_file(patch_path))
            self.assertTrue(packet["patch_nonempty"])

    def test_validation_fails_on_decision_packet_patch_hash_mismatch(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            packet_path = Path(summary["run_dir"]) / "OPENHANDS_DECISION_PACKET.json"
            packet = json.loads(packet_path.read_text())
            packet["patch_sha256"] = "0" * 64
            packet_path.write_text(json.dumps(packet) + "\n")
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_openhands_decision_packet_artifacts(recorder, Path(summary["run_dir"]))
            failed_ids = {check["id"] for check in recorder.failures()}
            self.assertIn("openhands_decision_patch_sha256", failed_ids)

    def test_validation_fails_on_decision_packet_canonical_repo_dirty(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            packet_path = Path(summary["run_dir"]) / "OPENHANDS_DECISION_PACKET.json"
            packet = json.loads(packet_path.read_text())
            packet["canonical_repo_clean"] = False
            packet_path.write_text(json.dumps(packet) + "\n")
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_openhands_decision_packet_artifacts(recorder, Path(summary["run_dir"]))
            failed_ids = {check["id"] for check in recorder.failures()}
            self.assertIn("openhands_decision_canonical_repo_clean", failed_ids)

    def test_validation_fails_on_decision_packet_scope_status_fail(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            packet_path = Path(summary["run_dir"]) / "OPENHANDS_DECISION_PACKET.json"
            packet = json.loads(packet_path.read_text())
            packet["scope_status"]["scope_status"] = "fail"
            packet_path.write_text(json.dumps(packet) + "\n")
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_openhands_decision_packet_artifacts(recorder, Path(summary["run_dir"]))
            failed_ids = {check["id"] for check in recorder.failures()}
            self.assertIn("openhands_decision_scope_status_not_fail", failed_ids)

    def test_review_commands_and_cleanup_plan_are_generated_without_cleanup_execution(self) -> None:
        allowed = ".agent_manager_scratch/OPENHANDS_MANUAL_WRITE_TEST.md"
        tmp, root, project_id, summary, _runner = self.run_sample(
            allow_openhands=True,
            enable_env=True,
            task_text="Create the manual write test file.",
            allowed_files=[allowed],
            write_files=[allowed],
        )
        with tmp:
            old_root = prepare_openhands_decision_packet.ROOT
            prepare_openhands_decision_packet.ROOT = root
            try:
                packet = prepare_openhands_decision_packet.prepare(project_id)
            finally:
                prepare_openhands_decision_packet.ROOT = old_root
            run_dir = Path(summary["run_dir"])
            review = (run_dir / "OPENHANDS_REVIEW_COMMANDS.md").read_text()
            cleanup = (run_dir / "OPENHANDS_CLEANUP_PLAN.md").read_text()
            self.assertIn("git -C", review)
            self.assertIn("apply --check", review)
            self.assertIn("Manual only. Do not run unless you intend to apply this patch.", review)
            self.assertIn("worktree remove", cleanup)
            self.assertIn("branch -D", cleanup)
            self.assertTrue(Path(packet["worktree_path"]).exists())


if __name__ == "__main__":
    unittest.main()
