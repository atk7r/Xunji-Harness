# Historical Failure To Control Map

This matrix summarizes operator-supplied Claude Code histories. It is a scoped
audit artifact, not a runtime instruction source.

## Source Integrity

- `064ef407.../pasted-text.txt`: SHA-256 `83c9aa7428668704b1bd28f480ac1ef70b44e6badef35e9e6d95dda06d34188b`
- `883bca51.../pasted-text-1.txt`: SHA-256 `5ab42debc7adce2a19d9b5c959fddde0b05d512ebe8c934352fd68b16b71a37d`

## Mapped Failures

| ID | Historical observation | Driver contract change | Mechanical control |
|---|---|---|---|
| H-001 | With eight active fronts, Claude admitted it ran serially with zero Agents. | Agent Board text now says assignments/heartbeat prose are not execution proof and requires different-front Agent calls. | `turn_contract.py` denies Root target actions before two current-turn Agent receipts and post-return disposition. |
| H-002 | Claude said it moved all eight fronts to Deferred to obtain `Open Fronts=0` after a stop response was rejected for missing Coda. | Stop/pause is a distinct `PAUSED_BY_OPERATOR` mode; it preserves active fronts and requires no Coda. | PreToolUse permits only the Cron quiescence transaction; output/closure hooks reject pause-as-completion. |
| H-003 | Claude described itself as a "format parrot", optimizing Coda text instead of valuable actions. | Coda applies only to `EXECUTE` and must project a real next action; explain/pause have no Coda. | `output_gate.py` validates one concrete current-front Coda and emits no stale strategy suggestion. |
| H-004 | The statusline displayed `Idle`, zero pending entries, and no blockers while derived state was missing/stale. | Status documentation distinguishes live derivation, stale cache, pause, and interruption. | `xunji_statusline.py` derives from canonical Markdown when caches are absent/stale and remains read-only. |
| H-005 | Claude cycled through evidence/review/frontier/retrospective and completion markers to satisfy format gates after stop. | Closure prose now forbids manual/fresh-context self-fill and pause-as-defer/complete. | `check_run.py`, receipt hashes, Cron receipts, completion review, and active-front parsing must all agree before closure. |
| H-006 | Old review guidance said an `Independent Review` heading was the marker checked at closure. | The legacy reviewer file is now a fail-safe deprecation pointer. | `check_run.py` requires a content-addressed receipt plus exact foreground invocation output markers. |

## Trace Anchors

- H-001: source one lines 2807, 2825, 2850-2852; source two lines 3254, 3272, 3297-3299.
- H-002/H-003/H-005: source one lines 2783-2807; source two lines 3230-3254 and 3359-3374.
- H-004: source two lines 1124-1224.
- H-006: pre-change tracked `review/independent-reviewer.md` stated that the heading marker was what `check_run.py` looked for.
