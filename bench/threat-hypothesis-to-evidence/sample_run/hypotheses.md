# Hypotheses

## H-001

- Claim: signed order replay may allow cross-user order read
- Status: rejected
- Front: F-001
- Threat hypothesis: signed order replay may allow cross-user order read
- Asset/role/input: app.example user GET /api/order?id=...&sign=...
- Expected signal: victim order id returns to attacker when sign is reused
- Refutation/control: replay rejected when id/sign owner binding is changed
- Next safe verification: guarded replay control
- Linked IS/C/E: IS-001, E-001
- Linked evidence: E-001
