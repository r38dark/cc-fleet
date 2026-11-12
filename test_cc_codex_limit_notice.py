"""The visual limit warning must not depend on whether the bridge pauses a single account."""
import datetime,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock
import cc_codex_rotation as R
NOW=int(time.time())
def iso(t):return datetime.datetime.fromtimestamp(t,datetime.timezone.utc).isoformat()
def account(slot='gpt1',session=20,week=20,**extra):
 row=dict(slot=slot,label=slot,ts=NOW,windows=[dict(mins=300,pct=session,resets_at=iso(NOW+3600)),dict(mins=10080,pct=week,resets_at=iso(NOW+86400))])
 row.update(extra);return row

def notice(rows,active='gpt1',pause=None):return R.limit_notice_state(rows,active,pause,now=NOW)

class LimitNotice(unittest.TestCase):
 def test_single_five_hour_warning_without_queue_pause(self):
  rows=[account(session=100)];p=R.limit_pause_state(rows,'gpt1',False,NOW);n=notice(rows,pause=p)
  self.assertFalse(p['active']);self.assertTrue(n['active']);self.assertFalse(n['paused']);self.assertTrue(n['single'])
  self.assertEqual(n['windows'],[300]);self.assertAlmostEqual(n['resume_at'],NOW+3600)
 def test_single_week_warning_without_queue_pause(self):
  rows=[account(week=100)];p=R.limit_pause_state(rows,'gpt1',False,NOW);n=notice(rows,pause=p)
  self.assertFalse(p['active']);self.assertTrue(n['active']);self.assertFalse(n['paused'])
  self.assertEqual(n['windows'],[10080]);self.assertAlmostEqual(n['resume_at'],NOW+86400)
 def test_two_full_windows_wait_for_both(self):
  n=notice([account(session=100,week=100)])
  self.assertEqual(n['windows'],[300,10080]);self.assertAlmostEqual(n['resume_at'],NOW+86400)
 def test_each_used_up_window_carries_its_reset_for_the_tile_badge(self):
  # бейдж плитки пишет «лимит недели / 5 ч исчерпан до …» о том окне, что кончается позже: нужен сброс каждого окна
  n=notice([account(session=100,week=100)])
  self.assertEqual(set(n['resets']),{'300','10080'});self.assertAlmostEqual(n['resets']['300'],NOW+3600);self.assertAlmostEqual(n['resets']['10080'],NOW+86400)
  self.assertEqual(notice([account(week=100)])['resets'].keys(),{'10080'})
  a=account(session=100,week=100);a['windows'][1]['resets_at']=None
  self.assertEqual(set(notice([a])['resets']),{'300'})          # неизвестный сброс не выдумываем
  self.assertEqual(notice([account(reached=True)])['resets'],{})
 def test_below_real_limit_is_not_exhaustion(self):
  for pct in (0,85,90,99,99.9):self.assertFalse(notice([account(session=pct,week=pct)])['active'])
 def test_notices_clear_when_fresh_usage_is_available(self):
  self.assertTrue(notice([account(session=100)])['active'])
  self.assertFalse(notice([account(session=1)])['active'])
 def test_unavailable_data_does_not_create_a_limit(self):
  for flags in ({'error':'fixture error'},{'stale':True},{'login_required':True},{'loading':True},{'lapsed':True},{'ts':NOW-181},{'ts':0}):
   self.assertFalse(notice([account(session=100,**flags)])['active'],flags)
  self.assertFalse(notice([])['active']);self.assertFalse(notice([account(slot='other',session=100)])['active'])
 def test_service_limit_without_full_window_does_not_guess_a_reset(self):
  for flags in ({'reached':True},{'usage_allowed':False}):
   n=notice([account(**flags)],pause={'active':True,'resume_at':NOW+3600})
   self.assertTrue(n['active']);self.assertEqual(n['windows'],[]);self.assertIsNone(n['resume_at'])
 def test_unknown_reset_does_not_promise_a_known_earlier_one(self):
  a=account(session=100,week=100);a['windows'][1]['resets_at']=None
  self.assertIsNone(notice([a])['resume_at'])
 def test_expired_window_is_not_an_endless_warning(self):
  a=account(session=100);a['windows'][0]['resets_at']=iso(NOW-121)
  self.assertFalse(notice([a])['active'])
  a['windows'][0]['resets_at']=iso(NOW-119);self.assertTrue(notice([a])['active'])
 def test_expired_session_does_not_hide_remaining_week_limit(self):
  a=account(session=100,week=100);a['windows'][0]['resets_at']=iso(NOW-121)
  self.assertEqual(notice([a])['windows'],[10080])
 def test_a_limit_on_another_account_does_not_block_the_current_one(self):
  self.assertFalse(notice([account(),account(slot='gpt2',session=100)])['active'])
 def test_candidate_does_not_hide_current_limit_warning(self):
  rows=[account(session=100),account(slot='gpt2')];p=R.limit_pause_state(rows,'gpt1',True,NOW)
  n=notice(rows,pause=p);self.assertTrue(n['active']);self.assertFalse(n['paused']);self.assertFalse(p['active'])
 def test_real_multi_account_pause_still_reports_queue_and_earliest_reset(self):
  a=account(session=100,week=100);b=account(slot='gpt2',session=100)
  p=R.limit_pause_state([a,b],'gpt1',False,NOW);n=notice([a,b],pause=p)
  self.assertTrue(p['active']);self.assertTrue(n['active']);self.assertTrue(n['paused'])
  self.assertEqual(n['resume_slot'],'gpt2');self.assertAlmostEqual(n['resume_at'],NOW+3600)
 def test_invalid_percentages_are_unknown(self):
  for pct in (None,'unknown',float('nan'),float('inf')):
   self.assertFalse(notice([account(session=pct)])['active'])
 def test_public_api_exposes_notice_without_mutating_rotation_or_console(self):
  rot=R.Rotation.__new__(R.Rotation);rot.lock=threading.RLock();rot.active=lambda:'gpt1'
  rot.accounts=[account(session=100)];rot.state=dict(optimize=True,threshold=90,weekly_cap=99)
  rot.console=SimpleNamespace(_pid=lambda:False,_meta=lambda:{},stop=Mock(),apply_plan=Mock())
  rot.codex=SimpleNamespace(profile_slots=lambda:['gpt1']);rot.message='fixture';rot.last_error='';rot.updated=NOW;rot.save=Mock()
  result=rot.public();self.assertFalse(result['limit_pause']['active']);self.assertTrue(result['limit_notice']['active'])
  self.assertFalse(result['limit_notice']['paused']);rot.save.assert_not_called();rot.console.stop.assert_not_called();rot.console.apply_plan.assert_not_called()
  rot.codex.profile_slots=lambda:[];self.assertFalse(rot.limit_notice(now=NOW)['active'])
 def test_existing_queue_hold_remains_visible_when_usage_sample_ages(self):
  rot=R.Rotation.__new__(R.Rotation);rot.lock=threading.RLock();rot.active=lambda:'gpt1'
  rot.codex=SimpleNamespace(profile_slots=lambda:['gpt1'])
  rot.accounts=[account(session=100,ts=NOW-200)]
  rot.limit_pause=lambda _now:dict(active=True,slot='gpt1',windows=[300],resume_at=NOW+3600)
  n=rot.limit_notice(now=NOW);self.assertTrue(n['active']);self.assertTrue(n['paused'])

if __name__=='__main__':unittest.main()
