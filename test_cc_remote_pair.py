import base64
import json
import os
import tempfile
import types
import unittest
from pathlib import Path

import cc_remote
import cc_remote_mode as M
from cc_claude_profile import ProfileError
from cc_profile_state import ProfileState
from cc_profiles import NativeProfiles


class FakeState:
    def __init__(self):
        self.revision = 7
        self.leader = None
        self.manual_choices = {'claude': 'full', 'codex': None}


class FakeProfiles:
    def __init__(self):
        self.state = FakeState()
        self.paused_for = set()
        self.scenarios = []
        self.scenario_result = {'ok': True}
        self.native = types.SimpleNamespace(busy=lambda: False)

    def paused(self, e):
        return e in self.paused_for

    def exchange(self, e):
        return Path('/tmp/ex') / e

    def apply_scenario(self, body):
        self.scenarios.append(body)
        if self.scenario_result.get('ok'):
            self.state.manual_choices = dict(body['choices'])
            ch = body['choices']
            self.state.leader = 'claude' if ch.get('claude') == 'orchestrator' else 'codex' if ch.get('codex') == 'orchestrator' else None
            self.paused_for = {e for e in ('claude', 'codex') if not ch.get(e)}
        return self.scenario_result


class FakeWorkers:
    def __init__(self):
        self.profiles = FakeProfiles()
        self.running = True

    def claude_running(self):
        return self.running

    def screen_busy(self):
        return self.running


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cc_remote.MEMBERS_FILE = os.path.join(self.tmp, 'm.json')
        cc_remote.STATE_FILE = os.path.join(self.tmp, 's.json')
        M.MODE_FILE = os.path.join(self.tmp, 'mode.json')
        with open(cc_remote.MEMBERS_FILE, 'w') as f:
            json.dump({'prod': {'label': 'Аккаунт PROD', 'host': '192.0.2.1', 'tmux': 'friend', 'back_host': '192.0.2.2'}}, f)
        self.wk = FakeWorkers()
        M._NS.clear()
        M._NS.update(WORKERS=self.wk, tg_notify=lambda t: None)
        M._wcache.update(ts=0.0, val='dev', key=None)
        M._pbusy.update(ts=0.0, val=False)
        self.calls = []
        self.prod_bad = ''
        self.prod_busy = False
        self.local_busy = False
        self.off_ok = {'ok': True}
        self.on_ok = {'ok': True}

        def fake_off(reason, force, restore=True):
            self.calls.append(('off', restore))
            if self.off_ok.get('ok'):
                M._save(active=False, member=None)
            return self.off_ok

        def fake_on(mid, reason, queued, resume, tg_on=True, restore=True):
            self.calls.append(('on', tg_on, restore))
            if self.on_ok.get('ok'):
                M._save(active=True, member=mid, tg=tg_on)
            return self.on_ok

        self._orig = (M._off_job, M._on_job, M._prod_not_ready, M.ctl, M._local_busy)
        M._off_job, M._on_job = fake_off, fake_on
        M._prod_not_ready = lambda mid, force=False: self.prod_bad
        M.ctl = lambda m, args, timeout=150: {'ok': True, 'busy': self.prod_busy}
        M._local_busy = lambda: self.local_busy

    def tearDown(self):
        M._off_job, M._on_job, M._prod_not_ready, M.ctl, M._local_busy = self._orig

    def run_pair(self, kind, **kw):
        res = M.pair(kind, **kw)
        t = M._job['t']
        if res.get('started') and t:
            t.join(10)
        M._wcache['ts'] = 0.0
        return res

    def choices(self):
        return [s['choices'] for s in self.wk.profiles.scenarios]

    def set_pair(self, claude, codex, tg=True):
        self.wk.profiles.state.manual_choices = {'claude': claude, 'codex': codex}
        M._save(active=True, member='prod', tg=tg)


class PairState(Base):
    def test_pair_kind_requires_active(self):
        self.wk.profiles.state.manual_choices = {'claude': 'orchestrator', 'codex': 'executor'}
        self.assertEqual(M.pair_kind(), '')
        M._save(active=True, member='prod')
        self.assertEqual(M.pair_kind(), 'prod_codex')

    def test_pair_kind_variants(self):
        self.set_pair('executor', 'orchestrator', tg=False)
        self.assertEqual(M.pair_kind(), 'codex_prod')
        self.set_pair('full', None)
        self.assertEqual(M.pair_kind(), '')
        self.set_pair('orchestrator', None)
        self.assertEqual(M.pair_kind(), '')
        self.wk.profiles.state.manual_choices = None
        self.assertEqual(M.pair_kind(), '')

    def test_public_has_pair_and_tg(self):
        self.assertIsNone(M.public()['pair'])
        self.assertTrue(M.public()['tg'])
        self.set_pair('orchestrator', 'executor')
        d = M.public()
        self.assertEqual(d['pair']['kind'], 'prod_codex')
        self.assertEqual(d['pair']['name'], 'Claude PROD → Codex')
        self.assertTrue(d['pair']['lock'])

    def test_worker_prod_pair_and_codex_leader(self):
        self.set_pair('orchestrator', 'executor')
        self.assertEqual(M.worker(), 'prod')
        self.set_pair('executor', 'orchestrator', tg=False)
        self.wk.profiles.state.leader = 'codex'
        M._wcache['ts'] = 0.0
        self.assertEqual(M.worker(), 'codex')

    def test_scenario_guard(self):
        self.assertEqual(M.scenario_guard({'claude': 'executor', 'codex': 'orchestrator'}), '')
        M._save(active=True, member='prod', tg=True)
        for ch in ({'claude': 'full', 'codex': None}, {'claude': 'orchestrator', 'codex': 'executor'}):
            self.assertEqual(M.scenario_guard(ch), '')
        for ch in ({'claude': 'executor', 'codex': 'orchestrator'}, {'claude': 'full', 'codex': 'full'}, {'claude': None, 'codex': 'full'}, None):
            self.assertTrue(M.scenario_guard(ch))
        M._save(tg=False)
        self.assertEqual(M.scenario_guard({'claude': 'executor', 'codex': 'orchestrator'}), '')
        for ch in ({'claude': 'full', 'codex': None}, {'claude': 'orchestrator', 'codex': 'executor'}):
            self.assertTrue(M.scenario_guard(ch))

    def test_action_guard(self):
        self.assertEqual(M.action_guard('apply'), '')
        M._save(active=True, member='prod')
        self.assertTrue(M.action_guard('apply'))
        self.assertTrue(M.action_guard('stop'))
        self.assertEqual(M.action_guard('config'), '')

    def test_pair_locks_handoff_on_off(self):
        self.set_pair('orchestrator', 'executor')
        for res in (M.handoff('dev'), M.on('prod'), M.off()):
            self.assertFalse(res['ok'])
            self.assertIn('пара', res['message'])
        self.assertEqual(self.calls, [])

    def test_no_pair_keeps_handoff_free(self):
        M._save(active=True, member='prod', tg=True)
        res = self.run_pair('off')
        self.assertTrue(res['ok'])
        self.assertNotIn('started', res)


class PairFlows(Base):
    def test_unknown_kind(self):
        self.assertFalse(M.pair('mars')['ok'])

    def test_already_on(self):
        self.set_pair('orchestrator', 'executor')
        res = M.pair('prod_codex')
        self.assertTrue(res['ok'])
        self.assertNotIn('started', res)

    def test_prod_codex_from_dev(self):
        res = self.run_pair('prod_codex')
        self.assertTrue(res['started'])
        self.assertEqual(self.calls, [('on', True, True)])
        self.assertEqual(self.choices(), [{'claude': 'orchestrator', 'codex': 'executor'}])
        self.assertEqual(M.pair_kind(), 'prod_codex')
        self.assertEqual(M.mode().get('error'), '')
        self.assertEqual(M.mode().get('to'), '')

    def test_prod_codex_from_dev_scenario_fails_keeps_prod(self):
        self.wk.profiles.scenario_result = {'ok': False, 'message': 'отказ'}
        self.run_pair('prod_codex')
        self.assertTrue(M.active())
        self.assertIn('Работа осталась у Claude PROD', M.mode()['error'])

    def test_prod_codex_prod_fails_to_start(self):
        self.on_ok = {'ok': False, 'message': 'нет'}
        self.run_pair('prod_codex')
        self.assertEqual(self.choices(), [])
        self.assertFalse(M.active())

    def test_prod_codex_from_codex_prod_restarts_with_tg(self):
        self.set_pair('executor', 'orchestrator', tg=False)
        self.run_pair('prod_codex')
        self.assertEqual(self.calls, [('off', False), ('on', True, False)])
        self.assertEqual(self.choices(), [{'claude': 'orchestrator', 'codex': 'executor'}])
        self.assertTrue(M.tg())

    def test_prod_codex_from_prod_solo_changes_only_scenario(self):
        M._save(active=True, member='prod', tg=True)
        self.run_pair('prod_codex')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.choices(), [{'claude': 'orchestrator', 'codex': 'executor'}])

    def test_codex_prod_from_dev(self):
        self.run_pair('codex_prod')
        self.assertEqual(self.calls, [('on', False, True)])
        self.assertEqual(self.choices(), [{'claude': 'executor', 'codex': 'orchestrator'}])
        self.assertEqual(M.pair_kind(), 'codex_prod')
        self.assertFalse(M.tg())

    def test_codex_prod_from_prod_solo_stops_and_restarts_without_tg(self):
        M._save(active=True, member='prod', tg=True)
        self.run_pair('codex_prod')
        self.assertEqual(self.calls, [('off', False), ('on', False, False)])
        self.assertEqual(M.pair_kind(), 'codex_prod')

    def test_codex_prod_scenario_fails_stops_prod(self):
        self.wk.profiles.scenario_result = {'ok': False, 'message': 'отказ'}
        self.run_pair('codex_prod')
        self.assertEqual(self.calls, [('on', False, True), ('off', True)])
        self.assertFalse(M.active())
        self.assertIn('Claude на PROD остановлен', M.mode()['error'])

    def test_off_from_prod_codex_keeps_prod_alone(self):
        self.set_pair('orchestrator', 'executor')
        self.run_pair('off')
        self.assertEqual(self.choices(), [{'claude': 'full', 'codex': None}])
        self.assertEqual(self.calls, [])
        self.assertTrue(M.active())
        self.assertEqual(M.pair_kind(), '')

    def test_off_from_codex_prod_releases_prod_without_waking_dev(self):
        self.set_pair('executor', 'orchestrator', tg=False)
        self.run_pair('off')
        self.assertEqual(self.choices(), [{'claude': None, 'codex': 'full'}])
        self.assertEqual(self.calls, [('off', False)])
        self.assertFalse(M.active())

    def test_busy_prod_refused_unless_forced(self):
        self.set_pair('orchestrator', 'executor')
        self.prod_busy = True
        res = M.pair('off')
        self.assertTrue(res.get('answering'))
        self.assertEqual(self.choices(), [])
        self.assertTrue(self.run_pair('off', force=True)['started'])

    def test_not_active_checks_prod_and_local_busy(self):
        self.prod_bad = 'PROD не готов: нет связи.'
        self.assertFalse(M.pair('prod_codex')['ok'])
        self.prod_bad = ''
        self.local_busy = True
        res = M.pair('codex_prod')
        self.assertFalse(res['ok'])
        self.assertTrue(res['busy'])
        self.assertEqual(self.calls, [])


class PairRoute(Base):
    def body(self, claude, codex, rev=7):
        return {'choices': {'claude': claude, 'codex': codex}, 'revision': rev}

    def route(self, *a, **kw):
        res = M.scenario_route(self.body(*a, **kw))
        t = M._job['t']
        if res and res.get('started') and t:
            t.join(10)
        M._wcache['ts'] = 0.0
        return res

    def test_not_active_goes_usual_way(self):
        self.assertIsNone(M.scenario_route(self.body('executor', 'orchestrator')))
        self.assertEqual(self.calls, [])

    def test_codex_orchestrator_from_prod_solo_becomes_codex_prod(self):
        M._save(active=True, member='prod', tg=True)
        res = self.route('executor', 'orchestrator')
        self.assertTrue(res['started'])
        self.assertEqual(self.calls, [('off', False), ('on', False, False)])
        self.assertEqual(M.pair_kind(), 'codex_prod')
        self.assertFalse(M.tg())

    def test_codex_orchestrator_from_prod_codex_becomes_codex_prod(self):
        self.set_pair('orchestrator', 'executor')
        self.route('executor', 'orchestrator')
        self.assertEqual(M.pair_kind(), 'codex_prod')

    def test_stale_or_missing_revision_is_conflict(self):
        M._save(active=True, member='prod', tg=True)
        for rev in (6, None, '7'):
            res = self.route('executor', 'orchestrator', rev=rev)
            self.assertFalse(res['ok'])
            self.assertTrue(res['conflict'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.choices(), [])

    def test_codex_prod_to_prod_codex(self):
        self.set_pair('executor', 'orchestrator', tg=False)
        self.route('orchestrator', 'executor')
        self.assertEqual(self.calls, [('off', False), ('on', True, False)])
        self.assertEqual(M.pair_kind(), 'prod_codex')

    def test_codex_prod_codex_full_releases_prod(self):
        self.set_pair('executor', 'orchestrator', tg=False)
        self.route(None, 'full')
        self.assertEqual(self.choices(), [{'claude': None, 'codex': 'full'}])
        self.assertFalse(M.active())

    def test_already_codex_prod_is_noop(self):
        self.set_pair('executor', 'orchestrator', tg=False)
        res = self.route('executor', 'orchestrator')
        self.assertTrue(res['ok'])
        self.assertNotIn('started', res)
        self.assertEqual(self.calls, [])

    def test_busy_prod_is_not_interrupted(self):
        M._save(active=True, member='prod', tg=True)
        self.prod_busy = True
        res = self.route('executor', 'orchestrator')
        self.assertFalse(res['ok'])
        self.assertTrue(res['answering'])
        self.assertEqual(self.calls, [])

    def test_other_scenarios_are_left_to_guard(self):
        M._save(active=True, member='prod', tg=True)
        for c, x in (('full', None), ('orchestrator', 'executor'), (None, 'full'), ('full', 'full')):
            self.assertIsNone(M.scenario_route(self.body(c, x)))
        self.set_pair('executor', 'orchestrator', tg=False)
        for c, x in (('full', None), ('orchestrator', None)):
            self.assertIsNone(M.scenario_route(self.body(c, x)))
        for bad in (None, 'x', {}, {'choices': None}, {'choices': {'claude': 'executor'}}):
            self.assertIsNone(M.scenario_route(bad))
        self.assertEqual(self.calls, [])


class ProdIo(Base):
    def setUp(self):
        super().setUp()
        self.log = []
        self.ctl_results = {}
        self.orig_rctl = cc_remote.ctl
        self.orig_sleep = M.time.sleep
        M.time.sleep = lambda s: None
        cc_remote.ctl = self.fake_ctl
        self.sendin = [{'ok': True}]
        self.tail = []

    def tearDown(self):
        cc_remote.ctl = self.orig_rctl
        M.time.sleep = self.orig_sleep
        super().tearDown()

    def fake_ctl(self, mid, *args, inp=None, timeout=25):
        self.log.append(args[0])
        if args[0] == 'sendin':
            self.last_text = inp
            return self.sendin.pop(0) if len(self.sendin) > 1 else self.sendin[0]
        if args[0] == 'hist':
            return {'ok': True, 'path': '/root/.claude/projects/-root/x.jsonl', 'size': 10}
        if args[0] == 'histtail':
            if not self.tail:
                return {'ok': True, 'size': 10, 'b64': ''}
            return self.tail.pop(0)
        if args[0] == 'status':
            return {'ok': True, 'running': True, 'busy': self.prod_busy}
        return None

    @staticmethod
    def tail_of(*events):
        raw = ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events).encode()
        return {'ok': True, 'size': 10 + len(raw), 'b64': base64.b64encode(raw).decode()}

    def test_send_once_codes(self):
        self.assertEqual(M.prod_send_once('привет'), (True, ''))
        self.assertEqual(self.last_text, 'привет')
        self.sendin = [{'ok': False, 'error': 'busy'}]
        self.assertEqual(M.prod_send_once('x'), (False, 'busy'))
        self.sendin = [{'ok': False, 'error': 'not_running'}]
        self.assertEqual(M.prod_send_once('x'), (False, 'not_running'))

    def test_send_once_strips_control_chars_and_limits_size(self):
        M.prod_send_once('a\x00b\x1b[31mc\r\nd')
        self.assertNotIn('\x00', self.last_text)
        self.assertNotIn('\x1b', self.last_text)
        M.prod_send_once('я' * 40000)
        self.assertLessEqual(len(self.last_text.encode()), 47100)

    def test_send_retries_while_busy(self):
        self.sendin = [{'ok': False, 'error': 'busy'}, {'ok': False, 'error': 'busy'}, {'ok': True}]
        self.assertEqual(M.prod_send('x', wait=60), (True, ''))
        self.assertEqual(self.log.count('sendin'), 3)

    def test_send_gives_up_without_wait(self):
        self.sendin = [{'ok': False, 'error': 'busy'}]
        self.assertEqual(M.prod_send('x'), (False, 'busy'))
        self.assertEqual(self.log.count('sendin'), 1)

    def test_ask_returns_final_answer(self):
        self.tail = [self.tail_of(
            {'type': 'user', 'message': {'content': 'вопрос'}},
            {'type': 'assistant', 'message': {'stop_reason': 'tool_use', 'content': [{'type': 'text', 'text': 'промежуточно'}]}},
            {'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'готово'}]}})]
        self.assertEqual(M.prod_ask('сделай'), 'готово')
        self.assertEqual(self.log[:2], ['hist', 'sendin'])

    def test_ask_waits_for_more_bytes(self):
        self.tail = [{'ok': True, 'size': 10, 'b64': ''},
                     self.tail_of({'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'ответ'}]}})]
        self.assertEqual(M.prod_ask('сделай'), 'ответ')

    def test_ask_input_rejected(self):
        self.sendin = [{'ok': False, 'error': 'not_running'}]
        with self.assertRaises(RuntimeError) as cm:
            M.prod_ask('сделай')
        self.assertEqual(str(cm.exception), 'claude_input_rejected')

    def test_ask_incomplete_answer(self):
        self.tail = [self.tail_of({'type': 'assistant', 'message': {'stop_reason': 'max_tokens', 'content': []}})]
        with self.assertRaises(RuntimeError) as cm:
            M.prod_ask('сделай')
        self.assertEqual(str(cm.exception), 'claude_incomplete_answer')

    def test_ask_cancelled(self):
        cancel = types.SimpleNamespace(is_set=lambda: True)
        with self.assertRaises(RuntimeError) as cm:
            M.prod_ask('сделай', cancel)
        self.assertEqual(str(cm.exception), 'step_cancelled_at_expiry')

    def test_prod_busy_cached_and_prod_ready(self):
        self.prod_busy = True
        self.assertTrue(M.prod_busy())
        self.prod_busy = False
        self.assertTrue(M.prod_busy())
        M._pbusy['ts'] = 0.0
        self.assertFalse(M.prod_busy())
        self.assertTrue(M.prod_ready())

    def test_orch_script_is_python_with_destination(self):
        src = M._orch_script('/opt/x/outbox/task.md', {'back_host': '203.0.113.7', 'back_key': '/root/.ssh/k'})
        compile(src, 'orch_step.py', 'exec')
        self.assertIn('/opt/x/outbox/task.md', src)
        self.assertIn('203.0.113.7', src)
        self.assertIn('/root/.ssh/k', src)
        self.assertEqual(M.back_ssh({}), ('', M.BACK_KEY))   # без записи пары адреса нет: шаг ведущему не ставится

    def test_announce_role(self):
        put = []
        orig = M.put_file
        M.put_file = lambda m, data, remote, bits='644': put.append((remote, bits)) or True
        try:
            self.assertTrue(M.announce_role('executor'))
            self.assertEqual(put, [])
            self.assertIn('Codex', self.last_text)
            self.assertTrue(M.announce_role('leader'))
            self.assertEqual(put, [(M.ORCH_PATH, '755')])
            self.assertIn(M.ORCH_PATH, self.last_text)
            self.assertFalse(M.announce_role('paused'))
        finally:
            M.put_file = orig


class FakeRemote:
    ROLE_TEXT = M.ROLE_TEXT

    def __init__(self):
        self._tg = True
        self.ready = True
        self.busy = False
        self.announced = []
        self.announce_ok = True

    def active(self):
        return True

    def tg(self):
        return self._tg

    def prod_ready(self):
        return self.ready

    def prod_busy(self):
        return self.busy

    def announce_role(self, role):
        self.announced.append(role)
        return self.announce_ok


class NativeRemoteSlot(unittest.TestCase):
    """Слот Claude на PROD в ядре профилей: локальную консоль не трогаем, роль уходит на PROD."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rm = FakeRemote()
        self.local_calls = []
        claude = types.SimpleNamespace(capture=lambda: self.local_calls.append('capture') or {'thread_id': 't'},
                                       apply=lambda *a: self.local_calls.append('apply'),
                                       prepare=lambda *a: self.local_calls.append('prepare'))
        n = NativeProfiles.__new__(NativeProfiles)
        n.ns = {'REMOTE_MODE': self.rm, 'cc_codex': types.SimpleNamespace(own=lambda p: None)}
        n.base = self.tmp
        n.claude = claude
        n.claude_work = str(self.tmp / 'work')
        n.bridge = types.SimpleNamespace(_state=lambda: {})
        n.manager = types.SimpleNamespace(exchange=lambda e: self.tmp / 'ex' / e)
        n.busy = lambda: False
        self.n = n

    @staticmethod
    def state(claude, codex):
        s = ProfileState()
        assert s.apply_scenario({'claude': claude, 'codex': codex}, 'подтверждаю', s.revision)['ok']
        return s

    def test_capture_does_not_touch_local_console(self):
        self.assertEqual(self.n.capture(['claude']), {'claude_remote': {'tg': True}})
        self.assertEqual(self.local_calls, [])
        self.rm._tg = False
        self.assertEqual(self.n.capture(['claude']), {'claude_remote': {'tg': False}})

    def test_capture_local_when_not_remote(self):
        self.n.ns['REMOTE_MODE'] = types.SimpleNamespace(active=lambda: False)
        self.assertIn('claude', self.n.capture(['claude']))
        self.assertEqual(self.local_calls, ['capture'])

    def test_preflight_needs_ready_prod(self):
        before, after = self.state('full', None), self.state('orchestrator', 'executor')
        cap = {'claude_remote': {'tg': True}}
        self.n.preflight(before, after, ['claude'], cap)
        self.assertEqual(self.local_calls, [])
        self.rm.ready = False
        with self.assertRaises(ProfileError) as cm:
            self.n.preflight(before, after, ['claude'], cap)
        self.assertEqual(str(cm.exception), 'claude_prod_not_ready')

    def test_preflight_paused_role_does_not_need_prod(self):
        before, after = self.state('executor', 'orchestrator'), self.state(None, 'full')
        self.rm.ready = False
        self.n.preflight(before, after, ['claude'], {'claude_remote': {'tg': False}})

    def test_apply_announces_role(self):
        before, after = self.state('full', None), self.state('orchestrator', 'executor')
        self.n.apply(before, after, ['claude'], {'claude_remote': {'tg': True}})
        self.assertEqual(self.rm.announced, ['leader'])
        self.assertEqual(self.local_calls, [])
        self.n.apply(after, self.state('executor', 'orchestrator'), ['claude'], {'claude_remote': {'tg': False}})
        self.assertEqual(self.rm.announced, ['leader', 'executor'])

    def test_apply_paused_role_is_silent(self):
        self.n.apply(self.state('executor', 'orchestrator'), self.state(None, 'full'), ['claude'], {'claude_remote': {'tg': False}})
        self.assertEqual(self.rm.announced, [])

    def test_apply_failure_raises(self):
        self.rm.announce_ok = False
        with self.assertRaises(ProfileError) as cm:
            self.n.apply(self.state('full', None), self.state('orchestrator', 'executor'), ['claude'], {'claude_remote': {}})
        self.assertEqual(str(cm.exception), 'claude_prod_role_failed')

    def test_rollback_restores_old_role_best_effort(self):
        before = self.state('full', None)
        self.n.rollback(before, ['claude'], {'claude_remote': {'tg': True}})
        self.assertEqual(self.rm.announced, ['solo'])
        self.rm.announce_ok = False
        self.n.rollback(before, ['claude'], {'claude_remote': {'tg': True}})

    def test_recovery_matches_follows_prod(self):
        before = self.state('full', None)
        self.assertTrue(self.n.recovery_matches(before, ['claude'], {'claude_remote': {}}))
        self.rm.ready = False
        self.assertFalse(self.n.recovery_matches(before, ['claude'], {'claude_remote': {}}))

    def test_busy_includes_prod(self):
        n = NativeProfiles.__new__(NativeProfiles)
        n.ns = {'REMOTE_MODE': self.rm, 'session_busy': lambda: False}
        n.bridge = types.SimpleNamespace(BRIDGE=types.SimpleNamespace(busy=lambda: False))
        n.codex = types.SimpleNamespace(busy=lambda: False)
        n.manager = types.SimpleNamespace(input_allowed=lambda e: True)
        self.assertFalse(NativeProfiles.busy(n))
        self.rm.busy = True
        self.assertTrue(NativeProfiles.busy(n))


if __name__ == '__main__':
    unittest.main()
