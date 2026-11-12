import datetime
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import cc_codex_quota as Q
import cc_codex_rotation as R
import cc_codex_bridge as B
import cc_profiles
from cc_input_queue import InputQueue


def account(session=94,week=15):
    now=time.time();iso=lambda t:datetime.datetime.fromtimestamp(t,datetime.timezone.utc).isoformat()
    return dict(slot='a',ts=now,windows=[dict(mins=300,pct=session,resets_at=iso(now+600)),dict(mins=10080,pct=week,resets_at=iso(now+86400))])


class Policy(unittest.TestCase):
    def rotation(self,row):
        r=R.Rotation.__new__(R.Rotation);r.lock=threading.RLock();r.state=dict(optimize=True,threshold=90,weekly_cap=99)
        r.accounts=[row];r.active=lambda:'a';r.codex=SimpleNamespace(profile_slots=lambda:['a']);r.save=Mock()
        return r

    def test_single_90_is_held_and_89_is_not(self):
        self.assertTrue(self.rotation(account(90)).limit_pause()['active'])
        self.assertFalse(self.rotation(account(89)).limit_pause()['active'])

    def test_99_override_on_off_100_and_reset(self):
        r=self.rotation(account(20,99))
        self.assertTrue(r.limit_pause()['active'])
        self.assertTrue(r.configure({'pause_override':True})[0]);self.assertFalse(r.limit_pause()['active'])
        n=r.limit_notice();self.assertTrue(n['policy']);self.assertTrue(n['override']);self.assertFalse(n['paused'])
        self.assertTrue(r.configure({'pause_override':False})[0]);self.assertTrue(r.limit_pause()['active'])
        self.assertTrue(r.configure({'pause_override':True})[0]);r.accounts=[account(20,100)]
        self.assertTrue(r.limit_pause()['active']);self.assertTrue(r.limit_notice()['hard'])
        self.assertFalse(r.configure({'pause_override':True})[0])
        r.accounts=[account(20,0)];self.assertFalse(r.limit_pause()['active']);self.assertFalse(r.state['pause_override'])

    def test_both_windows_have_distinct_resets(self):
        r=self.rotation(account(90,99));p=r.limit_pause()
        self.assertEqual(p['windows'],[300,10080]);self.assertLess(p['resets']['300'],p['resets']['10080'])
        self.assertEqual(p['percentages'],{'300':90,'10080':99})

    def test_unknown_reset_is_not_invented(self):
        a=account();a['windows'][0]['resets_at']=None
        self.assertIsNone(self.rotation(a).limit_pause()['resume_at'])


class PersistentQueue(unittest.TestCase):
    def test_waiting_texts_survive_restart_and_keep_order(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'queue.json';q=InputQueue();q.attach_journal(path)
            q.reserve('text',dict(quota_wait=True),text='first');q.reserve('console',text='second')
            self.assertEqual(q.take_ready(predicate=lambda e:not e.delivery.get('quota_wait')),[])
            q.close(preserve=True)
            restored=InputQueue();restored.attach_journal(path)
            self.assertEqual([e.text for e in restored.take_ready(2)],['first','second'])
            self.assertEqual(Q.read(path),[]);self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_stop_clears_saved_queue_and_atomic_failure_keeps_old_data(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'queue.json';q=InputQueue();q.attach_journal(path);q.reserve('text',text='kept')
            old=path.read_bytes()
            with patch('cc_input_queue.atomic',side_effect=OSError('fixture disk failure')):
                with self.assertRaises(OSError):q.reserve('text',text='not accepted')
            self.assertEqual(path.read_bytes(),old);self.assertEqual(len(q),1)
            q.clear();self.assertEqual(Q.read(path),[])

    def test_paused_inputs_do_not_steer_the_running_turn(self):
        b=B.Bridge();b._ensure_worker=lambda:False;b._notice_async=Mock()
        with patch.object(B,'LIMIT_PAUSE',return_value=dict(active=True)):
            b._reserve_input('text',text='next task');self.assertEqual(b.take_live_texts(),[])
        with patch.object(B,'LIMIT_PAUSE',return_value=dict(active=False)):
            self.assertEqual(b.take_live_texts(),[])
            self.assertEqual(b.inputs.take_ready()[0].text,'next task')

    def test_console_jobs_are_distinguished_from_telegram_and_deduplicated(self):
        b=B.Bridge();b._ensure_worker=lambda:False;b._notice_async=Mock()
        with patch.object(B,'LIMIT_PAUSE',return_value=dict(active=True)):
            self.assertTrue(b.enqueue_console('console task','request-123')[0])
            self.assertTrue(b.enqueue_console('console task','request-123')[0])
        self.assertEqual(len(b.inputs),1);entry=b.inputs.take_ready()[0]
        self.assertEqual(entry.kind,'console');self.assertEqual(entry.delivery['source'],'console')


class NativePause(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        code="import ctypes,time;ctypes.CDLL(None).prctl(15,b'codex',0,0,0);time.sleep(60)"
        self.child=subprocess.Popen([sys.executable,'-c',code])
        end=time.monotonic()+3
        while time.monotonic()<end:
            if Path('/proc/%d/comm'%self.child.pid).read_text().strip()=='codex':break
            time.sleep(.01)
        self.bridge=SimpleNamespace(inputs=InputQueue(),_notice_async=Mock())
        self.point={'turn':'installation-turn'}
        self.console=SimpleNamespace(_pid=lambda:self.child.pid,PAUSED=lambda:False,mark=lambda:self.point)
        self.pause=dict(active=True,resume_at=time.time()+600,windows=[300],hard=False)
        self.rotation=SimpleNamespace(limit_pause=lambda:self.pause)
        self.guard=Q.Guard(self.base,self.rotation,self.console,self.bridge)

    def tearDown(self):
        if self.child.poll() is None:
            self.child.send_signal(signal.SIGCONT);self.child.terminate();self.child.wait(3)
        self.tmp.cleanup()

    def wait_state(self, stopped):
        end=time.monotonic()+2
        while time.monotonic()<end:
            if ((Q.identity(self.child.pid) or {}).get('state')=='T')==stopped:return
            time.sleep(.01)
        self.fail('Inert process did not change state')

    def test_real_stop_continue_preserves_pid_and_process_start(self):
        before=Q.identity(self.child.pid);self.guard.tick();self.wait_state(True)
        self.assertTrue(self.guard.public()['frozen']);self.guard.tick();self.assertEqual(self.bridge._notice_async.call_count,1)
        self.pause={'active':False};self.guard.tick();self.wait_state(False)
        after=Q.identity(self.child.pid);self.assertEqual(before['start'],after['start']);self.assertEqual(before['pid'],after['pid'])

    def test_profile_and_quota_pause_do_not_release_each_other(self):
        self.guard.tick();self.wait_state(True)
        native=cc_profiles.NativeProfiles.__new__(cc_profiles.NativeProfiles);native.base=self.base
        row=Q.read(self.guard.marker)
        profile=self.base/'profile_runtime/codex-paused.json';Q.atomic(profile,row)
        native._codex_pause(False);self.wait_state(True)
        Q.atomic(profile,row);self.pause={'active':False};self.guard.tick();self.wait_state(True)
        native._codex_pause(False);self.wait_state(False)

    def test_installation_grace_is_bound_to_one_existing_turn(self):
        Q.atomic(self.guard.grace,dict(turn='installation-turn',screen_pid=self.child.pid))
        self.guard.tick();self.wait_state(False);self.assertTrue(self.guard.finishing)
        self.point={};self.guard.tick();self.wait_state(True);self.assertFalse(self.guard.finishing)

    def test_restart_with_unknown_snapshot_keeps_existing_pause(self):
        self.guard.tick();self.wait_state(True)
        restarted=Q.Guard(self.base,self.rotation,self.console,self.bridge)
        self.assertTrue(restarted.fallback(dict(active=False,unknown=True))['active'])
        self.pause=dict(active=False,unknown=True);restarted.tick();self.wait_state(True)

    def test_stale_pid_marker_does_not_stop_unrelated_process(self):
        Q.atomic(self.guard.marker,[dict(pid=self.child.pid,start='wrong-start')]);self.console._pid=lambda:None
        self.guard.tick();self.wait_state(False)


if __name__=='__main__':unittest.main()
