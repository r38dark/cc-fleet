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

    def test_frozen_screen_of_stopped_console_comes_from_the_log(self):
        self.write("Последний экран\r\n\x1b[31mкрасный\x1b[0m".encode(), "wb")
        cur, hist, stopped = C.frozen_snapshot(True)
        self.assertIn("Последний экран", self.text(cur))
        self.assertIn("красный", self.text(cur))
        self.assertIn("color", cur)
        self.assertEqual(hist, "")
        self.assertGreater(stopped, 0)
        self.assertIsNone(C.frozen_snapshot(False)[1])

    def test_frozen_screen_falls_back_to_previous_log_when_new_one_is_empty(self):
        with open(C._log() + ".prev", "wb") as f:
            f.write("Прошлый сеанс".encode())
        open(C._log(), "wb").close()  # свежий запуск ещё ничего не нарисовал
        self.assertIn("Прошлый сеанс", self.text(C.frozen_snapshot()[0]))

    def test_frozen_screen_without_any_log(self):
        self.assertEqual(C.frozen_snapshot(True), ("", "", 0))
        self.assertEqual(C.frozen_snapshot(False), ("", None, 0))

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
                  mock.patch.object(C, "_retire_unit", return_value=True),
                  mock.patch.object(C, "BIN", return_value="/x/codex"),
                  mock.patch.object(cc_codex, "profile_dir", side_effect=lambda slot: os.path.join(TMP, 'profiles', slot)),
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
        with mock.patch.object(C, "_pid", side_effect=lambda **kwargs: next(pids)), mock.patch.object(C.subprocess, "run", run):
            ok, msg = C.start()
        self.assertTrue(ok, msg)
        argv, kw = calls[0]
        self.assertEqual(argv[0], "/usr/bin/systemd-run")
        self.assertIn("--unit=cc-codex-console.service", argv)
        self.assertIn("--working-directory=" + C.CLI_CWD, argv)
        self.assertIn("/usr/bin/screen", argv)
        self.assertIn("-mS", argv)
        self.assertEqual(argv[argv.index("-mS") + 1], "cc-codex")
        for want in ("--sandbox", "read-only", "--cd", self.work, "/x/codex"):
            self.assertIn(want, argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(kw["cwd"], C.CLI_CWD)
        self.assertEqual(kw["env"], {"PATH": "/usr/bin:/bin"})
        self.assertIn("--property=KillMode=control-group", argv)
        # лог сбрасывается раз в секунду с самого старта — через свой rc
        rc = argv[argv.index("-c") + 1]
        with open(rc) as f:
            self.assertEqual(f.read(), 'logfile flush 1\nterm screen-256color\ntermcapinfo * "Km=\\E[M"\n')
        meta = cc_codex.jload(C._meta_path(), {})
        self.assertEqual((meta["pid"], meta["sandbox"], meta["cwd"], meta["slot"]), ("77", "read-only", self.work, "gpt1"))

    def test_mcp_keys_go_into_command_line_and_meta_after_the_other_keys(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout="", stderr="")
        keys = ["-c", 'mcp_servers.notion.url="https://x/mcp"', "-c", "mcp_servers.notion.enabled_tools=[\"a\"]"]
        pids = iter([None, "77"])
        with mock.patch.object(C, "MCP", lambda: keys), mock.patch.object(C, "_pid", side_effect=lambda **kwargs: next(pids)), \
                mock.patch.object(C.subprocess, "run", run):
            ok, msg = C.start()
        self.assertTrue(ok, msg)
        argv = calls[0]
        self.assertEqual(argv[-4:], keys)  # ключи в самом конце: не сбивают -s/-a/-C
        self.assertLess(argv.index("--cd"), argv.index("mcp_servers.notion.enabled_tools=[\"a\"]"))
        self.assertEqual(cc_codex.jload(C._meta_path(), {})["mcp"], keys)

    def test_private_transport_start_keeps_environment_rc_and_metadata_together(self):
        terminal = dict(screen_bin='/opt/cc-limits/terminal/screen-5.0.2/screen',
                        screen_dir=os.path.join(self.d, 'screen5'), screen_rgb=True)
        pids = iter([None, '77'])
        with mock.patch.object(C.cc_codex_terminal, 'target', return_value=terminal), \
                mock.patch.object(C, '_pid', side_effect=lambda **kw: next(pids)), \
                mock.patch.object(C.cc_codex, 'runas_user', return_value='nobody'), \
                mock.patch.object(C.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            ok, msg = C.start()
        self.assertTrue(ok, msg)
        argv = run.call_args.args[0]
        self.assertIn(terminal['screen_bin'], argv)
        self.assertIn('SCREENDIR='+terminal['screen_dir'], argv)
        with open(os.path.join(self.d, 'console.rc')) as stream:
            self.assertIn('truecolor on\n', stream.read())
        meta = cc_codex.jload(C._meta_path(), {})
        self.assertEqual({k: meta[k] for k in terminal}, terminal)
        self.assertEqual(os.stat(terminal['screen_dir']).st_mode & 0o777, 0o700)

    def test_no_mcp_keys_outside_reserve(self):
        calls = []
        pids = iter([None, "77"])
        with mock.patch.object(C, "_pid", side_effect=lambda **kwargs: next(pids)), \
                mock.patch.object(C.subprocess, "run", lambda argv, **kw: (calls.append(argv), mock.Mock(returncode=0, stdout="", stderr=""))[1]):
            C.start()
        self.assertFalse([x for x in calls[0] if "mcp_servers" in x])
        self.assertEqual(cc_codex.jload(C._meta_path(), {})["mcp"], [])

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
        with mock.patch.object(C, "_pid", side_effect=lambda **kwargs: next(pids)), mock.patch.object(C, "_ctl") as ctl, \
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
        if "@readbuf" in args:
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
                  mock.patch.object(C, "_retire_unit", return_value=True),
                  mock.patch.object(C, "BIN", return_value="/x/codex"),
                  mock.patch.object(C, "PLAN", return_value=("workspace-write", self.work, "gpt1")),
                  mock.patch.object(cc_codex, "profile_slots", return_value=["gpt1"]),
                  mock.patch.object(C, "_pid", return_value="77"),
                  mock.patch.object(C, "_ctl", self.fc.ctl),
                  mock.patch.object(C, "PASTE_DELAY", 0), mock.patch.object(C, "POLL", 0.01),
                  mock.patch.object(C, "CMD_DELAY", 0), mock.patch.object(C, "CMD_WAIT", 0.3),
                  mock.patch.object(C, "ENTER_RETRY", 0.1), mock.patch.object(C, "START_WAIT", 0.6), mock.patch.object(C, "PROMPT_WAIT", 0.05)):
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
        self.assertEqual(kinds[0][0], "@readbuf")
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
        self.assertIn("Не получил подтверждение", str(cm.exception))
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

    def test_ensure_restarts_when_reserve_mcp_keys_appear_or_go(self):
        # резерв включился/закончился → набор ключей Notion другой → консоль перезапускается; тот же набор — не трогаем
        keys = ["-c", 'mcp_servers.notion.url="https://x/mcp"']
        for was, now in (([], keys), (keys, [])):
            self.meta(mcp=was)
            with mock.patch.object(C, "MCP", lambda now=now: now), mock.patch.object(C, "start", return_value=(True, "ok")) as st, \
                    mock.patch.object(C, "stop", return_value=(True, "ok")) as sp:
                self.assertEqual(C.ensure(), (True, "ok"), (was, now))
            sp.assert_called_once()
            st.assert_called_once()
        self.meta(mcp=keys, pending_settings={})
        with mock.patch.object(C, "MCP", lambda: keys), mock.patch.object(C, "start") as st, mock.patch.object(C, "stop") as sp:
            self.assertEqual(C.ensure(), (True, ""))
        st.assert_not_called()
        sp.assert_not_called()
        self.meta(mcp=[])

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
        with mock.patch.object(C, "_pid", side_effect=lambda **kwargs: next(pids)), mock.patch.object(C.subprocess, "run", run):
            ok, msg = C.start()
        self.assertTrue(ok, msg)
        argv = calls[0]
        i = argv.index("/x/codex")
        self.assertEqual(argv[i + 1:i + 3], ["resume", self.TID])
        self.assertEqual(argv[argv.index("--ask-for-approval") + 1], "never")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        meta = cc_codex.jload(C._meta_path(), {})
        self.assertEqual((meta["pid"], meta["approval"], meta["tids"]), ("88", "never", {os.path.realpath(self.work): self.TID}))

    def test_start_rejects_missing_conversation_without_silent_fallback(self):
        self.meta(tids={os.path.realpath(self.work): "01a191d3-ffff-7271-a135-a12554619a0a"})
        with mock.patch.object(C, "_pid", return_value=None), mock.patch.object(C.subprocess, "run") as run:
            ok, message = C.start()
        self.assertFalse(ok)
        self.assertIn("другой разговор", message)
        run.assert_not_called()

    def test_forget_clears_conversations_and_stops(self):
        self.meta(tids={os.path.realpath(self.work): self.TID})
        with mock.patch.object(C, "stop", return_value=(True, "")) as sp:
            C.forget()
        self.assertEqual(cc_codex.jload(C._meta_path(), {})["tids"], {})
        sp.assert_called_once()

    def typed(self):
        return [a[-1] for a in self.fc.calls if "stuff" in a]

    def test_compact_types_command_then_enter_and_sees_the_turn_start(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        self.fc.script = [lambda: append(path, evt("task_started", turn_id="T2"))]
        ok, msg = C.compact()
        self.assertTrue(ok, msg)
        self.assertEqual(self.typed(), ["/compact", "\r"])  # команда и Enter порознь: вставка стала бы текстом
        self.assertFalse(self.fc.pasted)
        self.assertIn("Сжатие запущено", msg)

    def test_compact_says_when_codex_did_not_start(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        ok, msg = C.compact()
        self.assertFalse(ok)
        self.assertIn("не начал сжатие", msg)

    def test_compact_without_known_conversation_just_sends(self):
        ok, msg = C.compact()
        self.assertTrue(ok)
        self.assertEqual(self.typed(), ["/compact", "\r"])

    def test_compact_not_typed_into_busy_console(self):
        path = self.make(self.TID, self.work)
        self.meta(tids={os.path.realpath(self.work): self.TID})
        append(path, evt("task_started", turn_id="T9"))  # ход открыт
        ok, msg = C.compact()
        self.assertFalse(ok)
        self.assertIn("отвечает", msg)
        self.assertEqual(self.typed(), [])

    def test_compact_not_typed_while_bridge_message_is_being_typed(self):
        with C._ask_lock:
            ok, msg = C.compact(lang="en")
        self.assertFalse(ok)
        self.assertIn("replying", msg)
        self.assertEqual(self.typed(), [])

    def test_compact_without_console(self):
        with mock.patch.object(C, "_pid", return_value=None):
            ok, msg = C.compact()
        self.assertFalse(ok)
        self.assertIn("не запущена", msg)
        self.assertEqual(self.typed(), [])

    def test_usable_needs_codex_and_screen(self):
        with mock.patch.object(C.shutil, "which", return_value="/usr/bin/screen"):
            self.assertTrue(C.usable())
            with mock.patch.object(C, "BIN", return_value=None):
                self.assertFalse(C.usable())
        with mock.patch.object(C.shutil, "which", return_value=None):
            self.assertFalse(C.usable())

    # --- ответ, который не дошёл из-за перезапуска балансера: mark() до отправки, recover() после
    def point(self, path, **kw):
        return dict(path=path, off=os.path.getsize(path), turn=None, **kw)

    def test_mark_points_at_end_of_current_rollout(self):
        path = self.make(self.TID, self.work, [evt("task_started", turn_id="OPEN")])
        self.meta(tids={os.path.realpath(self.work): self.TID}, started=0)
        m = C.mark()
        self.assertEqual((m["path"], m["off"], m["turn"]), (path, os.path.getsize(path), "OPEN"))

    def test_mark_without_rollout_is_none(self):
        self.assertIsNone(C.mark())

    def test_recover_returns_answer_of_turn_finished_while_nobody_waited(self):
        path = self.make(self.TID, self.work)
        point = self.point(path)
        append(path, evt("task_started", turn_id="T1"), say("черновик"),
               evt("task_complete", turn_id="T1", last_agent_message="готовый ответ"))
        self.assertEqual(C.recover(point, 1000), ("готовый ответ", self.TID))

    def test_recover_falls_back_to_last_message(self):
        path = self.make(self.TID, self.work)
        point = self.point(path)
        append(path, evt("task_started", turn_id="T1"), say("из сообщения"), evt("task_complete", turn_id="T1"))
        self.assertEqual(C.recover(point, 1000)[0], "из сообщения")

    def test_recover_waits_for_turn_that_was_open_when_message_was_sent(self):
        path = self.make(self.TID, self.work, [evt("task_started", turn_id="T0")])
        point = self.point(path, **{})
        point["turn"] = "T0"
        threading.Timer(0.2, append, (path, evt("task_complete", turn_id="T0", last_agent_message="дописал"))).start()
        self.assertEqual(C.recover(point, 1000, timeout=5), ("дописал", self.TID))

    def test_recover_ignores_other_turns(self):
        path = self.make(self.TID, self.work)
        point = self.point(path)
        append(path, evt("task_started", turn_id="T1"), evt("task_complete", turn_id="SUB", last_agent_message="чужой"),
               evt("task_complete", turn_id="T1", last_agent_message="свой"))
        self.assertEqual(C.recover(point, 1000)[0], "свой")

    def test_recover_gives_up_when_no_turn_started(self):
        path = self.make(self.TID, self.work)
        self.assertEqual(C.recover(self.point(path), 1000), (None, self.TID))

    def test_recover_aborted_turn_without_new_one_is_none(self):
        path = self.make(self.TID, self.work)
        point = self.point(path)
        append(path, evt("task_started", turn_id="T1"), evt("turn_aborted", turn_id="T1", reason="interrupted"))
        self.assertEqual(C.recover(point, 1000), (None, self.TID))

    def test_recover_follows_next_turn_after_abort(self):
        path = self.make(self.TID, self.work)
        point = self.point(path)
        append(path, evt("task_started", turn_id="T1"), evt("turn_aborted", turn_id="T1"),
               evt("task_started", turn_id="T2"), evt("task_complete", turn_id="T2", last_agent_message="после уточнения"))
        self.assertEqual(C.recover(point, 1000)[0], "после уточнения")

    def test_recover_console_closed_while_turn_open(self):
        path = self.make(self.TID, self.work, [evt("task_started", turn_id="T0")])
        point = self.point(path)
        point["turn"] = "T0"
        with mock.patch.object(C, "_pid", return_value=None):
            with self.assertRaises(C.ConsoleError):
                C.recover(point, 1000, timeout=5)

    def test_recover_abort_event(self):
        path = self.make(self.TID, self.work, [evt("task_started", turn_id="T0")])
        point = self.point(path)
        point["turn"] = "T0"
        ev = threading.Event()
        ev.set()
        with self.assertRaises(C.Aborted):
            C.recover(point, 1000, abort=ev)


class Routes(unittest.TestCase):
    def get(self, query, snap=None, bin_="/x/codex", claude_running=True):
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
                mock.patch.object(C, "frozen_snapshot", return_value=("codex last", "codex last history", 777)), \
                mock.patch.object(L, "console_snapshot", return_value=("claude screen", "claude history")), \
                mock.patch.object(L, "_current_screen_pid", return_value="123" if claude_running else None), \
                mock.patch.object(L, "console_frozen_snapshot", return_value=("last screen", "last history", 12345)), \
                mock.patch.object(L, "console_idle_reason", return_value="stopped"):
            L.H.do_GET(Fake())
        return got[0]

    def test_claude_console_unchanged(self):
        code, d = self.get("history=1")
        self.assertEqual((code, d), (200, {"ok": True, "current": "claude screen", "history": "claude history", "running": True}))

    def test_claude_stopped_shows_saved_screen(self):
        code, d = self.get("history=1", claude_running=False)
        self.assertEqual((code, d), (200, {"ok": True, "current": "last screen", "history": "last history",
                                          "running": False, "idle": "stopped", "stopped": 12345}))

    def test_unknown_session_falls_back_to_claude(self):
        self.assertEqual(self.get("s=bash")[1]["current"], "claude screen")

    def test_codex_running(self):
        code, d = self.get("s=codex&history=1", snap=("cur", "hist"))
        self.assertEqual(code, 200)
        self.assertEqual((d["session"], d["running"], d["current"], d["history"]), ("codex", True, "cur", "hist"))

    def test_codex_without_history_param_has_no_history(self):
        d = self.get("s=codex", snap=("cur", None))[1]
        self.assertNotIn("history", d)

    def test_codex_not_running_shows_last_screen_like_claude(self):
        d = self.get("s=codex&history=1")[1]
        self.assertEqual((d["ok"], d["running"], d["current"], d["history"], d["stopped"]),
                         (True, False, "codex last", "codex last history", 777))

    def test_codex_not_running_without_history_param_has_no_history(self):
        d = self.get("s=codex")[1]
        self.assertEqual((d["running"], d["current"], d["stopped"]), (False, "codex last", 777))

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


class CmdRoute(unittest.TestCase):
    def post(self, body):
        got = []

        class Fake:
            def _send(self, code, obj):
                got.append((code, obj))
        with mock.patch.object(L, "codex_bin", return_value="/x/codex"), \
                mock.patch.object(C, "status", return_value={"running": True}):
            L.H._chatgpt_post(Fake(), "console/cmd", body)
        return got[0]

    def test_compact(self):
        with mock.patch.object(C, "compact", return_value=(True, "ok")) as cp, \
                mock.patch.object(L.cc_codex_bridge, "reset_thread") as rt:
            self.assertEqual(self.post({"cmd": "compact", "lang": "en"}), (200, {"running": True, "ok": True, "message": "ok"}))
        cp.assert_called_once_with(lang="en")
        rt.assert_not_called()

    def test_new_forgets_the_conversation_and_starts_clean(self):
        order = []
        with mock.patch.object(L.cc_codex_bridge, "reset_thread", side_effect=lambda: order.append("reset")), \
                mock.patch.object(C, "start", side_effect=lambda lang=None: order.append("start") or (True, "go")):
            code, obj = self.post({"cmd": "new"})
        self.assertEqual(order, ["reset", "start"])  # сначала разговор забыт, потом консоль заново
        self.assertEqual((code, obj["ok"]), (200, True))
        self.assertIn("прошлый разговор забыт", obj["message"])

    def test_new_reports_start_failure(self):
        with mock.patch.object(L.cc_codex_bridge, "reset_thread"), \
                mock.patch.object(C, "start", return_value=(False, "нет входа")):
            code, obj = self.post({"cmd": "new"})
        self.assertEqual((obj["ok"], obj["message"]), (False, "нет входа"))

    def test_unknown_command(self):
        self.assertEqual(self.post({"cmd": "rm"})[0], 400)


class Page(unittest.TestCase):
    def test_compact_and_new_buttons_live_in_the_console_toolbar_without_a_stop_button(self):
        # кнопки остановки консоли нет; сжать и новая сессия видны на вкладках Claude DEV, PROD и Codex всегда
        tabs = L.PAGE[L.PAGE.index('id="cTabs"'):L.PAGE.index('class="tzoom"')]
        self.assertNotIn('id="ctStop"', L.PAGE)
        self.assertLess(tabs.index('id="ctCompact"'), tabs.index('id="ctNew"'))
        self.assertRegex(tabs, r'id="ctCompact" hidden')
        self.assertRegex(tabs, r'id="ctNew" hidden')
        self.assertIn("const k=consCur(),show=k==='claude'||k==='prod'||k==='codex';", L.PAGE)
        self.assertIn("$('#ctCompact').hidden=$('#ctNew').hidden=!show;", L.PAGE)

    def test_action_buttons_wrap_into_second_row_on_phone_without_clashing_with_card_acts(self):
        tabs = L.PAGE[L.PAGE.index('id="cTabs"'):L.PAGE.index('class="tzoom"')]
        wrap = tabs[tabs.index('<span class="ctacts">'):]
        for i in ("ctCompact", "ctNew"):
            self.assertIn('id="%s"' % i, wrap)  # обе кнопки действий лежат в одной обёртке
        self.assertIn(".ctacts{display:contents}", L.PAGE)  # на широком экране обёртка не влияет на раскладку
        self.assertIn("html:root:root .ctabs.cacts .ctacts{display:flex;gap:4px;grid-column:1/-1}", L.PAGE)
        self.assertIn("html:root:root .termwrap.hascacts .termbox{padding-top:92px}", L.PAGE)
        # класс .acts уже занят карточкой аккаунта (flex, отступы, padding у button) — для панели берём свой
        self.assertNotRegex(L.PAGE, r"classList\.(toggle|add|remove)\('(has)?acts'")
        self.assertIn("$('#cTabs').classList.toggle('cacts',show)", L.PAGE)
        # при смене вкладки состояние кнопок пересчитывается заново (Notion AI — кнопок нет)
        self.assertIn("P.idle.hidden=true;", L.PAGE)  # смена модели в панели сбрасывает плашку
        self.assertIn("splitBtnSync();\n ctActsSync();", L.PAGE)  # consTabs пересчитывает кнопки на каждой смене

    def test_buttons_post_to_console_cmd_and_new_asks_first(self):
        self.assertIn("acctPost('chatgpt/console/cmd',{cmd})", L.PAGE)
        self.assertIn("if(cmd==='new'&&!confirm(tr('cxcNewQ')))return;", L.PAGE)
        # те же две кнопки стоят и на вкладках Claude DEV/PROD — вкладка Codex по-прежнему идёт в cxConsCmd
        self.assertIn("return s==='codex'?cxConsCmd(cmd,anchor):", L.PAGE)
        self.assertIn("addEventListener('click',()=>consActCmd('compact'))", L.PAGE)
        self.assertIn("addEventListener('click',()=>consActCmd('new'))", L.PAGE)

    def test_tabs_are_hidden_until_codex_is_available(self):
        self.assertRegex(L.PAGE, r'<div class="ctabs" id="cTabs"[^>]*\bhidden\b')
        self.assertIn("$('#cTabs').hidden=!(av||pv)", L.PAGE)  # av = cxConsOn(): Codex установлен и есть вход ChatGPT; pv — подключён Аккаунт PROD
        self.assertIn("function baseCur(){return CONS==='prod'&&prodAvail()?'prod':CONS==='codex'&&cxAvail()&&!document.documentElement.classList.contains('ag-unlinked-codex')?'codex':'claude';}", L.PAGE)
        self.assertIn("function consCur(){const ks=splitEff();return ks?ks[splitActIdx(ks)]:baseCur();}", L.PAGE)

    def test_tabs_sit_inside_console_block_before_it(self):
        wrap = L.PAGE.index('<div class="termwrap">')
        self.assertGreater(L.PAGE.index('id="cTabs"'), wrap)
        self.assertLess(L.PAGE.index('id="cTabs"'), L.PAGE.index('id="termBox"'))

    def test_phone_tabs_have_big_tap_target(self):
        phone = L.PAGE[L.PAGE.index("@media (max-width:640px){"):]
        self.assertIn("html:root:root .iconbtn.ctab,html:root:root .iconbtn.ctstop{height:34px}", phone)

    def test_poll_asks_for_selected_session_only(self):
        self.assertIn("function consQuery(s,P){return s==='codex'?'&s=codex':s==='prod'?'&s=prod&cols='+termCols(P&&P.box):'';}", L.PAGE)
        self.assertEqual(L.PAGE.count("'console?token='+TOKEN+consQuery(s,P)"), 1)  # опрос экрана
        self.assertEqual(L.PAGE.count("'&history=1'+consQuery(s,P)"), 1)  # опрос прокрутки
        self.assertIn("if(s!==P.k)return;", L.PAGE)  # ответ от прежней модели панели отбрасывается
        self.assertIn("if(s!==P.k||requestSeq<P.applied)return;", L.PAGE)

    def test_first_poll_waits_for_script_load(self):
        # consCur() -> cxAvail() читает cxData/cxbData (let ниже по скрипту): вызов на старте даёт «before initialization»
        self.assertIn("setTimeout(()=>{consTabs();ccConsoleHistory();tickAll();},0);setInterval(tickAll,2000);", L.PAGE)
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

    def test_one_idle_plate_for_all_three_consoles(self):
        page = L.PAGE
        for gone in ('id="cxCons"', 'id="prodCons"', 'cxConsMsg', 'prodConsUi', 'class="cxcons"'):
            self.assertNotIn(gone, page)  # центральные надписи убраны: «не запущена» теперь везде серая плашка снизу
        self.assertIn('id="termIdle"', page)
        self.assertIn('id="termIdleGo"', page)
        for who in ("'Claude',null", "'Claude на PROD'", "'Codex'"):
            self.assertIn(who, page)  # Claude, PROD и Codex рисуют плашку одной функцией
        self.assertEqual(page.count('function idleUi('), 1)
        self.assertEqual(page.count("P.idle.hidden=true"), 1)  # сброс только при смене модели в панели

    def test_plate_goes_to_the_bottom_when_there_is_no_screen_to_show(self):
        page = L.PAGE
        self.assertIn(".termbox.termempty{display:flex;flex-direction:column}", page)
        self.assertIn(".termbox.termempty .termidle{margin-top:auto}", page)
        self.assertIn("box.classList.toggle('termempty',!P.idle.hidden&&!P.cur.textContent.trim()&&!P.hist.textContent.trim());", page)
        # признак ставится после того, как экран выведен, иначе он смотрел бы на прошлый опрос
        self.assertLess(page.index("P.cur.innerHTML=fitSep(d.current||'',box);"), page.index("box.classList.toggle('termempty'"))

    def test_console_input_is_explained_on_the_page(self):
        m = re.search(r"cxcSub:\(sb,cwd\)=>'([^']*)", L.PAGE)
        self.assertIn("Ввод — под выбранной консолью", m.group(1))
        self.assertIn('id="fleetInput"', L.PAGE)


class Paused(unittest.TestCase):
    """Пауза профиля замораживает процесс Codex (SIGSTOP); консоль должна это знать, а не выглядеть живой."""

    def setUp(self):
        import signal
        import subprocess
        self.signal = signal
        self.base = tempfile.mkdtemp(prefix="pause_", dir=TMP)
        os.makedirs(os.path.join(self.base, "profile_runtime"))
        p = mock.patch.object(C, "BASE", self.base)
        p.start()
        self.addCleanup(p.stop)
        self.child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (self.child.kill(), self.child.wait()))

    def _state(self):
        with open("/proc/%d/stat" % self.child.pid) as f:
            return f.read().rsplit(")", 1)[1].split()

    def _wait_state(self, want):
        import time
        for _ in range(100):
            if (self._state()[0] == "T") == want:
                return
            time.sleep(0.02)
        self.fail("процесс не перешёл в нужное состояние")

    def _write(self, rows):
        with open(os.path.join(self.base, "profile_runtime", "codex-paused.json"), "w") as f:
            json.dump(rows, f)

    def test_frozen_process_is_reported_and_thawed_one_is_not(self):
        start = self._state()[19]
        self._write([{"pid": self.child.pid, "start": start}])
        self.assertFalse(C.frozen())  # процесс жив и не заморожен: файл сам по себе ничего не значит
        self.child.send_signal(self.signal.SIGSTOP)
        self._wait_state(True)
        self.assertTrue(C.frozen())
        self.child.send_signal(self.signal.SIGCONT)
        self._wait_state(False)
        self.assertFalse(C.frozen())

    def test_stale_file_does_not_count(self):
        self.child.send_signal(self.signal.SIGSTOP)
        self._wait_state(True)
        self._write([{"pid": self.child.pid, "start": "1"}])  # тот же pid, но другой процесс (время старта не совпало)
        self.assertFalse(C.frozen())
        dead = self.child.pid + 100000
        self._write([{"pid": dead, "start": "1"}])  # процесса нет — файл остался после остановки консоли
        self.assertFalse(C.frozen())

    def test_missing_or_broken_file_means_not_paused(self):
        self.assertFalse(C.frozen())
        path = os.path.join(self.base, "profile_runtime", "codex-paused.json")
        for raw in ("", "{", "{}", "null", '[{"pid": "x"}]', '[1, "a", null]', '[{"pid": 1}]'):
            with open(path, "w") as f:
                f.write(raw)
            self.assertFalse(C.frozen(), raw)

    def test_status_carries_paused_only_for_a_running_console(self):
        self.child.send_signal(self.signal.SIGSTOP)
        self._wait_state(True)
        self._write([{"pid": self.child.pid, "start": self._state()[19]}])
        with mock.patch.object(C, "BIN", return_value="/x/codex"), mock.patch.object(C, "PLAN", return_value=("read-only", "/w", None)):
            with mock.patch.object(C, "_pid", return_value="77"):
                st = C.status()
                self.assertIs(st.get("paused"), True)
                self.assertIs(st.get("frozen"), True)  # процесс и правда остановлен сигналом
            with mock.patch.object(C, "_pid", return_value=None):
                st = C.status()
                self.assertFalse(st["running"])
                self.assertNotIn("paused", st)  # консоль остановлена: это «не запущена», а не «на паузе»
                self.assertNotIn("frozen", st)

    def test_profile_pause_shows_even_when_the_process_was_restarted_unfrozen(self):
        # страница сама запускает консоль Codex при открытии вкладки: новый процесс не заморожен, а профиль всё ещё «пауза»
        with mock.patch.object(C, "BIN", return_value="/x/codex"), mock.patch.object(C, "PLAN", return_value=("read-only", "/w", None)), \
                mock.patch.object(C, "_pid", return_value="77"):
            self.assertNotIn("paused", C.status())  # профиль не против, процесс жив
            with mock.patch.object(C, "PAUSED", lambda: True):
                st = C.status()
                self.assertIs(st.get("paused"), True)
                self.assertNotIn("frozen", st)  # заморозки нет — страница не должна утверждать обратное
            with mock.patch.object(C, "PAUSED", mock.Mock(side_effect=RuntimeError("профили не готовы"))):
                self.assertNotIn("paused", C.status())  # сбой профилей не ломает опрос консоли

    def test_stopped_console_under_a_paused_profile_is_marked_so_the_page_does_not_autostart_it(self):
        with mock.patch.object(C, "BIN", return_value="/x/codex"), mock.patch.object(C, "PLAN", return_value=("read-only", "/w", None)), \
                mock.patch.object(C, "_pid", return_value=None):
            self.assertNotIn("profile_paused", C.status())
            with mock.patch.object(C, "PAUSED", lambda: True):
                st = C.status()
            self.assertIs(st.get("profile_paused"), True)
            self.assertFalse(st["running"])
            self.assertNotIn("paused", st)  # «на паузе» — про запущенную консоль; остановленная остаётся «не запущена»
            with mock.patch.object(C, "PAUSED", mock.Mock(side_effect=RuntimeError("профили не готовы"))):
                self.assertNotIn("profile_paused", C.status())

    def test_page_does_not_start_codex_by_itself_while_the_profile_holds_the_pause(self):
        page = L.PAGE
        self.assertIn("else if(cxAutoGo&&d.available!==false&&d.ok!==false&&!d.profile_paused&&ciAcc()){cxAutoGo=false;cxConsAct('start',true,P);}", page)
        self.assertEqual(page.count("cxConsAct('start',true"), 1)  # автозапуск один, и он за условием
        self.assertIn("(d.profile_paused&&!cxStarting?' '+tr('cxcPausedOff'):'')", page)  # плашка объясняет, почему не запустилась
        self.assertEqual(len(re.findall(r"cxcPausedOff:'", page)), 2)
        self.assertIn("async function paneGo(P){const b=P.idleGo,w=b.dataset.go;", page)
        self.assertIn("window.fleetAsk(b,tr(w==='codex'?'askStartCx':'askStartProd'),tr('askYes')))return;if(w==='codex')cxConsAct('start',false,P);else prodStart(P);", page)  # кнопкой — по-прежнему можно, но после окна «Точно?» (62045)

    def test_profiles_hand_their_pause_role_to_the_console(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(C.__file__)), "cc_profiles.py"), encoding="utf-8").read()
        self.assertIn("console.PAUSED=lambda:profiles.paused('codex')", src)  # без этого плашка видна только у замороженного процесса

    def test_page_shows_the_plate_for_a_paused_console_without_a_start_button(self):
        page = L.PAGE
        self.assertIn("d.running===false?String(d.stopped||0):d.paused?'paused':''", page)  # idleUi считает паузу поводом для плашки
        self.assertIn("d.running&&d.paused?tr('cxcPaused')+(d.frozen?' '+tr('cxcFrozen'):'')", page)  # про заморозку — только если она есть
        self.assertEqual(len(re.findall(r"cxcPaused:'", page)), 2)  # русский и английский тексты
        self.assertEqual(len(re.findall(r"cxcFrozen:'", page)), 2)
        self.assertIn("'Codex',d.running?null:{id:'codex'", page)  # кнопки у «на паузе» нет: процесс жив, запуск ничего не даст


if __name__ == "__main__":
    unittest.main()

class ClaudeFrozenSnapshot(unittest.TestCase):
    def test_snapshot_from_previous_log_and_missing_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "console.log")
            with mock.patch.object(L, "CONSOLE_LOG", path):
                self.assertEqual(L.console_frozen_snapshot(True), ("", "", 0))
                with open(path + ".prev", "wb") as f:
                    f.write("Последний экран\r\n\x1b[31mкрасный\x1b[0m".encode())
                cur, history, stopped = L.console_frozen_snapshot(True)
                self.assertIn("Последний экран", cur)
                self.assertIn("красный", cur)
                self.assertIn("color", cur)
                self.assertEqual(history, "")
                self.assertGreater(stopped, 0)
                self.assertIsNone(L.console_frozen_snapshot(False)[1])
