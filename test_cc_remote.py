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

    def test_ssh_fail_keeps_old_limits(self):
        cc_remote.fetch_limits('prod')
        self.answer = (255, 'timeout')
        row = cc_remote.fetch_limits('prod', force=True)
        self.assertFalse(row['online'])
        self.assertEqual(row['error'], 'ssh')
        self.assertEqual(row['five_hour']['pct'], 5.0)

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
