# Evidence Ledger

> Certainty: use only the canonical scale: `1.0` direct/reproducible,
> `0.8` controlled/replayed confirmed, `0.5` suspected candidate, `0.3` clue/noise.
> Only `>= 0.8` may be reported confirmed, and a confirmed entry MUST carry a
> `Replicated / Control` field AND saved `Artifacts` paths under the run dir
> (check_run hard-fails a confirmed entry with no artifact, warns with no control).
> When `probe --save` produced a response body and `.replay.json`, list both
> concrete paths separately under `Artifacts`; `Replay` is adjudication prose,
> not an artifact-list substitute.
> Full meanings: `docs/cognition/README.md` "Evidence Confidence".

## E-xxx

- Maturity: phenomenon / candidate / finding
- Reportable: yes / no (confirmed vuln→report; coverage/verdict→summary)
- Superseded: (set when replaced by newer evidence)
- Time:
- Action:
- Source:
- Result:
- Caused by us: yes / no / unknown
- Alternative explanation:
- Certainty:
- Replicated / Control: (conditional — required once this entry is confirmed; the replay or baseline that rules out the benign explanation)
- Replay: (conditional — required when replay is DIVERGED or SKIPPED-PRIVACY-REDACTED; adjudication prose only: record downgrade or the fresh guarded replication/control, never claim a redacted placeholder was replayed)
- Artifacts: (conditional — required once this entry is confirmed; list each concrete saved file/dir on its own continuation line. For `probe --save`, list both `evidence/<name>.html` and `evidence/<name>.html.replay.json` separately; never move the sidecar path into `Replay` or compress it as suffix/pair prose.)
- Supports:
- Refutes:
- Unlocks: (conditional — the F-id this confirmed fact makes actionable, satisfying that front's precondition; the 组合利用 edge. Omit when it unlocks nothing.)
- Next:
