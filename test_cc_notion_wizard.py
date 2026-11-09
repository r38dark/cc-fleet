# Мастер «Подключить Notion AI»: установка служб из панели, файлы в манифесте, серая плитка открывает мастер (2.0.15)
# python3 -m unittest test_cc_notion_wizard -v
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import cc_notion_ai as N

HERE = os.path.dirname(os.path.abspath(__file__))


def manifest():
    return json.load(open(os.path.join(HERE, "update_manifest.json"), encoding="utf-8"))["files"]


class ShippedFiles(unittest.TestCase):
    def test_every_service_file_rides_in_the_manifest(self):
        # мастер ставит службы из BASE/notion_ai: эти файлы должны доезжать на каждый сервер установкой и обновлением
        tracked = subprocess.run(["git", "ls-files", "notion_ai"], cwd=HERE, capture_output=True, text=True).stdout.split()
        if not tracked:
            self.skipTest("нет git-метаданных")
        want = {f for f in tracked if not f.endswith("README.md")}
        have = {f["src"] for f in manifest() if f["src"].startswith("notion_ai/")}
        self.assertEqual(want, have)
        for f in manifest():
            if f["src"].startswith("notion_ai/"):
                self.assertTrue(os.path.isfile(os.path.join(HERE, f["src"])), f["src"])
                self.assertEqual(f["mode"], "755" if f["src"].endswith(("install.sh",)) or "/bin/" in f["src"] else "644", f["src"])

    def test_installer_from_the_install_folder_does_not_copy_a_file_onto_itself(self):
        # мастер запускает BASE/notion_ai/install.sh: cc_notion_ai.py там уже лежит, install не должен падать «same file»
        tmp = tempfile.mkdtemp(prefix="naiwiz_")
        base = os.path.join(tmp, "base")
        shutil.copytree(os.path.join(HERE, "notion_ai"), os.path.join(base, "notion_ai"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(HERE, "cc_notion_ai.py"), os.path.join(base, "cc_notion_ai.py"))
        env = dict(os.environ, CC_LIMITS_BASE=base, NAI_TEST="1", NAI_SKIP_DEPS="1", NAI_NO_SYSTEMCTL="1",
                   NAI_WEB=os.path.join(tmp, "web"), NAI_BIN=os.path.join(tmp, "bin"), NAI_UNITS=os.path.join(tmp, "units"),
                   NAI_TOKEN_COPY=os.path.join(tmp, "token_copy"))
        r = subprocess.run(["bash", os.path.join(base, "notion_ai", "install.sh")], env=env, capture_output=True, text=True, timeout=60, cwd=base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("модуль панели уже на месте", r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(tmp, "web", "server.py")))
        self.assertTrue(os.path.isfile(os.path.join(tmp, "units", "notion-delegate.service")))
        self.assertTrue(os.path.isfile(os.path.join(base, "notion_ai.json")))


class InstallState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="naiwiz_")
        os.makedirs(os.path.join(self.tmp, "notion_ai"))
        open(os.path.join(self.tmp, "notion_ai", "install.sh"), "w").write("#!/bin/bash\n")
        self.units = {"notion-delegate.service": "inactive", "cc-notion-install.service": "inactive"}
        self.installed = False
        for p in (mock.patch.object(N, "NAI_BASE", self.tmp),
                  mock.patch.object(N, "_run", side_effect=lambda a, t=30: (0, self.units.get(a[-1], ""))),
                  mock.patch.object(N, "notion_installed", side_effect=lambda: self.installed)):
            p.start()
            self.addCleanup(p.stop)

    def log(self, text):
        open(os.path.join(self.tmp, "notion_install.log"), "w", encoding="utf-8").write(text)

    def test_idle_before_anything_started(self):
        s = N.install_state()
        self.assertEqual((s["installed"], s["running"], s["phase"], s["src"]), (False, False, "idle", True))

    def test_phases_running_error_done(self):
        self.units["cc-notion-install.service"] = "active"
        self.assertEqual(N.install_state()["phase"], "running")
        self.units["cc-notion-install.service"] = "inactive"
        self.log("[notion-ai] что-то\nRC=1\n")
        s = N.install_state()
        self.assertEqual((s["phase"], s["rc"]), ("error", 1))
        self.installed, self.units["notion-delegate.service"] = True, "active"
        self.log("[notion-ai] Готово\nRC=0\n")
        s = N.install_state()
        self.assertEqual((s["phase"], s["installed"], s["rc"]), ("done", True, 0))

    def test_log_is_tailed_and_colours_are_stripped(self):
        self.log("\n".join("\x1b[32mстрока %d\x1b[0m" % i for i in range(40)) + "\n")
        lines = N.install_state()["log"]
        self.assertEqual(len(lines), 14)
        self.assertEqual(lines[-1], "строка 39")

    def test_no_install_files_is_reported(self):
        os.remove(os.path.join(self.tmp, "notion_ai", "install.sh"))
        self.assertFalse(N.install_state()["src"])
        r = N.install_start()
        self.assertFalse(r["ok"])
        self.assertIn("обнови балансер", r["message"])

    def test_start_runs_the_installer_as_a_separate_systemd_unit(self):
        with mock.patch.object(N.shutil, "which", return_value="/usr/bin/systemd-run"), \
                mock.patch.object(N.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            r = N.install_start()
        self.assertTrue(r["ok"], r)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "systemd-run")
        self.assertIn("--unit=cc-notion-install", argv)          # отдельная служба: перезапуск панели в конце установки её не прервёт
        self.assertIn("--setenv=CC_LIMITS_BASE=" + self.tmp, argv)
        self.assertEqual(argv[argv.index("sh"):argv.index("sh") + 2], ["sh", "-c"])
        self.assertIn(os.path.join(self.tmp, "notion_ai", "install.sh"), argv)
        self.assertIn(os.path.join(self.tmp, "notion_install.log"), argv)
        self.assertIn('echo "RC=$?"', argv[argv.index("-c") + 1])  # код завершения попадает в журнал, по нему мастер видит итог

    def test_start_does_nothing_when_installed_or_already_running(self):
        with mock.patch.object(N.subprocess, "run") as run:
            self.installed, self.units["notion-delegate.service"] = True, "active"
            self.assertIn("уже стоят", N.install_start()["message"])
            self.installed, self.units["notion-delegate.service"] = False, "inactive"
            self.units["cc-notion-install.service"] = "active"
            self.assertIn("уже идёт", N.install_start()["message"])
        run.assert_not_called()

    def test_start_failures_are_reported(self):
        with mock.patch.object(N.shutil, "which", return_value=None):
            self.assertIn("systemd", N.install_start()["message"])
        with mock.patch.object(N.shutil, "which", return_value="/x"), \
                mock.patch.object(N.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "Failed")):
            r = N.install_start()
        self.assertFalse(r["ok"])
        self.assertIn("Failed", r["message"])


class PageWiring(unittest.TestCase):
    def setUp(self):
        self.page = N.inject('<html><head></head><body>' + N.CFG_ANCHOR + '<script>var x=1</script></body></html>')

    def test_wizard_is_injected_once(self):
        self.assertEqual(self.page.count('id="naiWizScript"'), 1)
        self.assertEqual(N.inject(self.page).count('id="naiWizScript"'), 1)
        self.assertIn("window.naiWizOpen=function", self.page)

    def test_grey_tile_opens_the_wizard_not_a_link(self):
        self.assertIn("else if(window.naiWizOpen)window.naiWizOpen();else window.open(", N.UI)
        self.assertIn("Подключить Notion AI", N.UI)
        self.assertNotIn("run sudo ./install.sh from the balancer folder", N.UI)

    def test_settings_have_a_wizard_button(self):
        self.assertIn('id="naiWizOpen"', N.CFG_UI)
        self.assertIn("window.naiWizOpen()", N.CFG_UI)

    def test_routes_exist(self):
        src = open(os.path.join(HERE, "cc_notion_ai.py"), encoding="utf-8").read()
        self.assertIn("'/api/notion-ai/install'", src)
        self.assertIn("'/api/notion-ai/install/start'", src)
        self.assertIn("result = install_start()", src)

    @unittest.skipUnless(shutil.which("node"), "нет node")
    def test_wizard_script_is_valid_javascript(self):
        m = re.search(r'<script id="naiWizScript">(.*?)</script>', N.WIZ_UI, re.S)
        self.assertIsNotNone(m)
        path = os.path.join(tempfile.mkdtemp(prefix="naiwiz_"), "wiz.js")
        open(path, "w", encoding="utf-8").write(m.group(1))
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_step_has_its_text_in_both_languages(self):
        js = N.WIZ_UI
        for k in ("install", "chat", "login", "token", "key", "check", "agent"):
            self.assertIn("%s:['" % k, js)
        self.assertGreaterEqual(js.count("T('"), 30)   # ru/en пары


class LoginCode(unittest.TestCase):
    """Notion присылает код из 6 букв («kvpugs»): служба и поля ввода обязаны принимать буквы."""

    def put_code(self, code, state="login_wait", busy=False):
        src = open(os.path.join(HERE, "notion_ai", "web", "server.py"), encoding="utf-8").read()
        m = re.search(r"def put_code\(code\):.*?(?=\n\ndef )", src, re.S)
        self.assertIsNotNone(m)
        tmp = tempfile.mkdtemp(prefix="naicode_")
        ns = {"re": re, "os": os, "D": tmp, "AUTH": {"state": state}, "LOGIN": {"busy": busy}}
        exec(m.group(0), ns)
        ns["put_code"](code)
        return open(os.path.join(tmp, "code.txt"), encoding="utf-8").read()

    def test_letters_and_digits_are_accepted(self):
        for c in ("kvpugs", "KVPUGS", "123456", "ab12cd", " kvpugs "):
            self.assertEqual(self.put_code(c), c.strip())

    def test_wrong_length_or_symbols_are_rejected(self):
        for c in ("kvpug", "kvpugsx", "kvp ugs", "kvpug-", "", None):
            with self.assertRaises(ValueError, msg=repr(c)):
                self.put_code(c)

    def test_code_is_not_taken_when_no_login_is_waiting(self):
        with self.assertRaises(RuntimeError):
            self.put_code("kvpugs", state="ok", busy=False)

    def test_panel_and_wizard_fields_are_not_digit_only(self):
        for html in (N.CFG_UI, N.WIZ_UI):
            for field in ("naiCodeIn", "nwCode"):
                if 'id="%s"' % field in html:
                    tag = html[html.index('id="%s"' % field):][:300]
                    tag = tag[:tag.index(">")]
                    self.assertNotIn("numeric", tag, field)
                    self.assertNotIn('maxlength="6"', tag, field)
        self.assertNotIn("6 цифр", N.CFG_UI + N.WIZ_UI)
        self.assertNotIn("6 digits", N.WIZ_UI)

    def test_login_start_message_does_not_promise_digits(self):
        with mock.patch.object(N, "_delegate", return_value={}):
            self.assertNotIn("цифр", N.login_start()["message"])


class ChatField(unittest.TestCase):
    """Notion сменил подсказку поля ввода в чате агента на «Chat with <имя>»: служба обязана находить и её."""

    def test_no_wait_for_the_old_hint_only(self):
        for name in ("server.py", "agent_ops.py", "login2.py"):
            src = open(os.path.join(HERE, "notion_ai", "web", name), encoding="utf-8").read()
            self.assertNotIn('get_by_placeholder("Ask Notion AI")', src, name)
            self.assertIn('placeholder^="Chat with"', src, name)
            self.assertIn('placeholder^="Ask Notion AI"', src, name)

    def test_service_files_compile(self):
        import py_compile
        for name in ("server.py", "agent_ops.py", "login2.py", "nagents.py", "notion_ai_view.py", "notion_ai_tg.py"):
            py_compile.compile(os.path.join(HERE, "notion_ai", "web", name), cfile=os.path.join(tempfile.mkdtemp(), "x.pyc"), doraise=True)


if __name__ == "__main__":
    unittest.main()
