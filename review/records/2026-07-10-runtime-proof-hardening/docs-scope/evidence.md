# Primary Driver Documentation Evidence

## E-001 - Claude-facing contract parity

- Maturity: finding
- Action: Cross-check CLAUDE, workflow, primary skills, and Agent/run templates against implemented turn, receipt, fan-out, pause, review, and output gates.
- Result: Manual review, model-budget excuses, heartbeat proof, ambiguous resume, thin Coda, pause-as-defer, and free-form post-denial result advice are removed. Guidance is consistent with the separately reviewed current-turn receipt, post-return disposition, and execution-action retry controls; documentation is not runtime proof.
- Control: The current full-suite log covers rule/template checks and implemented runtime selftests; a hashed inventory scans Claude-facing Markdown for known historical shortcut language.
- Replicated: yes
- Artifacts: `root_rules.diff`, `workflow_core.diff`, `workflow_reference.diff`, `primary_skills.diff`, `agent_role_templates.diff`, `lifecycle_templates.diff`, `peer_review.diff`, `selftest_all.log`, `historical_failures.md`, `stale_reference_audit.json`, `installed-runtime-manifest.json`
- Certainty: 0.8
