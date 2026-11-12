import datetime
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import cc_codex
import cc_codex_console as console
import cc_codex_rotation as rotation
import cc_fleet
import cc_session


MODEL = 'chosen-model'
TID = '11111111-2222-4333-8444-555555555555'


def account(slot, session=20, week=30, hours=12, **extra):
    reset = datetime.datetime.fromtimestamp(time.time()+hours*3600, datetime.timezone.utc).isoformat()
    return dict(slot=slot, label=slot, ts=time.time(), windows=[{'mins':300,'pct':session},
                {'mins':10080,'pct':week,'resets_at':reset}],
                models=[{'id':MODEL,'efforts':['high'],'is_default':True,'default_effort':'high'}], **extra)


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.home = self.root/'gpt1';self.home.mkdir()
        (self.home/'config.toml').write_text('model="default-other-model"\nmodel_reasoning_effort="low"\n')
        self.db=sqlite3.connect(self.home/'state_5.sqlite')
        self.db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,model TEXT,reasoning_effort TEXT,cwd TEXT,rollout_path TEXT,updated_at_ms INTEGER)')
        self.db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?)',(TID,MODEL,'high','/project',str(self.home/'rollout.jsonl'),int((time.time()-10)*1000)))
        self.db.commit();self.addCleanup(self.db.close)
        self.meta={'slot':'gpt1','cwd':'/project','tids':{'/project':TID}}

    def capture(self, meta=None):
        return cc_session.capture(meta or self.meta, lambda slot:str(self.root/slot))

    def test_model_and_effort_come_from_exact_thread(self):
        saved=self.capture();self.assertEqual((saved['model'],saved['effort'],saved['thread_id']),(MODEL,'high',TID))

    def test_destination_account_does_not_replace_source_model(self):
        other=self.root/'gpt2';other.mkdir();(other/'config.toml').write_text('model="wrong"')
        saved=self.capture();args=cc_session.launch_args('/codex',saved,'danger-full-access','never')
        self.assertEqual(args[args.index('--model')+1],MODEL)
        self.assertIn(TID,args);self.assertNotIn('--last',args)
        self.assertIn('sqlite_home='+json.dumps(str(self.home)),args)

    def test_launch_settings_win_until_first_new_turn(self):
        meta=dict(self.meta,started=time.time(),settings={'model':'new-choice','effort':'xhigh','service_tier':None})
        saved=self.capture(meta);self.assertEqual((saved['model'],saved['effort']),('new-choice','xhigh'))
        self.db.execute('UPDATE threads SET model=?,reasoning_effort=?,updated_at_ms=?',('later-manual-choice','high',int((time.time()+1)*1000)));self.db.commit()
        self.assertEqual(self.capture(meta)['model'],'later-manual-choice')

    def test_workspace_and_access_are_explicit(self):
        args=cc_session.launch_args('/codex',self.capture(),'workspace-write','never',['-c','mcp_servers.test.enabled=false'])
        self.assertEqual(args[args.index('--cd')+1],'/project')
        self.assertEqual(args[args.index('--sandbox')+1],'workspace-write')
        self.assertIn('model_reasoning_effort="high"',args)

    def test_new_workspace_does_not_resume_an_unrelated_thread(self):
        args=cc_session.launch_args('/codex',{'new_session':True,'cwd':'/other','model':MODEL},'read-only','never')
        self.assertNotIn('resume',args);self.assertNotIn('--last',args)


class Console(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_long_turn_remains_busy_beyond_old_tail_limit(self):
        p=self.root/'rollout.jsonl'
        event={'type':'event_msg','timestamp':'2026-11-03T00:00:00Z','payload':{'type':'task_started','turn_id':'root'}}
        p.write_bytes(json.dumps(event).encode()+b'\n'+b'{}\n'*(console.TAIL//2))
        self.assertTrue(console._turn_open(p))
        with p.open('ab') as f:f.write(json.dumps(dict(event,payload={'type':'task_complete','turn_id':'child'})).encode()+b'\n')
        self.assertTrue(console._turn_open(p))
        with p.open('ab') as f:f.write(json.dumps(dict(event,payload={'type':'task_complete','turn_id':'root'})).encode()+b'\n')
        self.assertFalse(console._turn_open(p))

    def test_terminal_control_words_in_user_text_do_not_affect_busy(self):
        p=self.root/'rollout.jsonl';p.write_text(json.dumps({'type':'response_item','payload':{'type':'task_started','turn_id':'fake'}})+'\n')
        self.assertFalse(console._turn_open(p))

    def test_slash_commands_are_sent_without_telegram_prefix(self):
        with mock.patch.object(console,'busy',return_value=False),mock.patch.object(console,'ensure',return_value=(True,'')), \
             mock.patch.object(console,'_meta',return_value={'started':0}),mock.patch.object(console,'_paste',return_value=True) as paste, \
             mock.patch.object(console,'_ctl',return_value=types.SimpleNamespace(returncode=0)) as ctl,mock.patch.object(console.time,'sleep'):
            ok,_=console.send_input('/model chosen-model');self.assertTrue(ok);paste.assert_called_once_with('chosen-model')
            self.assertEqual(ctl.call_args.args[0][-1],'/model ')

    def test_plain_message_is_sent_while_model_replies(self):
        with mock.patch.object(console,'current_turn_open',return_value=True),mock.patch.object(console,'ensure',return_value=(True,'')), \
             mock.patch.object(console,'_meta',return_value={'started':0}),mock.patch.object(console,'_paste',return_value=True) as paste:
            self.assertTrue(console.send_input('message')[0]);paste.assert_called_once_with('message')

    def test_command_is_held_while_model_replies(self):
        with mock.patch.object(console,'current_turn_open',return_value=True),mock.patch.object(console,'_paste') as paste, \
             mock.patch.object(console,'_ctl') as ctl:
            ok,message=console.send_input('/model x');self.assertFalse(ok);self.assertIn('команду',message)
            paste.assert_not_called();ctl.assert_not_called()
            self.assertFalse(console._ask_lock.locked(),'замок освобождён после отказа')

    def test_message_is_held_while_bridge_request_runs(self):
        with console._ask_lock,mock.patch.object(console,'_paste') as paste:
            self.assertFalse(console.send_input('message')[0]);paste.assert_not_called()

    def test_invalid_console_input_is_rejected(self):
        for text in ['',None,'Ж'*25000]:self.assertFalse(console.send_input(text)[0])

    def test_pending_model_survives_busy_and_empty_retry(self):
        p=self.root/'meta.json';p.write_text('{}')
        with mock.patch.object(console,'_meta_path',return_value=str(p)),mock.patch.object(console,'_meta',side_effect=lambda:json.loads(p.read_text())), \
             mock.patch.object(console,'active_settings',return_value={'model':'old','effort':'high'}),mock.patch.object(cc_codex,'own'), \
             mock.patch.object(console,'current_turn_open',return_value=True),mock.patch.object(console,'ensure') as ensure:
            self.assertTrue(console.request_settings({'model':MODEL,'effort':'xhigh'})[2])
            self.assertTrue(console.request_settings({})[2]);ensure.assert_not_called()
            self.assertEqual(json.loads(p.read_text())['pending_settings']['model'],MODEL)


class Policy(unittest.TestCase):
    def test_available_known_limits_and_model_are_required(self):
        self.assertTrue(rotation.eligible(account('gpt1'),MODEL,'high'))
        for row in [account('gpt1',login_required=True),account('gpt1',stale=True),account('gpt1',usage_allowed=False),account('gpt1',session=100),account('gpt1',week=99),dict(account('gpt1'),windows=[]),dict(account('gpt1'),ts=1),dict(account('gpt1'),models=[])]:
            self.assertFalse(rotation.eligible(row,MODEL,'high'),row)

    def test_near_reset_with_headroom_is_preferred(self):
        self.assertGreater(rotation.score(account('soon',hours=2)),rotation.score(account('later',hours=120)))

    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        settings={'model':MODEL,'effort':'high','thread_id':TID,'history_home':temp.name,'cwd':'/project'}
        bridge_state={'slot':'gpt1'}
        bridge=types.SimpleNamespace(_lock=threading.RLock(),load=lambda:dict(bridge_state),_save=lambda d:bridge_state.update(d))
        codex=types.SimpleNamespace(jload=lambda p,d:dict(d),_jsave=lambda p,d:Path(p).write_text(json.dumps(d)),own=lambda p:None,
                profile_slots=lambda:['gpt1','gpt2'],meta=lambda s:{'label':s},cached_models=lambda s:None,get_accounts=lambda b,force=False:[account('gpt1'),account('gpt2')],set_prefs=mock.Mock(return_value=(True,'')))
        con=types.SimpleNamespace(active_settings=lambda:dict(settings),_pid=lambda:'fake-pid',_meta=lambda:{'slot':'gpt1'},
            _meta_path=lambda:os.path.join(temp.name,'console.json'),busy=lambda:False,current_turn_open=lambda:False,
            _ask_lock=threading.Lock(),stop=mock.Mock(return_value=(True,'')),start=mock.Mock(return_value=(True,'')),request_settings=mock.Mock(),apply_plan=mock.Mock(),verify_ready=mock.Mock(return_value=(True,'')))
        obj=rotation.Rotation(temp.name,codex,con,lambda:'/fake-codex',bridge);obj.accounts=[account('gpt1'),account('gpt2')]
        return obj,con,codex,bridge_state

    def test_switch_preserves_exact_model_effort_and_thread(self):
        obj,con,codex,bridge=self.fixture();obj.state['optimize']=False
        self.assertTrue(obj.switch('gpt2',manual=True)[0]);self.assertEqual(bridge['slot'],'gpt2')
        self.assertEqual(codex.set_prefs.call_args.args[2:4],(MODEL,'high'))
        self.assertEqual(json.loads(Path(con._meta_path()).read_text())['pending_settings']['thread_id'],TID)

    def test_busy_turn_prevents_switch(self):
        obj,con,_,bridge=self.fixture();con.busy=lambda:True
        self.assertFalse(obj.switch('gpt2')[0]);self.assertEqual(bridge['slot'],'gpt1');con.stop.assert_not_called()

    def test_busy_turn_rechecked_after_preference_write(self):
        obj,con,_,bridge=self.fixture();con.current_turn_open=lambda:True
        self.assertFalse(obj.switch('gpt2')[0]);self.assertEqual(bridge['slot'],'gpt1');con.stop.assert_not_called()

    def test_start_failure_rolls_back_account(self):
        obj,con,_,bridge=self.fixture();con.start.side_effect=[(False,'failed'),(True,'restored')]
        self.assertFalse(obj.switch('gpt2')[0]);self.assertEqual(bridge['slot'],'gpt1');self.assertEqual(con.start.call_count,2)
        self.assertNotIn('history',obj.state)

    def test_profile_transition_suspends_rotation_and_plan_refresh(self):
        obj,con,_,bridge=self.fixture();obj.suspended=lambda:True;obj.state['optimize']=False
        self.assertFalse(obj.switch('gpt2',manual=True)[0]);obj.tick();con.stop.assert_not_called();con.apply_plan.assert_not_called();self.assertEqual(bridge['slot'],'gpt1')

    def test_manual_choice_requires_optimization_off(self):
        obj,con,_,bridge=self.fixture();self.assertFalse(obj.switch('gpt2',manual=True)[0]);con.stop.assert_not_called()

    def test_invalid_config_does_not_partially_change_policy(self):
        obj,_,_,_=self.fixture();self.assertFalse(obj.configure({'optimize':False,'threshold':10})[0]);self.assertTrue(obj.state['optimize'])

    def test_snapshot_does_not_wait_for_account_network(self):
        obj,_,codex,_=self.fixture();gate=threading.Event();self.addCleanup(gate.set)
        codex.get_accounts=lambda b,force=False:(gate.wait(1),[account('gpt1')])[1]
        start=time.monotonic();data=obj.snapshot();self.assertLess(time.monotonic()-start,.1);self.assertTrue(data['loading'])
        gate.set()


class Input(unittest.TestCase):
    def test_deduplication_and_conflict(self):
        con=types.SimpleNamespace(send_input=mock.Mock(return_value=(True,'sent')))
        obj=cc_fleet.ConsoleInput({'cc_codex_console':con})
        self.assertTrue(obj.send('codex','message','nonce1234')[0]);self.assertTrue(obj.send('codex','message','nonce1234')[0])
        self.assertFalse(obj.send('codex','changed','nonce1234')[0]);self.assertEqual(con.send_input.call_count,1)

    def test_invalid_engine_and_nonce_never_reach_console(self):
        con=types.SimpleNamespace(send_input=mock.Mock())
        obj=cc_fleet.ConsoleInput({'cc_codex_console':con})
        self.assertFalse(obj.send('other','test','nonce1234')[0]);self.assertFalse(obj.send('codex','test','bad')[0]);con.send_input.assert_not_called()

    def test_claude_plain_message_goes_while_busy_but_command_waits(self):
        with tempfile.TemporaryDirectory() as folder:
            obj=cc_fleet.ConsoleInput({'BASE':folder,'cfg':lambda:{'screen_session':'fake'},'session_busy':lambda:True})
            calls=[]
            with mock.patch.object(cc_fleet.subprocess,'run',side_effect=lambda a,**k:calls.append(a) or types.SimpleNamespace(returncode=0)),mock.patch.object(cc_fleet.time,'sleep'):
                self.assertTrue(obj.send('claude','ещё одно сообщение','nonce0001')[0]);self.assertTrue(calls)
                calls.clear()
                ok,message=obj.send('claude','/compact','nonce0002');self.assertFalse(ok);self.assertIn('команду',message);self.assertFalse(calls)

    def test_claude_bracketed_paste_preserves_unicode_without_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as folder:
            obj=cc_fleet.ConsoleInput({'BASE':folder,'cfg':lambda:{'screen_session':'fake'},'session_busy':lambda:False})
            seen=[]
            def run(args,**kw):
                if args[-2]=='readbuf':seen.append(Path(args[-1]).read_text())
                return types.SimpleNamespace(returncode=0)
            with mock.patch.object(cc_fleet.subprocess,'run',side_effect=run),mock.patch.object(cc_fleet.time,'sleep'):
                self.assertTrue(obj.send('claude','Привет $(literal)\n/model x','nonce5678')[0])
            self.assertEqual(seen,['\x1b[200~Привет $(literal)\n/model x\x1b[201~'])
            self.assertFalse(list(Path(folder).iterdir()))





class Extra(unittest.TestCase):
    def test_missing_metadata_uses_same_project_index(self):
        with tempfile.TemporaryDirectory() as td:
            db=sqlite3.connect(Path(td)/'state_5.sqlite')
            db.execute('CREATE TABLE threads(id TEXT,model TEXT,cwd TEXT,updated_at INTEGER)')
            db.executemany('INSERT INTO threads VALUES(?,?,?,?)',[(TID,MODEL,'/project',1),('other','wrong','/other',2)])
            db.commit();db.close()
            saved=cc_session.capture({'slot':'gpt1','cwd':'/project'},lambda s:td)
            self.assertEqual(saved['thread_id'],TID)
            args=cc_session.launch_args('/codex',{'cwd':'/empty'},'read-only','never')
            self.assertNotIn('resume',args)

    def test_busy_rejection_can_be_retried_without_duplicate_paste(self):
        con=types.SimpleNamespace(send_input=mock.Mock(side_effect=[(False,'В консоли Codex идёт ответ.'),(True,'sent')]))
        obj=cc_fleet.ConsoleInput({'cc_codex_console':con})
        self.assertFalse(obj.send('codex','message','retry123')[0]);self.assertTrue(obj.send('codex','message','retry123')[0])
        self.assertTrue(obj.send('codex','message','retry123')[0]);self.assertEqual(con.send_input.call_count,2)

    def test_ambiguous_send_failure_is_not_replayed(self):
        con=types.SimpleNamespace(send_input=mock.Mock(return_value=(False,'Консоль не приняла ввод.')))
        obj=cc_fleet.ConsoleInput({'cc_codex_console':con})
        obj.send('codex','message','retry123');obj.send('codex','message','retry123');self.assertEqual(con.send_input.call_count,1)

    def test_native_modal_blocks_account_commit_and_rolls_back(self):
        obj,con,_,bridge=Policy.fixture(self)
        con.verify_ready.side_effect=[(False,'open elsewhere'),(True,'')]
        self.assertFalse(obj.switch('gpt2')[0]);self.assertEqual(bridge['slot'],'gpt1')
        self.assertEqual(con.start.call_count,2);self.assertNotIn('history',obj.state)

    def test_new_profile_is_visible_before_network_refresh(self):
        obj,_,codex,_=Policy.fixture(self);codex.profile_slots=lambda:['gpt1','gpt2','gpt3'];obj.updated=time.time()
        snapshot=obj.snapshot();self.assertEqual([a['slot'] for a in snapshot['accounts']],['gpt1','gpt2','gpt3']);self.assertTrue(snapshot['accounts'][2]['loading'])

    def test_deleted_account_is_not_shown_from_old_cache(self):
        obj,_,codex,_=Policy.fixture(self);codex.profile_slots=lambda:['gpt1'];obj.updated=time.time()
        self.assertEqual([a['slot'] for a in obj.snapshot()['accounts']],['gpt1'])

    def test_queued_profile_is_retried_without_new_message(self):
        obj,con,_,_=Policy.fixture(self);obj.state['optimize']=False
        with mock.patch.object(obj,'refresh'):obj.tick()
        con.apply_plan.assert_called_once()

    def test_native_start_modal_is_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'console.log';p.write_text('This conversation is open in another app\n›')
            with mock.patch.object(console,'_log',return_value=str(p)),mock.patch.object(console,'_pid',return_value='fake'),mock.patch.object(console,'_wait_ready'):
                self.assertFalse(console.verify_ready()[0])
                p.write_text('Codex\n› Ready · ? for shortcuts');self.assertTrue(console.verify_ready()[0])


class Routes(unittest.TestCase):
    def fixture(self,path,body=None,authed=True):
        import io
        rotation_obj,con,codex,bridge=Policy.fixture(self)
        from cc_input_queue import InputQueue
        rotation_obj.bridge.BRIDGE=types.SimpleNamespace(inputs=InputQueue(),_notice_async=mock.Mock(),enqueue_console=mock.Mock(return_value=(True,'queued')))
        con.PAUSED=lambda:False;con.mark=lambda:None
        class H:
            def _authed(self):return self.authorized
            def _send(self,status,data):return status,data
            def do_GET(self):return 'old-get'
            def do_POST(self):return 'old-post'
            def _chatgpt_post(self,action,body):return 'old-'+action
        ns={'H':H,'PAGE':'<html><head></head><body></body></html>','BASE':str(rotation_obj.path.parent),
            'cc_codex':codex,'cc_codex_console':con,'cc_codex_bridge':rotation_obj.bridge,'codex_bin':lambda:'/fake'}
        import cc_profiles
        profile_stub=types.SimpleNamespace(transitioning=False,public=lambda:{'ok':True,'available':True},input_allowed=lambda e:True,console_allowed=lambda e:True,side_active=lambda e:False,paused=lambda e:False,pending=types.SimpleNamespace(exists=lambda:False),action=lambda *a:{'ok':True},apply_scenario=mock.Mock(return_value={'ok':True}),tasks=types.SimpleNamespace(confirm=lambda body:{'ok':True}))
        ns['TEST_PROFILES']=profile_stub
        with mock.patch.object(cc_profiles,'bind',return_value=profile_stub):cc_fleet.install(ns)
        h=ns['H']();h.path=path;h.authorized=authed
        raw=json.dumps(body or {}).encode();h.rfile=io.BytesIO(raw);h.headers={'Content-Length':str(len(raw))}
        return h,ns

    def test_new_routes_require_authentication_before_body_read(self):
        for path in ['/api/profiles/scenario/apply','/api/profiles/claude/apply','/api/profiles/task/confirm','/api/console/input','/api/console/key','/api/chatgpt/rotation/config','/api/chatgpt/rotation/switch','/api/chatgpt/models/check']:
            h,_=self.fixture(path,authed=False);self.assertEqual(h.do_POST()[0],403);self.assertEqual(h.rfile.tell(),0)
        for path in ['/api/profiles','/api/chatgpt/bridge','/api/chatgpt','/api/chatgpt/rotation','/api/chatgpt/models']:
            h,_=self.fixture(path,authed=False);self.assertEqual(h.do_GET()[0],403)

    def test_existing_routes_still_delegate(self):
        h,_=self.fixture('/api/config');self.assertEqual(h.do_POST(),'old-post');self.assertEqual(h.do_GET(),'old-get')
        self.assertEqual(h._chatgpt_post('bridge/save',{}),'old-bridge/save')

    def test_shared_scenario_route_passes_both_choices_in_one_transaction(self):
        body=dict(choices=dict(claude='orchestrator',codex='executor'),revision=9)
        h,ns=self.fixture('/api/profiles/scenario/apply',body)
        self.assertEqual(h.do_POST(),(200,{'ok':True}))
        ns['TEST_PROFILES'].apply_scenario.assert_called_once_with(body)

    def test_payload_shape_and_size_are_checked(self):
        h,_=self.fixture('/api/console/input');h.headers['Content-Length']='65537';self.assertEqual(h.do_POST()[0],413)
        h,_=self.fixture('/api/console/input');h.headers['Content-Length']='-1';self.assertEqual(h.do_POST()[0],413)
        h,_=self.fixture('/api/console/input');h.rfile=__import__('io').BytesIO(b'[]');h.headers['Content-Length']='2';self.assertEqual(h.do_POST()[0],400)

    def test_authenticated_console_input_dispatches_to_selected_provider(self):
        h,ns=self.fixture('/api/console/input',{'session':'codex','text':'test','request_id':'nonce1234'})
        ns['cc_codex_console'].send_input=mock.Mock(return_value=(True,'sent'))
        self.assertEqual(h.do_POST(),(200,{'ok':True,'message':'sent'}));ns['cc_codex_console'].send_input.assert_called_once_with('test')

    def test_quota_input_is_queued_once_and_not_sent_to_native_console(self):
        h,ns=self.fixture('/api/console/input',{'session':'codex','text':'waiting task','request_id':'quota-req-1'})
        ns['FLEET_ROTATION'].accounts=[account('gpt1',session=94)]
        ns['cc_codex_console'].send_input=mock.Mock()
        self.assertEqual(h.do_POST(),(200,{'ok':True,'message':'queued'}))
        ns['cc_codex_bridge'].BRIDGE.enqueue_console.assert_called_once_with('waiting task','quota-req-1')
        ns['cc_codex_console'].send_input.assert_not_called()


if __name__=='__main__':unittest.main()
