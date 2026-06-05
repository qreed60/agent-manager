# Agent Manager

Central reusable overnight agent-manager framework.

This project is installed on the LLM server and can run against multiple target projects.

The framework owns:
- project registry
- shared schemas
- agent profiles
- OpenHands profile switching
- runner/orchestration code in later phases
- generated runs, logs, reports, and worktrees

Target projects own only project-specific state, such as:
- project safety rules
- weekly plan
- objective backlog
- validation adapter configuration
- optional committed `.agent_manager/` project state

Current phase:
- Phase 1: server-level foundation only.

Phase 1 forbids:
- model calls
- OpenHands execution
- LangGraph execution
- coder-agent execution
- source-code modification in target projects
- auto-merge
- auto-push
