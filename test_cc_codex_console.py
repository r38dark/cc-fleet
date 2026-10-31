# Консоль Codex: запуск/останов, зеркало экрана из лога screen, маршруты /api/console?s=codex и вкладки на странице.
# python3 -m unittest test_cc_codex_console -v
import os
import re
import tempfile
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
