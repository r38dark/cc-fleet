import json
import os
import tempfile
import unittest
import urllib.parse

import cc_limits as L
import cc_remote
import cc_remote_mode as M


def _w(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f)


class RemoteConsole(unittest.TestCase):
    """Вкладка «Аккаунт PROD» в консоли: экран, ввод, клавиши, запуск. ssh подменён."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cc_remote.MEMBERS_FILE = os.path.join(self.tmp, 'm.json')
        cc_remote.STATE_FILE = os.path.join(self.tmp, 's.json')
        M.MODE_FILE = os.path.join(self.tmp, 'mode.json')
        M.FROZEN_FILE = os.path.join(self.tmp, 'last.json')
        M._frozen.update(mid=None, current='', history='', ts=0, saved=0.0)
        _w(cc_remote.MEMBERS_FILE, {'prod': {'label': 'Аккаунт PROD', 'host': '192.0.2.1', 'tmux': 'friend'}})
        M._NS.update(pyte=L.pyte, _row_html=L._row_html)
        M._cview.update(key=None, ts=0.0, resp=None, fail_until=0.0)
        self.calls = []
        self.answer = {'ok': True, 'running': True, 'cols': 80, 'rows': 5, 'text': '\x1b[31mкрасный\x1b[0m текст\nвторая строка\n\n'}
        self.code = 0

        def fake(m, cmd, timeout=25, inp=None):
            self.calls.append((cmd, inp))
            return self.code, json.dumps(self.answer)

        cc_remote.ssh_run = fake

    @staticmethod
    def q(s):
        return urllib.parse.parse_qs(s)

    def test_ansi_html_keeps_colour_and_drops_blank_tail(self):
        html = M._ansi_html('\x1b[31mred\x1b[0m ok\nline2\n\n\n', 40)
        self.assertIn('red', html)
        self.assertIn('line2', html)
        self.assertEqual(html.count('\n'), 1)
        self.assertIn('<span', html)

    def test_view_running_gives_current_screen(self):
        d = M.console_view(self.q('s=prod&cols=100'))
        self.assertTrue(d['ok'] and d['running'] and d['available'])
        self.assertIn('красный', d['current'])
        self.assertNotIn('history', d)
        self.assertTrue(self.calls[0][0].endswith('ctl.py ansi 100 0'))

    def test_view_history_request(self):
        d = M.console_view(self.q('s=prod&cols=100&history=1'))
        self.assertIn('красный', d['history'])
        self.assertEqual(d['current'], '')
        self.assertTrue(self.calls[0][0].endswith('ctl.py ansi 100 3000'))

    def test_view_not_running(self):
        self.answer = {'ok': True, 'running': False, 'text': '', 'cols': 0, 'rows': 0}
        d = M.console_view(self.q('s=prod'))
        self.assertTrue(d['ok'])
        self.assertFalse(d['running'])
        self.assertEqual(d['current'], '')
        self.assertEqual(d['stopped'], 0)  # экрана ещё не видели: плашка без «показан последний экран»
        self.assertIn('не запущен', d['idle'])

    def _stop_prod(self):
        self.answer = {'ok': True, 'running': False, 'text': '', 'cols': 0, 'rows': 0}
        M._cview.update(key=None, ts=0.0, resp=None, fail_until=0.0)

    def test_view_stopped_shows_last_seen_screen_like_native_claude(self):
        M.console_view(self.q('s=prod&cols=100'))  # пока Claude работает, экран запоминается
        self._stop_prod()
        d = M.console_view(self.q('s=prod&cols=100'))
        self.assertFalse(d['running'])
        self.assertIn('красный', d['current'])
        self.assertGreater(d['stopped'], 0)
        self.assertIn('не запущен', d['idle'])
        self.assertNotIn('history', d)

    def test_view_stopped_history_is_the_last_seen_history(self):
        M.console_view(self.q('s=prod&cols=100&history=1'))
        self._stop_prod()
        d = M.console_view(self.q('s=prod&cols=100&history=1'))
        self.assertFalse(d['running'])
        self.assertIn('красный', d['history'])

    def test_last_screen_survives_panel_restart(self):
        self.assertTrue(M.freeze_screen('prod'))
        self.assertTrue(os.path.isfile(M.FROZEN_FILE))
        M._frozen.update(mid=None, current='', history='', ts=0, saved=0.0)  # панель перезапустили
        self._stop_prod()
        d = M.console_view(self.q('s=prod&cols=100&history=1'))
        self.assertIn('красный', d['current'])
        self.assertIn('красный', d['history'])

    def test_freeze_before_stop_takes_screen_and_history(self):
        self.assertTrue(M.freeze_screen('prod'))
        self.assertEqual([c[0].split('ctl.py ')[1] for c in self.calls], ['ansi 0 0', 'ansi 0 3000'])  # размер окна не трогаем
        cur, his, ts = M._frozen_get('prod')
        self.assertIn('красный', cur)
        self.assertIn('красный', his)
        self.assertGreater(ts, 0)

    def test_freeze_failure_does_not_break_stop(self):
        self.code = 255
        self.assertFalse(M.freeze_screen('prod'))
        self.answer = {'ok': True, 'running': False, 'text': '', 'cols': 0, 'rows': 0}
        self.code = 0
        self.assertFalse(M.freeze_screen('prod'))  # Claude уже не идёт: нечего снимать, старый кадр не затирается
        self.assertEqual(M._frozen_get('prod')[0], '')

    def test_view_without_connection(self):
        self.code = 255
        d = M.console_view(self.q('s=prod'))
        self.assertFalse(d['ok'])
        self.assertIn('связи', d['message'])

    def test_view_parallel_polls_share_one_ssh(self):
        a = M.console_view(self.q('s=prod&cols=100'))
        b = M.console_view(self.q('s=prod&cols=100'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(a, b)
        M.console_view(self.q('s=prod&cols=100&history=1'))  # другой запрос — свой ssh
        self.assertEqual(len(self.calls), 2)

    def test_view_expired_cache_asks_again(self):
        M.console_view(self.q('s=prod&cols=100'))
        M._cview['ts'] -= 5
        M.console_view(self.q('s=prod&cols=100'))
        self.assertEqual(len(self.calls), 2)

    def test_lost_connection_is_not_retried_on_every_poll(self):
        self.code = 255
        self.assertFalse(M.console_view(self.q('s=prod'))['ok'])
        M._cview['ts'] -= 5   # общий ответ устарел, но пауза после сбоя ещё идёт
        d = M.console_view(self.q('s=prod&cols=90'))
        self.assertFalse(d['ok'])
        self.assertIn('связи', d['message'])
        self.assertEqual(len(self.calls), 1)
        M._cview['fail_until'] = 0.0   # пауза прошла — связь вернулась
        self.code = 0
        self.assertTrue(M.console_view(self.q('s=prod&cols=90'))['ok'])

    def test_view_without_member(self):
        _w(cc_remote.MEMBERS_FILE, {})
        self.assertFalse(M.console_view(self.q('s=prod'))['available'])

    def test_input_goes_through_stdin_and_cleans_controls(self):
        self.answer = {'ok': True}
        ok, msg = M.console_input('  привет\x07 мир\r\n  ')
        self.assertTrue(ok)
        cmd, inp = self.calls[0]
        self.assertTrue(cmd.endswith('ctl.py sendin queue'))
        self.assertEqual(inp, 'привет мир')

    def test_input_refusals(self):
        self.answer = {'ok': False, 'error': 'busy'}
        ok, msg = M.console_input('текст')
        self.assertFalse(ok)
        self.assertIn('идёт ответ', msg)
        self.answer = {'ok': False, 'error': 'not_running'}
        self.assertIn('не запущен', M.console_input('текст')[1])
        self.calls.clear()
        self.assertFalse(M.console_input('   ')[0])
        self.assertFalse(M.console_input('я' * 30000)[0])
        self.assertEqual(self.calls, [])

    def test_key_names(self):
        self.answer = {'ok': True}
        self.assertTrue(M.console_key('escape')[0])
        self.assertTrue(self.calls[0][0].endswith('ctl.py key Escape'))
        self.assertFalse(M.console_key('f12')[0])
        self.assertEqual(len(self.calls), 1)

    def _models(self):
        M._NS.update(all_models=lambda: {'claude-a': 'A', 'claude-b': 'B'}, cfg=lambda: {},   # пул не сужали: показываются все
                     effort_support=lambda k: ['low', 'medium', 'high'] if k == 'claude-a' else [])
        _w(cc_remote.STATE_FILE, {'prod': {'model': 'claude-a', 'effort': 'low', 'online': True}})

    def test_models_view(self):
        self._models()
        v = M.models_view()
        self.assertEqual([m['id'] for m in v['models']], ['claude-a', 'claude-b'])
        self.assertEqual(v['models'][0]['efforts'], ['low', 'medium', 'high'])
        self.assertEqual((v['model'], v['effort']), ('claude-a', 'low'))

    def test_models_view_follows_the_shared_quick_menu_pool(self):
        # «Модели в быстром меню» общие у Claude и PROD — отмеченные в пуле показываются и у PROD
        self._models()
        M._NS.update(all_models=lambda: {'claude-a': 'A', 'claude-b': 'B', 'claude-c': 'C'}, cfg=lambda: {'enabled_models': ['claude-b']})
        try:
            ids = [m['id'] for m in M.models_view()['models']]
            self.assertEqual(ids, ['claude-a', 'claude-b'])  # claude-a — текущая модель PROD, остаётся в списке, claude-c снята с пула
            M._NS.update(cfg=lambda: {})                     # пул не сужали — показываются все
            self.assertEqual([m['id'] for m in M.models_view()['models']], ['claude-a', 'claude-b', 'claude-c'])
            M._NS.update(cfg=lambda: 1 / 0)                  # настройки не читаются — не ломаемся, показываем все
            self.assertEqual(len(M.models_view()['models']), 3)
        finally:
            M._NS.update(cfg=lambda: {})

    def test_set_model_refuses_a_model_taken_off_the_pool(self):
        self._models()
        M._NS.update(cfg=lambda: {'enabled_models': ['claude-a']})
        try:
            self.assertFalse(M.set_model({'model': 'claude-b'})['ok'])
            self.assertEqual(self.calls, [])
        finally:
            M._NS.update(cfg=lambda: {})

    def test_set_model_refusals_do_not_touch_the_server(self):
        self._models()
        for body in ({}, {'model': 'нет'}, {'effort': 'max'}, {'model': 'claude-b', 'effort': 'high'}):
            self.assertFalse(M.set_model(body)['ok'], body)
        self.assertEqual(self.calls, [])

    def test_set_model_writes_effort_and_refreshes_panel_data(self):
        self._models()
        self.answer = {'ok': True, 'applied': ['/effort high'], 'wait': False}
        r = M.set_model({'effort': 'high'})
        self.assertTrue(r['ok'])
        self.assertTrue(self.calls[0][0].endswith('ctl.py setmodel - high'))
        self.assertTrue(any('usage.py' in c for c, _ in self.calls[1:]))  # данные панели перечитаны

    def test_set_model_reports_wait_when_claude_is_busy(self):
        self._models()
        self.answer = {'ok': True, 'applied': [], 'wait': True}
        r = M.set_model({'model': 'claude-b'})
        self.assertTrue(r['ok'] and r['wait'])
        self.assertIn('отвечает', r['message'])
        self.assertTrue(self.calls[0][0].endswith('ctl.py setmodel claude-b -'))

    def test_start_does_nothing_when_already_running(self):
        self.answer = {'ok': True, 'running': True}
        res = M.console_start()
        self.assertTrue(res['ok'])
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][0].endswith('ctl.py status'))

    def _start_calls(self, mode_obj):
        """Запуск кнопкой при заданном режиме: возвращает команды ctl, ушедшие на PROD."""
        _w(M.MODE_FILE, mode_obj)
        sid = '8b12fd2d-0546-46fa-82c5-2beaa741de1f'

        def fake(m, cmd, timeout=25, inp=None):
            self.calls.append((cmd, inp))
            if cmd.endswith('ctl.py status'):
                return 0, json.dumps({'ok': True, 'running': False})
            if cmd.endswith('ctl.py hist'):
                return 0, json.dumps({'ok': True, 'path': '/root/.claude/projects/-root/%s.jsonl' % sid, 'size': 5})
            return 0, json.dumps({'ok': True})

        cc_remote.ssh_run = fake
        M._cstart.update(t=None, error='')
        self.assertTrue(M.console_start()['ok'])
        M._cstart['t'].join(10)
        return [c for c, _ in self.calls], sid

    def test_start_when_work_is_on_prod_keeps_telegram_and_conversation(self):
        calls, sid = self._start_calls({'active': True, 'member': 'prod', 'tg': True})
        self.assertTrue(calls[-1].endswith('ctl.py start %s 1' % sid), calls)

    def test_start_when_work_is_on_prod_as_executor_has_no_telegram(self):
        calls, sid = self._start_calls({'active': True, 'member': 'prod', 'tg': False})
        self.assertTrue(calls[-1].endswith('ctl.py start %s 0' % sid), calls)

    def test_start_when_work_is_not_on_prod_stays_plain(self):
        calls, _ = self._start_calls({'active': False, 'member': 'prod'})
        self.assertTrue(calls[-1].endswith('ctl.py start - 0'), calls)
        self.assertFalse(any(c.endswith('ctl.py hist') for c in calls))


if __name__ == '__main__':
    unittest.main()
