import copy
import itertools
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from cc_manual_scenarios import validate_choices,ROLES,DUO_ID
from cc_profile_state import ProfileState
from cc_profiles import Profiles
from test_cc_profiles import FakeNative,legacy_pair_state


class ManualPolicy(unittest.TestCase):
    def test_new_leader_executor_pairs_are_rejected_and_state_is_untouched(self):
        # связки Claude↔Codex убраны: новые пары не принимаются ни в каком порядке
        for leader in ('claude','codex'):
            state=ProfileState();other=state.other(leader);before=state.export()
            for companion in (None,'full','orchestrator','executor'):
                self.assertFalse(state.apply_scenario({leader:'orchestrator',other:companion},revision=0)['ok'])
                self.assertEqual(state.export(),before)

    def test_only_full_or_claude_duo_are_accepted(self):
        valid=[]
        for a,b in itertools.product((None,'full','reserve','duo','orchestrator','executor'),repeat=2):  # reserve больше не принимается
            if validate_choices(dict(claude=a,codex=b))[0]:valid.append((a,b))
        self.assertCountEqual(valid,[(None,'full'),('full',None),('duo',None)])

    def test_duo_is_claude_only(self):
        state=ProfileState();before=state.export()
        self.assertFalse(state.apply_scenario(dict(claude=None,codex='duo'),'подтверждаю',0)['ok'])
        self.assertFalse(state.apply_scenario(dict(claude='duo',codex='full'),'подтверждаю',0)['ok'])
        self.assertEqual(state.export(),before)

    def test_duo_needs_confirmation_then_claude_works_solo_and_codex_is_paused(self):
        state=ProfileState();before=state.export();choices=dict(claude='duo',codex=None)
        self.assertTrue(state.apply_scenario(choices,revision=0)['confirmation_required']);self.assertEqual(state.export(),before)
        self.assertTrue(state.apply_scenario(choices,'подтверждаю',0)['ok'])
        view=state.public();claude=view['engines']['claude']
        self.assertEqual(claude['role'],'solo');self.assertEqual(claude['selected'],DUO_ID)
        self.assertEqual(view['engines']['codex']['role'],'paused')
        self.assertIsNone(view['leader'])
        self.assertEqual(view['manual_scenario']['choices'],choices)

    def test_duo_survives_reload_and_does_not_replace_the_last_full_choice(self):
        state=ProfileState();self.assertTrue(state.apply_scenario(dict(claude=None,codex='full'),'подтверждаю',0)['ok'])
        last=state.export().get('last_solo')
        self.assertTrue(state.apply_scenario(dict(claude='duo',codex=None),'подтверждаю',state.revision)['ok'])
        self.assertEqual(state.export().get('last_solo'),last)
        restored=ProfileState.from_data(state.export());view=restored.public()
        self.assertEqual(view['engines']['claude']['selected'],DUO_ID);self.assertEqual(view['engines']['claude']['role'],'solo')
        self.assertEqual(restored.manual_choices,dict(claude='duo',codex=None))

    def test_leaving_duo_for_full_returns_claude_to_its_own_full_profile(self):
        state=ProfileState();self.assertTrue(state.apply_scenario(dict(claude='duo',codex=None),'подтверждаю',0)['ok'])
        self.assertTrue(state.apply_scenario(dict(claude='full',codex=None),'подтверждаю',state.revision)['ok'])
        self.assertEqual(state.public()['engines']['claude']['selected'],'claude_solo_full')

    def test_old_route_apply_accepts_duo_only_for_claude(self):
        state=ProfileState();before=state.export()
        self.assertFalse(state.apply('codex',DUO_ID,'подтверждаю',0)['ok']);self.assertEqual(state.export(),before)
        self.assertTrue(state.apply('claude',DUO_ID,'подтверждаю',0)['ok'])
        self.assertEqual(state.public()['engines']['claude']['selected'],DUO_ID)

    def test_invalid_selections_and_revisions_do_not_modify_state(self):
        state=ProfileState();before=state.export()
        for choices in [None,{},dict(claude='full'),dict(claude='full',codex='full'),
                        dict(claude='orchestrator',codex=None),dict(claude='executor',codex='executor')]:
            self.assertFalse(state.apply_scenario(choices,revision=0)['ok']);self.assertEqual(state.export(),before)
        for revision in [None,True,'0',-1,1]:
            result=state.apply_scenario(dict(claude=None,codex='full'),'подтверждаю',revision)
            self.assertFalse(result['ok']);self.assertEqual(state.export(),before)

    def test_full_confirmation_is_global_and_other_engine_is_paused(self):
        state=ProfileState();before=state.export();choices=dict(claude=None,codex='full')
        self.assertTrue(state.apply_scenario(choices,revision=0)['confirmation_required'])
        self.assertEqual(state.export(),before)
        self.assertTrue(state.apply_scenario(choices,'подтверждаю',0)['ok'])
        view=state.public();self.assertEqual(view['engines']['claude']['role'],'paused')
        self.assertEqual(view['engines']['codex']['role'],'solo')
        self.assertEqual(ProfileState.from_data(state.export()).public()['manual_scenario']['choices'],choices)

    def test_single_codex_account_is_never_paused_by_claude_full(self):
        # один аккаунт Codex — ротации нет: Claude Full оставляет Codex самостоятельным (не на паузе, с прежним профилем)
        with patch.object(ProfileState,'codex_independent',staticmethod(lambda:True)):
            state=ProfileState();choices=dict(claude='full',codex=None)
            self.assertTrue(state.apply_scenario(choices,'подтверждаю',0)['ok'])
            view=state.public();codex=view['engines']['codex']
            self.assertEqual(view['engines']['claude']['role'],'solo');self.assertEqual(codex['role'],'solo');self.assertTrue(codex['active'])
            self.assertNotIn('на паузе',codex['label']);self.assertNotIn('не участвует',codex['label']);self.assertEqual(codex['selected'],codex['base_selected'])
            # зеркальный случай: Claude (несколько аккаунтов, есть ротация) при Codex Full по-прежнему на паузе
            other=ProfileState();self.assertTrue(other.apply_scenario(dict(claude=None,codex='full'),'подтверждаю',0)['ok'])
            self.assertEqual(other.public()['engines']['claude']['role'],'paused')

    def test_several_codex_accounts_keep_the_old_pause(self):
        with patch.object(ProfileState,'codex_independent',staticmethod(lambda:False)):
            state=ProfileState();self.assertTrue(state.apply_scenario(dict(claude='full',codex=None),'подтверждаю',0)['ok'])
            self.assertEqual(state.public()['engines']['codex']['role'],'paused')

    def test_broken_independence_check_falls_back_to_pause(self):
        def boom():raise OSError('нет профилей')
        with patch.object(ProfileState,'codex_independent',staticmethod(boom)):
            state=ProfileState();self.assertTrue(state.apply_scenario(dict(claude='full',codex=None),'подтверждаю',0)['ok'])
            self.assertEqual(state.public()['engines']['codex']['role'],'paused')

    def test_legacy_state_is_reported_without_activating_or_pausing_sessions(self):
        state=ProfileState();raw=state.export();raw.pop('manual_choices')
        restored=ProfileState.from_data(raw);view=restored.public()
        self.assertTrue(view['manual_scenario']['legacy'])
        self.assertEqual([view['engines'][e]['role'] for e in ('claude','codex')],['solo','solo'])
        self.assertEqual(restored.selected,raw['selected'])

    def test_public_work_catalog_has_full_and_duo_without_pair_entries(self):
        public=ProfileState().public()
        self.assertFalse(public['capabilities']['orchestrator']);self.assertTrue(public['capabilities']['duo'])
        want=dict(claude=['claude_solo_full',DUO_ID],codex=['codex_solo_full'])
        for engine,data in public['engines'].items():
            self.assertEqual([p['id'] for p in data['profiles'] if p['kind']!='reserve'],want[engine])

    def test_older_saved_pairs_are_still_readable_with_their_rights(self):
        # записи прежних версий (ведущий/ведомый) читаются без падения и без смены прав
        for leader in ('claude','codex'):
            state=legacy_pair_state(leader);follower=state.other(leader)
            choices={leader:'orchestrator',follower:'executor'}
            self.assertEqual(state.public()['leader'],leader)
            native=FakeNative()
            self.assertEqual(native.plan(state,leader)['access'],'read')
            self.assertEqual(native.plan(state,follower)['access'],'write')
            self.assertEqual(native.plan(state,follower)['task_rights'],'dev')
            self.assertEqual(ProfileState.from_data(state.export()).manual_choices,choices)


    def test_old_one_engine_route_cannot_implicitly_assign_executor(self):
        state=ProfileState();before=state.export()
        self.assertFalse(state.apply('codex','orchestrator',revision=0)['ok'])
        self.assertEqual(state.export(),before)

    def test_inconsistent_persisted_topology_is_rejected(self):
        state=legacy_pair_state('claude')
        raw=state.export();raw['leader']='codex'
        with self.assertRaises(ValueError):ProfileState.from_data(raw)


class ManualTransactions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.native=FakeNative();self.manager=Profiles(self.tmp.name,self.native)

    def apply(self,choices,confirm=''):
        return self.manager.apply_scenario(dict(choices=choices,confirm=confirm,revision=self.manager.state.revision))

    def test_install_and_get_do_not_touch_native_processes(self):
        before=copy.deepcopy((self.native.model,self.native.tid))
        for _ in range(3):self.manager.public()
        self.assertFalse(self.native.applied);self.assertEqual(before,(self.native.model,self.native.tid))

    def test_invalid_or_unconfirmed_request_has_no_runtime_or_file_effect(self):
        before=self.manager.path.read_bytes()
        for choices in [dict(claude='full',codex='full'),dict(claude=None,codex='orchestrator'),dict(claude='orchestrator',codex='full'),dict(claude=None,codex='full')]:
            self.assertFalse(self.apply(choices)['ok'])
        self.assertEqual(self.manager.path.read_bytes(),before);self.assertEqual(self.native.applied,[])

    def test_both_engines_commit_once_and_survive_reload(self):
        choices=dict(claude='full',codex=None)
        self.assertTrue(self.apply(choices,'подтверждаю')['ok']);self.assertEqual(len(self.native.applied),1)
        self.assertCountEqual(self.native.applied[0][2],['claude','codex'])
        other=Profiles(self.tmp.name,FakeNative());self.assertEqual(other.state.manual_choices,choices)
        self.assertEqual(other.native.applied,[])

    def test_failed_second_native_application_restores_both_state_and_models(self):
        before=self.manager.state.export();self.native.fail=True
        self.assertFalse(self.apply(dict(claude='full',codex=None),'подтверждаю')['ok'])
        self.assertEqual(self.manager.state.export(),before)
        self.assertEqual(json.loads(self.manager.path.read_text())['core'],before)
        self.assertEqual(self.native.model,dict(claude='claude-test',codex='gpt-test'))
        self.assertTrue(self.native.rollbacks);self.assertFalse(self.manager.pending.exists())

    def test_busy_turn_rejects_entire_change_and_preserves_legacy_sessions(self):
        self.native.busy_value=True
        self.assertTrue(self.apply(dict(claude=None,codex='full'),'подтверждаю')['busy'])
        self.assertEqual(self.native.applied,[]);self.assertIsNone(self.manager.state.manual_choices)

    def test_install_verification_holds_profile_changes_but_keeps_console_input(self):
        marker=self.manager.base/'profile-update.json'
        from pathlib import Path
        start=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
        marker.write_text(json.dumps(dict(pid=os.getpid(),start=start)))
        self.assertTrue(self.manager.public()['updating']);self.assertTrue(self.manager.input_allowed('codex'))
        self.assertTrue(self.apply(dict(claude=None,codex='full'),'подтверждаю')['busy'])
        self.assertEqual(self.native.applied,[])
        marker.unlink();self.assertFalse(self.manager.public()['updating'])

    def test_failed_preflight_does_not_commit_a_scenario(self):
        before=self.manager.state.export()
        with patch.object(self.native,'preflight',side_effect=RuntimeError('reserve_not_ready')):
            self.assertFalse(self.apply(dict(claude='reserve',codex=None),'подтверждаю')['ok'])
        self.assertEqual(self.native.applied,[]);self.assertEqual(self.manager.state.export(),before)
        self.assertFalse(self.manager.pending.exists())

    def test_switching_full_moves_exclusivity_to_the_selected_model(self):
        self.assertTrue(self.apply(dict(claude=None,codex='full'),'подтверждаю')['ok'])
        self.assertFalse(self.manager.input_allowed('claude'));self.assertTrue(self.manager.input_allowed('codex'))
        self.assertTrue(self.apply(dict(claude='full',codex=None),'подтверждаю')['ok'])
        self.assertTrue(self.manager.input_allowed('claude'));self.assertFalse(self.manager.input_allowed('codex'))

    def test_stale_request_never_reaches_native_adapter(self):
        stale=self.manager.state.revision;self.apply(dict(claude=None,codex='full'),'подтверждаю')
        count=len(self.native.applied)
        result=self.manager.apply_scenario(dict(choices=dict(claude='full',codex=None),confirm='подтверждаю',revision=stale))
        self.assertTrue(result['conflict']);self.assertEqual(len(self.native.applied),count)


if __name__=='__main__':unittest.main()
