# Retrospective Loop Fix Review Scope

Review `reviewed.diff` in this directory. The change is a Codex-authored
maintenance diff for Xunji's Claude-primary run lifecycle, output hook, review
availability, probe evidence capture, saturation, coverage sync, OCR barrier
recording, and retrospective closure gates.

Primary risk areas:

- `.claude/hooks/output_gate.py` is behavior-changing and must not over-block
  closed runs or weaken existing safety behavior.
- `tools/peer_review.py` fallback must not create a fake independent-review pass.
- `tools/coverage_matrix.py --sync-coverage` must not overclaim asset verdicts.
- `tools/probe.py` preflight/cookie/CSRF support must preserve existing probe behavior.
- New retrospective gates should prevent repeated framework lessons without
  excessive false positives.

Verification already run:

- `python3 tools/selftest_all.py --timeout 600` -> 54 passed, 0 failed.
- `python3 tools/check_run.py runs/hamastar_20260709-test1_20260709` -> passed with warnings only.
- `python3 tools/check_knowledge.py && python3 tools/check_templates.py && python3 tools/check_runtime_boundary.py && python3 .agents/skills/xunji-closure-audit/scripts/closure_audit.py`.
- `git diff --check`.

Raw verification artifacts are recorded in `evidence.md` as E-002 through E-010.

Independent review WARN disposition:

- PR-001 was accepted as a real residual latest-run risk signal: the
  `check_run_hamastar.log` warnings remain present-tense follow-up work for that
  run (Metacog pass, classify_hosts content classification, and F-003/F-004
  barrier-closure wording). This maintenance diff fixes the framework recurrence
  path but does not rewrite those run facts.
- PR-002 is addressed by committing `peer_review.md` and `peer_review.json` as
  review artifacts in this record; the review verdict is WARN, not PASS.
- PR-003 was addressed by adding structural file/hunk summaries for `.diff` and
  `.patch` artifacts in `tools/peer_review.py`; reviewers no longer have to rely
  on a truncated excerpt to verify scope. The targeted behavior is also covered
  by `peer_review.py --selftest` inside full selftest.
- PR-004 is addressed in risk assessment by recording `loop_state_hamastar.log`
  and `coverage_sync_hamastar.json`; latest run still has deferred fronts and one
  untested applicable cell, so it is a closure-review candidate, not a magically
  closed run.
- Output-gate review concern was addressed by adding an `output_gate.py --selftest` subprocess case
  against a temporary real runs root with an open front.
- Captcha OCR concern is partially addressed: a real local captcha sample OCR smoke is recorded in
  `captcha_ocr_sample.json`, and the all-empty barrier branch is covered by the
  `captcha_ocr` selftest included in full selftest output. The real sample did
  not produce all-empty OCR, so no false barrier claim is made.
- Coverage reviewer blind spot was accepted and fixed after review:
  `tools/coverage_matrix.py` now maps `closed_type_b` to `closed`, with
  `coverage_matrix_selftest.log` covering that regression.
- PR-005 remains an arkcli backend partial-review limitation; final disposition
  treats the independent review as WARN with adopted fixes, not as a clean PASS.

Diff artifact SHA1: `fc7a30240695e36e0f336d2e5ae24c1edf8fd63a`.
