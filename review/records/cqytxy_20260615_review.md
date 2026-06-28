# Independent Review: cqytxy.edu.cn (2026-06-15)

## Summary

| Finding | Op Cert | Verdict | Rev Cert | Key Issue |
|---|---|---|---|---|
| VULN-001: ykds CSRF bypass | 0.85 | **FALSE POSITIVE** | N/A | 标准Spring Security CSRF token，非漏洞 |
| VULN-002: ykds user enum | 0.80 | **OVERCLAIMED** | 0.35 | 无保存证据；仅单向oracle；无有效用户 |
| VULN-003: zfpt admin exposure | 0.90 | **CONFIRMED** | 0.90 | 暴露属实，子断言(user存在/IIS版本)证据不足 |

## Detailed Verdicts

### VULN-001: FALSE POSITIVE
HTML中嵌入CSRF token是Spring Security标准行为，不是绕过。未证明：
- 跨session token固定/预测
- 服务端不验证token
- CORS允许跨域读取
- 缺少token的POST能成功

### VULN-002: OVERCLAIMED
- 未保存/forgot/mail/send的原始HTTP响应
- 只看到"用户不存在"（一侧），未见"用户存在"的响应
- IP限流(1/min)使实际利用不可能
- 24+次尝试未找到任何有效用户

### VULN-003: CONFIRMED
支付管理后台公网暴露确实存在。但：
- admin/sa用户存在性：OCR通过后返回"密码错误"而非"用户不存在"，这是用户存在性的弱证据（需保存原始响应确认）
- IIS版本：未保存Server头证据

## Missing Evidence
1. 所有HTTP响应头未保存
2. /forgot/mail/send原始响应未保存
3. 60+登录尝试的日志/响应未保存
4. CSRF token跨session测试未做
5. SQL注入过滤消息原始响应未保存
