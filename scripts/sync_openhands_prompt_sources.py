#!/usr/bin/env python3
from pathlib import Path
import json
import shutil

ROOT = Path.home() / "agent-manager"
PROMPT_SOURCES = ROOT / "configs" / "prompt_sources.json"

def fail(msg: str) -> None:
    raise SystemExit(f"Prompt source sync failure: {msg}")

if not PROMPT_SOURCES.exists():
    fail(f"missing {PROMPT_SOURCES}")

data = json.loads(PROMPT_SOURCES.read_text())
source_root = Path(data["sources"]["openhands_agent_prompts"]["repo_path"])

if not source_root.exists():
    fail(f"prompt source repo does not exist: {source_root}")

qwen_prompt = source_root / "prompts" / "profiles" / "qwen3_6_agentic_development.j2"
settings_example = source_root / "config" / "openhands_agent_settings.example.json"
apply_script = source_root / "scripts" / "apply_openhands_agent_settings.sh"

for path in [qwen_prompt, settings_example, apply_script]:
    if not path.exists():
        fail(f"missing expected source file: {path}")

coder_profile = ROOT / "profiles" / "openhands" / "coder"
source_cache = ROOT / "profiles" / "openhands" / "_source"
vendor_dir = ROOT / "vendor" / "openhands_prompt_project"

source_cache.mkdir(parents=True, exist_ok=True)
vendor_dir.mkdir(parents=True, exist_ok=True)

shutil.copy2(qwen_prompt, coder_profile / "system_prompt.j2")
shutil.copy2(settings_example, source_cache / "openhands_agent_settings.example.json")
shutil.copy2(apply_script, vendor_dir / "apply_openhands_agent_settings.sh")

print("Synced OpenHands prompt sources.")
print(f"Coder prompt: {coder_profile / 'system_prompt.j2'}")
print(f"Settings example cache: {source_cache / 'openhands_agent_settings.example.json'}")
print(f"Vendor apply script: {vendor_dir / 'apply_openhands_agent_settings.sh'}")
