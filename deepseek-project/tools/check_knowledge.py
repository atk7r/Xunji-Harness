"""Structural and anti-weaponization check for the grounding knowledge base.

This enforces the contract in knowledge/README.md: each entry must carry
recognition signatures, weak-point anchors (class + reference + source), a
safe-verification principle, and confounders — and must NOT carry payloads,
exploit steps, or PoC. The check is structural; it does not certify that a cited
CVE/CNVD is real or that an anchor is correct.

Hard failures: missing/extra structure, missing frontmatter, an anchor without a
Reference or source tag, a forbidden weaponization heading/field, bad maturity
or date. Payload-shaped strings only WARN (they may be legitimate recognition
signatures), flagging drift toward a payload library for human review.

Pure stdlib. Run: python tools/check_knowledge.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"

# Files that are not entries.
SKIP_NAMES = {"README.md"}

REQUIRED_SECTIONS = [
    "## Recognition",
    "## Weak-Point Anchors",
    "## Safe-Verification Principle",
    "## False-Positive / Confounders",
    "## References",
]

REQUIRED_FRONTMATTER = ["id", "product", "maturity", "last_reviewed"]
VALID_MATURITY = {"seed", "verified", "stale"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Forbidden as a markdown heading or frontmatter key — these turn an entry into a
# weapon. Matched against headings/keys only, not prose (citing "a public exploit
# exists" is allowed; a `## Exploit` / `payload:` block is not).
FORBIDDEN_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*(payload|payloads|exploit|exploitation|exploit chain|steps|"
    r"step-by-step|poc|proof of concept|request body|raw request)\b",
    re.IGNORECASE,
)
FORBIDDEN_KEY_RE = re.compile(
    r"^\s*(payload|payloads|exploit|steps|poc|request|request_body|rawrequest)\s*:",
    re.IGNORECASE,
)

# Payload-shaped strings → WARN only (could be a legitimate recognition signature).
PAYLOAD_SHAPE_PATTERNS = [
    re.compile(r"union\s+select", re.IGNORECASE),
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"\$\{jndi:", re.IGNORECASE),
    re.compile(r"/etc/passwd"),
    re.compile(r"/dev/tcp/"),
    re.compile(r"eval\s*\(\s*\$_", re.IGNORECASE),
    re.compile(r"<\?php"),
    re.compile(r"\.\./\.\./"),
    re.compile(r"'\s*or\s*'1'\s*=\s*'1", re.IGNORECASE),
    re.compile(r"\bsleep\s*\(\s*\d", re.IGNORECASE),
]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body). Minimal YAML: top-level `key: value`."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_block, body = parts[1], parts[2]
    fm: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm, body


def split_anchors(weak_section: str) -> list[str]:
    """Split the Weak-Point Anchors section into per-anchor blocks."""
    blocks: list[str] = []
    current: list[str] = []
    for line in weak_section.splitlines():
        if re.match(r"^\s*-\s+Anchor:", line, re.IGNORECASE):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def section_body(text: str, heading: str) -> str:
    """Return text from `heading` up to the next `## ` heading."""
    idx = text.find(heading)
    if idx == -1:
        return ""
    rest = text[idx + len(heading):]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def check_entry(path: Path, errors: list[str], warnings: list[str]) -> None:
    rel = path.relative_to(ROOT)
    # `_`-prefixed files (e.g. _TEMPLATE.md) carry intentional placeholders:
    # validate structure and forbidden fields, but skip placeholder-value checks.
    is_template = path.stem.startswith("_")
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)

    # Frontmatter
    if not fm:
        errors.append(f"{rel}: missing or malformed frontmatter")
    elif not is_template:
        for key in REQUIRED_FRONTMATTER:
            if key not in fm or not fm[key]:
                errors.append(f"{rel}: frontmatter missing '{key}'")
        if fm.get("id") and fm["id"] != path.stem:
            errors.append(f"{rel}: frontmatter id '{fm['id']}' != filename '{path.stem}'")
        if fm.get("maturity") and fm["maturity"] not in VALID_MATURITY:
            errors.append(f"{rel}: invalid maturity '{fm['maturity']}'")
        if fm.get("last_reviewed") and not DATE_RE.match(fm["last_reviewed"]):
            errors.append(f"{rel}: last_reviewed not YYYY-MM-DD")

    # Required sections
    for heading in REQUIRED_SECTIONS:
        if heading not in text:
            errors.append(f"{rel}: missing section '{heading}'")

    # Forbidden weaponization headings / keys
    for line in text.splitlines():
        if FORBIDDEN_HEADING_RE.match(line) or FORBIDDEN_KEY_RE.match(line):
            errors.append(f"{rel}: forbidden weaponization heading/field -> {line.strip()!r}")

    # Each anchor needs a Reference and a source tag (skip the template's example).
    weak = section_body(text, "## Weak-Point Anchors")
    anchors = split_anchors(weak)
    if not is_template and fm.get("maturity") == "verified" and not anchors:
        errors.append(f"{rel}: maturity 'verified' but no anchors")
    for i, block in enumerate(anchors, 1):
        if not is_template:
            if not re.search(r"reference\s*:", block, re.IGNORECASE):
                errors.append(f"{rel}: anchor #{i} has no Reference")
            if not re.search(r"source\s*:", block, re.IGNORECASE):
                errors.append(f"{rel}: anchor #{i} has no source tag")

    # Payload-shape tripwire (WARN only)
    for pattern in PAYLOAD_SHAPE_PATTERNS:
        m = pattern.search(body)
        if m:
            warnings.append(
                f"{rel}: payload-shaped string {m.group(0)!r} — confirm it is a "
                f"recognition signature, not a payload"
            )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not KNOWLEDGE.exists():
        print("knowledge check passed (no knowledge/ dir yet)")
        return 0

    if not (KNOWLEDGE / "README.md").exists():
        errors.append("knowledge/README.md missing (the grounding-not-weapon contract)")

    entries = [
        p for p in sorted(KNOWLEDGE.glob("*.md")) if p.name not in SKIP_NAMES
    ]
    for path in entries:
        check_entry(path, errors, warnings)

    if warnings:
        print("warnings")
        for w in warnings:
            print(f"- {w}")

    if errors:
        print("knowledge check failed")
        for e in errors:
            print(f"- {e}")
        return 1

    print(f"knowledge check passed ({len(entries)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
