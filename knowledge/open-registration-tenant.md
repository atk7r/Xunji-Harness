---
id: open-registration-tenant
product: Self-registration and tenant isolation weakness recognition
vendor: cross-product
aliases: [open registration, self-registration, tenant bypass, tenant isolation, 开放注册, 租户隔离, multi-tenant]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["/register", "/signup", "/account/register", "customerid", "tenantid", "companyid", "create account"]
---

<!--
PUBLIC grounding tier. Generic recognition of open self-registration and
multi-tenant isolation weaknesses — cross-product. Source: scshr run-observation
(E-005 open registration, E-012 unvalidated CustomerID), hamastar run
(SIMagic IDOR post-registration).
-->

## Recognition (identification only)

- Signature (registration endpoint): `/register`, `/signup`, `/create-account`,
  `/Identity/Account/Register` (ASP.NET Core Identity), `/user/register`,
  `/member/register`. A 200 with a registration form (not a login form).
- Signature (tenant fields): form fields named `CustomerID`, `CustomerId`,
  `TenantId`, `CompanyID`, `OrgID`, `ClientID`, `orgId`, `tenant` — these
  are multi-tenant isolation keys. If present in a registration form, they
  are critical to validate server-side.
- Signature (weak validation): registration form lacks `required`, `data-val-required`,
  `pattern` attributes on tenant-isolation fields. The field is free-text input
  rather than a dropdown populated from a verified tenant list.
- Signature (mail confirmation gates): pages with `RequireConfirmedAccount`,
  "please check your email", "confirmation link sent" text. These MAY or
  may not actually enforce email verification — verify, do not assume.
- Distinguishing notes: a registration page existing is not itself a vulnerability
  (many SaaS products have open registration by design). The weakness is in
  the combination: registration without invite/verification + tenant field
  accepted as user input + weak/no server-side tenant validation.

## Weak-Point Anchors

- Anchor: tenant-isolation key accepted from untrusted client input
  - Affected: multi-tenant SaaS where the registration form includes a tenant
    identifier field that is not validated server-side.
  - Mechanism: the tenant ID determines data isolation (all users in tenant A
    share data, isolated from tenant B). If a registrant can freely set this
    value, they can join any tenant's data space — bypassing the multi-tenant
    security model. The tell is a free-text CustomerID/TenantID field with no
    server-side validation.
  - Reference: CWE-639 (Authorization Bypass Through User-Controlled Key)
  - source: run-observation (scshr E-005/E-012)
- Anchor: open registration + IDOR on user-owned objects → horizontal escalation
  - Affected: self-service portals where registration grants access to
    endpoints with incrementable object IDs (payslip, profile, document).
  - Mechanism: after self-registering and logging in, the user can enumerate
    object IDs on post-auth endpoints to access data belonging to other users
    in the same tenant — or across tenants if the tenant filter is also missing.
  - Reference: CWE-639
  - source: run-observation (scshr + hamastar SimMAGIC IDOR)
- Anchor: email confirmation gate not enforced on sensitive endpoints
  - Affected: apps where `RequireConfirmedAccount` is set but only enforced
    on the login page, not on API endpoints or password-reset flows.
  - Mechanism: the unconfirmed account may still be able to call authenticated
    API endpoints (the token is issued before email confirmation) or to
    trigger password-reset flows that bypass confirmation.
  - Reference: CWE-287 (Improper Authentication)
  - source: driver-reasoning

## Verification Principle

- Existence proof: a GET on the registration path returns the form. A POST
  with throwaway data creates an account (or returns a validation error that
  reveals what IS validated). If the tenant field accepts arbitrary values,
  that is the existence proof of missing validation.
- Hard stops: create ONE throwaway account to prove registration persists, then
  stop. Do NOT create multiple accounts. Do NOT use the created account to
  access real tenant data — record the potential IDOR surface for operator
  decision. Operator must delete the test account.

## False-Positive / Confounders

- Some SaaS products intentionally allow self-registration (freemium model) —
  the finding is in missing tenant validation, not registration itself.
- `CustomerID` as a dropdown populated from a verified list = correct
  implementation; not a finding.
- Registration that requires an invitation code or admin approval is correctly
  gated — the registration page existing is not the vulnerability.
- Multi-tenant isolation may be enforced by subdomain rather than a form field
  (e.g., `tenant.product.com`) — test the subdomain-level isolation, not the
  form field.

## References

- CWE-639: Authorization Bypass Through User-Controlled Key
- CWE-287: Improper Authentication
- OWASP: Multi-Tenant Application Security
- This repo's run-observation: scshr E-005 (open registration + unvalidated
  CustomerID), E-012 (CustomerID optional free text); hamastar SimMAGIC IDOR
- Related: [[auth-protocol-surface]] [[security-header-weaknesses]]
