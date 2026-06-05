#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ID="${1:-${AGENT_MANAGER_PROJECT_ID:-}}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 <project_id>"
  echo "Or set AGENT_MANAGER_PROJECT_ID."
  exit 2
fi

python3 -m json.tool configs/projects.json >/dev/null
python3 -m json.tool configs/global_policy.json >/dev/null
python3 -m json.tool configs/model_registry.json >/dev/null

python3 -m agent_manager.cli list-projects
python3 -m agent_manager.cli show-project "$PROJECT_ID" >"/tmp/agent-manager-${PROJECT_ID}-project.json"
python3 -m agent_manager.cli adapter-info "$PROJECT_ID" >"/tmp/agent-manager-${PROJECT_ID}-adapter.json"

echo "Phase 2 smoke test complete."
echo "Project JSON: /tmp/agent-manager-${PROJECT_ID}-project.json"
echo "Adapter JSON: /tmp/agent-manager-${PROJECT_ID}-adapter.json"
