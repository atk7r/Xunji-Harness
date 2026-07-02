#!/usr/bin/env python3
"""Transform an operator-supplied string into encoding/container variants.

This is not a payload list and not a scanner. It mutates exactly the input string
the driver provides, so it helps test parser/normalization behavior without
turning Xunji into a playbook.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.parse
import xml.sax.saxutils
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import print_json, write_artifact  # noqa: E402


def variants(value: str) -> list[dict]:
    out: list[dict] = []

    def add(kind: str, v: str, note: str = "") -> None:
        if not any(x["value"] == v and x["kind"] == kind for x in out):
            out.append({"kind": kind, "value": v, "note": note})

    add("raw", value, "original operator-supplied value")
    add("url", urllib.parse.quote(value, safe=""), "percent-encoded")
    add("url_plus", urllib.parse.quote_plus(value), "form-style percent-encoding")
    add("double_url", urllib.parse.quote(urllib.parse.quote(value, safe=""), safe=""), "double percent-encoded")
    add("base64", base64.b64encode(value.encode()).decode(), "base64 of original bytes")
    add("hex", value.encode().hex(), "hex of original bytes")
    add("json_string", json.dumps(value, ensure_ascii=False), "JSON string literal")
    add("json_body", json.dumps({"value": value}, ensure_ascii=False), "minimal JSON object wrapper")
    add("xml_text", f"<value>{xml.sax.saxutils.escape(value)}</value>", "minimal XML text wrapper")
    add("form_body", urllib.parse.urlencode({"value": value}), "application/x-www-form-urlencoded wrapper")
    add("upper", value.upper(), "case variant")
    add("lower", value.lower(), "case variant")

    if "/" in value or "\\" in value or "." in value:
        slash = value.replace("\\", "/")
        add("path_slash_normalized", slash, "backslash to slash")
        add("path_dot_collapsed_probe", slash.replace("../", "./../"), "normalization-sensitive path variant")
        add("path_url", urllib.parse.quote(slash, safe="/"), "path-preserving percent encoding")
    return out


def build_output(value: str) -> dict:
    vs = variants(value)
    return {
        "candidate": True,
        "input": value,
        "variants": vs,
        "count": len(vs),
        "control": "Use raw input as baseline and one transformed value as mutant.",
        "replicated": "Not applicable: transform-only sensor; active proof belongs in probe/blind_diff.",
        "note": "Transforms only the supplied string; no vulnerability payload list is embedded.",
    }


def _selftest() -> int:
    data = build_output("../A b")
    kinds = {v["kind"] for v in data["variants"]}
    checks = [
        ("raw present", "raw" in kinds),
        ("url present", "url" in kinds),
        ("json wrapper present", "json_body" in kinds),
        ("path variant present", "path_url" in kinds),
        ("no empty variants", all(v["value"] for v in data["variants"])),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("mutate_payload selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate encoding/container variants for a supplied value.")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--run", help="run dir; writes artifact under <run>/evidence/sensors/")
    ap.add_argument("--tag", default="mutations")
    ap.add_argument("--out", type=Path, help="explicit JSON output path")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.value is None:
        ap.error("value is required")
    data = build_output(args.value)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        data["artifact"] = str(args.out)
        args.out.write_text(json.dumps({"sensor": "mutate_payload", **data}, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        args.out.chmod(0o600)
    elif args.run:
        path = write_artifact(args.run, "mutate_payload", args.tag, data)
        data["artifact"] = str(path)
    print_json({"sensor": "mutate_payload", **data})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
