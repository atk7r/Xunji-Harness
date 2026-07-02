# Evidence Ledger

## E-001: Upload path control for harmless proof object
- Action: Submitted a harmless proof object with a fixture path parameter.
- Result: upload path control confirmed: object appeared under the chosen synthetic subdirectory.
- Certainty: 0.8
- Control: randomized name mode ignored caller path; path control mode honored caller path.
- Replicated: yes
- Cleanup: proof object removed.
- Supports: H-001

## E-002: Randomized name mode
- Action: Uploaded through the safe endpoint.
- Result: randomized name used and caller path ignored.
- Certainty: 0.8
- Refutes: H-009
