import json
import os
import tempfile
import time
import unittest

import cc_remote


class RemoteLimits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cc_remote.MEMBERS_FILE = os.path.join(self.tmp, 'm.json')
        cc_remote.STATE_FILE = os.path.join(self.tmp, 's.json')
        json.dump({'prod': {'label': 'Аккаунт PROD', 'host': '192.0.2.1', 'tmux': 'friend'}}, open(cc_remote.MEMBERS_FILE, 'w'))
        self.calls = []
        self.answer = (0, json.dumps({'ok': True, 'email': 'a@b.c', 'plan': 'pro',
                                      'five_hour': {'pct': 5.0, 'resets_at': 'x'}, 'seven_day': {'pct': 9.0, 'resets_at': 'y'}}))
        cc_remote.ssh_run = lambda m, cmd, timeout=25: (self.calls.append(cmd), self.answer)[1]

    def test_unknown_member(self):
        self.assertIsNone(cc_remote.fetch_limits('нет'))

    def test_throttled_answer_is_numbers_with_stale_mark_not_an_error(self):
        # 63531: Anthropic ответил 429, скрипт лимитов отдал последние цифры с метками stale/retry_at — на плитке не ошибка «429»
        cc_remote.fetch_limits('prod')
        self.answer = (0, json.dumps({'ok': True, 'stale': True, 'stale_code': 429, 'retry_at': 1794380000.0,
                                      'five_hour': {'pct': 88.0, 'resets_at': 'x'}, 'seven_day': {'pct': 9.0, 'resets_at': 'y'}}))
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertEqual(row['error'], '')
        self.assertTrue(row['online'])
        self.assertTrue(row['stale'])
        self.assertEqual(row['retry_at'], 1794380000.0)
        self.assertEqual(row['five_hour']['pct'], 88.0)
        self.answer = (0, json.dumps({'ok': True, 'five_hour': {'pct': 50.0, 'resets_at': 'x'}, 'seven_day': {'pct': 9.0, 'resets_at': 'y'}}))
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertNotIn('stale', row)                      # свежие цифры метку снимают
        self.assertNotIn('retry_at', row)

    def test_ok_and_cache(self):
        a = cc_remote.fetch_limits('prod')
        self.assertTrue(a['online'])
        self.assertEqual(a['five_hour']['pct'], 5.0)
        self.assertEqual(a['email'], 'a@b.c')
        b = cc_remote.fetch_limits('prod')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(a['ts'], b['ts'])
        cc_remote.fetch_limits('prod', force=True)
        self.assertEqual(len(self.calls), 2)

    def _set_fail_since(self, seconds_ago):
        st = json.load(open(cc_remote.STATE_FILE))
        st['prod']['fail_since'] = time.time() - seconds_ago
        json.dump(st, open(cc_remote.STATE_FILE, 'w'))

    def test_ssh_fail_keeps_old_limits(self):
        # долгий сбой (дольше LINK_GRACE): «нет связи», но прежние цифры остаются
        cc_remote.fetch_limits('prod')
        self.answer = (255, 'timeout')
        self._set_fail_since(cc_remote.LINK_GRACE + 1)
        # прошлый сбой начался давно, а онлайн-отметка у строки ещё стоит
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertFalse(row['online'])
        self.assertEqual(row['error'], 'ssh')
        self.assertEqual(row['five_hour']['pct'], 5.0)

    def test_short_ssh_drop_is_not_shown_as_no_connection(self):
        # дом/VPN моргнул на секунды: плитка не должна показывать «нет связи» на все 3 минуты кэша
        cc_remote.fetch_limits('prod')
        self.answer = (255, 'timeout')
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertTrue(row['online'])
        self.assertEqual(row['five_hour']['pct'], 5.0)
        self.assertGreater(row['fail_since'], 0)
        # перепроверка скоро (LINK_RETRY), а не через CACHE_SEC
        calls = len(self.calls)
        cc_remote.fetch_limits('prod')
        self.assertEqual(len(self.calls), calls)  # прямо сейчас — из кэша
        st = json.load(open(cc_remote.STATE_FILE))
        st['prod']['ts'] -= cc_remote.LINK_RETRY + 1
        json.dump(st, open(cc_remote.STATE_FILE, 'w'))
        cc_remote.fetch_limits('prod')
        self.assertEqual(len(self.calls), calls + 1)

    def test_drop_that_keeps_going_becomes_no_connection(self):
        cc_remote.fetch_limits('prod')
        self.answer = (255, 'timeout')
        self.assertTrue(cc_remote.fetch_limits('prod', force=True)['online'])
        self._set_fail_since(cc_remote.LINK_GRACE + 1)
        self.assertFalse(cc_remote.fetch_limits('prod', force=True)['online'])

    def test_recovery_clears_the_failure_mark(self):
        cc_remote.fetch_limits('prod')
        self.answer = (255, 'timeout')
        cc_remote.fetch_limits('prod', force=True)
        self.answer = (0, json.dumps({'ok': True, 'email': 'a@b.c', 'plan': 'pro',
                                      'five_hour': {'pct': 6.0, 'resets_at': 'x'}, 'seven_day': {'pct': 9.0, 'resets_at': 'y'}}))
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertTrue(row['online'])
        self.assertFalse(row['fail_since'])
        self.assertEqual(row['five_hour']['pct'], 6.0)

    def test_first_ever_failure_is_no_connection_at_once(self):
        # прежних цифр нет — держать нечего
        self.answer = (255, 'timeout')
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertFalse(row['online'])
        self.assertEqual(row['error'], 'ssh')

    def test_login_problem_is_online_with_error(self):
        self.answer = (0, json.dumps({'ok': False, 'error': 'token_expired'}))
        row = cc_remote.fetch_limits('prod')
        self.assertTrue(row['online'])
        self.assertEqual(row['error'], 'token_expired')

    def test_cached_only_known_members(self):
        cc_remote.fetch_limits('prod')
        st = json.load(open(cc_remote.STATE_FILE))
        st['gone'] = {'x': 1}
        json.dump(st, open(cc_remote.STATE_FILE, 'w'))
        self.assertEqual(list(cc_remote.cached()), ['prod'])

    def test_broken_members_file(self):
        open(cc_remote.MEMBERS_FILE, 'w').write('{oops')
        self.assertEqual(cc_remote.members(), {})


if __name__ == '__main__':
    unittest.main()
