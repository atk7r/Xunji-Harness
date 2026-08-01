# Peer Review — 2026-07-09-retro-closure-final-review

_backend: claude:code-cli · 2026-07-08T18:14Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: claude:code-cli_
_brain: codex_
_bundle_hash: 3502053bd91bfeb946c8463841801c532e911c1b_
_evidence_index_hash: c687eba1b25af3861e8e146121b21d11eeb95cbe_

## Findings
- (none)

## Blind-spot check
- **Anti-lump heuristic boundary**: `classify_hosts.py:948` uses `< 200` characters after HTML tag stripping as the STUB_PAGE threshold. A thin API gateway response or minimal SPA shell (e.g., `<html><body><div id="root"></div><script src="app.js"></script></body></html>` = ~80 chars after stripping) could be misclassified as STUB_PAGE. The `_should_try_common_subpaths` check before flagging, plus `verdict_required: true`, provides a safety net — but only if the driver reads the VERDICT REQUIRED output (see W-4 above).
- **`_completion_markers` scope is `decisions.md`-only**: `loop_state.py:1454-1456` searches only `decisions.md` for `GHOST_COMPLETE` / `NORMAL_COMPLETE`. This is architecturally correct (decisions.md is the canonical decision log), but if a marker is accidentally written to `frontier.md` or `report.md`, it will be invisible to the completion machinery. The template at `loop_prompt.md:84-88` correctly says to put it in decisions.md, so this is a documentation-enforced contract.
- **`--value-json` flag naming carries product-specific semantics**: `probe.py:1680` — the flag wraps JSON in `{"Value":"<escaped>"}`, named after the AIS HR product's API convention. For a generic HTTP probe tool, this product-specific behavior is somewhat surprising. The flag help text ("wrap JSON as an escaped string Value field") and the knowledge entry documentation (`knowledge/soarcloud-ais-hr.md:696-698`) clarify this, but a future maintainer unfamiliar with the AIS HR product might misunderstand this flag's purpose.
- **Agent Board gate now requires `heartbeat_count > 0`**: `run_gate.py:88-96` — the new gate requires at least 2 agents to have `heartbeat_count > 0` OR a status in `{running, working, done, merged, blocked, failed, abandoned}`. The `heartbeat_count` requirement means a freshly spawned agent that hasn't yet recorded a heartbeat will fail this check even though it was correctly assigned. The error message (line 105) tells the driver to run `workers.py heartbeat --status running`, but there's a race condition: between assignment and first heartbeat, the gate will block. The selftest at line 182 confirms this with the correct passing case (`heartbeat_count: 1`). The regression risk is low because the budget reason escape hatch (`decisions.md:186-191`) provides a manual override.
- **`peer_review.py` selftest confirms the `_strip_template_review_placeholders` dependency is live**: `peer_review.py:1695-1702` — the selftest exercises `review_panel(…, into_run=True)` with `NEEDS_DRIVER` verdict, which calls `_append_manual_driver_template`, which calls `_strip_template_review_placeholders`. Since 53/53 pass, this dependency is confirmed satisfied. No missing-function risk.

## Context-limit notes
- I could not verify the `_strip_template_review_placeholders` function definition directly (Grep/Glob denied) but confirmed its existence through the selftest exercising the exact code path.
- I read the full 2081-line active diff and all evidence artifacts. The 1.5MB staged-diff.txt contains `review/records/**` audit artifacts that I did not review byte-by-byte; the report correctly notes these are historical evidence trail, not active behavior changes.
- The CNVD/Taiwan-specific product knowledge (Soar Cloud AIS HR, ZUSO ART advisories ZA-2025-04..09) is outside my full context. I rely on the `knowledge/soarcloud-ais-hr.md` entry as authoritative and do not independently verify the CVE mappings.
- The Chinese-language hook messages and anti-drift binding rules are reviewed for structural soundness (what they trigger, how they gate) but not for idiomatic Chinese correctness.