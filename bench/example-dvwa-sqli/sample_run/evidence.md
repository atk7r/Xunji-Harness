# Evidence Ledger

> 合成样例(非真实目标)。bench 按 marker 匹配确认条目, 这里刻意覆盖: 一个确认 SQLi、
> 一个确认 reflected XSS、一个纯负向(登录页非漏洞, 不应误报)、一个未确认线索(0.5)。

## E-001: SQL injection in id param (union-based)
- Action: GET /vulnerabilities/sqli/?id=1' UNION SELECT user,password-- -
- Result: 回显 admin 哈希; union-based SQL injection 确认
- Certainty: 1.0
- Replicated: 两次独立请求同结果
- Control: 良性 id=1 无回显 vs payload 回显差分
- Artifacts: `evidence/sqli_union.html`
- Supports: H-001

## E-002: login page present at /login.php (environment, not a vuln)
- Action: GET /login.php
- Result: 标准登录页; 无弱点。login page present —— 仅环境事实
- Certainty: 0.8
- Replicated: yes
- Refutes: H-009

## E-003: reflected XSS in search param
- Action: GET /vulnerabilities/xss_r/?name=<script>alert(1)</script>
- Result: name 原样回显进 HTML, reflected XSS 确认(payload 未编码落入 DOM)
- Certainty: 0.9
- Control: 良性 name=foo 不触发 vs payload 触发
- Artifacts: `evidence/xss_reflected.html`
- Supports: H-002

## E-004: possible CSRF on password change (unconfirmed)
- Action: 观察 /vulnerabilities/csrf/ 无 token
- Result: 疑似无 CSRF token, 但未构造跨站请求验证
- Certainty: 0.5
- Note: 线索, 缺 PoC 验证
