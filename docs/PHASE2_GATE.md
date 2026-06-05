# Phase 2 Gate

Phase 2 is complete when:

- `python3 -m agent_manager.cli list-projects` works.
- `python3 -m agent_manager.cli show-project thomsonlint` works.
- `python3 -m agent_manager.cli adapter-info thomsonlint` works.
- `scripts/phase2_smoke.sh` works.
- The ThomsonLint adapter is a stub only.
- No OpenHands execution occurs.
- No model calls occur.
- No LangGraph runtime exists.
- No target project source files are modified.

If `doctor` reports the ThomsonLint repo path is missing, either:
1. clone/copy ThomsonLint onto this server later, or
2. edit `configs/projects.json` to the correct path.
