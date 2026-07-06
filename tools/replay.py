#!/usr/bin/env python3
"""replay.py — 自动重放核实(B1-②).

读 probe 留的 `.replay.json` 操作录像, 走 guard 重新发同一请求, 把响应和录像比对, 核实证据
【对应现实】而非只信描述。这是 B1 的闭环: 录像(probe --save)备料, replay 用起来。

安全边界(effects, not methods):
- 只自动重放【幂等的 GET】; 写操作(POST/PUT/DELETE/PATCH)再执行一次有副作用 -> 默认 SKIPPED-WRITE,
  `--force` 才重放(操作者授权)。
- 重放经 probe.send() -> 继承全部 guard(RateLimiter/cap_body/HostHealth/SessionBudget 熔断)。

比对分级:
- IDENTICAL : status 同 且 sha1 同 -> 证据被现实完整支持(最强)。
- CONSISTENT: status 同 但 sha1 异 -> 端点还在那个状态, 内容随动态/时效变(CSRF/时间戳), 仍是支持。
- DIVERGED  : status 变 -> 证据存疑(目标改了 / 当时造假 / 下线), 需 driver 判断。
- UNREACHABLE: 重放发不出去(超时/RST) -> 无法核实(够不着 != 证据假, 同"够不着!=它安全")。
- SKIPPED-WRITE: 写操作未重放(默认)。

残留墙(replay 触不到的): 破坏性证据(证明"能删")不能安全重放; 一次性/时效证据(token 过期)重放
会假阴; 目标下线无法重放。这些停在 driver 判断, 不是 replay 能闭合的。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

_here = Path(__file__).resolve()
sys.path.insert(0, str(_here.parent))           # tools/  (probe)
sys.path.insert(0, str(_here.parents[1]))       # repo root (sentinel)
import probe   # 同目录: 复用 send() 的 guard 层

ROOT = Path(__file__).resolve().parents[1]
WRITE_METHODS = {"POST", "PUT", "PATCH"}          # 有副作用: --force 才重放
DESTRUCTIVE_METHODS = {"DELETE"}                  # 破坏性: 永不自动重放(撞 CLAUDE.md 硬边界 删资源 never)


def _authorized_scope(run_dir: Path) -> set:
    """授权 scope = target.md 的【In-scope assets】, 复用护栏层 sentinel.state.scope_hosts ——
    单一权威 scope 源。【不】用 coverage/surface: 那些含 recon 扫到的噪音/越界 IP(标"噪音/兜底"),
    拿它当白名单会把越界资产当 in-scope —— 2026-06-17 把噪音 IP 13.159.140.34 当目标 Jenkins 怂恿打,
    正栽在此(run 自己的护栏用 scope_hosts 早把它判越界了, 是 replay 当时没用同一个源)。"""
    try:
        from sentinel.state import scope_hosts
        return scope_hosts(run_dir)
    except Exception:
        return set()


def _host_in_scope(host: str, scope: set) -> bool:
    """镜像 sentinel.classifier._host_in_scope: 精确 或 子域名后缀匹配(hamastar.com.tw 覆盖
    2019yles-mgr.hamastar.com.tw, 但不覆盖噪音 IP, 也不被 evilhamastar.com.tw 蒙混)。"""
    host = (host or "").lower()
    return bool(host) and any(host == s or host.endswith("." + s) for s in scope)


def _authorized_scope_for_file(rec_path: Path) -> "set | None":
    """单文件模式: 从录像路径向上找含 target.md 的 run 目录, 取其授权 scope。找不到返回 None
    (-> fail-closed, 拒绝重放)。"""
    for parent in rec_path.resolve().parents:
        if (parent / "target.md").is_file():
            return _authorized_scope(parent)
    return None


def replay_one(rec_path, *, force: bool = False, timeout: int = 20,
               allowed_hosts: "set | None" = None) -> dict:
    """重放单个 .replay.json, 返回结构化结果(含 verdict)。"""
    try:
        rec = json.loads(Path(rec_path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"file": str(rec_path), "verdict": "BAD-RECORD", "error": str(e)}
    req = rec.get("request", {}) or {}
    resp = rec.get("response", {}) or {}
    method = (req.get("method") or "GET").upper()
    url = req.get("url", "")
    headers = req.get("headers", {}) or {}
    body = req.get("body")
    out: dict = {"file": str(rec_path), "method": method, "url": url,
                 "old_status": resp.get("status")}

    # scope 门(防篡改/越界录像打 scope 外): host 必须在 run 授权资产台账。allowed_hosts=None 时
    # 跳过(单文件无 run 上下文), 由 main 警告。
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    # scope fail-CLOSED: 无法确定授权 scope(allowed_hosts=None)就【拒绝】, 不放行(dogfood 第7次
    # BLOCKER: 单文件模式无 --scope 曾 fail-open)。授权 scope = target.md In-scope(run/回溯)或 --scope。
    if allowed_hosts is None:
        out["verdict"] = "SKIPPED-NO-SCOPE"
        out["note"] = "无法确定授权 scope —— 拒绝重放(fail-closed); 在 run 目录下跑, 或用 --scope"
        return out
    if host and not _host_in_scope(host, allowed_hosts):
        out["verdict"] = "SKIPPED-OUT-OF-SCOPE"
        out["note"] = f"host {host} 不在授权 scope({sorted(allowed_hosts)}) —— 拒绝重放(防打 scope 外)"
        return out

    # 破坏性方法【永不】自动重放(--force 也不解锁): 撞 CLAUDE.md 硬边界(删资源 never)。
    if method in DESTRUCTIVE_METHODS:
        out["verdict"] = "SKIPPED-DESTRUCTIVE"
        out["note"] = f"{method} 破坏性, 永不自动重放(再执行=删资源; --force 也不解锁); 需人工核实"
        return out
    if method in WRITE_METHODS and not force:
        out["verdict"] = "SKIPPED-WRITE"
        out["note"] = "写操作默认不自动重放(再执行一次有副作用); --force 才重放"
        return out

    data = body.encode("utf-8") if isinstance(body, str) else None
    try:
        new = probe.send(method, url, headers, data, None, timeout, want_headers=False)
    except Exception as e:
        # probe.send 的 guard 熔断(HostBackoff/SessionTripped/RateBudget...)抛异常 -> 规整成 verdict
        out["verdict"] = "GUARD-BLOCKED"
        out["error"] = str(e)
        return out
    if new.get("error"):
        out["verdict"] = "UNREACHABLE"
        out["error"] = new["error"]
        return out

    new_status = new.get("status")
    new_full = new.get("sha1_full") or new.get("sha1") or ""   # 全 sha1(整完整性); 回退 12 位
    old_full = resp.get("sha1") or ""
    out["new_status"] = new_status
    out["sha1_match"] = bool(new_full and old_full and new_full == old_full)
    if new_status == out["old_status"] and out["sha1_match"]:
        out["verdict"] = "IDENTICAL"
    elif new_status == out["old_status"]:
        out["verdict"] = "CONSISTENT"
        out["note"] = ("status 同但内容变 —— 可能动态内容(时间戳/CSRF), 也可能【会话失效/漏洞已修】"
                       "返回登录页或错误页。CONSISTENT 不等于核实通过: driver 须核对内容是否仍是漏洞"
                       "响应(尤其认证请求, 过期 cookie 会返回同 status 的登录页)。")
    else:
        out["verdict"] = "DIVERGED"
    return out


def replay_run(run_dir, *, force: bool = False, timeout: int = 20,
               allowed_hosts: "set | None" = None) -> list:
    run_dir = Path(run_dir)
    if allowed_hosts is None:
        allowed_hosts = _authorized_scope(run_dir)   # 授权 scope(target.md In-scope), 非 coverage
        if not allowed_hosts:
            print("[warn] target.md 未声明授权 scope -> 全部按越界跳过; 用 --scope 显式指定",
                  file=sys.stderr)
    recs = sorted(run_dir.glob("**/*.replay.json"))
    return [replay_one(r, force=force, timeout=timeout, allowed_hosts=allowed_hosts) for r in recs]


def _print_results(results: list) -> dict:
    counts: dict = {}
    for r in results:
        v = r.get("verdict", "?")
        counts[v] = counts.get(v, 0) + 1
        line = f"[{v}] {r.get('method','?')} {r.get('url','')}"
        if "new_status" in r:
            line += f" ({r.get('old_status')}→{r['new_status']}, sha1 {'同' if r.get('sha1_match') else '异'})"
        elif r.get("error"):
            line += f"  ({r['error'][:60]})"
        print(line)
    if counts:
        print("\n汇总: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    else:
        print("(无录像)")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="自动重放核实操作录像(B1-②)")
    ap.add_argument("target", nargs="?", help="run 目录 或 单个 .replay.json")
    ap.add_argument("--force", action="store_true",
                    help="也重放写操作(POST/PUT/DELETE/PATCH) —— 再执行一次有副作用, 危险")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--scope", default=None,
                    help="逗号分隔授权 scope host(覆盖从 target.md In-scope 自动提取, 后缀匹配子域); 单文件建议显式给")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.target:
        ap.error("需要 run 目录或 .replay.json(或 --selftest)")
    t = Path(args.target)
    if not t.is_absolute():
        t = ROOT / t
    scope = {h.strip().lower() for h in args.scope.split(",") if h.strip()} if args.scope else None
    if t.is_file():
        if scope is None:
            scope = _authorized_scope_for_file(t)   # 回溯录像所在 run 的 target.md
        if not scope:
            print("[error] 无法确定授权 scope(录像不在 run 目录下且未给 --scope) —— 拒绝重放"
                  "(fail-closed)。用 --scope 显式指定 host。", file=sys.stderr)
            return 2
        results = [replay_one(t, force=args.force, timeout=args.timeout, allowed_hosts=scope)]
    elif t.is_dir():
        results = replay_run(t, force=args.force, timeout=args.timeout, allowed_hosts=scope)
    else:
        print(f"目标不存在: {t}")
        return 1
    counts = _print_results(results)
    # DIVERGED = 证据存疑(目标变/当时造假) -> 非0退出提示注意; UNREACHABLE 不算失败(够不着!=假)
    return 1 if counts.get("DIVERGED") else 0


def _selftest() -> int:
    import http.server
    import socketserver
    import threading
    import tempfile
    import hashlib
    body = b"replay-ok-body"
    sha = hashlib.sha1(body).hexdigest()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

    checks: list = []
    with probe.selftest_isolation():
        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/"
        LH = {"127.0.0.1"}                       # selftest 都打本地 -> 授权 scope
        d = Path(tempfile.mkdtemp())

        def mkrec(name, method, u, status, sha1, bodyval=None):
            p = d / name
            p.write_text(json.dumps({
                "request": {"method": method, "url": u, "headers": {}, "body": bodyval},
                "response": {"status": status, "sha1": sha1, "len": 0}}), encoding="utf-8")
            return p

        try:
            # fail-closed: 无 scope -> SKIPPED-NO-SCOPE(不 fail-open) —— dogfood 第7次 BLOCKER
            checks.append(("无 scope -> SKIPPED-NO-SCOPE(fail-closed)",
                           replay_one(mkrec("ns.replay.json", "GET", url, 200, sha))["verdict"] == "SKIPPED-NO-SCOPE"))
            # 正确录像 -> IDENTICAL
            checks.append(("正确录像 -> IDENTICAL",
                           replay_one(mkrec("a.html.replay.json", "GET", url, 200, sha), allowed_hosts=LH)["verdict"] == "IDENTICAL"))
            # status 同 sha 异(内容动态变) -> CONSISTENT
            checks.append(("status同 sha异 -> CONSISTENT",
                           replay_one(mkrec("b.html.replay.json", "GET", url, 200, "0" * 40), allowed_hosts=LH)["verdict"] == "CONSISTENT"))
            # status 异(当时声称404实际200) -> DIVERGED
            checks.append(("status异 -> DIVERGED(证据存疑)",
                           replay_one(mkrec("c.html.replay.json", "GET", url, 404, sha), allowed_hosts=LH)["verdict"] == "DIVERGED"))
            # 写操作 -> SKIPPED-WRITE; --force 才重放
            post = mkrec("d.replay.json", "POST", url, 200, sha, bodyval="x")
            checks.append(("写操作默认 SKIPPED-WRITE", replay_one(post, allowed_hosts=LH)["verdict"] == "SKIPPED-WRITE"))
            checks.append(("--force 重放写操作(不再skip)", replay_one(post, force=True, allowed_hosts=LH)["verdict"] != "SKIPPED-WRITE"))
            # 不可达 -> UNREACHABLE
            checks.append(("目标不可达 -> UNREACHABLE",
                           replay_one(mkrec("e.replay.json", "GET", "http://127.0.0.1:1/", 200, sha),
                                      timeout=2, allowed_hosts=LH)["verdict"] == "UNREACHABLE"))
            # 坏记录 -> BAD-RECORD(在 scope 检查前)
            bad = d / "bad.replay.json"
            bad.write_text("{not json", encoding="utf-8")
            checks.append(("坏 JSON -> BAD-RECORD", replay_one(bad, allowed_hosts=LH)["verdict"] == "BAD-RECORD"))
            # 破坏性 DELETE -> SKIPPED-DESTRUCTIVE(--force 也不解锁)
            dele = mkrec("del.replay.json", "DELETE", url, 200, sha)
            checks.append(("DELETE -> SKIPPED-DESTRUCTIVE", replay_one(dele, allowed_hosts=LH)["verdict"] == "SKIPPED-DESTRUCTIVE"))
            checks.append(("DELETE --force 仍 SKIPPED-DESTRUCTIVE",
                           replay_one(dele, force=True, allowed_hosts=LH)["verdict"] == "SKIPPED-DESTRUCTIVE"))
            # scope 门(防打 scope 外); 授权 scope 用后缀匹配
            checks.append(("scope 外 host -> SKIPPED-OUT-OF-SCOPE",
                           replay_one(mkrec("sc.html.replay.json", "GET", url, 200, sha),
                                      allowed_hosts={"other.example"})["verdict"] == "SKIPPED-OUT-OF-SCOPE"))
            checks.append(("scope 内 host -> 正常重放",
                           replay_one(mkrec("sc2.html.replay.json", "GET", url, 200, sha),
                                      allowed_hosts={"127.0.0.1"})["verdict"] == "IDENTICAL"))
            # 授权 scope 匹配(纯函数, 不打网络) —— 13.159.140.34 教训
            checks.append(("授权scope: 子域后缀匹配 in-scope",
                           _host_in_scope("2019x-mgr.hamastar.com.tw", {"hamastar.com.tw"})))
            checks.append(("授权scope: 噪音IP越界(13.159.140.34)",
                           not _host_in_scope("13.159.140.34", {"hamastar.com.tw"})))
            checks.append(("授权scope: 防伪子域不匹配(evilhamastar.com.tw)",
                           not _host_in_scope("evilhamastar.com.tw", {"hamastar.com.tw"})))
            # _authorized_scope 读 target.md In-scope, 【不】读 coverage(含噪音 IP)
            scoped = Path(tempfile.mkdtemp())
            (scoped / "target.md").write_text("# Target\n- In-scope assets: hamastar.com.tw\n", encoding="utf-8")
            (scoped / "classify").mkdir()
            (scoped / "classify" / "coverage.json").write_text(
                json.dumps({"assets": [{"host": "13.159.140.34"}, {"host": "www.hamastar.com.tw"}]}),
                encoding="utf-8")
            asc = _authorized_scope(scoped)
            checks.append(("_authorized_scope 取 target.md In-scope", "hamastar.com.tw" in asc))
            checks.append(("_authorized_scope 不含 coverage 噪音 IP 13.159.140.34", "13.159.140.34" not in asc))
            # guard 熔断异常 -> GUARD-BLOCKED(不崩)
            _orig = probe.send
            probe.send = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HostBackoff"))
            try:
                checks.append(("guard 异常 -> GUARD-BLOCKED(不崩)",
                               replay_one(mkrec("g.html.replay.json", "GET", url, 200, sha), allowed_hosts=LH)["verdict"] == "GUARD-BLOCKED"))
            finally:
                probe.send = _orig
            # 批量(显式 scope)
            res = replay_run(d, allowed_hosts={"127.0.0.1"})
            checks.append(("批量重放 run 目录(scope 内, 含 IDENTICAL)",
                           len(res) >= 5 and any(r["verdict"] == "IDENTICAL" for r in res)))
        finally:
            srv.shutdown()
    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("replay selftest " + ("passed" if not failed else f"FAILED ({len(failed)})"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
