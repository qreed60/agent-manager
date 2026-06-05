# Agent Manager Implementation Phases

## Phase 1 — Server-level agent-manager foundation
Create the reusable central directory structure, base configs, schemas, profile folders, runs folder, and worktree folder.

## Phase 2 — Project registry and project adapter stubs
Make project registration explicit and add adapter stubs for project-specific validation/metrics.

## Phase 3 — Agent profile foundation
Add manager, coder, validation review, SQA, security, scalability, and architecture profiles.

## Phase 4 — OpenHands profile switcher
Create a safe dry-run-first settings/profile switcher.

## Phase 5 — Project-local control state bootstrap
Add optional `.agent_manager/` state inside target projects.

## Phase 6 — Deterministic project metrics collector
Read project artifacts and produce structured metrics.

## Phase 7 — Plain Python runner v0
Run artifact-only nightly loop with no write-capable agent.

## Phase 8 — Manager planning pass
Use manager model to select one scoped objective and generate task graph.

## Phase 9 — Isolated coder execution
Run one coder task in an isolated worktree.

## Phase 10 — Deterministic validation harness
Run tests, schema checks, artifact checks, scope checks, and blocker checks.

## Phase 11 — Morning report and weekly plan update
Produce human review packet and update weekly state.

## Phase 12 — LangGraph migration
Move proven runner into checkpointed LangGraph execution.

## Phase 13 — Read-only review agents
Add validation review, SQA, and security agents.

## Phase 14 — Scalability and architecture agents
Add read-only scalability and architecture review.

## Phase 15 — Multi-model routing
Route tasks to long-reasoning, instruct, vision, and coder models.

## Phase 16 — Time-boxed multi-pass loop
Add 11 PM to 6 AM loop with no-new-work cutoff.

## Phase 17 — Human interrupts and draft PR support
Allow draft PR creation and approval checkpoints. No auto-merge.
