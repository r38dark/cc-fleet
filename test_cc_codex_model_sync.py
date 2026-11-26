"""Account defaults must not masquerade as a resumed conversation's model."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import types
import unittest
from unittest import mock

import cc_codex_rotation
import cc_limits
import test_cc_fleet_overview as fleet_tests


class RuntimeSnapshot(unittest.TestCase):
    def fixture(self, running=True, pending=None):
        obj = cc_codex_rotation.Rotation.__new__(cc_codex_rotation.Rotation)
        obj.lock = threading.RLock()
        obj.refresh = mock.Mock()
        obj.accounts = [{'slot': 'gpt1', 'model': None, 'effort': 'low', 'models': []}]
        obj.refreshing, obj.updated = False, 10
        obj.codex = types.SimpleNamespace(profile_slots=lambda: ['gpt1'], meta=lambda slot: {})
        obj.binary = lambda: '/fake-codex'
        obj.console = types.SimpleNamespace(
            _pid=lambda: '123' if running else None,
            _meta=lambda: {'slot': 'gpt1', 'pending_settings': pending},
            active_settings=mock.Mock(return_value={
                'model': 'old-model', 'effort': 'high', 'service_tier': None,
                'thread_id': 'private-thread', 'rollout_path': '/private/history'}))
        return obj

    def test_live_model_is_separate_from_account_default_and_private_history(self):
        obj = self.fixture()
        snap = obj.snapshot()
        self.assertIsNone(snap['accounts'][0]['model'])
        self.assertEqual(snap['runtime'], dict(running=True, slot='gpt1', model='old-model',
                                             effort='high', service_tier=None, pending=None))
        self.assertNotIn('private', json.dumps(snap))

    def test_pending_choice_does_not_replace_the_running_model(self):
        obj = self.fixture(pending={'model': 'new-model', 'effort': 'low',
                                    'thread_id': 'private-thread', 'rollout_path': '/private/history'})
        snap = obj.snapshot()
        self.assertEqual(snap['runtime']['model'], 'old-model')
        self.assertEqual(snap['runtime']['pending'], {'model': 'new-model', 'effort': 'low'})
        self.assertNotIn('private', json.dumps(snap))

    def test_stopped_console_uses_defaults_without_resurrecting_old_state(self):
        obj = self.fixture(running=False)
        self.assertEqual(obj.snapshot()['runtime'], {'running': False})
        obj.console.active_settings.assert_not_called()


class PreferenceRouting(unittest.TestCase):
    fixture = fleet_tests.Routes.fixture

    def route(self, model, effort='high'):
        handler, ns = self.fixture('/api/chatgpt/prefs')
        codex, console = ns['cc_codex'], ns['cc_codex_console']
        catalog = [{'id': 'new-model', 'is_default': True, 'default_effort': 'high'},
                   {'id': 'old-model', 'is_default': False, 'default_effort': 'high'}]
        codex._lock = threading.RLock()
        codex._cache = {'gpt1': {'data': {'models': catalog}}}
        console.request_settings.return_value = (True, 'waiting for reply', True)
        ns['FLEET_ROTATION'].refresh = mock.Mock()
        response = handler._chatgpt_post('prefs', dict(slot='gpt1', model=model, effort=effort, fast=False))
        return response, console.request_settings.call_args.args[0]

    def test_selecting_default_resolves_to_new_default_for_live_console(self):
        response, settings = self.route('')
        self.assertTrue(response[1]['pending'])
        self.assertEqual(settings, dict(model='new-model', effort='high', service_tier=None))

    def test_explicit_selection_and_effort_are_passed_to_live_console(self):
        _, settings = self.route('old-model', 'low')
        self.assertEqual(settings, dict(model='old-model', effort='low', service_tier=None))


@unittest.skipUnless(shutil.which('node'), 'node is required for actual picker JavaScript')
class PickerRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = cc_limits.PAGE
        source = page[page.index('function cxQCur('):page.index('async function cxpApply(')]
        harness = r"""
const LANG='ru',posts=[];
const tr=(key,...args)=>key+(args.length?':'+args.join(','):'');
const acctEsc=s=>String(s==null?'':s),toast=()=>{};
const els={'#cxQ':{hidden:false,classList:{add(){},remove(){}}},
 '#cxMod':{setAttribute(){}},'#cxModN':{},'#cxModE':{},'#cxQb':{innerHTML:''}};
const $=s=>els[s],window={fleetAsk:async()=>true};
let ACC,cxData;
const cxLimAcc=()=>ACC;
async function acctPost(path,body){posts.push(body);return{ok:true,message:'ok'}}
async function cxLoad(){}
const ms=[{id:'new-model',name:'NEW',is_default:true,efforts:['low','high'],default_effort:'low'},
 {id:'old-model',name:'OLD',efforts:['low','high'],default_effort:'high'}];
function reset(){ACC={slot:'gpt1',model:null,effort:'low',models:ms};cxData={accounts:[ACC],
 runtime:{running:true,slot:'gpt1',model:'old-model',effort:'high',pending:null}};posts.length=0;}
__SOURCE__
(async()=>{
 const o={};reset();
 cxQBtn();o.header=[els['#cxModN'].textContent,els['#cxModE'].textContent];
 cxQRender();o.currentHTML=els['#cxQb'].innerHTML;
 await cxQSet('',null);o.applyDefault=posts.slice();
 reset();await cxQSet(null,'low');o.effortKeepsLiveModel=posts.slice();
 reset();await cxQSet('old-model',null);o.explicitOld=posts.slice();
 reset();await cxQSet('new-model',null);o.explicitNew=posts.slice();
 reset();ACC.model='new-model';cxData.runtime.pending={model:'new-model',effort:'high'};
 cxQBtn();o.pendingHeader=[els['#cxModN'].textContent,els['#cxModE'].textContent];
 cxQRender();o.pendingHTML=els['#cxQb'].innerHTML;
 await cxQSet(null,'low');o.effortKeepsPendingModel=posts.slice();
 reset();cxData.runtime.pending={model:'new-model',effort:'high'};
 await cxQSet(null,'low');o.pendingDefault=posts.slice();
 reset();cxData.runtime.model='new-model';cxData.runtime.effort='low';
 await cxQSet('',null);o.sameDefault=posts.slice();
 reset();cxData.runtime.slot='gpt2';o.otherAccount=cxQCur(ACC).name;
 reset();cxData.runtime.running=false;o.stopped=cxQCur(ACC).name;
 reset();cxData.runtime.model='unlisted-model';o.unknown=cxQCur(ACC).name;
 console.log(JSON.stringify(o));
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace('__SOURCE__', source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'picker.js'
            path.write_text(harness)
            run = subprocess.run(['node', str(path)], capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise AssertionError(run.stderr)
        cls.results = json.loads(run.stdout)

    def test_header_shows_live_model_and_effort_instead_of_new_default(self):
        self.assertEqual(self.results['header'], ['OLD', 'high'])
        self.assertRegex(self.results['currentHTML'], r'aria-checked="true" data-m="old-model"')
        self.assertRegex(self.results['currentHTML'], r'aria-checked="false" data-m=""')

    def test_selecting_default_is_not_a_false_noop(self):
        self.assertEqual(self.results['applyDefault'], [dict(slot='gpt1', model='', effort='high', fast=False)])

    def test_effort_change_keeps_the_running_model(self):
        self.assertEqual(self.results['effortKeepsLiveModel'], [dict(slot='gpt1', model='old-model', effort='low', fast=False)])

    def test_explicit_model_is_persisted_even_when_already_running(self):
        self.assertEqual(self.results['explicitOld'], [dict(slot='gpt1', model='old-model', effort='high', fast=False)])
        self.assertEqual(self.results['explicitNew'], [dict(slot='gpt1', model='new-model', effort='high', fast=False)])

    def test_pending_choice_keeps_header_honest_and_survives_effort_change(self):
        self.assertEqual(self.results['pendingHeader'], ['OLD', 'high · cxQWait'])
        self.assertRegex(self.results['pendingHTML'], r'aria-checked="true" data-m="new-model"')
        self.assertEqual(self.results['effortKeepsPendingModel'], [dict(slot='gpt1', model='new-model', effort='low', fast=False)])
        self.assertEqual(self.results['pendingDefault'], [dict(slot='gpt1', model='', effort='low', fast=False)])

    def test_matching_default_is_a_noop_and_other_sessions_do_not_leak(self):
        self.assertEqual(self.results['sameDefault'], [])
        self.assertEqual(self.results['otherAccount'], 'NEW')
        self.assertEqual(self.results['stopped'], 'NEW')
        self.assertEqual(self.results['unknown'], 'unlisted-model')


if __name__ == '__main__':
    unittest.main()
