import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from cc_profiles import Profiles, NativeProfiles
from cc_profile_state import ProfileState
from cc_profile_gate import decide
from cc_claude_profile import ClaudeProfile, ProfileError, atomic
from cc_profile_tasks import ProfileTasks, completed_claude_answer

class FakeNative:
    def __init__(self):
        self.manager=None;self.claude_cwd='/test/work';self.busy_value=False;self.fail=False;self.applied=[];self.rollbacks=[];self.statuses=dict(claude='up',codex='up');self.model=dict(claude='claude-test',codex='gpt-test');self.tid=dict(claude='claude-thread',codex='codex-thread');self.bridge=SimpleNamespace(delete_profile=lambda pid:(True,''))
    plan=NativeProfiles.plan
    def seed(self):return ProfileState()
    def busy(self):return self.busy_value
    def capture(self,changed):return dict(model=copy.deepcopy(self.model),tid=copy.deepcopy(self.tid))
    def preflight(self,*args):pass
    def apply(self,before,after,changed,captured):
        self.applied.append((before.export(),after.export(),changed));
        if self.fail:self.model['codex']='bad';raise ProfileError('simulated_apply_failed')
    def rollback(self,before,changed,captured):self.rollbacks.append(changed);self.model=captured['model'];self.tid=captured['tid']
    def availability(self):return self.statuses

def legacy_pair_state(leader,state=None):
    raw=(state or ProfileState()).export();other='codex' if leader=='claude' else 'claude'
    raw.update(leader=leader,manual_choices={leader:'orchestrator',other:'executor'},selected={leader:'orchestrator',other:'executor'},service=None,restore=None,revision=raw['revision']+1)
    return ProfileState.from_data(raw)

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.now=1000;self.native=FakeNative();self.p=Profiles(self.tmp.name,self.native,lambda:self.now)
    def action(self,e,pid,word=''):
        if pid=='orchestrator':return self.p.transition(legacy_pair_state(e,self.p.state),'Исторический сценарий')
        return self.p.action(e,'apply',dict(id=pid,confirm=word,revision=self.p.state.revision))
    def test_install_and_reads_do_not_change_console_or_model(self):
        for _ in range(3):self.p.public()
        self.assertFalse(self.native.applied);self.assertFalse(self.p.managed['codex']);self.assertEqual(self.native.model['codex'],'gpt-test')
    def test_explicit_selection_adopts_current_permissions_without_install_time_relaunch(self):
        self.assertFalse(self.p.public()['engines']['claude']['applied']);self.assertFalse(self.native.applied)
        self.assertTrue(self.action('claude','claude_solo_full','подтверждаю')['ok']);self.assertTrue(self.native.applied);self.assertTrue(self.p.public()['engines']['claude']['applied'])

    def test_both_leader_directions_persist_and_have_one_executor(self):
        for e in ['claude','codex']:
            self.assertTrue(self.action(e,'orchestrator')['ok']);other='codex' if e=='claude' else 'claude';d=self.p.public();self.assertEqual(d['leader'],e);self.assertEqual(d['engines'][other]['role'],'executor')
            other_native=FakeNative();reload=Profiles(self.tmp.name,other_native,lambda:self.now);self.assertEqual(reload.public()['leader'],e)
        self.assertEqual(self.native.model,dict(claude='claude-test',codex='gpt-test'));self.assertEqual(self.native.tid['codex'],'codex-thread')
    def test_full_confirmation_and_busy_fail_before_side_effects(self):
        self.action('codex','orchestrator');n=len(self.native.applied);r=self.action('codex','codex_solo_full');self.assertTrue(r['confirmation_required']);self.assertEqual(n,len(self.native.applied));self.native.busy_value=True;r=self.action('codex','codex_solo_full','подтверждаю');self.assertTrue(r['busy']);self.assertEqual(n,len(self.native.applied));self.assertEqual(self.p.state.selected['codex'],'orchestrator')
    def test_failure_rolls_back_runtime_and_persistent_profile(self):
        before=self.p.state.export();self.native.fail=True;r=self.action('claude','orchestrator');self.assertFalse(r['ok']);self.assertEqual(self.p.state.export(),before);self.assertEqual(self.native.model['codex'],'gpt-test');self.assertTrue(self.native.rollbacks);self.assertFalse(self.p.pending.exists());self.assertEqual(json.loads(self.p.path.read_text())['core'],before)
    def test_interrupted_transaction_recovers_before_allowing_input(self):
        before=self.p.state.export();atomic(self.p.pending,dict(before=before,after=before,managed=self.p.managed,changed=['codex'],captured=self.native.capture(['codex'])));self.assertFalse(self.p.input_allowed('codex'));self.p.recover();self.assertTrue(self.p.input_allowed('codex'));self.assertTrue(self.native.rollbacks)
    def test_stale_request_has_no_console_effect(self):
        rev=self.p.state.revision;self.action('claude','orchestrator');n=len(self.native.applied);r=self.p.action('codex','apply',dict(id='orchestrator',revision=rev));self.assertTrue(r['conflict']);self.assertEqual(n,len(self.native.applied))
    def test_removed_profiles_have_no_runtime_side_effects(self):
        for e in ['claude','codex']:
            for pid in [e,'emergency','custom-old']:
                n=len(self.native.applied);self.assertFalse(self.action(e,pid,'аварийный')['ok']);self.assertEqual(len(self.native.applied),n)


class GateTests(unittest.TestCase):
    def setUp(self):self.policy=dict(cwd='/safe/work',access='write',write_roots=['/safe/work'],read_roots=['/safe/work','/project'])
    def event(self,name,path):return dict(hook_event_name='PreToolUse',tool_name=name,tool_input=dict(file_path=path),cwd='/safe/work')
    def test_root_paths_bash_agents_and_mcp_blocked_in_workspace(self):
        for name,path in [('Write','/project/a'),('Edit','/safe/work/../other'),('Bash','/safe/work'),('Agent','/safe/work'),('mcp__notion__notion_spawn_session','/safe/work')]:self.assertTrue(decide(self.policy,self.event(name,path)))
        self.assertFalse(decide(self.policy,self.event('Write','/safe/work/a')));self.assertFalse(decide(self.policy,self.event('Read','/project/a')))
    def test_symlink_escape_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'work';root.mkdir();(root/'link').symlink_to('/etc');self.policy.update(cwd=str(root),write_roots=[str(root)]);self.assertTrue(decide(self.policy,self.event('Write',str(root/'link/passwd'))))
    def test_pause_and_expiry_block_tools_even_in_bypass(self):
        self.policy.update(access='full',paused=True);self.assertTrue(decide(self.policy,dict(hook_event_name='UserPromptSubmit')));self.policy.update(paused=False,expires=1);self.assertFalse(decide(self.policy,self.event('Bash','/root')))
    def test_full_still_excludes_other_agents_but_reserve_allows_its_agent(self):
        self.policy.update(access='full');self.assertFalse(decide(self.policy,self.event('Bash','/root')));self.assertTrue(decide(self.policy,self.event('Agent','/root')));self.policy['reserve']=True;self.assertFalse(decide(self.policy,self.event('mcp__notion__notion_spawn_session','/root')))

class CommandTests(unittest.TestCase):
    def test_resumes_exact_thread_model_and_effort_without_fork_or_old_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=ClaudeProfile(dict(BASE=tmp,cfg=lambda:dict(claude_cmd='IS_SANDBOX=1 /usr/bin/claude --resume --dangerously-skip-permissions --channels plugin:telegram')))
            snapshot=dict(thread_id='11111111-1111-1111-1111-111111111111',model='claude-exact',effort='xhigh');args=adapter.command(snapshot,dict(access='write'),'role text')
            self.assertEqual(args[args.index('--resume')+1],snapshot['thread_id']);self.assertEqual(args[args.index('--model')+1],'claude-exact');self.assertEqual(args[args.index('--effort')+1],'xhigh');self.assertEqual(args[args.index('--permission-mode')+1],'dontAsk');self.assertNotIn('--fork-session',args);self.assertNotIn('--dangerously-skip-permissions',args);self.assertIn('--channels',args);self.assertIn('--system-prompt-snapshot',args)

class ClaudeResultTests(unittest.TestCase):
    def test_terminal_reasons_from_native_history_and_intermediate_tools(self):
        for reason in ('end_turn','stop_sequence'):
            event=dict(type='assistant',message=dict(stop_reason=reason,content=[dict(type='text',text='verified')]))
            self.assertEqual(completed_claude_answer(event),'verified')
        self.assertIsNone(completed_claude_answer(dict(type='assistant',message=dict(stop_reason='tool_use',content=[dict(type='text',text='working')]))))
        self.assertIsNone(completed_claude_answer(dict(type='assistant',message=dict(stop_reason='max_tokens',content=[dict(type='text',text='partial')]))))

class TaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.native=FakeNative();self.p=Profiles(self.tmp.name,self.native);self.p.transition(legacy_pair_state('claude',self.p.state),'Исторический сценарий');self.sent=[];self.asked=[]
        self.tasks=ProfileTasks(self.p,lambda e,t:self.sent.append((e,t)),lambda e,t:self.asked.append((e,t)) or 'checked result');self.p.tasks=self.tasks;self.draft=self.p.exchange('claude')/'outbox/task.md';self.draft.parent.mkdir(parents=True);self.draft.write_text('права: дев\nOriginal safe step');self.tasks.tick()
    def test_no_dispatch_before_human_confirmation_and_immutable_task(self):
        self.assertFalse(self.asked);task=self.tasks.public();self.draft.write_text('права: полные\nREPLACED TEXT');r=self.tasks.confirm(dict(id=task['id'],approve=True));self.assertTrue(r['ok']);self.tasks.tick();self.tasks.worker.join(2);self.assertEqual(self.asked[0][0],'codex');self.assertIn('Original safe step',self.asked[0][1]);self.assertNotIn('REPLACED TEXT',self.asked[0][1]);self.assertEqual(self.sent[0][0],'claude');self.assertEqual(self.tasks.public()['status'],'done')
    def test_stale_profile_cannot_approve_task(self):
        self.p.transition(legacy_pair_state('codex',self.p.state),'Исторический сценарий');r=self.tasks.confirm(dict(id=self.tasks.public()['id'],approve=True));self.assertFalse(r['ok']);self.assertFalse(self.asked)
    def test_running_step_blocks_profile_changes_and_restart_never_resends(self):
        self.tasks.state['status']='approved';self.tasks.save();r=self.p.transition(legacy_pair_state('codex',self.p.state),'Исторический сценарий');self.assertTrue(r['busy']);self.tasks.state['status']='running';self.tasks.save();restored=ProfileTasks(self.p,lambda *a:None,lambda *a:self.fail('must never resend'));self.assertEqual(restored.public()['status'],'uncertain');restored.tick();self.assertIsNone(restored.worker)

if __name__=='__main__':unittest.main()
