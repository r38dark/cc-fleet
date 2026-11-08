"""Повторный вход в Claude на втором сервере (кнопка «Войти заново» на карточке Claude PROD)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import cc_remote_mode as M

MEMBER = {"label": "Claude PROD", "host": "192.0.2.10", "user": "root", "key": "/root/.ssh/k", "port": 2222}
URL = "https://claude.ai/oauth/authorize?code=true&client_id=x&login_hint=a%40b.c"


class FakeChild:
    def __init__(self, idx=0, url=URL, before=""):
        self.idx, self.before, self.sent, self.closed = idx, before, [], False
        self.match = mock.Mock()
        self.match.group.return_value = url

    def expect(self, patterns, timeout=None):
        if len(patterns) == 3:      # ожидание ссылки / TIMEOUT / EOF
            return self.idx
        return 0                    # ожидание EOF после кода

    def sendline(self, text):
        self.sent.append(text)

    def close(self, force=False):
        self.closed = True


class ReloginTest(unittest.TestCase):
    def setUp(self):
        M._relogin.clear()
        self.ssh = []
        self.ssh_answer = (0, json.dumps({"ok": True, "email": "new@example.com"}))
        self.spawned = []
        self.child = FakeChild()
        patches = [
            mock.patch.object(M, "_member_id", return_value="prod"),
            mock.patch.object(M.R, "members", return_value={"prod": MEMBER}),
            mock.patch.object(M.R, "cached", return_value={"prod": {"email": "old@example.com"}}),
            mock.patch.object(M.R, "ssh_run", side_effect=self._ssh),
            mock.patch.object(M.R, "fetch_limits", return_value={}),
            mock.patch.object(M, "_notify"),
            mock.patch.object(M.pexpect, "spawn", side_effect=self._spawn),
            mock.patch.object(M.time, "sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _ssh(self, m, cmd, timeout=25, inp=None):
        self.ssh.append((cmd, inp))
        return self.ssh_answer

    def _spawn(self, cmd, args, **kw):
        self.spawned.append((cmd, args, kw))
        return self.child

    def test_start_returns_link_and_runs_login_in_temp_home_on_second_server(self):
        res = M.relogin_start()
        self.assertTrue(res["ok"]); self.assertEqual(res["url"], URL); self.assertEqual(res["email"], "old@example.com")
        cmd, args, kw = self.spawned[0]
        self.assertEqual(cmd, "ssh"); self.assertIn("-tt", args)
        self.assertIn("-p", args); self.assertIn("2222", args); self.assertIn("-i", args)
        remote = args[-1]
        self.assertIn("HOME=/tmp/ccfleet-relogin-", remote); self.assertIn("--email old@example.com", remote)
        self.assertEqual(args[-2], "root@192.0.2.10")
        self.assertIn("cur", M._relogin)

    def test_start_without_second_server(self):
        with mock.patch.object(M.R, "members", return_value={}):
            res = M.relogin_start()
        self.assertFalse(res["ok"]); self.assertEqual(self.spawned, [])

    def test_start_without_link_cleans_up(self):
        self.child = FakeChild(idx=1, before="boom: claude not found")
        res = M.relogin_start()
        self.assertFalse(res["ok"]); self.assertIn("claude not found", res["message"])
        self.assertTrue(self.child.closed); self.assertNotIn("cur", M._relogin)
        self.assertTrue(any(c.startswith("rm -rf -- /tmp/ccfleet-relogin-") for c, _ in self.ssh))

    def test_second_start_drops_previous_attempt(self):
        first = self.child
        M.relogin_start()
        self.child = FakeChild()
        M.relogin_start()
        self.assertTrue(first.closed)

    def test_submit_installs_tokens_and_reports(self):
        M.relogin_start()
        res = M.relogin_submit("abc123-DEF_456#xyz")
        self.assertTrue(res["ok"]); self.assertEqual(res["email"], "new@example.com"); self.assertIn("обновлён", res["message"])
        self.assertEqual(self.child.sent, ["abc123-DEF_456#xyz"])
        cmd, inp = self.ssh[-1]
        self.assertTrue(cmd.startswith("python3 - /tmp/ccfleet-relogin-")); self.assertIn("claudeAiOauth", inp)
        self.assertNotIn("cur", M._relogin); M.R.fetch_limits.assert_called_once()
        self.assertIn("Claude PROD", M._notify.call_args.args[0])

    def test_submit_failure_resets_attempt(self):
        M.relogin_start()
        self.ssh_answer = (0, json.dumps({"ok": False, "error": "no_token"}))
        res = M.relogin_submit("abc123-DEF_456#xyz")
        self.assertFalse(res["ok"]); self.assertIn("новую ссылку", res["message"])
        self.assertNotIn("cur", M._relogin); self.assertTrue(self.child.closed)

    def test_submit_validates_code_and_needs_attempt(self):
        self.assertIn("Вставь код", M.relogin_submit("ab c")["message"])
        self.assertIn("Нет активной попытки", M.relogin_submit("abc123-DEF_456#xyz")["message"])
        self.assertEqual(self.ssh, [])

    def test_sweep_drops_abandoned_attempt(self):
        M.relogin_start()
        M._relogin["cur"]["started"] = time.time() - M.RELOGIN_TTL - 5
        M.relogin_sweep()
        self.assertNotIn("cur", M._relogin); self.assertTrue(self.child.closed)

    def test_install_script_replaces_live_login_and_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as home:
            tmp_login = os.path.join(home, "ccfleet-tmp"); os.makedirs(tmp_login + "/.claude")
            json.dump({"claudeAiOauth": {"accessToken": "NEW", "refreshToken": "R2", "expiresAt": 9}},
                      open(tmp_login + "/.claude/.credentials.json", "w"))
            json.dump({"oauthAccount": {"emailAddress": "new@example.com", "accountUuid": "u-new"}}, open(tmp_login + "/.claude.json", "w"))
            os.makedirs(home + "/.claude")
            json.dump({"claudeAiOauth": {"accessToken": "OLD"}, "mcpOAuth": {"keep": 1}}, open(home + "/.claude/.credentials.json", "w"))
            json.dump({"oauthAccount": {"emailAddress": "old@example.com"}, "other": 5}, open(home + "/.claude.json", "w"))
            r = subprocess.run([sys.executable, "-", tmp_login], input=M._RELOGIN_INSTALL, capture_output=True, text=True,
                               env=dict(os.environ, HOME=home), timeout=30)
            self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), {"ok": True, "email": "new@example.com"}, r.stderr)
            live = json.load(open(home + "/.claude/.credentials.json"))
            self.assertEqual(live["claudeAiOauth"]["accessToken"], "NEW"); self.assertEqual(live["mcpOAuth"], {"keep": 1})
            self.assertEqual(oct(os.stat(home + "/.claude/.credentials.json").st_mode & 0o777), "0o600")
            self.assertTrue(os.path.exists(home + "/.claude/.credentials.json.bak_relogin"))
            cfg = json.load(open(home + "/.claude.json"))
            self.assertEqual(cfg["oauthAccount"]["emailAddress"], "new@example.com"); self.assertEqual(cfg["other"], 5)
            self.assertFalse(os.path.exists(tmp_login), "временная папка входа удалена")

    def test_install_script_refuses_when_login_did_not_finish(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(home + "/empty")
            r = subprocess.run([sys.executable, "-", home + "/empty"], input=M._RELOGIN_INSTALL, capture_output=True, text=True,
                               env=dict(os.environ, HOME=home), timeout=30)
            self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["ok"], False)
            self.assertFalse(os.path.exists(home + "/.claude/.credentials.json"))


if __name__ == "__main__":
    unittest.main()
