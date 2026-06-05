#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m json.tool configs/projects.json >/dev/null
python3 -m json.tool configs/global_policy.json >/dev/null
python3 -m json.tool configs/model_registry.json >/dev/null

python3 -m agent_manager.cli list-projects
python3 -m agent_manager.cli show-project thomsonlint >/tmp/agent-manager-thomsonlint-project.json
python3 -m agent_manager.cli adapter-info thomsonlint >/tmp/agent-manager-thomsonlint-adapter.json

echo "Phase 2 smoke test complete."
echo "Project JSON: /tmp/agent-manager-thomsonlint-project.json"
echo "Adapter JSON: /tmp/agent-manager-thomsonlint-adapter.json"
