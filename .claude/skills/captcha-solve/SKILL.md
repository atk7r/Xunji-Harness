---
name: captcha-solve
description: Procedure for solving an interactive captcha barrier (slider / click-select / rotate / text) by driving a real headless browser and reusing the page's OWN verification JS, then extracting the resulting validate token to feed a follow-up request. Invoke when a captcha gates the endpoint you need to verify. Procedure and tooling only — no target selection, no per-vendor payload library.
---

# Captcha Solving (barrier bypass)

A **capability/procedure** skill, not a playbook. Solving a captcha is **method,
and method is free** — this skill does not decide *what* to attack or *whether*
to; it encodes the recurring, fiddly mechanism of getting past a captcha barrier
so a downstream check can run. It is generic on purpose: the *approach* transfers
across vendors; it ships no vendor payload kit.

## When to invoke

- A captcha (slider / click-select / rotate-to-upright / text-OCR) sits in front
  of the request you need to send to verify a vulnerability (e.g. an
  unauthenticated endpoint reachable only after a captcha token).
- You need a **valid verify token**, not to defeat captcha "in general."

## Core principle: reuse the page's own JS in a real browser

The single most reusable insight: **do not reimplement the site's crypto/encoding
in Python.** Load the real page in Playwright and call the site's own functions
via `page.evaluate(...)`. Pages routinely ship the encode/decode/sign helpers
client-side (the key is often delivered in the challenge itself), so the browser
context already holds everything needed to produce a valid response.

```text
load page (acquire its JS + cookies)
  -> fetch challenge   (in-page fetch, so same-origin + headers are real)
  -> solve             (compute target, OR call the page's own decode/sign fn)
  -> build response    (human-like trajectory / ordered clicks / angle)
  -> submit            (in-page fetch to the check endpoint)
  -> extract token     (the validate token from the success response)
  -> feed forward       (attach the token to the follow-up request)
```

## Per-type notes (generic — derive specifics live)

- **Slider**: find the gap offset (from a returned coordinate, or by image diff of
  bg vs puzzle), then drag the handle there. The response usually wants a
  **trajectory**, not just an endpoint — see gotchas.
- **Click-select (click-select)**: the challenge names targets (chars/icons) in an order;
  click their on-image coordinates in that order. Coordinates may need scaling
  from natural to rendered image size.
- **Rotate**: rotate the image to upright; submit the angle (often as a fraction
  of 360 or a pixel offset the page's JS maps to an angle).
- **Text / distorted**: out of scope for in-page solving; if needed, hand the
  image to an OCR/solver step — keep it a separate tool, not baked in here.
  Use `tools/captcha_ocr.py` for bounded local OCR diagnostics; after 3-5 empty
  attempts, record an OCR barrier / Type B condition instead of blind guessing.

## Gotchas (learned the hard way; generalize, don't hardcode)

- The verify field is often a **JSON string**, not a scalar — parse it, read the
  inner `validate`/token field, and re-serialize when submitting.
- Submitting a **single endpoint position is rejected**; build a **human-like
  trajectory** — many points (≥ ~20), ease-in/out acceleration, realistic total
  duration (~1s+), with start/end timestamps.
- Encrypt/sign each trajectory point with the page's own fn and the
  challenge-supplied key, exactly as the page would — don't invent the format.
- When the challenge provides **no image to measure** (no gap to compute), the
  expected solve may be a fixed extreme (e.g. drag fully to one end) rather than a
  decoded coordinate — try that before assuming failure.
- Use a real `User-Agent`, `ignore_https_errors`, and `locale` matching the site;
  drive the challenge/submit as **in-page `fetch`** so origin and headers are
  authentic.

## Tooling

- Run under the project's Playwright venv (`render.py` and the browser tools use
  `.venv\Scripts\python.exe` on Windows, `.venv/bin/python` elsewhere). Chromium
  is fetched once via `playwright install chromium`.
- Route host access through the guard (`from harness.guard import RateLimiter`)
  when wiring this into a tool under `tools/`; a standalone PoC copy may fall back
  to a no-op limiter.
- A solver belongs with its PoC: an undisclosed-vuln solver lives in that vuln's
  `poc_library/xday/<id>/` (local), packaged per the `poc-package` skill.

## Boundary

Solving the captcha is free (method). What you do **after** the barrier is graded
by **effect**, not by this skill:

- Default to **proof-level (prove-and-stop)**: solve once, prove the gated endpoint is
  reachable, stop.
- Driving a solved captcha to enable **high-rate brute-force, credential
  stuffing, or request flooding** crosses into the effect-gated / hard-blocked
  zone (availability / flooding) — that is not unlocked by being able to solve the
  captcha. **SMS / SMS verification-code endpoints especially**: solving the
  captcha does not license triggering a flood of messages.
- Limits remain `safety-boundary` (effect, not method) and the
  `.claude/hooks/` gate.
