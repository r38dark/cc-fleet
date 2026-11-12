import json
import os
import tempfile
import time
import unittest

import cc_remote as R
import cc_remote_auto as A
import cc_remote_mode as M

NOW = 1_800_000_000.0


def cfg(**kw):
    return dict(dict(A.DEFAULTS, enabled=True), **kw)


def native(level='hard', role='solo', stale=False):
    return dict(level=level, role=role, stale=stale)


def prod(usable=True):
    return dict(usable=usable, why='')


def mode(active=False, busy=False, since=NOW - 3600):
    return dict(active=active, busy=busy, since=since)


def memo(**kw):
    return dict(dict(to_prod=0, to_native=0, both_notified=False, last_return=0.0), **kw)


class Decide(unittest.TestCase):
    def run_ticks(self, n, c, nat, pr, md, mm):
        res = None
        for _ in range(n):
            res = A.decide(NOW, c, nat, pr, md, mm)
        return res

    def test_disabled_does_nothing(self):
        self.assertEqual(A.decide(NOW, cfg(enabled=False), native(), prod(), mode(), memo())[0], None)

    def test_to_prod_needs_two_ticks(self):
        mm = memo()
        self.assertIsNone(A.decide(NOW, cfg(), native(), prod(), mode(), mm)[0])
        act, why = A.decide(NOW, cfg(), native(), prod(), mode(), mm)
        self.assertEqual(act, 'to_prod')
        self.assertEqual(mm['to_prod'], 0)

    def test_to_prod_for_every_native_blocked_level(self):
        for level in ('hard', 'week', 'weekrisk'):
            self.assertEqual(self.run_ticks(2, cfg(), native(level), prod(), mode(), memo())[0], 'to_prod', level)

    def test_no_handoff_when_native_has_limit(self):
        for level in ('none', 'gate', 'manual'):
            mm = memo(to_prod=1)
            self.assertIsNone(self.run_ticks(3, cfg(), native(level), prod(), mode(), mm)[0], level)
            self.assertEqual(mm['to_prod'], 0)

    def test_only_solo_claude_is_handed_off(self):
        for role in ('leader', 'executor', 'paused', ''):
            self.assertIsNone(self.run_ticks(3, cfg(), native(role=role), prod(), mode(), memo())[0], role)

    def test_no_handoff_when_prod_has_no_limit(self):
        self.assertIsNone(self.run_ticks(3, cfg(), native(), prod(False), mode(), memo())[0])

    def test_cooldown_after_return(self):
        self.assertIsNone(self.run_ticks(3, cfg(), native(), prod(), mode(), memo(last_return=NOW - 100))[0])
        self.assertEqual(self.run_ticks(2, cfg(), native(), prod(), mode(), memo(last_return=NOW - 5000))[0], 'to_prod')

    def test_busy_or_stale_snapshot_blocks_decisions(self):
        self.assertIsNone(self.run_ticks(3, cfg(), native(), prod(), mode(busy=True), memo())[0])
        self.assertIsNone(self.run_ticks(3, cfg(), native(stale=True), prod(), mode(), memo())[0])

    def test_no_switch_just_because_native_limit_is_back(self):
        # понятия «вернуться» нет; работа остаётся там, куда её переключили, сколько бы она ни пробыла
        for since in (NOW - 30, NOW - 700, NOW - 36000):
            self.assertIsNone(self.run_ticks(5, cfg(), native('none'), prod(), mode(True, since=since), memo())[0])

    def test_switch_to_native_at_once_when_prod_is_exhausted_and_native_is_free(self):
        act, why = self.run_ticks(2, cfg(), native('none'), prod(False), mode(True, since=NOW - 30), memo())
        self.assertEqual(act, 'to_native')
        self.assertIn('PROD', why)

    def test_stay_on_prod_while_native_is_blocked_and_prod_has_limit(self):
        self.assertIsNone(self.run_ticks(5, cfg(), native('hard'), prod(), mode(True), memo())[0])

    def test_both_exhausted_notifies_once_then_again_after_recovery(self):
        mm = memo()
        self.assertEqual(A.decide(NOW, cfg(), native('hard'), prod(False), mode(True), mm)[0], 'notify_both')
        self.assertIsNone(A.decide(NOW, cfg(), native('hard'), prod(False), mode(True), mm)[0])
        A.decide(NOW, cfg(), native('hard'), prod(True), mode(True), mm)  # PROD снова пригоден — флаг снят
        self.assertEqual(A.decide(NOW, cfg(), native('hard'), prod(False), mode(True), mm)[0], 'notify_both')

    def test_flapping_signal_does_not_trigger(self):
        mm = memo()
        A.decide(NOW, cfg(), native('hard'), prod(), mode(), mm)
        A.decide(NOW, cfg(), native('none'), prod(), mode(), mm)   # на тике лимит «вернулся» — счёт сброшен
        self.assertIsNone(A.decide(NOW, cfg(), native('hard'), prod(), mode(), mm)[0])


class ProdState(unittest.TestCase):
    def test_states(self):
        ok = {'online': True, 'error': '', 'five_hour': {'pct': 12.0, 'resets_at': ''}, 'seven_day': {'pct': 9.0, 'resets_at': ''}}
        self.assertTrue(A.prod_state(ok, 90, 99)['usable'])
        self.assertFalse(A.prod_state(dict(ok, five_hour={'pct': 95.0, 'resets_at': ''}), 90, 99)['usable'])
        self.assertFalse(A.prod_state(dict(ok, seven_day={'pct': 99.0, 'resets_at': ''}), 90, 99)['usable'])
        self.assertFalse(A.prod_state(dict(ok, online=False), 90, 99)['usable'])
        self.assertFalse(A.prod_state(dict(ok, error='no_login'), 90, 99)['usable'])
        self.assertFalse(A.prod_state(dict(ok, error='http_500'), 90, 99)['usable'])
        self.assertFalse(A.prod_state(None, 90, 99)['usable'])

    def test_expired_token_is_not_the_same_as_no_limit(self):
        """Баг: Claude на PROD давно не работал, токен истёк (живёт ~8 ч и обновляется только в работе), и PROD считался непригодным.
        Автопередача на него не шла, а владельцу приходило ложное «лимиты закончились и там, и там»."""
        past = '2026-11-07T01:00:00+00:00'
        future = '2099-01-01T00:00:00+00:00'
        base = {'online': True, 'error': 'token_expired'}
        low = dict(base, five_hour={'pct': 12.0, 'resets_at': future}, seven_day={'pct': 9.0, 'resets_at': future})
        res = A.prod_state(low, 90, 99, now=1794045000)
        self.assertTrue(res['usable'])
        self.assertTrue(res['stale'])
        high_future = dict(base, five_hour={'pct': 92.0, 'resets_at': future}, seven_day={'pct': 9.0, 'resets_at': future})
        self.assertFalse(A.prod_state(high_future, 90, 99, now=1794045000)['usable'])      # окно ещё не сбросилось
        high_past = dict(base, five_hour={'pct': 92.0, 'resets_at': past}, seven_day={'pct': 9.0, 'resets_at': future})
        self.assertTrue(A.prod_state(high_past, 90, 99, now=1794045000)['usable'])         # окно уже сбросилось
        week_full = dict(base, five_hour={'pct': 5.0, 'resets_at': future}, seven_day={'pct': 99.0, 'resets_at': future})
        self.assertFalse(A.prod_state(week_full, 90, 99, now=1794045000)['usable'])
        nothing = A.prod_state(dict(base), 90, 99, now=1794045000)
        self.assertFalse(nothing['usable'])                                                # цифр нет вовсе: не знаем
        self.assertIn('цифр', nothing['why'])


class Tick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        A.CFG_FILE = os.path.join(self.tmp, 'auto.json')
        R.MEMBERS_FILE = os.path.join(self.tmp, 'm.json')
        with open(R.MEMBERS_FILE, 'w') as f:
            json.dump({'prod': {'label': 'Аккаунт PROD', 'host': '192.0.2.1'}}, f)
        self.calls, self.sent = [], []
        for owner, name in ((A, '_snapshot'), (M, 'mode'), (M, 'busy'), (M, 'on'), (M, 'off')):
            self.addCleanup(setattr, owner, name, getattr(owner, name))
        self.addCleanup(setattr, A, 'CFG_FILE', A.CFG_FILE)
        self.addCleanup(setattr, R, 'MEMBERS_FILE', R.MEMBERS_FILE)
        self.state = dict(native=native(), prod=dict(prod(), row={'five_hour': {'pct': 12.0}, 'seven_day': {'pct': 9.0}}))
        A._snapshot = lambda ns, mid: (self.state['native'], self.state['prod'])
        self.md = dict(active=False)
        M.mode = lambda: self.md
        M.busy = lambda: False
        M.on = lambda mid, reason, *a, **k: (self.calls.append(('on', reason)), dict(ok=True))[1]
        M.off = lambda reason, *a, **k: (self.calls.append(('off', reason)), dict(ok=True))[1]
        A._memo.update(to_prod=0, to_native=0, both_notified=False, last_return=0.0, off_wait=0.0)
        self.ns = dict(tg_notify=lambda t: self.sent.append(t))

    def test_disabled_never_touches_anything(self):
        for _ in range(4):
            A.tick(self.ns)
        self.assertEqual(self.calls, [])

    def test_enable_persists_and_hands_off_after_two_ticks(self):
        A.set_enabled(True)
        self.assertTrue(A.load()['enabled'])
        A.tick(self.ns)
        self.assertEqual(self.calls, [])
        self.assertEqual(A.tick(self.ns), 'to_prod')
        self.assertEqual(self.calls[0][0], 'on')
        self.assertIn('автопередача', self.calls[0][1])
        self.assertTrue(self.sent and 'Переход на Claude PROD' in self.sent[0])

    def test_notification_marks_stale_prod_numbers(self):
        self.state['prod']['row'] = {'error': 'token_expired', 'five_hour': {'pct': 12.0, 'resets_at': '2099-01-01T00:00:00+00:00'},
                                     'seven_day': {'pct': 9.0, 'resets_at': '2099-01-01T00:00:00+00:00'}}
        A.set_enabled(True)
        A.tick(self.ns)
        self.assertEqual(A.tick(self.ns), 'to_prod')
        self.assertIn('токен устарел', self.sent[0])
        self.assertIn('5 ч 12%', self.sent[0])

    def test_dry_run_only_reports(self):
        A.set_enabled(True)
        c = A.load()
        c['dry_run'] = True
        A.save(c)
        A.tick(self.ns)
        self.assertEqual(A.tick(self.ns), 'to_prod')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sent, [])

    def test_return_sets_cooldown(self):
        A.set_enabled(True)
        self.md = dict(active=True, since=NOW)
        self.state['native'] = native('none')
        self.state['prod'] = dict(prod(False), row={})
        A.tick(self.ns)
        self.assertEqual(A.tick(self.ns), 'to_native')
        self.assertEqual(self.calls[0][0], 'off')
        self.assertGreater(A._memo['last_return'], 0)

    def test_tick_handoff_stays_on_prod_while_prod_has_limit(self):
        # ни ручная передача кнопкой, ни автопередача сами не переключаются, пока на PROD есть лимит
        A.set_enabled(True)
        self.state['native'] = native('none')
        for reason in ('по кнопке в панели', 'автопередача: у Claude DEV нет лимита, на Claude PROD есть'):
            self.md = dict(active=True, since=time.time() - 36000, reason=reason)
            for _ in range(4):
                A.tick(self.ns)
            self.assertEqual(self.calls, [], reason)

    def test_tick_switches_to_native_when_prod_limit_ends(self):
        A.set_enabled(True)
        self.md = dict(active=True, since=time.time() - 3600, reason='по кнопке в панели')
        self.state['native'] = native('none')
        self.state['prod'] = dict(prod(False), row={})
        A.tick(self.ns)
        self.assertEqual(A.tick(self.ns), 'to_native')
        self.assertEqual(self.calls[0][0], 'off')
        self.assertIn('автопереключение', self.calls[0][1])
        self.assertNotIn('возврат', self.calls[0][1])

    def _prod_answers(self):
        """PROD выше порога, у Claude DEV лимит есть, а Claude на PROD отвечает без пауз: обычное переключение отказывает."""
        A.set_enabled(True)
        self.md = dict(active=True, since=time.time() - 3600, reason='по кнопке в панели')
        self.state['native'] = native('none')
        self.state['prod'] = dict(prod(False), row={})
        def off(reason, force=False):
            self.calls.append(('off-force' if force else 'off', reason))
            return dict(ok=True) if force else dict(ok=False, busy=True, answering=True, message='отвечает')
        M.off = off

    def test_answering_prod_is_switched_by_force_after_grace(self):
        # 08.11: PROD шёл одним длинным ходом, обычное переключение 17 минут получало «дождись конца ответа»
        self._prod_answers()
        for _ in range(2):
            A.tick(self.ns)
        self.assertEqual([c[0] for c in self.calls], ['off'])
        self.assertTrue(A._memo['off_wait'] > 0)
        A._memo['off_wait'] = time.time() - A.FORCE_AFTER + 20   # льгота ещё не вышла: снова только обычная попытка
        for _ in range(2):
            A.tick(self.ns)
        self.assertEqual([c[0] for c in self.calls], ['off', 'off'])
        A._memo['off_wait'] = time.time() - A.FORCE_AFTER - 5
        for _ in range(2):
            A.tick(self.ns)
        self.assertEqual([c[0] for c in self.calls], ['off', 'off', 'off', 'off-force'])
        self.assertIn('остановлен посреди хода', self.calls[-1][1])
        self.assertEqual(A._memo['off_wait'], 0.0)
        self.assertGreater(A._memo['last_return'], 0)
        self.assertTrue(self.sent and 'Переход на Claude DEV' in self.sent[0])

    def test_wait_is_dropped_when_prod_has_limit_again(self):
        self._prod_answers()
        for _ in range(2):
            A.tick(self.ns)
        self.assertTrue(A._memo['off_wait'] > 0)
        self.state['prod'] = dict(prod(True), row={'five_hour': {'pct': 12.0}, 'seven_day': {'pct': 9.0}})
        A.tick(self.ns)
        self.assertEqual(A._memo['off_wait'], 0.0)

    def test_failed_start_is_retried_not_reported_as_done(self):
        A.set_enabled(True)
        M.on = lambda mid, reason, *a, **k: (self.calls.append(('on', reason)), dict(ok=False, message='занято'))[1]
        A.tick(self.ns)
        A.tick(self.ns)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
