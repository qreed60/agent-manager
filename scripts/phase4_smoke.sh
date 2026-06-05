#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

TEST_DIR="/tmp/agent-manager-phase4-openhands"
TEST_SETTINGS="${TEST_DIR}/agent_settings.json"

rm -rf "${TEST_DIR}"
mkdir -p "${TEST_DIR}"

SOURCE_SETTINGS="profiles/openhands/_source/openhands_agent_settings.example.json"
if [[ -f "${SOURCE_SETTINGS}" ]]; then
  cp "${SOURCE_SETTINGS}" "${TEST_SETTINGS}"
else
  cp "profiles/openhands/coder/settings.template.json" "${TEST_SETTINGS}"
fi

python3 scripts/apply_openhands_profile.py \
  --profile coder \
  --settings-file "${TEST_SETTINGS}"

python3 scripts/apply_openhands_profile.py \
  --profile coder \
  --settings-file "${TEST_SETTINGS}" \
  --apply

python3 -m json.tool "${TEST_SETTINGS}" >/dev/null

test -f "${TEST_DIR}/system_prompt.j2"
test -f "${TEST_DIR}/security_policy.j2"

grep -q "Agent" "${TEST_SETTINGS}"

echo "Phase 4 smoke test complete."
echo "Test dir: ${TEST_DIR}"
