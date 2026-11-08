#!/usr/bin/env python3
# Установка Codex из панели («Подключить Codex»): поддельные node и npm, настоящие процессы и группы процессов.
# Запуск: python3 -m unittest test_cc_codex_install -v
import json, os, stat, tempfile, textwrap, threading, time, unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="cccxinst_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_codex  # noqa: E402
import cc_limits as L  # noqa: E402

FAKE_NODE = '#!/bin/sh\necho "${FAKE_NODE_VER:-v20.1.0}"\n'
# поддельный npm: install -g --prefix P pkg → кладёт P/bin/codex; режимы — переменной FAKE_NPM
FAKE_NPM = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, subprocess, sys, time
    a = sys.argv[1:]
    prefix = a[a.index("--prefix") + 1]
    open(os.environ["FAKE_NPM_LOG"], "a").write(" ".join(a) + "\\n")
    mode = os.environ.get("FAKE_NPM", "ok")
    print("npm http fetch GET 200 https://registry.npmjs.org/@openai%2fcodex", flush=True)
    if mode == "slow":
        child = subprocess.Popen(["sleep", "300"])
        open(os.environ["FAKE_NPM_CHILD"], "w").write(str(child.pid))
        time.sleep(300)
    if mode == "fail":
        print("npm error code ENOTFOUND", flush=True)
        sys.exit(1)
    if mode == "nocodex":
        sys.exit(0)
    os.makedirs(os.path.join(prefix, "bin"), exist_ok=True)
    path = os.path.join(prefix, "bin", "codex")
    body = '#!/bin/sh\\necho broken >&2\\nexit 3\\n' if mode == "badbin" else '#!/bin/sh\\necho "codex-cli 0.166.0"\\n'
    open(path, "w").write(body)
    os.chmod(path, 0o755)
    print("added 1 package in 2s")
''')


# поддельный screen: пишет аргументы в FAKE_SCREEN_LOG; hardcopy кладёт в файл «экран консоли» из FAKE_SCREEN_TEXT; FAKE_SCREEN=dead — сессии нет
FAKE_SCREEN = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, sys
    a = sys.argv[1:]
    open(os.environ["FAKE_SCREEN_LOG"], "a").write(repr(a) + "\\n")
    if os.environ.get("FAKE_SCREEN") == "dead":
        sys.exit(1)
    if "hardcopy" in a:
        open(a[-1], "w").write(os.environ.get("FAKE_SCREEN_TEXT", ""))
''')


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Install(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="t", dir=TMP)
        self.tools = os.path.join(self.dir, "tools")
        os.makedirs(self.tools)
        write_exec(os.path.join(self.tools, "node"), FAKE_NODE)
        write_exec(os.path.join(self.tools, "npm"), FAKE_NPM)
        self.log = os.path.join(self.dir, "npm.log")
        self.child = os.path.join(self.dir, "child.pid")
        self.prefix = os.path.join(self.dir, "codex-cli")
        self.saved = []
        env = {"PATH": self.tools + os.pathsep + "/usr/bin:/bin", "FAKE_NPM_LOG": self.log, "FAKE_NPM_CHILD": self.child}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for name, val in (("_NODE_DIRS", ()), ("INSTALL_PREFIX", lambda: self.prefix),
                          ("ON_INSTALLED", self.saved.append), ("INSTALL_TTL", 60)):
            q = mock.patch.object(cc_codex, name, val)
            q.start()
            self.addCleanup(q.stop)
        cc_codex._inst = {"state": "idle"}

    def wait(self, states, limit=20):
        end = time.time() + limit
        while time.time() < end:
            st = cc_codex.install_status()
            if st["state"] in states:
                return st
            time.sleep(0.05)
        self.fail("состояние %s не наступило: %r" % (states, cc_codex.install_status()))

    def test_node_info_ready_old_and_missing(self):
        self.assertEqual(cc_codex.node_info(), {"node": "v20.1.0", "npm": True, "ready": True})
        with mock.patch.dict(os.environ, {"FAKE_NODE_VER": "v14.21.3"}):
            i = cc_codex.node_info()
            self.assertEqual((i["node"], i["ready"]), ("v14.21.3", False))  # старый Node не годится
        os.remove(os.path.join(self.tools, "npm"))
        with mock.patch.dict(os.environ, {"PATH": self.tools}):  # настоящий npm из /usr/bin в поиск не попадает
            i = cc_codex.node_info()
            self.assertEqual((i["node"], i["npm"], i["ready"]), ("v20.1.0", False, False))  # есть Node, нет npm
            os.remove(os.path.join(self.tools, "node"))
            self.assertEqual(cc_codex.node_info(), {"node": None, "npm": False, "ready": False})

    def test_success_installs_to_own_prefix_and_remembers_path(self):
        ok, msg = cc_codex.install_start()
        self.assertEqual((ok, msg), (True, ""))
        st = self.wait(("done", "failed"))
        self.assertEqual(st["state"], "done", st)
        self.assertEqual(st["version"], "codex-cli 0.166.0")
        bin_path = os.path.join(self.prefix, "bin", "codex")
        self.assertEqual(self.saved, [bin_path])  # путь отдан панели ровно один раз
        self.assertTrue(os.access(bin_path, os.X_OK))
        # команда фиксированная: ровно пакет из NPM_PKG и своя папка, ничего от человека
        self.assertEqual(open(self.log).read().split(), ["install", "-g", "--prefix", self.prefix, cc_codex.NPM_PKG])

    def test_npm_failure_shows_tail_and_does_not_save(self):
        with mock.patch.dict(os.environ, {"FAKE_NPM": "fail"}):
            cc_codex.install_start()
            st = self.wait(("done", "failed"))
        self.assertEqual(st["state"], "failed")
        self.assertIn("ENOTFOUND", st["err"])
        self.assertEqual(self.saved, [])
        # после ошибки можно повторить — и тогда получится
        cc_codex.install_start()
        self.assertEqual(self.wait(("done", "failed"))["state"], "done")

    def test_npm_ok_but_no_binary_is_failure(self):
        with mock.patch.dict(os.environ, {"FAKE_NPM": "nocodex"}):
            cc_codex.install_start()
            st = self.wait(("done", "failed"))
        self.assertEqual(st["state"], "failed")
        self.assertEqual(self.saved, [])

    def test_binary_that_does_not_start_is_failure(self):
        with mock.patch.dict(os.environ, {"FAKE_NPM": "badbin"}):
            cc_codex.install_start()
            st = self.wait(("done", "failed"))
        self.assertEqual(st["state"], "failed")
        self.assertIn("не запускается", st["err"])
        self.assertEqual(self.saved, [])

    def test_saving_path_error_is_reported(self):
        cc_codex.ON_INSTALLED = mock.Mock(side_effect=OSError("диск полон"))
        cc_codex.install_start(lang="en")
        st = self.wait(("done", "failed"))
        self.assertEqual(st["state"], "failed")
        self.assertIn("диск полон", st["err"])
        self.assertIn("saving its path failed", st["err"])

    def test_no_node_refuses_without_starting_anything(self):
        with mock.patch.dict(os.environ, {"PATH": self.dir}):
            ok, msg = cc_codex.install_start()
            self.assertFalse(ok)
            self.assertIn("Node.js", msg)
            ok, msg = cc_codex.install_start(lang="en")
            self.assertIn("required", msg)
        self.assertFalse(os.path.exists(self.log))
        self.assertEqual(cc_codex.install_status()["state"], "idle")

    def test_old_node_refuses(self):
        with mock.patch.dict(os.environ, {"FAKE_NODE_VER": "v12.0.0"}):
            ok, msg = cc_codex.install_start()
        self.assertFalse(ok)
        self.assertIn("слишком старый", msg)

    def test_second_start_while_running_does_not_spawn_second_npm(self):
        with mock.patch.dict(os.environ, {"FAKE_NPM": "slow"}):
            self.assertTrue(cc_codex.install_start()[0])
            self.assertTrue(cc_codex.install_start()[0])
            end = time.time() + 10
            while time.time() < end and not os.path.exists(self.child):
                time.sleep(0.05)
            self.assertEqual(len(open(self.log).read().strip().splitlines()), 1)
            self.assertEqual(cc_codex.install_status()["state"], "running")
            cc_codex.install_cancel()
            self.wait(("idle",))

    def test_cancel_kills_whole_process_group(self):
        with mock.patch.dict(os.environ, {"FAKE_NPM": "slow"}):
            cc_codex.install_start()
            end = time.time() + 10
            while time.time() < end and not os.path.exists(self.child):
                time.sleep(0.05)
            pid = int(open(self.child).read())
            self.assertTrue(cc_codex.install_cancel())
            st = self.wait(("idle",))
        self.assertIsNone(st["err"])
        self.assertEqual(self.saved, [])
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):  # npm — обёртка, потомок sleep тоже должен умереть
            os.kill(pid, 0)
        self.assertFalse(cc_codex.install_cancel())  # отменять нечего

    def test_hang_is_killed_by_timeout(self):
        with mock.patch.object(cc_codex, "INSTALL_TTL", 1), mock.patch.dict(os.environ, {"FAKE_NPM": "slow"}):
            cc_codex.install_start()
            st = self.wait(("failed",), limit=15)
        self.assertIn("15 минут", st["err"])

    def test_log_keeps_only_last_lines(self):
        cc_codex.install_start()
        st = self.wait(("done",))
        self.assertIn("added 1 package", st["log"])
        self.assertNotIn("\x1b", st["log"])


class Routes(unittest.TestCase):
    """Маршруты панели: кнопка работает, пока Codex ещё нет, и закрыта токеном."""

    @classmethod
    def setUpClass(cls):
        import http.server
        # исходный обработчик панели: у наследников (cc_fleet и др.) маршрут /api/chatgpt/bridge свой, и результат зависел бы от порядка импорта модулей в общем прогоне
        handler = next(c for c in L.H.__mro__ if c.__module__ == L.__name__)
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        c = L.cfg()
        c.pop("codex_bin", None)
        c["hook_token"] = "t-secret"
        L.jsave(L.CONFIG, c)
        self.dir = tempfile.mkdtemp(prefix="r", dir=TMP)
        self.tools = os.path.join(self.dir, "tools")
        os.makedirs(self.tools)
        write_exec(os.path.join(self.tools, "node"), FAKE_NODE)
        write_exec(os.path.join(self.tools, "npm"), FAKE_NPM)
        write_exec(os.path.join(self.tools, "screen"), FAKE_SCREEN)
        self.screen_log = os.path.join(self.dir, "screen.log")
        env = {"PATH": self.tools + os.pathsep + "/usr/bin:/bin", "FAKE_NPM_LOG": os.path.join(self.dir, "npm.log"),
               "FAKE_NPM_CHILD": os.path.join(self.dir, "child"), "FAKE_SCREEN_LOG": self.screen_log,
               "FAKE_SCREEN_TEXT": "$ claude\n> " + cc_codex.SETUP_MARK + " Please connect Codex...\n"}
        q0 = mock.patch.object(L, "SETUP_PAUSE", (0, 0))  # паузы между вводами нужны живой консоли, поддельному screen — нет
        q0.start()
        self.addCleanup(q0.stop)
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for name, val in (("_NODE_DIRS", ()), ("INSTALL_PREFIX", lambda: os.path.join(self.dir, "codex-cli"))):
            q = mock.patch.object(cc_codex, name, val)
            q.start()
            self.addCleanup(q.stop)
        # настоящий путь запоминания (ON_INSTALLED из cc_limits) пишет в config.json нашей временной папки
        cc_codex._inst = {"state": "idle"}
        self.addCleanup(lambda: setattr(cc_codex, "_inst", {"state": "idle"}))

    def call(self, method, path, body=None, token="t-secret"):
        import urllib.error, urllib.request
        sep = "&" if "?" in path else "?"
        url = self.url + path + (sep + "token=" + token if token else "")
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_bridge_without_codex_reports_install_info(self):
        with mock.patch.object(cc_codex, "find_bin", return_value=None):  # на машине, где Codex уже стоит, поиск находил бы настоящий
            code, d = self.call("GET", "/api/chatgpt/bridge")
        self.assertEqual(code, 200)
        self.assertFalse(d["available"], d)
        self.assertEqual(d["install"]["state"], "idle")
        self.assertTrue(d["install"]["ready"])  # Node и npm нашлись

    def test_install_requires_token(self):
        for method, path, body in (("GET", "/api/chatgpt/install", None), ("POST", "/api/chatgpt/install/start", {}),
                                   ("POST", "/api/chatgpt/install/cancel", {})):
            self.assertEqual(self.call(method, path, body, token="wrong")[0], 403, path)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "npm.log")))  # без токена npm не запускался

    def test_full_install_through_http_enables_codex(self):
        code, d = self.call("POST", "/api/chatgpt/install/start", {})
        self.assertEqual((code, d["ok"]), (200, True))
        end = time.time() + 20
        while time.time() < end:
            code, d = self.call("GET", "/api/chatgpt/install")
            if d["state"] in ("done", "failed"):
                break
            time.sleep(0.1)
        self.assertEqual(d["state"], "done", d)
        # путь попал в config.json, и теперь панель считает, что Codex есть
        want = os.path.join(self.dir, "codex-cli", "bin", "codex")
        self.assertEqual(L.cfg().get("codex_bin"), want)
        code, b = self.call("GET", "/api/chatgpt/bridge")
        self.assertTrue(b["available"])
        # второй раз ставить нечего
        code, d = self.call("POST", "/api/chatgpt/install/start", {"lang": "en"})
        self.assertFalse(d["ok"])
        self.assertIn("already installed", d["message"])

    def test_start_without_node_returns_message_not_error(self):
        with mock.patch.dict(os.environ, {"PATH": self.dir}):
            code, d = self.call("POST", "/api/chatgpt/install/start", {})
        self.assertEqual(code, 200)
        self.assertFalse(d["ok"])
        self.assertIn("Node.js", d["message"])

    def test_cancel_route(self):
        with mock.patch.dict(os.environ, {"FAKE_NPM": "slow"}):
            self.call("POST", "/api/chatgpt/install/start", {})
            end = time.time() + 10
            while time.time() < end and not os.path.exists(os.path.join(self.dir, "child")):
                time.sleep(0.05)
            code, d = self.call("POST", "/api/chatgpt/install/cancel", {})
        self.assertEqual(code, 200)
        end = time.time() + 10
        while time.time() < end and cc_codex.install_status()["state"] != "idle":
            time.sleep(0.05)
        self.assertEqual(cc_codex.install_status()["state"], "idle")

    # ---- «Поручить Claude» и «Скопировать промт» ----
    def screen_calls(self):
        if not os.path.exists(self.screen_log):
            return []
        import ast
        with open(self.screen_log) as f:
            return [ast.literal_eval(x) for x in f.read().splitlines()]

    def test_prompt_and_ask_require_token_and_touch_nothing_without_it(self):
        self.assertEqual(self.call("GET", "/api/chatgpt/install/prompt", token="wrong")[0], 403)
        self.assertEqual(self.call("POST", "/api/chatgpt/install/ask-claude", {}, token="wrong")[0], 403)
        self.assertEqual(self.screen_calls(), [])  # без токена в консоль ничего не уходит

    def test_prompt_is_fixed_safe_for_screen_and_has_no_secret(self):
        code, d = self.call("GET", "/api/chatgpt/install/prompt")
        self.assertEqual(code, 200)
        p = d["prompt"]
        self.assertTrue(p.startswith(cc_codex.SETUP_MARK))
        self.assertTrue(p.isascii())  # кодировка консоли не вмешается
        for bad in ("^", "\\", "\n", "\r"):
            self.assertNotIn(bad, p)  # screen stuff читает ^x и \ooo как управляющие
        self.assertLess(len(p), 1500)
        self.assertIn("127.0.0.1:%d" % L.cfg().get("port", 8877), p)
        self.assertIn(L.CONFIG, p)
        self.assertIn("X-CC-Token", p)
        self.assertNotIn("t-secret", p)  # сам токен в текст не попадает — Claude читает его из config.json
        self.assertIn("Russian", p)
        self.assertIn("English", self.call("GET", "/api/chatgpt/install/prompt?lang=en")[1]["prompt"])

    def test_ask_claude_types_prompt_then_enter_and_sees_it_on_screen(self):
        code, d = self.call("POST", "/api/chatgpt/install/ask-claude", {})
        self.assertEqual((code, d["ok"], d["seen"]), (200, True, True))
        calls = self.screen_calls()
        base = ["-S", L.cfg().get("screen_session", "claude"), "-p", "0", "-X"]
        want = L.codex_setup_prompt("ru")
        n = -(-len(want) // L.SETUP_CHUNK)  # число кусков
        self.assertGreater(n, 1)  # длиннее предела screen stuff — одним вводом нельзя
        chunks = calls[:n]
        for c in chunks:
            self.assertEqual(c[:len(base) + 1], base + ["stuff"])
            self.assertLessEqual(len(c[-1].encode()), L.SETUP_CHUNK)  # ни один ввод не длиннее предела
        self.assertEqual("".join(c[-1] for c in chunks), want)  # куски вместе — ровно промт, без потерь
        self.assertEqual(calls[n], base + ["stuff", "\r"])  # Enter — отдельным вводом
        self.assertEqual(calls[n + 1][:len(base) + 1], base + ["hardcopy"])  # потом смотрим экран
        self.assertEqual(len(calls), n + 2)

    def test_ask_claude_reports_when_prompt_is_not_on_screen(self):
        with mock.patch.dict(os.environ, {"FAKE_SCREEN_TEXT": "claude is busy...\n"}):
            code, d = self.call("POST", "/api/chatgpt/install/ask-claude", {})
        self.assertEqual((d["ok"], d["seen"]), (True, False))  # ввод принят, но метки на экране нет — человек увидит подсказку

    def test_ask_claude_without_session_says_copy_it(self):
        with mock.patch.dict(os.environ, {"FAKE_SCREEN": "dead"}):
            code, d = self.call("POST", "/api/chatgpt/install/ask-claude", {"lang": "en"})
        self.assertEqual((code, d["ok"], d["seen"]), (200, False, False))
        self.assertIn("Copy the prompt", d["message"])
        self.assertEqual(len(self.screen_calls()), 1)  # первый же ввод не принят — дальше не идём

    def test_ask_claude_ignores_any_text_from_the_request(self):
        self.call("POST", "/api/chatgpt/install/ask-claude", {"text": "rm -rf /", "prompt": "evil", "cmd": "evil"})
        with open(self.screen_log) as f:
            log = f.read()
        self.assertNotIn("evil", log)
        self.assertNotIn("rm -rf", log)

    def test_ask_claude_when_codex_already_installed_does_nothing(self):
        c = L.cfg()
        fake = os.path.join(self.dir, "codex")
        write_exec(fake, "#!/bin/sh\necho codex-cli 1\n")
        c["codex_bin"] = fake
        L.jsave(L.CONFIG, c)
        code, d = self.call("POST", "/api/chatgpt/install/ask-claude", {"lang": "en"})
        self.assertFalse(d["ok"])
        self.assertIn("already installed", d["message"])
        self.assertEqual(self.screen_calls(), [])


if __name__ == "__main__":
    unittest.main()
