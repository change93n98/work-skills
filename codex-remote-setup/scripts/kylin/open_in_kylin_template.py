"""Codex json_stdin file handler template. Render before installing. No shell interpolation of paths."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

TARGET_HOST = ''
TARGET_USER = ''
REMOTE_HELPER = ''


def ssh_alias(host):
    if not isinstance(host, dict) or host.get('kind') != 'ssh':
        raise ValueError('Kylin handler requires an SSH workspace')
    for item in [host, *[v for v in host.values() if isinstance(v, dict)]]:
        value = item.get('sshAlias')
        if isinstance(value, str) and value.strip():
            return value.strip()
    command = host.get('terminal_command')
    if isinstance(command, list) and command and isinstance(command[-1], str):
        return command[-1].strip()
    identifier = host.get('id', '')
    if isinstance(identifier, str) and identifier.startswith('remote-ssh-discovered:'):
        return identifier.split(':', 1)[1]
    name = host.get('name')
    if isinstance(name, str) and name.strip():
        return name.strip()
    raise ValueError('Missing SSH alias')


def ssh_executable():
    return str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/OpenSSH/ssh.exe')


def resolve_host(alias):
    if not alias or alias.startswith('-') or any(c.isspace() or ord(c) < 32 for c in alias):
        raise ValueError('Invalid SSH alias')
    result = subprocess.run([ssh_executable(), '-G', alias], capture_output=True, text=True,
                            timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    result.check_returncode()
    config = {}
    for row in result.stdout.splitlines():
        key, _, value = row.partition(' ')
        if key in ('hostname', 'user', 'port'):
            config[key] = value.strip()
    return config


def is_target_request(request):
    host = request.get('hostConfig')
    if not isinstance(host, dict) or host.get('kind') != 'ssh':
        return False
    alias = ssh_alias(host)
    resolved = resolve_host(alias)
    return resolved.get('hostname') == TARGET_HOST and resolved.get('user') == TARGET_USER


def normalized_request(request):
    alias = ssh_alias(request.get('hostConfig'))
    resolved = resolve_host(alias)
    if resolved.get('hostname') != TARGET_HOST or resolved.get('user') != TARGET_USER:
        raise ValueError('This handler does not match the requested SSH host and user')
    path = request.get('remotePath') or request.get('remoteWorkspaceRoot')
    if not isinstance(path, str) or not path.startswith('/') or any(ord(c) < 32 for c in path):
        raise ValueError('A remote absolute path without control characters is required')
    location = request.get('location') or {}
    line = int(location['line']) if location.get('line') is not None else 1
    column = int(location['column']) if location.get('column') is not None else 1
    if line < 1 or column < 1:
        raise ValueError('Line and column must be positive, one-based integers')
    return alias, {'path': path, 'location': {'line': line, 'column': column}}


def record(event):
    path = Path.home() / '.codex/logs/kylin-open.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'time': datetime.now().astimezone().isoformat(), **event}, ensure_ascii=False) + '\n')


def open_request(request, dry_run=False):
    alias, payload = normalized_request(request)
    command = [ssh_executable(), '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ClearAllForwardings=yes', alias, 'python3', REMOTE_HELPER]
    if dry_run:
        print(json.dumps({'command': command, 'stdin': payload}, ensure_ascii=False))
        return 0
    try:
        result = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                                text=True, encoding='utf-8', timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr)[-1800:])
        response = json.loads(result.stdout)
        if not response.get('ok'):
            raise RuntimeError(response.get('error', 'Remote editor did not confirm the request'))
        record({'route': 'kylin', 'ssh_alias': alias, 'request': payload, 'result': response,
                'target': request.get('target')})
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except Exception as error:
        record({'route': 'kylin', 'ssh_alias': alias, 'request': payload, 'error': str(error)})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    options = parser.parse_args()
    return open_request(json.load(sys.stdin), options.dry_run)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
