# Peer Review — hamastar_20260615

_backend: codex · 2026-06-17T00:15Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: BLOCKER

_backend: codex_  

## Findings
- [BLOCKER] Final report omits the run’s highest-impact confirmed finding: SimMAGIC self-registration leading to full license-management access/IDOR | Evidence: evidence.md:266, evidence.md:271, evidence.md:283, evidence.md:288, evidence.md:298, evidence.md:300 | Why: E-016/E-017 are certainty 1.0 with saved artifacts, but the report’s confirmed findings only list four lower-impact items at report.md:31-60.
- [BLOCKER] Report directly contradicts later evidence by saying SimMAGIC/product platforms were untested due to CDN blocking | Evidence: report.md:74, report.md:82, evidence.md:271, evidence.md:274, evidence.md:288 | Why: The evidence says SimMAGIC HTTPS was reachable, registration/login succeeded, and authenticated license data was accessed.
- [WARN] Not every evidence item with certainty >=0.8 is carried into confirmed findings | Evidence: evidence.json:3-15, report.md:31-60 | Why: evidence.json marks E-002, E-013, E-014, E-015, E-016, E-017 confirmed, but the report omits most of them from confirmed findings.
- [WARN] E-002 open redirect should not be confirmed at 0.8 | Evidence: evidence.md:24, evidence.md:26, evidence.md:27 | Why: Only ReturnUrl reflection in a login form was observed; the ledger itself says server-side validation after POST could still prevent the redirect.
- [WARN] Report’s evidence table has stale/high certainties for downgraded or negative/environment findings | Evidence: report.md:94, report.md:95, report.md:98, evidence.md:100, evidence.md:114, evidence.md:166 | Why: E-006/E-007/E-010 are reported as 1.0/0.8/0.8 in the table, while the evidence ledger downgraded them to 0.5/0.3/0.3.
- [WARN] E-015 overstates unauthenticated API access | Evidence: evidence.md:256, evidence.md:258, evidence.md:259 | Why: Empty arrays from unauthenticated POSTs support endpoint enumeration and silent auth behavior, not confirmed unauthorized access to department/role/people data.
- [WARN] E-017 overstates destructive capability | Evidence: evidence.md:292, evidence.md:293, evidence.md:298, evidence.md:300 | Why: Viewing delete links/pages is not the same as confirmed ability to delete; the read/edit IDOR is strong, but destructive operations should be phrased as exposed UI/endpoints unless safely verified.
- [WARN] Coverage/report summary silently drops reachable high-value surfaces | Evidence: surface_recon.md:7, coverage.json:3, coverage.json:48, coverage.json:56, coverage.json:204, coverage.json:276, report.md:25, report.md:27 | Why: The ledger covers 128 assets and 68 reachable/examined entries, including Jenkins and additional admin/login surfaces, but the report compresses this to “10 deep tested” and “30+ low priority untested” without explaining what was not probed.
- [WARN] “Common vuln sweep complete across reachable assets” is too broad | Evidence: frontier.md:91, frontier.md:94, frontier.md:96, frontier.md:97 | Why: The same section admits customer government sites were not exhaustively probed, so “complete across reachable assets” overclaims depth.

## Blind-spot check
- The author appears to have preserved an older “CDN blocked/product untested” narrative after SimMAGIC was later reached and exploited.
- The critical path was not RCE/getshell; it was business-logic access control after open registration.
- Evidence-gate discipline was applied inconsistently: some negative/timeout findings were downgraded in evidence.md but not in report.md.
- Empty unauthenticated API responses were treated too generously.
- Delete capability was inferred from reachable UI/routes rather than proven action.
- Reachable but lower-prioritized admin surfaces, Jenkins, and product-adjacent hosts were not reflected clearly in the final risk picture.

## Context-limit notes
- Some Chinese text rendered as mojibake in the terminal, but key Traditional Chinese evidence lines and IDs were still interpretable.
- I did not validate Taiwan/CNVD/local ownership context for IP-only or ASUS-looking assets; those may need operator confirmation before security conclusions.