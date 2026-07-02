# Evidence Ledger

## E-001: SQL injection indicated by controlled database error
- Action: Sent a harmless syntax probe to a local fixture query parameter.
- Result: SQL injection confirmed by database error only on the altered input.
- Certainty: 0.8
- Control: baseline input returned normal page; altered input returned database error.
- Replicated: yes
- Supports: H-001

## E-002: Generic 500 on health endpoint
- Action: Observed one generic 500 from /health.
- Result: generic 500 without input correlation.
- Certainty: 0.5
- Note: environment instability, not a confirmed vulnerability.
