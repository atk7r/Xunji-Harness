diff --git a/docs/templates/run/evidence.md b/docs/templates/run/evidence.md
index 9253c57..4a64b16 100644
--- a/docs/templates/run/evidence.md
+++ b/docs/templates/run/evidence.md
@@ -1,9 +1,11 @@
 # Evidence Ledger
 
-> Certainty: only `>= 0.8` may be reported confirmed, and a confirmed entry MUST
-> carry a `Replicated / Control` field AND a saved `Artifacts` path under the run
-> dir (check_run hard-fails a confirmed entry with no artifact, warns with no
-> control). Full scale + meanings: `docs/cognition/README.md` "Evidence Confidence".
+> Certainty: use only the canonical scale: `1.0` direct/reproducible,
+> `0.8` controlled/replayed confirmed, `0.5` suspected candidate, `0.3` clue/noise.
+> Only `>= 0.8` may be reported confirmed, and a confirmed entry MUST carry a
+> `Replicated / Control` field AND a saved `Artifacts` path under the run dir
+> (check_run hard-fails a confirmed entry with no artifact, warns with no control).
+> Full meanings: `docs/cognition/README.md` "Evidence Confidence".
 
 ## E-001
 
diff --git a/tools/coverage_matrix.py b/tools/coverage_matrix.py
index bece62c..4eac659 100644
--- a/tools/coverage_matrix.py
+++ b/tools/coverage_matrix.py
@@ -77,11 +77,56 @@ GROUP_CLASS_MAP: dict[str, set[str]] = {
 }
 
 
+EVIDENCE_GROUP_PATTERNS: dict[str, list[re.Pattern]] = {
+    "Auth": [
+        re.compile(p, re.I) for p in (
+            r"\bauth(?:entication)?[- ]?(?:gate|bypass|slip)\b", r"\bSSO\b", r"\bOAuth\b",
+            r"signature bypass", r"signed-API|sign(?:ature)? verification|hardcoded .*secret",
+            r"OPPO_REDIRECT_URL|Redirect-Uri", r"Basic Auth", r"token[- ]?(?:gated|issuance)",
+        )
+    ],
+    "Injection": [
+        re.compile(p, re.I) for p in (
+            r"\bSQLi\b|NoSQLi|injection", r"SSTI", r"deseriali[sz]ation",
+            r"CVE-2018-15133",
+        )
+    ],
+    "IDOR": [
+        re.compile(p, re.I) for p in (
+            r"\bIDOR\b", r"priv[- ]?esc|cross[- ]?org",
+            r"(?:org[-_ ]?ID|organizationId).{0,40}\b(?:swap|switch|tamper|control|mismatch|enumerat)",
+        )
+    ],
+    "Misconfig": [
+        re.compile(p, re.I) for p in (
+            r"config(?:uration)?[- ]?leak|env\.js|micro_app\.json|app_config\.json",
+            r"CORS|WAF|swagger|actuator|\.env",
+        )
+    ],
+    "InfoLeak": [
+        re.compile(p, re.I) for p in (
+            r"leak|disclos", r"internal host|internal .*domain|backend API",
+            r"bucket|Sentry DSN|version disclosure|APP_KEY|org[- ]?ID",
+        )
+    ],
+    "SSRF": [re.compile(p, re.I) for p in (r"\bSSRF\b", r"url[- ]?fetch|URL fetch|metadata SSRF")],
+    "PathTraversal": [re.compile(p, re.I) for p in (r"path traversal|arbitrary file|file read|file download")],
+    "XXE": [re.compile(r"\bXXE\b", re.I)],
+    "Upload": [re.compile(p, re.I) for p in (r"\bupload\b|file upload",)],
+    "Logic": [re.compile(p, re.I) for p in (r"\breplay\b|nonce|freshness|flow bypass|method[- ]?specific|GET-slip",)],
+}
+
+
+EVIDENCE_TEST_FIELD_RE = re.compile(
+    r"(?im)^\s*-\s*(Action|Result|Control|Replicated|Artifacts?|Status|Verdict)\s*[:：]"
+)
+
+
 SURFACE_GROUPS: dict[str, set[str]] = {
     "login": {"Auth", "Injection"},
     "sso": {"Auth"},
     "oauth": {"Auth"},
-    "param-api": {"Injection", "IDOR", "SSRF", "Logic"},
+    "param-api": {"Injection", "IDOR", "Logic"},
     "graphql": {"Injection", "IDOR", "Logic"},
     "websocket": {"Injection", "IDOR", "Logic"},
     "upload": {"Upload", "PathTraversal", "XXE"},
@@ -268,6 +313,64 @@ def _parse_front_blocks(run_dir: Path) -> list[dict]:
     return blocks
 
 
+def _parse_evidence_blocks(run_dir: Path) -> dict[str, dict]:
+    ev = run_dir / "evidence.md"
+    if not ev.exists():
+        return {}
+    text = ev.read_text(encoding="utf-8", errors="replace")
+    out: dict[str, dict] = {}
+    for b in re.split(r"(?=^##\s)", text, flags=re.MULTILINE):
+        if not b.lstrip().startswith("##"):
+            continue
+        head = b.splitlines()[0].strip()
+        m = re.search(r"\b(E-\d+[a-z]*)\b", head)
+        if not m:
+            continue
+        eid = m.group(1)
+        out[eid] = {
+            "id": eid,
+            "text": b,
+            "front_refs": sorted(set(re.findall(r"\bF-\d+\b", b))),
+            "groups": _evidence_groups(b),
+        }
+    return out
+
+
+def _evidence_groups(text: str) -> set[str]:
+    if not EVIDENCE_TEST_FIELD_RE.search(text):
+        return set()
+    if _evidence_certainty(text) < 0.5:
+        return set()
+    signal = _evidence_signal_text(text)
+    groups: set[str] = set()
+    for group, pats in EVIDENCE_GROUP_PATTERNS.items():
+        if any(p.search(signal) for p in pats):
+            groups.add(group)
+    return groups
+
+
+def _evidence_signal_text(text: str) -> str:
+    """Keep coverage inference on tested/proven fields, not caveats or next leads."""
+    keep = []
+    for line in text.splitlines():
+        if re.match(
+            r"(?i)^\s*-\s*(Action|Result|Control|Replicated|Status|Verdict)\s*[:：]",
+            line,
+        ):
+            keep.append(line)
+    return "\n".join(keep)
+
+
+def _evidence_certainty(text: str) -> float:
+    vals = []
+    for m in re.finditer(r"(?im)^\s*-\s*Certainty[^\n:：]*[:：]\s*[\(（]?\s*(\d(?:\.\d+)?)", text):
+        try:
+            vals.append(float(m.group(1)))
+        except ValueError:
+            pass
+    return max(vals) if vals else 0.0
+
+
 def _front_tried_classes(front: dict, constraints: list[dict]) -> set[str]:
     tried = {_canonical(x) for x in _parse_list_field(front["text"], "Vectors tried") if _canonical(x)}
     fid = front["id"]
@@ -279,6 +382,13 @@ def _front_tried_classes(front: dict, constraints: list[dict]) -> set[str]:
     return tried
 
 
+def _front_evidence_groups(front: dict, evidence: dict[str, dict]) -> set[str]:
+    groups: set[str] = set()
+    for eid in sorted(set(re.findall(r"\bE-\d+[a-z]*\b", front["text"]))):
+        groups.update(evidence.get(eid, {}).get("groups", set()))
+    return groups
+
+
 def _class_groups(classes: set[str]) -> set[str]:
     out: set[str] = set()
     for group, members in GROUP_CLASS_MAP.items():
@@ -308,8 +418,9 @@ def derive(run_dir: Path) -> dict:
         })
 
     constraints = _parse_constraints(run_dir)
+    evidence = _parse_evidence_blocks(run_dir)
     for front in _parse_front_blocks(run_dir):
-        tried_groups = _class_groups(_front_tried_classes(front, constraints))
+        tried_groups = _class_groups(_front_tried_classes(front, constraints)) | _front_evidence_groups(front, evidence)
         if not tried_groups:
             continue
         declared_tokens = _front_declared_asset_tokens(front["text"])
@@ -319,6 +430,16 @@ def derive(run_dir: Path) -> dict:
                 row["fronts"].append(front["id"])
                 row["tested"] = sorted(set(row["tested"]) | tried_groups)
 
+    for eid, ev in evidence.items():
+        ev_groups = set(ev.get("groups", set()))
+        if not ev_groups:
+            continue
+        for row in rows:
+            row_tokens = set(row["tokens"])
+            if _mentions_any_host(ev["text"], row_tokens):
+                row["fronts"] = sorted(set(row["fronts"]) | set(ev.get("front_refs", [])))
+                row["tested"] = sorted(set(row["tested"]) | ev_groups)
+
     group_names = [g for g, _ in GROUPS]
     matrix = []
     for row in rows:
@@ -447,6 +568,10 @@ def _selftest() -> int:
         {"host": "portal.example", "reachable": True, "title": "Admin API docs"},
         {"host": "asset-field.example", "reachable": True, "flags": ["LOGIN"]},
         {"host": "url-field.example", "port": 8443, "reachable": True, "flags": ["LOGIN"]},
+        {"host": "evidence-only.example", "reachable": True, "flags": ["LOGIN"]},
+        {"host": "status-only.example", "reachable": True, "flags": ["LOGIN"]},
+        {"host": "low-cert.example", "reachable": True, "flags": ["LOGIN"]},
+        {"host": "confounder.example", "reachable": True, "flags": ["SURFACE:API"]},
         {"host": "d.example", "reachable": False, "flags": ["SURFACE:UPLOAD"]},
     ]}), encoding="utf-8")
     (run / "frontier.md").write_text(
@@ -477,6 +602,27 @@ def _selftest() -> int:
         "- Vectors tried: auth-bypass\n",
         encoding="utf-8",
     )
+    (run / "evidence.md").write_text(
+        "# Evidence Ledger\n\n"
+        "## E-001\n"
+        "- Action: checked evidence-only.example login boundary\n"
+        "- Result: SSO auth-gate observed; 401 on unauth API\n"
+        "- Certainty: 0.5\n"
+        "- Supports: F-006\n\n"
+        "## E-002\n"
+        "- Action: checked status-only.example public page\n"
+        "- Result: returned HTTP 401 text without boundary mechanism evidence\n"
+        "- Certainty: 0.3\n\n"
+        "## E-003\n"
+        "- Action: checked low-cert.example login boundary\n"
+        "- Result: SSO auth-gate clue from one redirect only\n"
+        "- Certainty: 0.3\n\n"
+        "## E-004\n"
+        "- Action: checked confounder.example parameter handling\n"
+        "- Result: normal validation response, no parameter anomaly\n"
+        "- Note: false-positive confounder mentioned SQLi as an alternate hypothesis only\n"
+        "- Certainty: 0.5\n",
+        encoding="utf-8")
     data = derive(run)
     warns, errors = check(run)
     write_outputs(run)
@@ -509,6 +655,14 @@ def _selftest() -> int:
         ("explicit Targets field accepts URL host:port",
          by_asset["url-field.example:8443"]["cells"]["Auth"] == "tested"
          and "F-005" in by_asset["url-field.example:8443"]["fronts"]),
+        ("evidence-derived auth test fills matrix without Vectors tried",
+         by_asset["evidence-only.example"]["cells"]["Auth"] == "tested"),
+        ("bare HTTP status text does not fill Auth coverage",
+         by_asset["status-only.example"]["cells"]["Auth"] == "untested"),
+        ("low-certainty evidence does not fill Auth coverage",
+         by_asset["low-cert.example"]["cells"]["Auth"] == "untested"),
+        ("confounder note does not fill Injection coverage",
+         by_asset["confounder.example"]["cells"]["Injection"] == "untested"),
         ("corrupt primary coverage warns while using nested coverage",
          "nested.example" in bad_by_asset and bad_cov_warns and not bad_cov_errors),
         ("check reports warnings only", warns and not errors),
diff --git a/tools/probe.py b/tools/probe.py
index 4890881..047a576 100644
--- a/tools/probe.py
+++ b/tools/probe.py
@@ -165,10 +165,24 @@ def _is_waf_block(headers: dict, body: bytes) -> bool:
         return True
     return False
 
+def _range_header_value(byte_range: str) -> str:
+    br = byte_range.strip()
+    return br if br.lower().startswith("bytes=") else f"bytes={br}"
+
+
+def _header_value(headers: dict, name: str) -> str | None:
+    name_l = name.lower()
+    for k, v in headers.items():
+        if k.lower() == name_l:
+            return v
+    return None
+
+
 def send(method: str, url: str, headers: dict, data: bytes | None,
          auth_key: str | None, timeout: int, save: str | None = None,
          retry: int = 0, retry_wait: float = 1.5,
-         want_headers: bool = False, no_redirect: bool = False) -> dict:
+         want_headers: bool = False, no_redirect: bool = False,
+         byte_range: str | None = None) -> dict:
     host = urlparse(url).hostname or "unknown"
     afc = AuthFailCounter()
     if auth_key:
@@ -178,9 +192,14 @@ def send(method: str, url: str, headers: dict, data: bytes | None,
     sb = SessionBudget()
     sb.check()                         # 整场量熔断: 冷却期直接 abort(跨 host 总量/外渗)
 
+    req_headers = {"User-Agent": UA, **headers}
+    if byte_range and not any(k.lower() == "range" for k in req_headers):
+        req_headers["Range"] = _range_header_value(byte_range)
     req = urllib.request.Request(url=url, method=method.upper(),
-                                 data=data, headers={"User-Agent": UA, **headers})
+                                 data=data, headers=req_headers)
     summary: dict = {"method": method.upper(), "url": url}
+    if byte_range:
+        summary["range"] = _header_value(req_headers, "Range")
     opener = _opener(no_redirect)
     last_err: str | None = None
     raw = b""
@@ -344,6 +363,23 @@ def _selftest() -> int:
                 pass
 
             def do_GET(self):
+                if self.path.startswith("/range"):
+                    b = b"0123456789"
+                    if self.headers.get("Range") == "bytes=2-5":
+                        part = b[2:6]
+                        self.send_response(206)
+                        self.send_header("Content-Type", "text/plain")
+                        self.send_header("Content-Range", "bytes 2-5/10")
+                        self.send_header("Content-Length", str(len(part)))
+                        self.end_headers()
+                        self.wfile.write(part)
+                        return
+                    self.send_response(200)
+                    self.send_header("Content-Type", "text/plain")
+                    self.send_header("Content-Length", str(len(b)))
+                    self.end_headers()
+                    self.wfile.write(b)
+                    return
                 if self.path.startswith("/redir"):
                     # 模拟登录成功: 302 跳转, 会话 cookie 设在【这一跳】上(跟随跳转会丢失它)
                     self.send_response(302)
@@ -408,6 +444,17 @@ def _selftest() -> int:
             fr = send("GET", f"http://127.0.0.1:{port}/redir", {}, None, None, 5, want_headers=True)
             checks.append(("默认跟随 -> 200 且会话 cookie 丢(故认证流需 --no-redirect)",
                            fr.get("status") == 200 and "ApplicationCookie" not in "\n".join(fr.get("set_cookies", []))))
+            rr = send("GET", f"http://127.0.0.1:{port}/range", {}, None, None, 5,
+                      want_headers=True, byte_range="2-5")
+            checks.append(("--range sends Range header and receives partial body",
+                           rr.get("status") == 206 and rr.get("snippet") == "2345"
+                           and rr.get("headers", {}).get("Content-Range") == "bytes 2-5/10"
+                           and rr.get("range") == "bytes=2-5"))
+            rr2 = send("GET", f"http://127.0.0.1:{port}/range", {"range": "bytes=2-5"},
+                       None, None, 5, want_headers=True, byte_range="0-1")
+            checks.append(("--range respects caller-supplied Range header casing",
+                           rr2.get("status") == 206 and rr2.get("snippet") == "2345"
+                           and rr2.get("range") == "bytes=2-5"))
         finally:
             srv.shutdown()
     # 统一布局 _place_save: 裸文件名 + --run -> <run>/evidence/; 显式路径/无 --run 原样
@@ -471,6 +518,9 @@ def main() -> int:
     ap.add_argument("--no-redirect", action="store_true",
                     help="不跟随 3xx 跳转 —— 直接拿 302 那一跳(认证流会话 cookie 设在跳转上, 跟随会丢; "
                          "也防被跳转带到 scope 外)")
+    ap.add_argument("--range", dest="byte_range", default=None,
+                    help="HTTP byte range helper, e.g. 0-262143 or bytes=0-262143. "
+                         "Adds a Range header unless one was supplied explicitly.")
     ap.add_argument("--samples", type=int, default=1,
                     help="DIFF 模式每侧采样次数；>1 时做稳定性判定(去噪)")
     args = ap.parse_args()
@@ -504,7 +554,7 @@ def main() -> int:
             def sample(url: str) -> tuple[dict, bool, list]:
                 runs = [send("GET", url, headers, None, args.auth_key,
                              args.timeout, None, args.retry, args.retry_wait,
-                             args.headers) for _ in range(n)]
+                             args.headers, byte_range=args.byte_range) for _ in range(n)]
                 hs = sorted({r.get("sha1") for r in runs})
                 return runs[0], len(hs) == 1, hs
 
@@ -531,7 +581,8 @@ def main() -> int:
             out = {"tag": args.tag, **send(args.method, args.url, headers,
                                            data, args.auth_key, args.timeout,
                                            args.save, args.retry, args.retry_wait,
-                                           args.headers, args.no_redirect)}
+                                           args.headers, args.no_redirect,
+                                           args.byte_range)}
     except SessionTripped as e:
         out = {"error": f"session-volume-breaker: {e}"}
     except RateBudgetExceeded as e:
diff --git a/tools/workers.py b/tools/workers.py
index cd65514..ca35073 100644
--- a/tools/workers.py
+++ b/tools/workers.py
@@ -640,24 +640,72 @@ def create_agent_assignment(run_dir: Path, *, role: str, front: str,
 
 def _agent_status_from_file(path: Path) -> str:
     text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
-    return (_field(text, "Status") or "?").lower()
+    status = (_field(text, "Status") or "?").lower()
+    if _normalized_agent_status(status) in {"assigned", "working", "?"} and _has_completion_findings(text):
+        return "done (findings appended)"
+    return status
+
+
+def _has_completion_findings(text: str) -> bool:
+    m = re.search(r"(?ims)^##\s+Findings\b.*?(?=^##\s+|\Z)", text)
+    if not m:
+        return False
+    body = re.sub(r"(?m)^##\s+Findings\b.*$", "", m.group(0)).strip()
+    if not body:
+        return False
+    if re.search(r"(?i)\b(still investigating|pending|tbc|tbd|todo|placeholder|draft only)\b", body):
+        return False
+    structured = re.search(
+        r"(?im)^\s*[-*]\s*(Candidate|Phenomenon|Refutes|Evidence|Control|Artifact|Result|Verdict)\s*[:：]",
+        body,
+    )
+    plain_completion = re.search(
+        r"(?i)\b(no exploitable|no findings|not exploitable|refuted|auth[- ]?gated|blocked|complete|done)\b",
+        body,
+    )
+    return bool(structured or plain_completion)
+
+
+def _normalized_agent_status(status: str) -> str:
+    status_l = (status or "").strip().lower()
+    if status_l.startswith(("done", "complete", "completed")):
+        return "done"
+    if status_l.startswith("merged"):
+        return "merged"
+    if status_l.startswith("block"):
+        return "blocked"
+    if status_l.startswith("work"):
+        return "working"
+    if status_l.startswith("assign"):
+        return "assigned"
+    return status_l or "?"
 
 
 def agent_status_rows(run_dir: Path) -> list[dict]:
     data = load_assignments(run_dir)
     rows = []
+    changed = False
     for rec in data.get("assignments", []):
         if not isinstance(rec, dict):
             continue
         ap = ROOT / rec["agent_file"] if not Path(rec.get("agent_file", "")).is_absolute() else Path(rec["agent_file"])
         row = dict(rec)
         row["file_status"] = _agent_status_from_file(ap)
+        file_status_norm = _normalized_agent_status(row["file_status"])
+        rec_status_norm = _normalized_agent_status(str(rec.get("status") or ""))
+        if file_status_norm == "done" and rec_status_norm in {"assigned", "working", "?"}:
+            rec["status"] = "done"
+            rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
+            row["status"] = "done"
+            changed = True
         if ap.exists():
             text = ap.read_text(encoding="utf-8", errors="replace")
             row["parse_error"] = not (_field(text, "Role") and _field(text, "Assigned front"))
         else:
             row["parse_error"] = True
         rows.append(row)
+    if changed:
+        _atomic_write(_assignments_path(run_dir), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
     return rows
 
 
@@ -1258,6 +1306,44 @@ def _selftest() -> int:
     agent_clean.mkdir()
     create_agent_assignment(agent_clean, role="web-hunter", front="F-001")
     agent_clean_issues = agent_discipline_issues(agent_clean)
+    status_sync = d / "status_sync"
+    status_sync.mkdir()
+    sync_rec = create_agent_assignment(status_sync, role="web-hunter", front="F-001")
+    sync_file = ROOT / sync_rec["agent_file"] if not Path(sync_rec["agent_file"]).is_absolute() else Path(sync_rec["agent_file"])
+    sync_file.write_text(sync_file.read_text(encoding="utf-8").replace(
+        "- Status: assigned", "- Status: complete (candidate produced)"), encoding="utf-8")
+    sync_rows = agent_status_rows(status_sync)
+    sync_state = load_assignments(status_sync)
+    status_findings = d / "status_findings"
+    status_findings.mkdir()
+    findings_rec = create_agent_assignment(status_findings, role="web-hunter", front="F-002")
+    findings_file = ROOT / findings_rec["agent_file"] if not Path(findings_rec["agent_file"]).is_absolute() else Path(findings_rec["agent_file"])
+    findings_file.write_text(findings_file.read_text(encoding="utf-8") + "\n## Findings\n\n- Candidate: done\n", encoding="utf-8")
+    findings_rows = agent_status_rows(status_findings)
+    findings_state = load_assignments(status_findings)
+    status_blank_findings = d / "status_blank_findings"
+    status_blank_findings.mkdir()
+    blank_rec = create_agent_assignment(status_blank_findings, role="web-hunter", front="F-003")
+    blank_file = ROOT / blank_rec["agent_file"] if not Path(blank_rec["agent_file"]).is_absolute() else Path(blank_rec["agent_file"])
+    blank_file.write_text(blank_file.read_text(encoding="utf-8") + "\n## Findings\n\n", encoding="utf-8")
+    blank_rows = agent_status_rows(status_blank_findings)
+    blank_state = load_assignments(status_blank_findings)
+    status_negative_findings = d / "status_negative_findings"
+    status_negative_findings.mkdir()
+    neg_rec = create_agent_assignment(status_negative_findings, role="web-hunter", front="F-004")
+    neg_file = ROOT / neg_rec["agent_file"] if not Path(neg_rec["agent_file"]).is_absolute() else Path(neg_rec["agent_file"])
+    neg_file.write_text(neg_file.read_text(encoding="utf-8") + "\n## Findings\n\nNo exploitable issues found.\n", encoding="utf-8")
+    neg_rows = agent_status_rows(status_negative_findings)
+    neg_state = load_assignments(status_negative_findings)
+    status_placeholder_findings = d / "status_placeholder_findings"
+    status_placeholder_findings.mkdir()
+    placeholder_rec = create_agent_assignment(status_placeholder_findings, role="web-hunter", front="F-005")
+    placeholder_file = ROOT / placeholder_rec["agent_file"] if not Path(placeholder_rec["agent_file"]).is_absolute() else Path(placeholder_rec["agent_file"])
+    placeholder_file.write_text(
+        placeholder_file.read_text(encoding="utf-8") + "\n## Findings\n\n- Candidate: still investigating\n",
+        encoding="utf-8")
+    placeholder_rows = agent_status_rows(status_placeholder_findings)
+    placeholder_state = load_assignments(status_placeholder_findings)
     a_web = create_agent_assignment(run, role="web", front="F-002")
     a1 = create_agent_assignment(run, role="web-auth", front="F-001")
     a2 = create_agent_assignment(run, role="verify", front="F-001")
@@ -1319,6 +1405,21 @@ def _selftest() -> int:
         ("status command exits 0", status_cli_exit == 0),
         ("agent-check empty run exits 0", agent_check_empty_exit == 0),
         ("agent-check clean scaffold has no issues", agent_clean_issues == []),
+        ("status sync: complete file flips assignment to done",
+         sync_rows and sync_rows[0].get("status") == "done"
+         and sync_state["assignments"][0].get("status") == "done"),
+        ("status sync: Findings section flips assignment to done",
+         findings_rows and findings_rows[0].get("status") == "done"
+         and findings_state["assignments"][0].get("status") == "done"),
+        ("status sync: empty Findings section stays assigned",
+         blank_rows and blank_rows[0].get("status") == "assigned"
+         and blank_state["assignments"][0].get("status") == "assigned"),
+        ("status sync: negative Findings summary flips assignment to done",
+         neg_rows and neg_rows[0].get("status") == "done"
+         and neg_state["assignments"][0].get("status") == "done"),
+        ("status sync: investigatory placeholder stays assigned",
+         placeholder_rows and placeholder_rows[0].get("status") == "assigned"
+         and placeholder_state["assignments"][0].get("status") == "assigned"),
         ("role alias web uses web-hunter template", "Missing role template" not in web_context.read_text(encoding="utf-8")),
         ("agent assignment writes context pack", context_exists),
         ("assignments.json records agent", any(a.get("agent") == a1["agent"] for a in load_assignments(run)["assignments"])),
