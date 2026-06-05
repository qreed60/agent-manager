#!/usr/bin/env python3
"""Phase 18A: Model-backed read-only AI agent.

Advisory-only AI review of latest deterministic artifacts.
No source writes, no OpenHands execution, no push/merge/PR creation.

Live model calls require BOTH:
  --allow-model-call CLI flag AND AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 env var.
Default mode is dry-run (no model call).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.client
import json
from json import dumps as json_dumps
from json import loads as json_loads
from pathlib import Path
import random
import re
import socket
import ssl
from typing import Any
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase18a_ai_readonly_agent"

REQUIRED_ARTIFACTS_JSON = [
    "AI_READONLY_REVIEW.json",
    "AI_RESPONSE_PARSED.json",
    "AI_SAFETY_STATUS.json",
    "AI_READONLY_SUMMARY.json",
]
REQUIRED_ARTIFACTS_TEXT = [
    "AI_READONLY_REVIEW.md",
    "AI_PROMPT.md",
    "AI_RESPONSE_RAW.txt",
    "AI_READONLY_SUMMARY.md",
]

# Artifact pointer names -> expected JSON file inside the latest dir
ARTIFACT_POINTERS = {
    "latest_human_approval": ("APPROVAL_PACKET.json", "APPROVAL_SUMMARY.json"),
    "latest_nightly_window": ("NIGHTLY_WINDOW_REPORT.json",),
    "latest_langgraph_v0": ("LANGGRAPH_RUN_MANIFEST.json",),
    "latest_validation": ("VALIDATION_REPORT.json",),
    "latest_review_agents": ("REVIEW_AGENTS_SUMMARY.json",),
    "latest_model_routing": ("MODEL_ROUTING_PLAN.json",),
    "latest_morning_report": ("MORNING_REPORT.json",),
    "latest_runner_v0": ("RUN_MANIFEST.json",),
    "latest_manager_plan": ("MANAGER_DECISION.json",),
}

SAFETY_BOUNDARIES = """\
## Safety Boundaries (AI Agent)

- This agent is READ-ONLY and ADVISORY only.
- It CANNOT approve its own work.
- Deterministic validation remains authoritative.
- No source writes, no OpenHands execution, no push, no merge, no PR creation.
- No shell or tool access is granted to the model.
- No secrets (API keys, tokens) are included in prompts.\
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ------------------------------------------------------------------ #
#  Environment / config helpers                                       #
# ------------------------------------------------------------------ #

def _env_or_none(name: str) -> str | None:
    val = __import__("os").environ.get(name)
    return val if val else None


def resolve_model_config() -> dict[str, str | None]:
    """Return model config with precedence: AGENT_MANAGER_* > fallback env vars."""
    base_url = (
        _env_or_none("AGENT_MANAGER_OPENAI_BASE_URL")
        or _env_or_none("OPENAI_BASE_URL")
        or _env_or_none("LLM_BASE_URL")
        or _env_or_none("MODEL")  # some local servers use this
        or "http://127.0.0.1:1234/v1"
    )
    api_key = (
        _env_or_none("AGENT_MANAGER_OPENAI_API_KEY")
        or _env_or_none("OPENAI_API_KEY")
        or _env_or_none("LLM_API_KEY")
        or None
    )
    model = (
        _env_or_none("AGENT_MANAGER_AI_MODEL")
        or _env_or_none("LLM_MODEL")
        or _env_or_none("MODEL")
        or "gpt-4o-mini"
    )
    return {"base_url": base_url, "api_key": api_key, "model": model}


def extract_host(url: str) -> str:
    """Extract only the scheme+host from a URL, stripping path and secrets."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port
    if port:
        return f"{parsed.scheme}://{host}:{port}"
    return f"{parsed.scheme}://{host}"


# ------------------------------------------------------------------ #
#  Artifact loading                                                   #
# ------------------------------------------------------------------ #

def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json_loads(path.read_text())
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except (FileNotFoundError, OSError):
        return None


def load_artifact_summaries(project_id: str) -> dict[str, Any]:
    """Load concise summaries from latest artifact directories.

    Returns references and short summaries, not full file contents.
    """
    run_root = ROOT / "runs" / project_id
    result: dict[str, Any] = {"_pointer_presence": {}}

    for pointer_name, json_files in ARTIFACT_POINTERS.items():
        pointer = run_root / pointer_name
        if not (pointer.exists() or pointer.is_symlink()):
            result["_pointer_presence"][pointer_name] = "missing"
            continue

        resolved = None
        try:
            resolved = pointer.resolve()
        except OSError:
            pass

        if not resolved or not resolved.is_dir():
            result["_pointer_presence"][pointer_name] = "broken_symlink"
            continue

        result["_pointer_presence"][pointer_name] = "present"
        dir_summaries: dict[str, Any] = {}
        for jf in json_files:
            candidate = resolved / jf
            data = _safe_read_json(candidate)
            if data is not None:
                # Carry only a concise summary
                summary: dict[str, Any] = {}
                for key in ("status", "blocking", "generated_by", "schema_version"):
                    val = data.get(key)
                    if val is not None:
                        summary[key] = val
                dir_summaries[jf] = summary

        result[pointer_name] = dir_summaries

    return result


def build_prompt(artifact_summaries: dict[str, Any], project_id: str, max_input_chars: int) -> tuple[str, list[str]]:
    """Build the AI prompt from artifact summaries.

    Returns (prompt_text, secret_env_names) so caller can verify no secrets leak.
    """
    lines = [
        "# Read-Only AI Agent Review Request",
        "",
        f"**Project**: {project_id}",
        f"**Timestamp**: {utc_now()}",
        "",
        "## Current Objective",
        "",
    ]

    # Carry active objective if present
    active_obj = artifact_summaries.get("latest_runner_v0", {})
    obj_file = active_obj.get("ACTIVE_OBJECTIVE.json")
    if isinstance(obj_file, dict):
        selected = obj_file.get("selected_objective", "unknown")
        lines.append(f"- Selected objective: `{selected}`")
        status_val = obj_file.get("status")
        if status_val:
            lines.append(f"- Objective status: {status_val}")

    lines.extend([
        "",
        "## Latest Validation Status",
        "",
    ])
    val_report = artifact_summaries.get("latest_validation", {})
    val_json = val_report.get("VALIDATION_REPORT.json")
    if isinstance(val_json, dict):
        lines.append(f"- Status: {val_json.get('status', 'unknown')}")
        blocking = val_json.get("blocking")
        if blocking is not None:
            lines.append(f"- Blocking: {str(blocking).lower()}")

    lines.extend([
        "",
        "## Latest Review-Agent Status",
        "",
    ])
    review_summary = artifact_summaries.get("latest_review_agents", {})
    rev_json = review_summary.get("REVIEW_AGENTS_SUMMARY.json")
    if isinstance(rev_json, dict):
        lines.append(f"- Status: {rev_json.get('status', 'unknown')}")
        blocking = rev_json.get("blocking")
        if blocking is not None:
            lines.append(f"- Blocking: {str(blocking).lower()}")

    lines.extend([
        "",
        "## Latest Model-Routing Status",
        "",
    ])
    mr_summary = artifact_summaries.get("latest_model_routing", {})
    mr_json = mr_summary.get("MODEL_ROUTING_PLAN.json")
    if isinstance(mr_json, dict):
        lines.append(f"- Status: {mr_json.get('status', 'unknown')}")

    lines.extend([
        "",
        "## Latest Nightly-Window Status",
        "",
    ])
    nw_summary = artifact_summaries.get("latest_nightly_window", {})
    nw_json = nw_summary.get("NIGHTLY_WINDOW_REPORT.json")
    if isinstance(nw_json, dict):
        lines.append(f"- Status: {nw_json.get('status', 'unknown')}")

    lines.extend([
        "",
        "## Latest Human-Approval Status",
        "",
    ])
    ha_summary = artifact_summaries.get("latest_human_approval", {})
    ha_json = ha_summary.get("APPROVAL_PACKET.json")
    if isinstance(ha_json, dict):
        rec = ha_json.get("recommended_human_decision", "unknown")
        lines.append(f"- Recommended decision: `{rec}`")

    lines.extend([
        "",
        "## Risk Assessment Request",
        "",
        "Based on the above deterministic artifacts, provide:",
        "",
        "1. A concise summary of the current state.",
        "2. Identified risks (if any).",
        "3. A recommendation: **accept**, **revise**, **discard**, or **hold**.",
        "",
        "**Important**: This AI agent CANNOT approve its own work.",
        "Deterministic validation remains authoritative.",
        "",
        SAFETY_BOUNDARIES,
    ])

    prompt_text = "\n".join(lines)

    # Truncate if needed (leave room for safety boundaries which are always at end)
    safety_len = len(SAFETY_BOUNDARIES) + 50
    if max_input_chars > safety_len and len(prompt_text) > max_input_chars:
        prompt_text = prompt_text[: max_input_chars - 20] + "\n\n[... truncated ...]\n" + SAFETY_BOUNDARIES

    # Secret env var names for test verification
    secret_names = [
        "AGENT_MANAGER_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "AGENT_MANAGER_OPENAI_BASE_URL",
        "OPENAI_BASE_URL",
        "LLM_BASE_URL",
    ]

    return prompt_text, secret_names


# ------------------------------------------------------------------ #
#  Model call (standard-library HTTP only)                            #
# ------------------------------------------------------------------ #

def _ssl_context_for_url(base_url: str) -> ssl.SSLContext | None:
    if base_url.startswith("https://"):
        ctx = ssl.create_default_context()
        return ctx
    return None


def call_model(
    base_url: str,
    api_key: str | None,
    model_name: str,
    prompt_text: str,
    timeout_seconds: int,
) -> tuple[str, dict[str, Any]]:
    """Call an OpenAI-compatible Chat Completions endpoint.

    Returns (raw_response_text, safety_record).
    Uses only standard-library HTTP. Never writes API keys to artifacts.
    """
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https://" else 80)
    path = parsed.path.rstrip("/") + "/chat/completions"
    is_https = parsed.scheme == "https://"

    body = json_dumps({
        "model": model_name,
        "messages": [
            {"role": "system", "content": SAFETY_BOUNDARIES},
            {"role": "user", "content": prompt_text},
        ],
        "temperature": 0.0,
    })

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    safety_record = {
        "model_call_performed": True,
        "dry_run": False,
        "model_name": model_name,
        "base_url_host_only": extract_host(base_url),
        "timeout_seconds": timeout_seconds,
        "prompt_size_chars": len(prompt_text),
    }

    conn: ssl.SSLContext | http.client.HTTPConnection | http.client.HTTPSConnection
    if is_https:
        ctx = _ssl_context_for_url(base_url)
        conn = http.client.HTTPSConnection(host, port, context=ctx, timeout=timeout_seconds)  # type: ignore[assignment]
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout_seconds)

    raw_response = ""
    try:
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        raw_body = resp.read().decode("utf-8", errors="replace")
        safety_record["response_size_chars"] = len(raw_body)
        safety_record["http_status"] = resp.status
        raw_response = raw_body
    except (socket.timeout, OSError, ssl.SSLError, http.client.HTTPException) as exc:
        safety_record["error"] = str(exc)
        safety_record["response_size_chars"] = 0
        raw_response = f"{{\"_error\": \"{str(exc)}\"}}"
    finally:
        try:
            conn.close()
        except OSError:
            pass

    return raw_response, safety_record


# ------------------------------------------------------------------ #
#  Dry-run placeholder                                                #
# ------------------------------------------------------------------ #

def dry_run_placeholder(project_id: str) -> tuple[str, dict[str, Any]]:
    """Return deterministic placeholder for dry-run mode."""
    raw = (
        "[DRY-RUN MODE — no model was called]\n\n"
        "This is a deterministic placeholder.\n"
        "To enable live model calls, provide both:\n"
        "  --allow-model-call CLI flag AND AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 env var.\n"
    )
    safety = {
        "model_call_performed": False,
        "dry_run": True,
        "model_name": None,
        "base_url_host_only": None,
        "timeout_seconds": 60,
        "prompt_size_chars": 0,
        "response_size_chars": len(raw),
    }
    return raw, safety


# ------------------------------------------------------------------ #
#  JSON parsing of model response                                     #
# ------------------------------------------------------------------ #

def parse_model_response(raw: str) -> dict[str, Any]:
    """Parse model response as JSON. If it fails, return a warn-status parsed report."""
    stripped = raw.strip()
    # Try to find JSON in the response (some models wrap in markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", stripped, re.DOTALL)
    if json_match:
        candidate = json_match.group(1).strip()
    else:
        candidate = stripped

    try:
        data = json_loads(candidate)
        if isinstance(data, dict):
            return {
                "status": "pass",
                "parse_method": "json_extracted",
                **data,
            }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: warn status with raw content reference
    return {
        "status": "warn",
        "parse_method": "raw_fallback",
        "raw_response_truncated": stripped[:500] if len(stripped) > 500 else stripped,
        "note": "Could not parse model response as JSON. Raw content preserved in AI_RESPONSE_RAW.txt.",
    }


# ------------------------------------------------------------------ #
#  Artifact writers                                                   #
# ------------------------------------------------------------------ #

def write_json_artifact(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(data, indent=2, sort_keys=True) + "\n")


def write_text_artifact(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ------------------------------------------------------------------ #
#  Main generate function                                             #
# ------------------------------------------------------------------ #

def generate(
    project_id: str,
    created_utc: str | None = None,
    allow_model_call: bool = False,
    env_allow_key: str | None = None,
    timeout_seconds: int = 60,
    max_input_chars: int = 12000,
    model_name: str | None = None,
    base_url_override: str | None = None,
) -> dict[str, Any]:
    """Run the AI read-only agent and write all artifacts.

    Returns the summary dict for printing.
    """
    load_project(project_id)  # validate project exists first
    created = created_utc or utc_now()
    run_dir = ROOT / "runs" / project_id / f"ai_readonly_{created}"

    # Load artifact summaries
    artifact_summaries = load_artifact_summaries(project_id)

    # Build prompt (no secrets included)
    prompt_text, secret_env_names = build_prompt(artifact_summaries, project_id, max_input_chars)
    write_text_artifact(run_dir / "AI_PROMPT.md", prompt_text)

    # Determine if we actually call the model
    env_flag = env_allow_key or _env_or_none("AGENT_MANAGER_AI_ENABLE_MODEL_CALLS")
    will_call_model = allow_model_call and (env_flag == "1")

    if will_call_model:
        config = resolve_model_config()
        actual_base_url = base_url_override or config["base_url"]
        actual_api_key = config["api_key"]  # may be None
        actual_model = model_name or config["model"]

        raw_response, safety_status = call_model(
            base_url=actual_base_url,
            api_key=actual_api_key,
            model_name=actual_model,
            prompt_text=prompt_text,
            timeout_seconds=timeout_seconds,
        )
    else:
        raw_response, safety_status = dry_run_placeholder(project_id)

    write_text_artifact(run_dir / "AI_RESPONSE_RAW.txt", raw_response)

    # Parse response JSON (warn if can't parse — not fail)
    parsed_response = parse_model_response(raw_response)
    write_json_artifact(run_dir / "AI_RESPONSE_PARSED.json", parsed_response)

    # Safety status: always deny dangerous operations
    safety_status["source_writes_allowed"] = False
    safety_status["openhands_execution_allowed"] = False
    safety_status["auto_push_allowed"] = False
    safety_status["auto_merge_allowed"] = False
    safety_status["pr_creation_allowed"] = False
    write_json_artifact(run_dir / "AI_SAFETY_STATUS.json", safety_status)

    # AI review report (advisory, read_only_manager_reviewer role)
    ai_review = _build_ai_review(artifact_summaries, project_id, created, will_call_model, run_dir)
    write_json_artifact(run_dir / "AI_READONLY_REVIEW.json", ai_review)
    write_text_artifact(run_dir / "AI_READONLY_REVIEW.md", _build_markdown_report(ai_review))

    # AI summary
    ai_summary = _build_ai_summary(project_id, created, run_dir, will_call_model, safety_status)
    write_json_artifact(run_dir / "AI_READONLY_SUMMARY.json", ai_summary)
    write_text_artifact(run_dir / "AI_READONLY_SUMMARY.md", _build_summary_markdown(ai_summary))

    # Update symlink
    update_latest_symlink(run_dir, project_id)

    return ai_summary


def _build_ai_review(artifact_summaries: dict[str, Any], project_id: str, created_utc: str, model_called: bool, run_dir: Path) -> dict[str, Any]:
    """Build the AI review report (advisory role)."""
    # Gather status info from artifacts
    val_status = "unknown"
    rev_status = "unknown"
    mr_status = "unknown"
    nw_status = "unknown"
    ha_recommended = "unknown"

    val_json = artifact_summaries.get("latest_validation", {}).get("VALIDATION_REPORT.json")
    if isinstance(val_json, dict):
        val_status = val_json.get("status", "unknown")

    rev_json = artifact_summaries.get("latest_review_agents", {}).get("REVIEW_AGENTS_SUMMARY.json")
    if isinstance(rev_json, dict):
        rev_status = rev_json.get("status", "unknown")

    mr_json = artifact_summaries.get("latest_model_routing", {}).get("MODEL_ROUTING_PLAN.json")
    if isinstance(mr_json, dict):
        mr_status = mr_json.get("status", "unknown")

    nw_json = artifact_summaries.get("latest_nightly_window", {}).get("NIGHTLY_WINDOW_REPORT.json")
    if isinstance(nw_json, dict):
        nw_status = nw_json.get("status", "unknown")

    ha_json = artifact_summaries.get("latest_human_approval", {}).get("APPROVAL_PACKET.json")
    if isinstance(ha_json, dict):
        ha_recommended = ha_json.get("recommended_human_decision", "unknown")

    # Determine recommendation based on statuses
    recommendation = "hold"
    if val_status == "pass" and rev_status in ("pass", "warn"):
        recommendation = "accept"
    elif val_status != "pass":
        recommendation = "revise"
    else:
        recommendation = "hold"

    findings = [
        {
            "id": "deterministic_validation_authority",
            "severity": "info",
            "source": "AI_READONLY_REVIEW.json",
            "message": "Deterministic validation remains authoritative. AI advisory does not override it.",
        },
        {
            "id": "ai_no_self_approval",
            "severity": "high",
            "source": "AI_READONLY_REVIEW.json",
            "message": "This AI agent cannot approve its own work.",
        },
    ]

    if val_status != "pass":
        findings.append({
            "id": "validation_not_passing",
            "severity": "high",
            "source": "latest_validation/VALIDATION_REPORT.json",
            "message": f"Deterministic validation status is {val_status!r}, not 'pass'.",
        })

    if rev_status == "fail":
        findings.append({
            "id": "review_agents_fail",
            "severity": "high",
            "source": "latest_review_agents/REVIEW_AGENTS_SUMMARY.json",
            "message": f"Review agents summary status is 'fail'.",
        })

    return {
        "schema_version": 1,
        "agent": "read_only_manager_reviewer",
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "role": "advisory_readonly",
        "recommendation": recommendation,
        "model_call_performed": model_called,
        "findings": findings,
        "generated_by": GENERATED_BY,
    }


def _build_ai_summary(
    project_id: str,
    created_utc: str,
    run_dir: Path,
    model_called: bool,
    safety_status: dict[str, Any],
) -> dict[str, Any]:
    """Build the AI summary report."""
    return {
        "schema_version": 1,
        "agent": "ai_readonly_agent",
        "project_id": project_id,
        "created_utc": created_utc,
        "run_dir": str(run_dir),
        "model_call_performed": model_called,
        "safety_status": safety_status,
        "artifacts_generated": [
            "AI_READONLY_REVIEW.json",
            "AI_READONLY_REVIEW.md",
            "AI_PROMPT.md",
            "AI_RESPONSE_RAW.txt",
            "AI_RESPONSE_PARSED.json",
            "AI_SAFETY_STATUS.json",
            "AI_READONLY_SUMMARY.json",
            "AI_READONLY_SUMMARY.md",
        ],
        "generated_by": GENERATED_BY,
    }


def _build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AI Read-Only Review",
        "",
        f"**Agent**: {report['agent']}",
        f"**Project**: {report['project_id']}",
        f"**Created UTC**: {report['created_utc']}",
        f"**Recommendation**: {report.get('recommendation', 'N/A')}",
        f"**Model Call Performed**: {str(report.get('model_call_performed', False)).lower()}",
        "",
        "## Findings",
        "",
    ]
    for item in report.get("findings", []):
        lines.append(f"- **{item['severity'].upper()}** `{item['id']}`: {item['message']}")
        lines.append(f"  - Source: {item['source']}")
    lines.extend(["", "## Safety", "", "- Advisory only. No source writes, no OpenHands execution.", "- Deterministic validation remains authoritative."])
    lines.append("")
    return "\n".join(lines)


def _build_summary_markdown(summary: dict[str, Any]) -> str:
    safety = summary.get("safety_status", {})
    lines = [
        "# AI Read-Only Summary",
        "",
        f"**Project**: {summary['project_id']}",
        f"**Created UTC**: {summary['created_utc']}",
        f"**Model Call Performed**: {str(summary.get('model_call_performed', False)).lower()}",
        "",
        "## Safety Status",
        "",
    ]
    for key in ("source_writes_allowed", "openhands_execution_allowed", "auto_push_allowed", "auto_merge_allowed", "pr_creation_allowed"):
        val = safety.get(key, "unknown")
        lines.append(f"- {key}: {str(val).lower()}")

    lines.extend(["", "## Artifacts Generated", ""])
    for artifact in summary.get("artifacts_generated", []):
        lines.append(f"- {artifact}")
    lines.append("")
    return "\n".join(lines)


def update_latest_symlink(run_dir: Path, project_id: str) -> None:
    latest = ROOT / "runs" / project_id / "latest_ai_readonly"
    if latest.exists() or latest.is_symlink():
        try:
            latest.unlink()
        except OSError:
            pass
    latest.symlink_to(run_dir, target_is_directory=True)


def load_project(project_id: str) -> dict[str, Any]:
    config_path = ROOT / "configs" / "projects.json"
    data = json_loads(config_path.read_text())
    projects = data.get("projects")
    if not isinstance(projects, dict) or not isinstance(projects.get(project_id), dict):
        raise SystemExit(f"unknown project id: {project_id}")
    return projects[project_id]


# ------------------------------------------------------------------ #
#  CLI entry point                                                    #
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 18A: Model-backed read-only AI agent (advisory only).",
    )
    parser.add_argument("project_id", help="Project identifier from configs/projects.json")
    parser.add_argument("--allow-model-call", action="store_true", default=False,
                        help="Allow live model call (requires AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 env var)")
    parser.add_argument("--timeout-seconds", type=int, default=60,
                        help="Timeout for model HTTP call in seconds")
    parser.add_argument("--max-input-chars", type=int, default=12000,
                        help="Maximum characters for the prompt input")
    parser.add_argument("--model", default=None,
                        help="Override model name (falls back to AGENT_MANAGER_AI_MODEL / LLM_MODEL / MODEL)")
    parser.add_argument("--base-url", default=None,
                        help="Override base URL (falls back to AGENT_MANAGER_OPENAI_BASE_URL / OPENAI_BASE_URL / LLM_BASE_URL)")
    args = parser.parse_args()

    summary = generate(
        project_id=args.project_id,
        allow_model_call=args.allow_model_call,
        timeout_seconds=args.timeout_seconds,
        max_input_chars=args.max_input_chars,
        model_name=args.model,
        base_url_override=args.base_url,
    )

    print(f"AI read-only agent complete for {args.project_id}")
    print(f"Run dir: {summary['run_dir']}")
    print(f"Model call performed: {str(summary['model_call_performed']).lower()}")


if __name__ == "__main__":
    main()
