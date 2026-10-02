#!/usr/bin/env python3
"""One bounded real request using the remote VS Code extension's Claude binary.

No keys or raw subprocess logs leave the target. This does not automate VS Code's
UI: reload the window and check a new conversation after it passes.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


def successful_result(returncode, stdout):
    for line in reversed(stdout.splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and result.get("type") == "result":
            return (returncode == 0 and result.get("is_error") is False
                    and str(result.get("result", "")).strip() == "OK")
    return False


def probe(cwd, timeout):
    home = Path.home()
    machine = json.loads((home / ".vscode-server/data/Machine/settings.json").read_text())
    settings = home / ".claude/settings.json"
    env = dict(os.environ)
    if settings.exists():
        env.update(json.loads(settings.read_text()).get("env", {}))
    env.update({x["name"]: x["value"] for x in machine.get("claudeCode.environmentVariables", [])})
    env["CLAUDE_CODE_ENTRYPOINT"] = "claude-vscode"
    binaries = list((home / ".vscode-server/extensions").glob(
        "anthropic.claude-code-*/resources/native-binary/claude"))
    if not binaries:
        return {"ok": False, "reason": "VS Code Claude binary not found"}
    binary = max(binaries, key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.parents[2].name)))
    args = [str(binary), "-p", "Reply only OK.", "--output-format", "json",
            "--max-turns", "1", "--tools", "", "--no-session-persistence",
            "--settings", '{"disableAllHooks":true}']
    try:
        r = subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "Claude request timed out"}
    ok = successful_result(r.returncode, r.stdout)
    return {"ok": ok, "client": "claude-vscode", "binary": str(binary),
            "exit_code": r.returncode,
            "reason": "real reply OK" if ok else "real request failed; inspect remote Claude logs with secrets redacted"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--host", help="SSH alias or host; prefer the alias from sync.py --list")
    target.add_argument("--wsl", help="local WSL distro")
    target.add_argument("--local", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cwd", default="/tmp", help="empty/safe remote directory, default /tmp")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60 seconds")
    if args.local:
        try:
            report = probe(args.cwd, args.timeout)
        except Exception as error:
            # Exception messages / CLI output can contain credentials.
            report = {"ok": False, "reason": type(error).__name__}
        print(json.dumps(report))
        return 0 if report["ok"] else 1
    remote_args = ["python3", "-", "--local", "--cwd", args.cwd, "--timeout", str(args.timeout)]
    if args.host:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               "-o", "ClearAllForwardings=yes", args.host, shlex.join(remote_args)]
    else:
        cmd = ["wsl.exe", "-d", args.wsl, "--", *remote_args]
    try:
        r = subprocess.run(cmd, input=Path(__file__).read_text(encoding="utf-8"),
                           text=True, encoding="utf-8", capture_output=True, timeout=args.timeout + 15)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"ok": False, "reason": type(error).__name__}))
        return 1
    # Emit only the structured report; SSH startup scripts may write arbitrary text.
    for line in reversed(r.stdout.splitlines()):
        try:
            report = json.loads(line)
            if isinstance(report, dict) and isinstance(report.get("ok"), bool):
                print(json.dumps(report))
                return 0 if r.returncode == 0 and report["ok"] else 1
        except ValueError:
            pass
    print(json.dumps({"ok": False, "reason": "remote probe did not return a report", "exit_code": r.returncode}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
