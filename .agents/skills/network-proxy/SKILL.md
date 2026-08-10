---
name: network-proxy
description: Network connectivity workarounds — proxy configuration, git push failures through SOCKS, WebFetch/WebSearch blocks, and general outbound-access troubleshooting. Invoke when any network operation fails (git push/pull/clone, web fetch, API call) and the fix is likely proxy/connectivity-related rather than a target-side issue.
---

# Network Proxy & Connectivity Troubleshooting

A **utility** skill. When the machine is behind a SOCKS proxy or firewall and a
network operation fails, this skill provides the fix patterns. It does NOT decide
*what* to access — it only encodes the recurring connectivity workarounds.

## When to invoke

- `git push` / `git pull` / `git clone` fails with HTTP 400/403/504 or hangs
- WebFetch / WebSearch returns "unable to verify if domain is safe" or times out
- Any outbound HTTPS request fails when the proxy is known to be working
- Large-repo operations through SOCKS proxy

## Local Outbound Proxy

The local SOCKS5 proxy often used for developer outbound access:

| Setting | Value |
|---------|-------|
| Protocol | SOCKS5h (DNS resolved through proxy) |
| Address | `127.0.0.1:7892` |
| Service | Clash / V2Ray (local) |

Do not confuse this with Xunji's active engagement proxy discipline:

- Active Xunji target-facing tools (`probe.py`, `render.py`, `scan.py`, sensors)
  use `--proxy`, `XUNJI_PROXY`, or `tools/harness/proxy.conf` through
  `tools/harness/proxy.py`.
- Direct is the Claude-primary target default (`XUNJI_PROXY_REQUIRED=0`). The
  engagement proxy is selected only by an explicit current operator request
  (`XUNJI_PROXY_REQUIRED=1` or registered `--proxy`); dormant config is inert.
- A route-less historical contract and a prompt that only forbids direct remain
  offline. Browser subprocesses strip ambient proxy variables; scanner wrappers
  preflight the selected proxy and disable native transport retries.
- A proxy-attributed failure stops automatic retry and remains paused until a
  newer top-level operator turn chooses direct or explicitly selects proxy again.
  Confirmation is route-specific. Codex advice must not reinterpret an internal
  wake or cooldown as confirmation.
- Codex review traffic uses the dedicated `CODEX_PROXY` /
  `tools/harness/codex_proxy.conf` path.
- Model/API calls must not be routed through the engagement proxy.

## Git through SOCKS proxy

### Quick one-shot push

```bash
git -c http.proxy=socks5h://127.0.0.1:7892 -c http.postBuffer=524288000 push <remote> <branch>
```

### Why postBuffer matters

Default `http.postBuffer` is 1MB. Large repos (100+ commits, 1000+ objects) will
exceed this and GitHub returns HTTP 400. Setting it to 524288000 (500MB) fixes
this. The proxy path adds latency; the larger buffer accommodates it.

### Per-remote proxy config

```bash
git config remote.<remote-name>.proxy socks5h://127.0.0.1:7892
```

### Global postBuffer (recommended if you regularly proxy)

```bash
git config --global http.postBuffer 524288000
```

## Shell environment proxy

When ordinary CLI tools (curl, pip, etc.) need proxy access, prefer per-command
environment variables so the setting does not leak into later model/API or
engagement commands:

```bash
ALL_PROXY=socks5h://127.0.0.1:7892 curl -I https://example.com
```

Use persistent `export ALL_PROXY=...` only inside a short-lived shell where you
will not run Xunji active tools or model/API clients afterwards.

For Xunji active tools, do this instead:

```bash
XUNJI_PROXY_REQUIRED=1 XUNJI_PROXY=socks5h://127.0.0.1:7892 python tools/probe.py GET "<url>" --save <name> --run runs/<dir>
```

## WebFetch / WebSearch failures

When the harness reports "unable to verify if domain is safe" for fetch/search:
this is often a proxy/egress issue, not a content policy rejection. Options:

1. **Use gh CLI instead** — `gh api` / `gh repo view` routes through the git
   credential chain and may succeed when direct fetch fails.
2. **Clone and read locally** — `git clone --depth 1 <url> /tmp/name` and read
   from disk.
3. **Try with explicit proxy env for the specific CLI** — do not leave proxy
   variables exported for later model/API or active engagement commands.

## Tooling boundary

This skill provides **connectivity fixes only**. It does NOT:
- Decide what targets to access or whether an operation is authorized
- Provide payloads, exploits, or attack methodology
- Bypass rate limits or authentication — that's the target's concern, not the network's

The limits remain `src-safety-boundary` (effect, not method) and the live
Claude `.claude/hooks/` gate. Codex does not provide or maintain a parallel
hook boundary.
