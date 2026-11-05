"""Full reserve rights, bounded delegation, restoration and failure cases."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cc_notion as notion
import cc_codex_bridge as bridge
from cc_profile_state import ProfileState
from cc_profiles import NativeProfiles,Profiles
from cc_profile_gate import decide
from test_cc_profiles import FakeNative,legacy_pair_state

class FullReserveTests(unittest.TestCase):
    def full(self,engine):
        s=ProfileState()
        self.assertTrue(s.apply_scenario({e:'full' if e==engine else None for e in ('claude','codex')},'подтверждаю',s.revision)['ok'])
        return s

    def reserve(self,s,e,automatic):
        if automatic:
            self.assertTrue(s.configure(e,True,confirm='подтверждаю')['ok'])
            s.availability[s.other(e)]=False;s.reconcile_availability()
        else:self.assertTrue(s.apply(e,'reserve','подтверждаю',s.revision)['ok'])

    def test_both_full_modes_keep_commands_and_restore_without_deadline(self):
        for engine in ('claude','codex'):
            for automatic in (False,True):
                with self.subTest(engine=engine,automatic=automatic):
                    s=self.full(engine);choices=copy.deepcopy(s.manual_choices)
                    self.reserve(s,engine,automatic)
                    plan=NativeProfiles.plan(None,s,engine)
                    self.assertEqual((plan['access'],plan['mode'],plan['role']),('full','self','reserve'))
                    self.assertEqual(s.public()['engines'][s.other(engine)]['role'],'paused')
                    self.assertEqual(s.until,0)
                    s=ProfileState.from_data(s.export());self.assertEqual(s.service['access'],'full')
                    if automatic:s.availability[s.other(engine)]=True;s.reconcile_availability()
                    else:s.stop_service(engine)
                    self.assertEqual(s.manual_choices,choices);self.assertIsNone(s.service)
                    self.assertEqual(NativeProfiles.plan(None,s,engine)['access'],'full')

    def test_paired_paused_and_old_reserve_never_gain_full(self):
        for engine in ('claude','codex'):
            for leader in ('claude','codex'):
                for automatic in (False,True):
                    s=legacy_pair_state(leader);before=copy.deepcopy(s.manual_choices)
                    self.reserve(s,engine,automatic)
                    self.assertEqual(NativeProfiles.plan(None,s,engine)['access'],'write')
                    s.stop_service(engine);self.assertEqual(s.manual_choices,before)
            s=self.full('codex' if engine=='claude' else 'claude')
            self.reserve(s,engine,False);self.assertEqual(s.service['access'],'write')
            s=self.full(engine);self.reserve(s,engine,False);del s.service['access']
            restored=ProfileState.from_data(s.export())
            self.assertEqual(NativeProfiles.plan(None,restored,engine)['access'],'write')
            restored.reconcile_availability();self.assertNotIn('access',restored.service)

    def test_prompts_name_configured_agent_and_all_four_tools_for_either_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            native=SimpleNamespace(notion=notion,plan=lambda s,e:NativeProfiles.plan(None,s,e),manager=SimpleNamespace(exchange=lambda e:Path(tmp)/e),claude_work=tmp)
            with patch.object(notion,'CONFIG',lambda:dict(name='Reserve Helper')):
                for e in ('claude','codex'):
                    s=self.full(e);self.reserve(s,e,False)
                    text=NativeProfiles.prompt(native,s,e)
                    self.assertIn('Reserve Helper',text)
                    for tool in notion.CODEX_TOOLS:self.assertIn(tool,text)
                    for phrase in ('секреты','проверяй','уже подтверждённой задачи','хэшами'):self.assertIn(phrase,text)
                    s.service['source']='auto';text=NativeProfiles.prompt(native,s,e)
                    self.assertIn('данным лимитов',text);self.assertNotIn('отключён человеком',text)

    def test_codex_full_reserve_recognition_does_not_change_other_profiles(self):
        for access in ('write','full'):
            self.assertEqual(bridge.active_profile(dict(profile='reserve',mode='self',access=access,task_rights='dev')),'reserve')
        self.assertEqual(bridge.active_profile(dict(profile='reserve',mode='orchestrator',access='full',task_rights='dev')),'')
        self.assertEqual(bridge.active_profile(dict(profile='executor',mode='self',access='full',task_rights='dev')),'')

    def test_generated_full_reserve_instructions_match_effective_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bridge,'workspace_dir',lambda:tmp),patch.object(bridge.cc_codex,'own',lambda p:None),patch.object(bridge,'project_dir',lambda s:'/test-project'),patch.object(bridge,'RESERVE_NOTE',lambda:'Notion reserve workflow'),patch.object(bridge,'image_output_note',lambda s:''):
                bridge.ensure_workspace(dict(profile='reserve',mode='self',access='full',task_rights='dev'))
                text=(Path(tmp)/'AGENTS.md').read_text()
                self.assertIn('Сохраняются права Full',text);self.assertIn('Claude на паузе',text)
                self.assertNotIn('Проект не меняй',text);self.assertNotIn('Notion-агент не используются',text)
                self.assertIn('Notion reserve workflow',text)

    def test_four_mcp_tools_only_and_full_commands_remain_allowed(self):
        with patch.object(notion,'active',lambda:True),patch.object(notion,'SOLO_PROFILE',lambda:False):
            args=notion.codex_args();values=dict(zip(args[1::2],args[::2]))
            self.assertIn('mcp_servers.notion.enabled=true',values)
            self.assertIn('mcp_servers.notion.enabled_tools='+__import__('json').dumps(list(notion.CODEX_TOOLS),separators=(',',':')),values)
        policy=dict(access='full',reserve=True,cwd='/test')
        for name in ('Bash',*('mcp__notion__'+t.replace('-','_') for t in notion.CODEX_TOOLS)):
            self.assertFalse(decide(policy,dict(tool_name=name)))
        for name in ('Agent','mcp__notion__notion_update_page','mcp__codex__run'):
            self.assertTrue(decide(policy,dict(tool_name=name)))

    def test_failed_full_reserve_switch_restores_state_and_console_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            n=FakeNative();p=Profiles(tmp,n);e='codex'
            p.apply_scenario(dict(choices=dict(claude=None,codex='full'),confirm='подтверждаю',revision=0))
            before=p.state.export();n.fail=True
            result=p.action(e,'apply',dict(id='reserve',confirm='подтверждаю',revision=p.state.revision))
            self.assertFalse(result['ok']);self.assertEqual(p.state.export(),before)
            self.assertEqual(n.model[e],'gpt-test');self.assertEqual(n.tid[e],'codex-thread')
            self.assertFalse(p.pending.exists())

    def test_native_preflight_never_upgrades_actual_restricted_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            n=SimpleNamespace(busy=lambda:False,bridge=SimpleNamespace(_state=lambda:{}),manager=SimpleNamespace(exchange=lambda e:Path(tmp)/e),ns={'cc_codex':SimpleNamespace(own=lambda p:None)},reserve_ready=lambda:True,claude_work=tmp)
            for actual in ('write','full'):
                before=self.full('codex');after=ProfileState.from_data(before.export());self.reserve(after,'codex',False)
                NativeProfiles.preflight(n,before,after,['codex'],dict(codex_settings=dict(access=actual),codex_runtime=dict(thread_id='same'),codex_sandbox='danger-full-access' if actual=='full' else 'workspace-write'))
                self.assertEqual(after.service['access'],actual)
            before=self.full('codex');after=ProfileState.from_data(before.export());self.reserve(after,'codex',False)
            NativeProfiles.preflight(n,before,after,['codex'],dict(codex_settings=dict(access='full'),codex_runtime=dict(thread_id='same'),codex_sandbox='workspace-write'))
            self.assertEqual(after.service['access'],'write')

    def test_claude_preflight_preserves_only_existing_bypass_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            n=SimpleNamespace(busy=lambda:False,bridge=SimpleNamespace(_state=lambda:{}),manager=SimpleNamespace(exchange=lambda e:Path(tmp)/e),ns={'cc_codex':SimpleNamespace(own=lambda p:None)},reserve_ready=lambda:True,claude_work=tmp,claude=SimpleNamespace(prepare=lambda *a:None),claude_policy=lambda s:{},prompt=lambda s,e:'test')
            for actual in (False,True):
                before=self.full('claude');after=ProfileState.from_data(before.export());self.reserve(after,'claude',False)
                NativeProfiles.preflight(n,before,after,['claude'],dict(claude=dict(bypass=actual)))
                self.assertEqual(after.service['access'],'full' if actual else 'write')

if __name__=='__main__':unittest.main()
