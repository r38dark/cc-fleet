import json,tempfile,unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import pyte
import cc_codex_console as console
from cc_profiles import Profiles,NativeProfiles
from cc_claude_profile import atomic,ProfileError
from cc_session import launch_args
from test_cc_profiles import FakeNative

class Recovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.n=FakeNative();self.p=Profiles(self.tmp.name,self.n)
 def pending(self):
  before=self.p.state.export();atomic(self.p.pending,dict(before=before,after=before,managed=self.p.managed,changed=['codex'],captured=self.n.capture(['codex'])))
 def test_failed_recovery_is_attempted_once_across_ticks_and_restarts(self):
  self.pending()
  with patch.object(self.n,'rollback',side_effect=ProfileError('locked')) as rollback:
   for _ in range(5):self.p.tick()
   self.assertEqual(rollback.call_count,1);self.assertTrue(self.p.public()['recovery']['blocked']);self.assertFalse(self.p.input_allowed('codex'))
  other=FakeNative();loaded=Profiles(self.tmp.name,other)
  with patch.object(other,'rollback') as rollback:
   for _ in range(3):loaded.tick()
   rollback.assert_not_called()
 def test_failed_transaction_does_not_enter_auto_relaunch_loop(self):
  self.n.fail=True
  with patch.object(self.n,'rollback',side_effect=ProfileError('locked')) as rollback:
   result=self.p.action('codex','apply',dict(id='codex_solo_full',confirm='подтверждаю',revision=0))  # был служебный резерв
   self.assertFalse(result['ok']);self.assertTrue(self.p.public()['recovery']['blocked'])
   raw=json.loads(self.p.pending.read_text());self.assertEqual(raw['rollback_failure']['code'],'locked');self.assertIn('failure',raw)
   for _ in range(5):self.p.tick()
   self.assertEqual(rollback.call_count,1)
 def test_verified_restore_unblocks_queue_without_another_restart(self):
  self.pending()
  with patch.object(self.n,'rollback',side_effect=ProfileError('unit_still_stopping')) as rollback:
   self.p.tick();self.assertTrue(self.p.pending.exists());self.assertEqual(rollback.call_count,1)
   self.n.recovery_matches=lambda *args:True
   self.p.tick();self.assertFalse(self.p.pending.exists());self.assertEqual(rollback.call_count,1)
   self.assertTrue(self.p.input_allowed('codex'));self.assertEqual(self.p.error,'')
   self.assertEqual(len(list((Path(self.tmp.name)/'profile_runtime').glob('recovered-*.json'))),1)
 def test_busy_turn_does_not_clear_recovery_barrier(self):
  self.pending();raw=json.loads(self.p.pending.read_text());raw['recovery_blocked']=True;atomic(self.p.pending,raw)
  self.n.busy_value=True;self.n.recovery_matches=lambda *args:True
  self.p.tick();self.assertTrue(self.p.pending.exists());self.assertFalse(self.n.rollbacks)
 def test_runtime_mismatch_keeps_queue_blocked_without_restarting(self):
  self.pending();raw=json.loads(self.p.pending.read_text());raw['recovery_blocked']=True;atomic(self.p.pending,raw)
  self.n.recovery_matches=lambda *args:False
  self.p.tick();self.assertTrue(self.p.pending.exists());self.assertFalse(self.p.input_allowed('codex'));self.assertFalse(self.n.rollbacks)
 def test_native_restore_check_rejects_changed_thread_rights_or_tools(self):
  settings=dict(access='full',profile='codex_solo_full');runtime=dict(thread_id='exact',model='gpt-6.1-sol',effort='xhigh',cwd='/tmp/test')
  meta=dict(sandbox='danger-full-access',mcp=[])
  n=SimpleNamespace(bridge=SimpleNamespace(load=lambda:settings),codex=SimpleNamespace(_pid=lambda:'123',_meta=lambda:meta,active_settings=lambda:runtime,MCP=lambda:[],verify_ready=lambda **kw:(True,'')))
  captured=dict(codex_settings=settings.copy(),codex_runtime=runtime.copy(),codex_sandbox='danger-full-access')
  self.assertTrue(NativeProfiles.recovery_matches(n,self.p.state,['codex'],captured))
  for target,key,value in ((runtime,'thread_id','another'),(meta,'sandbox','workspace-write'),(meta,'mcp',['changed']),(meta,'pending_settings',{'thread_id':'exact'})):
   old=target.get(key);target[key]=value
   self.assertFalse(NativeProfiles.recovery_matches(n,self.p.state,['codex'],captured))
   if old is None:target.pop(key)
   else:target[key]=old
  n.codex.verify_ready=lambda **kw:(False,'locked')
  self.assertFalse(NativeProfiles.recovery_matches(n,self.p.state,['codex'],captured))
 def test_stale_recovery_error_is_cleared_after_external_repair(self):
  self.p.error='Автоматические повторы восстановления остановлены. stale'
  self.p.tick();self.assertEqual(self.p.error,'')
 def test_explicit_profile_selection_can_retry_blocked_recovery(self):
  self.pending()
  with patch.object(self.n,'rollback',side_effect=ProfileError('locked')):self.p.tick()
  result=self.p.apply_scenario(dict(choices=dict(claude=None,codex='full'),confirm='подтверждаю',revision=0))
  self.assertTrue(result['ok']);self.assertFalse(self.p.pending.exists());self.assertTrue(self.p.input_allowed('codex'))
 def test_busy_turn_never_triggers_recovery(self):
  self.pending();self.n.busy_value=True
  for _ in range(3):self.p.tick()
  self.assertFalse(self.n.rollbacks);self.assertNotIn('recovery_attempts',json.loads(self.p.pending.read_text()))
 def test_crash_after_persisted_attempt_does_not_repeat_it(self):
  self.pending();raw=json.loads(self.p.pending.read_text());raw['recovery_attempts']=1;atomic(self.p.pending,raw)
  self.p.tick();self.assertFalse(self.n.rollbacks);self.assertTrue(self.p.public()['recovery']['blocked'])
 def test_absent_claude_does_not_block_codex_when_claude_should_be_paused(self):
  with patch.object(self.n,'capture',return_value=dict(claude_absent=True,codex_settings=dict(access='full'),codex_sandbox='danger-full-access',codex_runtime=dict(thread_id='exact'))):
   candidate=type(self.p.state).from_data(self.p.state.export());candidate.apply('codex','reserve',True,candidate.revision)
   n=SimpleNamespace(busy=lambda:False,bridge=SimpleNamespace(_state=lambda:{}),manager=SimpleNamespace(exchange=lambda e:Path(self.tmp.name)/e),ns={'cc_codex':SimpleNamespace(own=lambda p:None)},reserve_ready=lambda:True,claude_work=self.tmp.name,claude_policy=lambda s:dict(paused=True))
   NativeProfiles.preflight(n,self.p.state,candidate,['claude','codex'],self.n.capture([]))
   n.claude_policy=lambda s:dict(paused=False)
   with self.assertRaisesRegex(ProfileError,'claude_history_unknown'):NativeProfiles.preflight(n,self.p.state,candidate,['claude','codex'],self.n.capture([]))

 def test_tui_owns_its_runtime_and_exact_conversation(self):
  args=launch_args('codex',dict(thread_id='exact',cwd='/tmp/test',model='gpt-6.1-sol',effort='xhigh'),'danger-full-access','never')
  self.assertIn('--no-daemon',args);self.assertEqual(args[1:3],['resume','exact']);self.assertNotIn('fork',args)
 def test_visible_terminal_frame_ignores_erased_historical_lock(self):
  path=Path(self.tmp.name)/'console.log';path.write_bytes(b'This conversation is open in another app\r\n\x1b[2J\x1b[H'+ 'Codex\r\n› Ready · ? for shortcuts'.encode())
  with patch.object(console,'pyte',pyte),patch.object(console,'_log',return_value=str(path)),patch.object(console,'_pid',return_value='fake'),patch.object(console,'_dims',return_value=(100,32)),patch.object(console,'_wait_ready'):
   self.assertTrue(console.verify_ready()[0])
   path.write_text('This conversation is open in another app\n›')
   ok,message=console.verify_ready();self.assertFalse(ok);self.assertIn('занята другим подключением',message)

class UnitRetirement(unittest.TestCase):
 def test_waits_until_systemd_releases_old_unit(self):
  from subprocess import CompletedProcess
  results=[CompletedProcess([],0,''),CompletedProcess([],0,'loaded\n'),CompletedProcess([],0,'not-found\n')]
  with patch.object(console.subprocess,'run',side_effect=results) as run,patch.object(console.time,'sleep') as sleep:
   self.assertTrue(console._retire_unit());self.assertEqual(run.call_count,3);sleep.assert_called_once()
   self.assertEqual(run.call_args_list[0].args[0],['/usr/bin/systemctl','stop',console.UNIT])
 def test_failed_systemd_query_does_not_claim_unit_is_gone(self):
  from subprocess import CompletedProcess
  with patch.object(console.subprocess,'run',side_effect=[CompletedProcess([],0,''),CompletedProcess([],1,'')]):
   self.assertFalse(console._retire_unit())

if __name__=='__main__':unittest.main()
