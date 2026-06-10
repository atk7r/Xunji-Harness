---
name: src-safety-boundary
description: Boundary-only skill for authorized SRC and vulnerability research sessions. Load at the start of security testing work. This skill contains limits only: no methodology, no attack ideas, no payload guidance, and no playbooks.
---

# SRC Safety Boundary

This skill is a boundary, not a playbook.

The AI chooses its own reasoning, tooling, and verification path. This file
only declares what must not happen and when to stop for user confirmation.

## Hard Limits

`.claude/hooks/safety_gate.py` deterministically blocks Bash commands that match
deny rules in `.claude/hooks/safety_rules.json`.

Blocked classes include:

- destructive host or filesystem operations
- permission, ownership, role, ACL, or privilege changes
- target resource deletion
- money movement, payment, refund, withdrawal, recharge, payout, or settlement
- online brute force
- denial of service, flooding, high-rate scanning, or load intended to degrade
  availability

Do not bypass the hook through obfuscation, alternate binaries, encoding,
splitting commands, or indirect execution.

## Human Approval

Human approval cannot unlock a destructive action class.

If a verification idea touches a boundary, stop and ask for an equivalent safe
alternative. Proceed only with the safe alternative after explicit confirmation.

## Scope

The hook does not enforce target scope. The operator must only test authorized
targets. If authorization or scope is unclear, stop and ask.

## Harmless Verification (无害化原则)

Prove only that the vulnerability exists, then stop. Assess impact against the
three factors — confidentiality, availability, integrity — and never expand
impact past the proof.

### Confidentiality (机密性)

- Unauthorized access or privilege escalation: once the unauthorized / 越权
  logic is demonstrated, do not then retrieve or retain user information or
  system file information.
- Reachable database query (e.g. SQL injection): proving the DB instance and
  library/table names is enough. Do not query detailed personal-information or
  business data. No dumping / 拖库.
- Host or device high privilege: proving current-user environment information is
  enough. Do not fetch other users' data or business data.
- Never use the gained host or device as a pivot to scan or test the internal
  network.

### Availability (可用性)

- Assume limited safety redundancy. Do not run large-traffic or large-scale
  scans that could crash the network, host, or device.
- Do not execute any test case that causes local or remote denial of service.
- Do not execute any test case that could disturb overall business logic or
  cause users financial / property loss.

### Integrity (完整性)

- Backend / admin function access: proving the current role attribute is enough.
  Do not use the functions to edit, add, delete, or tamper.
- Host / device / database high privilege: proving environment information is
  enough. Do not edit, add, delete, or tamper files, programs, or data.
- Upload that parses or executes: proving the parse-and-execute logic is enough.
  Do not leave any control-purpose program or code (no webshell / backdoor
  residue).

## Platform & Legal Rules

These bind every authorized SRC / EDUSRC run, in addition to the limits above:

- Do not upload webshells, trojans, viruses, or any malicious program.
- Do not use any vulnerability to obtain system data. Prove existence only.
- No test action may affect the target's normal business operation.
- Do not privately retain vulnerability information or vendor / company data,
  and do not disclose vulnerability content to unrelated people.
- If a test genuinely requires modifying / adding / deleting target data, stop
  and obtain explicit platform authorization first.
- If access or privilege is gained and deeper work seems warranted, stop and ask
  the platform first. Do not scan, pivot, or set up a proxy from that access.
- Payment-related vulnerabilities: describe the result and the test account in
  the report. Never profit from the vulnerability.
- After testing, remove all residue — webshells, uploaded files, created
  permissions, backdoors, scheduled jobs. Leave nothing reusable or guessable.
- Submit only accurate, verified findings. Do not submit false reports.
- Operate within PRC law. The platform and vendor reserve the right to pursue
  legal liability.

## Evidence

Reports must cite evidence. Signals are not conclusions. Model confidence is not
evidence. Single observations and environment-provided artifacts are not enough
to confirm a finding.

Use the run workflow in `docs/WORKFLOW.md` to maintain the evidence ledger and
false-positive checks.
