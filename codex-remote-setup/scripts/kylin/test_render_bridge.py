import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from render_bridge import render


class RenderTests(unittest.TestCase):
    def instance(self, root):
        render('test-node.example', 'dev', '/home/dev', root, 'kylin.node')
        spec = importlib.util.spec_from_file_location('generated_bridge', Path(root) / 'open_in_kylin.py')
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        return bridge

    def request(self, path='/home/dev/project/main.py'):
        return {'hostConfig': {'kind': 'ssh', 'sshAlias': 'configured-alias'},
                'remotePath': path, 'location': {'line': 24, 'column': 7}}

    def test_rendered_route_and_toml(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = self.instance(root)
            with patch.object(bridge, 'resolve_host', return_value={'hostname': 'test-node.example', 'user': 'dev'}):
                alias, payload = bridge.normalized_request(self.request('/home/dev/project/中文 a;$(whoami)\'".py'))
            self.assertEqual(alias, 'configured-alias')
            self.assertEqual(payload['location'], {'line': 24, 'column': 7})
            self.assertEqual(payload['path'], '/home/dev/project/中文 a;$(whoami)\'".py')
            cfg = tomllib.loads((Path(root) / 'handler.toml').read_text(encoding='utf-8'))
            handler = cfg['desktop']['custom_file_handlers']['kylin.node']
            self.assertTrue(handler['supports_ssh'])
            self.assertEqual(handler['input'], 'json_stdin')
            self.assertEqual(bridge.REMOTE_HELPER, '/home/dev/.local/lib/codex-kylin-open/open_remote.py')

    def test_other_nodes_and_local_paths_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = self.instance(root)
            self.assertFalse(bridge.is_target_request({'path': 'C:/project/main.py'}))
            with patch.object(bridge, 'resolve_host', return_value={'hostname': 'other.example', 'user': 'dev'}):
                self.assertFalse(bridge.is_target_request(self.request()))
                with self.assertRaises(ValueError):
                    bridge.normalized_request(self.request())

    def test_invalid_path_and_line(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = self.instance(root)
            with patch.object(bridge, 'resolve_host', return_value={'hostname': 'test-node.example', 'user': 'dev'}):
                for path in ['relative.py', '/tmp/file\n.py']:
                    with self.assertRaises(ValueError):
                        bridge.normalized_request(self.request(path))
                request = self.request()
                request['location']['line'] = 0
                with self.assertRaises(ValueError):
                    bridge.normalized_request(request)

    def test_refuses_overwrite_and_invalid_handler_id(self):
        with tempfile.TemporaryDirectory() as root:
            self.instance(root)
            with self.assertRaises(FileExistsError):
                self.instance(root)
            with self.assertRaises(ValueError):
                render('test-node.example', 'dev', '/home/dev', root, 'bad id')


if __name__ == '__main__':
    unittest.main()
