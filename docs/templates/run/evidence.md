# Evidence Ledger

> Certainty: only `>= 0.8` may be reported confirmed, and a confirmed entry MUST
> carry a `Replicated / Control` field AND a saved `Artifacts` path under the run
> dir (check_run hard-fails a confirmed entry with no artifact, warns with no
> control). Full scale + meanings: `docs/cognition/README.md` "Evidence Confidence".

## E-001

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
- Artifacts: (conditional — required once this entry is confirmed; the saved file/dir that proves it, e.g. `evidence/<name>.html`. Save with `probe --save NAME --run runs/<dir>`.)
- Supports:
- Refutes:
- Unlocks: (conditional — the F-id this confirmed fact makes actionable, satisfying that front's precondition; the 组合利用 edge. Omit when it unlocks nothing.)
- Next:
