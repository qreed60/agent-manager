# Phase 6 Gate

Phase 6 is complete when:

- `scripts/collect_project_metrics.py` exists.
- The collector writes central run artifacts under `runs/<project_id>/<timestamp>/`.
- The collector creates or updates `runs/<project_id>/latest`.
- Generated artifacts include:
  - `RUN_METRICS.json`
  - `UNKNOWN_ANALYSIS.json`
  - `VALIDATION_SUMMARY.json`
- All generated JSON parses.
- The target repo is read-only during collection.
- No OpenHands run occurs.
- No model calls occur.
- No LangGraph runtime occurs.
- No target project source behavior is modified.
