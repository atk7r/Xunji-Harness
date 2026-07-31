# TODO Completion Matrix

This record is the acceptance map for completing `TODO.md`.  A checked item must
end in one of two states:

- `implemented`: code/docs are wired to an owner and covered by a deterministic
  check or real-driver evidence.
- `decided`: a decision-gated option was evaluated and explicitly rejected or
  superseded with a concrete reason; it is not described as implemented.

The starting baseline is commit `28929965d81eac66ffbc58b2c20b37ac69f5a7c2`.
Before this completion patch, `check_rules`, `check_templates`,
`check_runtime_boundary`, and the closure audit passed; `selftest_all.py`
reported 69 passed / 0 failed.

| ID | TODO line | Acceptance owner | Required closure |
|---|---:|---|---|
| T01 | 95 | typed artifact query | narrow sort/unique/cut/search grammar, containment, caps, selftest |
| T02 | 97 | target and artifact capabilities | WebSocket handshake plus existing range/chunk/JS inventory paths share mandatory services |
| T03 | 116 | Macro-Stage policy | S1 projection binds scope/source/asset/stack/knowledge/coverage/front/budget inputs |
| T04 | 118 | lane planner | S1 defaults to effect-disjoint offline lanes; model egress remains explicit |
| T05 | 121 | Macro-Stage policy | S1 exit requirements are mechanically projected |
| T06 | 123 | evidence gate | S1 outputs remain observation/candidate only |
| T07 | 127 | work-plan schema/validator | S2 lane plan fields and controls are complete before effects |
| T08 | 129 | Agent settlement | every execution return has Reviewer then Root settlement |
| T09 | 131 | overlap/budget policy | one ready target lane per asset; shared request/model budgets |
| T10 | 134 | Macro-Stage policy | S2 exit blocks Type-A, merge, review, and coverage debt |
| T11 | 137 | stage transition | new inventory/knowledge gaps can return S2 to S1 |
| T12 | 141 | Macro-Stage policy | S3 projects an explicit closure-gap summary |
| T13 | 143 | lane planner/completion review | S3 biases verification/review/parity and can reopen S2 |
| T14 | 145 | Single Synthesizer | canonical promotion remains Root single-writer |
| T15 | 147 | closure gate | final gate covers check_run, independent review, parity, Agents, retrospective, journal |
| T16 | 197 | scheduler | two compatible ready lanes use capacity-bounded parallel mode |
| T17 | 218 | stage scheduler defaults | distinct S1/S2/S3 effect and fan-out profiles with tests |
| T18 | 236 | native Agent control | notification/message guidance cannot become result/evidence/authority |
| T19 | 238 | maintenance isolation decision | optional host worktree path is documented; live run keeps one evidence store |
| T20 | 257 | W2 gate | T03-T19 plus driver evidence pass |
| T21 | 260 | W3 gate | T01-T02, route breaker, observability, and error projections pass |
| T22 | 315 | benchmark metrics | delegation/evidence/coverage/yield/duplicate/merge/gain/budget/FP/reopen metrics |
| T23 | 318 | scheduler A/B | recorded root-direct/serial/parallel fixture comparison and decision |
| T24 | 328 | fd-relative hardening decision | cross-platform value/risk evaluation recorded |
| T25 | 331 | foreign lifecycle | typed quarantine is wired and regression-tested |
| T26 | 343 | setup adapter evaluation | HTML/PDF/DOCX/text/OCR inventory and admission decisions recorded |
| T27 | 346 | normalizer modes | off/local/external effects, receipts, redaction, and fail-closed boundaries tested |
| T28 | 349 | intel URL decision | default-disabled separate-capability decision and redirect/scope requirements recorded |
| T29 | 352 | setup input matrix | URL/host/JSON/Markdown/path/mutation/context adversarial fixtures |
| T30 | 355 | normalizer hard gate | source refs, pointer selection, instruction non-execution, and value benchmark pass |
| T31 | 360 | canonical parser | typed source-span parsers and explicit schema errors used by named consumers |
| T32 | 363 | parser fixtures | canonical/legacy/duplicate/fence/punctuation/hostile/oversize cases |
| T33 | 365 | peer review | live-run/maintenance-diff/plan/docs scope kinds and rubrics |
| T34 | 367 | review receipt | scope kind, reviewer identity, reviewed hash, context limits, failures; stale detection |
| T35 | 372 | candidate promotion roadmap | each boundary has schema/validator/writer/rollback disposition |
| T36 | 375 | candidate authority | AI remains candidate-only across admitted boundaries |
| T37 | 377 | promotion bindings | Agent/review/evidence/JS/scope/knowledge/report bindings verified |
| T38 | 380 | candidate benchmark decisions | expansion occurs only on measured benefit; rejected classes are superseded |
| T39 | 385 | CI | PR and OS/Python matrix jobs for deterministic checks and suites |
| T40 | 388 | formal tests | `tests/` allowed; compatibility selftest entrypoints retained |
| T41 | 390 | dev environment | locked optional dev dependencies, ruff, and narrow type check |
| T42 | 392 | preflight | diff check, sensitive scan, review fingerprint; safe CI artifacts |
| T43 | 397 | roadmap truth | scorer-current versus fixture/A-B gaps corrected |
| T44 | 401 | generated excerpts | owner/alias duplication mechanically rejected |
| T45 | 404 | closure audit | skill/tool/selftest/template/schema/doc wiring covered |
| T46 | 409 | backlog metadata | every formal item has owner, dependency, size, acceptance, status, evidence |
| T47 | 414 | negative benchmarks | setup/parser/merge/conflict/Agent/stale/backend/closure negative fixtures |
| T48 | 417 | normalizer metrics | precision/recall/provenance/hallucination/schema/rejection/pointer metrics |
| T49 | 419 | local hygiene | warning-only root scratch detection without content reads or deletion |
| T50 | 421 | scratch cleanup | bounded dry-run-by-default TTL tool and retention guidance |
| T51 | 426 | repository adapter decision | admit only demonstrated two-consumer abstraction |
| T52 | 428 | module split decision | split only touched boundaries with measured benefit |
| T53 | 430 | context budget | always-loaded files have budgets and duplicate-rule fixtures |

## Completion ledger

Size is the delivered change size (`S/M/L`), not an estimate of future work.
`base` means the prerequisite was already enforced at the starting commit and
was reverified rather than reimplemented.

| ID | Status | Dependency / size | Evidence or decision |
|---|---|---|---|
| T01 | implemented | registry / M | `tools/inspect_artifact.py --selftest`; literal/regex search, sort, unique, cut, JSON, caps and containment |
| T02 | implemented | probe + registry / M | `tools/websocket_probe.py --selftest`; existing `js_inventory.py`, `probe.py` range/chunk recorder path |
| T03 | implemented | work plan / M | `stage_policy.py` S1 required inputs and projection fixtures |
| T04 | implemented | T03 + workers / M | `workers.py plan --stage S1`; offline execution/review pairs only |
| T05 | implemented | T03 / S | S1 exit facts and missing-fact blockers in `stage_policy.py` |
| T06 | implemented | evidence gate base / S | S1 whole-plan target rejection plus existing evidence-promotion owner |
| T07 | implemented | work-plan base / M | stage-aware lane validation plus frozen lane schema |
| T08 | implemented | Agent settlement base / S | existing execution→Reviewer→Root typed settlement fixtures reverified |
| T09 | implemented | T07 / M | S2 same-asset ready-target conflict rejection; existing shared budgets |
| T10 | implemented | T03 / M | S2 Type-A/open, merge, review and coverage debt exit blockers |
| T11 | implemented | work-plan owner / S | `work_plan.py --selftest` proves settled S2 can replan to S1 when the coverage/knowledge inventory prerequisite reopens |
| T12 | implemented | T03 / M | S3 closure-gap facts: canonical debt/journal derived; check-run/review/parity remain owner-required and fail closed |
| T13 | implemented | T12 + workers / M | S3 generates verify/review only; existing final review can reopen S2 |
| T14 | implemented | synthesizer base / S | S3 control/repo-mutation lane rejection and existing Root-owned promotion |
| T15 | implemented | check-run base / S | current closure predicate and global completion fixtures reverified |
| T16 | implemented | T17 + T23 / M | capacity-bound scheduler remains autonomous soft recommendation; hard parallel gate rejected by measured merge cost |
| T17 | implemented | T03 + workers / M | S1/S2/S3 distinct proposal, whole-plan/dependency-ready validation, exact legacy lane-shape dual read, CLI `commit-plan --stage` selftests |
| T18 | implemented | Agent Board / S | Claude-primary launch/return/settlement owner freezes native-message non-authority |
| T19 | decided | architecture / S | maintenance worktrees admitted only for source isolation; live evidence store remains single |
| T20 | implemented | T03-T19 / L | isolated Claude Code 2.1.201 primary-driver completed S1 plan→Hunter→Reviewer→Root cycle_end; receipt adjudication in `real-driver.md` |
| T21 | implemented | T01-T02 + guard base / L | typed offline/WS tools plus existing route breaker/status/error fixtures |
| T22 | implemented | bench / M | `bench.py` emits attributable delegation/evidence/coverage/yield/duplicate/merge/gain/budget/FP/reopen metrics; reopen is lower-is-better |
| T23 | decided | T22 / M | typed finite rows/caps; `bench/scheduler-ab/truth.json` records speed/coverage gain, merge cap exceeded, soft-only |
| T24 | decided | threat model / M | decision record rejects repository-wide fd rewrite absent reproduced race and cross-platform proof |
| T25 | implemented | runtime base / S | foreign lifecycle quarantine and interrupted Reviewer fixtures reverified |
| T26 | decided | setup owner / M | per-format provenance/fixture requirements recorded; unsupported formats remain `normalizer_required` |
| T27 | implemented | setup normalizer base / S | `off/local/external` candidate, redaction/hash/receipt and fail-closed fixtures reverified |
| T28 | decided | target boundary / S | intel URL remains disabled; any future fetch is a separate redirect-gated target capability |
| T29 | implemented | setup-source base / M | host/URL/IDNA/JSON/Markdown/injection/path/mutation/size/context matrix plus real-driver-discovered relative Markdown precedence fixture |
| T30 | implemented | T27-T29 / S | existing deterministic source/hash/pointer/no-instruction/value gates reverified |
| T31 | implemented | parser owners / L | `canonical_records.py`; input-shape/context/saturation/check-run consumers migrated with historical-shape dual read |
| T32 | implemented | T31 / M | fence, case variants, Chinese punctuation/source spans, bounded legacy warnings, native/explicit-legacy finding boundary, typed review and Agent-result fixtures |
| T33 | implemented | peer review / M | four scope kinds and non-live rubrics/bundles in `peer_review.py` |
| T34 | implemented | T33 + check-run / M | v2 identity/hash/limits/failures/raw result; failed/empty/untracked/incomplete scope fail closed; non-live path is read-only; live evidence-index stale gate |
| T35 | decided | deterministic owners / M | only setup candidate promotion retained; remaining candidate layers superseded |
| T36 | implemented | T35 + base gates / S | candidates remain non-authoritative; existing writers make canonical decisions |
| T37 | implemented | T31-T35 + base / M | assignment/bundle/evidence/source/scope/knowledge/report bindings reverified |
| T38 | decided | T35 / S | no expansion without measured net benefit; rejected classes explicitly superseded |
| T39 | implemented | dev lock + suites / M | `.github/workflows/ci.yml` Linux full and macOS/Windows focused matrices |
| T40 | decided | suite compatibility / S | formal `tests/` is allowed; existing CLI `--selftest` contract retained |
| T41 | implemented | T39 / S | `requirements-dev.lock`, exact optional pins, expanded touched-file ruff/mypy CI gates |
| T42 | implemented | Git + CI / M | `preflight.py` worktree or explicit base-to-HEAD diff check, sensitive categories and reviewed fingerprint; JSON-only bench upload |
| T43 | implemented | T22-T23 / S | ROADMAP now separates current scorer/metrics from limited fixture breadth and soft-only A/B |
| T44 | decided | template owners / S | generic prose deduplicator rejected; owner-specific manifest/parity/drift fixtures remain authoritative |
| T45 | implemented | closure audit / M | command/selftest/template/schema/context-budget wiring checks |
| T46 | implemented | T01-T53 / M | this owner/dependency/size/acceptance/status/evidence ledger; all 53 formal TODO items are closed with implementation or explicit decision evidence |
| T47 | implemented | existing fault suites / M | setup/parser/merge/conflict/Agent/stale/backend/closure negative fixtures in aggregate suite |
| T48 | implemented | normalizer bench base / S | existing precision/recall/provenance/schema/rejection/pointer metrics reverified |
| T49 | implemented | hygiene / S | warning-only untracked scratch-name detection; no content read or deletion |
| T50 | implemented | T49 / M | bounded allowed roots, dry-run default, explicit apply, symlink/identity recheck; onboarding retention |
| T51 | decided | consumer evidence / S | no adapter admitted without two real consumers and measured coupling cost |
| T52 | decided | coupling evidence / S | no module split admitted without touched-boundary measurable benefit |
| T53 | implemented | closure audit / M | `context-budgets.v1.json` plus missing-file, size, owner and duplicate-rule checks against the real contract in CI |
