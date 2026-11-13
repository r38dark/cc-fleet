import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cc_codex_bridge as bridge
import cc_codex_emergency as emergency
from cc_profile_state import ProfileScenarios, ProfileState
from cc_profiles import Profiles
from cc_profile_tasks import ProfileTasks
from test_cc_profiles import FakeNative,legacy_pair_state


class SimpleProfiles(unittest.TestCase):
    def setUp(self):
        self.now=1000;self.state=ProfileScenarios(lambda:self.now)

    def test_exact_symmetric_catalog(self):
        for engine in ['claude','codex']:
            profiles=self.state.definitions(engine)
            # внутренний каталог: Full, прежняя связка (нужна, чтобы читать старые записи; в интерфейс не попадает), у Claude — «Opus → Sonnet»
            self.assertEqual([p['id'] for p in profiles],[engine+'_solo_full','orchestrator']+(['claude_opus_sonnet'] if engine=='claude' else []))
            self.assertEqual([p['kind'] for p in profiles],['full','orchestrator']+(['duo'] if engine=='claude' else []))
            self.assertEqual(profiles[0]['access'],'full');self.assertEqual(profiles[1]['access'],'read')
            self.assertEqual(profiles[1]['task_rights'],'dev')
            self.assertTrue(profiles[1]['title'].startswith('Claude → Codex' if engine=='claude' else 'Codex → Claude'))

    def test_legacy_bridge_catalog_cannot_offer_removed_or_custom_profiles(self):
        self.assertEqual([p[0] for p in bridge._profiles({'profiles':[dict(id='old',name='old',mode='self',access='write',task_rights='full')]})],['orchestrator','codex_solo_full'])

    def test_explicit_companion_is_reported_without_becoming_a_selectable_profile(self):
        settings=dict(profile='executor',mode='self',access='write',task_rights='dev')
        self.assertEqual(bridge.active_profile(settings),'executor')
        self.assertNotIn('executor',[p[0] for p in bridge._profiles(settings)])
        settings['access']='full';self.assertEqual(bridge.active_profile(settings),'')

    def test_removed_scenarios_are_rejected_without_changing_state(self):
        for engine in ['claude','codex']:
            for profile in [engine,'emergency','old-custom']:
                before=self.state.public();self.assertFalse(self.state.apply(engine,profile,'аварийный')['ok']);self.assertEqual(self.state.public(),before)
            self.assertFalse(self.state.configure(engine,True,True,'аварийный')['ok'])




    def test_legacy_stored_state_is_normalized_without_runtime_work(self):
        old=ProfileState().export();old['selected']=dict(claude='claude',codex='old-custom');old['last_solo']=dict(old['selected']);old['until']=1
        old['auto']['codex']=dict(enabled=True,emergency=True)
        state=ProfileState.from_data(old,lambda:self.now)
        self.assertEqual(state.selected,dict(claude='claude_solo_full',codex='codex_solo_full'))
        self.assertEqual(state.until,0);self.assertFalse(state.auto['codex']['emergency'])
        self.assertFalse(state.auto['codex']['enabled'])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'work_profiles.json').write_text(json.dumps(dict(core=old,managed=dict(claude=True,codex=True))))
            native=FakeNative();manager=Profiles(tmp,native,lambda:self.now)
            self.assertEqual(native.applied,[]);self.assertFalse(manager.managed['claude']);self.assertFalse(manager.managed['codex'])
            self.assertEqual(manager.state.until,0)

    def test_orchestrator_caps_requested_full_step_to_legacy_dev_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            native=FakeNative();profiles=Profiles(tmp,native);profiles.transition(legacy_pair_state('claude',profiles.state),'Исторический сценарий')
            sent=[];asked=[];tasks=ProfileTasks(profiles,lambda *args:sent.append(args),lambda *args:asked.append(args) or 'проверено');profiles.tasks=tasks
            draft=profiles.exchange('claude')/'outbox/task.md';draft.parent.mkdir(parents=True);draft.write_text('права: полные\nПроверяемый шаг')
            tasks.tick();task=tasks.public();self.assertEqual(task['rights'],'dev');self.assertEqual(task['requested_rights'],'full')
            self.assertNotIn('права: полные',task['text'].lower());self.assertEqual(asked,[])
            tasks.confirm(dict(id=task['id'],approve=True));tasks.tick();tasks.worker.join(2)
            self.assertIn('Права шага: dev',asked[0][1]);self.assertEqual(sent[0][0],'claude')

    def test_full_has_explicit_activation_and_preserves_native_model_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            native=FakeNative();profiles=Profiles(tmp,native);before=copy.deepcopy((native.model,native.tid))
            result=profiles.action('claude','apply',dict(id='claude_solo_full'));self.assertTrue(result['confirmation_required']);self.assertEqual(native.applied,[])
            self.assertTrue(profiles.action('claude','apply',dict(id='claude_solo_full',confirm='подтверждаю',revision=profiles.state.revision))['ok'])
            self.assertEqual((native.model,native.tid),before)

    def test_no_expiry_watcher_is_started(self):
        with mock.patch.object(emergency,'reconcile'),mock.patch.object(emergency.threading,'Thread') as thread:
            emergency.start();thread.assert_not_called()

    def test_legacy_manual_mode_save_cannot_reenable_removed_scenario(self):
        from test_cc_fleet_overview import Routes
        route=Routes();self.addCleanup(route.doCleanups)
        handler,_=route.fixture('/api/chatgpt/bridge/save')
        status,data=handler._chatgpt_post('bridge/save',dict(mode='mediator'))
        self.assertEqual(status,200);self.assertFalse(data['ok'])


if __name__=='__main__':unittest.main()
