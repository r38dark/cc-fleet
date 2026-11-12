# Вместо паузы по лимитам — передача на Claude PROD (, 07.11.26): хуки просят панель, панель передаёт сразу.
# Ни боевая папка, ни Telegram, ни ssh не трогаются: все файлы во временной папке.
# python3 -m unittest test_cc_pause_handoff -v
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import cc_remote as R
import cc_remote_auto as A
import cc_remote_mode as M
import pause_ctl as pc
import tg_queue as Q

FUTURE = '2099-01-01T00:00:00+00:00'


def put(path, doc):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def get(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


class Files(unittest.TestCase):
    """Подмена всех файлов cc_remote_auto / cc_remote / pause_ctl на временные + заглушки того, что читает боевое состояние."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='ccph_')
        self.addCleanup(shutil.rmtree, self.d, True)
        j = lambda n: os.path.join(self.d, n)
        self.saved = [(A, n, getattr(A, n)) for n in ('CFG_FILE', 'KICK_FILE', 'HB_FILE', 'MODE_FILE')]
        self.saved += [(R, n, getattr(R, n)) for n in ('MEMBERS_FILE', 'STATE_FILE')]
        self.saved += [(pc, n, getattr(pc, n)) for n in ('STATE', 'level_state', '_threshold', '_weekly_cap',
                                                           'nearest_reset', '_tg', '_log')]
        self.saved += [(Q, 'QUEUE', Q.QUEUE)]
        self.addCleanup(self.restore)
        A.CFG_FILE, A.KICK_FILE, A.HB_FILE, A.MODE_FILE = j('auto.json'), j('kick.json'), j('hb.json'), j('mode.json')
        R.MEMBERS_FILE, R.STATE_FILE = j('members.json'), j('rstate.json')
        pc.STATE = j('pause_state.json')
        Q.QUEUE = j('tg_queue.jsonl')
        self.ls = dict(level='hard', stale=False, line='acc3 90%', why='все выше порога', accounts={}, active='acc3')
        pc.level_state = lambda: self.ls
        pc._threshold = lambda: 90
        pc._weekly_cap = lambda: 99
        pc.nearest_reset = lambda week=False: ('', '')
        self.tgs = []
        pc._tg = lambda text, force=False: self.tgs.append(text)
        pc._log = lambda m: None
        self.now = time.time()
        put(A.CFG_FILE, dict(enabled=True, dry_run=False, ticks=2, min_stay=600, cooldown=900, sim_level='', sim_prod=''))
        put(R.MEMBERS_FILE, {'prod': {'label': 'PROD', 'host': '192.0.2.1'}})
        self.prod_row = {'online': True, 'error': '', 'ts': self.now - 30,
                         'five_hour': {'pct': 12.0, 'resets_at': FUTURE}, 'seven_day': {'pct': 9.0, 'resets_at': FUTURE}}
        put(R.STATE_FILE, {'prod': self.prod_row})
        put(A.HB_FILE, {'ts': self.now - 5, 'last_return': 0})
        put(A.MODE_FILE, {'active': False, 'stage': ''})

    def restore(self):
        for owner, name, val in self.saved:
            setattr(owner, name, val)

    def fresh(self, at):
        """Пульс панели и цифры PROD «свежие» на момент at (как их обновляет поток панели)."""
        put(A.HB_FILE, {'ts': at - 5, 'last_return': 0})
        put(R.STATE_FILE, {'prod': dict(self.prod_row, ts=at - 30)})

    def cfg(self, **kw):
        c = get(A.CFG_FILE)
        c.update(kw)
        put(A.CFG_FILE, c)


class Ready(Files):
    def test_all_conditions_ok(self):
        ok, why = A.handoff_ready(self.now)
        self.assertTrue(ok, why)

    def test_each_blocker_keeps_the_plain_pause(self):
        self.cfg(enabled=False)
        self.assertFalse(A.handoff_ready(self.now)[0])
        self.cfg(enabled=True, dry_run=True)
        self.assertFalse(A.handoff_ready(self.now)[0])          # пробный режим ничего не передаёт — значит и паузу не отменяет
        self.cfg(dry_run=False)
        os.remove(A.HB_FILE)
        self.assertFalse(A.handoff_ready(self.now)[0])          # панель не отвечает — принять запрос некому
        put(A.HB_FILE, {'ts': self.now - 200})
        self.assertFalse(A.handoff_ready(self.now)[0])          # пульс протух
        put(A.HB_FILE, {'ts': self.now - 5, 'last_return': self.now - 100})
        ok, why = A.handoff_ready(self.now)
        self.assertFalse(ok)
        self.assertIn('рано после переключения', why)            # кулдаун 15 мин после переключения с PROD
        put(A.HB_FILE, {'ts': self.now - 5, 'last_return': self.now - 1000})
        self.assertTrue(A.handoff_ready(self.now)[0])
        put(A.MODE_FILE, {'active': True})
        self.assertFalse(A.handoff_ready(self.now)[0])          # уже на PROD
        put(A.MODE_FILE, {'active': False, 'stage': ''})
        self.ls['level'] = 'none'
        self.assertFalse(A.handoff_ready(self.now)[0])          # у DEV есть, где работать
        self.ls['level'] = 'gate'
        self.assertFalse(A.handoff_ready(self.now)[0])          # балансер ещё сам уйдёт на другой аккаунт DEV
        self.ls.update(level='hard', stale=True)
        self.assertFalse(A.handoff_ready(self.now)[0])
        self.ls['stale'] = False

    def test_week_levels_count_too(self):
        for lvl in ('week', 'weekrisk'):
            self.ls['level'] = lvl
            self.assertTrue(A.handoff_ready(self.now)[0], lvl)

    def test_prod_numbers(self):
        put(R.STATE_FILE, {'prod': dict(self.prod_row, ts=self.now - 700)})
        ok, why = A.handoff_ready(self.now)
        self.assertFalse(ok)
        self.assertIn('свежих цифр', why)
        put(R.STATE_FILE, {})
        self.assertFalse(A.handoff_ready(self.now)[0])
        put(R.STATE_FILE, {'prod': dict(self.prod_row, five_hour={'pct': 95.0, 'resets_at': FUTURE})})
        ok, why = A.handoff_ready(self.now)
        self.assertFalse(ok)
        self.assertIn('непригоден', why)
        self.cfg(sim_prod='1')
        self.assertTrue(A.handoff_ready(self.now)[0])           # подмена для живой проверки
        put(R.STATE_FILE, {'prod': self.prod_row})
        self.cfg(sim_prod='0')
        self.assertFalse(A.handoff_ready(self.now)[0])

    def test_transfer_in_progress_is_not_a_reason_for_pause(self):
        put(A.MODE_FILE, {'active': False, 'stage': 'начало', 'since_ts': self.now - 20})
        self.assertEqual(A.request_handoff(self.now), (True, 'передача на PROD уже идёт'))
        self.assertFalse(os.path.exists(A.KICK_FILE))


class Kick(Files):
    def test_request_writes_one_kick_and_is_idempotent(self):
        self.assertTrue(A.request_handoff(self.now)[0])
        first = get(A.KICK_FILE)['ts']
        self.assertEqual(first, self.now)
        self.assertTrue(A.pending(self.now + 5))
        self.assertTrue(A.request_handoff(self.now + 5)[0])      # хук зовут на каждый инструмент — запрос один
        self.assertEqual(get(A.KICK_FILE)['ts'], first)

    def test_kick_the_panel_did_not_take_means_plain_pause(self):
        A.request_handoff(self.now)
        self.fresh(self.now + 100)
        self.assertFalse(A.pending(self.now + 100))
        ok, why = A.request_handoff(self.now + 100)
        self.assertFalse(ok)
        self.assertIn('не подхватила', why)

    def test_old_unclaimed_kick_does_not_block_a_new_cycle(self):
        A.request_handoff(self.now)
        self.fresh(self.now + 3000)
        self.assertTrue(A.request_handoff(self.now + 3000)[0])
        self.assertEqual(get(A.KICK_FILE)['ts'], self.now + 3000)

    def test_taken_kick_allows_the_next_one(self):
        A.request_handoff(self.now)
        A._kick_taken(self.now)
        self.assertFalse(A.pending(self.now + 1))
        self.fresh(self.now + 400)
        self.assertTrue(A.request_handoff(self.now + 400)[0])
        self.assertEqual(get(A.KICK_FILE)['ts'], self.now + 400)

    def test_taken_mark_ignores_a_newer_kick(self):
        A.request_handoff(self.now)
        A._kick_taken(self.now - 1)                              # отметка про другой запрос
        self.assertNotIn('taken', get(A.KICK_FILE))

    def test_heartbeat_keeps_return_time_for_cooldown(self):
        A._memo['last_return'] = 1234.0
        try:
            A._heartbeat()
        finally:
            A._memo['last_return'] = 0.0
        d = get(A.HB_FILE)
        self.assertEqual(d['last_return'], 1234.0)
        self.assertAlmostEqual(d['ts'], time.time(), delta=5)


class PauseSet(Files):
    """pause_ctl.cmd_set: вместо паузы — запрос на передачу; все прежние пути паузы целы."""

    def ns(self, **kw):
        return argparse.Namespace(**dict(dict(reason='лимиты сессионного окна', resume_at='', note='остановлен'), **kw))

    def test_handoff_instead_of_pause(self):
        self.assertEqual(pc.cmd_set(self.ns()), 0)
        self.assertFalse(os.path.exists(pc.STATE), 'пауза не должна ставиться')
        self.assertEqual(self.tgs, [], 'и в чат про паузу не пишем')
        self.assertTrue(A.pending())

    def test_plain_pause_when_handoff_is_not_possible(self):
        self.cfg(enabled=False)
        pc.cmd_set(self.ns())
        st = get(pc.STATE)
        self.assertTrue(st['active'])
        self.assertTrue(self.tgs and 'пауза по лимитам' in self.tgs[0])

    def test_no_handoff_flag_forces_the_pause(self):
        pc.cmd_set(self.ns(no_handoff=True))
        self.assertTrue(get(pc.STATE)['active'])
        self.assertFalse(os.path.exists(A.KICK_FILE))

    def test_handoff_error_falls_back_to_pause(self):
        orig = A.request_handoff
        A.request_handoff = lambda *a, **k: 1 / 0
        self.addCleanup(setattr, A, 'request_handoff', orig)
        pc.cmd_set(self.ns())
        self.assertTrue(get(pc.STATE)['active'])

    def test_manual_enable_button_is_a_real_pause(self):
        put(pc.STATE, {'override': True})
        pc.cmd_on(argparse.Namespace(by='web panel'))
        self.assertTrue(get(pc.STATE)['active'])
        self.assertFalse(os.path.exists(A.KICK_FILE))

    def test_cli_set_is_a_real_pause(self):
        import sys
        old = sys.argv
        sys.argv = ['pause_ctl.py', 'set', '--reason', 'руками']
        try:
            pc.main()
        finally:
            sys.argv = old
        self.assertTrue(get(pc.STATE)['active'])

    def test_release_clears_limits_pause(self):
        self.assertFalse(pc.release_for_remote())                                  # паузы нет
        put(pc.STATE, {'active': True, 'kind': 'session', 'remote_hold': 5.0, 'since': 1})
        self.assertTrue(pc.release_for_remote())
        st = get(pc.STATE)
        self.assertFalse(st['active'])
        self.assertNotIn('remote_hold', st)
        put(pc.STATE, {'active': True, 'kind': 'reserve', 'since': 1})
        self.assertTrue(pc.release_for_remote())                                   # запись прежней версии — обычная пауза
        put(pc.STATE, {'active': True, 'kind': 'week', 'since': 1})
        self.assertTrue(pc.release_for_remote())


class Tick(Files):
    def setUp(self):
        super().setUp()
        self.calls, self.sent, self.released, self.set_calls = [], [], [], []
        for owner, name in ((A, '_snapshot'), (A, '_queue_text'), (A, '_queue_taken'), (M, 'mode'), (M, 'busy'), (M, 'active'),
                            (M, 'on'), (M, 'off'), (M, 'pair_kind'), (pc, 'release_for_remote'), (pc, 'cmd_set')):
            self.addCleanup(setattr, owner, name, getattr(owner, name))
        self.state = dict(native=dict(level='hard', role='solo', stale=False),
                          prod=dict(usable=True, why='', row={'five_hour': {'pct': 12.0}, 'seven_day': {'pct': 9.0}}))
        A._snapshot = lambda ns, mid: (self.state['native'], self.state['prod'])
        A._queue_text = lambda: ('1) 20:00 от Owner:\nпривет', [111.0])
        self.taken = []
        A._queue_taken = self.taken.append
        self.md = dict(active=False)
        M.mode = lambda: self.md
        M.busy = lambda: False
        M.active = lambda: bool(self.md.get('active'))
        M.pair_kind = lambda: ''
        self.on_res = dict(ok=True)
        M.on = lambda mid, reason, queued='', *a, **k: (self.calls.append(('on', reason, queued)), self.on_res)[1]
        M.off = lambda reason, *a, **k: (self.calls.append(('off', reason)), dict(ok=True))[1]
        pc.release_for_remote = lambda: self.released.append(1) or True
        pc.cmd_set = lambda a: self.set_calls.append(a) or 0
        A._memo.update(to_prod=0, to_native=0, both_notified=False, last_return=0.0)
        self.ns = dict(tg_notify=lambda t: self.sent.append(t))

    def test_kicked_tick_hands_off_without_waiting_for_the_second_tick(self):
        self.assertEqual(A.tick(self.ns, kicked=True), 'to_prod')
        self.assertEqual([c[0] for c in self.calls], ['on'])
        self.assertEqual(self.set_calls, [], 'передача началась — паузы нет')
        self.assertEqual(self.released, [1], 'стоявшая пауза снимается')
        self.assertIn('Переход на Claude PROD', self.sent[0])

    def test_queued_messages_travel_with_the_handoff(self):
        A.tick(self.ns, kicked=True)
        self.assertIn('привет', self.calls[0][2])
        self.assertEqual(self.taken, [[111.0]], 'ушедшие сообщения помечены разобранными')

    def test_regular_two_tick_path_also_releases_the_pause(self):
        A.tick(self.ns)
        self.assertEqual(self.calls, [])
        self.assertEqual(A.tick(self.ns), 'to_prod')
        self.assertEqual(self.released, [1])
        self.assertEqual(self.set_calls, [])

    def test_failed_start_puts_the_pause_after_a_kick(self):
        self.on_res = dict(ok=False, message='занято')
        A.tick(self.ns, kicked=True)
        self.assertEqual(self.taken, [])
        self.assertEqual(self.released, [])
        self.assertEqual(len(self.set_calls), 1)
        self.assertTrue(self.set_calls[0].no_handoff)             # второй раз передачу не спрашиваем
        self.assertIn('не состоялась', self.set_calls[0].note)

    def test_prod_became_unusable_means_pause(self):
        self.state['prod'] = dict(usable=False, why='лимит', row={})
        A.tick(self.ns, kicked=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.set_calls), 1)

    def test_not_solo_role_means_pause(self):
        self.state['native']['role'] = 'leader'
        A.tick(self.ns, kicked=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.set_calls), 1)

    def test_disabled_after_kick_means_pause(self):
        self.cfg(enabled=False)
        A.tick(self.ns, kicked=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.set_calls), 1)

    def test_snapshot_crash_means_pause_and_loop_survives(self):
        def boom(ns, mid):
            raise RuntimeError('ssh')
        A._snapshot = boom
        with self.assertRaises(RuntimeError):
            A.tick(self.ns, kicked=True)
        self.assertEqual(len(self.set_calls), 1)

    def test_repeat_kick_during_transfer_does_not_pause(self):
        M.busy = lambda: True
        A.tick(self.ns, kicked=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.set_calls, [])

    def test_no_pause_when_level_is_fine_again(self):
        self.state['native']['level'] = 'none'
        self.ls['level'] = 'none'
        A.tick(self.ns, kicked=True)
        self.assertEqual(self.set_calls, [])                      # лимит вернулся, пока шёл запрос: паузы не нужно

    def test_without_kick_nothing_is_paused(self):
        self.state['prod'] = dict(usable=False, why='', row={})
        A.tick(self.ns)
        self.assertEqual(self.set_calls, [])


class Queue(Files):
    def test_text_and_taken_roundtrip(self):
        rows = [dict(ts=1.0, chat_id='1', message_id='1', user='Owner', text='первое', taken_ts=0),
                dict(ts=2.0, chat_id='1', message_id='2', user='Owner', text='второе', taken_ts=0),
                dict(ts=3.0, chat_id='1', message_id='3', user='Owner', text='старое', taken_ts=9.0)]
        Q._rewrite(rows)
        text, stamps = A._queue_text()
        self.assertIn('первое', text)
        self.assertIn('второе', text)
        self.assertNotIn('старое', text)
        self.assertEqual(stamps, [1.0, 2.0])
        Q._rewrite(Q._rows() + [dict(ts=4.0, chat_id='1', message_id='4', user='Owner', text='пришло позже', taken_ts=0)])
        A._queue_taken(stamps)
        left = [r['text'] for r in Q._pending()]
        self.assertEqual(left, ['пришло позже'])                   # не помечаем то, что пришло уже после выборки

    def test_empty_queue(self):
        self.assertEqual(A._queue_text(), ('', []))
        A._queue_taken([])

    def test_ack_says_handoff_not_pause(self):
        args = argparse.Namespace(chat='1', msg_id='5', user='Owner', ts='', text_file='', notify=False)
        import io
        import contextlib
        import sys
        old = sys.stdin
        sys.stdin = io.StringIO('привет')
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = Q.cmd_enqueue(args)
        finally:
            sys.stdin = old
        self.assertEqual(code, 10)
        self.assertIn('передаю работу на Claude PROD', buf.getvalue())
        self.assertFalse(os.path.exists(pc.STATE))


class Hooks(unittest.TestCase):
    """Настоящие хуки Claude в отдельных процессах, пакет скопирован в чистую папку: что видит Claude и что остаётся на диске."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='ccph_e2e_')
        self.addCleanup(shutil.rmtree, self.d, True)
        here = os.path.dirname(os.path.abspath(__file__))
        for n in ('pause_ctl.py', 'tg_queue.py', 'cc_avail.py', 'cc_remote_auto.py', 'cc_remote.py', 'limits_gate.py'):
            shutil.copy(os.path.join(here, n), self.d)
        os.makedirs(os.path.join(self.d, 'hooks'))
        for n in ('pause_tool_gate.py', 'queue_on_limits.py'):
            shutil.copy(os.path.join(here, 'hooks', n), os.path.join(self.d, 'hooks'))
        now = time.time()
        # единственный аккаунт Claude DEV выше порога сессии, уйти некуда → уровень hard
        put(os.path.join(self.d, 'snapshot.json'), {'ts': now, 'active': 'acc3', 'accounts': {'acc3': {
            'active': True, 'plan': 'pro', 'five_hour': {'pct': 92.0, 'resets_at': FUTURE}, 'seven_day': {'pct': 10.0, 'resets_at': FUTURE}}}})
        put(os.path.join(self.d, 'config.json'), {})
        put(os.path.join(self.d, 'remote_auto.json'), dict(enabled=True, dry_run=False, ticks=2, min_stay=600, cooldown=900, sim_level='', sim_prod=''))
        put(os.path.join(self.d, 'remote_members.json'), {'prod': {'label': 'PROD', 'host': '192.0.2.1'}})
        put(os.path.join(self.d, 'remote_state.json'), {'prod': {'online': True, 'error': '', 'ts': now - 20,
                                                                  'five_hour': {'pct': 10.0, 'resets_at': FUTURE}, 'seven_day': {'pct': 5.0, 'resets_at': FUTURE}}})
        put(os.path.join(self.d, 'remote_auto_hb.json'), {'ts': now - 3, 'last_return': 0})
        put(os.path.join(self.d, 'remote_mode.json'), {'active': False, 'stage': ''})

    def env(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith('CC_')}
        e.update(CC_LIMITS_BASE=self.d, CC_LIMITS_DIR=self.d, CLAUDE_CONFIG_DIR=os.path.join(self.d, 'claude'), PATH=os.environ['PATH'])
        return e

    def run_py(self, rel, *args, stdin=''):
        return subprocess.run([sys.executable, '-I', os.path.join(self.d, rel), *args], input=stdin, text=True,
                              capture_output=True, timeout=60, env=self.env(), cwd=self.d)

    def gate(self):
        return self.run_py('hooks/pause_tool_gate.py', stdin=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}))

    def pause_active(self):
        try:
            return bool(get(os.path.join(self.d, 'pause_state.json')).get('active'))
        except OSError:
            return False

    def test_tool_hook_lets_work_continue_and_asks_the_panel(self):
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('deny', r.stdout)
        self.assertFalse(self.pause_active())
        self.assertTrue(get(os.path.join(self.d, 'remote_auto_kick.json'))['ts'] > 0)
        first = get(os.path.join(self.d, 'remote_auto_kick.json'))['ts']
        self.gate()
        self.assertEqual(get(os.path.join(self.d, 'remote_auto_kick.json'))['ts'], first)   # второй вызов запрос не плодит

    def test_tool_hook_pauses_as_before_when_autotransfer_is_off(self):
        put(os.path.join(self.d, 'remote_auto.json'), dict(enabled=False, dry_run=False, ticks=2, min_stay=600, cooldown=900, sim_level='', sim_prod=''))
        r = self.gate()
        self.assertIn('deny', r.stdout)
        self.assertTrue(self.pause_active())
        self.assertFalse(os.path.exists(os.path.join(self.d, 'remote_auto_kick.json')))

    def test_tool_hook_pauses_when_panel_is_silent(self):
        os.remove(os.path.join(self.d, 'remote_auto_hb.json'))
        r = self.gate()
        self.assertIn('deny', r.stdout)
        self.assertTrue(self.pause_active())

    def test_unclaimed_request_turns_into_pause_after_ttl(self):
        self.gate()
        kick = os.path.join(self.d, 'remote_auto_kick.json')
        put(kick, {'ts': time.time() - 120})                       # панель так и не взяла запрос
        put(os.path.join(self.d, 'remote_auto_hb.json'), {'ts': time.time() - 3, 'last_return': 0})
        r = self.gate()
        self.assertIn('deny', r.stdout)
        self.assertTrue(self.pause_active())

    def test_incoming_message_goes_to_queue_without_pause(self):
        text = os.path.join(self.d, 'msg.txt')
        with open(text, 'w', encoding='utf-8') as f:
            f.write('привет')
        r = self.run_py('tg_queue.py', 'enqueue', '--chat', '1', '--msg-id', '7', '--user', 'Owner', '--ts', '', '--text-file', text)
        self.assertEqual(r.returncode, 10, r.stdout + r.stderr)
        self.assertIn('передаю работу на Claude PROD', r.stdout)
        self.assertFalse(self.pause_active())
        self.assertEqual(len(Q._pending(json.loads(l) for l in open(os.path.join(self.d, 'tg_queue.jsonl'), encoding='utf-8'))), 1)
        self.assertTrue(os.path.exists(os.path.join(self.d, 'remote_auto_kick.json')))


if __name__ == '__main__':
    unittest.main()
