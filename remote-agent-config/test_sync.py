import copy
from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sync
import verify_claude


KEY = "test-only-fake-key-01234567890123456789"


class ApprovalTests(unittest.TestCase):
    def test_merge_preserves_state_and_is_idempotent(self):
        original = {"projects": {"/work": {"hasTrustDialogAccepted": False}},
                    "customApiKeyResponses": {"approved": ["older-key"], "rejected": ["rejected-key"]}}
        before = copy.deepcopy(original)
        merged = sync.approve_api_key(original, KEY)
        self.assertEqual(original, before)
        self.assertEqual(merged["projects"], original["projects"])
        self.assertEqual(merged["customApiKeyResponses"]["approved"], ["older-key", KEY[-20:]])
        self.assertEqual(sync.approve_api_key(merged, KEY), merged)

    def test_explicit_rejection_is_never_overridden(self):
        for approved in ([], [KEY[-20:]]):
            with self.assertRaisesRegex(ValueError, "explicitly rejected"):
                sync.approve_api_key({"customApiKeyResponses": {"approved": approved, "rejected": [KEY[-20:]]}}, KEY)

    def test_invalid_state_is_not_replaced(self):
        for value in (None, "bad", {"approved": "bad"}, {"approved": [1]}):
            with self.assertRaises(ValueError):
                sync.approve_api_key({"customApiKeyResponses": value}, KEY)
        for text in ("", "[1]", "null", "{"):
            with self.assertRaises(ValueError):
                sync.json_object(text, "state")

    def test_no_api_key_does_not_add_approval(self):
        self.assertEqual(sync.approve_api_key({"other": True}, None), {"other": True})

    def test_remote_read_distinguishes_missing_and_failure(self):
        for rc, expected in [(44, None), (0, "{}")]:
            with patch.object(sync, "ssh", return_value=subprocess.CompletedProcess([], rc, "{}", "")):
                self.assertEqual(sync.remote_read("host", "/home/state"), expected)
        with patch.object(sync, "ssh", return_value=subprocess.CompletedProcess([], 1, "", "denied")):
            with self.assertRaises(RuntimeError):
                sync.remote_read("host", "/home/state")


class WslTests(unittest.TestCase):
    def test_repair_auth_even_when_environment_already_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = root / ".vscode-server/data/Machine/settings.json"
            machine.parent.mkdir(parents=True)
            env = [{"name": "ANTHROPIC_API_KEY", "value": KEY}]
            machine.write_text(json.dumps({"claudeCode.environmentVariables": env, "http.proxy": "keep"}))
            auth = root / ".claude.json"
            auth.write_text(json.dumps({"projects": {"x": "keep"}}))
            settings = root / ".claude/settings.json"
            settings.parent.mkdir()
            settings.write_text('{"keep_cli":true}')
            with patch.object(sync, "wsl_run", return_value=subprocess.CompletedProcess([], 0, "/home/test", "")), \
                 patch.object(sync, "wsl_unc", side_effect=lambda distro, path: str(root / path.removeprefix('/home/test/'))):
                self.assertEqual(sync.sync_wsl("test", env, "stamp"), "updated")
                self.assertEqual(sync.sync_wsl("test", env, "stamp2"), "skip")
            self.assertTrue(json.loads(machine.read_text())["claudeCode.disableLoginPrompt"])
            self.assertEqual(json.loads(machine.read_text())["http.proxy"], "keep")
            self.assertEqual(json.loads(auth.read_text())["projects"], {"x": "keep"})
            self.assertIn(KEY[-20:], json.loads(auth.read_text())["customApiKeyResponses"]["approved"])
            self.assertEqual(settings.read_text(), '{"keep_cli":true}')
            self.assertTrue(Path(str(auth) + ".bak-stamp").exists())
            self.assertFalse(Path(str(auth) + ".bak-stamp2").exists())


class VerificationTests(unittest.TestCase):
    def test_auth_status_is_not_a_successful_conversation(self):
        self.assertFalse(verify_claude.successful_result(0, '{"loggedIn":true}'))

    def test_actual_failed_conversation_is_not_success(self):
        failure = json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"})
        self.assertFalse(verify_claude.successful_result(0, failure))
        success = json.dumps({"type": "result", "is_error": False, "result": "OK"})
        self.assertFalse(verify_claude.successful_result(1, success))
        self.assertTrue(verify_claude.successful_result(0, "noise\n" + success))


class SshSyncTests(unittest.TestCase):
    def test_repairs_and_verifies_auth_then_skips_repeat(self):
        home = "/home/test"
        config = {"env": {"ANTHROPIC_API_KEY": KEY, "ANTHROPIC_BASE_URL": "https://example.invalid"}}
        env_list = [{"name": k, "value": v} for k, v in config["env"].items()]
        remote = {home + "/.claude/settings.json": json.dumps(config),
                  home + "/.vscode-server/data/Machine/settings.json": json.dumps({"other": 123, "claudeCode.environmentVariables": env_list}),
                  home + "/.claude.json": '{"projects":{"keep":true}}'}

        def fake_scp(host, source, target):
            remote[target] = Path(source).read_text()

        def fake_ssh(host, command, check=True):
            if " && mv " in command:
                import shlex
                parts = shlex.split(command)
                remote[parts[-1]] = remote.pop(parts[-2])
            return subprocess.CompletedProcess([], 0, "VERIFY_OK", "")

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(sync, "parse_config", return_value=[{"alias": "test", "hostname": "test"}]))
            stack.enter_context(patch.object(sync, "pick_provider", return_value={"name": "test", "is_current": True, "settings": config}))
            stack.enter_context(patch.object(sync, "remote_home", return_value=home))
            stack.enter_context(patch.object(sync, "remote_read", side_effect=lambda host, path: remote.get(path)))
            stack.enter_context(patch.object(sync, "ssh", side_effect=fake_ssh))
            scp = stack.enter_context(patch.object(sync, "scp_to", side_effect=fake_scp))
            stack.enter_context(patch.object(sync.tempfile, "mkdtemp", return_value=directory))
            stack.enter_context(patch("sys.argv", ["sync.py", "--hosts", "test", "--targets", "claude"]))
            output = stack.enter_context(patch("sys.stdout", new_callable=io.StringIO))
            sync.main()
            self.assertIn("1 updated", output.getvalue())
            machine = json.loads(remote[home + "/.vscode-server/data/Machine/settings.json"])
            self.assertEqual(machine["other"], 123)
            self.assertTrue(machine["claudeCode.disableLoginPrompt"])
            auth = json.loads(remote[home + "/.claude.json"])
            self.assertEqual(auth["projects"], {"keep": True})
            self.assertIn(KEY[-20:], auth["customApiKeyResponses"]["approved"])
            scp.reset_mock()
            sync.main()
            scp.assert_not_called()
            self.assertIn("already up to date", output.getvalue())
            self.assertNotIn(KEY, output.getvalue())
            self.assertNotIn(KEY[-20:], output.getvalue())


if __name__ == "__main__":
    unittest.main()
