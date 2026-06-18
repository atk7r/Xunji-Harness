---
id: ida-zerotrust-iam
product: IDA 零信任 / IAM unified identity access gateway
vendor: unknown vendor ("IDA" zero-trust / SDP, environment-aware admission)
aliases: [IDA, 零信任, IAM, SDP, 环境感知, iam/auth, trustAssess, startTunnel]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/iam/auth/", "trustassess", "getmachineiduuid", "idastrategyid"]
---

<!--
Grounding knowledge, not a weapon. Source: <run> run-observation.
Vendor undetermined → do not invent CVEs. No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: backend API prefix `/iam/auth/` (`/iam/auth/login/*`, `/iam/auth/index/*`, `/iam/auth/noLogin/*`,
  `/iam/auth/qrcode/*`, `/iam/auth/dingApi/*`).
- Signature: a front-end Vue portal at `/app/` (`LoginedShow` chunk); client tunnel logic `/startTunnel`,
  `/tunnelConnect`, connecting a local agent `http://127.0.0.1:60001/getMachineIdUuid`.
- Signature: zero-trust terms `trustAssess` (trust assessment), "IDA环境感知" (environment awareness),
  `idaStrategyId`, `sdpOn`, `agentIdentifyConfig`; unified error body `{"code":<int>,"msg":..,"content":..}`
  (code 5002/5000, etc.).
- Distinguishing notes: multi-tenant (tenant resolved by host); auth flow `initial → prepare(instId) → auth →
  trustAssess(environment awareness) → flowSuccess`.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: pre-login `/iam/auth/*` interface unauthenticated information-disclosure flaw class
  - Affected: `login/initial` (returns auth config + password policy), `index/getAgentConfig` (returns agent/SDP/network policy)
  - Mechanism: the config interfaces a pre-login page needs are unauthenticated and return too many internal fields
    (ServiceImpl class names / CAS internal addresses / password policy / zero-trust policy)
  - Reference: this repo's run-observation (an engagement, E-011)
  - source: run-observation
- Anchor: `login/forgetPwd` unauthenticated password-change endpoint / account takeover flaw class
  - Affected: `/iam/auth/login/forgetPwd` (fields account/code/password/passwordTwo/mobile)
    + `/iam/auth/login/sendValidCode` (notifyCode=forget_code)
  - Mechanism: an unauthenticated-reachable "send code → change password" chain; the harm depends on the SMS-code logic
    (can it be bypassed/brute-forced/tampered, or a phone set for another's account). A harmless test (fake account) can
    rule out "empty-code-changes-password" trivial bypass, but the code logic's soundness needs a real test account
  - Reference: this repo's run-observation (an engagement, E-017/E-018)
  - source: run-observation
- Anchor: noLogin / third-party OAuth / QR-login surface
  - Affected: `noLogin/getDingUserByCode`, `qrcode/getQrcode`+`qrcode/polling`, `dingApi/*`
  - Mechanism: unauthenticated namespaces; QR-login hijack (qrId binding/predictability), OAuth code handling needs
    per-interface review; this deployment's DingTalk is mostly unconfigured
  - Reference: this repo's run-observation
  - source: driver-reasoning
- Anchor: auth-flow environment-awareness (zero-trust) bypass flaw class
  - Affected: `prepare` (issues SESSION unauthenticated), `trustAssess` (needs agent machineId), `auth`, `flowSuccess`
  - Mechanism: step-by-step gating; this repo tested three paths (empty session hitting flowSuccess / forged machineId /
    auth probe) — all correctly gated (no bypass), but `prepare` pre-auth SESSION reuse, full instId enumeration, and the
    nasIp/inIframe semantics are still a logic-probing surface
  - Reference: this repo's run-observation (an engagement, E-016)
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: `/iam/auth/` + `trustAssess` / "IDA环境感知" confirms the product. Enumerate the unauth surface with
  benign GETs (do not trigger the WAF); **endpoint enumeration must first run `fetch_assets.py` to fetch all of the
  SPA's chunks** (otherwise endpoints are missed — see the 4/13 engagement lesson).
- Hard stops: info disclosure stops at proving sensitive fields are returned (no bulk data pull); forgetPwd change =
  integrity damage (operator-gated, not auto-changed); sendValidCode single-shot with a fake number (SMS bombing =
  flooding, hard-forbidden); QR hijack needs a human to scan (not autonomous).

## False-Positive / Confounders

- Multiple hosts on the same IP (cw/ots/quest/static/trust/wisdom…) all land on the same `/app/` default page from
  outside — they are aliases of the same app, not independent surfaces.
- `trustAssess` returning "terminal must be enabled" is normal zero-trust interception (a session ≠ access), not a
  bypassable signal.
- An endpoint list based on partial chunks → "enumeration complete" does not hold (must verify completeness with fetch_assets).

## References

- This repo's run-observation: runs/<run>/ evidence E-011~E-018; reports report_iam_unauth_disclosure.md /
  report_iam_forgetpwd_ato.md
