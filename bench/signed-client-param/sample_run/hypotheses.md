# Hypotheses

## H-001

- Threat hypothesis: client-side signature may be replayable with a different owner id
- Asset/role/input: POST /api/order/confirm uid/orderId/sign/nonce
- Expected signal: tampered owner id accepted with replayed sign
- Refutation/control: tampered owner id rejected
- Linked IS/C/E: IS-001, E-001
