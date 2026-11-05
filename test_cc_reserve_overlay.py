"""The reserve is a delegation workflow over Full; Yes is explicit and scoped."""
import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cc_notion as notion
import cc_codex_bridge as bridge
import cc_profiles as profiles
from cc_profile_state import ProfileState
from test_cc_profiles import FakeNative

class ReserveOverlay(unittest.TestCase):
    def full(self,engine):
        state=ProfileState();state.apply_scenario({e:'full' if e==engine else None for e in ('claude','codex')},'подтверждаю',0)
        return state

    def test_only_explicit_yes_enables_reserve_and_never_enables_full_profile(self):
        for engine in ('claude','codex'):
            for answer in (None,False,0,1,'true','yes','да',''):
                s=self.full(engine);before=s.export()
                result=s.apply(engine,'reserve',answer,s.revision)
                self.assertTrue(result['confirmation_required']);self.assertEqual(result['confirmation'],'yes_no')
                self.assertNotIn('word',result);self.assertEqual(s.export(),before)
            s=self.full(engine)
            self.assertTrue(s.apply(engine,'reserve',True,s.revision)['ok'])
            s=ProfileState();self.assertTrue(s.apply_scenario({engine:'full',s.other(engine):None},True,0)['confirmation_required'])

    def test_full_profile_survives_manual_and_auto_reserve_and_reload(self):
        for engine in ('claude','codex'):
            for automatic in (False,True):
                s=self.full(engine);choices=s.manual_choices.copy()
                if automatic:
                    self.assertTrue(s.configure(engine,True,confirm=True)['ok'])
                    s.availability[s.other(engine)]=False;s.reconcile_availability()
                else:self.assertTrue(s.apply(engine,'reserve',True,s.revision)['ok'])
                s=ProfileState.from_data(s.export());public=s.public();plan=profiles.NativeProfiles.plan(None,s,engine)
                self.assertEqual(public['engines'][engine]['selected'],engine+'_solo_full')
                self.assertEqual(public['engines'][engine]['label'],s.actor(engine)+' Full')
                self.assertEqual(public['manual_scenario']['choices'],choices)
                self.assertEqual(plan['profile'],engine+'_solo_full');self.assertEqual(plan['access'],'full')
                self.assertEqual(public['engines'][s.other(engine)]['role'],'paused')
                s.stop_service(engine);self.assertEqual(s.manual_choices,choices)

    def test_auto_confirmation_is_yes_no_and_false_does_not_change_configuration(self):
        s=self.full('codex');before=s.export()
        result=s.configure('codex',True,confirm=False)
        self.assertEqual(result['confirmation'],'yes_no');self.assertNotIn('word',result);self.assertEqual(s.export(),before)
        self.assertTrue(s.configure('codex',True,confirm=True)['ok'])
        self.assertTrue(s.auto['codex']['enabled'])

    def test_bound_full_profile_receives_only_the_four_reserve_tools_and_delegate_prompt(self):
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            # Restore every module callback changed by bind, including those changed after patching.
            for name in ('active','public','tick','start','SOLO_PROFILE','CONFIG'):
                stack.enter_context(patch.object(notion,name,getattr(notion,name)))
            notion.CONFIG=lambda:dict(name='Test Helper')
            settings=dict(profile='codex_solo_full',mode='self',access='full',task_rights='dev')
            n=FakeNative();n.notion=notion;n.emergency=SimpleNamespace();n.claude_work=tmp
            n.original_notion_args=notion.codex_args;n.original_notion_note=notion.codex_note
            n.original_notion_public=lambda lv=None:dict(available=True,connected=True)
            n.reserve_ready=lambda:True;native_class=profiles.NativeProfiles;n.prompt=lambda state,e:native_class.prompt(n,state,e)
            n.bridge=SimpleNamespace(load=lambda:settings,active_profile=bridge.active_profile,BRIDGE=SimpleNamespace(enqueue_work=lambda item:None))
            n.codex=SimpleNamespace(MCP=lambda:[],apply_plan=lambda:None)
            ns=dict(BASE=tmp,FLEET_ROTATION=SimpleNamespace())
            stack.enter_context(patch.object(profiles,'NativeProfiles',lambda ns:n))
            p=profiles.bind(ns,SimpleNamespace())
            self.assertTrue(p.apply_scenario(dict(choices=dict(codex='full',claude=None),confirm='подтверждаю',revision=0))['ok'])
            self.assertTrue(notion.SOLO_PROFILE());self.assertFalse(n.bridge.RESERVE_ACTIVE())
            self.assertNotIn('mcp_servers.notion.url=',str(n.codex.MCP()))
            self.assertTrue(p.action('codex','apply',dict(id='reserve',confirm=True,revision=p.state.revision))['ok'])
            self.assertFalse(notion.SOLO_PROFILE());self.assertTrue(n.bridge.RESERVE_ACTIVE())
            self.assertEqual(bridge.active_profile(settings),'codex_solo_full')
            args=n.codex.MCP();text=' '.join(args)
            for tool in notion.CODEX_TOOLS:self.assertIn(tool,text)
            self.assertIn('Test Helper',text);self.assertIn('передавай агенту проверяемыми шагами',text)
            self.assertIn('не переходи на самостоятельное выполнение без согласования с человеком',text)
            self.assertNotIn('notion-update-page',text)
            self.assertTrue(p.action('codex','stop',dict(revision=p.state.revision))['ok'])
            self.assertTrue(notion.SOLO_PROFILE());self.assertFalse(n.bridge.RESERVE_ACTIVE())
            self.assertNotIn('mcp_servers.notion.url=',str(n.codex.MCP()))

    def test_full_reserve_generated_instructions_do_not_say_work_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bridge,'workspace_dir',lambda:tmp),patch.object(bridge.cc_codex,'own',lambda p:None),patch.object(bridge,'project_dir',lambda s:'/project'),patch.object(bridge,'RESERVE_ACTIVE',lambda:True),patch.object(bridge,'RESERVE_NOTE',lambda:'Reserved workflow'),patch.object(bridge,'image_output_note',lambda s:''):
                bridge.ensure_workspace(dict(profile='codex_solo_full',mode='self',access='full',task_rights='dev'))
                text=(Path(tmp)/'AGENTS.md').read_text()
                self.assertIn('Сохраняются права Full',text);self.assertIn('Reserved workflow',text)
                self.assertNotIn('Claude и Notion-агент не используются',text)

if __name__=='__main__':unittest.main()
