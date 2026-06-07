"""Regression tests for Phase 18I guarded OpenHands decision-packet apply gate."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import apply_openhands_decision_packet as apply_script
from scripts import validate_agent_run


def _make_clean_git_repo(path: Path) -> None:
    """Initialize a git repo at *path* with one commit so it is clean."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("sample\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=Test", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _make_valid_packet(run_dir: Path, canonical_repo: Path) -> dict:
    """Create a synthetic valid decision packet in *run_dir*."""
    patch_file = run_dir / "OPENHANDS_PATCH.diff"
    patch_file.write_text("diff --git a/ADDED.txt b/ADDED.txt\nnew file mode 100644\nindex 0000000..e69de29\n--- /dev/null\n+++ b/ADDED.txt\n@@ -0,0 +1 @@\n+hello\n")
    patch_hash = apply_script.sha256_file(patch_file)

    packet: dict = {
        "schema_version": 1,
        "generated_by": "phase18g_openhands_decision_packet",
        "project_id": "test_project",
        "created_utc": "20260606T000000Z",
        "source_run_dir": str(run_dir),
        "canonical_repo": str(canonical_repo),
        "worktree_path": "",
        "worktree_branch": "",
        "base_branch": "",
        "worktree_head": "",
        "task_type": "manual_task_text",
        "exit_status": {"status": "pass", "returncode": 0},
        "scope_status": {"scope_status": "pass"},
        "changed_files": [],
        "canonical_repo_clean": True,
        "patch_file": str(patch_file),
        "patch_sha256": patch_hash,
        "patch_nonempty": True,
        "recommendation": "accept_for_manual_review",
    }
    (run_dir / "OPENHANDS_DECISION_PACKET.json").write_text(json.dumps(packet) + "\n")
    return packet


class ApplyGateTests(unittest.TestCase):
    """Test the apply_openhands_decision_packet.py script gates."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "run_dir"
        self.run_dir.mkdir()
        self.canonical_repo = self.root / "canonical_repo"
        _make_clean_git_repo(self.canonical_repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- check-only success from synthetic valid decision packet --

    def test_check_only_success_from_valid_packet(self) -> None:
        """check-only mode with a valid packet passes all gates."""
        _make_valid_packet(self.run_dir, self.canonical_repo)
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertEqual(status["status"], "pass")
        self.assertFalse(status["applied"])
        self.assertTrue(status["patch_sha256_verified"])
        self.assertTrue(status["git_apply_check_passed"])

    # -- default mode is check-only --

    def test_default_mode_is_check_only(self) -> None:
        """Without --apply, the script runs in check-only mode."""
        _make_valid_packet(self.run_dir, self.canonical_repo)
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertEqual(status["mode"], "check_only")

    # -- apply mode refuses without --allow-canonical-write --

    def test_apply_refuses_without_allow_canonical_write(self) -> None:
        _make_valid_packet(self.run_dir, self.canonical_repo)
        env = dict(os.environ, AGENT_MANAGER_ALLOW_CANONICAL_APPLY="1")
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
                "--apply",
                "--confirm-project", "test_project",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertEqual(status["status"], "fail")
        self.assertIn("--allow-canonical-write", status.get("refusal_reason", ""))

    # -- apply mode refuses without AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1 --

    def test_apply_refuses_without_env_gate(self) -> None:
        _make_valid_packet(self.run_dir, self.canonical_repo)
        env = dict(os.environ)
        env.pop("AGENT_MANAGER_ALLOW_CANONICAL_APPLY", None)
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
                "--apply",
                "--allow-canonical-write",
                "--confirm-project", "test_project",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertIn("AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1", status.get("refusal_reason", ""))

    # -- apply mode refuses without --confirm-project match --

    def test_apply_refuses_without_confirm_project_match(self) -> None:
        _make_valid_packet(self.run_dir, self.canonical_repo)
        env = dict(os.environ, AGENT_MANAGER_ALLOW_CANONICAL_APPLY="1")
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
                "--apply",
                "--allow-canonical-write",
                "--confirm-project", "wrong_project",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertIn("--confirm-project test_project", status.get("refusal_reason", ""))

    # -- refuses packet with wrong recommendation --

    def test_refuses_wrong_recommendation(self) -> None:
        _make_valid_packet(self.run_dir, self.canonical_repo)
        packet = json.loads((self.run_dir / "OPENHANDS_DECISION_PACKET.json").read_text())
        packet["recommendation"] = "discard_worktree"
        (self.run_dir / "OPENHANDS_DECISION_PACKET.json").write_text(json.dumps(packet) + "\n")
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertIn("recommendation is not 'accept_for_manual_review'", status.get("refusal_reason", ""))

    # -- refuses patch hash mismatch --

    def test_refuses_patch_hash_mismatch(self) -> None:
        _make_valid_packet(self.run_dir, self.canonical_repo)
        packet = json.loads((self.run_dir / "OPENHANDS_DECISION_PACKET.json").read_text())
        packet["patch_sha256"] = "a" * 64
        (self.run_dir / "OPENHANDS_DECISION_PACKET.json").write_text(json.dumps(packet) + "\n")
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertIn("patch sha256 mismatch", status.get("refusal_reason", ""))

    # -- refuses dirty canonical repo before apply --

    def test_refuses_dirty_canonical_repo(self) -> None:
        _make_valid_packet(self.run_dir, self.canonical_repo)
        (self.canonical_repo / "DIRTY.txt").write_text("dirty\n")
        subprocess.run(["git", "add", "DIRTY.txt"], cwd=self.canonical_repo, check=True, capture_output=True)
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertIn("canonical repo is currently dirty", status.get("refusal_reason", ""))

    # -- refuses failed git apply --check --

    def test_refuses_failed_git_apply_check(self) -> None:
        """Patch that conflicts with existing content fails git apply --check."""
        patch_file = self.run_dir / "OPENHANDS_PATCH.diff"
        patch_file.write_text("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old content\n+new content\n")
        patch_hash = apply_script.sha256_file(patch_file)

        packet: dict = {
            "schema_version": 1,
            "generated_by": "phase18g_openhands_decision_packet",
            "project_id": "test_project",
            "created_utc": "20260606T000000Z",
            "source_run_dir": str(self.run_dir),
            "canonical_repo": str(self.canonical_repo),
            "worktree_path": "",
            "worktree_branch": "",
            "base_branch": "",
            "worktree_head": "",
            "task_type": "manual_task_text",
            "exit_status": {"status": "pass", "returncode": 0},
            "scope_status": {"scope_status": "pass"},
            "changed_files": [],
            "canonical_repo_clean": True,
            "patch_file": str(patch_file),
            "patch_sha256": patch_hash,
            "patch_nonempty": True,
            "recommendation": "accept_for_manual_review",
        }
        (self.run_dir / "OPENHANDS_DECISION_PACKET.json").write_text(json.dumps(packet) + "\n")

        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertIn("git apply --check", status.get("refusal_reason", ""))

    # -- successful apply in temp repo applies patch but does not commit --

    def test_successful_apply_applies_patch_no_commit(self) -> None:
        """Apply mode with all gates passes and applies the patch without committing."""
        _make_valid_packet(self.run_dir, self.canonical_repo)
        env = dict(os.environ, AGENT_MANAGER_ALLOW_CANONICAL_APPLY="1")
        result = subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
                "--apply",
                "--allow-canonical-write",
                "--confirm-project", "test_project",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0)
        status = json.loads((self.run_dir / "OPENHANDS_APPLY_STATUS.json").read_text())
        self.assertTrue(status["applied"])
        self.assertEqual(status["status"], "pass")

        # Verify the patch was actually applied (ADDED.txt exists).
        added_file = self.canonical_repo / "ADDED.txt"
        self.assertTrue(added_file.exists(), "Patch should have created ADDED.txt in canonical repo.")

        # Verify no commit was made.
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.canonical_repo, capture_output=True, text=True)
        lines = [l for l in log.stdout.strip().splitlines() if l]
        self.assertEqual(len(lines), 1, "Only the original init commit should exist; no new commit.")

    # -- review markdown artifacts are generated --

    def test_review_markdown_artifacts_generated(self) -> None:
        """Check-only mode generates OPENHANDS_APPLY_STATUS.md and OPENHANDS_APPLY_REVIEW_COMMANDS.md."""
        _make_valid_packet(self.run_dir, self.canonical_repo)
        subprocess.run(
            [
                "python3", str(apply_script.ROOT / "scripts" / "apply_openhands_decision_packet.py"),
                "test_project",
                "--run-dir", str(self.run_dir),
            ],
            capture_output=True, text=True,
        )
        status_md = self.run_dir / "OPENHANDS_APPLY_STATUS.md"
        review_md = self.run_dir / "OPENHANDS_APPLY_REVIEW_COMMANDS.md"
        self.assertTrue(status_md.exists(), "OPENHANDS_APPLY_STATUS.md should be generated.")
        self.assertTrue(review_md.exists(), "OPENHANDS_APPLY_REVIEW_COMMANDS.md should be generated.")

        status_text = status_md.read_text()
        self.assertIn("test_project", status_text)
        self.assertIn("check_only", status_text)

        review_text = review_md.read_text()
        self.assertIn("--confirm-project", review_text)
        self.assertIn("apply --check", review_text)


class ValidationIntegrationTests(unittest.TestCase):
    """Test that validate_agent_run.py correctly validates OPENHANDS_APPLY_STATUS.json."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.coder_dir = self.root / "coder_dir"
        self.coder_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- validation accepts check-only pass --

    def test_validation_accepts_check_only_pass(self) -> None:
        status = {
            "schema_version": 1,
            "generated_by": "phase18i_guarded_openhands_patch_apply",
            "project_id": "test_project",
            "created_utc": "20260606T000000Z",
            "mode": "check_only",
            "source_run_dir": str(self.coder_dir),
            "packet_path": "",
            "patch_file": "",
            "patch_sha256": "abc123",
            "patch_sha256_verified": True,
            "canonical_repo": "",
            "canonical_repo_clean_before": True,
            "git_apply_check_passed": True,
            "applied": False,
            "apply_returncode": None,
            "canonical_repo_status_after": {},
            "refusal_reason": None,
            "status": "pass",
            "no_commit_push_merge_pr_performed": True,
        }
        (self.coder_dir / "OPENHANDS_APPLY_STATUS.json").write_text(json.dumps(status) + "\n")
        (self.coder_dir / "OPENHANDS_APPLY_STATUS.md").write_text("# Report\n")
        (self.coder_dir / "OPENHANDS_APPLY_REVIEW_COMMANDS.md").write_text("# Review\n")

        recorder = validate_agent_run.CheckRecorder()
        validate_agent_run.validate_openhands_apply_status(recorder, self.coder_dir)
        failed_ids = {check["id"] for check in recorder.failures()}
        self.assertEqual(failed_ids, set(), f"Expected no failures but got: {recorder.failures()}")

    # -- validation fails apply status fail --

    def test_validation_fails_on_apply_status_fail(self) -> None:
        status = {
            "schema_version": 1,
            "generated_by": "phase18i_guarded_openhands_patch_apply",
            "project_id": "test_project",
            "created_utc": "20260606T000000Z",
            "mode": "check_only",
            "source_run_dir": str(self.coder_dir),
            "packet_path": "",
            "patch_file": "",
            "patch_sha256": "abc123",
            "patch_sha256_verified": True,
            "canonical_repo": "",
            "canonical_repo_clean_before": True,
            "git_apply_check_passed": True,
            "applied": False,
            "apply_returncode": None,
            "canonical_repo_status_after": {},
            "refusal_reason": "something went wrong",
            "status": "fail",
            "no_commit_push_merge_pr_performed": True,
        }
        (self.coder_dir / "OPENHANDS_APPLY_STATUS.json").write_text(json.dumps(status) + "\n")

        recorder = validate_agent_run.CheckRecorder()
        validate_agent_run.validate_openhands_apply_status(recorder, self.coder_dir)
        failed_ids = {check["id"] for check in recorder.failures()}
        self.assertIn("openhands_apply_status_not_fail", failed_ids)


if __name__ == "__main__":
    unittest.main()
