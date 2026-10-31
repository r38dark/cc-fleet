# Консоль Codex: запуск/останов, зеркало экрана из лога screen, маршруты /api/console?s=codex и вкладки на странице.
# python3 -m unittest test_cc_codex_console -v
import json
import os
import re
import tempfile
import threading
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="cccxcon_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_codex  # noqa: E402
import cc_codex_console as C  # noqa: E402
import cc_limits as L  # noqa: E402  (подставляет pyte и разметку строк в C)


def fresh():
    """Новая папка консоли и чистое зеркало."""
    d = tempfile.mkdtemp(prefix="d_", dir=TMP)
    C._m.update(pid=None, screen=None, stream=None, offset=0, geom=(0, 0))
    return d


class Mirror(unittest.TestCase):
    def setUp(self):
        self.d = fresh()
        self.pid = mock.patch.object(C, "_pid", return_value="123")
        self.dir = mock.patch.object(C, "_dir", return_value=self.d)
        self.dims = mock.patch.object(C, "_dims", return_value=(40, 6))
        for p in (self.pid, self.dir, self.dims):
            p.start()
            self.addCleanup(p.stop)

    def write(self, data, mode="ab"):
        with open(C._log(), mode) as f:
            f.write(data)

    def text(self, html):
        return re.sub(r"<[^>]+>", "", html).replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")

    def test_no_session_is_none(self):
        with mock.patch.object(C, "_pid", return_value=None):
            self.assertIsNone(C.snapshot())

    def test_screen_is_built_from_log(self):
        self.write("Привет, Codex\r\n\x1b[31mкрасный\x1b[0m".encode(), "wb")
        cur, hist = C.snapshot(want_history=True)
        self.assertIn("Привет, Codex", self.text(cur))
        self.assertIn("красный", self.text(cur))
        self.assertIn("color", cur)  # цвет сохранён
        self.assertEqual(hist, "")  # прокрутки пока нет

    def test_feeds_only_new_bytes(self):
        self.write(b"one\r\n", "wb")
        C.snapshot()
        off = C._m["offset"]
        self.assertEqual(off, 5)
        self.write(b"two\r\n")
        cur, _ = C.snapshot()
        self.assertEqual(C._m["offset"], 10)
        self.assertEqual([l.strip() for l in self.text(cur).splitlines() if l.strip()], ["one", "two"])

    def test_scrollback_goes_to_history(self):
        self.write(b"".join(b"line%d\r\n" % i for i in range(20)), "wb")
        cur, hist = C.snapshot(want_history=True)
        self.assertIn("line19", self.text(cur))
        self.assertIn("line0", self.text(hist))
        self.assertNotIn("line0", self.text(cur))

    def test_recreated_log_restarts_screen(self):
        self.write(b"old text\r\n", "wb")
        C.snapshot()
        self.write(b"new\r\n", "wb")  # лог короче прежнего — файл пересоздан
        cur, _ = C.snapshot()
        self.assertEqual(self.text(cur).strip(), "new")

    def test_new_session_resets_screen(self):
        self.write(b"first\r\n", "wb")
        C.snapshot()
        with mock.patch.object(C, "_pid", return_value="456"):
            self.write(b"second\r\n", "wb")
            cur, _ = C.snapshot()
        self.assertNotIn("first", self.text(cur))

    def test_log_over_limit_is_truncated_but_screen_kept(self):
        self.write(b"keep me\r\n", "wb")
        with mock.patch.object(C, "LOG_MAX", 4):
            cur, _ = C.snapshot()
        self.assertEqual(os.path.getsize(C._log()), 0)
        self.assertEqual(C._m["offset"], 0)
        self.assertIn("keep me", self.text(cur))
        self.write(b"more\r\n")  # дальше screen допишет с начала файла
        cur, _ = C.snapshot()
        self.assertIn("more", self.text(cur))
        self.assertIn("keep me", self.text(cur))

    def test_resize_keeps_text(self):
        self.write(b"abc\r\n", "wb")
        C.snapshot()
        with mock.patch.object(C, "_dims", return_value=(60, 8)):
            cur, _ = C.snapshot()
        self.assertEqual(C._m["geom"], (60, 8))
        self.assertIn("abc", self.text(cur))


class Start(unittest.TestCase):
    def setUp(self):
        self.d = fresh()
        self.work = tempfile.mkdtemp(prefix="w_", dir=TMP)
        for p in (mock.patch.object(C, "_dir", return_value=self.d),
                  mock.patch.object(C, "BIN", return_value="/x/codex"),
                  mock.patch.object(C, "PLAN", return_value=("read-only", self.work, None)),
                  mock.patch.object(cc_codex, "profile_slots", return_value=["gpt1"])):
            p.start()
            self.addCleanup(p.stop)

    def test_no_codex(self):
        with mock.patch.object(C, "BIN", return_value=None):
            ok, msg = C.start()
        self.assertFalse(ok)
        self.assertIn("не установлен", msg)
        with mock.patch.object(C, "BIN", return_value=None):
            self.assertIn("not installed", C.start(lang="en")[1])
            self.assertEqual(C.status(), {"available": False})

    def test_already_running(self):
        with mock.patch.object(C, "_pid", return_value="1"), mock.patch.object(C.subprocess, "run") as run:
            self.assertEqual(C.start(), (True, "Консоль уже запущена."))
        run.assert_not_called()

    def test_no_account(self):
        with mock.patch.object(C, "_pid", return_value=None), mock.patch.object(cc_codex, "profile_slots", return_value=[]):
            ok, msg = C.start()
        self.assertFalse(ok)
        self.assertIn("ChatGPT", msg)

    def test_bad_folder_and_sandbox(self):
        with mock.patch.object(C, "_pid", return_value=None):
            with mock.patch.object(C, "PLAN", return_value=("read-only", "/нет/такой", None)):
                self.assertEqual(C.start()[1], "Рабочая папка не найдена.")
            with mock.patch.object(C, "PLAN", return_value=("whatever", self.work, None)):
                self.assertEqual(C.start()[1], "Неизвестные права доступа.")

    def test_command_line(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return mock.Mock(returncode=0, stdout="", stderr="")
        pids = iter([None, "77"])
        with mock.patch.object(C, "_pid", side_effect=lambda: next(pids)), mock.patch.object(C.subprocess, "run", run):
            ok, msg = C.start()
        self.assertTrue(ok, msg)
        argv, kw = calls[0]
        self.assertEqual(argv[0], "screen")
        self.assertIn("-dmS", argv)
        self.assertEqual(argv[argv.index("-dmS") + 1], "cc-codex")
        for want in ("--no-alt-screen", "-s", "read-only", "-C", self.work, "/x/codex"):
            self.assertIn(want, argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(kw["cwd"], self.work)
        self.assertEqual(kw["env"]["CODEX_HOME"], cc_codex.profile_dir("gpt1"))
        self.assertEqual(kw["env"]["TERM"], "xterm-256color")
        # лог сбрасывается раз в секунду с самого старта — через свой rc
        rc = argv[argv.index("-c") + 1]
        with open(rc) as f:
            self.assertEqual(f.read(), "logfile flush 1\n")
        meta = cc_codex.jload(C._meta_path(), {})
        self.assertEqual((meta["pid"], meta["sandbox"], meta["cwd"], meta["slot"]), ("77", "read-only", self.work, "gpt1"))

    def test_status_shows_running_session_rights(self):
        cc_codex._jsave(C._meta_path(), {"pid": "77", "sandbox": "workspace-write", "cwd": "/w", "started": 5})
        with mock.patch.object(C, "_pid", return_value="77"):
            st = C.status()
        self.assertEqual((st["running"], st["sandbox"], st["cwd"], st["started"]), (True, "workspace-write", "/w", 5))
        self.assertEqual(st["plan_sandbox"], "read-only")
        with mock.patch.object(C, "_pid", return_value="78"):  # другая сессия — чужие метки не показываем
            self.assertNotIn("sandbox", C.status())
        with mock.patch.object(C, "_pid", return_value=None):
            self.assertFalse(C.status()["running"])

    def test_stop(self):
        with mock.patch.object(C, "_pid", return_value=None):
            self.assertTrue(C.stop()[0])
        pids = iter(["9", "9", None])
        with mock.patch.object(C, "_pid", side_effect=lambda: next(pids)), mock.patch.object(C, "_ctl") as ctl, \
                mock.patch.object(C.time, "sleep"):
            ok, msg = C.stop()
        self.assertTrue(ok, msg)
        ctl.assert_called_once_with(["-S", "cc-codex", "-X", "quit"])


class Rollout(unittest.TestCase):
    """Разбор файлов сессии Codex и подготовка текста для вставки."""

    def setUp(self):
        self.prof = tempfile.mkdtemp(prefix="p_", dir=TMP)
        p = mock.patch.object(cc_codex, "PROFILES", self.prof)
        p.start()
        self.addCleanup(p.stop)
        self.day = os.path.join(self.prof, "gpt1", "sessions", "2026", "10", "31")
        os.makedirs(self.day)

    def make(self, tid, cwd, events=(), mtime=None):
        path = os.path.join(self.day, f"rollout-2026-10-31T19-47-07-{tid}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": "2026-10-31T11:47:07Z", "type": "session_meta", "payload": {"id": tid, "cwd": cwd}}) + "\n")
            for ev in events:
                f.write(json.dumps(ev) + "\n")
        if mtime:
            os.utime(path, (mtime, mtime))
        return path

    def test_paste_text(self):
        self.assertEqual(C._paste_text("Привет\r\nмир\n\nвторой абзац"), "Привет\nмир\n\nвторой абзац")
        # ESC закрыл бы вставку, остальное управляющее — мусор; перевод строки и табуляция остаются
        self.assertEqual(C._paste_text("a\x1b[201~b\x00c\x7fd\te"), "a[201~bcd\te")
        for head in ("/status", "!rm x", "$skill", "@file", "\n  /status"):
            self.assertTrue(C._paste_text(head + " что-то").startswith("» "), head)
        self.assertEqual(C._paste_text("обычный /текст ! тут"), "обычный /текст ! тут")
        self.assertEqual(C._paste_text(" \x1b \n"), "")

    def test_find_rollout_by_id(self):
        tid = "01a191d3-2ad6-7271-a135-a12554619a0a"
        path = self.make(tid, "/w")
        self.assertEqual(C.find_rollout("gpt1", tid), path)
        self.assertIsNone(C.find_rollout("gpt1", "01a191d3-0000-7271-a135-a12554619a0a"))
        self.assertEqual(C._tid_of(path), tid)

    def test_new_rollout_by_folder_and_time(self):
        old = self.make("01a191d3-0000-7271-a135-a12554619a01", "/w", mtime=1000)
        other = self.make("01a191d3-0000-7271-a135-a12554619a02", "/другая", mtime=5000)
        mine = self.make("01a191d3-0000-7271-a135-a12554619a03", "/w", mtime=5000)
        self.assertEqual(C._new_rollout("gpt1", "/w", 4000), mine)
        self.assertIsNone(C._new_rollout("gpt1", "/w", 6000))
        self.assertIsNone(C._new_rollout("gpt1", "/w", 4000, exclude=mine))
        self.assertTrue(old and other)

    def test_events_read_only_whole_lines(self):
        path = os.path.join(self.prof, "x.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"a": 1}\n{"b": 2}\n{"c"')
        evs, off = C._events(path, 0)
        self.assertEqual(evs, [{"a": 1}, {"b": 2}])
        with open(path, "a", encoding="utf-8") as f:
            f.write(': 3}\n')
        evs, off2 = C._events(path, off)
        self.assertEqual(evs, [{"c": 3}])
        self.assertEqual(C._events(path, off2), ([], off2))

    def test_turn_open(self):
        def ev(kind, turn, ts="2026-10-31T12:00:00Z"):
            return {"timestamp": ts, "type": "event_msg", "payload": {"type": kind, "turn_id": turn}}
        tid = "01a191d3-0000-7271-a135-a12554619a10"
        started = ev("task_started", "t1")
        self.assertTrue(C._turn_open(self.make(tid, "/w", [started])))
        self.assertFalse(C._turn_open(self.make(tid, "/w", [started, ev("task_complete", "t1")])))
        self.assertFalse(C._turn_open(self.make(tid, "/w", [started, ev("turn_aborted", "t1")])))
        # чужой (подчинённый) ход закончился, наш идёт
        self.assertTrue(C._turn_open(self.make(tid, "/w", [started, ev("task_complete", "sub")])))
        # ход начат до запуска консоли — остался от убитого процесса
        since = C._utc("2026-10-31T12:30:00Z")
        self.assertFalse(C._turn_open(self.make(tid, "/w", [started]), since))
        self.assertTrue(C._turn_open(self.make(tid, "/w", [ev("task_started", "t2", "2026-10-31T12:31:00Z")]), since))
        self.assertFalse(C._turn_open(os.path.join(self.prof, "нет.jsonl")))


class FakeConsole:
    """Подставной screen + Codex: на Enter дописывает в файл сессии события, как настоящий Codex."""

    def __init__(self, case, prof, slot="gpt1"):
        self.case, self.prof, self.slot = case, prof, slot
        self.calls, self.pasted, self.enters = [], [], 0
        self.script = []  # что дописать в файл сессии на очередной Enter: список функций (path) → None
        self.path = None

    def ctl(self, args, timeout=10):
        self.calls.append(list(args))
        if "readbuf" in args:
            with open(args[-1], encoding="utf-8") as f:
                self.pasted.append(f.read())
        if args[-1] == "\r":
            self.enters += 1
            if self.script:
                self.script.pop(0)()
        return mock.Mock(returncode=0, stdout="", stderr="")


def evt(kind, **p):
    return {"timestamp": "2026-10-31T12:34:00Z", "type": "event_msg", "payload": dict(type=kind, **p)}


def say(text):
    return {"timestamp": "2026-10-31T12:34:01Z", "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}}


def append(path, *events):
    with open(path, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


class Ask(Rollout):
    TID = "01a191d3-2ad6-7271-a135-a12554619a0a"

    def setUp(self):
        super().setUp()
        self.work = tempfile.mkdtemp(prefix="w_", dir=TMP)
        self.d = fresh()
        self.fc = FakeConsole(self, self.prof)
        for p in (mock.patch.object(C, "_dir", return_value=self.d),
                  mock.patch.object(C, "BIN", return_value="/x/codex"),
                  mock.patch.object(C, "PLAN", return_value=("workspace-write", self.work, "gpt1")),
                  mock.patch.object(cc_codex, "profile_slots", return_value=["gpt1"]),
                  mock.patch.object(C, "_pid", return_value="77"),
                  mock.patch.object(C, "_ctl", self.fc.ctl),
                  mock.patch.object(C, "PASTE_DELAY", 0), mock.patch.object(C, "POLL", 0.01),
                  mock.patch.object(C, "START_WAIT", 0.6), mock.patch.object(C, "PROMPT_WAIT", 0.05)):
            p.start()
            self.addCleanup(p.stop)
        cc_codex._jsave(C._meta_path(), {"pid": "77", "sandbox": "workspace-write", "cwd": self.work, "slot": "gpt1",
                                         "approval": "never", "started": 1000, "tids": {}})

    def meta(self, **kw):
        m = cc_codex.jload(C._meta_path(), {})
        m.update(kw)
        cc_codex._jsave(C._meta_path(), m)

    def reply(self, path, answer="ответ", turn="T1", last=True):
        """Что Codex пишет в файл сессии, получив сообщение."""
        def go():
            append(path, evt("task_started", turn_id=turn), say(answer),
                   evt("task_complete", turn_id=turn, last_agent_message=answer if last else None))
        return go

    def test_resumed_conversation_answer_and_text(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [self.reply(path, "Четыре")]
        ans, tid = C.ask("Привет!\nСколько будет $2+2?")
        self.assertEqual((ans, tid), ("Четыре", self.TID))
        # вставкой (bracketed paste), как есть, с переводом строки, затем Enter
        self.assertEqual(self.fc.pasted, ["\x1b[200~Привет!\nСколько будет $2+2?\x1b[201~"])
        kinds = [c[-2:] if "stuff" not in c else ["stuff", c[-1]] for c in self.fc.calls]
        self.assertEqual(kinds[0][0], "readbuf")
        self.assertEqual(self.fc.calls[1][-2:], ["paste", "."])
        self.assertEqual(self.fc.calls[-1][-2:], ["stuff", "\r"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "paste.txt")), "файл вставки не оставляем")

    def test_only_new_turn_is_answered(self):
        path = self.make(self.TID, self.work, [evt("task_started", turn_id="OLD"), say("старое"),
                                               evt("task_complete", turn_id="OLD", last_agent_message="старое")])
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [self.reply(path, "новое", turn="NEW")]
        self.assertEqual(C.ask("вопрос")[0], "новое")

    def test_answer_falls_back_to_last_message(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [self.reply(path, "из сообщения", last=False)]
        self.assertEqual(C.ask("вопрос")[0], "из сообщения")

    def test_fresh_conversation_finds_new_file_and_remembers_id(self):
        def go():
            path = self.make(self.TID, self.work, [evt("task_started", turn_id="T1"), say("привет"),
                                                   evt("task_complete", turn_id="T1", last_agent_message="привет")])
            os.utime(path, None)
        self.fc.script = [go]
        ans, tid = C.ask("здравствуй")
        self.assertEqual((ans, tid), ("привет", self.TID))
        self.assertEqual(cc_codex.jload(C._meta_path(), {})["tids"], {os.path.realpath(self.work): self.TID})

    def test_busy_console_is_not_typed_into(self):
        path = self.make(self.TID, self.work, [dict(evt("task_started", turn_id="T9"), timestamp="2026-10-31T13:00:00Z")])
        self.meta(tids={os.path.realpath(self.work): self.TID}, started=int(C._utc("2026-10-31T12:00:00Z")))
        with self.assertRaises(C.ConsoleError) as cm:
            C.ask("вопрос")
        self.assertIn("уже идёт запрос", str(cm.exception))
        self.assertEqual(self.fc.calls, [])
        self.assertTrue(path)

    def test_message_not_taken_presses_enter_once_more_then_fails(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        with self.assertRaises(C.ConsoleError) as cm:
            C.ask("вопрос")
        self.assertIn("не приняла", str(cm.exception))
        self.assertEqual(self.fc.enters, 2)  # первый Enter + один повторный
        self.assertTrue(path)

    def test_late_enter_is_enough(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [lambda: None, self.reply(path, "поздно, но принято")]
        self.assertEqual(C.ask("вопрос")[0], "поздно, но принято")

    def test_abort_before_and_during(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        ev = threading.Event()
        ev.set()
        with self.assertRaises(C.Aborted):
            C.ask("вопрос", abort=ev)
        self.assertEqual(self.fc.calls, [])
        # ход начался, потом /stop: Esc → turn_aborted
        ev = threading.Event()

        def begin():
            append(path, evt("task_started", turn_id="T2"))
            threading.Timer(0.1, lambda: (ev.set(), append(path, evt("turn_aborted", turn_id="T2", reason="interrupted")))).start()
        self.fc.script = [begin]
        with self.assertRaises(C.Aborted):
            C.ask("вопрос", abort=ev)

    def test_interrupted_in_console_by_human_is_error(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [lambda: append(path, evt("task_started", turn_id="T3"), evt("turn_aborted", turn_id="T3", reason="interrupted"))]
        with self.assertRaises(C.ConsoleError) as cm:
            C.ask("вопрос")
        self.assertNotIsInstance(cm.exception, C.Aborted)
        self.assertIn("прерван", str(cm.exception))

    def test_console_closed_while_waiting(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [lambda: append(path, evt("task_started", turn_id="T4"))]
        pids = iter(["77"] * 4)  # ensure/ask проверяют «жив ли», потом сессия исчезает
        with mock.patch.object(C, "_pid", side_effect=lambda: next(pids, None)):
            with self.assertRaises(C.ConsoleError) as cm:
                C.ask("вопрос")
        self.assertIn("закрылась", str(cm.exception))

    def test_timeout_interrupts_codex(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [lambda: append(path, evt("task_started", turn_id="T5"))]
        with self.assertRaises(C.ConsoleError) as cm:
            C.ask("вопрос", timeout=0.2)
        self.assertIn("не ответил", str(cm.exception))
        self.assertEqual(self.fc.calls[-1][-2:], ["stuff", "\x1b"])

    def test_empty_message(self):
        with self.assertRaises(C.ConsoleError):
            C.ask(" \x1b ")

    def test_interrupt_sends_escape(self):
        self.assertTrue(C.interrupt())
        self.assertEqual(self.fc.calls, [["-S", "cc-codex", "-p", "0", "-X", "stuff", "\x1b"]])

    # --- ensure / start / forget
    def test_ensure_keeps_matching_console(self):
        with mock.patch.object(C, "start") as st, mock.patch.object(C, "stop") as sp:
            self.assertEqual(C.ensure(), (True, ""))
        st.assert_not_called()
        sp.assert_not_called()

    def test_ensure_restarts_when_rights_folder_or_approval_changed(self):
        for patch in ({"sandbox": "read-only"}, {"cwd": "/другая"}, {"approval": None}):
            self.meta(**patch)
            with mock.patch.object(C, "start", return_value=(True, "ok")) as st, \
                    mock.patch.object(C, "stop", return_value=(True, "ok")) as sp:
                self.assertEqual(C.ensure(), (True, "ok"), patch)
            sp.assert_called_once()
            st.assert_called_once()
            self.meta(sandbox="workspace-write", cwd=self.work, approval="never")

    def test_ensure_does_not_restart_mid_request(self):
        self.make(self.TID, self.work, [dict(evt("task_started", turn_id="T6"), timestamp="2026-10-31T13:00:00Z")])
        self.meta(sandbox="read-only", tids={os.path.realpath(self.work): self.TID}, started=int(C._utc("2026-10-31T12:00:00Z")))
        with mock.patch.object(C, "stop") as sp:
            ok, msg = C.ensure()
        self.assertFalse(ok)
        self.assertIn("идёт запрос", msg)
        sp.assert_not_called()

    def test_ensure_starts_stopped_console(self):
        with mock.patch.object(C, "_pid", return_value=None), mock.patch.object(C, "start", return_value=(True, "запущена")) as st:
            self.assertEqual(C.ensure(), (True, "запущена"))
        st.assert_called_once()

    def test_start_resumes_known_conversation_with_no_approvals(self):
        self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout="", stderr="")
        pids = iter([None, "88"])
        with mock.patch.object(C, "_pid", side_effect=lambda: next(pids)), mock.patch.object(C.subprocess, "run", run):
            ok, msg = C.start()
        self.assertTrue(ok, msg)
        argv = calls[0]
        i = argv.index("/x/codex")
        self.assertEqual(argv[i + 1:i + 3], ["resume", self.TID])
        self.assertEqual(argv[argv.index("-a") + 1], "never")
        self.assertEqual(argv[argv.index("-s") + 1], "workspace-write")
        meta = cc_codex.jload(C._meta_path(), {})
        self.assertEqual((meta["pid"], meta["approval"], meta["tids"]), ("88", "never", {os.path.realpath(self.work): self.TID}))

    def test_start_forgets_id_whose_file_is_gone(self):
        self.meta(tids={os.path.realpath(self.work): "01a191d3-ffff-7271-a135-a12554619a0a"})
        calls = []
        pids = iter([None, "89"])
        with mock.patch.object(C, "_pid", side_effect=lambda: next(pids)), \
                mock.patch.object(C.subprocess, "run", lambda argv, **kw: (calls.append(argv), mock.Mock(returncode=0, stdout="", stderr=""))[1]):
            self.assertTrue(C.start()[0])
        self.assertNotIn("resume", calls[0])
        self.assertEqual(cc_codex.jload(C._meta_path(), {})["tids"], {})

    def test_forget_clears_conversations_and_stops(self):
        self.meta(tids={os.path.realpath(self.work): self.TID})
        with mock.patch.object(C, "stop", return_value=(True, "")) as sp:
            C.forget()
        self.assertEqual(cc_codex.jload(C._meta_path(), {})["tids"], {})
        sp.assert_called_once()

    def test_usable_needs_codex_and_screen(self):
        with mock.patch.object(C.shutil, "which", return_value="/usr/bin/screen"):
            self.assertTrue(C.usable())
            with mock.patch.object(C, "BIN", return_value=None):
                self.assertFalse(C.usable())
        with mock.patch.object(C.shutil, "which", return_value=None):
            self.assertFalse(C.usable())


class Routes(unittest.TestCase):
    def get(self, query, snap=None, bin_="/x/codex"):
        got = []

        class Fake:
            path = "/api/console?token=t&" + query
            headers = {}

            def _authed(self):
                return True

            def _send(self, code, obj):
                got.append((code, obj))
        with mock.patch.object(L, "codex_bin", return_value=bin_), \
                mock.patch.object(C, "snapshot", return_value=snap), \
                mock.patch.object(C, "status", return_value={"available": True, "running": snap is not None}), \
                mock.patch.object(L, "console_snapshot", return_value=("claude screen", "claude history")):
            L.H.do_GET(Fake())
        return got[0]

    def test_claude_console_unchanged(self):
        code, d = self.get("history=1")
        self.assertEqual((code, d), (200, {"ok": True, "current": "claude screen", "history": "claude history"}))

    def test_unknown_session_falls_back_to_claude(self):
        self.assertEqual(self.get("s=bash")[1]["current"], "claude screen")

    def test_codex_running(self):
        code, d = self.get("s=codex&history=1", snap=("cur", "hist"))
        self.assertEqual(code, 200)
        self.assertEqual((d["session"], d["running"], d["current"], d["history"]), ("codex", True, "cur", "hist"))

    def test_codex_without_history_param_has_no_history(self):
        d = self.get("s=codex", snap=("cur", None))[1]
        self.assertNotIn("history", d)

    def test_codex_not_running(self):
        d = self.get("s=codex")[1]
        self.assertEqual((d["ok"], d["running"], d["current"]), (True, False, None))

    def test_codex_not_installed(self):
        d = self.get("s=codex", bin_=None)[1]
        self.assertEqual((d["available"], d["running"]), (False, False))

    def test_post_routes(self):
        got = []

        class Fake:
            def _send(self, code, obj):
                got.append((code, obj))
        with mock.patch.object(L, "codex_bin", return_value="/x/codex"), \
                mock.patch.object(C, "start", return_value=(True, "go")) as st, \
                mock.patch.object(C, "stop", return_value=(False, "no")) as sp, \
                mock.patch.object(C, "status", return_value={"running": True}):
            L.H._chatgpt_post(Fake(), "console/start", {"lang": "en"})
            L.H._chatgpt_post(Fake(), "console/stop", {})
        st.assert_called_once_with(lang="en")
        sp.assert_called_once_with(lang=None)
        self.assertEqual(got[0], (200, {"running": True, "ok": True, "message": "go"}))
        self.assertEqual(got[1], (200, {"running": True, "ok": False, "message": "no"}))


class Page(unittest.TestCase):
    def test_tabs_are_hidden_until_codex_is_available(self):
        self.assertRegex(L.PAGE, r'<div class="ctabs" id="cTabs"[^>]*\bhidden\b')
        self.assertIn("$('#cTabs').hidden=!av", L.PAGE)  # av = cxAvail(): Codex установлен
        self.assertIn("function consCur(){return CONS==='codex'&&cxAvail()?'codex':'claude';}", L.PAGE)

    def test_tabs_sit_inside_console_block_before_it(self):
        wrap = L.PAGE.index('<div class="termwrap">')
        self.assertGreater(L.PAGE.index('id="cTabs"'), wrap)
        self.assertLess(L.PAGE.index('id="cTabs"'), L.PAGE.index('id="termBox"'))

    def test_phone_tabs_have_big_tap_target(self):
        phone = L.PAGE[L.PAGE.index("@media (max-width:640px){"):]
        self.assertIn("html:root:root .iconbtn.ctab,html:root:root .iconbtn.ctstop{height:34px}", phone)

    def test_poll_asks_for_selected_session_only(self):
        self.assertIn("(s==='codex'?'&s=codex':'')", L.PAGE)
        self.assertIn("if(s!==consCur())return;", L.PAGE)  # ответ от прежней вкладки отбрасывается

    def test_first_poll_waits_for_script_load(self):
        # consCur() -> cxAvail() читает cxData/cxbData (let ниже по скрипту): вызов на старте даёт «before initialization»
        self.assertIn("setTimeout(()=>{ccConsoleHistory();ccConsole();},0);setInterval(ccConsole,2000);", L.PAGE)
        self.assertNotRegex(L.PAGE, r"\nccConsoleHistory\(\);ccConsole\(\);")

    def test_selected_tab_is_remembered_in_browser(self):
        self.assertIn("localStorage.setItem('cc_contab',k)", L.PAGE)

    def test_texts_in_both_languages(self):
        def keys(lang):
            m = re.search(r"\n %s:\{\n(.*?)\n \},?\n" % lang, L.PAGE, re.S)
            return set(re.findall(r"^\s{2}(cxc\w+):", m.group(1), re.M))
        ru, en = keys("ru"), keys("en")
        self.assertEqual(ru ^ en, set())
        used = set(re.findall(r"tr\('(cxc\w+)'", L.PAGE)) | set(re.findall(r"'(cxcSb\w+)'", L.PAGE))
        self.assertEqual(sorted(used - ru), [])

    def test_view_only_is_said_on_the_page(self):
        m = re.search(r"cxcSub:\(sb,cwd\)=>'([^']*)", L.PAGE)
        self.assertIn("Только просмотр", m.group(1))


if __name__ == "__main__":
    unittest.main()
