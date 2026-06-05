# Model and Agent Routing Rules

1. Long-reasoning model owns planning, risk review, task decomposition, and final synthesis.
2. Instruct model owns structured summaries, classification, and normalization.
3. Vision model owns visual observation only.
4. Coding model owns repo edits only inside an isolated branch/worktree.
5. Deterministic validation outranks all model judgments.
6. No model may assign itself new permissions.
7. No model may expand scope beyond ACTIVE_OBJECTIVE or TASK_GRAPH.
8. No model may silently change validation criteria.
9. No write-capable model receives unrelated context.
10. One night produces at most one write-capable objective.

Phase 1 status:
- Routing is documented only.
- No model routing is active.
