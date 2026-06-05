#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys


ROOT = Path.home() / "agent-manager"
DEFAULT_SETTINGS_FILE = Path.home() / ".openhands" / "agent_settings.json"


def fail(message: str) -> None:
    raise SystemExit(f"OpenHands profile apply failure: {message}")


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"missing JSON file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")

    if not isinstance(data, dict):
        fail(f"JSON root must be an object: {path}")

    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")


def profile_dir(profile: str) -> Path:
    path = ROOT / "profiles" / "openhands" / profile
    if not path.exists():
        known = sorted(p.name for p in (ROOT / "profiles" / "openhands").iterdir() if p.is_dir() and not p.name.startswith("_"))
        fail(f"unknown profile: {profile}. Known profiles: {', '.join(known)}")
    return path


def load_profile(profile: str) -> tuple[Path, dict]:
    pdir = profile_dir(profile)
    meta = load_json(pdir / "profile.json")
    return pdir, meta


def source_settings_example() -> Path | None:
    cached = ROOT / "profiles" / "openhands" / "_source" / "openhands_agent_settings.example.json"
    if cached.exists():
        return cached

    prompt_sources = ROOT / "configs" / "prompt_sources.json"
    if prompt_sources.exists():
        data = load_json(prompt_sources)
        repo = Path(data["sources"]["openhands_agent_prompts"]["repo_path"])
        candidate = repo / "config" / "openhands_agent_settings.example.json"
        if candidate.exists():
            return candidate

    return None


def load_base_settings(settings_file: Path, pdir: Path) -> tuple[dict, str]:
    if settings_file.exists():
        return load_json(settings_file), str(settings_file)

    example = source_settings_example()
    if example and example.exists():
        return load_json(example), str(example)

    template = pdir / "settings.template.json"
    return load_json(template), str(template)


def normalize_tools(tool_names: list[str]) -> list[dict]:
    return [{"name": name, "params": {}} for name in tool_names]


def ensure_default_tools(data: dict) -> None:
    existing = data.get("include_default_tools")
    if not isinstance(existing, list):
        existing = []

    for tool in ["FinishTool", "ThinkTool"]:
        if tool not in existing:
            existing.append(tool)

    data["include_default_tools"] = existing


def apply_llm_runtime(section: dict, profile: str, max_output_tokens: int, preserve_thinking: bool) -> None:
    section.update({
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
        "usage_id": profile,
    })

    extra_body = section.get("litellm_extra_body")
    if not isinstance(extra_body, dict):
        extra_body = {}

    extra_body.update({
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
    })

    chat_kwargs = extra_body.get("chat_template_kwargs")
    if not isinstance(chat_kwargs, dict):
        chat_kwargs = {}

    chat_kwargs["enable_thinking"] = True
    chat_kwargs["preserve_thinking"] = preserve_thinking
    extra_body["chat_template_kwargs"] = chat_kwargs
    section["litellm_extra_body"] = extra_body


def build_settings(base: dict, profile: str, meta: dict, max_output_tokens: int, preserve_thinking: bool) -> dict:
    data = dict(base)

    data["kind"] = "Agent"
    data["system_prompt_filename"] = "system_prompt.j2"
    data["security_policy_filename"] = "security_policy.j2"
    data["tool_concurrency_limit"] = 1

    allowed_tools = meta.get("allowed_tools")
    if not isinstance(allowed_tools, list):
        fail(f"profile missing list field allowed_tools: {profile}")

    data["tools"] = normalize_tools(allowed_tools)
    ensure_default_tools(data)

    kwargs = data.get("system_prompt_kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}
    kwargs["cli_mode"] = True
    kwargs["llm_security_analyzer"] = True
    kwargs["agent_manager_profile"] = profile
    kwargs["agent_manager_write_access"] = bool(meta.get("write_access", False))
    data["system_prompt_kwargs"] = kwargs

    if isinstance(data.get("llm"), dict):
        apply_llm_runtime(data["llm"], profile, max_output_tokens, preserve_thinking)
    else:
        # Some exported examples use top-level model/base_url fields instead of .llm.
        if "model" in data or "base_url" in data:
            apply_llm_runtime(data, profile, max_output_tokens, preserve_thinking)

    condenser = data.get("condenser")
    if isinstance(condenser, dict):
        condenser["max_size"] = 120
        if isinstance(condenser.get("llm"), dict):
            apply_llm_runtime(condenser["llm"], f"{profile}_condenser", max_output_tokens, preserve_thinking)

    return data


def copy_with_backup(src: Path, dst: Path, backup_dir: Path, label: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, backup_dir / f"{label}.bak")
    shutil.copy2(src, dst)


def apply_profile(
    profile: str,
    settings_file: Path,
    apply: bool,
    max_output_tokens: int,
    preserve_thinking: bool,
) -> int:
    pdir, meta = load_profile(profile)

    if not (pdir / "system_prompt.j2").exists():
        fail(f"profile is missing system_prompt.j2: {pdir}")

    if not (pdir / "security_policy.j2").exists():
        fail(f"profile is missing security_policy.j2: {pdir}")

    base, base_source = load_base_settings(settings_file, pdir)
    rendered = build_settings(base, profile, meta, max_output_tokens, preserve_thinking)

    settings_dir = settings_file.parent
    prompt_dst = settings_dir / "system_prompt.j2"
    policy_dst = settings_dir / "security_policy.j2"

    print(f"Profile: {profile}")
    print(f"Write access: {meta.get('write_access')}")
    print(f"Settings file: {settings_file}")
    print(f"Base settings source: {base_source}")
    print(f"Prompt source: {pdir / 'system_prompt.j2'}")
    print(f"Policy source: {pdir / 'security_policy.j2'}")
    print(f"Prompt destination: {prompt_dst}")
    print(f"Policy destination: {policy_dst}")
    print(f"max_output_tokens: {max_output_tokens}")
    print(f"preserve_thinking: {preserve_thinking}")

    if not apply:
        print("Dry run: true")
        print("Apply status: dry run successful; no files modified")
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = settings_dir / ".agent_manager_backups" / f"{profile}_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if settings_file.exists():
        shutil.copy2(settings_file, backup_dir / "agent_settings.json.bak")

    copy_with_backup(pdir / "system_prompt.j2", prompt_dst, backup_dir, "system_prompt.j2")
    copy_with_backup(pdir / "security_policy.j2", policy_dst, backup_dir, "security_policy.j2")

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(settings_file, rendered)

    manifest = {
        "profile": profile,
        "settings_file": str(settings_file),
        "backup_dir": str(backup_dir),
        "prompt_destination": str(prompt_dst),
        "policy_destination": str(policy_dst),
        "timestamp_utc": timestamp,
    }
    write_json(backup_dir / "manifest.json", manifest)

    print("Dry run: false")
    print("Apply status: success")
    print(f"Backup dir: {backup_dir}")
    print("Restore command:")
    print(f"  cp {backup_dir}/agent_settings.json.bak {settings_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply central agent-manager OpenHands profile.")
    parser.add_argument("--profile", required=True, help="Profile name, e.g. coder, manager, security")
    parser.add_argument("--settings-file", default=str(DEFAULT_SETTINGS_FILE), help="OpenHands agent_settings.json path")
    parser.add_argument("--apply", action="store_true", help="Actually write settings and prompt files")
    parser.add_argument("--max-output-tokens", type=int, default=24000)
    parser.add_argument("--preserve-thinking", action="store_true", default=True)
    parser.add_argument("--no-preserve-thinking", action="store_false", dest="preserve_thinking")

    args = parser.parse_args(argv)

    if args.max_output_tokens <= 0:
        fail("--max-output-tokens must be positive")

    return apply_profile(
        profile=args.profile,
        settings_file=Path(args.settings_file).expanduser(),
        apply=args.apply,
        max_output_tokens=args.max_output_tokens,
        preserve_thinking=args.preserve_thinking,
    )


if __name__ == "__main__":
    raise SystemExit(main())
