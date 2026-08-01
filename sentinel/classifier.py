"""sentinel.classifier — locus + provenance attribution (Phase 1, keyword-based).

The core of "tell the operator's own cleanup apart from behavior to scrutinize":
classify each action by WHERE it acts (locus) and WHO triggered it (provenance),
never by the agent's self-report. See the design doc / CaMeL provenance principle.
"""

from __future__ import annotations

import re

# locus
LOCAL_WORKSPACE = "LOCAL_WORKSPACE"
TARGET = "TARGET"
LOCAL_OTHER = "LOCAL_OTHER"
UNKNOWN = "UNKNOWN"
# provenance
OPERATOR_DIRECTED = "OPERATOR_DIRECTED"
PLAN_DERIVED = "PLAN_DERIVED"
TARGET_DERIVED = "TARGET_DERIVED"
UNATTRIBUTED = "UNATTRIBUTED"

_URL_RE = re.compile(r"\b(?:https?|ftp)://([^/\s:'\"]+)", re.I)
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_REMOTE_TOOL = re.compile(r"\b(curl|wget|nc|ncat|socat)\b|probe\.py|render\.py|scan\.py", re.I)
# a path-looking token: starts with / ~ ./ ../ or drive, or contains a slash
_PATH_RE = re.compile(r"(?<!\w)(?:~|\$HOME|/[^\s;,|&'\"]*|\.{1,2}/[^\s;,|&'\"]*|[A-Za-z]:[\\/][^\s;,|&'\"]*|[\w.\-]+/[^\s;,|&'\"]*)")
_SYS_DIR = re.compile(r"^(?:/(?:bin|sbin|boot|dev|etc|lib|lib64|proc|root|sys|usr|var|home|opt|srv|mnt)\b|/$|~|\$HOME|[A-Za-z]:[\\/]?$|/[a-z]$)", re.I)
# 重定向汇/源(2>/dev/null 之类): 不是动作的操作对象, 不该参与 locus 判定 —— 否则 `rm runs/x 2>/dev/null`
# 因 /dev/null 是系统路径被误判 LOCAL_OTHER → 把"清理自己 scratch"当 L4 销毁(mokwon dogfood #11)。
_REDIR_SINK = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/zero", "/dev/tty"}


# verbs that operate on the local working tree (not a remote target) unless a
# remote URL is also present — so a local repo/history rewrite is workspace-locus
# even when it carries no filesystem-path token (e.g. `git filter-repo --path x`).
_LOCAL_VERBS = {"git", "npm", "pnpm", "yarn", "pip", "make", "cargo", "go",
                "mvn", "gradle", "poetry", "rmdir"}


def normalize_action(tool: str, command: str) -> dict:
    command = command or ""
    urls = _URL_RE.findall(command)
    hosts = set(h.lower() for h in urls) | set(_IP_RE.findall(command))
    remote = bool(urls) or (bool(_REMOTE_TOOL.search(command)) and bool(hosts))
    paths = [p for p in _PATH_RE.findall(command)
             if not p.lower().startswith(("http", "ftp"))
             and p.strip("'\"").lower() not in _REDIR_SINK]
    verb = command.split()[0].lower() if command.split() else ""
    return {"tool": tool, "command": command, "urls": urls, "verb": verb,
            "hosts": sorted(hosts), "remote": remote, "paths": paths}


def _is_system_path(p: str) -> bool:
    return bool(_SYS_DIR.match(p.strip().strip("'\"")))


def _salient_tokens(command: str) -> list[str]:
    """Tokens that identify what the action targets: the verb + path strings +
    path basenames + non-flag words >=3 chars. Used for keyword attribution."""
    toks: set[str] = set()
    words = command.split()
    if words:
        toks.add(words[0].lower())                         # the verb (rm, git, curl...)
    if len(words) > 1 and words[0].lower() == "git":
        toks.add(words[1].lower())                         # git subcommand
    for p in _PATH_RE.findall(command):
        p = p.strip("'\"")
        toks.add(p.lower())
        toks.add(p.rstrip("/").split("/")[-1].lower())     # basename
    for w in words:
        w = w.strip("'\"").lower()
        if len(w) >= 3 and not w.startswith("-"):
            toks.add(w)
    return [t for t in toks if t]


def _host_in_scope(hosts: list, scope: set) -> bool:
    """A host is in scope if it equals an in-scope host OR is a SUBDOMAIN of one
    (api.example.com is in scope when example.com is). The leading-dot suffix check
    prevents look-alike confusion (evil-example.com / example.com.evil.com do NOT match
    '.example.com'). Without this, every subdomain of an apex-only scope was flagged
    out-of-scope -> false scope_drift (a real-run defect, 2nd layer)."""
    for h in hosts:
        h = (h or "").lower()
        for s in scope:
            if h == s or h.endswith("." + s):
                return True
    return False


def classify(action: dict, ctx: dict) -> dict:
    """ctx = {scope_hosts:set, directives:[str], plan_keywords:[str], taint:bool}"""
    scope = {h.lower() for h in ctx.get("scope_hosts", set())}
    paths = action.get("paths", [])

    # --- locus ---
    if action.get("remote") or action.get("hosts"):
        locus = TARGET
    elif action.get("verb") in _LOCAL_VERBS:
        locus = LOCAL_WORKSPACE                 # local repo/tooling op (e.g. git history rewrite)
    elif paths and all(not _is_system_path(p) for p in paths):
        locus = LOCAL_WORKSPACE
    elif paths:
        locus = LOCAL_OTHER
    else:
        locus = UNKNOWN

    # --- provenance ---
    salient = _salient_tokens(action.get("command", ""))
    directives = " \n ".join(ctx.get("directives", [])).lower()
    plan_kw = set(ctx.get("plan_keywords", []))
    host_in_scope = _host_in_scope(action.get("hosts", []), scope)

    if ctx.get("taint"):
        provenance = TARGET_DERIVED
    elif any(len(t) >= 3 and t in directives for t in salient):
        provenance = OPERATOR_DIRECTED
    elif host_in_scope or any(t in plan_kw for t in salient):
        provenance = PLAN_DERIVED
    else:
        provenance = UNATTRIBUTED

    return {"locus": locus, "provenance": provenance,
            "host_in_scope": host_in_scope, "salient": salient}
