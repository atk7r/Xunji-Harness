Now I have all the information I need. Let me compile the fresh-context review.

---

## Claude Fresh-Context Review — record_evidence closure

- **Verdict:** WARN
- **Findings:**

  - **WARN — Selftest evidence is partial; review overclaims full coverage**
    `evidence/selftest_all.txt` shows only 4 suites were run (`--only check_run,peer_review,timestamp_gate,record_evidence`). The `closure_scan.txt` claims `all_selftests 42 not_registered 0` but that's a static count from the `SUITES` list, not a live execution. `report.md` says "4 passed, 0 failed" — true for the 4 run, but the diff adds `record_evidence` to a 42‑entry battery and only 1/10th of it was exercised. A full-battery run before declaring closure would catch import-order side-effects, module shadowing (the tool imports `evidence_parse`), or temp‑file contention.

  - **WARN — `--trust` defaults to `operator-reviewed`, misleading for web‑research**
    `record_evidence.py:205`: `--trust` default is `"operator-reviewed"`. Every entry emitted by the tool — including web‑research entries where `--source web-research` — gets `Trust: operator-reviewed`. Web research is an *unverified external source*; labeling it operator‑reviewed before the operator has reviewed it weakens the trust signal. The `evidence_parse.py:152` inference logic happens to assign the same label for non‑target sources, so this is consistent (not a regression), but the tool has a chance to be better than the inference fallback — it knows the source at write time. Consider: source `"web-research"` → trust `"untrusted"`; source `"target-*"` → trust `"untrusted"`; everything else → `"operator-reviewed"`.

  - **WARN — Manual‑write fallback removed from `web-research/SKILL.md` with no replacement**
    `web-research/SKILL.md` diff removes the fallback block:
    ```markdown
    If `record_evidence.py` is not available, write directly to `evidence.md` with: ...
    ```
    The original fallback was weak (free‑form prose, no E‑id, no canonical fields), but it was *something* — a protocol‑compliant operator could still record evidence when the tool wasn't present. Now the tool IS present, so this is correct in theory, but if the tool ever breaks (Python path issue, missing `evidence.md`, write‑permission failure), the skill offers no documented recovery path. A one‑line "if the tool fails, fall back to `record_evidence.py --dry-run` and hand‑write the block" would preserve the safety margin without weakening the mechanical‑first discipline.

  - **INFO — `--alternative-explanation` default is web‑research‑specific but applied universally**
    `record_evidence.py:217-220`: the default alt‑explanation is `"Recorded source may be stale, wrong, incomplete, or not applicable until verified against current target artifacts."` This is exactly right for web‑research entries. For a `target-session-artifact` entry with `certainty=0.8` and `artifacts=evidence/proof.html`, the same boilerplate is misleading — the source IS a current target artifact. The caller can override it, but a source‑sensitive default would be cleaner. Not a blocker.

  - **INFO — Tool is append‑only; no update/edit path**
    `append_entry()` always appends (or replaces the template on first write). There's no mechanism to update an existing E‑id entry after the fact (e.g., promote a `phenomenon` to `candidate` after cross‑validation). The `evidence.md` file is plain Markdown and can be hand‑edited, but the mechanical path is one‑directional. This is a deliberate simplicity choice, not a bug, but it means the "recording closure" is append‑closure, not lifecycle‑closure.

  **No findings on the following (verified clean):**

  - **E‑id numbering**: `_next_id()` at line 139 scans all `## E-\d+` headers and increments from max+1. Template replacement at line 146–164 correctly detects the single stock `E-001` block with all 8 required field markers and re‑uses the same ID. Tested in selftest (lines 382–384).
  - **Conservative defaults**: Default `phenomenon`/`0.3` is enforced at `argparse` level (lines 212–213, `default=`). Cross‑validation pathway (`--maturity candidate --certainty 0.5`) is documented in both skills and validated in selftest (line 394–395).
  - **Web‑research promotion gate**: `_validate_args` at line 118–122 hard‑blocks `source=web-research` combined with `certainty >= 0.8` or `maturity=finding`. Selftest at line 398–399 confirms exit code 2 for this case.
  - **Certainty↔maturity consistency**: Lines 109–116 enforce bidirectional consistency (`>=0.8` ⇔ `finding`, `< 0.8` ⇔ not‑`finding`).
  - **Confirmed‑evidence artifact/control gate**: Line 114–116 requires `--artifacts` and `--replicated-control` when certainty ≥ 0.8.
  - **Artifact scoping**: The tool emits `Artifacts: none` for web‑research entries. Selftest at line 384 confirms the parser (`evidence_parse.py`) correctly scopes this field and doesn't mis‑parse URLs in other fields as missing file artifacts.
  - **Atomic write**: Lines 268–270 use tempfile + `os.Path.replace()` — safe against partial writes.
  - **Docs accuracy**: Both skill files reference the real, existing `tools/record_evidence.py`. Default behavior (`phenomenon`/`0.3`, `--maturity candidate --certainty 0.5` after cross‑validation) is documented identically in both skills. The `xunji-web-research-sync` doc correctly distinguishes evidence recording from `decisions.md` recording (line 85: "Write decisions.md only when the research changed a run decision").
  - **No weakening of evidence discipline**: The change removes a weak prose‑only fallback and replaces it with a mechanical tool that enforces canonical fields, correct E‑id numbering, conservative defaults, and a hard gate against direct web‑research‑to‑finding promotion. Evidence discipline is *strengthened*, not weakened.
  - **selftest_all.py integration**: The new `record_evidence` entry at line 66 is correctly placed adjacent to `timestamp_gate` (its upstream dependency in the web‑research pipeline), follows the same `(name, argv, note)` tuple format, and would be exercised by a full `python tools/selftest_all.py` run.

- **Residual risk / limitations**

  1. **No integration test with a real run directory**: The selftest uses `tempfile.mkdtemp()` with synthetic `evidence.md` content. A real run's `evidence.md` might have edge cases (UTF‑8 BOM, Windows CRLF, large 100+ entry files, entries with trailing `E-xxx` in prose). The tool uses `errors="replace"` on reads which would silently mangle encoding errors.
  2. **No `--date` format validation**: The tool accepts any string for `--date`. A malformed date (e.g., `"yesterday"`) would be written into `Time:` verbatim. The skill docs recommend `$(python tools/timestamp_gate.py --iso)` but the tool doesn't enforce it.
  3. **No cross‑reference validation**: `--supports` and `--refutes` accept arbitrary strings but the tool never verifies those E‑ids/H‑ids/F‑ids exist in the current ledger. An entry can reference a non‑existent E‑id and the tool won't warn.
  4. **Single‑block‑only template detection**: `_template_placeholder_span()` at line 147 requires exactly one `## E-\d+` block. If someone writes two template stubs (unlikely but possible), the tool falls through to append‑mode and creates `E-003`, leaving stale templates. This is conservative (no data loss) but means the template‑replace path is fragile to accidental edits.
  5. **The peer review panel was partial**: PR‑001 and PR‑002 confirm arkcli backends (kimi‑k2.7‑code, minimax‑m3) failed; only `glm‑5.2` produced usable output. The Claude fresh‑context review fills this gap but the heterogeneous coverage isn't as broad as intended.
