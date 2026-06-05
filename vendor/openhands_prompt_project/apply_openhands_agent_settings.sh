#!/usr/bin/env bash
set -euo pipefail

DEFAULT_SETTINGS_FILE="${HOME}/.openhands/agent_settings.json"
DEFAULT_MAX_OUTPUT_TOKENS=24000

settings_file="${DEFAULT_SETTINGS_FILE}"
max_output_tokens="${DEFAULT_MAX_OUTPUT_TOKENS}"
preserve_thinking=1
dry_run=0

usage() {
  cat <<'EOF'
Usage: bash scripts/apply_openhands_agent_settings.sh [options]

Options:
  --settings-file PATH     OpenHands agent_settings.json path.
  --max-output-tokens N    max_output_tokens to apply. Default: 24000.
  --preserve-thinking      Preserve Qwen thinking context across turns. Default.
  --no-preserve-thinking   Keep thinking enabled, but disable preserve_thinking.
  --dry-run                Validate and summarize without writing.
  -h, --help               Show this help.
EOF
}

fail() {
  printf 'Settings apply failure: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --settings-file)
      [[ $# -ge 2 ]] || fail "--settings-file requires a path"
      settings_file="$2"
      shift 2
      ;;
    --max-output-tokens)
      [[ $# -ge 2 ]] || fail "--max-output-tokens requires an integer"
      max_output_tokens="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --preserve-thinking)
      preserve_thinking=1
      shift
      ;;
    --no-preserve-thinking)
      preserve_thinking=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

case "${max_output_tokens}" in
  ''|*[!0-9]*)
    fail "--max-output-tokens must be a positive integer"
    ;;
esac
if [[ "${max_output_tokens}" -le 0 ]]; then
  fail "--max-output-tokens must be a positive integer"
fi

[[ -f "${settings_file}" ]] || fail "settings file is missing: ${settings_file}"

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

python3 - "${settings_file}" "${max_output_tokens}" "${preserve_thinking}" >"${tmp_file}" <<'PY'
import json
import pathlib
import sys

settings_path = pathlib.Path(sys.argv[1])
max_output_tokens = int(sys.argv[2])
preserve_thinking = bool(int(sys.argv[3]))

data = json.loads(settings_path.read_text())
if not isinstance(data, dict):
    raise SystemExit("agent settings root must be a JSON object")

llm = data.get("llm")
if not isinstance(llm, dict):
    raise SystemExit("agent settings must contain an object at .llm")

runtime_profile = {
    "temperature": 0.6,
    "top_p": 0.95,
    "top_k": 20,
    "max_input_tokens": 131072,
    "max_output_tokens": max_output_tokens,
    "timeout": None,
    "disable_vision": True,
    "caching_prompt": True,
    "prompt_cache_retention": "24h",
    "native_tool_calling": True,
    "drop_params": True,
    "modify_params": True,
    "stream": False,
    "reasoning_effort": "high",
    "enable_encrypted_reasoning": True,
    "extended_thinking_budget": 65536,
}

extra_body_profile = {
    "min_p": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
}

def apply_llm_profile(target, usage_id):
    target.update(runtime_profile)
    target["usage_id"] = usage_id
    extra_body = target.get("litellm_extra_body")
    if not isinstance(extra_body, dict):
        extra_body = {}
    extra_body.update(extra_body_profile)
    chat_template_kwargs = extra_body.get("chat_template_kwargs")
    if not isinstance(chat_template_kwargs, dict):
        chat_template_kwargs = {}
    chat_template_kwargs["enable_thinking"] = True
    chat_template_kwargs["preserve_thinking"] = preserve_thinking
    extra_body["chat_template_kwargs"] = chat_template_kwargs
    target["litellm_extra_body"] = extra_body

def ensure_unique_items(root, key, required_items):
    existing = root.get(key)
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        raise SystemExit(f".{key} must be a list when present")
    seen = set()
    result = []
    for item in existing + required_items:
        item_key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if item_key not in seen:
            result.append(item)
            seen.add(item_key)
    root[key] = result

apply_llm_profile(llm, "agent")

condenser = data.get("condenser")
if isinstance(condenser, dict):
    condenser["max_size"] = 120
    condenser_llm = condenser.get("llm")
    if isinstance(condenser_llm, dict):
        apply_llm_profile(condenser_llm, "condenser")

data["system_prompt_filename"] = "system_prompt.j2"
data["security_policy_filename"] = "security_policy.j2"
data["tool_concurrency_limit"] = 1
data["kind"] = "Agent"

ensure_unique_items(data, "tools", ["terminal", "file_editor", "task_tracker", "task_tool_set"])
ensure_unique_items(data, "include_default_tools", ["FinishTool", "ThinkTool"])

system_prompt_kwargs = data.get("system_prompt_kwargs")
if not isinstance(system_prompt_kwargs, dict):
    system_prompt_kwargs = {}
system_prompt_kwargs["cli_mode"] = True
system_prompt_kwargs["llm_security_analyzer"] = True
data["system_prompt_kwargs"] = system_prompt_kwargs

json.dump(data, sys.stdout, indent=2, sort_keys=False)
sys.stdout.write("\n")
PY

if [[ "${dry_run}" -eq 1 ]]; then
  printf 'Settings file: %s\n' "${settings_file}"
  printf 'Dry run: true\n'
  printf 'max_output_tokens: %s\n' "${max_output_tokens}"
  printf 'preserve_thinking: %s\n' "${preserve_thinking}"
  printf 'Apply status: dry run successful; settings file was not modified\n'
  printf 'Would update: .llm, top-level tools/defaults, system prompt filenames, and existing .condenser/.condenser.llm when present\n'
  exit 0
fi

backup_file="${settings_file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "${settings_file}" "${backup_file}"
cp "${tmp_file}" "${settings_file}"

printf 'Settings file: %s\n' "${settings_file}"
printf 'Backup file: %s\n' "${backup_file}"
printf 'Apply status: success\n'
printf 'Restore command: cp %q %q\n' "${backup_file}" "${settings_file}"
