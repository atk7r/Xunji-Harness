# Evidence Ledger

## E-001: NoSQL injection in JSON filter
- Action: Compared normal search filter with a synthetic altered operator object.
- Result: NoSQL injection confirmed by differential result count and stable response shape.
- Certainty: 0.9
- Control: normal search returned one row; altered filter returned all fixture rows.
- Replicated: yes
- Supports: H-001

## E-002: Normal search endpoint present
- Action: Baseline search request.
- Result: normal search behavior only.
- Certainty: 0.8
- Refutes: H-009
