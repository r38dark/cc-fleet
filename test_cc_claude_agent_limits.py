"""Независимые верхние состояния Claude используют установленные пороги гейта."""
import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

import cc_remote_limits as limits

NOW = 1800000000


def row(week, session=0, reset=7200, session_reset=3600):
    iso = lambda seconds: datetime.datetime.fromtimestamp(NOW + seconds, datetime.timezone.utc).isoformat()
    return dict(online=True, ts=NOW, five_hour=dict(pct=session, resets_at=iso(session_reset)),
                seven_day=dict(pct=week, resets_at=iso(reset)))


class States(unittest.TestCase):
    def states(self, local=None, remote=None, **policy):
        view = dict(threshold=90, weekly_cap=99, weekly_pause=True, pause={}, stale=False)
        view.update(policy)
        return limits.agent_limits(view, dict(accounts=local or {}), remote or {}, now=NOW)

    def test_two_claudes_keep_their_own_week_and_reset(self):
        result = self.states({'a': row(100)}, {'r': row(99, reset=5 * 86400)})
        self.assertEqual(set(result), {'claude', 'prod'})
        self.assertEqual(result['claude']['pct'], 100)
        self.assertEqual(result['prod']['pct'], 99)
        self.assertEqual(result['claude']['resume_at'], NOW + 7200)
        self.assertEqual(result['prod']['resume_at'], NOW + 5 * 86400)
        self.assertTrue(all(s['waiting'] for s in result.values()))
        self.assertFalse(result['claude']['can_override'])
        self.assertTrue(result['prod']['can_override'])

    def test_policy_threshold_is_not_hardcoded(self):
        self.assertEqual(self.states(remote={'r': row(95)}, weekly_cap=95)['prod']['threshold'], 95)
        self.assertEqual(self.states(remote={'r': row(98)}), {})

    def test_override_and_disabled_weekly_pause_do_not_claim_a_pause(self):
        self.assertFalse(self.states(remote={'r': row(99)}, pause={'override': True})['prod']['waiting'])
        self.assertFalse(self.states(remote={'r': row(99)}, weekly_pause=False)['prod']['waiting'])
        self.assertTrue(self.states(remote={'r': row(100)}, weekly_pause=False)['prod']['waiting'])
        self.assertFalse(self.states({'a': row(99)}, level='manual')['claude']['waiting'])
        self.assertTrue(self.states(remote={'r':row(100)},pause={'override':True})['prod']['waiting'])

    def test_other_usable_local_account_does_not_report_an_engine_wait(self):
        result = self.states({'a': row(100), 'b': row(20)}, {'r': row(99)})
        self.assertNotIn('claude', result)
        self.assertIn('prod', result)

    def test_stale_local_does_not_hide_current_prod(self):
        result = self.states({'a': row(100)}, {'r': row(99)}, stale=True)
        self.assertEqual(set(result), {'prod'})

    def test_unknown_remote_and_reset_data_are_not_invented(self):
        self.assertEqual(self.states(remote={'r': dict(row(99), online=False)}), {})
        unknown = row(99);unknown['seven_day']['resets_at'] = None
        self.assertEqual(self.states(remote={'r': unknown})['prod']['resume_at'], 0)
        self.assertEqual(self.states(remote={'r': row(0)}), {})

    def test_later_of_both_blocking_windows_and_no_private_fields(self):
        data = row(99, session=100, session_reset=9000)
        data.update(email='private@example.test', token='fixture-private-value')
        result = self.states(remote={'r': data})
        self.assertEqual(result['prod']['resume_at'], NOW + 9000)
        self.assertEqual(result['prod']['windows'],[
            {'window':'5h','resume_at':NOW+9000}, {'window':'week','resume_at':NOW+7200}])
        self.assertNotIn('private', json.dumps(result))

    def test_timers_come_from_the_same_nearest_account_not_different_accounts(self):
        result=self.states({'a':row(100,session=100,reset=12000,session_reset=300),
                            'b':row(100,session=100,reset=4000,session_reset=3000)})
        self.assertEqual(result['claude']['windows'],[
            {'window':'5h','resume_at':NOW+3000}, {'window':'week','resume_at':NOW+4000}])

    def test_confirmed_pause_remains_visible_without_fresh_percentages(self):
        remote_pause=dict(enabled=True,applied=True,blocked=True,resume_at=NOW+9000)
        result=limits.agent_limits(dict(stale=True,pause=dict(active=True,resume_at=NOW+7200)),{}, {},remote_pause,now=NOW)
        self.assertEqual(set(result),{'claude','prod'})
        self.assertEqual(result['prod']['window'],'pause')
        self.assertIsNone(result['prod']['pct'])
        remote_pause['applied']=False
        self.assertEqual(limits.agent_limits({}, {}, {},remote_pause,now=NOW),{})

    def test_disabled_weekly_pause_does_not_claim_entire_pool_is_stopped(self):
        result=self.states({'a':row(99),'b':row(100)},weekly_pause=False)
        self.assertFalse(result['claude']['waiting'])

    def test_fresh_reset_removes_old_weekly_banner_while_prod_is_still_capped(self):
        result=self.states({'a':row(0)}, {'r':row(99)}, pause=dict(active=True,resume_at=NOW-10))
        self.assertNotIn('claude',result)
        self.assertIn('prod',result)


@unittest.skipUnless(shutil.which('node'), 'node unavailable')
class Render(unittest.TestCase):
    def test_both_claude_controls_restore_pause_after_override_and_do_not_bypass_100(self):
        source=(Path(__file__).parent/'cc_limits.py').read_text()
        function=re.search(r'^function ccpAgents\(d\)\{.*?^\}',source,re.S|re.M).group()
        program="""
const nodes=Object.fromEntries(['ccPauseDev','ccPauseProd'].map(id=>[id,{hidden:true,innerHTML:''}]));
const document={getElementById:id=>nodes[id]},window={FLEET_TZ:'Asia/Irkutsk'},LANG='ru';
const tr=(k,...a)=>[k,...a].join('|'),ccpEsc=String,ccpLeft=()=> 'left';
"""+function+"""
const s={window:'week',pct:99,threshold:99,waiting:true,can_override:true};
ccpAgents({claude_limits:{claude:{...s},prod:{...s}}});const off=JSON.parse(JSON.stringify(nodes));
ccpAgents({claude_limits:{claude:{...s,override:true,waiting:false},prod:{...s,override:true,waiting:false}}});const on=JSON.parse(JSON.stringify(nodes));
ccpAgents({claude_limits:{prod:{...s,pct:100,can_override:false}}});
console.log(JSON.stringify({off,on,hard:nodes.ccPauseProd}));
"""
        result=json.loads(subprocess.run(['node','-e',program],check=True,capture_output=True,text=True,timeout=10).stdout)
        for item in result['off'].values():self.assertIn('ccpBtnOff',item['innerHTML'])
        for item in result['on'].values():self.assertIn('ccpBtnOn',item['innerHTML'])
        self.assertNotIn('ccpBtnOff',result['hard']['innerHTML'])

    def test_both_banners_render_and_disappear_independently(self):
        source = (Path(__file__).parent / 'cc_limits.py').read_text()
        function = re.search(r'^function ccpAgents\(d\)\{.*?^\}', source, re.S | re.M).group()
        program = """
const nodes=Object.fromEntries(['ccPauseDev','ccPauseProd'].map(id=>[id,{hidden:true,innerHTML:''}]));
const document={getElementById:id=>nodes[id]},window={FLEET_TZ:'Asia/Irkutsk'},LANG='ru';
const tr=(k,...args)=>[k,...args].join('|'),ccpEsc=s=>String(s),ccpLeft=()=> 'left';
""" + function + """
const d={remote:true,claude_limits:{claude:{window:'week',pct:100,threshold:99,resume_at:1800007200,waiting:true},prod:{window:'week',pct:99,threshold:99,resume_at:1800432000,waiting:true}}};
const count=ccpAgents(d),before=JSON.parse(JSON.stringify(nodes));
delete d.claude_limits.claude;ccpAgents(d);
console.log(JSON.stringify({count,before,after:nodes}));
"""
        process = subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True, timeout=10)
        result = json.loads(process.stdout)
        self.assertEqual(result['count'], 2)
        self.assertIn('Claude DEV|100', result['before']['ccPauseDev']['innerHTML'])
        self.assertIn('Claude PROD|99', result['before']['ccPauseProd']['innerHTML'])
        self.assertTrue(result['after']['ccPauseDev']['hidden'])
        self.assertFalse(result['after']['ccPauseProd']['hidden'])


if __name__ == '__main__':
    unittest.main()
