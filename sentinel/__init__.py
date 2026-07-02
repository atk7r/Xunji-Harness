"""sentinel — runtime behavior monitor for the autonomous red-team driver.

Phase 1: OBSERVE-ONLY. Fed by Claude Code hooks (UserPromptSubmit / PreToolUse /
PostToolUse / SessionStart), it reconstructs the agent's action trace and runs
deterministic behavioral detectors keyed off the run ledger (target.md scope,
frontier/decisions/hints). It NEVER blocks in Phase 1 — it only records behavioral
alerts to runs/<target>/alerts.md with a risk score, so the operator can judge
detector precision before any inline enforcement is turned on.

This is a DETECTION layer, not a boundary. It complements (does not replace) the
static effect backstop (.claude/hooks/safety_gate.py) and OS-level isolation.

Design: docs discussion 2026-06-13. Grounding: AgentArmor (trace-as-program),
CaMeL (control/data-flow provenance), ProbGuard (risk-threshold monitoring),
TraceAegis (behavioral anomaly). Keyword-heuristic attribution in Phase 1;
rigorous data-flow taint is Phase 2.
"""
