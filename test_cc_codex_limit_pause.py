# Пауза Codex по лимитам (как у Claude): python3 -m unittest test_cc_codex_limit_pause -v
import datetime, os, sys, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_codex_limits as R  # noqa: E402
import cc_codex_bridge as br  # noqa: E402

NOW = 1_800_000_000.0
iso = lambda ts: datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()


def acc(slot, ses, week, ses_reset=NOW + 3600, week_reset=NOW + 86400, **kw):
    a = {'slot': slot, 'label': slot.upper(), 'ts': NOW,
         'windows': [{'mins': 300, 'pct': ses, 'resets_at': iso(ses_reset)}, {'mins': 10080, 'pct': week, 'resets_at': iso(week_reset)}]}
    a.update(kw); return a


class TestState(unittest.TestCase):
    def test_free_account_no_pause(self):
        self.assertFalse(R.limit_pause_state([acc('a', 50, 50)], 'a', NOW)['active'])

    def test_single_account_pauses_on_its_own_threshold(self):
        for a in (acc('a',0,99),acc('a',90,10),acc('a',70,10,reached=True)):
            self.assertTrue(R.limit_pause_state([a],'a', NOW)['active'])
        self.assertFalse(R.limit_pause_state([acc('a',100,10,ses_reset=NOW-300)],'a', NOW)['active'])


    def test_candidate_or_unknown_no_pause(self):
        self.assertTrue(R.limit_pause_state([acc('a', 100, 10), acc('b', 10, 10)], 'a', NOW)['active'])
        self.assertFalse(R.limit_pause_state([acc('a', 100, 10, stale=True), acc('b', 100, 10)], 'a', NOW)['active'])
        self.assertFalse(R.limit_pause_state([acc('a', 100, 10, login_required=True), acc('b', 100, 10)], 'a', NOW)['active'])
        self.assertFalse(R.limit_pause_state([], 'a', NOW)['active'])

    def test_reached_flag_without_pct(self):
        p = R.limit_pause_state([acc('a', 70, 10, reached=True), acc('b', 100, 10)], 'a', NOW)
        self.assertTrue(p['active']); self.assertEqual(p['windows'], [])




class TestBridge(unittest.TestCase):
    def setUp(self):
        self.b = br.Bridge(); self.sent = []
        self.b._notice_async = self.sent.append

    def test_hold_once_and_resume(self):
        lp = {'active': True, 'window_names': ['неделя'], 'resume_at': time.time() + 3600, 'label': 'A', 'multi': False}
        with mock.patch.object(br, 'LIMIT_PAUSE', return_value=lp):
            self.b.inputs.reserve('text', {}, 'привет')
            self.assertTrue(self.b._limit_hold()); self.assertTrue(self.b._limit_hold())
        self.assertEqual(len(self.sent), 1)
        self.assertIn('⏸ Codex на паузе по лимитам: окно неделя, сброс в', self.sent[0]); self.assertIn('(1)', self.sent[0])
        with mock.patch.object(br, 'LIMIT_PAUSE', return_value={'active': False}):
            self.assertFalse(self.b._limit_hold()); self.assertFalse(self.b._limit_hold())
        self.assertEqual(self.sent[1], '▶️ Codex: лимит снова доступен — отправляю сообщения из очереди (1).')
        self.assertEqual(len(self.sent), 2)

    def test_broken_gate_does_not_block(self):
        with mock.patch.object(br, 'LIMIT_PAUSE', side_effect=RuntimeError('x')):
            self.assertFalse(self.b._limit_hold())
        self.assertEqual(self.sent, [])



if __name__ == '__main__':
    unittest.main()
