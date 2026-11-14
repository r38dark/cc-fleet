# Кнопка «Перерисовать консоль» (вкладка Claude DEV): настоящий ресайз pty окна сессии cols -> cols-1 -> cols.
# python3 -m unittest test_cc_console_redraw -v
# Настоящий pty из пары openpty(): живая screen-сессия и /opt/cc-limits не затрагиваются.
import fcntl
import io
import json
import os
import pty
import struct
import tempfile
import termios
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="ccredraw_")
os.environ.setdefault("CC_LIMITS_BASE", os.path.join(TMP, "base"))
os.environ.setdefault("CC_LIMITS_PROFILES", os.path.join(TMP, "profiles"))
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)

import cc_limits as L  # noqa: E402


def size(fd):
    return struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0)))[:2]


def put(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class Redraw(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        self.path = os.ttyname(self.slave)
        put(self.slave, 30, 100)
        self.seen = []     # размер окна в момент «паузы» (пока Claude Code перестраивает кадр)
        self.sleeps = []

        def fake_sleep(sec):
            self.sleeps.append(sec)
            self.seen.append(size(self.slave))
        for target, name, value in (
                (L, '_current_screen_pid', lambda scr: '4242'),
                (L, '_console_window_pty', lambda pid: self.path),
                (L.time, 'sleep', fake_sleep)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_window_is_narrowed_by_one_column_and_then_restored_exactly(self):
        ok, msg = L.redraw_console()
        self.assertTrue(ok, msg)
        self.assertEqual(self.seen, [(30, 99)])      # на паузе: на колонку уже, строки те же
        self.assertEqual(size(self.slave), (30, 100))  # после: ровно как было
        self.assertEqual(self.sleeps, [L.REDRAW_HOLD])

    def test_size_is_restored_even_when_the_pause_blows_up(self):
        with mock.patch.object(L.time, 'sleep', side_effect=RuntimeError('boom')):
            ok, msg = L.redraw_console()
        self.assertFalse(ok)
        self.assertEqual(size(self.slave), (30, 100))   # окно не остаётся суженным

    def test_no_session_or_no_pty_touches_nothing(self):
        with mock.patch.object(L, '_console_window_pty', lambda pid: None):
            ok, msg = L.redraw_console()
        self.assertFalse(ok)
        self.assertIn('не запущена', msg)
        self.assertEqual((self.seen, size(self.slave)), ([], (30, 100)))

    def test_tiny_window_is_left_alone(self):
        put(self.slave, 3, 15)
        ok, msg = L.redraw_console()
        self.assertFalse(ok)
        self.assertEqual((self.seen, size(self.slave)), ([], (3, 15)))

    def test_second_click_during_a_redraw_is_refused(self):
        self.assertTrue(L._redraw_lock.acquire(blocking=False))
        try:
            ok, msg = L.redraw_console()
        finally:
            L._redraw_lock.release()
        self.assertFalse(ok)
        self.assertIn('уже идёт', msg)
        self.assertEqual(self.seen, [])
        self.assertTrue(L.redraw_console()[0])   # замок отпущен: следующий клик работает

    def test_english_message_and_lock_released_after_failure(self):
        with mock.patch.object(L, '_console_window_pty', lambda pid: None):
            ok, msg = L.redraw_console('en')
        self.assertFalse(ok)
        self.assertIn('not running', msg)
        self.assertTrue(L._redraw_lock.acquire(blocking=False))   # замок не остался занятым
        L._redraw_lock.release()


class Route(unittest.TestCase):
    """Настоящий H.do_POST: cmd=redraw идёт в redraw_console и не вводит ничего в сессию (не slash-команда)."""

    def post(self, body):
        h = L.H.__new__(L.H)
        raw = json.dumps(body).encode()
        h.path = '/api/session'
        h.headers = {'Content-Length': str(len(raw))}
        h.rfile = io.BytesIO(raw)
        sent = []
        h._authed = lambda: True
        h._send = lambda code, data, ctype=None: sent.append((code, data))
        h.do_POST()
        return sent

    def test_redraw_goes_to_the_pty_resize_and_never_to_screen_stuff(self):
        with mock.patch.object(L, 'redraw_console', return_value=(True, 'готово')) as rd, \
                mock.patch.object(L, 'send_session_command') as ss:
            sent = self.post({'cmd': 'redraw', 'lang': 'en'})
        self.assertEqual(sent, [(200, {'ok': True, 'message': 'готово'})])
        rd.assert_called_once_with('en')
        ss.assert_not_called()

    def test_failed_redraw_answers_400_with_the_message(self):
        with mock.patch.object(L, 'redraw_console', return_value=(False, 'нет сессии')):
            sent = self.post({'cmd': 'redraw'})
        self.assertEqual(sent, [(400, {'ok': False, 'message': 'нет сессии'})])

    def test_compact_and_new_still_use_the_slash_commands(self):
        with mock.patch.object(L, 'redraw_console') as rd, \
                mock.patch.object(L, 'send_session_command', return_value=(True, 'ок')) as ss:
            self.post({'cmd': 'compact'})
        ss.assert_called_once_with('compact')
        rd.assert_not_called()
        self.assertNotIn('redraw', L.SESSION_COMMANDS)   # «redraw» нельзя превратить в ввод в сессию


class Page(unittest.TestCase):
    def test_button_is_last_in_the_acts_row_and_only_on_the_claude_dev_tab(self):
        page = L.PAGE
        acts = page[page.index('<span class="ctacts">'):page.index('</span></div>', page.index('<span class="ctacts">'))]
        self.assertLess(acts.index('id="ctCompact"'), acts.index('id="ctNew"'))
        self.assertLess(acts.index('id="ctNew"'), acts.index('id="ctRedraw"'))   # места «Сжать» и «Новая сессия» не сдвигаются
        self.assertIn("$('#ctRedraw').hidden=k!=='claude'", page)                 # PROD и Codex так не перерисовать
        self.assertIn("cmd:'redraw'", page)
        self.assertIn("$('#ctRedraw').addEventListener('click',consRedraw)", page)

    def test_redraw_does_not_reuse_the_new_session_button(self):
        page = L.PAGE
        body = page[page.index('async function consRedraw'):page.index("$('#ctRedraw').addEventListener")]
        self.assertNotIn("'new'", body)    # ↻ (ctNew) = /clear: для перерисовки её нельзя ни звать, ни советовать
        self.assertNotIn('confirm(', body)

    def test_title_exists_in_both_languages(self):
        self.assertEqual(L.PAGE.count('redrawTitle:'), 2)


if __name__ == '__main__':
    unittest.main()
