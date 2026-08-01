# Evidence Ledger

## E-001: Static-only fixture observed
- Action: Recorded static-only fixture pages and headers.
- Result: static-only fixture; no dynamic parameters, upload, auth state, or API routes observed.
- Certainty: 0.8
- Replicated: yes
- Refutes: H-001

## E-002: Directory listing not present
- Action: Requested directory root.
- Result: no directory listing; server returned static index.
- Certainty: 0.8
- Refutes: H-002
