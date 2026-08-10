# Target Destination Projection Maintenance Review

## Scope

- Candidate diff SHA-256 before this durable review record:
  `ede57e8febae9549ca93b49b3b2d681980228a36f15b0ccb5071aaffd4d963a6`
- Source SHA-256:
  - `capability_registry.py`: `7c9aeeaca0b3b722627bfee2039ee96628e4a416552e30e496eb6e7c8f787184`
  - `turn_contract.py`: `75dee8d67276722cb5591fc3a4401e5dae724f1c9243e2211a6e3901c486caaa`
  - `runtime_receipts.py`: `4837e5e897f92100869cd0ffd575deaead05e51e79789084a6760d253e15f244`
- Objective: stop output names such as `f003-cms-8090-app-js.js`, headers,
  payloads, and prose from being classified as coverage destinations while
  preserving every registry-declared primary/supporting argv destination.

## Verification

- `capability_registry.py --selftest`: PASS.
- `runtime_receipts.py --selftest`: PASS.
- Turn-contract focused assertions: PASS, including dotted `.js` save names,
  URL-shaped payload/header values, supporting preflight URLs, and scheme-less
  fail-closed behavior. The command retains seven SessionEnd assertion failures.
- Full matrix: 67 passed / 3 failed suites (`setup_transaction`,
  `turn_contract`, `xunji_statusline`), matching the published baseline's
  SessionEnd/session-selection failures.
- Rules, templates, runtime-boundary, compilation, and diff checks: PASS.
- DeepSeek-backed Claude primary driver executed the exact turn-contract selftest
  through real Hooks in an isolated candidate worktree. No extra tracked files
  appeared; the four focused assertions were `ok`.

## Independent Review

- Verdict: WARN
- reviewed_diff: ede57e8febae9549
- diff_fingerprint: ede57e8febae9549
- Matrix required for Codex-authored maintenance: external assistance plus
  fresh-context Claude, with Codex synthesis.
- External assistance limitation: the configured `arkcli` backend failed because
  its AgentPlan subscription had expired. No external or heterogeneous vote is
  claimed.
- Fresh-context Claude verdict: WARN. It found no defect in the core `.js`,
  payload, or header correction. Successive review findings led to shared scan
  validation/projection, probe DIFF coverage, explicit scheme-less fail-closed,
  removal of non-Bash arbitrary-field settlement credit, production excerpt
  serialization coverage, invalid-receipt integrity debt, and CJK IDN regression
  coverage.

## Codex Synthesis

- Accepted and fixed: validator/projector drift risks, DIFF coverage, scheme-less
  ambiguity, arbitrary structured-field credit, production receipt serialization,
  invalid successful-receipt projection, and over-broad CJK glued-prose matching.
- Dispositioned limitation: indirect replay/rerun capabilities deliberately have
  no destination-bearing argv; their target inventory comes from frozen run
  artifacts and remains owned by those registered tools. This change does not
  claim to redesign replay internals or redirect-chain policy.
- Dispositioned pre-existing debt: coverage admission remains host-oriented in the
  public baseline while assignment/settlement preserves explicit ports. That wider
  port-scope consistency issue is not converted into a silent PASS and is not
  broadened into this F-003 argv-classification repair.
- Confirmed source fact: normalized production runtime events persist the boolean
  `target_action` field and JSON `_excerpt`; the receipt tests now exercise the
  same serialization and the invalid-target integrity path.
- Publication decision: publish the scoped repair with WARN disclosure. Do not
  claim heterogeneous review, historical failure repair, live-target proof, or
  closure of the broader port/redirect/indirect-tool architecture fronts.
