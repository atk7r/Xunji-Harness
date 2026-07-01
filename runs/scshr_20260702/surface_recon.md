# Surface — ingested from recon

> Source: `/Users/ccj/Documents/AI/Guanlan/output/report_agent/scshr.com/recon.json` (generated_at 2026-06-14T14:10:12Z)
> Target: **scshr.com** — 飛騰雲端系統股份有限公司 (Soar Cloud System)
> 按 WORKFLOW「Ingest Existing Intelligence First」折叠; recon 已收集的事实(存活/IP/标题/指纹/分类)视为既有, 不重复发现。

- Stats: hosts=26, confirmed=14, pending=15, low=8, ips=3

## Assets

| host | category | recon-reach | verdict | tech | url |
|------|----------|-------------|---------|------|-----|
| 122.117.135.182 | 基础设施 / IP / 网关 | confirmed |  | microsoft iis web服务器, windows, asp, asp.net | https://122.117.135.182 |
| 20.198.176.62 | 基础设施 / IP / 网关 | confirmed |  | windows, asp.net, microsoft iis web服务器, asp | https://20.198.176.62 |
| 220-133-81-127.hinet-ip.hinet.net | 基础设施 / IP / 网关 | pending | likely_noise |  |  |
| ai.scshr.com | HR SaaS 业务应用群 | confirmed |  | asp.net, azure-arr, jquery | https://ai.scshr.com |
| api.scshr.com | API / 接口服务 | confirmed |  | asp.net, jquery | https://api.scshr.com |
| app.scshr.com | HR SaaS 业务应用群 | confirmed |  | jquery, asp.net, azure-arr | https://app.scshr.com |
| client.scshr.com | HR SaaS 业务应用群 | confirmed |  | asp.net, jquery | https://client.scshr.com |
| cloud.scshr.com | HR SaaS 业务应用群 | confirmed |  | jquery | https://cloud.scshr.com |
| device-8f98d13a-dd14-450f-9dd0-b499e0e76e5e.remotewd.com | 第三方 / 旁站 / 动态域名 | low | likely_noise | nginx web服务器 | https://device-8f98d13a-dd14-450f-9dd0-b499e0e76e5e.remotewd.com |
| elearning.scshr.com | HR SaaS 业务应用群 | low | needs_human | nginx web服务器 | https://elearning.scshr.com |
| hr-news.tw | 第三方 / 旁站 / 动态域名 | pending | needs_human |  |  |
| kh.scshr.com | 区域/租户部署实例 | confirmed |  | asp, asp.net, microsoft iis web服务器, windows | https://kh.scshr.com |
| payment.scshr.com | HR SaaS 业务应用群 | confirmed |  | microsoft iis web服务器, asp, asp.net, windows | https://payment.scshr.com |
| schedule.scshr.com | HR SaaS 业务应用群 | confirmed |  | jquery, asp.net | https://schedule.scshr.com |
| scs--nas.direct.quickconnect.to | 第三方 / 旁站 / 动态域名 | pending | needs_human | fortios, fortigate-sslvpn下一代vpn防火墙, fortinet security device httpd | https://scs--nas.direct.quickconnect.to |
| scs-ad.scshr.com | 区域/租户部署实例 | low | needs_human | nginx web服务器 | https://scs-ad.scshr.com |
| self-learning.ddns.net | 第三方 / 旁站 / 动态域名 | pending | likely_noise | asp, asp.net, microsoft iis web服务器, windows | https://self-learning.ddns.net |
| services.scshr.com | HR SaaS 业务应用群 | confirmed |  | jquery, asp.net, azure-arr | https://services.scshr.com |
| tp.scshr.com | 区域/租户部署实例 | low | needs_human | nginx web服务器 | https://tp.scshr.com |
| tscs.scshr.com | 区域/租户部署实例 | confirmed |  | nginx web服务器, asp.net, jquery | https://tscs.scshr.com |
| wpgbeta.scshr.com | 区域/租户部署实例 | confirmed |  | jquery, nginx web服务器, asp.net | https://wpgbeta.scshr.com |
| wpsite.home.kg | 第三方 / 旁站 / 动态域名 | pending | likely_noise | fortinet-sslvpn, fortinet security device httpd, fortios | https://wpsite.home.kg |
| www.hr-news.tw | 第三方 / 旁站 / 动态域名 | pending | needs_human |  |  |
| www.scshr.com | 官网与对外门户 | confirmed |  | google-站长平台, jquery, nginx web服务器, lightbox, php, wordpresscms博客系统, font awesome, jquery-ui | https://www.scshr.com |
| www.scshr.com.tw | 官网与对外门户 | pending | likely_real |  |  |
| yk50lan.scshr.com | 区域/租户部署实例 | pending | needs_human | fortinet-sslvpn, fortios, fortinet security device httpd | https://yk50lan.scshr.com |

## Entry Points

- **api.scshr.com** [api] reach=confirmed title="伺服端資訊" — API/接口入口：核查鉴权与接口文档（swagger 等）是否对外暴露。

## Needs Human (recon 标记待人工终裁)

- elearning.scshr.com
- hr-news.tw
- scs--nas.direct.quickconnect.to
- scs-ad.scshr.com
- tp.scshr.com
- www.hr-news.tw
- yk50lan.scshr.com

## Verification Tasks (recon 建议)

- [human] elearning.scshr.com: 人工终裁：教讀/學習端点，但解析到私网 192.168.8.200、url 404 且无有意义标题，未能确认
- [human] hr-news.tw: 人工终裁：解析到公司 HiNet IP 220.133.81.127，疑似 HR 资讯内容站，但 502 未能确认归属
- [human] scs--nas.direct.quickconnect.to: 人工终裁：Synology QuickConnect NAS，scs-- 前缀疑似公司 NAS，403/200 未能确认
- [human] scs-ad.scshr.com: 人工终裁：403，scs-ad 疑似 Active Directory / 认证相关内部资产，需人工确认
- [human] tp.scshr.com: 人工终裁：403 禁止存取，台北（tp）部署疑似访问控制/WAF，非纯噪音
- [human] www.hr-news.tw: 人工终裁：同 hr-news.tw，502 临时不可用，需人工确认
- [human] yk50lan.scshr.com: 人工终裁：200 但无标题，名含 lan 疑似内网相关部署，需人工确认
- [review] api.scshr.com: API/接口入口：核查鉴权与接口文档（swagger 等）是否对外暴露。

## Reachability Matrix

> recon-reach 是报告生成视角; mine 由你从本出口探测后回填。两者可不同(如境内资产对境外出口超时), 缺口即需中继/代理的信号。

| host | recon-reach | mine (probe 后回填) |
|------|-------------|----------------------|
| 122.117.135.182 | confirmed | ? |
| 20.198.176.62 | confirmed | ? |
| 220-133-81-127.hinet-ip.hinet.net | pending | ? |
| ai.scshr.com | confirmed | ? |
| api.scshr.com | confirmed | ? |
| app.scshr.com | confirmed | ? |
| client.scshr.com | confirmed | ? |
| cloud.scshr.com | confirmed | ? |
| device-8f98d13a-dd14-450f-9dd0-b499e0e76e5e.remotewd.com | low | ? |
| elearning.scshr.com | low | ? |
| hr-news.tw | pending | ? |
| kh.scshr.com | confirmed | ? |
| payment.scshr.com | confirmed | ? |
| schedule.scshr.com | confirmed | ? |
| scs--nas.direct.quickconnect.to | pending | ? |
| scs-ad.scshr.com | low | ? |
| self-learning.ddns.net | pending | ? |
| services.scshr.com | confirmed | ? |
| tp.scshr.com | low | ? |
| tscs.scshr.com | confirmed | ? |
| wpgbeta.scshr.com | confirmed | ? |
| wpsite.home.kg | pending | ? |
| www.hr-news.tw | pending | ? |
| www.scshr.com | confirmed | ? |
| www.scshr.com.tw | pending | ? |
| yk50lan.scshr.com | pending | ? |
