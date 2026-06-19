---
id: magtech-caibian
product: 玛格泰克 Magtech 期刊采编投稿系统
vendor: 北京玛格泰克 Magtech
aliases: [magtech, 玛格泰克, 采编, 期刊采编, journalx]
category: journal-submission-system
last_reviewed: 2026-06-20
maturity: seed
signatures: ["玛格泰克", "/userinfo/unauth/", "sm4-1.0.js", "newtoken", "journalx"]
---

<!-- PUBLIC grounding tier. Recognition + weak-point anchors only; no payloads. -->

## Recognition (identification only)

- Signature: editor/author/reviewer login portals (often paired `*editor` / `*user` vhosts) carrying
  the string `玛格泰克`; login POSTs to `/sso`; client JS `crypto/sm4-1.0.js`, `encdec/encdec.js`,
  `newToken/newToken.js`; an unauth namespace `/userinfo/unauth/...` (regist/editemail/emailOnly);
  session cookie `journalx.session.id`.
- Distinguishing notes: a multi-tenant platform — one backend serves many journal vhosts, so a flaw on
  one instance typically reproduces across the cluster.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: unauthenticated-access namespace
  - Affected: `/userinfo/unauth/*` (self-registration `regist/doRegist`, `emailOnly`).
  - Mechanism: pre-auth endpoints that process attacker input (registration, email checks).
  - Reference: CNVD "北京玛格泰克 期刊稿件远程处理系统 未授权访问"
  - source: external-cited
- Anchor: role mass-assignment / over-binding in self-registration (candidate)
  - Affected: `doRegist` carries a client `reviewerRole` field (UI hard-codes "false").
  - Mechanism: if the server binds the client-supplied role, an anonymous user could self-provision a
    privileged reviewer account (reads others' manuscripts). UNVERIFIED — needs an A/B registration.
  - Reference: run-observation (ujs_20260619 E-019/E-020)
  - source: run-observation
- Anchor: client-side crypto is transport obfuscation, not a boundary
  - Affected: `emailStr`/`password` are SM4-ECB encrypted client-side; the key is handed in a
    non-HttpOnly cookie `webmSecurityKey` by `GET /newSecurityKey`.
  - Mechanism: the key is client-readable → requests are fully reconstructable; SM4 does not protect
    against injection/abuse of the decrypted value.
  - Reference: run-observation (ujs_20260619 E-020)
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: confirm `玛格泰克` + `/userinfo/unauth/*` reachable; for the role mass-assignment,
  the proof is the granted role on a registered account.
- Hard stops: registration creates a persistent account (+ editor emails) = integrity change →
  author-and-handoff, not auto-run; never read others' real manuscripts (prove the role, stop).

## False-Positive / Confounders

- Other 采编 platforms (勤云/三才) differ; the `玛格泰克` string + `/sso` + sm4-1.0.js are the tell.

## References

- https://www.cnvd.org.cn/ (search "玛格泰克 / 期刊采编 / 稿件远程处理")
