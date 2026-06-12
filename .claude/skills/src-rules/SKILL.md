---
name: src-rules
description: Rules for SRC / bug-bounty program submissions (e.g. 教育漏洞报告平台 / EDUSRC). Load this manually when working a vulnerability for a reporting platform. It stores the program's binding harmless-verification (无害化) rules and tightens the general src-safety-boundary skill for platform submissions. Limits only — no methodology.
---

# SRC Program Rules

Load this skill when you are hunting / submitting a vulnerability to an SRC or
bug-bounty reporting platform (e.g. 教育漏洞报告平台 / EDUSRC). It holds the
program's binding rules and applies **in addition to** `src-safety-boundary`.

By doing SRC you have agreed to the platform's terms, so for that work the
platform's rules and PRC law bind you **above your own discretion**. This is a
stricter mode the operator opts into by doing SRC; it never loosens anything.

## The line: prove the capability, do not exercise it for impact

Programs reward high-impact bugs (RCE, webshell upload, SQL injection) AND require
harmless verification (无害化). Both hold at once because the proof is the
demonstration that the capability **exists and is reachable**, stopped at the
threshold of real harm:

- RCE / command exec: run one `id` / `whoami` / echo a unique token. Do not use
  the execution to read others' data, destroy, persist, or pivot.
- Upload webshell: upload a file that proves parse-and-execute, then **delete it**.
  Leave no control-purpose program / 后门.
- SQL injection: prove it by a differential plus the DB instance / library / table
  names. No dumping / 拖库 of personal or business data.
- 越权 / unauthorized access: prove the bypass logic. Do not then harvest others'
  information.
- Backend / data-changing functions: prove you reached the function and hold the
  role. Do not actually edit / add / delete real data.
- Host / device high privilege: prove current-user environment info. Do not fetch
  other users' / business data, and do not pivot.

Under-proving still fails (a scanner hit with no demonstrated impact is ignored or
downgraded) — prove genuine impact, but harmlessly.

## 无害化原则 (the binding requirement)

### Confidentiality (机密性)

- After proving unauthorized / 越权 logic, do not retrieve or retain user info or
  system file info.
- SQL injection: the DB instance + library/table names is enough. No detailed
  personal / business data. No 拖库.
- Host/device high privilege: current-user environment info is enough. No other
  users' data, no business data.
- Do NOT use a gained host as a pivot to scan / test the internal network.

### Availability (可用性)

- Assume limited redundancy: no large-traffic / large-scale scans that could crash
  the network, host, or device.
- No test case that causes local or remote denial of service.
- Nothing that disturbs business logic or could cause users financial loss.

### Integrity (完整性)

- Backend functions: proving the role attribute is enough. No edit / add / delete
  / tamper.
- Host / device / DB high privilege: proving environment info is enough. No edit /
  add / delete / tamper of files, programs, or data.
- Upload that parses or executes: proving the parse-and-execute logic is enough.
  Leave no control-purpose program / code (no webshell / backdoor residue).

## Behavior norms

- Remove every test artifact afterward (webshells, uploaded files, created
  permissions). Leave no backdoor or guessable program / code.
- Do NOT modify / add / delete the target site's data. If a test genuinely needs
  to change test data, get the **platform's** authorization first — not just the
  operator's.
- Only prove existence (无害化验证); do not exploit a bug to pull data.
- If you gain a system's privilege and want to go deeper, contact the **platform**
  first; do not use that privilege to scan or set up a pivot / proxy.
- No large concurrent scanning; ensure the work does not affect the target's
  normal operation and access.
- Money-related bugs (e.g. payment): describe the result and the test account in
  the report. Never profit from the bug.
- Do not leak vulnerability content to unrelated people.
- Test until accurate, then submit. No false reports.

## How this tightens the general framework

In SRC mode these move from "operator-gated soft" (the general red-team default in
`src-safety-boundary`) to **off the table for this engagement**, because the
platform — an authority above the operator here — forbids them:

- internal-network pivoting / lateral movement / proxying — forbidden (the general
  skill allows it with operator consent; under a platform it is not the operator's
  to consent to).
- modifying / adding / deleting target data — needs the platform's prior
  authorization, not the operator's.

Still machine-enforced by the hook regardless of mode: destruction / 删库,
拖库 / data dump, DoS, money movement.

## Scope & what the platform ignores (decide what is worth proving)

Education-industry units only. Commonly ignored or downgraded, so do not spend a
submission on them: DoS, Self-XSS, no-sensitive-action CSRF, scanner output with
no working exploit method, meaningless source / internal-IP / domain leakage,
already-public or duplicate bugs, anything that needs MITM or an admin login to
trigger. Aim for demonstrated impact that scores Medium or above.
