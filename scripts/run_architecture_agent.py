#!/usr/bin/env python3
"""Phase 22 - AI Architecture Agent (proposal layer only).

Reads a Phase 21 FEATURE_BRIEF.json and generates a deterministic mock
architecture proposal in --mock mode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_BY = "phase22_ai_architecture_agent"
ARCHITECTURE_PROPOSAL_SCHEMA = ROOT / "schemas" / "architecture_proposal.schema.json"

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + chr(10))


def model_call_allowed(allow_flag: bool) -> bool:
    env_val = os.environ.get("AGENT_MANAGER_AI_ENABLE_MODEL_CALLS", "0").strip() == "1"
    return allow_flag and env_val


def load_project_config(project_id, recorder):
    config_path = ROOT / "configs" / "projects.json"
    data = load_json(config_path)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        recorder.append(("project_config_shape", False))
        return None
    project = projects.get(project_id)
    if not isinstance(project, dict):
        recorder.append(("unknown_project_id", False))
        return None
    recorder.append(("valid_project_id", True))
    return project


def find_feature_brief(project_id, feature_id):
    candidate_dir = ROOT / "runs" / project_id / "feature_briefs" / feature_id
    if not candidate_dir.is_dir():
        return None, None
    brief_path = candidate_dir / "FEATURE_BRIEF.json"
    if not brief_path.exists():
        return None, None
    try:
        data = load_json(brief_path)
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    if data.get("generated_by", "") != "phase21_feature_brief_intake":
        return None, None
    return data, brief_path


def validate_against_schema(data, schema_path):
    errors = []
    try:
        schema = load_json(schema_path)
    except (FileNotFoundError, json.JSONDecodeError):
        return True, errors
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"missing required field: {field}")
    properties = schema.get("properties", {})
    for key, prop_schema in properties.items():
        if key not in data:
            continue
        value = data[key]
        enum_vals = prop_schema.get("enum")
        if enum_vals is not None and value not in enum_vals:
            errors.append(f"field {key!r} must be one of {enum_vals}; got {value!r}")
    th = prop_schema.get("type")
    if th == "integer" and not isinstance(data[key], int):
        errors.append(f"field {key!r} must be integer; got {type(data[key]).__name__}")
    if th == "string":
        ml = prop_schema.get("minLength")
        xl = prop_schema.get("maxLength")
        pat = prop_schema.get("pattern")
        vs = str(data[key])
        if ml is not None and len(vs) < ml:
            errors.append(f"field {key!r} length must be >= {ml}")
        if xl is not None and len(vs) > xl:
            errors.append(f"field {key!r} length must be <= {xl}")
        if pat is not None and not re.search(pat, vs):
            errors.append(f"field {key!r} does not match pattern {pat!r}")
    return len(errors) == 0, errors


def generate_mock_proposal(project_id, feature_id, brief_data, source_brief_path):
    created_utc = utc_now()
    title = brief_data.get('title', 'Untitled Feature')
    goal = brief_data.get('high_level_goal', '')
    behavior = brief_data.get('desired_behavior', '')
    must_haves = brief_data.get('must_have_requirements', [])
    if goal and behavior:
        problem_summary = f"Implement '{title}'. Goal: {goal}. Expected behavior: {behavior}."
    else:
        problem_summary = f"Address requirements for feature '{title}'."
    recommended_design = (f'Modular design with clear separation of concerns. '
        f'Entry point accepts {project_id} project context and {feature_id} feature scope, '
        f'delegates to focused modules per must-have requirement.')
    alternative_designs = [
        'Monolithic approach: single-module implementation for simplicity.',
        'Service-oriented design: separate processes for each major capability.',
    ]
    files_likely_involved = ['scripts/run_architecture_agent.py',
                             'schemas/architecture_proposal.schema.json']
    if must_haves:
        files_likely_involved.append(f'src/{feature_id}/core.py')
        files_likely_involved.append(f'tests/test_{feature_id}.py')
    interfaces_and_contracts = [
        'Architecture proposal JSON schema (schemas/architecture_proposal.schema.json)',
        'Feature brief intake contract (Phase 21)',
    ]
    data_artifacts = [
        f'runs/{project_id}/architecture_proposals/{feature_id}/ARCHITECTURE_PROPOSAL.json',
        f'runs/{project_id}/architecture_proposals/{feature_id}/ARCHITECTURE_PROPOSAL.md',
        f'runs/{project_id}/architecture_proposals/{feature_id}/ARCHITECTURE_AGENT_PROMPT.md',
    ]
    safety_risks = [
        'Model call must remain disabled unless both --allow-model-call and AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1 are set.',
        'Source writes to target project repos must be blocked in mock mode.',
        'OpenHands execution must not be triggered.',
    ]
    test_strategy = ('Unit tests for proposal generation, schema validation, error handling '
        f'for missing feature briefs and invalid project IDs. Integration smoke test with --mock flag.')
    implementation_sequence = [
        '1. Validate project_id against configs/projects.json',
        '2. Locate FEATURE_BRIEF.json for the given feature_id',
        '3. Generate deterministic mock architecture proposal',
        '4. Write ARCHITECTURE_PROPOSAL.json and ARCHITECTURE_PROPOSAL.md',
        '5. Write ARCHITECTURE_AGENT_PROMPT.md',
        '6. Run schema validation on generated JSON',
    ]
    assumptions = [
        f'Feature brief at runs/{project_id}/feature_briefs/{feature_id}/FEATURE_BRIEF.json is valid and complete.',
        'The project config in configs/projects.json contains the target project.',
        'No live model calls are needed for mock mode.',
    ]
    constraints = ['No OpenHands execution', 'No source writes to target repos',
                   'Model calls disabled by default', 'Deterministic output in --mock mode']
    out_of_scope = ['Manager objective planning', 'OpenHands request drafting',
                    'Coder task execution', 'Live model inference']
    questions_for_human = [
        'Is the recommended design appropriate for this feature?',
        'Are there additional constraints or requirements not captured in the feature brief?',
        'Should any must-have requirement be re-prioritized?',
    ]
    return {
        'schema_version': 1, 'generated_by': GENERATED_BY, 'created_utc': created_utc,
        'project_id': project_id, 'feature_id': feature_id,
        'source_feature_brief_path': str(source_brief_path), 'title': title,
        'architecture_status': 'proposal_ready', 'problem_summary': problem_summary,
        'recommended_design': recommended_design, 'alternative_designs': alternative_designs,
        'files_likely_involved': files_likely_involved,
        'interfaces_and_contracts': interfaces_and_contracts, 'data_artifacts': data_artifacts,
        'safety_risks': safety_risks, 'test_strategy': test_strategy,
        'implementation_sequence': implementation_sequence, 'assumptions': assumptions,
        'constraints': constraints, 'out_of_scope': out_of_scope,
        'questions_for_human': questions_for_human,
        'model_call_allowed': False, 'model_called': False,
        'source_writes_performed': False, 'openhands_executed': False,
    }


def build_markdown_proposal(proposal):
    lines = [f"# Architecture Proposal: {proposal['title']}", '',
             f"- **Feature ID**: {proposal['feature_id']}",
             f"- **Project**: {proposal['project_id']}",
             f"- **Status**: {proposal['architecture_status']}",
             f"- **Created UTC**: {proposal['created_utc']}",
             f"- **Generated By**: {proposal['generated_by']}", '']
    for section, key in [('Problem Summary', 'problem_summary'), ('Recommended Design', 'recommended_design')]:
        val = proposal.get(key)
        if val:
            lines.extend([f'## {section}', '', val, ''])
    alt = proposal.get('alternative_designs')
    if alt:
        lines.append('## Alternative Designs' + chr(10))
        for i, a in enumerate(alt, 1):
            lines.append(f'{i}. {a}')
        lines.append('')
    files = proposal.get('files_likely_involved')
    if files:
        lines.extend(['## Files Likely Involved', ''])
        for f_item in files:
            lines.append(f'- `{f_item}`')
        lines.append('')
    interfaces = proposal.get('interfaces_and_contracts')
    if interfaces:
        lines.extend(['## Interfaces and Contracts', ''])
        for iface in interfaces:
            lines.append(f'- {iface}')
        lines.append('')
    artifacts = proposal.get('data_artifacts')
    if artifacts:
        lines.extend(['## Data Artifacts', ''])
        for art in artifacts:
            lines.append(f'- {art}')
        lines.append('')
    risks = proposal.get('safety_risks')
    if risks:
        lines.extend(['## Safety Risks', ''])
        for risk in risks:
            lines.append(f'- {risk}')
        lines.append('')
    ts = proposal.get('test_strategy')
    if ts:
        lines.extend(['## Test Strategy', '', ts, ''])
    seq = proposal.get('implementation_sequence')
    if seq:
        lines.extend(['## Implementation Sequence', ''])
        for step in seq:
            lines.append(f'- {step}')
        lines.append('')
    for section, key in [('Assumptions', 'assumptions'), ('Constraints', 'constraints')]:
        vals = proposal.get(key)
        if vals:
            lines.extend([f'## {section}', ''])
            for v in vals:
                lines.append(f'- {v}')
            lines.append('')
    oos = proposal.get('out_of_scope')
    if oos:
        lines.extend(['## Out of Scope', ''])
        for item in oos:
            lines.append(f'- {item}')
        lines.append('')
    questions = proposal.get('questions_for_human')
    if questions:
        lines.extend(['## Questions for Human Review', ''])
        for q in questions:
            lines.append(f'- {q}')
        lines.append('')
    lines.extend([
        '## Safety Summary', '',
        f"- Model call allowed: {proposal.get('model_call_allowed', False)}",
        f"- Model called: {proposal.get('model_called', False)}",
        f"- Source writes performed: {proposal.get('source_writes_performed', False)}",
        f"- OpenHands executed: {proposal.get('openhands_executed', False)}",
        '', '---', ''])
    return chr(10).join(lines)


def build_agent_prompt(proposal, brief_data):
    lines = ['# Architecture Agent Prompt', '',
             'This prompt was generated by the Phase 22 AI Architecture Agent.', '',
             '## Source Feature Brief', '',
             f"- **Project**: {brief_data.get('project_id', '')}",
             f"- **Feature ID**: {brief_data.get('feature_id', '')}",
             f"- **Title**: {brief_data.get('title', '')}",
             f"- **Goal**: {brief_data.get('high_level_goal', '')}",
             '', '## Architecture Proposal Summary', '',
             f"- **Status**: {proposal['architecture_status']}",
             f"- **Recommended Design**: {proposal.get('recommended_design', 'N/A')}",
             '', '## Safety Flags', '',
             f"- Model call allowed: {proposal.get('model_call_allowed', False)}",
             f"- Model called: {proposal.get('model_called', False)}",
             f"- Source writes performed: {proposal.get('source_writes_performed', False)}",
             f"- OpenHands executed: {proposal.get('openhands_executed', False)}",
             '', '## Questions for Human Review', '']
    questions = proposal.get('questions_for_human', [])
    if questions:
        for q in questions:
            lines.append(f'- {q}')
    else:
        lines.append('- No questions raised.')
    lines.extend(['', '---', ''])
    return chr(10).join(lines)


def run_architecture_agent(project_id, feature_id, allow_model_call=False):
    recorder = []
    project = load_project_config(project_id, recorder)
    if project is None:
        bad = [msg for msg, ok in recorder if not ok]
        raise SystemExit(f'Architecture agent rejected: {bad}')
    brief_data, brief_path = find_feature_brief(project_id, feature_id)
    if brief_data is None or brief_path is None:
        raise SystemExit(
            f"Architecture agent rejected: no valid Phase 21 FEATURE_BRIEF.json "
            f'found for project={project_id!r}, feature_id={feature_id!r}')
    allowed = model_call_allowed(allow_model_call)
    mock_mode = not allowed
    proposal = generate_mock_proposal(project_id, feature_id, brief_data, brief_path)
    if mock_mode:
        proposal['model_call_allowed'] = False
        proposal['model_called'] = False
        proposal['source_writes_performed'] = False
        proposal['openhands_executed'] = False
    else:
        proposal['model_call_allowed'] = True
    schema_ok, schema_errors = validate_against_schema(proposal, ARCHITECTURE_PROPOSAL_SCHEMA)
    if not schema_ok:
        raise SystemExit(f'Architecture proposal rejected by schema validation: {schema_errors}')
    out_dir = ROOT / 'runs' / project_id / 'architecture_proposals' / feature_id
    write_json(out_dir / 'ARCHITECTURE_PROPOSAL.json', proposal)
    (out_dir / 'ARCHITECTURE_PROPOSAL.md').write_text(build_markdown_proposal(proposal))
    (out_dir / 'ARCHITECTURE_AGENT_PROMPT.md').write_text(build_agent_prompt(proposal, brief_data))
    return proposal


def main():
    parser = argparse.ArgumentParser(description='Phase 22 - AI Architecture Agent (proposal layer).')
    parser.add_argument('project_id', help='Registered project identifier from configs/projects.json.')
    parser.add_argument('--feature-id', required=True, help='Feature ID matching a Phase 21 FEATURE_BRIEF.json.')
    parser.add_argument('--mock', action='store_true', default=False,
                        help='Generate a deterministic mock architecture proposal (default: safe mode).')
    parser.add_argument('--allow-model-call', action='store_true', default=False,
                        help='Allow live model calls. Requires both this flag and AGENT_MANAGER_AI_ENABLE_MODEL_CALLS=1.')
    args = parser.parse_args()
    allow_model_call = False if args.mock else args.allow_model_call
    try:
        proposal = run_architecture_agent(project_id=args.project_id, feature_id=args.feature_id,
                                          allow_model_call=allow_model_call)
    except SystemExit as exc:
        print(f'Error: {exc}', file=sys.stderr)
        raise
    out_dir = ROOT / 'runs' / args.project_id / 'architecture_proposals' / args.feature_id
    print(f"Architecture proposal generated for project '{args.project_id}'")
    print(f"  Feature ID          : {proposal['feature_id']}")
    print(f"  Title               : {proposal['title']}")
    print(f"  Architecture Status : {proposal['architecture_status']}")
    print(f"  Model Call Allowed  : {proposal['model_call_allowed']}")
    print(f"  Model Called        : {proposal['model_called']}")
    print(f"  Source Writes       : {proposal['source_writes_performed']}")
    print(f"  OpenHands Executed  : {proposal['openhands_executed']}")
    print(f'  Proposal dir        : {out_dir}')


if __name__ == "__main__":
    main()
