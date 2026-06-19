# Independent Review — render.py --eval + KB seed + doctrine + ujs ledger fixes

_backend: codex (heterogeneous) · 2026-06-20_
> Candidate vote, not verdict. Driver integrated each finding through the evidence gate.

## Scope

This round's changes: `tools/render.py` (new `--eval` browser-replay mode), `tools/selftest_all.py`
(registered render), the mandatory-retrospective closure gate (`tools/check_run.py`, `tools/setup_run.py`,
`docs/templates/run/retrospective.md`), doctrine edits (`CLAUDE.md`, `docs/cognition/README.md`), five new
grounding KB entries (weaver-emobile, synjones-ecard, magtech-caibian, wengine-webvpn,
deserialization-signatures), and the `runs/ujs_20260619` evidence-ledger fixes.

## Round 1 — Verdict: BLOCKER (findings integrated)

- [BLOCKER] `render.py --eval` not guard-routed; eval JS could issue unlimited fetch/XHR outside guard
  while the tool claimed READ-ONLY → FIXED: `RateLimiter().gate(host)` before `page.evaluate`; docstring
  carves out `--eval` as not-read-only (state-changing = author-and-handoff, proof-level auto-run only).
- [BLOCKER] `--eval` traffic not captured in network.json → FIXED: network/cookie capture moved AFTER the
  eval block + 700ms flush; verified an eval-issued request now appears in network.json.
- [BLOCKER] E-013 overconfirmed as a broad SQLi refutation (re-captured "valid" artifact was a campus
  prompt, not tree content) → FIXED: downgraded 0.8→0.6 ("strong suspected", unconfirmed), artifacts'
  weakness disclosed. Confirmed set now `[E-018]` only.
- [WARN] E-018 confirmed without Replicated/Control → FIXED: added (four converging signals); has_control=true.
- [WARN] coverage.json examined:0 stale → FIXED: 13 examined assets marked.
- [WARN→PASS] KB entries stay grounding-tier (recognition + anchors, no payloads); deser entry surfaced on
  signature hit, not a blind sweep → preserves autonomy. No change needed.

## Round 2 — Closure re-check — Verdict: PASS

All five prior findings RESOLVED; no new issues introduced by the fixes (codex read-only re-verification,
2026-06-20). Validation: selftest_all 19/19, check_knowledge 24, check_rules pass.

## Blind-spot note

`--eval` in-page fetch cannot be per-request body/scope-guarded (it is the browser's fetch, not probe.py);
the boundary is enforced by rate-pacing + full traffic capture (auditable) + the contract (not read-only,
state-changing handed to operator, proof-level auto-run). This matches the effect-not-method boundary.
