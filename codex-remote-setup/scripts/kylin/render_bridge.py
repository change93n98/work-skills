"""Render a private, per-node Kylin bridge instance without editing live config."""
import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import sys


def render(host, user, remote_home, output_dir, handler_id='kylin-remote', python=None, force=False):
    for name, value in [('host', host), ('user', user)]:
        if not value or value.startswith('-') or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError(f'Invalid {name}')
    if not remote_home.startswith('/') or any(ord(c) < 32 for c in remote_home):
        raise ValueError('remote-home must be an absolute POSIX path without control characters')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', handler_id):
        raise ValueError('Invalid handler ID')
    output = Path(output_dir).expanduser().resolve()
    interpreter = Path(python or sys.executable).resolve()
    if not interpreter.is_file():
        raise FileNotFoundError(interpreter)
    if python is None and interpreter.with_name('pythonw.exe').is_file():
        interpreter = interpreter.with_name('pythonw.exe')
    helper = str(PurePosixPath(remote_home) / '.local/lib/codex-kylin-open/open_remote.py')
    source = Path(__file__).with_name('open_in_kylin_template.py').read_text(encoding='utf-8')
    for name, value in [('TARGET_HOST', host), ('TARGET_USER', user), ('REMOTE_HELPER', helper)]:
        source, count = re.subn(rf'^{name} = .*$', lambda _: f'{name} = {value!r}', source, count=1, flags=re.MULTILINE)
        if count != 1:
            raise RuntimeError('Template constant missing: ' + name)
    ast.parse(source)
    quoted = lambda value: json.dumps(str(value), ensure_ascii=False)
    snippet = '\n'.join([
        f'[desktop.custom_file_handlers.{quoted(handler_id)}]',
        'label = "龙芯远程编辑器（Kylin）"',
        'icon = "apps/vscode.png"',
        'command = ' + quoted(interpreter.as_posix()),
        'args = ["-X", "utf8", ' + quoted((output / 'open_in_kylin.py').as_posix()) + ']',
        'input = "json_stdin"', 'supports_ssh = true', '',
    ])
    payloads = {'open_in_kylin.py': source,
                'open_remote.py': Path(__file__).with_name('open_remote.py').read_text(encoding='utf-8'),
                'handler.toml': snippet}
    if not force:
        for name in payloads:
            if (output / name).exists():
                raise FileExistsError(output / name)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in payloads.items():
        (output / name).write_text(value, encoding='utf-8', newline='\n')
    return {'output_dir': str(output), 'remote_destination': helper, 'handler_id': 'custom:' + handler_id}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ['host', 'user', 'remote-home', 'output-dir']:
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--handler-id', default='kylin-remote')
    parser.add_argument('--python')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    print(json.dumps(render(args.host, args.user, args.remote_home, args.output_dir,
                            args.handler_id, args.python, args.force), ensure_ascii=False))
