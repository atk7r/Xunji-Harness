# Evidence Ledger

## E-001: Path traversal in download parameter
- Action: Requested a fixture-owned marker file outside the intended downloads directory.
- Result: path traversal download confirmed; only fixture-owned marker content was read.
- Certainty: 1.0
- Control: public download returned public file; invalid traversal returned 404.
- Replicated: yes
- Supports: H-001

## E-002: Public download works
- Action: Requested a normal public fixture download.
- Result: public download returned expected static file.
- Certainty: 0.8
- Refutes: H-009
