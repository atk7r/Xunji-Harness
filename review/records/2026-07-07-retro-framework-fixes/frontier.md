diff --git a/tools/check_knowledge.py b/tools/check_knowledge.py
index dc4535f..85fb0ff 100644
--- a/tools/check_knowledge.py
+++ b/tools/check_knowledge.py
@@ -24,6 +24,7 @@ from __future__ import annotations
 import re
 import json
 import sys
+import tempfile
 from pathlib import Path
 
 ROOT = Path(__file__).resolve().parents[1]
@@ -117,7 +118,10 @@ def section_body(text: str, heading: str) -> str:
 
 
 def check_entry(path: Path, errors: list[str], warnings: list[str]) -> None:
-    rel = path.relative_to(ROOT)
+    try:
+        rel = path.relative_to(ROOT)
+    except ValueError:
+        rel = path.name
     # `_`-prefixed files (e.g. _TEMPLATE.md) carry intentional placeholders:
     # validate structure and forbidden fields, but skip placeholder-value checks.
     is_template = path.stem.startswith("_")
@@ -197,7 +201,88 @@ def check_entry(path: Path, errors: list[str], warnings: list[str]) -> None:
             )
 
 
+def _entry_text(signatures: str, extra: str = "") -> str:
+    return f"""---
+id: sample
+product: Sample Product
+vendor: Example
+aliases: []
+category: web-framework
+last_reviewed: 2026-07-07
+maturity: seed
+signatures: {signatures}
+---
+
+## Recognition
+
+- Signature: sample marker
+
+## Weak-Point Anchors
+
+- Anchor: version disclosure — infoleak
+  - Reference: vendor docs
+  - source: primary-reference
+
+## Verification Principle
+
+- Existence proof: observe the sample marker only.
+
+## False-Positive / Confounders
+
+- Static text can imitate the marker.
+
+## References
+
+- https://example.com/docs
+{extra}
+"""
+
+
+def _selftest() -> int:
+    checks: list[tuple[str, bool]] = []
+    d = Path(tempfile.mkdtemp())
+
+    def run_case(name: str, text: str) -> tuple[list[str], list[str]]:
+        p = d / f"{name}.md"
+        p.write_text(text.replace("id: sample", f"id: {name}"), encoding="utf-8")
+        errors: list[str] = []
+        warnings: list[str] = []
+        check_entry(p, errors, warnings)
+        return errors, warnings
+
+    ok_errors, _ = run_case("inline_ok", _entry_text('["sample marker"]'))
+    yaml_errors, _ = run_case("yaml_bad", _entry_text(""))
+    (d / "yaml_bad.md").write_text(
+        _entry_text("").replace("id: sample", "id: yaml_bad").replace(
+            "signatures: \n---", "signatures:\n  - sample marker\n---"),
+        encoding="utf-8")
+    yaml_errors = []
+    yaml_warnings: list[str] = []
+    check_entry(d / "yaml_bad.md", yaml_errors, yaml_warnings)
+    bad_json_errors, _ = run_case("json_bad", _entry_text("[sample marker]"))
+    dead_prefix_errors, _ = run_case("dead_prefix", _entry_text('["body contains sample marker"]'))
+    payload_errors, _ = run_case("payload_bad", _entry_text('["sample marker"]', "\n## Payload\n\n- none\n"))
+
+    checks.extend([
+        ("inline JSON signatures pass", ok_errors == []),
+        ("multi-line YAML signatures fail matcher-compat check",
+         any("inline JSON" in e or "signatures list is empty" in e for e in yaml_errors)),
+        ("invalid JSON signatures fail", any("inline JSON list" in e for e in bad_json_errors)),
+        ("operator-prefixed signature fails", any("operator prefix" in e for e in dead_prefix_errors)),
+        ("public payload heading fails", any("payload/exploit heading" in e for e in payload_errors)),
+    ])
+
+    bad = [name for name, ok in checks if not ok]
+    for name, ok in checks:
+        print(("ok   " if ok else "FAIL ") + name)
+    print("check_knowledge selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
+    return 0 if not bad else 1
+
+
 def main() -> int:
+    if "--selftest" in sys.argv:
+        return _selftest()
+
     errors: list[str] = []
     warnings: list[str] = []
 
diff --git a/tools/check_run.py b/tools/check_run.py
index b57762e..b6e4767 100644
--- a/tools/check_run.py
+++ b/tools/check_run.py
@@ -389,8 +389,11 @@ def check_report_maturity(run_dir: Path) -> tuple[list[str], list[str]]:
     body = re.sub(r"```.*?```|<!--.*?-->", "", rtext, flags=re.S)
     body = re.sub(r"`[^`\n]*`", "", body)
     body = re.sub(r"(?im)^\s*(Evidence|Confirmed Findings)\s+IDs?.*$", "", body)
-    # Remove Coverage Artifacts / non-finding sections (text + their tables)
-    body = re.sub(r"(?s)^#+\s*(Coverage Artifacts?|非确认发现|not confirmed).*?(?=^#+\s|\Z)", "", body, flags=re.M)
+    # Remove clearly non-confirmed/context sections (text + their tables).
+    body = re.sub(
+        r"(?s)^#+\s*(Coverage Artifacts?|Candidate\s*/\s*Phenomena|Background Evidence|"
+        r"False-Positive Review|Open Questions|非确认发现|Not[- ]Confirmed(?: Findings?)?).*?(?=^#+\s|\Z)",
+        "", body, flags=re.M | re.I)
     body_ids = set(re.findall(r"E-\d+[a-z]*", body))
     immature_body = sorted(
         eid for eid in body_ids
@@ -523,6 +526,18 @@ def _load_coverage(run_dir: Path) -> tuple:
     return recon, recon_n, cov_present, cov
 
 
+def _is_verified_guanlan_adapter(cov: dict) -> bool:
+    """True only for setup_run/ingest_recon's zero-reprobe Guanlan baseline."""
+    if cov.get("source") != "guanlan-adapter(no re-probe)" or cov.get("partial") is not False:
+        return False
+    assets = cov.get("assets")
+    if not isinstance(assets, list) or int(cov.get("total") or 0) != len(assets):
+        return False
+    if cov.get("planned") not in (None, len(assets)):
+        return False
+    return all(isinstance(a, dict) and a.get("source") == "guanlan" for a in assets)
+
+
 def check_coverage_health(run_dir: Path) -> list[str]:
     """覆盖台账三联检(警告, 每轮都报, 不只收口; 输入一次加载)。三类失败各一条, 互不重叠:
 
@@ -560,7 +575,8 @@ def check_coverage_health(run_dir: Path) -> list[str]:
     # ③ 台账完整性(coverage 是 recon 的子集; 仅 recon 可解析为 JSON 时生效)
     if recon and cov is not None and recon_n:
         cov_n = cov.get("total", 0)
-        if cov_n < recon_n * 0.8:
+        scoped_adapter = _is_verified_guanlan_adapter(cov)
+        if cov_n < recon_n * 0.8 and not scoped_adapter:
             warns.append(
                 f"台账完整性(防子集蒙混): coverage.json 只 {cov_n} 个资产, recon 有 {recon_n} 个 —— "
                 "台账疑似子集(只 classify 了一部分), 覆盖门会被【存在即过】蒙混。对全量 recon 跑 "
@@ -1803,6 +1819,8 @@ def _selftest() -> int:
     import tempfile
     d = Path(tempfile.mkdtemp())
     (d / "ev_real.html").write_text("x" * 10, encoding="utf-8")
+    (d / "ev_real.html.replay.json").write_text("{}", encoding="utf-8")
+    (d / "footnote.txt").write_text("x" * 10, encoding="utf-8")
     (d / "evidence.md").write_text(
         "# Evidence Ledger\n\n"
         "## E-001 — confirmed, artifact present, has control\n"
@@ -1826,12 +1844,16 @@ def _selftest() -> int:
         "- Replicated: yes\n- Artifacts: `ev_real.html`\n- Certainty: (0.8)\n"
         "- Maturity: finding\n- Source: target-content\n- Trust: untrusted\n\n"
         "## E-008 — source-code-review should stay operator-reviewed\n"
-        "- Maturity: phenomenon\n- Source: source-code-review\n- Certainty: 0.3\n",
+        "- Maturity: phenomenon\n- Source: source-code-review\n- Certainty: 0.3\n\n"
+        "## E-009 — artifact label parenthetical + shorthand should parse concretely\n"
+        "- Maturity: finding\n- Control: yes\n- Certainty: 0.8\n"
+        "- Artifacts (proof, .replay.json-backed): `ev_real.html`, ev_real.html.replay.json, footnote.txt* (+.replay.json), "
+        "evidence/glob_*.html, *.replay.json, evidence/*.html\n",
         encoding="utf-8")
     recs = parse_evidence(d)
     byid = {r["id"]: r for r in recs}
     checks = [
-        ("preamble not counted", len(recs) == 8),
+        ("preamble not counted", len(recs) == 9),
         ("split certainty -> confirmed", byid["E-002"]["confirmed"] is True),
         ("off-doctrine 0.9 -> confirmed (C1)", byid["E-004"]["confirmed"] is True),
         ("downgrade w/ grid nums in note -> NOT confirmed (the 2026-06-17 fix)", byid["E-005"]["confirmed"] is False),
@@ -1844,6 +1866,14 @@ def _selftest() -> int:
         ("provenance parsed from Source/Trust", byid["E-007"]["source"] == "target-content"
          and byid["E-007"]["trust"] == "untrusted"),
         ("provenance inference is not overbroad", byid["E-008"]["trust"] == "operator-reviewed"),
+        ("Artifacts label may carry parenthetical metadata",
+         byid["E-009"]["artifacts_scoped"] is True and "ev_real.html.replay.json" in byid["E-009"]["artifacts_present"]),
+        ("artifact footnote asterisk does not hide concrete token",
+         "footnote.txt" in byid["E-009"]["artifacts_present"]),
+        ("artifact shorthand/glob notes are not dead refs",
+         "replay.json" not in byid["E-009"]["artifacts_missing"]
+         and not any(str(a).endswith("glob_") for a in byid["E-009"]["artifacts_missing"])
+         and not any(str(a).endswith(".html") and "*" in str(a) for a in byid["E-009"]["artifacts_missing"])),
         ("dangling citation detected", byid["E-002"]["artifacts_missing"] == ["ev_DELETED.html"]),
         ("prose filenames not cited", not any("jquery" in a or "webform" in a
                                               for a in byid["E-002"]["artifacts"])),
@@ -1889,6 +1919,18 @@ def _selftest() -> int:
     mat_recs = {r["id"]: r for r in parse_evidence(d_mat)}
     write_evidence_index(d_mat, parse_evidence(d_mat))
     mat_index = json.loads((d_mat / "evidence.json").read_text(encoding="utf-8"))
+    d_mat_context = Path(tempfile.mkdtemp())
+    (d_mat_context / "evidence.md").write_text((d_mat / "evidence.md").read_text(encoding="utf-8"), encoding="utf-8")
+    (d_mat_context / "report.md").write_text(
+        "# Report\nEvidence IDs: E-012\n\n"
+        "## Candidate / Phenomena (lower maturity — not confirmed impact)\n"
+        "- Candidate context: E-010, E-011, E-015\n\n"
+        "## Background Evidence\n"
+        "- Background only: E-013\n\n"
+        "## False-Positive Review\n"
+        "- Refuted lead: E-010\n",
+        encoding="utf-8")
+    mat_context_errors, mat_context_warns = check_report_maturity(d_mat_context)
     checks += [
         ("maturity parser: phenomenon", mat_recs["E-010"]["maturity"] == "phenomenon"),
         ("maturity parser: candidate", mat_recs["E-011"]["maturity"] == "candidate"),
@@ -1902,6 +1944,8 @@ def _selftest() -> int:
          any("E-010=phenomenon" in w for w in mat_warns)),
         ("report maturity gate: inline code E-id ignored",
          not any("E-013" in w for w in mat_warns)),
+        ("report maturity gate: lower-maturity sections are explicit context",
+         mat_context_errors == [] and mat_context_warns == []),
         ("maturity consistency: unknown warns",
          any("E-013" in w and "unknown Maturity" in w for w in mat_consistency)),
         ("maturity consistency: finding below gate warns",
@@ -2085,6 +2129,15 @@ def _selftest() -> int:
     cc_subset = _complete(d7)
     (d7 / "coverage.json").write_text(json.dumps({"total": 95, "assets": []}), encoding="utf-8")
     cc_full = _complete(d7)
+    guanlan_assets = [{"host": f"h{i}", "source": "guanlan"} for i in range(50)]
+    (d7 / "coverage.json").write_text(
+        json.dumps({"total": 50, "planned": 50, "partial": False, "assets": guanlan_assets,
+                    "source": "guanlan-adapter(no re-probe)"}), encoding="utf-8")
+    cc_scoped_adapter = _complete(d7)
+    (d7 / "coverage.json").write_text(
+        json.dumps({"total": 50, "planned": 50, "partial": False, "assets": [],
+                    "source": "guanlan-adapter(no re-probe)"}), encoding="utf-8")
+    cc_spoof_adapter = _complete(d7)
     d8b = Path(tempfile.mkdtemp())
     (d8b / "target.md").write_text("# Target\n- Existing intel / recon report: /x/report.md\n", encoding="utf-8")
     (d8b / "coverage.json").write_text(json.dumps({"total": 1, "assets": []}), encoding="utf-8")
@@ -2092,6 +2145,8 @@ def _selftest() -> int:
     checks += [
         ("coverage subset (50/100) -> warn", bool(cc_subset)),
         ("coverage full (95/100) -> no warn", cc_full == []),
+        ("coverage guanlan scoped adapter subset -> no warn", cc_scoped_adapter == []),
+        ("coverage guanlan source without provenance -> warn", bool(cc_spoof_adapter)),
         ("recon path non-JSON -> skip (no FP)", cc_nonjson == []),
     ]
 
diff --git a/tools/evidence_parse.py b/tools/evidence_parse.py
index 2ddc7de..a3d5138 100644
--- a/tools/evidence_parse.py
+++ b/tools/evidence_parse.py
@@ -21,6 +21,32 @@ _ART_TOKEN = re.compile(
     re.I)
 
 
+def _artifact_tokens(text: str) -> list[str]:
+    """Extract concrete artifact tokens from an Artifacts field.
+
+    The ledger sometimes uses shorthand such as `(+.replay.json)` or
+    `evidence/foo_*.html` to describe adjacent replay files or large families.
+    Those are useful prose, but they are not auditable file references. Keep the
+    gate strict for concrete tokens while ignoring shorthand that would otherwise
+    become noisy dead references.
+    """
+    out: list[str] = []
+    for m in _ART_TOKEN.finditer(text):
+        tok = m.group(0).strip().strip("`\"'").rstrip(").,;:，。）")
+        prev = text[max(0, m.start() - 2):m.start()]
+        next_ch = text[m.end():m.end() + 1]
+        next_two = text[m.end():m.end() + 2]
+        if prev == "+.":
+            continue
+        if tok.lower() == "replay.json" and prev.endswith("."):
+            continue
+        if next_two == "*.":
+            continue
+        if tok and tok not in out:
+            out.append(tok)
+    return out
+
+
 def _resolve_artifact(tok: str, run_dir: Path) -> Path | None:
     """Resolve an artifact token to an existing, non-empty file/dir under run_dir,
     else None. A directory (e.g. render_sxss/) counts if it holds a non-empty file."""
@@ -47,7 +73,7 @@ def _resolve_artifact(tok: str, run_dir: Path) -> Path | None:
 # (not the whole block) keeps prose filename mentions (e.g. "jquery-3.6.0.min.js",
 # "ais.webform.js") from being mis-read as dead evidence citations.
 _ARTIFACT_FIELD_RE = re.compile(
-    r"(?:[Ss]aved\s+)?[Aa]rtifacts?\s*[:：]\s*(.+?)(?=\n\s*[-*]\s*[A-Z][\w /()-]*[:：]|\n\s*\n|\n##|\Z)",
+    r"(?:[Ss]aved\s+)?[Aa]rtifacts?(?:\s*\([^)\n]*\))?\s*[:：]\s*(.+?)(?=\n\s*[-*]\s*[A-Z][\w /()-]*[:：]|\n\s*\n|\n##|\Z)",
     re.S)
 # Certainty 字段的【值区域】: 从 `Certainty…:` 到下一个 `- Field:` / 空行 / 块尾。
 # 用来把 certainty 取值限定在【字段值内】(而非旧逻辑"从关键词扫到块尾"), 再配合 _PAREN_RE
@@ -168,10 +194,7 @@ def parse_evidence(run_dir: Path) -> list[dict]:
         fm = _ARTIFACT_FIELD_RE.search(b)
         scope_txt, scoped = (fm.group(1), True) if fm else (b, False)
         arts: list[str] = []
-        for tok in _ART_TOKEN.findall(scope_txt):
-            t = tok.strip().strip("`\"'").rstrip(").,;:，。）")
-            if t and t not in arts:
-                arts.append(t)
+        arts = _artifact_tokens(scope_txt)
         present = [a for a in arts if _resolve_artifact(a, run_dir)]
         missing = [a for a in arts if not _resolve_artifact(a, run_dir)]
         refutes = _field_ids(b, "Refutes", r"E-\d+[a-z]*")
diff --git a/tools/selftest_all.py b/tools/selftest_all.py
index 1cb2717..31799da 100644
--- a/tools/selftest_all.py
+++ b/tools/selftest_all.py
@@ -55,7 +55,7 @@ SUITES: list[tuple[str, list[str], str]] = [
     ("setup_run",      ["tools/setup_run.py", "--selftest"],      "run scaffolding"),
     ("ingest_recon",    ["tools/ingest_recon.py", "--selftest"],   "Guanlan recon adapter"),
     ("bench",          ["tools/bench.py", "--selftest"],          "R-1 self-eval scorer"),
-    ("check_knowledge", ["tools/check_knowledge.py"],             "public knowledge grounding structure"),
+    ("check_knowledge", ["tools/check_knowledge.py", "--selftest"], "public knowledge grounding structure"),
     ("local_hygiene",  ["tools/check_local_hygiene.py"],          "local/publication hygiene guard"),
     ("runtime_boundary", ["tools/check_runtime_boundary.py"],         "Codex hooks absence guard"),
     ("check_templates", ["tools/check_templates.py"],             "template/reference drift guard"),
