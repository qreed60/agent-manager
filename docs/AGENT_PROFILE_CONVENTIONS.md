# Agent Profile Conventions

Agent profiles are central, reusable, and runner-specific.

Current runner:
- OpenHands

Profile layout:

profiles/openhands/<profile>/
  profile.json
  system_prompt.j2
  security_policy.j2
  settings.template.json

Rules:
- The coder profile is the only write-capable profile.
- All review profiles are read-only.
- Manager profile writes only agent-manager artifacts.
- No profile is executed in Phase 3.
- Profile switching is implemented in Phase 4.
