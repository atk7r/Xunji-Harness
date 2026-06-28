---
id: weak-credentials-captcha
product: Weak credential policy and captcha bypass recognition
vendor: cross-product
aliases: [weak password, default password, captcha bypass, rate limit, brute force, 弱口令, 验证码绕过, 爆破]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["retry-after", "too many login attempts", "password must be at least", "account locked", "429 too many requests", "captcha challenge"]
---

<!--
PUBLIC grounding tier. Generic recognition of weak credential policies,
captcha/rate-limit weaknesses, and authentication brute-force surfaces —
cross-product. Source: hamastar run (captcha cookie cleartext, ~70 password
attempts), mokwon run (student:12345678 weak password), DVWA runs
(weak/default credentials), cqytxy (arithmetic captcha solving).
-->

## Recognition (identification only)

- Signature (password policy weakness): password accepted with length < 8,
  no complexity requirements (no uppercase/number/special enforced), common
  passwords accepted. The tell is the error message: "must be at least 6
  characters" = weak policy; "must contain uppercase, lowercase, digit, and
  special character, minimum 12 characters" = strong policy.
- Signature (default credentials): the service documentation or default
  configuration references built-in accounts with well-known passwords;
  vendor install guides often list these. The tell is a login page that
  accepts common username/password pairs from the product manual.
- Signature (rate-limit absent): no `Retry-After` header or `X-RateLimit-*`
  headers on authentication endpoints; no 429 Too Many Requests after rapid
  attempts; server processes every login attempt with consistent response time.
- Signature (account lockout absent): no "account locked" or "too many attempts"
  message after 5-10 failed logins; consistent error message regardless of
  attempt count.
- Signature (captcha weaknesses): captcha image URL returns challenge without
  requiring session/auth; captcha answer stored in cookie/header in plaintext
  or reversibly encoded; slider captcha where the target position is sent
  client-side; arithmetic captcha with simple expression. "Click to verify"
  behavioral captcha with no server-side validation.
- Signature (user enumeration): different error messages for "user not found"
  vs "wrong password"; different response times for valid vs invalid users;
  password reset flow confirms/denies user existence.
- Distinguishing notes: weak password policy is a config-hygiene signal, not
  a direct vulnerability. The finding is in the COMBINATION: weak policy +
  no rate limit + no lockout = brute-force feasible. Each alone is LOW;
  together they form a viable attack path.

## Weak-Point Anchors

- Anchor: no rate limit + no lockout → credential brute-force feasible
  - Affected: login endpoints with no request throttling and no account lockout.
  - Mechanism: the attacker can send thousands of login attempts per minute
    without being throttled or triggering account lockout. Combined with a
    common password list, this yields account takeover for any user with a
    weak password.
  - Reference: CWE-307 (Improper Restriction of Excessive Authentication Attempts)
  - source: run-observation (hamastar D-003: ~70 password attempts on admin
    without lockout; scshr: no lockout on AIS login)
- Anchor: captcha answer leaked client-side
  - Affected: captcha implementations where the verification answer is sent
    to the client (in cookie, response body, or client-side JavaScript).
  - Mechanism: the captcha challenge response includes the expected answer
    (plaintext or reversibly encoded); the attacker extracts it and replays
    it with the login request, bypassing the intended human-verification.
  - Reference: CWE-602 (Client-Side Enforcement of Server-Side Security)
  - source: run-observation (hamastar E-010: captcha value in cleartext cookie;
    cqytxy: arithmetic captcha with predictable pattern)
- Anchor: user enumeration enables targeted brute-force
  - Affected: login flows that distinguish "user exists" from "wrong password".
  - Mechanism: the attacker first enumerates valid usernames from the error
    message or response timing, then brute-forces only those accounts —
    dramatically reducing the attack surface from the full user space.
  - Reference: CWE-204 (Observable Response Discrepancy)
  - source: run-observation (scshr: different ForgotPassword responses;
    hamastar: "用户密码输入错误" confirms valid username)

## Verification Principle

- Existence proof: test password policy by submitting a weak password and
  observing the error message. Test rate limiting by sending 5-10 rapid login
  attempts and observing response status/timing. Test captcha by inspecting
  the captcha response for leaked answers. Test user enumeration by comparing
  login errors for known-valid vs known-invalid usernames.
- Hard stops: confirm the weakness exists. Do NOT run a full brute-force
  attack (even with a small wordlist) — that is operator-gated. Do NOT use
  discovered valid usernames to attempt login. The finding is the weakness
  in the defense mechanism, not the compromised account.

## False-Positive / Confounders

- A consistent error message ("Invalid username or password" for both cases)
  is correct implementation — not user enumeration.
- Rate limiting may be IP-based; test from multiple IPs or wait for cooldown
  before concluding no rate limit exists.
- Account lockout may be silent (no error message change) — a locked account
  still receiving "Invalid password" but never succeeding even with the
  correct password is a locked account.
- Captcha that appears weak may still have server-side replay protection or
  HMAC signing — test that the extracted answer actually works on a real
  request before concluding bypass.
- Some systems use adaptive rate limiting (increasing delays) rather than
  hard cutoffs — a consistent ~2s response time after rapid attempts is a
  rate limit (just a subtle one).

## References

- CWE-307: https://cwe.mitre.org/data/definitions/307.html (Improper Restriction of Excessive Authentication Attempts)
- CWE-204: https://cwe.mitre.org/data/definitions/204.html (Observable Response Discrepancy)
- CWE-602: https://cwe.mitre.org/data/definitions/602.html (Client-Side Enforcement of Server-Side Security)
- OWASP Authentication Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- This repo's run-observation: hamastar (captcha cookie cleartext, no account
  lockout); mokwon (student:12345678 weak password); cqytxy (arithmetic
  captcha solving); scshr (user enumeration via ForgotPassword)
- Related: [[auth-protocol-surface]] [[open-registration-tenant]]
