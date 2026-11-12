# Пауза Codex по лимитам (как у Claude): python3 -m unittest test_cc_codex_limit_pause -v
import datetime, os, sys, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_codex_rotation as R  # noqa: E402
import cc_codex_bridge as br  # noqa: E402

NOW = 1_800_000_000.0
iso = lambda ts: datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()


def acc(slot, ses, week, ses_reset=NOW + 3600, week_reset=NOW + 86400, **kw):
    a = {'slot': slot, 'label': slot.upper(), 'ts': NOW,
         'windows': [{'mins': 300, 'pct': ses, 'resets_at': iso(ses_reset)}, {'mins': 10080, 'pct': week, 'resets_at': iso(week_reset)}]}
    a.update(kw); return a


class TestState(unittest.TestCase):
    def test_free_account_no_pause(self):
        self.assertFalse(R.limit_pause_state([acc('a', 50, 50)], 'a', False, NOW)['active'])

    def test_single_account_never_pauses(self):
        # один аккаунт Codex — ротации нет, пауза по лимитам не имеет смысла (просьба владельца)
        for a in (acc('a', 0, 100), acc('a', 100, 10), acc('a', 70, 10, reached=True), acc('a', 100, 10, ses_reset=NOW - 300)):
            self.assertFalse(R.limit_pause_state([a], 'a', False, NOW)['active'])

    def test_week_full_all_accounts(self):
        p = R.limit_pause_state([acc('a', 0, 100), acc('b', 0, 100, week_reset=NOW + 90000)], 'a', False, NOW)
        self.assertTrue(p['active']); self.assertEqual(p['windows'], [10080]); self.assertEqual(p['window_names'], ['неделя'])
        self.assertAlmostEqual(p['resume_at'], NOW + 86400, delta=1); self.assertTrue(p['multi'])
        self.assertEqual(p['accounts'][0]['week'], 100)

    def test_candidate_or_unknown_no_pause(self):
        self.assertFalse(R.limit_pause_state([acc('a', 100, 10), acc('b', 10, 10)], 'a', True, NOW)['active'])
        self.assertFalse(R.limit_pause_state([acc('a', 100, 10, stale=True), acc('b', 100, 10)], 'a', False, NOW)['active'])
        self.assertFalse(R.limit_pause_state([acc('a', 100, 10, login_required=True), acc('b', 100, 10)], 'a', False, NOW)['active'])
        self.assertFalse(R.limit_pause_state([], 'a', False, NOW)['active'])

    def test_reached_flag_without_pct(self):
        p = R.limit_pause_state([acc('a', 70, 10, reached=True), acc('b', 100, 10)], 'a', False, NOW)
        self.assertTrue(p['active']); self.assertEqual(p['windows'], [300])

    def test_nearest_free_account_and_grace(self):
        p = R.limit_pause_state([acc('a', 100, 10, ses_reset=NOW + 7200), acc('b', 10, 100, week_reset=NOW + 600)], 'a', False, NOW)
        self.assertTrue(p['active']); self.assertEqual(p['resume_slot'], 'b'); self.assertTrue(p['multi'])
        late = R.limit_pause_state([acc('a', 100, 10, ses_reset=NOW - 300), acc('b', 100, 10, ses_reset=NOW - 300)], 'a', False, NOW)
        self.assertFalse(late['active']); self.assertTrue(late['expired'])  # сброс прошёл, цифры не обновились — пробуем

    def test_rotation_method_uses_candidates(self):
        rot = R.Rotation.__new__(R.Rotation)
        import threading
        rot.lock = threading.RLock(); rot.state = {'threshold': 90, 'weekly_cap': 99}
        rot.active = lambda: 'a'
        rot.accounts = [acc('a', 100, 10), acc('b', 20, 20)]
        self.assertFalse(rot.limit_pause(now=NOW)['active'])  # есть куда переключиться
        rot.accounts = [acc('a', 100, 10), acc('b', 95, 20)]
        self.assertTrue(rot.limit_pause(now=NOW)['active'])   # кандидат выше порога ротации — ждём


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

    def test_text_multi(self):
        t = br.limit_hold_text({'window_names': ['5 ч'], 'label': 'B', 'multi': True}, 0)
        self.assertTrue(t.startswith('⏸ Codex на паузе по лимитам (B): окно 5 ч. Переключаться некуда — новые сообщения'))


if __name__ == '__main__':
    unittest.main()
