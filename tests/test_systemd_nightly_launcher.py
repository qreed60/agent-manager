from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import validate_agent_run


ROOT = Path(__file__).resolve().parents[1]


class SystemdNightlyLauncherTests(unittest.TestCase):
    def test_service_file_contains_safe_user_mode_execution(self) -> None:
        service = (ROOT / "systemd" / "agent-manager-nightly@.service").read_text()
        self.assertNotIn("User=", service)
        self.assertNotIn("Group=", service)
        self.assertIn("WorkingDirectory=/home/qreed/agent-manager", service)
        self.assertIn(
            "Environment=PATH=/home/qreed/agent-manager/.venv/bin:/usr/local/bin:/usr/bin:/bin",
            service,
        )
        self.assertIn("AGENT_MANAGER_NO_MODEL_CALLS=1", service)
        self.assertIn("AGENT_MANAGER_NO_OPENHANDS=1", service)
        self.assertIn("AGENT_MANAGER_MAX_CODE_WRITING_TASKS=0", service)
        self.assertIn("Restart=no", service)

    def test_service_invokes_run_nightly_window_with_project_template(self) -> None:
        service = (ROOT / "systemd" / "agent-manager-nightly@.service").read_text()
        self.assertIn(
            "ExecStart=/home/qreed/agent-manager/.venv/bin/python /home/qreed/agent-manager/scripts/run_nightly_window.py %i",
            service,
        )

    def test_timer_uses_2300_without_randomized_delay(self) -> None:
        timer = (ROOT / "systemd" / "agent-manager-nightly@.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 23:00:00", timer)
        self.assertIn("Persistent=true", timer)
        active_lines = "\n".join(line for line in timer.splitlines() if not line.strip().startswith("#"))
        self.assertNotIn("RandomizedDelaySec", active_lines)

    def test_install_script_does_not_run_immediately_by_default(self) -> None:
        script = (ROOT / "scripts" / "install_nightly_timer.sh").read_text()
        self.assertIn("RUN_NOW=0", script)
        self.assertIn("[[ \"${1:-}\" == \"--run-now\" ]]", script)
        self.assertIn("No immediate nightly run was started.", script)
        self.assertIn("systemctl --user enable \"$TIMER_NAME\"", script)
        self.assertIn("systemctl --user start \"$SERVICE_NAME\"", script)

    def test_max_code_writing_tasks_remains_disabled_by_default(self) -> None:
        policy = (ROOT / "configs" / "nightly_window_policy.json").read_text()
        self.assertIn('"max_code_writing_tasks": 0', policy)
        service = (ROOT / "systemd" / "agent-manager-nightly@.service").read_text()
        self.assertIn("AGENT_MANAGER_MAX_CODE_WRITING_TASKS=0", service)

    def test_validation_accepts_systemd_artifacts(self) -> None:
        recorder = validate_agent_run.CheckRecorder()
        validate_agent_run.validate_systemd_artifacts(recorder)
        self.assertEqual(recorder.failures(), [])

    def test_validation_rejects_user_or_group_in_user_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "systemd").mkdir()
            (root / "scripts").mkdir()
            (root / "configs").mkdir()
            service = (ROOT / "systemd" / "agent-manager-nightly@.service").read_text()
            (root / "systemd" / "agent-manager-nightly@.service").write_text(
                service.replace("Type=oneshot\n", "Type=oneshot\nUser=qreed\nGroup=qreed\n")
            )
            (root / "systemd" / "agent-manager-nightly@.timer").write_text(
                (ROOT / "systemd" / "agent-manager-nightly@.timer").read_text()
            )
            (root / "scripts" / "install_nightly_timer.sh").write_text(
                (ROOT / "scripts" / "install_nightly_timer.sh").read_text()
            )
            (root / "scripts" / "check_nightly_timer.sh").write_text(
                (ROOT / "scripts" / "check_nightly_timer.sh").read_text()
            )
            (root / "configs" / "nightly_window_policy.json").write_text(
                (ROOT / "configs" / "nightly_window_policy.json").read_text()
            )

            old_root = validate_agent_run.ROOT
            validate_agent_run.ROOT = root
            try:
                recorder = validate_agent_run.CheckRecorder()
                validate_agent_run.validate_systemd_artifacts(recorder)
            finally:
                validate_agent_run.ROOT = old_root

        failed_ids = {check["id"] for check in recorder.failures()}
        self.assertIn("systemd_service_no_user", failed_ids)
        self.assertIn("systemd_service_no_group", failed_ids)


if __name__ == "__main__":
    unittest.main()
