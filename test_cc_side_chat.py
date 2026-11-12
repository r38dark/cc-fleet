"""Побочная беседа: ввод человека в вкладку, которую профиль держит на паузе (окно открывается на время ответа)."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import cc_fleet
import cc_profiles
from cc_profile_gate import decide
from cc_profiles import Profiles
from test_cc_profiles import FakeNative


class SideNative(FakeNative):
    """FakeNative + то, что нужно окну: пауза Codex и политика Claude."""

    def __init__(self, runtime):
        super().__init__()
        self.pause_calls = []
        self.pause_error = None
        self.claude = SimpleNamespace(runtime=Path(runtime))

    def _codex_pause(self, on):
        if self.pause_error:
            raise self.pause_error
        self.pause_calls.append(bool(on))

    def claude_policy(self, state):
        role = state.public()['engines']['claude']['role']
        return dict(expires=0, access='write', paused=role == 'paused', cwd='/test/work', workspace='/test/work',
                    write_roots=['/test/work'], read_roots=['/test/work'])


class SideChat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1000.0]
        self.native = SideNative(self.tmp.name)
        self.p = Profiles(self.tmp.name, self.native, lambda: self.now[0])
        self.busy = {'codex': False, 'claude': False}
        self.p.side_busy = {k: (lambda k=k: self.busy[k]) for k in self.busy}

    def pause(self, who):
        """Сценарий «Full у другого»: выбранный движок работает, второй на паузе."""
        other = 'codex' if who == 'claude' else 'claude'
        choices = {who: None, other: 'full'}
        r = self.p.apply_scenario(dict(choices=choices, confirm='подтверждаю', revision=self.p.state.revision))
        self.assertTrue(r['ok'], r)
        self.assertTrue(self.p.paused(who))
        self.native.pause_calls.clear()

    def test_paused_codex_is_closed_until_window_opens_and_bridge_stays_closed(self):
        self.pause('codex')
        self.assertFalse(self.p.input_allowed('codex'))
        self.assertFalse(self.p.console_allowed('codex'))
        self.assertEqual(self.p.side_open('codex'), (True, ''))
        self.assertEqual(self.native.pause_calls, [False])  # SIGCONT один раз
        self.assertTrue(self.p.side_active('codex'))
        self.assertTrue(self.p.console_allowed('codex'))
        self.assertFalse(self.p.input_allowed('codex'))  # мост и ротация Codex от окна не просыпаются

    def test_open_is_idempotent_and_extends_the_window(self):
        self.pause('codex')
        self.p.side_open('codex')
        until = self.p.side['codex']['until']
        self.now[0] += 30
        self.assertEqual(self.p.side_open('codex'), (True, ''))
        self.assertEqual(self.native.pause_calls, [False])  # повторно не будим
        self.assertGreater(self.p.side['codex']['until'], until)

    def test_not_paused_engine_needs_no_window(self):
        self.assertTrue(self.p.input_allowed('codex'))
        self.assertEqual(self.p.side_open('codex'), (True, ''))
        self.assertFalse(self.p.side_active('codex'))
        self.assertEqual(self.native.pause_calls, [])

    def test_unknown_engine_is_rejected(self):
        self.assertFalse(self.p.side_open('other')[0])

    def test_window_stays_while_busy_and_closes_after_silence(self):
        self.pause('codex')
        self.p.side_open('codex')
        self.busy['codex'] = True
        self.now[0] += cc_profiles.SIDE_IDLE + 10
        self.p.side_tick()
        self.assertTrue(self.p.side_active('codex'), 'пока отвечает — окно держится')
        self.assertEqual(self.native.pause_calls, [False])
        self.busy['codex'] = False
        self.now[0] += cc_profiles.SIDE_IDLE - 1
        self.p.side_tick()
        self.assertTrue(self.p.side_active('codex'), 'тишина ещё короче SIDE_IDLE')
        self.now[0] += 5
        self.p.side_tick()
        self.assertFalse(self.p.side_active('codex'))
        self.assertEqual(self.native.pause_calls, [False, True])  # снова заморожен
        self.assertFalse(self.p.console_allowed('codex'))

    def test_hard_cap_closes_even_if_still_busy(self):
        self.pause('codex')
        self.p.side_open('codex')
        self.busy['codex'] = True
        for _ in range(int(cc_profiles.SIDE_MAX // 60) + 2):
            self.now[0] += 60
            self.p.side_tick()
        self.assertFalse(self.p.side_active('codex'))
        self.assertEqual(self.native.pause_calls[-1], True)

    def test_busy_probe_error_counts_as_idle(self):
        self.pause('codex')
        self.p.side_open('codex')

        def boom():
            raise RuntimeError('нет данных')
        self.p.side_busy['codex'] = boom
        self.now[0] += cc_profiles.SIDE_IDLE + 1
        self.p.side_tick()
        self.assertFalse(self.p.side_active('codex'))

    def test_profile_change_drops_window_without_extra_pause_call(self):
        self.pause('codex')
        self.p.side_open('codex')
        r = self.p.apply_scenario(dict(choices=dict(claude=None, codex='full'), confirm='подтверждаю', revision=self.p.state.revision))
        self.assertTrue(r['ok'], r)  # теперь Codex ведёт, Claude на паузе
        self.assertFalse(self.p.side_active('codex'))
        self.assertTrue(self.p.input_allowed('codex'))
        self.native.pause_calls.clear()
        self.p.side_tick()
        self.assertEqual(self.native.pause_calls, [])

    def test_window_never_opens_during_transition_or_recovery(self):
        self.pause('codex')
        self.p.transitioning = True
        ok, text = self.p.side_open('codex')
        self.assertFalse(ok)
        self.assertIn('переключение', text)
        self.p.transitioning = False
        self.p.pending.write_text('{}')
        self.assertFalse(self.p.side_open('codex')[0])
        self.assertEqual(self.native.pause_calls, [])
        self.assertFalse(self.p.side_active('codex'))

    def test_wake_failure_leaves_no_window(self):
        self.pause('codex')
        self.native.pause_error = OSError('x')
        ok, text = self.p.side_open('codex')
        self.assertFalse(ok)
        self.assertIn('Не удалось разбудить', text)
        self.assertFalse(self.p.side_active('codex'))
        self.assertFalse(self.p.console_allowed('codex'))

    def test_failed_return_to_pause_still_closes_window(self):
        self.pause('codex')
        self.p.side_open('codex')
        self.native.pause_error = ProcessLookupError('нет процесса')
        self.now[0] += cc_profiles.SIDE_IDLE + 1
        self.p.side_tick()  # не должно падать
        self.assertFalse(self.p.side_active('codex'))

    def test_claude_side_policy_is_read_only_and_restored(self):
        self.pause('claude')
        policy = Path(self.tmp.name) / 'claude-policy.json'
        policy.write_text(json.dumps(self.native.claude_policy(self.p.state)))
        event_prompt = {'hook_event_name': 'UserPromptSubmit'}
        self.assertTrue(decide(json.loads(policy.read_text()), event_prompt))  # на паузе хук режет любой ввод
        self.assertEqual(self.p.side_open('claude'), (True, ''))
        opened = json.loads(policy.read_text())
        self.assertFalse(opened['paused'])
        self.assertEqual(decide(opened, event_prompt), '')
        bash = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}
        edit = {'hook_event_name': 'PreToolUse', 'tool_name': 'Edit', 'tool_input': {'file_path': '/test/work/a.txt'}}
        read = {'hook_event_name': 'PreToolUse', 'tool_name': 'Read', 'tool_input': {'file_path': '/test/work/a.txt'}}
        self.assertTrue(decide(opened, bash), 'команды в побочной беседе запрещены')
        self.assertTrue(decide(opened, edit), 'запись в побочной беседе запрещена')
        self.assertEqual(decide(opened, read), '')
        self.now[0] += cc_profiles.SIDE_IDLE + 1
        self.p.side_tick()
        self.assertFalse(self.p.side_active('claude'))
        closed = json.loads(policy.read_text())
        self.assertTrue(closed['paused'])
        self.assertTrue(decide(closed, event_prompt))

    def test_claude_without_policy_file_does_not_create_one(self):
        self.pause('claude')
        self.assertEqual(self.p.side_open('claude'), (True, ''))
        self.assertFalse((Path(self.tmp.name) / 'claude-policy.json').exists())
        self.now[0] += cc_profiles.SIDE_IDLE + 1
        self.p.side_tick()
        self.assertFalse((Path(self.tmp.name) / 'claude-policy.json').exists())


class SideLabel(unittest.TestCase):
    """Метка «ответь в консоли» добавляется только в окне побочной беседы и не ломает слэш-команды."""

    def codex(self):
        con = SimpleNamespace(send_input=mock.Mock(return_value=(True, 'sent')))
        return cc_fleet.ConsoleInput({'cc_codex_console': con}), con

    def test_side_window_adds_label_once_to_codex_text(self):
        obj, con = self.codex()
        self.assertTrue(obj.send('codex', 'сколько будет 2+2?', 'nonce1234', side=True)[0])
        con.send_input.assert_called_once_with(cc_fleet.SIDE_LABEL + 'сколько будет 2+2?')
        self.assertIn('не в Telegram', cc_fleet.SIDE_LABEL)

    def test_normal_input_has_no_label(self):
        obj, con = self.codex()
        obj.send('codex', 'обычное сообщение', 'nonce1234')
        con.send_input.assert_called_once_with('обычное сообщение')

    def test_slash_commands_stay_commands_in_side_window(self):
        obj, con = self.codex()
        obj.send('codex', '/compact', 'nonce1234', side=True)
        obj.send('codex', '/model gpt-5', 'nonce5678', side=True)
        self.assertEqual([c.args[0] for c in con.send_input.call_args_list], ['/compact', '/model gpt-5'])

    def test_retry_with_same_nonce_does_not_double_label_or_resend(self):
        obj, con = self.codex()
        obj.send('codex', 'вопрос', 'nonce1234', side=True)
        self.assertTrue(obj.send('codex', 'вопрос', 'nonce1234', side=True)[0])
        self.assertFalse(obj.send('codex', 'другой', 'nonce1234', side=True)[0])
        self.assertEqual(con.send_input.call_count, 1)

    def test_claude_paste_carries_the_label(self):
        with tempfile.TemporaryDirectory() as folder:
            obj = cc_fleet.ConsoleInput({'BASE': folder, 'cfg': lambda: {'screen_session': 'fake'}, 'session_busy': lambda: False})
            seen = []

            def run(args, **kw):
                if args[-2] == 'readbuf':
                    seen.append(Path(args[-1]).read_text())
                return SimpleNamespace(returncode=0)
            with mock.patch.object(cc_fleet.subprocess, 'run', side_effect=run), mock.patch.object(cc_fleet.time, 'sleep'):
                self.assertTrue(obj.send('claude', 'как дела?', 'nonce1234', side=True)[0])
                self.assertTrue(obj.send('claude', 'как дела?', 'nonce5678')[0])
            self.assertEqual(seen, ['\x1b[200~' + cc_fleet.SIDE_LABEL + 'как дела?\x1b[201~', '\x1b[200~как дела?\x1b[201~'])


class SideClaudeStart(unittest.TestCase):
    """Запуск побочной сессии Claude на dev, пока основной остановлен (2b). Живой запуск не делается: subprocess подменён."""

    def ns(self, folder):
        return {'BASE': folder, 'cfg': lambda: {'screen_session': 'testscreen'}}

    def runner(self, alive, start_rc=0, ready=True, calls=None, plugin=False):
        def run(args, **kw):
            if calls is not None:
                calls.append(list(args))
            if args[0] == 'pgrep':
                return SimpleNamespace(returncode=0 if plugin else 1, stdout='', stderr='')
            if args[:2] == ['screen', '-ls']:
                return SimpleNamespace(returncode=0, stdout=('There is a screen on:\n\t123.testscreen\t(Detached)\n' if alive[0] else 'No Sockets found.\n'), stderr='')
            if args[0] == 'systemd-run':
                if start_rc == 0:
                    alive[0] = True
                return SimpleNamespace(returncode=start_rc, stdout='', stderr='')
            if 'hardcopy' in args:
                if ready:
                    Path(args[-1]).write_text('some banner\n? for shortcuts\n')
                return SimpleNamespace(returncode=0 if ready else 1, stdout='', stderr='')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        return run

    def test_running_claude_is_never_started_again(self):
        alive, calls = [True], []
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=self.runner(alive, calls=calls)):
            self.assertEqual(cc_fleet.start_side_claude(self.ns(folder)), (True, ''))
        self.assertFalse([c for c in calls if c[0] == 'systemd-run'])

    def test_stopped_claude_starts_side_script_without_telegram_and_waits_for_prompt(self):
        alive, calls = [False], []
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=self.runner(alive, calls=calls)), \
                mock.patch.object(cc_fleet.time, 'sleep'):
            ns = self.ns(folder)
            self.assertEqual(cc_fleet.start_side_claude(ns), (True, ''))
            self.assertFalse(list(Path(folder).iterdir()), 'временный файл экрана удалён')
            side = cc_fleet.side_script(ns)
        starts = [c for c in calls if c[0] == 'systemd-run']
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0][-1], side)
        self.assertTrue(side.endswith('/start_claude_side.sh'), 'побочный скрипт лежит рядом с панелью')
        self.assertNotIn('start_claude.sh', side.rsplit('/', 1)[-1].replace('start_claude_side.sh', ''), 'основной скрипт с Telegram не используется')

    def test_session_that_brought_telegram_plugin_is_stopped_at_once(self):
        """R2-3: если --settings не отключил плагин, побочную гасим — иначе второй опрос бота отнимает сообщения у ведущего."""
        alive, calls = [False], []
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=self.runner(alive, calls=calls, plugin=True)), \
                mock.patch.object(cc_fleet.time, 'sleep'), mock.patch.object(cc_fleet.os, 'unlink') as unlink:
            ok, message = cc_fleet.start_side_claude(self.ns(folder))
        self.assertFalse(ok)
        self.assertIn('плагином Telegram', message)
        self.assertIn(['screen', '-S', 'testscreen', '-X', 'quit'], calls)
        self.assertIn(['pkill', '-f', cc_fleet.SIDE_TG_MARK], calls)
        self.assertIn(cc_fleet.SIDE_CLAUDE_FLAG, [c.args[0] for c in unlink.call_args_list])

    def test_clean_session_is_kept_and_waits_for_plugin_to_show_up(self):
        alive, calls = [False], []
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=self.runner(alive, calls=calls)), \
                mock.patch.object(cc_fleet.time, 'sleep') as nap:
            self.assertEqual(cc_fleet.start_side_claude(self.ns(folder)), (True, ''))
        nap.assert_any_call(cc_fleet.SIDE_TG_SETTLE)
        self.assertNotIn(['screen', '-S', 'testscreen', '-X', 'quit'], calls)

    def test_script_refusal_reports_and_does_not_wait(self):
        alive = [False]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=self.runner(alive, start_rc=2)), \
                mock.patch.object(cc_fleet.time, 'sleep') as nap:
            ok, message = cc_fleet.start_side_claude(self.ns(folder))
        self.assertFalse(ok)
        self.assertIn('не запущена', message)
        nap.assert_not_called()

    def test_prompt_never_ready_times_out_with_clear_message(self):
        alive = [False]
        clock = [0.0]
        def tick(sec):
            clock[0] += sec
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=self.runner(alive, ready=False)), \
                mock.patch.object(cc_fleet.time, 'sleep', side_effect=tick), mock.patch.object(cc_fleet.time, 'time', side_effect=lambda: clock[0]):
            ok, message = cc_fleet.start_side_claude(self.ns(folder))
        self.assertFalse(ok)
        self.assertIn('не готова', message)

    def test_missing_binary_is_reported(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cc_fleet.subprocess, 'run', side_effect=FileNotFoundError('screen')):
            self.assertFalse(cc_fleet.claude_alive(self.ns(folder)))
            ok, message = cc_fleet.start_side_claude(self.ns(folder))
        self.assertFalse(ok)
        self.assertIn('Не удалось запустить', message)

    def test_side_script_does_not_leave_bare_bash_after_claude_exits(self):
        """R2-1: после выхода Claude screen testscreen должен закрыться; голый bash считался бы «основной Claude работает»."""
        text = (Path(__file__).parent / 'scripts' / 'start_claude_side.sh').read_text(encoding='utf-8')
        self.assertNotIn('exec bash', text)
        line = [x for x in text.splitlines() if x.startswith('screen -U -S "$SCREEN"')][0]
        self.assertTrue(line.rstrip().endswith('rm -f $SIDE_FLAG"'), line[-80:])   # claude …; rm -f флаг — и всё

    def test_flag_helper_follows_file(self):
        with tempfile.TemporaryDirectory() as folder:
            flag = Path(folder) / 'side_claude.json'
            with mock.patch.object(cc_fleet, 'SIDE_CLAUDE_FLAG', str(flag)), \
                    mock.patch.object(cc_fleet.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='')):   # плагина Telegram нет
                self.assertFalse(cc_fleet.side_claude_flag())
                flag.write_text('{}')
                self.assertTrue(cc_fleet.side_claude_flag())
                cc_fleet.subprocess.run.return_value = SimpleNamespace(returncode=0, stdout='', stderr='')   # плагин работает: основной Claude, флаг устарел
                self.assertFalse(cc_fleet.side_claude_flag())


class SideClaudeRoute(unittest.TestCase):
    """Маршрут /api/console/input для вкладки Claude, когда основной Claude остановлен (2c/2d): вопрос «Да», запуск, метка."""

    def route(self, body, alive, flag=False, start=(True, ''), sent=(True, 'ok')):
        import test_cc_fleet_overview as overview
        helper = overview.Routes('fixture')
        self.addCleanup(helper.doCleanups)   # временные папки заготовки маршрута
        handler, ns = helper.fixture('/api/console/input', dict(session='claude', request_id='side-req-0001', text='как дела?', **body))
        ns['cfg'] = lambda: {'screen_session': 'testscreen'}
        ns['session_busy'] = lambda: False
        patches = dict(
            alive=mock.patch.object(cc_fleet, 'claude_alive', return_value=alive),
            flag=mock.patch.object(cc_fleet, 'side_claude_flag', return_value=flag),
            start=mock.patch.object(cc_fleet, 'start_side_claude', return_value=start),
            send=mock.patch.object(cc_fleet.ConsoleInput, '_claude', return_value=sent))
        started = {name: patch.start() for name, patch in patches.items()}
        self.addCleanup(lambda: [patch.stop() for patch in patches.values()])
        return handler.do_POST(), started

    def test_stopped_claude_asks_before_starting_anything(self):
        (status, data), mocks = self.route({}, alive=False)
        self.assertEqual(status, 200)
        self.assertFalse(data['ok'])
        self.assertEqual(data['ask'], 'side')
        self.assertIn('остановлен', data['message'])
        mocks['start'].assert_not_called()
        mocks['send'].assert_not_called()

    def test_yes_starts_side_session_and_sends_text_with_label(self):
        (status, data), mocks = self.route({'side': True}, alive=False)
        self.assertEqual((status, data['ok']), (200, True))
        mocks['start'].assert_called_once()
        mocks['send'].assert_called_once_with(cc_fleet.SIDE_LABEL + 'как дела?')

    def test_failed_start_reports_reason_and_sends_nothing(self):
        (status, data), mocks = self.route({'side': True}, alive=False, start=(False, 'Побочная сессия Claude не запущена (код 3).'))
        self.assertFalse(data['ok'])
        self.assertIn('не запущена', data['message'])
        mocks['send'].assert_not_called()

    def test_running_main_claude_is_not_restarted_and_gets_plain_text(self):
        (status, data), mocks = self.route({}, alive=True)
        self.assertEqual((status, data['ok']), (200, True))
        mocks['start'].assert_not_called()
        mocks['send'].assert_called_once_with('как дела?')

    def test_running_main_claude_ignores_side_flag_from_page(self):
        (status, data), mocks = self.route({'side': True}, alive=True)
        self.assertTrue(data['ok'])
        mocks['start'].assert_not_called()
        mocks['send'].assert_called_once_with('как дела?')

    def test_existing_side_session_keeps_label_without_second_start(self):
        (status, data), mocks = self.route({}, alive=True, flag=True)
        self.assertTrue(data['ok'])
        mocks['start'].assert_not_called()
        mocks['send'].assert_called_once_with(cc_fleet.SIDE_LABEL + 'как дела?')


class SideTeardown(unittest.TestCase):
    """Побочная сессия Claude делит screen с основным: панель гасит её перед основным запуском, передачей и сменой режима (пункт 3)."""

    def setUp(self):
        import cc_workers
        self.M = cc_workers
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.flag = Path(self.tmp.name) / 'side_claude.json'
        self.screen = [False]     # есть ли screen testscreen
        self.plugin = [False]     # работает ли плагин Telegram (у основного Claude он есть)
        self.runs = []

        def run(args, timeout=30):
            self.runs.append(list(args))
            if args[:2] == ['screen', '-ls']:
                return 0, ('\t123.testscreen\t(Detached)\n' if self.screen[0] else 'No Sockets found.')
            if args[:2] == ['screen', '-S'] and 'quit' in args:
                self.screen[0] = False
                self.plugin[0] = False
                return 0, ''
            if args[0] == 'pgrep':
                return (0 if self.plugin[0] else 1), ''
            if args[0] == 'systemd-run':
                self.screen[0] = self.plugin[0] = True      # start_claude.sh: основной Claude с Telegram
                return 0, ''
            return 0, ''
        patches = [mock.patch.object(cc_workers, '_run', run), mock.patch.object(cc_workers, 'SIDE_FLAG', str(self.flag)),
                   mock.patch.object(cc_workers.time, 'sleep')]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.wk = cc_workers.Workers.__new__(cc_workers.Workers)
        self.wk.ns = {'cfg': lambda: {'screen_session': 'testscreen'}}

    def start_side(self):
        self.screen[0], self.plugin[0] = True, False
        self.flag.write_text('{}')

    def test_side_session_is_not_counted_as_main_claude(self):
        self.start_side()
        self.assertTrue(self.wk.screen_busy())
        self.assertTrue(self.wk.side_running())
        self.assertFalse(self.wk.claude_running())

    def test_main_claude_with_telegram_ignores_stale_flag(self):
        self.screen[0], self.plugin[0] = True, True
        self.flag.write_text('{}')
        self.assertFalse(self.wk.side_running())
        self.assertTrue(self.wk.claude_running())

    def test_stopped_claude_with_old_flag_is_not_side(self):
        self.flag.write_text('{}')
        self.assertFalse(self.wk.side_running())
        self.assertFalse(self.wk.claude_running())

    def test_start_claude_stops_side_first_and_clears_flag(self):
        self.start_side()
        self.assertTrue(self.wk.start_claude())
        order = [r[0] for r in self.runs if r[0] in ('systemd-run',) or (r[:2] == ['screen', '-S'] and 'quit' in r)]
        self.assertEqual(order, ['screen', 'systemd-run'], 'сначала screen quit побочной, потом запуск основного')
        self.assertFalse(self.flag.exists())
        self.assertTrue(self.wk.claude_running())
        self.assertFalse(self.wk.side_running())

    def test_start_claude_without_side_does_not_quit_anything(self):
        self.assertTrue(self.wk.start_claude())
        self.assertFalse([r for r in self.runs if 'quit' in r])

    def test_stop_claude_removes_flag_that_script_could_not_remove(self):
        self.start_side()
        self.assertTrue(self.wk.stop_claude())
        self.assertFalse(self.flag.exists())
        self.assertFalse(self.wk.screen_busy())

    def test_flag_constants_match_between_panel_modules_and_script(self):
        import re
        source = Path(self.M.__file__).read_text()          # SIDE_FLAG подменён в setUp, поэтому сверяем по тексту модуля
        self.assertEqual(re.search(r"^SIDE_FLAG = '([^']+)'", source, re.M).group(1), cc_fleet.SIDE_CLAUDE_FLAG)
        self.assertIn('SIDE_FLAG="$BASE/' + Path(cc_fleet.SIDE_CLAUDE_FLAG).name + '"', (Path(__file__).parent / 'scripts' / 'start_claude_side.sh').read_text())


if __name__ == '__main__':
    unittest.main()
