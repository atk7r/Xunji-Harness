# Peer Review Panel — 2026-07-07-loop-engineering-context

_backend: panel:arkcli · 2026-07-07T00:40Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli_
_brain: codex_
_bundle_hash: 057737ed54524e2f4531ac8b8edb0760cd771ed4_
_evidence_index_hash: 467c0301a13756f0d3c820229891f694f20ab7ca_

## Findings
- [WARN] PR-001 report.md Changed Files list omits tools/saturation.py, which the maintenance diff actually modifies to add the front_saturation helper consumed by loop_state.py | Evidence: evidence/diff.patch (E-001) diff --git a/tools/saturation.py, report.md##Changed Files | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The changed-files ledger is a subset of the actual diff; this undermines scope transparency and could cause reviewers to miss a dependency change that affects front saturation scoring.
- [WARN] PR-002 E-005 loop_state selftests confirm happy-path behavior but do not exercise failure paths or dependency-tool faults (coverage_matrix / workers / graph / malformed evidence). | Evidence: evidence/loop_state_selftest.txt (E-005), evidence/loop_bootstrap_selftest.txt (E-005) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] loop_state.py is a derived-state orchestrator that refreshes multiple subsystems; without failure-path coverage, regressions that silently omit gates or corrupt state/ caches are likely.
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: turity="artifact" since it just represents the change.

2. **WARN - Truncated evidence** - 15926 of likely 40000+ chars in E-001's diff excerpt means we cannot fully verify the implementation. The new 519-line tools/loop_state.py is only partially visible. Specifically:
   - The no-progress cycle counter logic
   - The Coda convergence logic
   - Whether the code actually stays advisory as claimed
   - The complete fan-out required logic

3. **WARN - E-006 "real recorded-run loop_state output" -; glm-5.2: parse error; output tail: s
- Race conditions if multiple processes write state/

**Issue 10: The `saturation.py` changes add a `front_saturation` public helper.** This is called by `loop_state.py`. The selftest confirms it works. The function reads `frontier.md` and returns saturation records. This seems clean.

**Issue 11: The `selftest_all.py` change just adds the `loop_state` suite to the list.** Simple and correct.

**Issue 12: Important - the report says "Does not recreate an orchestrator or let a tool choose/close | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- (none)

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: turity="artifact" since it just represents the change.

2. **WARN - Truncated evidence** - 15926 of likely 40000+ chars in E-001's diff excerpt means we cannot fully verify the implementation. The new 519-line tools/loop_state.py is only partially visible. Specifically:
   - The no-progress cycle counter logic
   - The Coda convergence logic
   - Whether the code actually stays advisory as claimed
   - The complete fan-out required logic

3. **WARN - E-006 "real recorded-run loop_state output" -
- [arkcli] glm-5.2: parse error; output tail: s
- Race conditions if multiple processes write state/

**Issue 10: The `saturation.py` changes add a `front_saturation` public helper.** This is called by `loop_state.py`. The selftest confirms it works. The function reads `frontier.md` and returns saturation records. This seems clean.

**Issue 11: The `selftest_all.py` change just adds the `loop_state` suite to the list.** Simple and correct.

**Issue 12: Important - the report says "Does not recreate an orchestrator or let a tool choose/close
