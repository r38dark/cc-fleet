"""Actual JSONL reader and Bridge, with local media preparation and no external API/model."""
import json
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
import cc_codex_bridge as B
import cc_codex_console as C
import test_cc_telegram_live as fixtures


class LiveMedia(unittest.TestCase):
    append=fixtures.LiveInput.append
    paste=fixtures.LiveInput.paste
    finish=fixtures.LiveInput.finish
    wait=fixtures.LiveInput.wait
    send=fixtures.LiveInput.send

    def setUp(self):
        fixtures.LiveInput.setUp(self)
        self.downloads=[];self.gates={};self.fail_ids=set();self.created=set()
        self.patch=mock.patch.object(B,'fetch_image',side_effect=self.fetch);self.patch.start();self.addCleanup(self.patch.stop)
        self.albums=mock.patch.object(B,'ALBUM_WAIT',.04);self.albums.start();self.addCleanup(self.albums.stop)
        self.addCleanup(self.stop_worker)  # stop preparers before media mocks are restored

    def stop_worker(self):
        for gate in self.gates.values():gate.set()
        self.bridge._cancel_inputs()
        fixtures.LiveInput.stop_worker(self)
        for thread in self.bridge.inputs._threads:thread.join(1)
        if self.bridge.notice_worker:self.bridge.notice_worker.join(1)

    def fetch(self,s,fid,**kwargs):
        self.downloads.append((fid,time.monotonic()))
        if fid in self.gates:self.gates[fid].wait(1)
        if fid in self.fail_ids:raise B.ImageError('Фото недоступно')
        p=self.root/(fid+'.png');p.write_bytes(b'\x89PNG\r\n\x1a\nfixture');self.created.add(fid);return str(p)

    def start_turn(self):
        self.send('first');self.wait(lambda:len(self.inputs)==1)

    def done(self,text='answer',turn=None):
        def ack_written():
            with self.file_lock:
                rows=[json.loads(line) for line in self.path.read_text().splitlines()]
            return sum((row.get('payload') or {}).get('role')=='user' for row in rows)>=len(self.inputs)
        self.wait(ack_written)
        worker=self.bridge.worker;self.finish(text,turn);worker.join(2)
        self.assertEqual(self.answers[-1],text)

    def test_photo_and_text_enter_before_current_turn_finishes(self):
        self.start_turn();start=time.monotonic();self.bridge.handle_image(['one'],'photo');self.send('followup')
        self.wait(lambda:len(self.inputs)==3)
        self.assertLess(self.inputs[-1][1]-start,.3)
        self.assertIn('one.png',self.inputs[1][0]);self.assertEqual(self.inputs[2][0],'followup')
        self.assertEqual(self.answers,[]);self.assertTrue(C.current_turn_open())
        self.done();C.ensure.assert_called_once()

    def test_photo_is_prepared_even_while_dispatch_paused(self):
        B.DISPATCH_ALLOWED.return_value=False
        self.bridge.handle_image(['one'],'photo');self.wait(lambda:len(self.downloads)==1)
        self.assertEqual(self.inputs,[])
        B.DISPATCH_ALLOWED.return_value=True;self.wait(lambda:len(self.inputs)==1);self.done()

    def test_slow_photo_preserves_order_without_blocking_native_reader(self):
        self.start_turn();self.gates['one']=threading.Event()
        self.bridge.handle_image(['one'],'photo');self.send('later')
        self.wait(lambda:len(self.downloads)==1);time.sleep(.03)
        self.assertEqual(len(self.inputs),1)
        start=time.monotonic();self.assertEqual(self.bridge.take_live_texts(1),[])
        self.assertLess(time.monotonic()-start,.05)
        self.gates['one'].set();self.wait(lambda:len(self.inputs)==3)
        self.assertIn('one.png',self.inputs[1][0]);self.assertEqual(self.inputs[2][0],'later');self.done()

    def test_out_of_order_downloads_are_delivered_in_receipt_order(self):
        self.start_turn();self.gates['slow']=threading.Event()
        self.bridge.handle_image(['slow'],'slow');self.bridge.handle_image(['fast'],'fast')
        self.wait(lambda:(self.root/'fast.png').exists());self.assertEqual(len(self.inputs),1)
        self.gates['slow'].set();self.wait(lambda:len(self.inputs)==3)
        self.assertIn('slow.png',self.inputs[1][0]);self.assertIn('fast.png',self.inputs[2][0]);self.done()

    def test_album_is_atomic_and_keeps_first_frame_position(self):
        self.start_turn();self.bridge.collect_album('group','one','album')
        self.send('after album');self.bridge.collect_album('group','two','')
        self.wait(lambda:len(self.inputs)==3)
        self.assertIn('one.png',self.inputs[1][0]);self.assertIn('two.png',self.inputs[1][0])
        self.assertEqual(self.inputs[2][0],'after album');self.done()

    def test_stale_album_timer_cannot_flush_new_frames(self):
        self.start_turn();self.bridge.collect_album('g','one','album')
        old=self.bridge.albums['g']['timer_token']
        self.bridge.collect_album('g','two','');self.bridge.flush_album('g',old)
        self.assertIn('g',self.bridge.albums)
        self.wait(lambda:len(self.inputs)==2);self.assertIn('two.png',self.inputs[1][0]);self.done()

    def test_failure_is_explicit_and_following_text_continues(self):
        self.start_turn();self.fail_ids.add('bad')
        self.bridge.handle_image(['bad'],'caption');self.send('after error')
        self.wait(lambda:len(self.inputs)==2 and len(self.notices)==1)
        self.assertEqual(self.inputs[1][0],'after error');self.assertIn('Фото недоступно',self.notices[0]);self.done()

    def test_partial_album_is_deleted_and_never_passed_to_model(self):
        self.start_turn();self.fail_ids.add('bad')
        self.bridge.handle_image(['one','bad'],'album');self.send('continue')
        self.wait(lambda:len(self.inputs)==2 and bool(self.notices))
        self.assertFalse((self.root/'one.png').exists())
        self.assertEqual(self.inputs[1][0],'continue');self.assertIn('Фото 2 из 2',self.notices[0]);self.done()

    def test_stop_cancels_download_and_no_late_photo_is_injected(self):
        self.start_turn();self.gates['late']=threading.Event()
        self.bridge.handle_image(['late'],'old photo');self.send('old text')
        self.wait(lambda:len(self.downloads)==1);worker=self.bridge.worker
        self.send('/stop');worker.join(1);self.gates['late'].set()
        self.wait(lambda:'late' in self.created and not (self.root/'late.png').exists() and not self.bridge.work_queue)
        time.sleep(.03);self.assertEqual(len(self.inputs),1)
        self.assertEqual(self.answers,[])

    def test_album_stop_does_not_allow_old_timer_to_touch_new_album(self):
        B.DISPATCH_ALLOWED.return_value=False
        self.bridge.collect_album('g','old','old');old=self.bridge.albums['g']['timer_token']
        self.bridge._cancel_inputs();self.bridge.collect_album('g','new','new')
        self.bridge.flush_album('g',old)
        self.assertIn('g',self.bridge.albums)
        B.DISPATCH_ALLOWED.return_value=True;self.wait(lambda:len(self.inputs)==1)
        self.assertIn('new.png',self.inputs[0][0]);self.assertNotIn('old.png',self.inputs[0][0]);self.done()

    def test_photo_can_steer_a_console_originated_turn(self):
        self.append(dict(type='task_started',turn_id=self.turn))
        self.bridge.handle_image(['one'],'from Telegram')
        self.wait(lambda:len(self.inputs)==1)
        C.ensure.assert_not_called();self.done()

    def test_image_caption_stop_is_content_not_a_bridge_command(self):
        self.start_turn();self.bridge.handle_image(['one'],'/stop')
        self.wait(lambda:len(self.inputs)==2)
        self.assertIn('/stop',self.inputs[1][0]);C.interrupt.assert_not_called();self.done()

    def test_new_conversation_cancels_pending_media_before_forgetting_thread(self):
        self.start_turn();self.gates['late']=threading.Event()
        self.bridge.handle_image(['late'],'old conversation');self.wait(lambda:bool(self.downloads))
        worker=self.bridge.worker
        with mock.patch.object(C,'forget') as forget:
            self.send('/new');forget.assert_called_once()
        worker.join(1);self.gates['late'].set()
        self.wait(lambda:'late' in self.created and not (self.root/'late.png').exists())
        self.assertEqual(len(self.inputs),1);self.assertFalse((self.root/'late.png').exists())

    def test_background_photo_does_not_replace_active_typing_indicator(self):
        self.start_turn();self.gates['one']=threading.Event()
        self.bridge.handle_image(['one'],'background');self.wait(lambda:bool(self.downloads))
        actions=[call.args[0] for call in B.ChatAction.return_value.start.call_args_list]
        self.assertEqual(actions,['typing'])
        self.gates['one'].set();self.wait(lambda:len(self.inputs)==2);self.done()

    def test_photo_arriving_at_final_boundary_cannot_get_old_answer(self):
        self.start_turn()
        def boundary(text):
            self.finish('old')
            self.inputs.append((text,time.monotonic()))
            self.append(dict(type='task_started',turn_id='T2'),
                        dict(type='message',role='user',content=[dict(type='input_text',text=text)]))
            self.finish('new',turn='T2');return True
        C._paste.side_effect=boundary;self.bridge.handle_image(['one'],'at boundary')
        self.wait(lambda:self.answers==['new'])

    def test_completion_while_photo_loads_returns_old_answer_then_same_conversation(self):
        self.start_turn();self.gates['one']=threading.Event()
        self.bridge.handle_image(['one'],'later')
        self.wait(lambda:bool(self.downloads));self.finish('first answer')
        self.wait(lambda:self.answers==['first answer'])
        self.turn='T2';self.gates['one'].set();self.wait(lambda:len(self.inputs)==2)
        # A real TUI starts a fresh turn after accepting input at its prompt.
        self.append(dict(type='task_started',turn_id='T2'))
        self.done('photo answer',turn='T2')
        self.assertEqual(self.answers,['first answer','photo answer'])
        self.assertEqual(C.active_settings()['thread_id'],'11111111-2222-4333-8444-555555555555')

    def test_media_deadline_releases_next_text_and_late_result_is_cleaned(self):
        self.start_turn();self.gates['late']=threading.Event()
        self.bridge.handle_image(['late'],'slow')
        self.wait(lambda:bool(self.downloads))
        self.bridge.inputs.items[0].deadline=time.monotonic()+.02
        self.send('after timeout');self.wait(lambda:len(self.inputs)==2 and bool(self.notices))
        self.assertEqual(self.inputs[1][0],'after timeout')
        self.gates['late'].set()
        self.wait(lambda:'late' in self.created and not (self.root/'late.png').exists())
        self.assertFalse((self.root/'late.png').exists());self.done()


if __name__=='__main__':unittest.main()
