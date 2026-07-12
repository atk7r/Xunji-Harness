# Outbound Privacy Hardening Final Review

Verdict: WARN
diff_fingerprint: d14f3a92f3d968dc
reviewed_diff: d14f3a92f3d968dc

Author: Codex
Date: 2026-07-13
Review record: `review/records/2026-07-13-outbound-privacy-hardening/`

## Independent Review

- The final scoped privacy diff was reviewed by the arkcli panel plus
  fresh-context Claude under `--driver codex`.
- Final-8 returned WARN with no BLOCKER. Every actionable finding from earlier
  rounds is dispositioned; accepted code defects were fixed and re-reviewed.
- Frozen privacy-only diff SHA-1:
  `1dd922dba8fc55c941358bebae012efdcf09322a`.
- The concurrent unrelated `TODO.md` roadmap replacement and its separate review
  record are explicitly excluded from this review and commit.
- One arkcli member repeatedly returned parse errors; another arkcli member and
  fresh-context Claude completed. This limitation is recorded and is not treated
  as a clean PASS.

## Verification

- `python3 tools/check_rules.py` passed.
- `python3 tools/selftest_all.py` passed 60 suites, 0 failed (85.3s).
- Runtime controls include browser pre-I/O denial, two matching neutral multipart
  wire captures, replicated Cookie/Set-Cookie non-replay records, and replicated
  response-header/body redaction records.
- `git diff --check`, staged diff check, publication hygiene, privacy source-copy
  comparison, and frozen/staged framework diff comparison passed.

## Residual Limits

- Hidden-destination custom network code is author-and-handoff; hook text
  inspection is not claimed as proof of per-socket validation.
- The engagement proxy is trusted operator infrastructure. Driver bytes are
  checked before proxying; independent proxy rewriting or injection needs a
  separate proxy audit.
- Common reversible encodings are inspected, but arbitrary bespoke transforms
  cannot be exhaustively decoded; driver guidance forbids encoding around the
  policy and over-nested percent transforms fail closed.
