# Report

## Summary

- Status: 完成14/14确认资产全覆盖, 无confirmed HIGH/CRITICAL, 7条reportable信息泄露
- Severity candidate: MEDIUM (信息泄露集群)
- Affected asset: www.scshr.com (WordPress), api.scshr.com, schedule.scshr.com, client.scshr.com, cloud.scshr.com, yk50lan.scshr.com:12443 (FortiGate)
- Evidence IDs: E-001, E-002, E-007, E-008, E-009, E-011, E-013 (candidate/phenomenon maturity — 信息泄露, 非确认可利用漏洞; 0 confirmed HIGH/CRITICAL)
- Fingerprints captured: AIS WebForm v7.3.2023.0705/7.3.2026.0612, DevExpress DXR.axd, FortiOS SSL VPN SAML SSO, WordPress plugins (wp-file-manager 8.0.4, code-snippets, Yoast SEO, ACF, Really Simple SSL, LiteSpeed Cache, Divi, CF7, HubSpot, Popup Maker)

## Impact

飛騰雲端 (Soar Cloud) HR SaaS 平台整体安全配置良好:
- WordPress 核心安全机制正确 (xmlrpc 禁用, 注册禁用, PHP 文件保护, 所有敏感 REST 端点 401)
- HR SaaS 使用 GUID-based 多租户路由, 无有效 GUID 无法接触业务逻辑
- FortiOS CVE-2022-40684 已修补
- 403 主机 (tp/scs-ad) 无绕过路径

但存在多处信息泄露, 可辅助社会工程/定向攻击:
1. 7 个 WordPress 用户枚举 (含管理员 sc_admin)
2. 内部 IP 192.168.8.221:8087 泄露
3. Azure AD 租户 ID fd4fe7e3-9e23-455a-8a67-1eca0be0465a
4. AIS 框架完整版本/配置信息 (schedule 2023年未更新)
5. .NET 类库文档 + WordPress REST API 路由 + 插件结构 暴露

## Evidence

| ID | 严重度 | 确定性 | 资产 | 描述 |
|----|--------|--------|------|------|
| E-001 | MEDIUM | 0.5 | www.scshr.com | 7 WordPress 用户枚举 (REST API) |
| E-002 | MEDIUM | 0.5 | www.scshr.com | 内部IP泄露 192.168.8.221:8087 |
| E-007 | LOW | 0.5 | yk50lan:12443 | Azure AD 租户ID fd4fe7e3-... |
| E-008 | LOW | 0.5 | api.scshr.com | .NET AIS_Define 类库文档 888页 |
| E-009 | LOW | 0.5 | www.scshr.com | WordPress REST API 完全开放 |
| E-011 | LOW | 0.5 | www.scshr.com | 6个额外插件 REST 结构 (code-snippets含RCE潜力) |
| E-012 | LOW | 0.5 | www.scshr.com | lostpassword 用户枚举 oracle |
| E-013 | MEDIUM | 0.5 | schedule/client/cloud | AIS 框架完整版本/配置 (ProgramItems 1918, DB日志配置) |

## Chains (组合利用)

- 无 — 未发现横向移动/权限提升路径; 所有前沿被独立门控 (auth/GUID/ACL)

## False-Positive Review

- E-014 修正了对 client.scshr.com 的错误分析: codex review 发现此前 probe.py stdout body 为空, 遗漏了保存文件中 10 个隐藏字段 + 4 个脚本 + 系统信息表; 分析已更正

## Reproduction Notes

所有证据均可通过以下方式复现:
```bash
# 用户枚举
python3 tools/probe.py GET "https://www.scshr.com/wp-json/wp/v2/users" --proxy http://127.0.0.1:7892

# 内部IP泄露
python3 tools/probe.py GET "https://www.scshr.com/wp-json/wp/v2/users/1" --proxy http://127.0.0.1:7892

# FortiGate Azure AD
python3 tools/probe.py GET "https://yk50lan.scshr.com:12443/remote/login" --proxy http://127.0.0.1:7892

# AIS 系统信息
python3 tools/probe.py GET "https://schedule.scshr.com/" --proxy http://127.0.0.1:7892
```

## Remediation

1. **WordPress**: 禁用 REST API 用户端点 (`wp-json/wp/v2/users`), 或通过插件限制; 移除用户 profile 中的内网 URL
2. **AIS 框架**: 删除或鉴权 "伺服端資訊" 默认页 (schedule/client/cloud), 移除版本号/配置信息
3. **api.scshr.com**: 移除 Sandcastle 文档 (`/api/help/`)
4. **FortiGate**: 考虑使用更安全的 SAML SP-initiated 流程或限制 /remote/login 的信息泄露
5. **整体**: 统一版本管理 — schedule 使用 2023 版本而 client 使用 2026, 需要对所有主机保持同步更新

## Open Questions

- schedule.scshr.com v7.3.2023.0705 与 client v7.3.2026.0612 版本差异 — 是否需要更新?
- __LOGINCOMPANYID 参数是否可用于租户枚举?
- GUID 跨主机复用的安全边界?
- elearning.scshr.com (私网IP) 是否仍在运行?
