"""«Двойная работа»: режим говорит «работа на Claude PROD», а основной Claude DEV с Telegram запущен (поднялся сам, мимо панели).
Счётчик расхождения, одно сообщение в Telegram, ответ панели, кнопки «Оставить DEV» / «Остановить DEV» и подключение в поток панели."""
import inspect
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import cc_remote_auto as A
import cc_remote_mode as M
import cc_remote_split as S
import cc_remote_ui as UI

NOW = 1_800_000_000.0


class Wk:
    def __init__(self, running=True, stops=True):
        self.running = running
        self.stops = stops
        self.stopped = 0

    def claude_running(self):
        return self.running

    def stop_claude(self):
        self.stopped += 1
        if self.stops:
            self.running = False
        return self.stops


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state = {'active': True, 'busy': False}
        self.wk = Wk()
        self.sent = []
        self.ns = {'tg_notify': self.sent.append}
        for target, value in (
                (S, dict(FILE=os.path.join(self.dir, 'remote_split.json'))),):
            for k, v in value.items():
                p = mock.patch.object(target, k, v)
                p.start()
                self.addCleanup(p.stop)
        for name, fn in (('active', lambda: self.state['active']), ('busy', lambda: self.state['busy']), ('_wk', lambda: self.wk)):
            p = mock.patch.object(M, name, fn)
            p.start()
            self.addCleanup(p.stop)
        self.reset()

    def reset(self):
        S._mem.update(first=0.0, seen=0.0, notified=0.0)
        S._loaded[0] = True

    def ticks(self, start, seconds, step=30):
        out = None
        for t in range(0, seconds + 1, step):
            out = S.tick(self.ns, now=start + t)
        return out


class Pure(unittest.TestCase):
    def test_suspect_needs_remote_mode_a_running_claude_and_no_operation(self):
        self.assertTrue(S.suspect(True, False, True))
        for args in ((False, False, True), (True, False, False), (True, True, True), (False, True, False)):
            self.assertFalse(S.suspect(*args), args)

    def test_nothing_is_reported_before_the_hold_time(self):
        st = dict(first=0, seen=0, notified=0)
        for t in range(0, S.HOLD_SEC, 30):
            st, notify = S.advance(NOW + t, True, st)
            self.assertFalse(notify, t)
        st, notify = S.advance(NOW + S.HOLD_SEC, True, st)
        self.assertTrue(notify)

    def test_one_notice_per_episode(self):
        st = dict(first=0, seen=0, notified=0)
        sent = 0
        for t in range(0, 600, 30):
            st, notify = S.advance(NOW + t, True, st)
            sent += notify
        self.assertEqual(sent, 1)

    def test_resolved_and_back_again_is_a_new_episode(self):
        st = dict(first=0, seen=0, notified=0)
        for t in range(0, 180, 30):
            st, _ = S.advance(NOW + t, True, st)
        st, notify = S.advance(NOW + 200, False, st)
        self.assertFalse(notify)
        self.assertEqual(st, dict(first=0.0, seen=0.0, notified=0.0))
        sent = 0
        for t in range(300, 500, 30):
            st, notify = S.advance(NOW + t, True, st)
            sent += notify
        self.assertEqual(sent, 1)

    def test_a_gap_in_checks_restarts_the_count(self):
        st, _ = S.advance(NOW, True, dict(first=0, seen=0, notified=0))
        st, notify = S.advance(NOW + S.HOLD_SEC + 10 * S.STALE_SEC, True, st)   # проверки не шли: «подряд» не доказано
        self.assertFalse(notify)
        self.assertEqual(st['first'], NOW + S.HOLD_SEC + 10 * S.STALE_SEC)


class Tick(Base):
    def test_plaque_and_one_message_after_two_minutes(self):
        self.assertEqual(S.tick(self.ns, now=NOW), {})
        self.assertEqual(self.sent, [])
        res = self.ticks(NOW, 300)
        self.assertTrue(res['on'])
        self.assertEqual(res['since'], NOW)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Двойная работа', self.sent[0])
        self.assertIn('Панель ничего не переключала', self.sent[0])

    def test_no_claude_here_means_no_plaque(self):
        self.wk.running = False
        self.assertEqual(self.ticks(NOW, 600), {})
        self.assertEqual(self.sent, [])

    def test_work_on_dev_is_normal(self):
        self.state['active'] = False
        self.assertEqual(self.ticks(NOW, 600), {})
        self.assertEqual(self.sent, [])

    def test_a_handoff_in_progress_is_not_a_split(self):
        self.state['busy'] = True
        self.assertEqual(self.ticks(NOW, 600), {})
        self.assertEqual(self.sent, [])

    def test_plaque_goes_away_when_claude_stops_and_does_not_repeat_the_message(self):
        self.ticks(NOW, 300)
        self.wk.running = False
        self.assertEqual(S.tick(self.ns, now=NOW + 330), {})
        self.assertEqual(len(self.sent), 1)

    def test_panel_restart_keeps_the_episode_without_a_second_message(self):
        self.ticks(NOW, 300)
        S._mem.update(first=0.0, seen=0.0, notified=0.0)   # перезапуск панели: память пуста, файл остался
        S._loaded[0] = False
        res = S.tick(self.ns, now=NOW + 330)
        self.assertTrue(res['on'])
        self.assertEqual(len(self.sent), 1)

    def test_stale_checks_hide_the_plaque(self):
        self.ticks(NOW, 300)
        self.assertEqual(S.public(NOW + 300 + S.STALE_SEC + 5), {})

    def test_a_failing_check_does_not_raise_or_change_state(self):
        self.ticks(NOW, 300)

        def boom():
            raise RuntimeError('нет screen')
        self.wk.claude_running = boom
        self.assertTrue(S.tick(self.ns, now=NOW + 330)['on'])

    def test_a_dead_notifier_does_not_break_the_check(self):
        def dead(text):
            raise OSError('нет сети')
        self.ns['tg_notify'] = dead
        self.assertTrue(self.ticks(NOW, 300)['on'])


class Public(Base):
    def test_remote_mode_public_carries_the_split(self):
        self.ticks(NOW, 300)
        with mock.patch.object(S.time, 'time', return_value=NOW + 300):
            self.assertTrue(M._split_public().get('on'))

    def test_hidden_while_busy_or_when_work_is_already_here(self):
        self.ticks(NOW, 300)
        with mock.patch.object(S.time, 'time', return_value=NOW + 300):
            self.state['busy'] = True
            self.assertEqual(M._split_public(), {})
            self.state.update(busy=False, active=False)
            self.assertEqual(M._split_public(), {})


class Resolve(Base):
    def test_unknown_action_and_busy_are_refused(self):
        self.assertFalse(S.resolve('сломай')['ok'])
        self.state['busy'] = True
        res = S.resolve('stop_dev')
        self.assertFalse(res['ok'])
        self.assertTrue(res['busy'])
        self.assertEqual(self.wk.stopped, 0)

    def test_nothing_to_resolve_touches_nothing(self):
        self.wk.running = False
        with mock.patch.object(M, 'off') as off:
            res = S.resolve('keep_dev')
        self.assertTrue(res['ok'])
        self.assertIn('уже нет', res['message'])
        off.assert_not_called()
        self.assertEqual(self.wk.stopped, 0)

    def test_keep_dev_returns_the_work_like_the_return_button(self):
        with mock.patch.object(M, 'off', return_value={'ok': True, 'started': True}) as off:
            res = S.resolve('keep_dev', force=True)
        self.assertTrue(res['ok'])
        self.assertEqual(off.call_count, 1)
        self.assertIn('Claude DEV запущен сам', off.call_args[0][0])
        self.assertIs(off.call_args[0][1], True)
        self.assertEqual(self.wk.stopped, 0)

    def test_keep_dev_passes_the_answering_refusal_to_the_panel(self):
        answer = {'ok': False, 'busy': True, 'answering': True, 'message': 'Claude на PROD сейчас отвечает'}
        with mock.patch.object(M, 'off', return_value=answer):
            self.assertEqual(S.resolve('keep_dev'), answer)

    def test_stop_dev_stops_only_the_local_claude_and_clears_the_plaque(self):
        self.ticks(NOW, 300)
        with mock.patch.object(M, 'off') as off:
            res = S.resolve('stop_dev')
        self.assertTrue(res['ok'])
        self.assertEqual(self.wk.stopped, 1)
        off.assert_not_called()
        self.assertEqual(S._mem['first'], 0.0)
        self.assertEqual(S.public(NOW + 300), {})

    def test_stop_dev_that_does_not_stop_says_so(self):
        self.wk.stops = False
        res = S.resolve('stop_dev')
        self.assertFalse(res['ok'])
        self.assertIn('не остановился', res['message'])


class Wiring(unittest.TestCase):
    def test_the_panel_thread_runs_the_check_whether_or_not_auto_handoff_is_on(self):
        src = inspect.getsource(A.start)
        self.assertIn('cc_remote_split.tick', src)
        self.assertLess(src.index('cc_remote_split.tick'), src.index('tick(ns, kicked=kicked)'))
        self.assertNotIn("cfg['enabled']", inspect.getsource(S.tick))

    def test_the_route_is_registered_and_calls_resolve(self):
        src = inspect.getsource(M.install)
        self.assertIn('"/api/remote/split"', src)
        self.assertIn('cc_remote_split.resolve', src)

    def test_manifest_ships_the_module(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, 'update_manifest.json'), encoding='utf-8') as f:
            self.assertIn('"src": "cc_remote_split.py"', f.read())


class FakeBase:
    sent = []
    authed = True

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        FakeBase.sent.append((code, body))

    def _authed(self):
        return FakeBase.authed

    def do_GET(self):
        FakeBase.sent.append(("base_get", self.path))

    def do_POST(self):
        FakeBase.sent.append(("base_post", self.path))


class Route(Base):
    """Настоящий RemoteHandler.do_POST: путь /api/remote/split доходит до resolve и отвечает состоянием."""

    def setUp(self):
        super().setUp()
        FakeBase.sent, FakeBase.authed = [], True
        p = mock.patch.dict(M._NS)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(M, 'public', return_value={'split': {}})
        p.start()
        self.addCleanup(p.stop)
        ns = {'H': FakeBase}
        M.install(ns)
        self.h = ns['H'].__new__(ns['H'])

    def post(self, body):
        import io
        import json
        raw = json.dumps(body).encode()
        self.h.path = '/api/remote/split'
        self.h.headers = {'Content-Length': str(len(raw))}
        self.h.rfile = io.BytesIO(raw)
        self.h.do_POST()
        return FakeBase.sent[-1]

    def test_stop_dev_goes_through_the_real_handler(self):
        code, body = self.post({'action': 'stop_dev'})
        self.assertEqual(code, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['state'], {'split': {}})
        self.assertEqual(self.wk.stopped, 1)

    def test_keep_dev_force_flag_reaches_off(self):
        with mock.patch.object(M, 'off', return_value={'ok': True}) as off:
            self.post({'action': 'keep_dev', 'force': True})
            self.post({'action': 'keep_dev', 'force': 'yes'})
        self.assertEqual([c[0][1] for c in off.call_args_list], [True, False])

    def test_unknown_action_and_no_auth_do_nothing(self):
        code, body = self.post({'action': 'сломай'})
        self.assertFalse(body['ok'])
        FakeBase.authed = False
        code, body = self.post({'action': 'stop_dev'})
        self.assertEqual(code, 403)
        self.assertEqual(self.wk.stopped, 0)


class Screen(unittest.TestCase):
    def test_script_is_valid_and_plaque_offers_both_buttons_with_confirmation(self):
        js = UI.JS
        for part in ("spEl.id='rmSplit'", 'data-split="keep_dev"', 'data-split="stop_dev"',
                     'Оставить DEV', 'Остановить DEV', "post('remote/split'", 'window.fleetAsk(', 'paintSplit();sSync()'):
            self.assertIn(part, js, part)
        self.assertIn('html.conly #rmSplit{display:none}', UI.CSS)
        self.assertLess(js.index("window.fleetAsk(b,keep?"), js.index("splitGo(act,false)"))   # без подтверждения запрос не уходит

    @unittest.skipUnless(shutil.which('node'), 'нет node')
    def test_script_parses_under_node(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'remote_ui.js')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(UI.JS)
            r = subprocess.run(['node', '--check', p], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
