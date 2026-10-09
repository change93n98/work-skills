import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'configure_remote.py'
spec = importlib.util.spec_from_file_location('configure_remote', SOURCE)
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


class Stream:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.sent = []
        self.closed = False

    def recv(self, size):
        return next(self.chunks, b'')

    def sendall(self, data):
        self.sent.append(data)

    def settimeout(self, timeout):
        pass

    def close(self):
        self.closed = True


class DiagnosticTests(unittest.TestCase):
    def probe(self, chunks, proxy=18080, tls_error=None):
        stream = Stream(chunks)
        with patch.object(remote.socket, 'create_connection', return_value=stream) as connect:
            with patch.object(remote.ssl, 'create_default_context') as tls:
                tls.return_value.wrap_socket.return_value = stream
                tls.return_value.wrap_socket.side_effect = tls_error
                result = remote.websocket_probe(proxy)
        return result, stream, connect.call_args.args[0]

    def test_proxy_401_proves_route_without_sending_credentials(self):
        result, stream, address = self.probe([
            b'HTTP/1.1 200 Connection established\r\n\r\n',
            b'HTTP/1.1 401 Unauthorized\r\n\r\n',
        ])
        self.assertEqual(address, ('127.0.0.1', 18080))
        self.assertEqual(result, {'stage': 'websocket_upgrade', 'http': 401, 'reachable': True})
        self.assertIn(b'CONNECT chatgpt.com:443', stream.sent[0])
        self.assertIn(b'Upgrade: websocket', stream.sent[1])
        self.assertNotIn(b'Authorization', b''.join(stream.sent))
        self.assertTrue(stream.closed)

    def test_direct_tls_reset_is_distinguished_from_proxy_failure(self):
        result, stream, address = self.probe([], proxy=None, tls_error=ConnectionResetError(104, 'reset'))
        self.assertEqual(address, ('chatgpt.com', 443))
        self.assertEqual(result['stage'], 'tls')
        self.assertEqual(result['errno'], 104)
        self.assertFalse(result['reachable'])
        self.assertTrue(stream.closed)

    def test_failed_connect_does_not_attempt_upgrade(self):
        result, stream, _ = self.probe([b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n'])
        self.assertEqual(result['stage'], 'proxy_connect')
        self.assertFalse(result['reachable'])
        self.assertEqual(len(stream.sent), 1)

    def test_closed_and_oversized_headers_are_bounded_failures(self):
        for chunks in ([b'HTTP/1.1 200', b''], [b'x' * 20000]):
            result, stream, _ = self.probe(chunks)
            self.assertFalse(result['reachable'])
            self.assertTrue(stream.closed)

    def test_403_is_not_a_successful_websocket_route(self):
        result, _, _ = self.probe([b'HTTP/1.1 403 Forbidden\r\n\r\n'], proxy=None)
        self.assertFalse(result['reachable'])

    def test_process_diagnostics_hide_secrets_and_detect_conflicting_proxies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, env in [('11', b''), ('12', b'HTTPS_PROXY=http://127.0.0.1:18080\0'),
                             ('13', b'HTTPS_PROXY=http://127.0.0.1:18080\0http_proxy=http://user:secret@elsewhere\0')]:
                entry = root / pid
                entry.mkdir()
                (entry / 'comm').write_text('codex\n')
                (entry / 'cmdline').write_bytes(b'codex\0app-server\0')
                (entry / 'environ').write_bytes(env + b'API_KEY=sensitive\0')
            with patch.object(remote.os, 'getuid', return_value=root.stat().st_uid, create=True):
                result = remote.running_codex_proxy('http://127.0.0.1:18080', root)
        self.assertEqual([item['proxy_env'] for item in result], ['missing', 'matches', 'different'])
        self.assertNotIn('sensitive', json.dumps(result))
        self.assertNotIn('secret', json.dumps(result))

    def test_check_only_keeps_all_configuration_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            mapping = home / '.config/codex-proxy-hosts/gpu-test.json'
            settings = home / '.vscode-server/data/Machine/settings.json'
            mapping.parent.mkdir(parents=True)
            settings.parent.mkdir(parents=True)
            proxy = 'http://127.0.0.1:18080'
            mapping.write_text(json.dumps({'mode': 'ssh', 'proxy': proxy, 'vscode_dir': str(home / '.vscode-server')}))
            settings.write_text(json.dumps({'http.proxy': proxy, 'unrelated': 123}))
            before = {p: p.read_bytes() for p in home.rglob('*') if p.is_file()}

            def run(args, **kwargs):
                if args[0] == 'curl':
                    return subprocess.CompletedProcess(args, 0, '200', '')
                if args[-1] == '--version':
                    return subprocess.CompletedProcess(args, 0, 'codex-cli test', '')
                return subprocess.CompletedProcess(args, 1, '', 'Not logged in')

            output = io.StringIO()
            with patch.object(remote.Path, 'home', return_value=home), patch.object(remote.socket, 'gethostname', return_value='gpu-test'), patch.object(remote.sys, 'argv', ['helper', '18080', 'check']), patch.object(remote.subprocess, 'run', side_effect=run), patch.object(remote, 'websocket_probe', return_value={'reachable': True, 'http': 401}), patch.object(remote, 'running_codex_proxy', return_value=[]), contextlib.redirect_stdout(output):
                remote.main()
            after = {p: p.read_bytes() for p in home.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertIn('MODEL_NOT_TESTED', output.getvalue())
            self.assertIn('CLI_LOGIN not_logged_in', output.getvalue())

    def test_configure_generates_valid_launcher_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / '.vscode-server/data/Machine/settings.json'
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({'unrelated': 123}))
            (home / '.bashrc').write_text('export KEEP_ME=1\n')

            def run(args, **kwargs):
                return subprocess.CompletedProcess(args, 0, '200' if args[0] == 'curl' else 'codex-cli test', '')

            with patch.object(remote.Path, 'home', return_value=home), patch.object(remote.socket, 'gethostname', return_value='gpu-test'), patch.object(remote.sys, 'argv', ['helper', '18080', 'configure']), patch.object(remote.subprocess, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                remote.main()
            launcher = home / '.local/bin/codex-proxy'
            compile(launcher.read_text(), str(launcher), 'exec')
            self.assertEqual(json.loads(settings.read_text())['unrelated'], 123)
            self.assertIn('export KEEP_ME=1', (home / '.bashrc').read_text())
            self.assertEqual(json.loads(settings.read_text())['http.proxy'], 'http://127.0.0.1:18080')


if __name__ == '__main__':
    unittest.main()
