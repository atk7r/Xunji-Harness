# Evidence Ledger

## E-001: Tenant record IDOR via record_id
- Action: Replayed a synthetic tenant A request with tenant B record_id.
- Result: IDOR confirmed: tenant B record body was returned under tenant A session.
- Certainty: 1.0
- Control: nonexistent record_id returned 404; tenant-owned record_id returned only own tenant.
- Replicated: yes
- Supports: H-001

## E-002: Empty list for archived records
- Action: Requested archived records list.
- Result: empty list; no unauthorized object returned.
- Certainty: 0.8
- Refutes: H-002
