#!/usr/bin/env python3
"""Small, auditable wrapper for text captcha OCR attempts.

This tool is deliberately limited: it invokes local tesseract with argv lists
only, records empty results clearly, and never decides that a captcha is bypassed.
Use it to gather a few proof-level OCR attempts before declaring an OCR barrier.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


DEFAULT_PSMS = [7, 8, 13]


def _resolve_image(path: str | Path) -> tuple[Path | None, str]:
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=True)
    except FileNotFoundError:
        return None, f"image not found: {p}"
    except OSError as e:
        return None, f"image path error: {e}"
    if not p.is_file():
        return None, f"image is not a file: {p}"
    return p, ""


def _build_cmd(tesseract: str, image: Path, *, psm: int, lang: str) -> list[str]:
    return [tesseract, str(image), "stdout", "--psm", str(psm), "-l", lang]


def run_ocr(image_path: str | Path, *, tesseract: str | None = None,
            psms: list[int] | None = None, lang: str = "eng",
            timeout: int = 10) -> dict:
    image, err = _resolve_image(image_path)
    if err:
        return {"ok": False, "error": err, "attempts": []}
    exe = tesseract or shutil.which("tesseract")
    if not exe:
        return {
            "ok": False,
            "error": "tesseract not found; install it or pass --tesseract /absolute/path",
            "image": str(image),
            "attempts": [],
        }
    if not shutil.which(exe) and not Path(exe).expanduser().is_file():
        return {
            "ok": False,
            "error": f"tesseract not found: {exe}",
            "image": str(image),
            "attempts": [],
        }
    attempts = []
    for psm in (psms or DEFAULT_PSMS):
        cmd = _build_cmd(exe, image, psm=int(psm), lang=lang)
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            attempts.append({"psm": int(psm), "ok": False, "error": f"timeout >{timeout}s"})
            continue
        text = (proc.stdout or "").strip()
        attempts.append({
            "psm": int(psm),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "text": text,
            "empty": not bool(text),
            "stderr_tail": (proc.stderr or "")[-400:],
        })
    nonempty = [a for a in attempts if a.get("text")]
    return {
        "ok": True,
        "image": str(image),
        "tesseract": exe,
        "attempts": attempts,
        "best_text": nonempty[0]["text"] if nonempty else "",
        "all_empty": not bool(nonempty),
        "barrier_hint": (
            "all OCR attempts returned empty; after 3-5 attempts record this as an OCR barrier "
            "instead of continuing captcha guessing"
        ) if not nonempty else "",
    }


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    img = d / "captcha sample.png"
    img.write_bytes(b"not-really-an-image")
    fake_tess = d / "fake_tesseract.py"
    fake_tess.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8")
    fake_tess.chmod(0o755)
    resolved, err = _resolve_image(img)
    missing, missing_err = _resolve_image(d / "missing.gif")
    cmd = _build_cmd("/usr/bin/tesseract", img, psm=7, lang="eng")
    no_tess = run_ocr(img, tesseract=str(d / "missing-tesseract"), psms=[7])
    empty_ocr = run_ocr(img, tesseract=str(fake_tess), psms=[7, 8, 13])
    checks = [
        ("path with spaces resolves", resolved == img.resolve() and not err),
        ("missing image returns clear error", missing is None and "image not found" in missing_err),
        ("argv command keeps path as one argument", cmd[1] == str(img) and cmd[2] == "stdout"),
        ("missing tesseract is clear", no_tess["ok"] is False and "tesseract not found" in no_tess["error"]),
        ("all-empty OCR attempts produce barrier hint",
         empty_ocr["ok"] is True and empty_ocr["all_empty"] is True
         and "OCR barrier" in empty_ocr["barrier_hint"]),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("captcha_ocr selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="bounded text captcha OCR wrapper")
    ap.add_argument("image", nargs="?", help="captcha image path")
    ap.add_argument("--tesseract", help="tesseract executable path")
    ap.add_argument("--psm", action="append", type=int, help="tesseract PSM value; repeatable")
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.image:
        ap.error("image is required")
    result = run_ocr(
        args.image,
        tesseract=args.tesseract,
        psms=args.psm,
        lang=args.lang,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
