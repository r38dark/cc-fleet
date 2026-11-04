import tempfile
import threading
import time
import unittest
from pathlib import Path
from cc_input_queue import InputQueue


class OrderedInputs(unittest.TestCase):
    def setUp(self):
        self.gates = []
        self.deleted = []
        self.q = InputQueue(limit=4, timeout=.3, cleanup=lambda files: self.deleted.extend(files))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for gate in self.gates: gate.set()
        self.q.close()
        for thread in self.q._threads: thread.join(1)
        self.assertFalse(any(t.is_alive() for t in self.q._threads))

    def wait(self, predicate):
        end = time.monotonic()+1
        while not predicate() and time.monotonic()<end: time.sleep(.002)
        self.assertTrue(predicate())

    def hold(self):
        gate = threading.Event(); self.gates.append(gate); return gate

    def test_ready_text_cannot_overtake_preparing_photo(self):
        gate=self.hold(); first=self.q.reserve('image')
        self.q.prepare(first, lambda _: (gate.wait(1), ('photo', ['file']))[1])
        self.q.reserve('text', text='later')
        start=time.monotonic();self.assertEqual(self.q.take_ready(2),[])
        self.assertLess(time.monotonic()-start,.05)
        gate.set();self.wait(lambda:first.state=='ready')
        self.assertEqual([e.text for e in self.q.take_ready(2)],['photo','later'])

    def test_second_download_may_finish_first_without_reordering(self):
        gate=self.hold(); first=self.q.reserve('image'); second=self.q.reserve('image')
        self.q.prepare(first,lambda _: (gate.wait(1),('first',[]))[1])
        self.q.prepare(second,lambda _: ('second',[]))
        self.wait(lambda:second.state=='ready');self.assertEqual(self.q.take_ready(2),[])
        gate.set();self.wait(lambda:first.state=='ready')
        self.assertEqual([e.text for e in self.q.take_ready(2)],['first','second'])

    def test_download_concurrency_is_bounded(self):
        gate=self.hold();lock=threading.Lock();active=[0];peak=[0]
        def prepare(_):
            with lock:active[0]+=1;peak[0]=max(peak[0],active[0])
            gate.wait(1)
            with lock:active[0]-=1
            return 'ready', []
        for _ in range(4): self.q.prepare(self.q.reserve('image'),prepare)
        self.wait(lambda:active[0]==2);self.assertEqual(peak[0],2)
        gate.set();self.wait(lambda:all(e.state=='ready' for e in self.q.items))
        self.assertEqual(peak[0],2)

    def test_clear_cannot_resurrect_late_prepared_photo(self):
        entered=self.hold();release=self.hold();entry=self.q.reserve('image')
        def prepare(_):entered.set();release.wait(1);return 'old', ['late-file']
        self.q.prepare(entry,prepare);self.assertTrue(entered.wait(1))
        self.q.clear();self.q.reserve('text', text='new')
        release.set();self.wait(lambda:'late-file' in self.deleted)
        self.assertEqual([e.text for e in self.q.take_ready(4)],['new'])

    def test_timeout_releases_later_text_and_drops_late_files(self):
        gate=self.hold();entry=self.q.reserve('image');entry.deadline=time.monotonic()+.03
        self.q.prepare(entry,lambda _:(gate.wait(1),('late',['late']))[1])
        self.q.reserve('text', text='next');time.sleep(.05)
        result=self.q.take_ready(2);self.assertTrue(result[0].error)
        self.assertEqual(result[1].text,'next');gate.set();self.wait(lambda:'late' in self.deleted)

    def test_collecting_album_reserves_position_before_it_is_sealed(self):
        album=self.q.reserve('image');self.q.reserve('text', text='after-album')
        self.assertEqual(self.q.take_ready(2),[])
        self.q.prepare(album,lambda _:('album',[]));self.wait(lambda:album.state=='ready')
        self.assertEqual([e.text for e in self.q.take_ready(2)],['album','after-album'])

    def test_failed_photo_does_not_block_next_message(self):
        class Failure(Exception): public_message='safe failure'
        def fail(_): raise Failure('https://token-must-not-be-printed')
        entry=self.q.reserve('image');self.q.prepare(entry,fail);self.q.reserve('text',text='next')
        self.wait(lambda:entry.state=='failed');ready=self.q.take_ready(2)
        self.assertEqual(ready[0].error,'safe failure');self.assertEqual(ready[1].text,'next')

    def test_unknown_error_hides_exception_details(self):
        def fail(_):raise ValueError('SECRET_URL')
        entry=self.q.reserve('image');self.q.prepare(entry,fail)
        self.wait(lambda:entry.state=='failed');self.assertNotIn('SECRET_URL',entry.error)

    def test_full_queue_and_closed_queue_reject_before_preparation(self):
        for _ in range(4):self.assertIsNotNone(self.q.reserve('text',text='x'))
        self.assertIsNone(self.q.reserve('image'));self.assertEqual(self.q._threads,[])
        self.q.close();self.assertIsNone(self.q.reserve('text',text='x'))

    def test_each_ready_entry_is_consumed_once(self):
        self.q.reserve('text',text='same');self.q.reserve('text',text='same')
        self.assertEqual([e.text for e in self.q.take_ready(4)],['same','same'])
        self.assertEqual(self.q.take_ready(4),[])

    def test_cancelled_album_cannot_be_sealed(self):
        entry=self.q.reserve('image');self.q.clear()
        self.assertFalse(self.q.prepare(entry,lambda _:('never',[])))
        self.assertEqual(self.q._threads,[])


if __name__=='__main__':unittest.main()
