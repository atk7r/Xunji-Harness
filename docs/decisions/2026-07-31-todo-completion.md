# TODO Completion Decisions — 2026-07-31

This record closes decision-gated items without describing rejected options as
implemented. `TODO.md` remains the only forward backlog. The per-item status and
evidence map is `review/records/2026-07-31-todo-completion/implementation-matrix.md`.

## Admitted implementations

- S1/S2/S3 share one `xunji.work-plan.v1` authority. `stage_policy.py` is a
  read-only deterministic projection: Root chooses the stage; it checks named
  inputs, exit facts, and lane shape. S1/S3 whole-plan limits cannot be hidden
  behind dependencies or `ROOT_DIRECT`; the assignment-free mode omits only
  synthetic Reviewer topology, not stage effect validation. S2 only rejects
  simultaneously ready same-asset target
  lanes, while the work-plan DAG owns valid serialization. `workers.py` supplies
  stage-specific lane defaults, while `work_plan.py` binds
  source/asset/knowledge/constraint changes into the plan fingerprint. Exact
  pre-expansion fingerprints remain a read-only compatibility path for already
  committed plans.
- Offline analysis uses `inspect_artifact.py`, existing JS inventory and range/
  chunk support. WebSocket work stops after one guarded opening handshake and
  reuses `probe.send`; it does not expose frames or a second network stack.
- Scheduler parallelism remains capacity bounded. The recorded Root-direct/
  serial/parallel fixture shows speed/coverage benefit but exceeds the declared
  merge-cost cap, so parallelism remains a soft recommendation rather than a new
  hard gate.
- Native runtime messages are admitted for status, clarification, follow-up
  within frozen authority, and a request to return. They do not change assignment
  authority and cannot become return, evidence, review, cancellation, or merge.
- Peer review now freezes one of `live-run`, `maintenance-diff`, `plan`, or
  `docs`. Result/receipt v2 records scope kind, reviewer identity, reviewed hash,
  context limits, backend failures, raw output, and Root disposition remains
  separate. A failed/empty Git diff, untracked non-ignored path, empty plan/docs
  input, or incomplete non-live context cannot produce PASS, and the hash never
  silently covers content withheld from the reviewer. Ordinary non-live review
  is in-memory/read-only;
  only explicit `--bundle-only` writes its ignored diagnostic artifact. Only
  `live-run` may refresh evidence sidecars or append a closure-facing
  ReviewReceipt.
- `canonical_records.py` owns typed/source-span constraints, review-ledger, and
  Agent-result records while aggregating the existing frontier/status owner
  (`run_model.py`) and evidence owner (`evidence_parse.py`). Context, saturation,
  input-shape, and `check_run` consume the shared constraint/review records.
  Historical case variants, duplicate/oversize/missing-Front constraints remain
  bounded and readable with warnings. Ordinary `PR-*` prose outside the actual
  review finding ledger is not reclassified as a native finding, but is surfaced
  as a compatibility warning when a native ledger is also present. The exact
  pre-ledger `PR-nnn — BLOCKER|WARN` shape remains a typed, disposition-gated
  finding; only headings with no explicit severity are warning-only.
- CI, pinned optional developer checks, read-only preflight, warning-only root
  scratch discovery, dry-run-first TTL cleanup, closure wiring checks, and
  always-loaded context budgets are admitted engineering controls. Metric totals
  only consume attributable event types, duplicate requests bind method plus
  asset/host plus URL/path and count extra occurrences, closure reopen is
  lower-is-better, and missing context inputs/duplicate owner rules fail with
  bounded diagnostics. CI passes an explicit committed base-to-HEAD range to
  preflight so a clean checkout does not turn the diff gate into a no-op. Push
  runs use the event's `before` commit (empty-tree on the first push), not
  `HEAD^`, so multi-commit pushes are fully covered. Stage-policy lifecycle owner
  failures remain unknown/fail-closed and expose stable owner diagnostics.

## Evaluated and not admitted

### Additional setup adapters

Markdown and ordinary JSON have deterministic token/ref inventory, provenance,
mutation, redaction, and benchmark fixtures. HTML, PDF, DOCX, plain text, and OCR
are not admitted as stable normalizers:

- HTML needs selector/DOM source-span provenance.
- PDF needs page/object/span provenance and deterministic extraction fixtures.
- DOCX needs relationship/part/span provenance and zip-bomb/TOCTOU fixtures.
- Plain text needs byte-offset provenance and an ambiguity policy.
- OCR needs image/page coordinates, engine/version identity, confidence handling,
  and a privacy-safe local extraction boundary.

Current code detects these formats and returns `normalizer_required`; it does not
silently parse them. This is the accepted decision until a format-specific
benchmark demonstrates value. The input matrix already covers host/URL/IDNA/
userinfo/port, JSON/Markdown, injection, path/symlink, source mutation, size, and
context limits; unsupported formats fail before pointer or Cron effects.

### Intel URL

`--intel-url` stays disabled and has no setup-metadata network fallback. If an
operator later authorizes it, it must be a separate target/read capability with
per-redirect DNS/IP, scope, privacy, credential, timeout, body, MIME, proxy,
guard, and recorder checks. It is not admitted merely because a source document
contains a URL.

### Candidate-structure expansion

Only setup normalization is admitted. Agent output already has its assignment/
front/assets/artifact schema and settlement owner; review already has a frozen
bundle/receipt; evidence, JS, scope, knowledge, report, retrospective, and hints
already have deterministic owners. Adding another AI candidate layer to those
surfaces has no measured net benefit and would expand model egress and rollback
surface. They are therefore superseded, not pending. A future proposal must name
its candidate schema, source hash/ref, mechanical validator, canonical writer,
rollback, and a benchmark that beats the current deterministic/manual path.

### Descriptor-relative filesystem rewrite

The local threat model is one trusted operator with fallible/coincident local
processes, not a hostile tenant. Existing protected paths use canonical
containment, no-follow/lstat identity, atomic replacement, directory fsync,
single writers, CAS, and crash fixtures. A repository-wide fd-relative rewrite
would add substantial macOS/Linux/Windows divergence without a reproduced
ancestor-swap failure. It is not admitted. Reopen only with a reproducible race
and a cross-platform fault/soak result.

### Repository adapters and module splitting

No new repository abstraction has two demonstrated consumers, and no touched
large module has a measured coupling failure that a split fixes. Both proposals
are superseded for this delivery. Existing public CLIs, errors, receipts, and
verdicts remain stable; future splits must preserve them and prove a measurable
benefit.

### Generic generated-excerpt framework

A repository-wide prose deduplicator is not admitted: identical safety language
can be either required reinforcement or an ownership bug. Owner-specific checks
remain authoritative: Agent instruction manifest/composition, driver-doc
conformance, template parity, command references, and closure wiring. New aliases
must add an owner-specific fixture rather than a generic copied excerpt.

## Maintenance worktree boundary

Repository maintenance may use effect-disjoint worktrees; this delivery itself
does. Worktrees are isolation for source edits, not engagement state. Live
`runs/<dir>` evidence, pointer activation, receipts, journals, review
dispositions, and closure stay in one canonical store with their existing
single-writer/CAS contracts.

## Completion semantics

One cycle ends after every planned execution has authentic return/failure,
dependent review, Root disposition, and typed `cycle_end`. An engagement ends
only in S3 when `check_run`, current independent review, report/evidence parity,
zero Agent/merge/review debt, retrospective, and terminal journal/Cron facts all
pass. Otherwise the next action is replan, stage transition, or an exact blocker;
the AI chooses routine strategy inside those gates, but cannot redefine them.
