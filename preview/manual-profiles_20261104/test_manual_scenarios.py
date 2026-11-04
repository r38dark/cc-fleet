import copy,unittest
from manual_scenarios import ManualScenarios,validate_choices

class ManualPolicy(unittest.TestCase):
 def setUp(self):self.state=ManualScenarios()
 def apply(self,choices,word='подтверждаю'):
  return self.state.apply_scenario(choices,word,self.state.revision)
 def test_catalog_is_mirrored_with_separate_executor(self):
  for e in ['claude','codex']:
   self.assertEqual([p['id'] for p in self.state.definitions(e)],[e+'_solo_full','orchestrator','executor','reserve'])
 def test_both_full_scenarios_pause_other_without_a_second_role(self):
  for e,other in [('claude','codex'),('codex','claude')]:
   self.assertTrue(self.apply({e:'full',other:None})['ok']);view=self.state.public();self.assertEqual(view['engines'][e]['role'],'solo');self.assertEqual(view['engines'][other]['role'],'paused');self.assertIsNone(view['engines'][other]['selected'])
 def test_both_leading_directions_need_explicit_executor(self):
  for e,other in [('claude','codex'),('codex','claude')]:
   before=self.state.public();self.assertFalse(self.apply({e:'orchestrator',other:None})['ok']);self.assertEqual(self.state.public(),before)
   self.assertTrue(self.apply({e:'orchestrator',other:'executor'})['ok']);self.assertEqual(self.state.public()['leader'],e);self.assertEqual(self.state.public()['engines'][other]['role'],'executor');self.assertEqual(self.state.public()['engines'][other]['selected'],'executor')
 def test_rejected_combinations_leave_existing_scenario_untouched(self):
  for choices in [dict(claude=None,codex=None),dict(claude='full',codex='full'),dict(claude='full',codex='executor'),dict(claude='orchestrator',codex='orchestrator'),dict(claude='executor',codex='executor'),dict(claude='reserve',codex='orchestrator'),dict(claude=None,codex='executor'),dict(claude='old',codex=None),dict(claude=['full'],codex=None),dict(claude='full'),None]:
   before=self.state.public();self.assertFalse(self.apply(choices)['ok']);self.assertEqual(self.state.public(),before)
 def test_full_and_reserve_require_confirmation_for_whole_scenario(self):
  for choices in [dict(claude='full',codex=None),dict(claude='reserve',codex=None)]:
   before=self.state.public();result=self.apply(choices,'');self.assertTrue(result['confirmation_required']);self.assertEqual(self.state.public(),before)
 def test_stale_revision_cannot_replace_another_windows_choice(self):
  old=self.state.revision;self.apply(dict(claude='orchestrator',codex='executor'));before=self.state.public()
  result=self.state.apply_scenario(dict(claude='full',codex=None),'подтверждаю',old);self.assertTrue(result['conflict']);self.assertEqual(self.state.public(),before)
 def test_one_engine_apply_does_not_silently_assign_follower(self):
  before=self.state.public();result=self.state.apply('claude','orchestrator',revision=self.state.revision);self.assertFalse(result['ok']);self.assertEqual(self.state.public(),before)
 def test_manual_reserve_restores_both_chosen_roles(self):
  for e,other in [('claude','codex'),('codex','claude')]:
   pair={e:'orchestrator',other:'executor'};self.apply(pair);self.apply({e:'reserve',other:None});self.assertEqual(self.state.public()['engines'][e]['until'],0)
   self.assertTrue(self.state.stop_service(e,self.state.revision)['ok']);self.assertEqual(self.state.choices,pair)
 def test_changing_reserve_side_still_restores_original_pair(self):
  pair=dict(claude='orchestrator',codex='executor');self.apply(pair);self.apply(dict(claude='reserve',codex=None));self.apply(dict(claude=None,codex='reserve'));self.state.stop_service('codex');self.assertEqual(self.state.choices,pair)
 def test_explicit_auto_reserve_works_without_expiry_and_restores_on_recovery(self):
  self.state.configure('codex',True,False,'подтверждаю',self.state.revision);self.state.set_availability('claude',False)
  self.assertEqual(self.state.choices,dict(claude=None,codex='reserve'));self.assertEqual(self.state.public()['engines']['codex']['until'],0)
  self.state.set_availability('claude',True);self.assertEqual(self.state.choices,dict(claude=None,codex='full'))
 def test_disabling_auto_restores_previous_roles(self):
  self.apply(dict(claude='orchestrator',codex='executor'));self.state.configure('codex',True,False,'подтверждаю',self.state.revision);self.state.set_availability('claude',False)
  self.state.configure('codex',False,False,'',self.state.revision);self.assertEqual(self.state.choices,dict(claude='orchestrator',codex='executor'))
 def test_public_gets_do_not_pick_roles_or_mutate_revision(self):
  before=copy.deepcopy(self.state.public())
  for _ in range(20):self.assertEqual(self.state.public(),before)

if __name__=='__main__':unittest.main()
