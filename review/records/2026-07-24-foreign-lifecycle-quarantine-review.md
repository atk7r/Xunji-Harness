# Resume-safe lifecycle admission and settlement review

- Date: 2026-07-24
- Author: Codex
- Verdict: PASS
- reviewed_diff: f1358ecb4d1d0e71
- Reviewed scope: runtime lifecycle admission, immutable foreign receipt schema,
  legacy quarantine/reprojection, denied-launch cancellation, offline local
  settlement, clause-local natural-language turn classification, recovery
  routing, capability registration, Claude owner docs, and architecture contract
- Initial scoped diff fingerprint:
  `49b534a024f2809a25c8c4c911f98d077805816f054bf1b1493108cfda67cdc3`
- Final scoped source/docs fingerprint after dispositions and Architecture
  Checkpoint:
  `9af8e0c32db3d0cdf5a38fd14420f929009a00fd5ba7fc6fa8c0020dbfab522f`
- Exact staged candidate fingerprint supplied to the final no-tools reviewer
  before review-metadata-only updates:
  `4a191122cbd9b8940495cf1943f986e5781caad0deaca6fb81bf3d7b3b7058f0`

## Reviewer availability

- arkcli panel: available, but the repository-maintenance invocation produced an
  engagement-closure bundle with no `evidence.md`, files, or findings. Its
  BLOCKER findings only said live-run evidence was absent and did not inspect
  the supplied code diff. This vote is recorded as invalid-scope / not
  applicable, not converted to PASS.
- Fresh-context Claude Code CLI: available through the configured
  DeepSeek-backed Claude Code; no tools and no edits.
- Codex self-review: synthesis only; not an independent vote.

## Fresh review and disposition

Initial fresh review session `ddafd5b8-9ff8-4750-b358-dea0a42d1bd3`
returned WARN.

- Accepted: raw substring search in `assignments.json` could keep a foreign Stop
  as false lifecycle debt. Fixed with recursive exact matching restricted to
  runtime identity fields, plus a regression where an unrelated note contains
  an agent-id prefix.
- Clarified: immutable v1 `transcript_sha256` is a digest of local transcript
  path identity, not transcript contents. The schema and code now state this;
  the field was not renamed because live immutable v1 receipts already exist.
- Dismissed: “no audit trail” conflicts with the content-addressed receipt,
  original seq/hash, journal-head binding, recovery status, and projection
  omitted-count.
- Dismissed: “foreign directory may not exist” conflicts with
  `_atomic_bytes()` calling the tested top-down directory-chain creator and
  fsync barriers.
- Dismissed: argparse accepting flexible option order does not expand the live
  Hook boundary; the capability registry still accepts only the documented
  exact argv.

Final fresh review session `069c0b5c-a3e7-4eed-ac5e-3df0d5042bd9`
returned PASS with no remaining source defect. It specifically rechecked exact
assignment ownership, every quarantine veto signal, receipt immutability,
idempotent replay, effective projection, and owner-doc consistency.

After the live resume exposed the denied-launch, offline-policy, and
cross-clause intent defects, the complete staged candidate was reviewed again by
fresh session `a56dc829-8096-48fc-8191-8d5850b016e5` with `--tools ""`.
It returned `VERDICT: PASS` and no actionable source defect. The review
specifically confirmed:

- only exact plan/lane/session/transcript-bound `PreToolUseDenied Agent`
  identities become negative launch proof;
- failed/successful Post, Start/Stop, and child actions remain debt;
- removing current-plan policy reauthorization does not weaken cancellation,
  because immutable transaction identity and repeated locked stale proofs remain;
- prepared cancellation and the runtime lock close the relevant TOCTOU windows;
- clause-local denial prevents scoped effect constraints from revoking the
  affirmative action while explanation/denial prompts stay read-only;
- foreign quarantine remains append-only, schema-bound, idempotent, and
  fail-closed on every Xunji ownership signal.

The reviewer first emitted the PASS in its transcript. The live Stop hook then
requested a Coda because the large diff prompt was mechanically classified as
an active-run execute turn; that output-protocol retry does not alter the
no-tools review vote.

## Verification

- `runtime_receipts.py --selftest`: PASS
- `capability_registry.py --selftest`: PASS
- `workers.py --selftest`: PASS
- `turn_contract.py --selftest`: PASS
- `check_rules.py`: PASS
- `check_templates.py`: PASS
- `tools/selftest_all.py`: 69/69 PASS (115.4s final run)
- `git diff --check`: PASS
- isolated Claude primary-driver foreign-lifecycle E2E: PASS
- live path-bound resumed cancellation E2E: PASS, receipt/state adjudicated
  separately with target=0 and Agent=0
- copied-run cancellation E2E: not applicable; absolute `run_dir` receipt
  identity correctly fails closed rather than being rewritten
