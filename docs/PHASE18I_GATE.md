# Phase 18I: Guarded Manual OpenHands Decision-Packet Apply Gate

## Purpose

Phase 18I provides a deterministic, heavily-gated script that can **check** and **optionally apply** an accepted OpenHands patch (`OPENHANDS_DECISION_PACKET.json` + `OPENHANDS_PATCH.diff`) to the canonical repository.

This is the final safety gate in the Phase 18 chain:
- Phase 18G generates the decision packet and patch diff.
- Phase 18H proved OpenHands can make a bounded real file edit in an isolated worktree.
- **Phase 18I** provides the manual apply mechanism with multiple refusal gates.

## Check-Only Default

The script runs in **check-only mode by default**. No flags are required:

```bash
python3 scripts/apply_openhands_decision_packet.py <PROJECT_ID>
```

In check-only mode:
- The patch is validated against all preconditions (packet integrity, hash verification, repo cleanliness).
- `git apply --check` is run to verify the patch would apply cleanly.
- **No changes are made** to the canonical repository.
- Artifacts are generated for review.

## Explicit Apply Gates

Apply mode requires **all four** of these conditions simultaneously:

1. `--apply` flag present on the command line
2. `--allow-canonical-write` flag present on the command line
3. `--confirm-project <PROJECT_ID>` exactly matching the project ID in the packet
4. Environment variable `AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1` set

If any gate is missing, the script refuses with a clear refusal reason and returns exit code 1:

```bash
AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1 \
  python3 scripts/apply_openhands_decision_packet.py \
  <PROJECT_ID> \
  --run-dir runs/<PROJECT_ID>/latest_openhands_coder \
  --packet runs/<PROJECT_ID>/latest_openhands_coder/OPENHANDS_DECISION_PACKET.json \
  --apply \
  --allow-canonical-write \
  --confirm-project <PROJECT_ID>
```

## Preconditions (All Must Pass)

The script refuses if **any** of these conditions are true:

| Check | Refusal Reason |
|-------|---------------|
| Decision packet missing | `decision packet error: missing file` |
| `generated_by != phase18g_openhands_decision_packet` | `generated_by mismatch` |
| `project_id` mismatch | `project_id mismatch` |
| `recommendation != accept_for_manual_review` | `recommendation is not 'accept_for_manual_review'` |
| `canonical_repo_clean != true` in packet | `packet canonical_repo_clean is not true` |
| `scope_status.scope_status != pass` | `scope_status scope_status is not pass` |
| `exit_status.status != pass` | `exit_status status is not pass` |
| `patch_nonempty != true` | `patch_nonempty is not true` |
| Patch file missing on disk | `patch file missing` |
| Patch SHA256 mismatch | `patch sha256 mismatch` |
| Canonical repo dirty before operation | `canonical repo is currently dirty before check/apply` |
| `git apply --check` fails | `patch does not pass git apply --check: ...` |
| Apply mode missing any gate | `apply mode refused: missing explicit gates: ...` |

## Generated Artifacts

All three artifacts are written to the OpenHands run directory (`runs/<PROJECT_ID>/latest_openhands_coder/`):

### OPENHANDS_APPLY_STATUS.json

Structured status with all fields defined in the requirements:
- `schema_version`, `generated_by`, `project_id`, `created_utc`
- `mode`: `"check_only"` or `"apply"`
- `source_run_dir`, `packet_path`, `patch_file`, `patch_sha256`
- `patch_sha256_verified`: boolean
- `canonical_repo`, `canonical_repo_clean_before`
- `git_apply_check_passed`: boolean
- `applied`: boolean (true only in apply mode with all gates passing)
- `apply_returncode`: int or null
- `canonical_repo_status_after`: dict with working_tree/untracked counts
- `refusal_reason`: string or null
- `status`: `"pass"`, `"warn"`, or `"fail"`
- `no_commit_push_merge_pr_performed`: always `true`

### OPENHANDS_APPLY_STATUS.md

Human-readable summary including:
- Project ID, mode, recommendation
- Patch file path and SHA256
- Git apply --check result (PASS/FAIL)
- Whether the patch was applied
- Canonical repo status before and after
- Refusal reason if any

### OPENHANDS_APPLY_REVIEW_COMMANDS.md

Step-by-step manual review commands:
1. Inspect decision packet (`python3 -m json.tool ...`)
2. Inspect patch (`sed -n '1,240p' ...`)
3. Check patch against canonical repo (`git apply --check ...`)
4. Explicitly-gated apply command (with all four gates shown)
5. Reminder: no commit/push/merge/PR

## Safe Manual Workflow

```bash
# 1. Run check-only to validate the patch
python3 scripts/apply_openhands_decision_packet.py my_project \
  --run-dir runs/my_project/latest_openhands_coder

# 2. Review the generated artifacts
cat runs/my_project/latest_openhands_coder/OPENHANDS_APPLY_STATUS.md
cat runs/my_project/latest_openhands_coder/OPENHANDS_APPLY_REVIEW_COMMANDS.md

# 3. If satisfied, run the explicitly-gated apply command from the review file
AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1 \
  python3 scripts/apply_openhands_decision_packet.py my_project \
  --run-dir runs/my_project/latest_openhands_coder \
  --apply --allow-canonical-write --confirm-project my_project

# 4. Manually inspect the working tree changes
git -C /path/to/canonical/repo status
git -C /path/to/canonical/repo diff
```

## Why This Is Still Not Overnight OpenHands

1. **Check-only default**: The script does nothing to the canonical repo unless explicitly told otherwise with multiple flags.
2. **Four independent gates**: All four apply gates must be satisfied simultaneously. Missing any one causes refusal.
3. **Environment variable gate**: `AGENT_MANAGER_ALLOW_CANONICAL_APPLY=1` cannot be set by a flag alone; it requires an explicit environment variable.
4. **No automated commit/push/merge/PR**: The script uses `git apply` which modifies the working tree but does not create commits, pushes, merges, or PRs.
5. **Not enabled in nightly**: This script is NOT referenced by `run_nightly_window.py`. It must be invoked manually.
6. **Precondition checks**: Every step of Phase 18G's output is validated before any operation proceeds.
7. **Canonical repo cleanliness check**: The script refuses if the canonical repo has uncommitted changes, preventing accidental overwrites.

## No Commit / Push / Merge / PR Behavior

The script:
- Does NOT call `git commit`
- Does NOT call `git push`
- Does NOT call `git merge`
- Does NOT create pull requests or merge requests
- Uses only `git apply` which modifies the working tree without creating a commit

After applying, the user must manually inspect changes and decide whether to commit:

```bash
git status    # See what changed
git diff      # Review the actual diff
git add . && git commit -m "Apply OpenHands patch"  # Manual decision point
```

## Validation Integration

`scripts/validate_agent_run.py` validates `OPENHANDS_APPLY_STATUS.json` when present:
- Requires `generated_by == phase18i_guarded_openhands_patch_apply`
- Fails if `status == "fail"`
- Requires `no_commit_push_merge_pr_performed == true`
- Requires `patch_sha256_verified == true`
- For check-only mode: requires `canonical_repo_clean_before == true` and `git_apply_check_passed == true`
- Validates markdown artifacts exist when JSON is present

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `scripts/apply_openhands_decision_packet.py` | Created | Guarded apply script with all gates |
| `scripts/validate_agent_run.py` | Modified | Added `validate_openhands_apply_status()` and integration |
| `tests/test_apply_openhands_decision_packet.py` | Created | 13 regression tests covering all gates and modes |
| `docs/PHASE18I_GATE.md` | Created | This documentation file |
