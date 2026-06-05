from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import run_nightly_window
from scripts import validate_agent_run


class NightlyWindowTests(unittest.TestCase):
    def make_sample_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        project_id = "sample_project"
        repo = root / "sample_repo"
        state_dir = repo / ".agent_manager"
        state_dir.mkdir(parents=True)
        (root / "configs").mkdir()
        (root / "configs" / "projects.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": {
                        project_id: {
                            "repo_path": str(repo),
                            "project_state_dir": ".agent_manager",
                            "server_state_dir": "runs/sample_project",
                            "worktree_root": "worktrees/sample_project",
                            "validation_adapter": "generic_git",
                            "enabled": True,
                        }
                    },
                }
            )
            + "\n"
        )
        (root / "configs" / "nightly_window_policy.json").write_text(json.dumps(run_nightly_window.DEFAULT_POLICY) + "\n")
        objective = {
            "id": "phase16_timeboxed_langgraph_loop",
            "priority": 1,
            "status": "active",
            "phase": "Phase 16",
            "write_capable": False,
        }
        (state_dir / "WEEKLY_PLAN.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )
        (state_dir / "OBJECTIVE_BACKLOG.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "objectives": [objective]}) + "\n"
        )
        return tmp, root, project_id

    def fake_runner(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "ok", "")

    def run_sample(self, quick_passes: int = 1) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict]:
        tmp, root, project_id = self.make_sample_root()
        old_root = run_nightly_window.ROOT
        run_nightly_window.ROOT = root
        try:
            manifest = run_nightly_window.run_window(
                project_id,
                created_utc="20260605T010203Z",
                quick_passes=quick_passes,
                command_runner=self.fake_runner,
            )
        finally:
            run_nightly_window.ROOT = old_root
        return tmp, root, project_id, manifest

    def test_policy_defaults_are_correct(self) -> None:
        policy = run_nightly_window.DEFAULT_POLICY
        self.assertEqual(policy["nightly_start"], "23:00")
        self.assertEqual(policy["no_new_work_cutoff"], "05:30")
        self.assertEqual(policy["hard_stop"], "06:00")
        self.assertEqual(policy["max_manager_passes"], 3)
        self.assertEqual(policy["max_code_writing_tasks"], 0)
        self.assertEqual(policy["future_max_code_writing_tasks"], 1)
        self.assertEqual(policy["max_retries_per_task"], 1)

    def test_no_new_work_cutoff_logic(self) -> None:
        policy = run_nightly_window.DEFAULT_POLICY
        self.assertTrue(run_nightly_window.can_start_new_pass("05:29", policy, 0))
        self.assertFalse(run_nightly_window.can_start_new_pass("05:30", policy, 0))
        self.assertFalse(run_nightly_window.can_start_new_pass("22:59", policy, 0))

    def test_hard_stop_logic(self) -> None:
        policy = run_nightly_window.DEFAULT_POLICY
        self.assertFalse(run_nightly_window.at_or_after_hard_stop("05:59", policy))
        self.assertTrue(run_nightly_window.at_or_after_hard_stop("06:00", policy))
        self.assertTrue(run_nightly_window.at_or_after_hard_stop("12:00", policy))
        self.assertFalse(run_nightly_window.at_or_after_hard_stop("23:00", policy))

    def test_max_pass_enforcement(self) -> None:
        tmp, root, project_id, manifest = self.run_sample(quick_passes=10)
        with tmp:
            self.assertEqual(manifest["pass_count"], 3)
            timeline = json.loads((root / "runs" / project_id / "latest_nightly_window" / "NIGHTLY_WINDOW_TIMELINE.json").read_text())
            self.assertEqual(len(timeline["passes"]), 3)

    def test_max_code_writing_tasks_is_zero_by_default(self) -> None:
        tmp, root, project_id, manifest = self.run_sample()
        with tmp:
            self.assertEqual(manifest["max_code_writing_tasks"], 0)
            safety = json.loads((root / "runs" / project_id / "latest_nightly_window" / "NIGHTLY_SAFETY_STATUS.json").read_text())
            self.assertEqual(safety["max_code_writing_tasks"], 0)
            self.assertFalse(safety["openhands_allowed"])

    def test_manifest_timeline_and_handoff_shape_is_valid(self) -> None:
        tmp, root, project_id, manifest = self.run_sample()
        with tmp:
            run_dir = root / "runs" / project_id / "latest_nightly_window"
            timeline = json.loads((run_dir / "NIGHTLY_WINDOW_TIMELINE.json").read_text())
            handoff = (run_dir / "MORNING_HANDOFF.md").read_text()
            self.assertEqual(manifest["project_id"], project_id)
            self.assertEqual(manifest["selected_objective_id"], "phase16_timeboxed_langgraph_loop")
            self.assertEqual(manifest["status"], "pass")
            self.assertEqual(timeline["passes"][0]["pass_index"], 1)
            self.assertEqual(timeline["passes"][0]["decision"], "run_langgraph_v0")
            self.assertIn("## Window Policy", handoff)
            self.assertIn("## Model Routing Summary", handoff)
            self.assertIn("## Next Action", handoff)

    def test_validation_accepts_latest_nightly_window_artifacts(self) -> None:
        tmp, root, project_id, _manifest = self.run_sample()
        with tmp:
            recorder = validate_agent_run.CheckRecorder()
            validate_agent_run.validate_nightly_window_artifacts(
                recorder,
                (root / "runs" / project_id / "latest_nightly_window").resolve(),
            )
            self.assertEqual(recorder.failures(), [])

    def test_generic_non_thomson_project_path_works_for_helper_logic(self) -> None:
        tmp, root, project_id = self.make_sample_root()
        with tmp:
            old_root = run_nightly_window.ROOT
            run_nightly_window.ROOT = root
            try:
                project = run_nightly_window.load_project(project_id)
                state_dir = run_nightly_window.project_state_dir(project)
            finally:
                run_nightly_window.ROOT = old_root
            self.assertEqual(state_dir, root / "sample_repo" / ".agent_manager")


if __name__ == "__main__":
    unittest.main()
