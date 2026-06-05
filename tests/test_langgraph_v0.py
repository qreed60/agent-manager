from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import run_langgraph_v0


class LangGraphV0HelperTests(unittest.TestCase):
    def test_tail_text_limits_lines_and_chars(self) -> None:
        text = "\n".join(f"line-{idx}" for idx in range(100))
        tail = run_langgraph_v0.tail_text(text, max_lines=3, max_chars=100)
        self.assertEqual(tail, "line-97\nline-98\nline-99")

        long_tail = run_langgraph_v0.tail_text("x" * 20, max_lines=40, max_chars=5)
        self.assertEqual(long_tail, "x" * 5)

    def test_append_trace_writes_json_compatible_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = run_langgraph_v0.initial_state("sample_project", "20260605T000000Z", run_dir)
            entry = run_langgraph_v0.new_trace_entry(
                "load_project",
                "pass",
                "20260605T000000Z",
                "20260605T000001Z",
                artifacts_read=["configs/projects.json"],
            )

            updated = run_langgraph_v0.append_trace(state, entry)

            self.assertEqual(updated["trace"][0]["node"], "load_project")
            self.assertTrue((run_dir / "LANGGRAPH_NODE_TRACE.json").exists())
            self.assertIn("configs/projects.json", (run_dir / "LANGGRAPH_NODE_TRACE.json").read_text())

    def test_initial_state_is_artifact_reference_only(self) -> None:
        state = run_langgraph_v0.initial_state(
            "sample_project",
            "20260605T000000Z",
            Path("/tmp/langgraph_v0_test"),
        )
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["artifacts"], {})
        self.assertEqual(state["trace"], [])

    def test_node_order_is_deterministic(self) -> None:
        self.assertEqual(
            run_langgraph_v0.NODE_ORDER,
            [
                "load_project",
                "collect_metrics",
                "run_plain_runner_v0",
                "run_manager_planning_pass",
                "write_morning_report",
                "validate_agent_run",
                "run_readonly_review_agents",
                "compile_model_routing_plan",
                "prepare_human_approval_packet",
                "finalize",
            ],
        )


if __name__ == "__main__":
    unittest.main()
