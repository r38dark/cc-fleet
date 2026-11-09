"""Общая сводка лимитов не подменяет локальный гейт и учитывает подключённые серверы."""
import copy
import datetime
import unittest
from unittest import mock

import cc_avail

NOW = 2000000000


def iso(seconds):
    return datetime.datetime.fromtimestamp(NOW + seconds, datetime.timezone.utc).isoformat()


def row(session=0, week=100, session_reset=3600, week_reset=86400):
    return dict(plan='pro', five_hour=dict(pct=session, resets_at=iso(session_reset)),
                seven_day=dict(pct=week, resets_at=iso(week_reset)))


def remote(**kwargs):
    return dict(row(**kwargs), online=True, ts=NOW, label='Other server')


class FleetSummary(unittest.TestCase):
    def summarize(self, local=None, other=None):
        return cc_avail.fleet_summary({'acc1': row(week_reset=3*86400)} if local is None else local,
                                     {'prod': remote()} if other is None else other, 90, 99, NOW)

    def test_nearest_remote_reset_wins_over_local_three_days(self):
        result = self.summarize()
        self.assertTrue(result['all_blocked'])
        self.assertTrue(result['all_week_capped'])
        self.assertEqual(result['remote_count'], 1)
        self.assertEqual(result['nearest']['acc'], 'remote:prod')
        self.assertEqual(result['nearest']['resets_at'], iso(86400))

    def test_waits_for_all_blocking_windows_of_each_account(self):
        result = self.summarize(other={'prod': remote(session=95, session_reset=2*86400)})
        self.assertEqual(result['nearest']['resets_at'], iso(2*86400))

    def test_usable_remote_prevents_global_exhaustion(self):
        result = self.summarize(other={'prod': remote(week=20)})
        self.assertFalse(result['all_blocked'])
        self.assertEqual(result['nearest']['resets_at'], iso(0))

    def test_usable_local_prevents_global_exhaustion(self):
        self.assertFalse(self.summarize(local={'acc1': row(week=10)})['all_blocked'])

    def test_stale_offline_or_error_remote_is_unknown(self):
        for extra in ({'ts': NOW-901}, {'online': False}, {'error': 'unavailable'}):
            result = self.summarize(other={'prod': dict(remote(), **extra)})
            self.assertFalse(result['all_blocked'])
            self.assertEqual(result['unknown'], ['remote:prod'])

    def test_missing_or_invalid_remote_timestamp_is_unknown(self):
        for ts in (None, 'bad'):
            self.assertFalse(self.summarize(other={'prod': dict(remote(), ts=ts)})['all_blocked'])

    def test_missing_usage_is_unknown_not_free_capacity(self):
        result = self.summarize(other={'prod': dict(remote(), five_hour={})})
        self.assertFalse(result['all_blocked'])
        self.assertIsNone(result['accounts']['remote:prod']['usable'])

    def test_free_account_cannot_beat_known_reset(self):
        result = self.summarize(other={'prod': dict(remote(), plan='free')})
        self.assertTrue(result['all_blocked'])
        self.assertFalse(result['all_week_capped'])
        self.assertEqual(result['nearest']['acc'], 'local:acc1')

    def test_no_remote_keeps_scope_local(self):
        self.assertEqual(self.summarize(other={})['remote_count'], 0)

    def test_inputs_are_not_mutated_and_no_identity_is_exposed(self):
        local, other = {'acc1': row()}, {'prod': dict(remote(), email='private@example.invalid')}
        before = copy.deepcopy((local, other))
        result = self.summarize(local, other)
        self.assertEqual((local, other), before)
        self.assertNotIn('email', str(result))


class FleetBanner(unittest.TestCase):
    def setUp(self):
        from test_cc_remote_banner import render, HARD
        self.render = render
        self.data = copy.deepcopy(HARD)
        self.data.update(level='week', fleet=cc_avail.fleet_summary(
            {'acc1': row(week_reset=3*86400)}, {'prod': remote()}, 90, 99, NOW))

    def test_same_banner_and_nearest_time_with_local_or_remote_active(self):
        results = self.render([dict(self.data, remote=False), dict(self.data, remote=True)])
        self.assertFalse(results[0]['hidden'])
        self.assertFalse(results[1]['hidden'])
        self.assertEqual(results[0]['html'], results[1]['html'])
        self.assertIn('ccpFleetWeekTitle', results[0]['html'])
        self.assertIn(str((NOW+86400)*1000), results[0]['html'])
        self.assertIn('Other server', results[0]['html'])
        self.assertNotIn('onclick=', results[0]['html'])

    def test_global_summary_does_not_advertise_local_wake_time(self):
        self.data['pause'] = dict(active=True, kind='week', resume_at=NOW+3*86400)
        result = self.render([self.data])[0]
        self.assertIn(str((NOW+86400)*1000), result['html'])
        self.assertNotIn(str((NOW+3*86400)*1000), result['html'])

    def test_account_label_is_escaped(self):
        self.data['fleet']['accounts']['remote:prod']['label'] = '<img src=x onerror=alert(1)>'
        result = self.render([self.data])[0]
        self.assertNotIn('<img', result['html'])
        self.assertIn('&lt;img', result['html'])


class FleetPauseAPI(unittest.TestCase):
    def test_view_adds_fleet_without_changing_local_level_or_alarm(self):
        import cc_limits as limits
        import pause_ctl
        local = dict(level='week', threshold=90, weekly_cap=99,
                     nearest={'acc': 'acc1', 'resets_at': iso(3*86400)},
                     pause=dict(active=True, kind='week', resume_at=NOW+3*86400))
        before = copy.deepcopy(local)
        with mock.patch.object(pause_ctl, 'level_state', return_value=local), \
             mock.patch.object(pause_ctl, '_remote_active', return_value=True), \
             mock.patch.object(limits, 'jload', return_value={'accounts': {'acc1': row(week_reset=3*86400)}}), \
             mock.patch.object(limits.cc_remote, 'cached', return_value={'prod': remote()}), \
             mock.patch.object(cc_avail.time, 'time', return_value=NOW):
            result = limits.pause_state()
        self.assertEqual(result['level'], before['level'])
        self.assertEqual(result['pause'], before['pause'])
        self.assertEqual(result['nearest'], before['nearest'])
        self.assertEqual(result['fleet']['nearest']['resets_at'], iso(86400))


if __name__ == '__main__':
    unittest.main()
