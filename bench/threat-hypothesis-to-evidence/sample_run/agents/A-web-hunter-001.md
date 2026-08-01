# Agent A-web-hunter-001

- Role: web-hunter
- Assigned front: F-001
- Status: done

## New Threat Hypotheses

### NH-1
- Threat hypothesis: signed order replay may allow cross-user order read
- Asset/role/input: app.example user GET /api/order?id=...&sign=...
- Expected signal: victim order id returns to attacker when sign is reused
- Refutation/control: replay rejected when id/sign owner binding is changed
- Linked IS/C/E: IS-001
- Status: candidate
- Next action: Root records H-001 and runs guarded replay control
