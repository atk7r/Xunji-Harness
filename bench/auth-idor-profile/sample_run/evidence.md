# Evidence Ledger

## E-001: Profile IDOR via user_id parameter
- Action: Compared own profile user_id=1001 with adjacent synthetic user_id=1002.
- Result: IDOR confirmed: profile response changed to another demo user's profile without a permission error.
- Certainty: 0.9
- Control: own user_id returned own profile; unauthenticated request returned login required.
- Replicated: yes
- Supports: H-001

## E-002: Login required without session
- Action: Requested profile endpoint without a session.
- Result: login required; this is expected access control behavior, not a finding.
- Certainty: 0.8
- Refutes: H-009
