import json
import os
import tempfile
import unittest
from types import SimpleNamespace

import cc_remote
import cc_remote_mode as M


class FakeState:
    def __init__(self):
        self.revision = 7
        self.leader = None


class FakeProfiles:
    def __init__(self):
        self.state = FakeState()
        self.paused_for = set()
        self.scenarios = []
        self.scenario_result = {'ok': True}
        self.resumed = []

    def paused(self, e):
        return e in self.paused_for

    def resume_for_handoff(self, engine):
        self.resumed.append(engine)
        if self.scenario_result.get("ok"):self.paused_for.discard(engine)
        return self.scenario_result

    def apply_scenario(self, body):
        self.scenarios.append(body)
        return self.scenario_result


class FakeWorkers:
    def __init__(self):
        self.profiles = FakeProfiles()
        self.running = True
        self.started = 0
        self.codex_running = True
        self.codex_started = 0
        self.deliveries = []
        self.delivery_ok = True
        self.ns = {'cc_codex_console': SimpleNamespace(status=lambda: {'running': self.codex_running}, start=self.start_codex)}

    def start_codex(self):
        self.codex_started += 1
        self.codex_running = True
        return True, ''

    def handoff_sync(self, target, **options):
        self.deliveries.append((target, options))
        return self.delivery_ok

    def handoff_refresh_owner_last(self):
        pass

    def claude_running(self):
        return self.running

    def screen_busy(self):
        return self.running

    def start_claude(self):
        self.started += 1
        self.running = True
        return True


class Handoff(unittest.TestCase):
    """Общая передача «любое место → любое»: цепочки шагов и состояние. Профили, ssh и PROD подменены."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cc_remote.MEMBERS_FILE = os.path.join(self.tmp, 'm.json')
        cc_remote.STATE_FILE = os.path.join(self.tmp, 's.json')
        M.MODE_FILE = os.path.join(self.tmp, 'mode.json')
        with open(cc_remote.MEMBERS_FILE, 'w') as f:
            json.dump({'prod': {'label': 'Аккаунт PROD', 'host': '192.0.2.1', 'tmux': 'friend'}}, f)
        self.wk = FakeWorkers()
        M._NS.clear()
        M._NS.update(WORKERS=self.wk, tg_notify=lambda t: None)
        M._wcache.update(ts=0.0, val='dev', key=None)
        self.calls = []
        self.prod_bad = ''
        self.prod_busy = False
        self.off_ok = {'ok': True}
        self.on_ok = {'ok': True}

        def fake_off(reason, force, restore=True, **options):
            self.calls.append(('off', restore))
            if self.off_ok.get('ok'):
                M._save(active=False, member=None)
            return self.off_ok

        def fake_on(mid, reason, queued, resume, **options):
            self.calls.append(('prod_on', mid))
            if self.on_ok.get('ok'):
                M._save(active=True, member=mid)
            return self.on_ok

        self._orig = (M._off_job, M._on_job, M._prod_not_ready, M.ctl, M.brief, cc_remote.ssh_run, M.rsync, cc_remote.ctl)
        M._off_job, M._on_job = fake_off, fake_on
        M._prod_not_ready = lambda mid, force=False: self.prod_bad
        M.ctl = lambda m, args, timeout=150: {'ok': True, 'busy': self.prod_busy}
        M.brief = lambda *a, **kw: 'fixture context'
        cc_remote.ssh_run = lambda *a, **kw: (0, '')
        self.remote_receipt = {'ok': True}
        cc_remote.ctl = lambda *a, **kw: self.remote_receipt
        self.copies = []
        M.rsync = lambda *a, **kw: self.copies.append((a,kw)) or True

    def tearDown(self):
        M._off_job, M._on_job, M._prod_not_ready, M.ctl, M.brief, cc_remote.ssh_run, M.rsync, cc_remote.ctl = self._orig

    def run_handoff(self, target, **kw):
        res = M.handoff(target, **kw)
        t = M._job['t']
        if res.get('started') and t:
            t.join(10)
        M._wcache['ts'] = 0.0
        return res

    def choices(self):
        return [s['choices'] for s in self.wk.profiles.scenarios]

    def test_worker_detection(self):
        self.assertEqual(M.worker(), 'dev')
        M._wcache['ts'] = 0.0
        self.wk.profiles.paused_for = {'claude'}
        self.assertEqual(M.worker(), 'codex')
        M._save(active=True, member='prod')
        self.assertEqual(M.worker(), 'codex')  # хост Claude не присваивает себе отдельное задание Codex
        self.wk.profiles.paused_for = set()
        M._wcache['ts'] = 0.0
        self.assertEqual(M.worker(), 'prod')
        M._save(active=False)
        M._wcache['ts'] = 0.0
        self.wk.profiles.paused_for = set()
        self.wk.profiles.state.leader = 'codex'
        self.assertEqual(M.worker(), 'codex')

    def test_public_has_worker_and_to(self):
        d = M.public()
        self.assertEqual(d['worker'], 'dev')
        self.assertEqual(d['to'], '')

    def test_same_target_does_nothing(self):
        res = self.run_handoff('dev')
        self.assertTrue(res['ok'])
        self.assertNotIn('started', res)
        self.assertEqual(self.calls, [])

    def test_unknown_target(self):
        self.assertFalse(M.handoff('mars')['ok'])

    def test_dev_to_codex_keeps_sender_and_delivers_context(self):
        res = self.run_handoff('codex')
        self.assertTrue(res['started'])
        self.assertEqual(self.choices(), [])
        self.assertEqual(self.wk.profiles.resumed, ['codex'])
        self.assertEqual(self.wk.deliveries, [('codex', {'force': True})])
        self.assertEqual(M.worker(), 'codex')
        self.assertEqual(M.public()['error'], '')
        self.assertEqual(M.public()['to'], '')
        self.assertFalse(M.busy())

    def test_prod_to_dev_restores_claude(self):
        M._save(active=True, member='prod')
        self.run_handoff('dev')
        self.assertEqual(self.calls, [('off', True)])
        self.assertEqual(self.choices(), [])

    def test_prod_to_codex_does_not_wake_native_claude(self):
        M._save(active=True, member='prod')
        self.wk.running = False
        self.run_handoff('codex')
        self.assertEqual(self.calls, [])
        self.assertTrue(M.active())
        self.assertEqual(self.choices(), [])
        self.assertEqual(M.worker(), 'codex')
        self.assertEqual(self.wk.started, 0)

    def test_codex_to_prod_keeps_codex_and_does_not_start_dev(self):
        self.wk.profiles.paused_for = {'claude'}
        self.run_handoff('prod')
        self.assertEqual(self.choices(), [])
        self.assertEqual(self.wk.profiles.resumed, ['claude'])
        self.assertEqual(self.calls, [('prod_on', 'prod')])

    def test_codex_to_dev_preserves_codex_profile(self):
        self.wk.profiles.paused_for = {'claude'}
        self.run_handoff('dev')
        self.assertEqual(self.choices(), [])
        self.assertEqual(self.wk.profiles.resumed, ['claude'])
        self.assertEqual(self.calls, [])

    def test_prod_not_ready_allows_expired_token_but_not_missing_login(self):
        import time
        M._prod_not_ready = self._orig[2]
        future = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(time.time() + 3600))
        past = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(time.time() - 3600))
        rows = {}
        original = cc_remote.fetch_limits
        self.addCleanup(setattr, cc_remote, 'fetch_limits', original)   # оригинал сохраняем ДО подмены
        cc_remote.fetch_limits = lambda mid, force=False: rows
        rows.update(online=True, error='token_expired', five_hour={'pct': 40.0, 'resets_at': future}, seven_day={'pct': 10.0, 'resets_at': future})
        self.assertEqual(M._prod_not_ready('prod'), '')                       # токен обновится при запуске Claude
        rows.update(error='no_login')
        self.assertIn('не готов', M._prod_not_ready('prod'))
        rows.update(error='token_expired', five_hour={'pct': 100.0, 'resets_at': future})
        self.assertIn('исчерпан', M._prod_not_ready('prod'))                  # цифры старые, но окно ещё не сбросилось
        rows.update(five_hour={'pct': 100.0, 'resets_at': past})
        self.assertEqual(M._prod_not_ready('prod'), '')                       # окно с тех пор сбросилось
        rows.update(online=False, error='ssh')
        self.assertIn('не готов', M._prod_not_ready('prod'))

    def test_prod_not_ready_blocks_before_any_step(self):
        self.prod_bad = 'PROD не готов: нет связи.'
        res = self.run_handoff('prod')
        self.assertFalse(res['ok'])
        self.assertEqual(res['message'], self.prod_bad)
        self.assertEqual(self.choices(), [])
        self.assertEqual(self.calls, [])

    def test_prod_answering_does_not_block_non_stopping_handoff_to_codex(self):
        M._save(active=True, member='prod')
        self.prod_busy = True
        res = self.run_handoff('codex')
        self.assertTrue(res['started'])
        self.assertEqual(self.calls, [])
        self.assertTrue(M.active())
        self.assertEqual(M.worker(), 'codex')

    def test_scenario_failure_is_reported_and_state_cleared(self):
        self.wk.profiles.scenario_result = {'ok': False, 'message': 'Дождись завершения работы.'}
        res = self.run_handoff('codex')
        self.assertTrue(res['started'])
        d = M.public()
        self.assertEqual(d['error'], 'Дождись завершения работы.')
        self.assertEqual(d['to'], '')
        self.assertEqual(d['stage'], '')
        self.assertFalse(M.busy())

    def test_receiver_failure_keeps_prod_and_does_not_start_dev(self):
        M._save(active=True, member='prod')
        self.wk.running = False
        self.wk.profiles.scenario_result = {'ok': False, 'message': 'Codex не готов.'}
        self.run_handoff('codex')
        self.assertEqual(self.wk.started, 0)
        self.assertTrue(M.active())
        self.assertEqual(self.calls, [])
        self.assertEqual(M.public()['error'], 'Codex не готов.')

    def test_second_handoff_refused_while_busy(self):
        import threading
        gate = threading.Event()
        self.wk.profiles.resume_for_handoff = lambda engine: (gate.wait(5), {'ok': True})[1]
        first = M.handoff('codex')
        self.assertTrue(first['started'])
        second = M.handoff('dev')
        self.assertTrue(second.get('busy'))
        gate.set()
        M._job['t'].join(10)


    def test_codex_receiver_starts_without_touching_sender(self):
        self.wk.codex_running = False
        self.run_handoff('codex')
        self.assertEqual(self.wk.codex_started, 1)
        self.assertEqual(self.wk.started, 0)
        self.assertTrue(self.wk.running)
        self.assertEqual(self.calls, [])

    def test_no_start_option_does_not_activate_or_launch_receiver(self):
        self.wk.codex_running = False
        self.run_handoff('codex', allow_start=False)
        self.assertEqual(self.wk.codex_started, 0)
        self.assertEqual(self.wk.profiles.resumed, [])
        self.assertTrue(self.wk.running)
        self.assertIn('Сначала запусти', M.public()['error'])

    def test_context_delivery_failure_does_not_stop_prod(self):
        M._save(active=True, member='prod')
        self.wk.delivery_ok = False
        self.run_handoff('codex')
        self.assertTrue(M.active())
        self.assertEqual(self.calls, [])
        self.assertEqual(M.worker(), 'prod')
        self.assertIn('не принял контекст', M.public()['error'])

    def test_focused_task_survives_availability_revision(self):
        M._save(active=True, member='prod')
        self.run_handoff('codex')
        self.wk.profiles.state.revision += 1
        self.assertEqual(M.worker(), 'codex')
        self.assertEqual(M.public()['task_target'], 'codex')


    def test_remote_refusal_is_not_treated_as_delivered(self):
        self.wk.profiles.paused_for = {'claude'}
        self.remote_receipt = {'ok': False, 'error': 'not_running'}
        self.run_handoff('prod')
        self.assertIn('не принял контекст', M.public()['error'])
        self.assertEqual(M.worker(), 'codex')
        self.assertNotIn('codex', self.wk.profiles.paused_for)

    def test_context_copy_failure_keeps_prod_running(self):
        M._save(active=True, member='prod')
        M.rsync = lambda *a, **kw: False
        self.run_handoff('codex')
        self.assertTrue(M.active())
        self.assertEqual(self.calls, [])
        self.assertIn('не скопирован', M.public()['error'])

    def test_pair_workflow_cannot_be_bypassed_by_independent_handoff(self):
        self.wk.profiles.state.public = lambda: {'engines': {'claude': {'role': 'leader'}, 'codex': {'role': 'executor'}}}
        result = self.run_handoff('codex')
        self.assertFalse(result['ok'])
        self.assertEqual(self.wk.profiles.resumed, [])
        self.assertTrue(M.public()['handoff_lock'])

    def test_on_off_routes_still_work(self):
        res = M.off()
        self.assertTrue(res['ok'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
