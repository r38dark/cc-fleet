"""Настоящий reader JSONL и обработчик моста; screen/Telegram заменены локальными подделками."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import cc_codex_console as C
import cc_codex_bridge as B

TID='11111111-2222-4333-8444-555555555555'


class LiveInput(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.path=self.root/('rollout-test-'+TID+'.jsonl');self.path.write_text('')
        self.file_lock=threading.Lock();self.inputs=[];self.answers=[];self.notices=[];self.errors=[];self.turn='T1'
        self.bridge=B.Bridge();self.state={'pending':None,'threads':{},'tasks':{}}
        self.config=dict(mode='self',token='fake',chat_id='test',workdir=str(self.root),slot='gpt1')
        meta=dict(slot='gpt1',cwd=str(self.root),started=0,tids={str(self.root):TID})
        patches=[mock.patch.object(C,'_pid',return_value='test-native'),mock.patch.object(C,'_meta',return_value=meta),
          mock.patch.object(C,'active_settings',return_value=dict(thread_id=TID,rollout_path=str(self.path),model='unchanged-model',effort='high')),
          mock.patch.object(C,'ensure',return_value=(True,'')),mock.patch.object(C,'_wait_ready'),mock.patch.object(C,'_remember'),
          mock.patch.object(C,'_paste',side_effect=self.paste),mock.patch.object(C,'POLL',.005),mock.patch.object(C,'START_WAIT',.4),
          mock.patch.object(C,'INPUT_ALLOWED',return_value=True),mock.patch.object(C,'usable',return_value=True),
          mock.patch.object(C,'interrupt',return_value=True),mock.patch.object(B,'BRIDGE',self.bridge),mock.patch.object(B,'CONSOLE',C),
          mock.patch.object(B,'load',return_value=self.config),mock.patch.object(B,'_state',return_value=self.state),
          mock.patch.object(B,'_state_save'),mock.patch.object(B,'plan',return_value=('workspace-write',str(self.root))),
          mock.patch.object(B,'ChatAction'),mock.patch.object(B,'DISPATCH_ALLOWED',return_value=True),mock.patch.object(B,'log')]
        for patch in patches:patch.start();self.addCleanup(patch.stop)
        self.bridge.send=lambda text,s=None:self.notices.append(text)
        self.bridge.send_answer=lambda text,*args:self.answers.append(text)
        self.addCleanup(self.stop_worker)

    def append(self,*payloads):
        with self.file_lock,self.path.open('a') as stream:
            for p in payloads:
                kind=p.get('type');role=p.get('role')
                row=dict(timestamp='2026-11-03T00:00:00Z',type='response_item' if role else 'event_msg',payload=p)
                stream.write(json.dumps(row,ensure_ascii=False)+'\n')

    def paste(self,text):
        self.inputs.append((text,time.monotonic()))
        if len(self.inputs)==1 and not C._turn_open(self.path):self.append(dict(type='task_started',turn_id=self.turn))
        self.append(dict(type='message',role='user',content=[dict(type='input_text',text=text)]))
        return True

    def finish(self,text='единый ответ',turn=None):
        self.append(dict(type='message',role='assistant',channel='final',content=[dict(type='output_text',text=text)]),
                    dict(type='task_complete',turn_id=turn or self.turn))

    def wait(self,predicate,seconds=2):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:time.sleep(.005)
        self.assertTrue(predicate())

    def stop_worker(self):
        self.bridge.cancel.set()
        if self.bridge.worker:self.bridge.worker.join(2)
        self.bridge.inputs.close()
        self.assertFalse(self.bridge.worker and self.bridge.worker.is_alive())
        self.assertIsNone(C._live_request)

    def send(self,text):self.bridge.handle_text(text)

    def test_followups_reach_same_native_turn_before_it_finishes(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        sent=time.monotonic()
        self.send('уточнение 1');self.send('уточнение 2');self.send('уточнение 3')
        self.wait(lambda:len(self.inputs)==4)
        self.assertLess(self.inputs[-1][1]-sent,.25)
        self.assertEqual([v[0] for v in self.inputs],['первое','уточнение 1','уточнение 2','уточнение 3'])
        self.assertTrue(self.bridge.worker.is_alive());self.assertEqual(self.answers,[]);self.assertEqual(self.notices,[])
        self.finish();self.bridge.worker.join(2);self.assertEqual(self.answers,['единый ответ']);C.ensure.assert_called_once()

    def test_telegram_can_steer_a_turn_started_from_the_console(self):
        self.append(dict(type='task_started',turn_id=self.turn));self.send('из Telegram во время работы в терминале')
        self.wait(lambda:len(self.inputs)==1);C.ensure.assert_not_called()
        self.finish();self.bridge.worker.join(2);self.assertEqual(self.answers,['единый ответ'])

    def test_quota_wait_excludes_timeout_and_keeps_next_task_until_current_finishes(self):
        held=threading.Event()
        with mock.patch.object(C,'QUOTA_PAUSE',side_effect=lambda:{'active':held.is_set()}),mock.patch.object(B,'LIMIT_PAUSE',side_effect=lambda:{'active':held.is_set()}),mock.patch.object(C,'START_WAIT',.04):
            self.send('first task');self.wait(lambda:len(self.inputs)==1)
            held.set();self.send('next task');time.sleep(.15)
            self.assertEqual(len(self.inputs),1);self.assertTrue(self.bridge.worker.is_alive());self.assertFalse(self.errors)
            held.clear();time.sleep(.03);self.assertEqual(len(self.inputs),1)
            def next_turn(text):
                self.turn='T2';self.append(dict(type='task_started',turn_id='T2'));return self.paste(text)
            C._paste.side_effect=next_turn
            self.finish('first answer',turn='T1');self.wait(lambda:len(self.inputs)==2)
            self.finish('second answer',turn='T2');self.bridge.worker.join(2)
            self.assertEqual(self.answers,['first answer','second answer'])

    def test_recovery_waits_through_quota_pause_before_task_started(self):
        held=threading.Event();held.set();result=[];abort=threading.Event()
        def recover():result.append(C.recover(dict(path=str(self.path),off=0,turn=None),time.time(),abort=abort))
        with mock.patch.object(C,'QUOTA_PAUSE',side_effect=lambda:{'active':held.is_set()}),mock.patch.object(C,'START_WAIT',.04):
            worker=threading.Thread(target=recover);worker.start()
            try:
                time.sleep(.15);self.assertTrue(worker.is_alive())
                self.append(dict(type='task_started',turn_id='T1'));self.finish('recovered')
                held.clear();worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual(result[0][0],'recovered')
            finally:abort.set();worker.join(1)

    def test_messages_received_during_console_preparation_are_promoted(self):
        entered,release=threading.Event(),threading.Event()
        C.ensure.side_effect=lambda *args:(entered.set(),release.wait(1),(True,''))[-1]
        self.send('первое');self.assertTrue(entered.wait(1));self.send('при запуске');release.set()
        self.wait(lambda:len(self.inputs)==2);self.assertEqual(self.inputs[1][0],'при запуске')
        self.finish();self.bridge.worker.join(2);self.assertEqual(self.answers,['единый ответ'])

    def test_finish_boundary_uses_new_reply_instead_of_previous_final(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        def boundary(text):
            self.finish('предыдущий ответ')
            self.inputs.append((text,time.monotonic()))
            self.turn='T2';self.append(dict(type='task_started',turn_id='T2'),dict(type='message',role='user',content=[dict(type='input_text',text=text)]))
            self.finish('ответ на уточнение')
            return True
        C._paste.side_effect=boundary;self.send('ещё уточнение');self.bridge.worker.join(2)
        self.assertEqual(self.answers,['ответ на уточнение']);self.assertEqual(self.notices,[])

    def test_old_final_before_user_ack_cannot_be_returned_as_its_answer(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        def boundary(text):
            self.inputs.append((text,time.monotonic()))
            self.finish('старый ответ')
            self.append(dict(type='message',role='user',content=[dict(type='input_text',text=text)]),dict(type='task_started',turn_id='T2'))
            self.finish('новый ответ',turn='T2');return True
        C._paste.side_effect=boundary;self.send('на границе');self.bridge.worker.join(2)
        self.assertEqual(self.answers,['новый ответ'])

    def test_ack_between_old_final_and_completion_waits_for_next_turn(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        def boundary(text):
            self.inputs.append((text,time.monotonic()))
            self.append(dict(type='message',role='assistant',channel='final',content=[dict(type='output_text',text='старый ответ')]),
                        dict(type='message',role='user',content=[dict(type='input_text',text=text)]),dict(type='task_complete',turn_id='T1'))
            return True
        C._paste.side_effect=boundary;self.send('уточнение');self.wait(lambda:len(self.inputs)==2)
        time.sleep(.03);self.assertEqual(self.answers,[]);self.assertTrue(self.bridge.worker.is_alive())
        self.append(dict(type='task_started',turn_id='T2'));self.finish('новый ответ',turn='T2');self.bridge.worker.join(2)
        self.assertEqual(self.answers,['новый ответ'])

    def test_identical_followups_are_distinct_messages(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        self.send('ещё');self.send('ещё');self.wait(lambda:len(self.inputs)==3)
        self.finish();self.bridge.worker.join(2);self.assertEqual(self.answers,['единый ответ'])

    def test_stop_clears_pending_followups(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        B.DISPATCH_ALLOWED.return_value=False
        self.send('не отправлять 1');self.send('не отправлять 2');self.send('/stop');self.bridge.worker.join(2)
        self.assertEqual(len(self.inputs),1);self.assertEqual(self.bridge.work_queue,[]);self.assertEqual(self.answers,[])
        self.assertFalse(self.bridge.worker and self.bridge.worker.is_alive())

    def test_stop_clears_unsubmitted_inputs_without_second_reply(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        self.send('/stop');self.bridge.worker.join(2)
        self.assertEqual(self.answers,[]);self.assertTrue(any('Остановил' in s for s in self.notices));C.interrupt.assert_called_once()

    def test_collapsed_blank_line_in_photo_prompt_is_acknowledged(self):
        def transport(text):
            self.inputs.append((text,time.monotonic()))
            self.append(dict(type='task_started',turn_id=self.turn),
                        dict(type='message',role='user',content=[dict(type='input_text',text=text.replace('\n\n','\n'))]))
            return True
        C._paste.side_effect=transport
        self.send('Исправь отступ\n\n[Вложения из Telegram: изображения лежат на сервере.\n/tmp/demo.jpg]')
        self.wait(lambda:len(self.inputs)==1);time.sleep(.5)
        self.assertTrue(self.bridge.worker.is_alive());self.assertEqual(self.notices,[])
        worker=self.bridge.worker
        self.finish('исправлено');worker.join(2);self.assertEqual(self.answers,['исправлено'])

    def test_different_indentation_does_not_ack_another_message(self):
        def transport(text):
            self.inputs.append((text,time.monotonic()))
            self.append(dict(type='task_started',turn_id=self.turn),
                        dict(type='message',role='user',content=[dict(type='input_text',text=text.replace('    return','return'))]))
            return True
        C._paste.side_effect=transport;self.send('def sample():\n    return 1');self.bridge.worker.join(2)
        self.assertEqual(self.answers,[]);self.assertTrue(any('подтверждение' in value for value in self.notices))

    def test_missing_ack_does_not_type_or_send_enter_twice(self):
        C._paste.side_effect=lambda text:(self.inputs.append((text,time.monotonic())),True)[1]
        self.send('неподтверждённое');self.bridge.worker.join(2)
        self.assertEqual(len(self.inputs),1);self.assertEqual(self.answers,[])
        self.assertTrue(any('подтверждение' in s and 'перед повтором' in s for s in self.notices))

    def test_stop_after_dequeue_before_console_start_is_not_lost(self):
        entered,release=threading.Event(),threading.Event();run=B.run_codex
        def delayed(*args):entered.set();release.wait(1);return run(*args)
        with mock.patch.object(B,'run_codex',side_effect=delayed):
            self.send('не начинать');self.assertTrue(entered.wait(1));self.send('/stop');release.set();self.bridge.worker.join(2)
        self.assertEqual(self.inputs,[]);self.assertEqual(self.answers,[])
        self.assertTrue(any('Остановил' in s for s in self.notices));C.ensure.assert_not_called()

    def test_close_or_cancel_does_not_leave_live_reader(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        C._pid.return_value=None;self.bridge.worker.join(2)
        self.assertTrue(any('закрылась' in s for s in self.notices));self.assertIsNone(C._live_request)

    def test_reader_ignores_child_completion_and_commentary(self):
        self.send('первое');self.wait(lambda:len(self.inputs)==1)
        self.append(dict(type='task_complete',turn_id='child'),dict(type='message',role='assistant',channel='commentary',content=[dict(type='output_text',text='прогресс')]))
        time.sleep(.025);self.assertEqual(self.answers,[])
        self.finish();self.bridge.worker.join(2);self.assertEqual(self.answers,['единый ответ'])

    def test_generation_and_pause_prevent_dispatch(self):
        old=self.bridge.inputs.reserve('text', text='старое');old.generation=999
        self.bridge.inputs.reserve('text', text='новое')
        B.DISPATCH_ALLOWED.return_value=False;self.assertEqual(self.bridge.take_live_texts(),[])
        B.DISPATCH_ALLOWED.return_value=True;self.assertEqual(self.bridge.take_live_texts(),['новое'])

    def test_queue_notice_is_removed_for_both_text_and_photo(self):
        self.bridge.enqueue_work=mock.Mock(return_value=(True,3))
        self.send('сообщение');self.bridge.handle_image(['fake-file'],'подпись')
        self.assertEqual(self.notices,[])


if __name__=='__main__':unittest.main()
