import copy
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import cc_codex as codex
from cc_codex_models import Discovery
from test_cc_fleet_overview import Routes


def model(mid):
    return dict(id=mid, displayName=mid.upper(), defaultReasoningEffort='high',
                supportedReasoningEfforts=[{'reasoningEffort':'high'}])


class CatalogTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.patch=mock.patch.object(codex,'PROFILES',str(self.root));self.patch.start();self.addCleanup(self.patch.stop)
        codex._models_cache.clear();codex._cache.clear()
        for slot in ['gpt1','gpt2']:
            (self.root/slot).mkdir();(self.root/slot/'auth.json').write_text('{}')

    def client(self,*pages):
        return types.SimpleNamespace(request=mock.Mock(side_effect=pages))

    def test_complete_catalog_pagination_hidden_and_duplicate(self):
        c=self.client({'data':[model('old')],'nextCursor':'page2'},
                      {'data':[model('old'),model('new'),dict(model('hidden'),hidden=True)]})
        self.assertEqual([m['id'] for m in codex._catalog(c,'gpt1')],['old','new'])
        self.assertEqual(c.request.call_args_list[1].args[1]['cursor'],'page2')
        self.assertEqual(c.request.call_args_list[0].args[0],'model/list')

    def test_force_bypasses_cache_and_accounts_do_not_share_catalog(self):
        c=self.client({'data':[model('old')]},{'data':[model('new')]},{'data':[model('other')]})
        codex._catalog(c,'gpt1');codex._catalog(c,'gpt1')
        self.assertEqual(c.request.call_count,1)
        self.assertEqual(codex._catalog(c,'gpt1',force=True)[0]['id'],'new')
        self.assertEqual(codex._catalog(c,'gpt2')[0]['id'],'other')
        self.assertEqual(codex.cached_models('gpt1')[0]['id'],'new')

    def test_failure_or_empty_result_keeps_previous_catalog(self):
        codex._catalog(self.client({'data':[model('old')]}),'gpt1')
        for page in [{'data':[]},{'data':'bad'},RuntimeError('private token')]:
            with self.assertRaises(Exception):codex._catalog(self.client(page),'gpt1',force=True)
            self.assertEqual(codex.cached_models('gpt1')[0]['id'],'old')

    def test_repeated_cursor_is_rejected_without_partial_publish(self):
        c=self.client({'data':[model('one')],'nextCursor':'same'}, {'data':[model('two')],'nextCursor':'same'})
        with self.assertRaises(codex.CodexError):codex._catalog(c,'gpt1')
        self.assertIsNone(codex.cached_models('gpt1'))

    def test_new_login_invalidates_old_catalog(self):
        codex._catalog(self.client({'data':[model('old')]}),'gpt1')
        (self.root/'gpt1/auth.json').write_text('{"new_login":true}')
        self.assertIsNone(codex.cached_models('gpt1'))
        self.assertEqual(codex._catalog(self.client({'data':[model('new')]}),'gpt1')[0]['id'],'new')

    def test_cached_models_cannot_be_mutated_by_reader(self):
        codex._catalog(self.client({'data':[model('old')]}),'gpt1')
        codex.cached_models('gpt1')[0]['efforts'].append('wrong')
        self.assertEqual(codex.cached_models('gpt1')[0]['efforts'],['high'])

    def test_refresh_updates_only_models_and_uses_no_inference_or_config_write(self):
        before=dict(slot='gpt1',model='old',effort='high',fast=True,windows=[{'pct':30}],ts=1)
        codex._cache['gpt1']={'ts':1,'data':copy.deepcopy(before)}
        c=self.client({'data':[model('old'),model('new')]})
        ctx=mock.MagicMock();ctx.__enter__.return_value=c
        with mock.patch.object(codex,'AppServer',return_value=ctx):codex.refresh_models('/fake','gpt1')
        after=dict(codex._cache['gpt1']['data']);self.assertEqual(len(after.pop('models')),2);self.assertEqual(after,before)
        self.assertEqual([call.args[0] for call in c.request.call_args_list],['model/list'])

    def test_unknown_slot_does_not_launch_process(self):
        with mock.patch.object(codex,'AppServer') as server:
            for slot in ['../gpt1','gpt3',None]:
                with self.assertRaises(codex.CodexError):codex.refresh_models('/fake',slot)
            server.assert_not_called()

    def test_account_deleted_during_check_does_not_publish_account_cache(self):
        c=self.client({'data':[model('new')]});ctx=mock.MagicMock();ctx.__enter__.return_value=c
        with mock.patch.object(codex,'AppServer',return_value=ctx),mock.patch.object(codex,'profile_slots',side_effect=[['gpt1'],[]]):
            with self.assertRaises(codex.CodexError):codex.refresh_models('/fake','gpt1')
        self.assertNotIn('gpt1',codex._cache)


class DiscoveryTests(unittest.TestCase):
    def fixture(self):
        rotation=types.SimpleNamespace(lock=threading.RLock(),active=lambda:'gpt1',accounts=[dict(slot='gpt1',models=[{'id':'old'}],model='old',effort='high')],publish_models=mock.Mock())
        cod=types.SimpleNamespace(profile_slots=lambda:['gpt1'],refresh_models=mock.Mock(return_value=[{'id':'old'},{'id':'new'}]))
        obj=Discovery(cod,rotation,lambda:'/fake');return obj,cod,rotation

    def finish(self,obj):
        deadline=time.monotonic()+2
        while obj.public()['checking'] and time.monotonic()<deadline:time.sleep(.005)
        self.assertFalse(obj.public()['checking']);return obj.public()

    def test_single_background_request_returns_immediately_and_marks_new_models(self):
        obj,cod,rotation=self.fixture();entered,release=threading.Event(),threading.Event()
        def fetch(*args):entered.set();release.wait(2);return [{'id':'old'},{'id':'new'}]
        cod.refresh_models.side_effect=fetch
        started=time.monotonic();self.assertTrue(obj.start()['checking']);self.assertLess(time.monotonic()-started,.2)
        self.assertTrue(entered.wait(1));self.assertTrue(obj.start()['checking']);self.assertEqual(cod.refresh_models.call_count,1)
        release.set();state=self.finish(obj);self.assertTrue(state['ok']);self.assertEqual(state['new_ids'],['new']);rotation.publish_models.assert_called_once()
        self.assertEqual(rotation.accounts[0]['model'],'old');self.assertEqual(rotation.accounts[0]['effort'],'high')

    def test_error_is_sanitized_and_does_not_publish(self):
        obj,cod,rotation=self.fixture();cod.refresh_models.side_effect=RuntimeError('SECRET token')
        obj.start();state=self.finish(obj);self.assertFalse(state['ok']);self.assertNotIn('SECRET',str(state));rotation.publish_models.assert_not_called()

    def test_without_active_account_no_background_job(self):
        obj,cod,rotation=self.fixture();rotation.active=lambda:''
        self.assertFalse(obj.start()['ok']);cod.refresh_models.assert_not_called()

    def test_account_switch_during_check_keeps_original_target(self):
        obj,cod,rotation=self.fixture();rotation.active=lambda:'gpt2'
        obj._work('/fake','gpt1',{'old'});self.assertEqual(cod.refresh_models.call_args.args,('/fake','gpt1'))
        rotation.publish_models.assert_called_once_with('gpt1',[{'id':'old'},{'id':'new'}])

    def test_public_snapshot_is_detached(self):
        obj,_,_=self.fixture();obj.start();self.finish(obj);state=obj.public();state['new_ids'].append('bad');self.assertNotIn('bad',obj.public()['new_ids'])


class ModelRoutes(Routes):
    def test_catalog_status_is_fast_and_authenticated(self):
        h,_=self.fixture('/api/chatgpt/models');status,data=h.do_GET();self.assertEqual(status,200);self.assertFalse(data['checking'])

    def test_authenticated_check_dispatches_to_background_controller(self):
        with mock.patch.object(Discovery,'start',return_value={'ok':True,'checking':True}) as start:
            h,_=self.fixture('/api/chatgpt/models/check');self.assertEqual(h.do_POST(),(200,{'ok':True,'checking':True}))
            start.assert_called_once_with()


if __name__=='__main__':unittest.main()
