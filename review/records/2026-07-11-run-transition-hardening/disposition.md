# Review Disposition

## PR-001 - Partial heterogeneous panel

- Status: open limitation
- Result: Claude Code completed; arkcli did not produce a valid vote.
- Detail: `kimi-k2.7-code` timed out and `glm-5.2` returned an unparseable response.
- Decision: Do not count arkcli as PASS. Refresh the review package after fixes,
  rerun Claude, and retry arkcli while retaining the failure record.

## Claude blind-spot findings

### Active-front denial accepted `frontier.md`

- Status: accepted and fixed
- Resolution: `_denied_result_claim_reason` now compares the exact state-derived
  envelope whenever a run is known. `frontier.md` is valid only with zero active
  fronts; an active run requires its actual F-id.
- Test: `frontier.md denial cannot bypass a real active F-id`.

### Control-file suffix and child-path coverage

- Status: accepted and fixed
- Resolution: protected runtime matching now includes `/`, `\\`, and `.` after
  protected names. Pending-directory children and atomic `.tmp` variants cannot
  be edited directly, including when no active run exists.
- Test: `root control files stay protected with no active run` covers both the
  pointer and a pending-contract child file.

### Transition-field/source-preservation coverage

- Status: accepted and fixed
- Resolution: statusline transition tests now require the target's `origin_run`
  and `bound_run` fields and verify that the source contract remains intact.

### Stop retry resolves before active-run lookup

- Status: dismissed with rationale
- Resolution: Claude Code defines `stop_hook_active` as a retry after some Stop
  hook already blocked. Re-entering any Stop gate causes the client block-cap
  override observed in the incident. Retry exits the chat turn only; it cannot
  change front files, completion markers, receipts, or `check_run` results.

### Conservative fd parsing

- Status: dismissed
- Resolution: rejecting non-canonical redirect placement is intentional. The two
  observed harmless suffixes are accepted; unknown shell forms remain denied.

### Script argument validation

- Status: dismissed with defense in depth
- Resolution: the gate verifies exact in-repository script identity and current
  operator transition intent. Each script remains authoritative for its argument
  schema and path validation. Added tests cover unrelated set-active, prompt-named
  resume, unauthorized setup, and out-of-tree script impersonation.

### Python executable spelling

- Status: accepted and fixed
- Resolution: exact control parsing now accepts `python`, `python3`,
  `python3.N`, and `python3.N.P`; tests cover bare and micro-version forms.

## Additional post-review audit fixes

- A pure `创建新 run` prompt now classifies as EXECUTE without requiring `/loop`.
- Multiple fresh pending contracts fail closed instead of crossing sessions.
- Contract hooks bind only the explicit pointer and never infer a recent run.
- No-run PreToolUse now requires a current-session pending contract for lifecycle
  transitions and blocks target execution until binding.
- GLM's recovered reasoning identified that PreTool validated a session but
  `claim_pending_contract` later selected by run-name heuristics. This was
  accepted and replaced with a hook-written target/session/prompt-hash claim
  ticket. Concurrent claims for one target fail closed; no heuristic fallback
  remains.

## Final Claude review blind spots

- No-active-run ordinary prompts already classify as `NORMAL`; a direct test now
  prevents regression. The review's EXECUTE concern came from a stale reading.
- English `clear the active run pointer` authorization and `--classify` argument
  placement now have explicit tests.
- `setup_run.py --target` is a target URL, not a run-name override. The parser
  correctly consumes its value and keeps the positional slug; an explicit test
  now locks this behavior.
- Unknown lifecycle flags now fail closed instead of allowing a future
  value-consuming option to be mistaken for the run slug.
- Same-session claim overwrite is intentional idempotence. Different-session
  claims for the same target remain a hard ambiguity error.
- Non-canonical shell redirects remain denied by design; the control parser is
  an allowlist, not a general shell parser.
- Final similar-path scan found that anti-drift and `run_gate` still inferred the
  most recently modified run when the pointer was absent. This was accepted and
  fixed: every runtime hook now treats the explicit pointer as the only run
  authority; tests prove recency cannot select a run.
- Final5 blind-spot review found that a bare `active run` mention could classify
  an informational question as EXECUTE. `RUN_BIND_RE` now requires an explicit
  set/switch/select/bind action while preserving lifecycle command matches; tests
  cover both the read-only question and executable switch.

## Final3 formal WARN disposition

- `PR-001`: resolved as review-generation ordering. The referenced final3 files
  now exist; future bundles do not promise the name of their own not-yet-written
  output.
- `PR-002`: accepted and fixed. `verified` was not a valid evidence maturity;
  all four entries now use `finding`, and `evidence.json` was regenerated by the
  canonical parser.
- `PR-003`: accepted and fixed. Known value and boolean options are explicit;
  every unknown lifecycle option fails closed instead of shifting its value into
  the slug position.
- `PR-004`: dismissed. Claude Code marks Stop retries with `stop_hook_active`
  specifically after a hard block; re-running any blocking Stop hook recreates
  the observed client block-cap loop. Canonical run state and `check_run` remain
  unchanged, so retry release cannot manufacture completion.
- `PR-005`: accepted as a residual test boundary. The hook subprocess path,
  claim consumption, setup activation failure, contract transfer, and atomic
  pointer switch are each covered. A monolithic setup subprocess would write
  into the repository's real `runs/` root, so the suite keeps these seams
  isolated.
- `PR-006`: dismissed as intentional conservative parsing. Canonical redirect
  suffixes are allowed; other shell forms are denied rather than normalized.

## Final6 formal WARN disposition

- `PR-001`: accepted and fixed. Direct tests now cover
  `loop_bootstrap.py --resume` and `xunji_statusline.py --set-active` target
  extraction.
- `PR-002`: dismissed with the established Stop retry rationale. A second
  blocking diagnostic recreates the client retry loop; canonical state still
  exposes every unresolved failure on the next operator turn.
- `PR-003`: accepted and fixed. Denial-envelope anchors now union derived loop
  state with a direct canonical `frontier.md` parse, so an empty derived result
  cannot downgrade an active front to `frontier.md`.
- `PR-004`: accepted and fixed. Pending bootstrap tests now reject both target
  Bash execution and an arbitrary `Write` before run binding.
