"""Open files through the current user's connected native Kylin extension host."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


def validate_request(request):
    path = request.get('path')
    if not isinstance(path, str) or not path.startswith('/') or any(ord(c) < 32 for c in path):
        raise ValueError('A remote absolute path without control characters is required')
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError('Remote path does not exist: ' + path)
    location = request.get('location') or {}
    line = int(location['line']) if location.get('line') is not None else 1
    column = int(location['column']) if location.get('column') is not None else 1
    if line < 1 or column < 1:
        raise ValueError('Line and column must be positive, one-based integers')
    return target, line, column


def find_ipc(server):
    process_ids = set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if args and args[0].decode(errors='replace') == str(server / 'node') and b'--type=extensionHost' in args:
                process_ids.add(int(proc.name))
        except OSError:
            continue
    result = subprocess.run(['ss', '-xlpn'], capture_output=True, text=True, timeout=5, check=True)
    sockets = set()
    for row in result.stdout.splitlines():
        pids = {int(pid) for pid in re.findall(r'pid=(\d+)', row)}
        if not pids.intersection(process_ids):
            continue
        match = re.search(r'(/\S*/vscode-ipc-[^\s]+\.sock)\s', row)
        if not match:
            continue
        path = Path(match[1])
        try:
            info = path.stat()
            if info.st_uid == os.getuid() and stat.S_ISSOCK(info.st_mode):
                sockets.add(str(path))
        except OSError:
            continue
    if not sockets:
        raise RuntimeError('No connected Kylin editor. Connect this node with Remote - Dev and open its project first.')
    if len(sockets) != 1:
        raise RuntimeError('Multiple Kylin editor sessions are connected. Keep one session for this node before opening files.')
    return sockets.pop()


def main():
    request = json.load(sys.stdin)
    path, line, column = validate_request(request)
    server = Path.home() / '.kylin-ide-server/server'
    ipc = find_ipc(server)
    command = [str(server / 'bin/remote-cli/kylin-ide-server'), '--reuse-window']
    if path.is_file():
        command += ['--goto', f'{path}:{line}:{column}']
    elif path.is_dir():
        command += [str(path)]
    else:
        raise ValueError('Only regular files and directories can be opened')
    env = os.environ.copy()
    env['VSCODE_IPC_HOOK_CLI'] = ipc
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    combined = result.stdout + result.stderr
    if result.returncode or 'Error when invoking' in combined or 'Command is only available' in combined:
        raise RuntimeError('Kylin CLI failed: ' + combined[-1500:])
    print(json.dumps({'ok': True, 'path': str(path), 'line': line, 'column': column,
                      'directory': path.is_dir(), 'ipc': ipc, 'cli_exit': result.returncode}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        raise SystemExit(1)
