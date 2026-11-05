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
   result=self.p.action('codex','apply',dict(id='reserve',confirm=True,revision=0))
   self.assertFalse(result['ok']);self.assertTrue(self.p.public()['recovery']['blocked'])
   for _ in range(5):self.p.tick()
   self.assertEqual(rollback.call_count,1)
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

if __name__=='__main__':unittest.main()
