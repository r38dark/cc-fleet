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


class FleetPauseAPI(unittest.TestCase):
    def test_view_reports_connected_claude_without_changing_saved_alarm(self):
        import cc_limits as limits
        import cc_remote_limits
        import pause_ctl
        local = dict(level='week', threshold=90, weekly_cap=99,
                     nearest={'acc': 'acc1', 'resets_at': iso(3*86400)},
                     pause=dict(active=True, kind='week', resume_at=NOW+3*86400))
        before = copy.deepcopy(local)
        with mock.patch.object(pause_ctl, 'level_state', return_value=local), \
             mock.patch.object(pause_ctl, '_remote_active', return_value=True), \
             mock.patch.object(limits, 'jload', return_value={'accounts': {'acc1': row(week_reset=3*86400)}}), \
             mock.patch.object(limits.cc_remote, 'cached', return_value={'prod': remote()}), \
             mock.patch.object(cc_remote_limits.time, 'time', return_value=NOW):
            result = limits.pause_state()
        self.assertEqual(result['level'], before['level'])
        self.assertEqual(result['pause'], before['pause'])
        self.assertEqual(result['nearest'], before['nearest'])
        self.assertEqual(result['claude_limits']['prod']['resume_at'], NOW + 86400)
        self.assertNotIn('claude', result['claude_limits'])


if __name__ == '__main__':
    unittest.main()
