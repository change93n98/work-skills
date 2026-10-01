#!/usr/bin/env python3
"""Configure local SSH and remote Codex for a local HTTP proxy; stdlib only."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile

HEADER = re.compile(r'^[ \t]*(Host|Match)[ \t]+([^\r\n]+)', re.I)
ALIAS = re.compile(r'[A-Za-z0-9_.-]+\Z')
BEGIN = '# >>> Codex SSH proxy >>>'
END = '# <<< Codex SSH proxy <<<'


def blocks(text):
    lines = text.splitlines(keepends=True)
    starts = []
    for i, line in enumerate(lines):
        match = HEADER.match(line)
        if match:
            starts.append((i, match[1].lower(), match[2].split('#', 1)[0].split()))
    return lines, [(i, starts[n + 1][0] if n + 1 < len(starts) else len(lines), kind, names)
                   for n, (i, kind, names) in enumerate(starts)]


def inventory(text):
    lines, parsed = blocks(text)
    result = []
    for start, end, kind, names in parsed:
        if kind != 'host':
            continue
        hostname = None
        for line in lines[start + 1:end]:
            match = re.match(r'^[ \t]*HostName[ \t]+(\S+)', line, re.I)
            if match:
                hostname = match[1]
                break
        for name in names:
            if ALIAS.fullmatch(name):
                result.append({'alias': name, 'hostname': hostname,
                               'single_alias_block': len(names) == 1})
    return result


def rewrite(text, nodes, local_port, remote_port):
    lines, parsed = blocks(text)
    newline = '\r\n' if '\r\n' in text else '\n'
    output, cursor, seen = [], 0, set()
    for start, end, kind, names in parsed:
        output.extend(lines[cursor:start])
        selected = set(names).intersection(nodes) if kind == 'host' else set()
        if not selected:
            output.extend(lines[start:end])
        else:
            if len(names) != 1:
                raise ValueError('Split multi-alias Host blocks first: ' + ' '.join(names))
            node = names[0]
            if node in seen:
                raise ValueError('Duplicate Host block: ' + node)
            seen.add(node)
            output.append(lines[start].rstrip('\r\n') + newline)
            output.extend('    ' + line + newline for line in [
                BEGIN,
                'RemoteForward 127.0.0.1:%d 127.0.0.1:%d' % (remote_port, local_port),
                'ServerAliveInterval 30', 'ServerAliveCountMax 3',
                'ExitOnForwardFailure no', END])
            managed = False
            for line in lines[start + 1:end]:
                if line.strip() == BEGIN:
                    if managed:
                        raise ValueError('Nested proxy markers in ' + node)
                    managed = True
                    continue
                if line.strip() == END:
                    if not managed:
                        raise ValueError('Unmatched proxy marker in ' + node)
                    managed = False
                    continue
                if managed:
                    continue
                if re.match(r'^\s*(ServerAliveInterval|ServerAliveCountMax|ExitOnForwardFailure)\s+', line, re.I):
                    continue
                match = re.match(r'^\s*RemoteForward\s+(\S+)\s+', line, re.I)
                if match and match[1].split(':')[-1] == str(remote_port):
                    continue
                output.append(line)
            if managed:
                raise ValueError('Unclosed proxy marker in ' + node)
        cursor = end
    output.extend(lines[cursor:])
    if seen != set(nodes):
        raise ValueError('Some selected aliases are not explicit Host blocks')
    return ''.join(output)


def effective(config, node, local_port, remote_port):
    result = subprocess.run(['ssh', '-F', str(config), '-G', node],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
    if result.returncode:
        raise RuntimeError('SSH configuration is invalid for ' + node)
    lines = {line.replace('[', '').replace(']', '') for line in result.stdout.splitlines()}
    expected = 'remoteforward 127.0.0.1:%d 127.0.0.1:%d' % (remote_port, local_port)
    if expected not in lines:
        raise RuntimeError('Expected loopback RemoteForward is absent for ' + node)
    for value in ['serveraliveinterval 30', 'serveralivecountmax 3', 'exitonforwardfailure no']:
        if value not in lines:
            raise RuntimeError('Earlier SSH options override the managed setting: ' + value)


def save_config(config, original_bytes, content, nodes, local_port, remote_port):
    fd, name = tempfile.mkstemp(prefix='config.codex-validate-', dir=str(config.parent))
    staged = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        for node in nodes:
            effective(staged, node, local_port, remote_port)
        if config.read_bytes() != original_bytes:
            raise RuntimeError('SSH config changed concurrently; rerun against the new file')
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = config.with_name(config.name + '.bak.codex-ssh-proxy-' + stamp)
        shutil.copy2(config, backup)
        # Write through the existing file to preserve its Windows ACL / Unix mode.
        try:
            config.write_bytes(content)
        except Exception:
            config.write_bytes(original_bytes)
            raise
        print('SSH_BACKUP', backup, flush=True)
    finally:
        staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-config', type=Path, default=Path.home() / '.ssh/config')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--nodes', nargs='+', help='Exact SSH Host aliases')
    selection.add_argument('--all', action='store_true', help='Explicitly select all configured aliases')
    parser.add_argument('--list', action='store_true', help='List aliases without connecting or changing files')
    parser.add_argument('--local-proxy-port', type=int, default=10808)
    parser.add_argument('--remote-proxy-port', type=int, default=18080)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check-only', action='store_true')
    modes.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config = args.ssh_config.expanduser().resolve(strict=True)
    original_bytes = config.read_bytes()
    original = original_bytes.decode('utf-8-sig')
    hosts = inventory(original)
    if args.list or (not args.nodes and not args.all):
        print(json.dumps(hosts, ensure_ascii=False, indent=2))
        if not args.list:
            print('Select --nodes ALIAS ... or --all to configure; no files were changed.')
        return 0
    nodes = list(dict.fromkeys(args.nodes or [host['alias'] for host in hosts]))
    available = {host['alias'] for host in hosts}
    if not nodes or any(not ALIAS.fullmatch(node) or node not in available for node in nodes):
        raise ValueError('Select known, explicit SSH Host aliases; run --list first')
    for port in [args.local_proxy_port, args.remote_proxy_port]:
        if not 1024 <= port <= 65535:
            raise ValueError('Proxy ports must be between 1024 and 65535')
    updated = rewrite(original, nodes, args.local_proxy_port, args.remote_proxy_port)
    if args.dry_run:
        print(json.dumps({'nodes': nodes, 'ssh_config_changed': updated != original,
                          'local_proxy_port': args.local_proxy_port,
                          'remote_proxy_port': args.remote_proxy_port}, indent=2))
        return 0
    if not shutil.which('ssh'):
        raise RuntimeError('OpenSSH ssh must be on PATH')
    with socket.create_connection(('127.0.0.1', args.local_proxy_port), timeout=3):
        pass
    if not args.check_only and updated != original:
        encoded = updated.encode('utf-8')
        if original_bytes.startswith(b'\xef\xbb\xbf'):
            encoded = b'\xef\xbb\xbf' + encoded
        save_config(config, original_bytes, encoded, nodes, args.local_proxy_port, args.remote_proxy_port)
    for node in nodes:
        effective(config, node, args.local_proxy_port, args.remote_proxy_port)
    remote_source = Path(__file__).with_name('configure_remote.py').read_bytes()
    failed = []
    for node in nodes:
        print('NODE', node, flush=True)
        command = ['ssh', '-F', str(config), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                   '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3',
                   node, 'python3', '-', str(args.remote_proxy_port),
                   'check' if args.check_only else 'configure']
        try:
            result = subprocess.run(command, input=remote_source, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=120)
            print(result.stdout.decode('utf-8', errors='replace'), end='', flush=True)
            if result.stderr:
                print(result.stderr.decode('utf-8', errors='replace'), end='', file=sys.stderr)
            if result.returncode:
                failed.append(node)
        except subprocess.TimeoutExpired:
            print('SSH operation timed out for ' + node, file=sys.stderr)
            failed.append(node)
    if failed:
        raise RuntimeError('Failed nodes: ' + ', '.join(failed) + '. Successful nodes remain configured; retry only failed targets.')
    print('DONE: keep the local proxy online, reconnect SSH / Remote-SSH, then reload the VS Code window.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print('ERROR:', error, file=sys.stderr)
        raise SystemExit(1)
