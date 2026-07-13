# Review Scope

Codex authored a narrow maintenance change to remove duplicated Setup box banners.

Review questions:

1. Are both setup_run.py banner prints removed, including start and end?
2. Are Setup phase_start/phase_end journal events preserved?
3. Does the selftest prevent accidental reintroduction of the banner helper and verify a closed Setup journal cycle?
4. Do Claude-primary instructions and canonical Router/Workflow docs clearly describe the setup-only display exception without weakening visible markers for Root Orchestrator, Hunter, Reviewer, or Report?
5. Does the change avoid touching run evidence or target-facing behavior?

This is repository maintenance only. Do not evaluate live target evidence.
