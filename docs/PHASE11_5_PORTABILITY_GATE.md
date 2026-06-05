# Phase 11.5 Portability Gate

Phase 11.5 hardens the agent manager before LangGraph migration. The central framework must be able to load and reason about a non-ThomsonLint project without assuming that every project is ThomsonLint.

## Allowed ThomsonLint References

These references are allowed:

- `configs/projects.json` entries registering `thomsonlint` as the first real project.
- `agent_manager/adapters/thomsonlint.py`, which is project-specific adapter code by design.
- Documentation that explicitly describes ThomsonLint as the first or example project.
- Phase labels and validation check ids such as `phase10_*` and `phase11_*` when they name workflow artifacts rather than a project.

## Disallowed Core Coupling

Core scripts and shared framework modules must not require:

- `project_id == thomsonlint`
- the path `/mnt/projects/ThomsonLint`
- the branch `agent-manager-project-state`
- generated objective ids such as `review_phase11_morning_report`

Project-specific behavior belongs in project config or a named adapter. Generic code should work for any registered project with a supported adapter.

## Register Another Project

Add a project entry to `configs/projects.json`:

```json
{
  "name": "Example Project",
  "repo_path": "/path/to/repo",
  "project_type": "git_repo",
  "state_mode": "central",
  "project_state_dir": ".agent_manager",
  "server_state_dir": "runs/example",
  "worktree_root": "worktrees/example",
  "default_branch": "main",
  "validation_adapter": "generic_git",
  "enabled": true
}
```

Use `validation_adapter: "generic_git"` for a simple repository that only needs basic git status, branch, HEAD, and repo existence checks. Use a project-specific adapter only when the project needs custom metrics or validation planning.

## Run The Audit

```bash
python3 scripts/audit_portability.py
python3 scripts/audit_portability.py --json
```

The audit ignores `.git/`, `runs/`, `worktrees/`, `tmp/`, `__pycache__/`, and `.pytest_cache/`. It exits nonzero only for `blocking_core_coupling` findings.

## Run Portability Tests

```bash
python3 -m unittest discover -s tests
```

The tests cover the existing ThomsonLint registration, a sample non-ThomsonLint project config, `generic_git` adapter instantiation, derived morning-report follow-up objective ids, and the portability audit.

## Why Before LangGraph

LangGraph migration will make project routing and workflow state more explicit. Fixing project assumptions first keeps the graph generic, makes adapter routing testable, and avoids encoding ThomsonLint-specific state into graph nodes.
