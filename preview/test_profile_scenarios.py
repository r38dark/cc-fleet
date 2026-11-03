import unittest
from profile_scenarios import ProfileScenarios
class ScenariosTests(unittest.TestCase):
 def setUp(self):self.now=1000;self.s=ProfileScenarios(lambda:self.now)
 def test_mirror_catalog(self):
  for e in ['claude','codex']:
   ps=self.s.definitions(e);self.assertEqual([p['kind'] for p in ps],['orchestrator','solo','full','reserve','emergency']);self.assertTrue(all(p['title'].startswith(e.capitalize() if e=='claude' else 'Codex') for p in ps))
 def test_only_one_leader_and_restore_solo(self):
  self.s.apply('claude','orchestrator');d=self.s.public();self.assertEqual(d['leader'],'claude');self.assertEqual(d['engines']['codex']['role'],'executor')
  self.s.apply('codex','orchestrator');d=self.s.public();self.assertEqual(d['leader'],'codex');self.assertEqual(d['engines']['claude']['base_selected'],'claude');self.assertEqual(d['engines']['claude']['role'],'executor')
  self.s.apply('claude','claude');self.assertIsNone(self.s.public()['leader']);self.assertEqual(self.s.public()['engines']['codex']['selected'],'codex_solo_full')
 def test_full_confirmation_on_each_side(self):
  for e in ['claude','codex']:
   self.s.apply(e,e);r=self.s.apply(e,e+'_solo_full');self.assertTrue(r['confirmation_required']);self.assertEqual(self.s.public()['engines'][e]['selected'],e);self.assertTrue(self.s.apply(e,e+'_solo_full','подтверждаю')['ok'])
 def test_reserve_restores_pair_and_cannot_have_two_owners(self):
  self.s.apply('codex','orchestrator');self.assertTrue(self.s.apply('claude','reserve','подтверждаю')['ok']);self.assertEqual(self.s.public()['engines']['codex']['role'],'paused');self.assertTrue(self.s.stop_service('claude')['ok']);self.assertEqual(self.s.public()['leader'],'codex')
  self.s.apply('claude','reserve','подтверждаю');self.s.apply('codex','reserve','подтверждаю');self.assertEqual(self.s.public()['service']['engine'],'codex');self.assertEqual(self.s.public()['engines']['claude']['role'],'paused')
 def test_emergency_confirmation_expiry_and_switch_cancels_old_restore(self):
  self.s.apply('claude','orchestrator');self.assertTrue(self.s.apply('codex','emergency')['confirmation_required']);self.s.apply('codex','emergency','аварийный');self.now+=7201;self.assertEqual(self.s.public()['leader'],'claude');self.assertIsNone(self.s.public()['service'])
  self.s.apply('claude','emergency','аварийный');self.s.apply('codex','codex');self.now+=7201;self.assertEqual(self.s.public()['engines']['codex']['selected'],'codex');self.assertIsNone(self.s.public()['service'])
 def test_stale_revision_rejected_without_mutation(self):
  rev=self.s.revision;self.s.apply('claude','orchestrator');d=self.s.public();self.assertTrue(self.s.apply('codex','orchestrator',revision=rev)['conflict']);self.assertEqual(self.s.public(),d)
 def test_invalid_engine_id_and_builtin_delete(self):
  self.assertFalse(self.s.apply('other','claude')['ok']);self.assertFalse(self.s.apply('claude','missing')['ok']);self.assertFalse(self.s.delete('claude','claude')['ok'])
 def test_auto_reserve_symmetric_and_restores_on_recovery(self):
  for e in ['claude','codex']:
   s=ProfileScenarios();other=s.other(e);s.apply(other,'orchestrator');before=s.public()['leader']
   self.assertTrue(s.configure(e,True,False)['confirmation_required']);self.assertTrue(s.configure(e,True,False,'подтверждаю')['ok']);self.assertIsNone(s.public()['service'])
   s.set_availability(other,False);d=s.public();self.assertEqual(d['service']['engine'],e);self.assertEqual(d['service']['source'],'auto');self.assertEqual(d['engines'][other]['role'],'paused')
   s.set_availability(other,True);self.assertIsNone(s.public()['service']);self.assertEqual(s.public()['leader'],before)
 def test_manual_stop_suppresses_auto_until_recovery(self):
  self.s.configure('claude',True,False,'подтверждаю');self.s.set_availability('codex',False);self.s.stop_service('claude')
  for _ in range(3):self.assertIsNone(self.s.public()['service'])
  self.assertTrue(self.s.public()['engines']['claude']['auto_blocked']);self.s.set_availability('codex',True);self.s.set_availability('codex',False);self.assertEqual(self.s.public()['service']['engine'],'claude')
 def test_automatic_emergency_requires_word_and_expires_without_loop(self):
  self.assertTrue(self.s.configure('codex',True,True,'подтверждаю')['confirmation_required']);self.s.configure('codex',True,True,'аварийный');self.s.set_availability('claude',False);self.assertEqual(self.s.public()['service']['emergency'],True)
  self.now+=7201;self.assertIsNone(self.s.public()['service']);self.assertIsNone(self.s.public()['service'])
 def test_never_auto_uses_unavailable_owner_and_manual_takes_precedence(self):
  self.s.configure('claude',True,False,'подтверждаю');self.s.configure('codex',True,False,'подтверждаю');self.s.set_availability('claude',False);self.s.set_availability('codex',False);self.assertIsNone(self.s.public()['service'])
  self.s.set_availability('codex',True);self.assertEqual(self.s.public()['service']['engine'],'codex');self.s.apply('claude','claude');self.assertIsNone(self.s.public()['service'])
 def test_stale_stop_and_config_cannot_change_new_scenario(self):
  rev=self.s.revision;self.s.apply('claude','reserve','подтверждаю');before=self.s.public();self.assertTrue(self.s.stop_service('claude',revision=rev)['conflict']);self.assertTrue(self.s.configure('claude',True,False,'подтверждаю',rev)['conflict']);self.assertEqual(self.s.public(),before)
if __name__=='__main__':unittest.main()
