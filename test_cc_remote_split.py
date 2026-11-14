"""«Двойная работа»: режим говорит «работа на Claude PROD», а основной Claude DEV с Telegram запущен (поднялся сам, мимо панели).
Счётчик расхождения, одно сообщение в Telegram, ответ панели, кнопки «Работа на DEV» / «Работа на PROD» и подключение в поток панели."""
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
        self.assertFalse(S.resolve('stop_dev')['ok'])   # старое имя действия больше не принимается
        self.state['busy'] = True
        with mock.patch.object(M, 'claim_prod') as claim:
            res = S.resolve('work_prod')
        self.assertFalse(res['ok'])
        self.assertTrue(res['busy'])
        claim.assert_not_called()
        self.assertEqual(self.wk.stopped, 0)

    def test_nothing_to_resolve_touches_nothing(self):
        self.wk.running = False
        with mock.patch.object(M, 'off') as off, mock.patch.object(M, 'claim_prod') as claim:
            for action in ('work_dev', 'work_prod'):
                res = S.resolve(action)
                self.assertTrue(res['ok'])
                self.assertIn('уже нет', res['message'])
        off.assert_not_called()
        claim.assert_not_called()
        self.assertEqual(self.wk.stopped, 0)

    def test_work_dev_returns_the_work_like_the_return_button(self):
        with mock.patch.object(M, 'off', return_value={'ok': True, 'started': True}) as off:
            res = S.resolve('work_dev', force=True)
        self.assertTrue(res['ok'])
        self.assertEqual(off.call_count, 1)
        self.assertIn('Claude DEV запущен сам', off.call_args[0][0])
        self.assertIs(off.call_args[0][1], True)
        self.assertEqual(self.wk.stopped, 0)

    def test_work_dev_passes_the_answering_refusal_to_the_panel(self):
        answer = {'ok': False, 'busy': True, 'answering': True, 'message': 'Claude на PROD сейчас отвечает'}
        with mock.patch.object(M, 'off', return_value=answer):
            self.assertEqual(S.resolve('work_dev'), answer)

    def test_work_prod_goes_through_claim_prod_and_clears_the_plaque(self):
        self.ticks(NOW, 300)
        self.assertTrue(S.public(NOW + 300))

        def claim(reason, force):
            self.wk.stop_claude()   # PROD уже работал: claim_prod погасил только DEV
            return {'ok': True, 'message': 'Claude PROD уже работает: Claude DEV остановлен.'}
        with mock.patch.object(M, 'off') as off, mock.patch.object(M, 'claim_prod', side_effect=claim) as cp:
            res = S.resolve('work_prod')
        self.assertTrue(res['ok'])
        off.assert_not_called()
        self.assertEqual(cp.call_count, 1)
        self.assertIn('владелец оставил работу на PROD', cp.call_args[0][0])
        self.assertIs(cp.call_args[0][1], False)
        self.assertEqual(S._mem['first'], 0.0)
        self.assertEqual(S.public(NOW + 300), {})

    def test_work_prod_failure_is_passed_through_and_dev_stays(self):
        bad = {'ok': False, 'message': 'PROD не готов: нет связи. Claude DEV не тронут.'}
        with mock.patch.object(M, 'claim_prod', return_value=bad) as cp:
            res = S.resolve('work_prod', force=True)
        self.assertEqual(res, bad)
        self.assertIs(cp.call_args[0][1], True)
        self.assertEqual(self.wk.stopped, 0)
        self.assertTrue(self.wk.running)


class ClaimProd(Base):
    """M.claim_prod: проверка PROD до остановки DEV, запуск PROD при необходимости."""

    def setUp(self):
        super().setUp()
        self.status = {'ok': True, 'running': False, 'busy': False, 'tg': False}
        self.job_args = []
        self.saved = []
        self.not_ready = ''
        self.rsync_ok = True       # результат rsync памяти DEV -> PROD
        self.rsync_left = 0        # сколько файлов ещё отличается после копирования (None — проверить не удалось)
        self.rsync_calls = []

        def fake_rsync(m, src, dst, to_remote, extra=(), protect_newer=True):
            self.rsync_calls.append((src, dst, to_remote, protect_newer))
            return self.rsync_ok

        def on_job(*args, **kwargs):
            self.job_args.append((args, kwargs))
            return {'ok': True}
        for target, name, value in (
                (M, 'lock_message', lambda: ''),
                (M, 'mode', lambda: {'member': 'p'}),
                (M.R, 'members', lambda: {'p': {'host': 'h'}}),
                (M, '_prod_not_ready', lambda mid, force=False: self.not_ready),
                (M, 'ctl', lambda m, args, timeout=150: self.status),
                (M, '_save', lambda **kw: self.saved.append(kw)),
                (M, 'rsync', fake_rsync),
                (M, 'rsync_pending', lambda m, src, dst, to_remote: self.rsync_left),
                (M, '_on_job', on_job)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def join(self):
        t = M._job.get('t')
        if t is not None:
            t.join(5)

    def test_prod_not_ready_leaves_dev_alone(self):
        self.not_ready = 'PROD не готов: нет связи.'
        res = M.claim_prod('причина')
        self.assertFalse(res['ok'])
        self.assertIn('PROD не готов', res['message'])
        self.assertIn('Claude DEV не тронут', res['message'])
        self.assertEqual(self.wk.stopped, 0)
        self.assertEqual(self.job_args, [])

    def test_prod_that_does_not_answer_leaves_dev_alone(self):
        self.status = {'ok': False, 'error': 'ssh'}
        res = M.claim_prod('причина')
        self.assertFalse(res['ok'])
        self.assertIn('не ответил', res['message'])
        self.assertIn('Claude DEV не тронут', res['message'])
        self.assertEqual((self.wk.stopped, self.job_args), (0, []))

    def test_missing_member_leaves_dev_alone(self):
        with mock.patch.object(M.R, 'members', lambda: {}):
            res = M.claim_prod('причина')
        self.assertFalse(res['ok'])
        self.assertIn('Claude DEV не тронут', res['message'])
        self.assertEqual((self.wk.stopped, self.job_args), (0, []))

    def test_running_prod_with_telegram_only_dev_is_stopped(self):
        self.status = {'ok': True, 'running': True, 'busy': True, 'tg': True}   # PROD отвечает — нам это не мешает, его не трогаем
        res = M.claim_prod('причина')
        self.assertTrue(res['ok'])
        self.assertNotIn('started', res)
        self.assertIn('Claude DEV остановлен', res['message'])
        self.assertIn('память DEV скопирована на PROD', res['message'])
        self.assertEqual(self.wk.stopped, 1)
        self.assertEqual(self.job_args, [])   # PROD не перезапускаем и беседу не гоняем
        # память едет с DEV на PROD, более новые файлы PROD не затираются (--update)
        self.assertEqual(self.rsync_calls, [(M.PROJ + '/memory/', M.PROJ + '/memory/', True, True)])

    def test_memory_copy_failure_does_not_fail_the_claim_but_says_so(self):
        self.status = {'ok': True, 'running': True, 'busy': False, 'tg': True}
        self.rsync_ok = False
        res = M.claim_prod('причина')
        self.assertTrue(res['ok'])
        self.assertEqual(self.wk.stopped, 1)   # DEV уже остановлен: работа осталась на PROD
        self.assertIn('Память DEV на PROD скопировать не удалось', res['message'])
        self.assertNotIn('скопирована на PROD.', res['message'])

    def test_memory_not_confirmed_is_reported(self):
        self.status = {'ok': True, 'running': True, 'busy': False, 'tg': True}
        for left in (3, None):
            self.rsync_left = left
            self.wk.stopped = 0
            res = M.claim_prod('причина')
            self.assertTrue(res['ok'])
            self.assertIn('не подтверждено', res['message'])

    def test_memory_is_not_copied_when_dev_does_not_stop(self):
        self.wk.stops = False
        self.status = {'ok': True, 'running': True, 'busy': False, 'tg': True}
        M.claim_prod('причина')
        self.assertEqual(self.rsync_calls, [])   # DEV ещё пишет: до остановки память не гоняем

    def test_memory_is_not_copied_separately_when_prod_gets_the_full_handoff(self):
        M.claim_prod('причина')
        self.join()
        self.assertEqual(self.rsync_calls, [])   # полную передачу делает _on_job (там же память)

    def test_dev_that_does_not_stop_says_so(self):
        self.wk.stops = False
        self.status = {'ok': True, 'running': True, 'busy': False, 'tg': True}
        res = M.claim_prod('причина')
        self.assertFalse(res['ok'])
        self.assertIn('не остановился', res['message'])
        self.assertEqual(self.job_args, [])

    def test_stopped_prod_gets_the_full_handoff_with_the_conversation(self):
        res = M.claim_prod('причина владельца')
        self.join()
        self.assertTrue(res['ok'])
        self.assertTrue(res['started'])
        self.assertEqual(len(self.job_args), 1)
        args, kwargs = self.job_args[0]
        self.assertEqual(args, ('p', 'причина владельца', '', True))   # resume=True: беседа DEV едет на PROD
        self.assertEqual(kwargs, {})
        self.assertEqual(self.wk.stopped, 0)   # DEV гасит сама передача, после копирования, а не мы заранее
        self.assertEqual(self.saved, [{'stage': 'начало', 'error': ''}])

    def test_prod_running_without_telegram_is_restarted_only_when_idle_or_forced(self):
        self.status = {'ok': True, 'running': True, 'busy': True, 'tg': False}
        res = M.claim_prod('причина')
        self.assertFalse(res['ok'])
        self.assertTrue(res['answering'])
        self.assertEqual(self.job_args, [])
        res = M.claim_prod('причина', force=True)
        self.join()
        self.assertTrue(res['ok'] and res['started'])
        self.assertEqual(len(self.job_args), 1)

    def test_pair_lock_no_operation_and_not_active_are_refused_before_any_check(self):
        with mock.patch.object(M, 'lock_message', lambda: 'пара включена'):
            res = M.claim_prod('причина')
        self.assertEqual((res['ok'], res['message']), (False, 'пара включена'))
        self.state['busy'] = True
        self.assertTrue(M.claim_prod('причина')['busy'])
        self.state.update(busy=False, active=False)
        self.assertTrue(M.claim_prod('причина')['ok'])
        self.assertEqual((self.wk.stopped, self.job_args), (0, []))


class TextAndNames(unittest.TestCase):
    def test_telegram_notice_uses_the_outcome_names(self):
        text = S._text(3)
        self.assertIn('«Работа на DEV»', text)
        self.assertIn('«Работа на PROD»', text)
        self.assertNotIn('Остановить DEV', text)
        self.assertNotIn('Оставить DEV', text)


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

    def test_work_prod_goes_through_the_real_handler(self):
        def claim(reason, force):
            self.wk.stop_claude()
            return {'ok': True, 'message': 'Claude PROD уже работает: Claude DEV остановлен.'}
        with mock.patch.object(M, 'claim_prod', side_effect=claim):
            code, body = self.post({'action': 'work_prod'})
        self.assertEqual(code, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['state'], {'split': {}})
        self.assertEqual(self.wk.stopped, 1)

    def test_work_dev_force_flag_reaches_off(self):
        with mock.patch.object(M, 'off', return_value={'ok': True}) as off:
            self.post({'action': 'work_dev', 'force': True})
            self.post({'action': 'work_dev', 'force': 'yes'})
        self.assertEqual([c[0][1] for c in off.call_args_list], [True, False])

    def test_unknown_action_and_no_auth_do_nothing(self):
        code, body = self.post({'action': 'сломай'})
        self.assertFalse(body['ok'])
        FakeBase.authed = False
        code, body = self.post({'action': 'work_prod'})
        self.assertEqual(code, 403)
        self.assertEqual(self.wk.stopped, 0)


class Screen(unittest.TestCase):
    def test_script_is_valid_and_plaque_offers_both_buttons_with_confirmation(self):
        js = UI.JS
        for part in ("spEl.id='rmSplit'", 'data-split="work_dev"', 'data-split="work_prod"',
                     '>Работа на DEV</button>', '>Работа на PROD</button>', "post('remote/split'", 'window.fleetAsk(', 'paintSplit();sSync()',
                     '<b>Работа на DEV:</b>', '<b>Работа на PROD:</b>', 'Не получится — Claude DEV останется как есть'):
            self.assertIn(part, js, part)
        for gone in ('Оставить DEV', 'Остановить DEV', 'keep_dev', 'stop_dev'):
            self.assertNotIn(gone, js, gone)
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
