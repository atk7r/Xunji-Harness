# Surface

## Input Shape Catalog

### IS-001

- URL pattern: POST /api/order/confirm
- Source JS/artifact: evidence/order.js
- Client-controlled params: orderId, uid, sign, nonce
- Client-side signature/token/nonce logic: md5(uid + orderId + nonce)
- State transition: order pending -> confirmed
- Linked threat hypothesis: H-001
