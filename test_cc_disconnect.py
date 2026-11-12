"""User-facing disconnect contract: authentication gone, history and unrelated data retained."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

import cc_disconnect as D
import cc_codex as C
import cc_codex_bridge as B
import cc_backup


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def swap(self, obj, key, value):
        p = patch.object(obj, key, value)
        p.start()
        self.addCleanup(p.stop)


class CodexDisconnect(Fixture):
    def setUp(self):
        super().setUp()
        self.swap(C, 'PROFILES', str(self.root / 'profiles'))
        self.home = Path(C.profile_dir('gpt1'))
        put(self.home / 'auth.json', {'tokens': {'access_token': 'test-only'}})
        self.history = put(self.home / 'sessions' / 'history.jsonl', 'retained conversation')
        self.config = put(self.home / 'config.toml', 'model="example"')
        self.meta = put(self.home / 'meta.json', {'label': 'old label'})

    def test_sign_out_hides_account_but_preserves_program_data(self):
        before = {p: p.read_bytes() for p in (self.history, self.config, self.meta)}
        ok, msg = C.delete_account(None, 'gpt1', 'confirm')
        self.assertTrue(ok, msg)
        self.assertEqual(C.profile_slots(), [])
        self.assertFalse((self.home / 'auth.json').exists())
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(C._free_slot(), 'gpt2')  # do not overwrite retained history on reconnect

    def test_cancel_does_not_stop_console_or_remove_login(self):
        before = Mock()
        self.assertFalse(C.delete_account(None, 'gpt1', 'no', before=before)[0])
        before.assert_not_called()
        self.assertEqual(C.profile_slots(), ['gpt1'])

    def test_busy_console_keeps_login(self):
        self.assertFalse(C.delete_account(None, 'gpt1', 'confirm', before=lambda *_: (False, 'busy'))[0])
        self.assertEqual(C.profile_slots(), ['gpt1'])

    def test_linked_auth_file_is_rejected(self):
        auth = self.home / 'auth.json'
        auth.rename(self.root / 'outside.json')
        auth.symlink_to(self.root / 'outside.json')
        self.assertFalse(C.delete_account(None, 'gpt1', 'confirm')[0])
        self.assertTrue((self.root / 'outside.json').exists())

    def test_prepare_disconnect_stops_only_matching_idle_console(self):
        con = SimpleNamespace(status=lambda: {'running': True}, _meta=lambda: {'slot': 'gpt1'},
                              busy=Mock(return_value=False), stop=Mock(return_value=(True, '')), forget=Mock())
        self.swap(B, 'CONSOLE', con)
        self.swap(B, 'BRIDGE', SimpleNamespace(busy=lambda: False))
        self.assertTrue(B.prepare_disconnect('gpt2')[0])
        con.stop.assert_not_called()
        self.assertTrue(B.prepare_disconnect('gpt1')[0])
        con.stop.assert_called_once()
        con.forget.assert_not_called()
        con.busy.return_value = True
        self.assertFalse(B.prepare_disconnect('gpt1')[0])

    def test_refresh_cannot_restore_authorization_after_disconnect(self):
        started, release, removed = threading.Event(), threading.Event(), threading.Event()
        def refresh(*_):
            started.set()
            self.assertTrue(release.wait(3))
            put(self.home / 'auth.json', {'tokens': {'access_token': 'refreshed-test-only'}})
            return {'slot':'gpt1'}
        self.swap(C, '_fetch_account', Mock(side_effect=refresh))
        probe = threading.Thread(target=lambda: C.fetch_account('fake', 'gpt1'))
        result = []
        def disconnect():
            result.append(C.delete_account(None, 'gpt1', 'confirm'))
            removed.set()
        probe.start()
        self.assertTrue(started.wait(3))
        deletion = threading.Thread(target=disconnect)
        deletion.start()
        self.assertFalse(removed.wait(.05))
        release.set()
        probe.join(3)
        deletion.join(3)
        self.assertFalse(probe.is_alive() or deletion.is_alive())
        self.assertTrue(result[0][0], result)
        self.assertFalse((self.home / 'auth.json').exists())
        self.assertTrue(C.fetch_account('fake', 'gpt1')['login_required'])
        C._fetch_account.assert_called_once()


class ClaudeDisconnect(Fixture):
    def setUp(self):
        super().setUp()
        import cc_limits as L
        self.L = L
        for key, rel in {'PROFILES':'profiles', 'BASE':'base', 'BACKUP_DIR':'backups',
                         'LIVE_CREDS':'live/.credentials.json', 'LIVE_CFG':'home/.claude.json',
                         'CONFIG':'base/config.json', 'SNAPSHOT':'base/snapshot.json',
                         'GOOD':'base/good.json', 'STATE':'base/state.json'}.items():
            self.swap(L, key, str(self.root / rel))
        (self.root / 'base').mkdir()
        self.swap(L, 'tg_notify', Mock())
        self.swap(L, '_current_screen_pid', Mock(return_value=None))
        self.home = self.root / 'profiles' / 'acc1'
        self.identity = {'accountUuid':'test-account-one', 'emailAddress':'one@example.invalid'}
        put(self.home / 'oauth_account.json', self.identity)
        put(self.home / 'credentials.json', {'claudeAiOauth':{'accessToken':'test-only'}, 'mcpOAuth':{'other':{'accessToken':'other-test-only'}}})
        self.history = put(self.home / 'projects' / 'session.jsonl', 'retained conversation')
        put(L.LIVE_CFG, {'oauthAccount':self.identity, 'theme':'dark'})
        put(L.LIVE_CREDS, {'claudeAiOauth':{'accessToken':'test-only'}, 'mcpOAuth':{'other':{'accessToken':'other-test-only'}}})

    def test_last_live_login_removed_but_other_credentials_and_history_survive(self):
        L = self.L
        ok, msg, _ = L.delete_account('acc1', 'confirm')
        self.assertTrue(ok, msg)
        self.assertEqual(L.profile_names(), [])
        self.assertEqual(L._real_names(), [])
        self.assertEqual(self.history.read_text(), 'retained conversation')
        self.assertNotIn('claudeAiOauth', D.read(self.home / 'credentials.json'))
        self.assertNotIn('claudeAiOauth', D.read(L.LIVE_CREDS))
        self.assertEqual(D.read(L.LIVE_CREDS)['mcpOAuth']['other']['accessToken'], 'other-test-only')
        self.assertEqual(D.read(L.LIVE_CFG), {'theme':'dark'})
        self.assertEqual(cc_backup.real_names(L.PROFILES), [])
        self.assertIn('test-account-one', cc_backup._deleted(L.BACKUP_DIR))
        self.assertEqual(L._free_slot(), 'acc2')

    def test_busy_last_session_is_untouched(self):
        self.L._current_screen_pid.return_value = 'test-pid'
        self.swap(self.L, 'session_busy', lambda: True)
        self.assertFalse(self.L.delete_account('acc1', 'confirm')[0])
        self.assertIn('claudeAiOauth', D.read(self.L.LIVE_CREDS))
        self.assertEqual(self.L.profile_names(), ['acc1'])

    def test_failure_to_stop_console_keeps_authorization(self):
        self.L._current_screen_pid.return_value = 'test-pid'
        self.swap(self.L, 'session_busy', lambda: False)
        with patch.object(self.L.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            self.assertFalse(self.L.delete_account('acc1', 'confirm')[0])
        self.assertIn('claudeAiOauth', D.read(self.L.LIVE_CREDS))

    def test_other_accounts_do_not_lose_live_credentials(self):
        put(self.L.LIVE_CFG, {'oauthAccount':{'accountUuid':'different-account'}})
        self.assertTrue(self.L.delete_account('acc1', 'confirm')[0])
        self.assertIn('claudeAiOauth', D.read(self.L.LIVE_CREDS))

    def test_live_token_without_account_metadata_is_also_removed(self):
        put(self.L.LIVE_CFG, {'theme':'dark'})
        self.assertTrue(self.L.delete_account('acc1', 'confirm')[0])
        self.assertNotIn('claudeAiOauth', D.read(self.L.LIVE_CREDS))
        self.assertEqual(D.read(self.L.LIVE_CFG), {'theme':'dark'})


if __name__ == '__main__':
    unittest.main()
