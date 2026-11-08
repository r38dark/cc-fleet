# Мастер «Второй сервер»: проверка, установка недостающего, подключение, обратный ключ, отключение, маршруты
# python3 -m unittest test_cc_remote_setup -v
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

import cc_remote as R
import cc_remote_setup as S

PROBE_OK = "uid=0\nos=Ubuntu 24.04\npython3=/usr/bin/python3\ntmux=/usr/bin/tmux\nrsync=/usr/bin/rsync\napt=/usr/bin/apt-get\nclaude=/usr/bin/claude\nclaude_other=/usr/bin/claude\nlogin=yes\ntg=/root/.claude/channels/telegram\n"
PROBE_BARE = "uid=0\nos=Debian 12\npython3=/usr/bin/python3\ntmux=\nrsync=\napt=/usr/bin/apt-get\nclaude=\nclaude_other=\nlogin=\ntg=\n"
PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBACKKEYforTESTSonly cc-fleet-back"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccrs_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = (S.KEY_PATH, S.AUTH_FILE, R.MEMBERS_FILE, R.BASE, S.BASE, R.STATE_FILE)
        S.KEY_PATH = os.path.join(self.tmp, "remote_key")
        S.AUTH_FILE = os.path.join(self.tmp, "ssh", "authorized_keys")
        R.MEMBERS_FILE = os.path.join(self.tmp, "remote_members.json")
        R.STATE_FILE = os.path.join(self.tmp, "remote_state.json")   # первый опрос пары после «Подключить» пишет сюда, а не в папку репозитория
        S.BASE = R.BASE = self.tmp
        self.addCleanup(self.restore)
        self.calls = []
        S._job.update(state="idle", title="", text="", checks=None)

    def restore(self):
        S.KEY_PATH, S.AUTH_FILE, R.MEMBERS_FILE, R.BASE, S.BASE, R.STATE_FILE = self.saved

    def ssh(self, replies):
        """Подставной R.ssh_run: ответы по порядку или по подстроке команды."""
        def fake(m, cmd, timeout=25, inp=None):
            self.calls.append((m, cmd))
            for key, rep in replies:
                if key is None or key in cmd:
                    return rep
            return 0, ""
        return mock.patch.object(R, "ssh_run", side_effect=fake)

    def fake_key(self):
        os.makedirs(os.path.dirname(S.KEY_PATH), exist_ok=True)
        open(S.KEY_PATH, "w").write("PRIVATE")
        open(S.KEY_PATH + ".pub", "w").write("ssh-ed25519 PANELPUB cc-fleet-panel\n")


class Fields(Base):
    def test_valid(self):
        ok, msg, f = S.valid_fields("203.0.113.10", "2222", "root", "cc2", "198.51.100.7")
        self.assertTrue(ok, msg)
        self.assertEqual(f, {"host": "203.0.113.10", "port": 2222, "user": "root", "tmux": "cc2", "back_host": "198.51.100.7"})
        ok, _, f = S.valid_fields("server.example.org", "", "", "", "")
        self.assertTrue(ok)
        self.assertEqual((f["port"], f["user"], f["tmux"]), (22, "root", "ccfleet"))

    def test_invalid(self):
        for args in (("bad host", 22, "root", "t", ""), ("", 22, "root", "t", ""), ("h;rm -rf /", 22, "root", "t", ""),
                     ("1.2.3.4", 0, "root", "t", ""), ("1.2.3.4", 70000, "root", "t", ""), ("1.2.3.4", "x", "root", "t", ""),
                     ("1.2.3.4", 22, "ubuntu", "t", ""), ("1.2.3.4", 22, "root", "плохо", ""), ("1.2.3.4", 22, "root", "a b", ""),
                     ("1.2.3.4", 22, "root", "t", "back host")):
            ok, msg, _ = S.valid_fields(*args)
            self.assertFalse(ok, args)
            self.assertTrue(msg)

    def test_member_has_port_only_when_not_22(self):
        self.fake_key()
        self.assertNotIn("port", S._member("1.2.3.4", 22, "root", "t"))
        self.assertEqual(S._member("1.2.3.4", 2200, "root", "t")["port"], 2200)


class Key(Base):
    def test_panel_key_is_created_once_with_private_mode(self):
        k = S.panel_key()
        self.assertTrue(k["pub"].startswith("ssh-ed25519 "), k)
        self.assertEqual(stat.S_IMODE(os.stat(S.KEY_PATH).st_mode), 0o600)
        self.assertEqual(S.panel_key()["pub"], k["pub"])  # второй раз тот же ключ

    def test_back_host_from_public_url(self):
        json.dump({"public_url": "https://panel.example.org"}, open(os.path.join(self.tmp, "config.json"), "w"))
        self.assertEqual(S.default_back_host(), "panel.example.org")


class Probe(Base):
    def setUp(self):
        super().setUp()
        self.fake_key()
        self.m = S._member("203.0.113.10", 22, "root", "cc2")

    def test_everything_present(self):
        with self.ssh([(None, (0, PROBE_OK))]):
            r = S.probe(self.m)
        self.assertTrue(r["ready"])
        self.assertEqual(r["missing"], [])
        self.assertTrue(all(c["ok"] for c in r["checks"]))

    def test_bare_server_lists_what_to_install(self):
        with self.ssh([(None, (0, PROBE_BARE))]):
            r = S.probe(self.m)
        self.assertFalse(r["ready"])
        self.assertEqual(r["missing"], ["tmux", "rsync"])
        self.assertTrue(r["apt"])
        by = {c["id"]: c for c in r["checks"]}
        self.assertFalse(by["tmux"]["ok"])
        self.assertIn("Установить недостающее", by["tmux"]["hint"])
        self.assertFalse(by["claude"]["ok"])
        self.assertTrue(by["claude"]["block"])
        self.assertFalse(by["login"]["ok"])
        self.assertFalse(by["login"]["block"])   # вход в Claude и Telegram — не обязательны для подключения
        self.assertFalse(by["tg"]["block"])

    def test_claude_elsewhere_gets_symlink_hint(self):
        out = PROBE_OK.replace("claude=/usr/bin/claude", "claude=").replace("claude_other=/usr/bin/claude", "claude_other=/usr/local/bin/claude")
        with self.ssh([(None, (0, out))]):
            r = S.probe(self.m)
        c = [x for x in r["checks"] if x["id"] == "claude"][0]
        self.assertFalse(c["ok"])
        self.assertIn("ln -sf /usr/local/bin/claude /usr/bin/claude", c["hint"])

    def test_not_root(self):
        with self.ssh([(None, (0, PROBE_OK.replace("uid=0", "uid=1000")))]):
            r = S.probe(self.m)
        self.assertFalse(r["ready"])
        self.assertFalse([c for c in r["checks"] if c["id"] == "root"][0]["ok"])

    def test_ssh_failures_explain_what_to_do(self):
        for code, text, word in ((255, "Permission denied (publickey).", "authorized_keys"), (124, "timeout", "адрес"), (1, "", "ssh -i")):
            with self.ssh([(None, (code, text))]):
                r = S.probe(self.m)
            self.assertFalse(r["ready"])
            self.assertEqual(len(r["checks"]), 1)
            self.assertIn(word, r["checks"][0]["hint"], code)

    def test_check_adds_local_tools_and_validates(self):
        with self.ssh([(None, (0, PROBE_OK))]), mock.patch.object(S, "local_checks", return_value=[{"id": "local_rsync", "ok": False, "block": True, "label": "x", "hint": "y"}]):
            r = S.check({"host": "203.0.113.10"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["ready"])   # на этом сервере нет rsync — подключать рано
        self.assertEqual(r["checks"][0]["id"], "local_rsync")
        self.assertFalse(S.check({"host": "плохо"})["ok"])


class Install(Base):
    def setUp(self):
        super().setUp()
        self.fake_key()

    def test_installs_only_missing_with_apt(self):
        with self.ssh([("apt-get install", (0, "")), (None, (0, PROBE_BARE))]):
            ok, msg = S.install_missing({"host": "203.0.113.10"})
        self.assertTrue(ok, msg)
        cmd = [c for _, c in self.calls if "apt-get install" in c][0]
        self.assertIn("tmux rsync", cmd)
        self.assertNotIn("python3", cmd.split("install")[1])

    def test_nothing_missing(self):
        with self.ssh([(None, (0, PROBE_OK))]):
            ok, msg = S.install_missing({"host": "203.0.113.10"})
        self.assertTrue(ok)
        self.assertIn("уже есть", msg)
        self.assertFalse([c for _, c in self.calls if "apt-get install" in c])

    def test_no_apt_and_no_ssh(self):
        with self.ssh([(None, (0, PROBE_BARE.replace("apt=/usr/bin/apt-get", "apt=")))]):
            ok, msg = S.install_missing({"host": "203.0.113.10"})
        self.assertFalse(ok)
        self.assertIn("вручную", msg)
        with self.ssh([(None, (255, "denied"))]):
            ok, msg = S.install_missing({"host": "203.0.113.10"})
        self.assertFalse(ok)
        self.assertIn("ключ", msg)

    def test_apt_failure_is_reported(self):
        with self.ssh([("apt-get install", (100, "E: Unable to locate package")), (None, (0, PROBE_BARE))]):
            ok, msg = S.install_missing({"host": "203.0.113.10"})
        self.assertFalse(ok)
        self.assertIn("Unable to locate", msg)


class AuthKeys(Base):
    def test_add_replace_remove(self):
        os.makedirs(os.path.dirname(S.AUTH_FILE))
        open(S.AUTH_FILE, "w").write("ssh-ed25519 OWNERKEY owner@laptop\n")
        S.auth_add(PUB, "203.0.113.10")
        S.auth_add(PUB.replace("BACKKEY", "NEWKEY"), "203.0.113.11")   # вторая запись заменяет первую
        lines = open(S.AUTH_FILE).read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "ssh-ed25519 OWNERKEY owner@laptop")   # чужое не тронуто
        self.assertTrue(lines[1].startswith('from="203.0.113.11",no-pty,no-agent-forwarding,no-X11-forwarding,no-port-forwarding ssh-ed25519 '))
        self.assertTrue(lines[1].endswith("cc-fleet-back:prod"))
        self.assertEqual(stat.S_IMODE(os.stat(S.AUTH_FILE).st_mode), 0o600)
        self.assertTrue(S.auth_remove())
        self.assertEqual(open(S.AUTH_FILE).read().splitlines(), ["ssh-ed25519 OWNERKEY owner@laptop"])
        self.assertFalse(S.auth_remove())


class Connect(Base):
    def setUp(self):
        super().setUp()
        self.fake_key()
        self.fields = {"host": "203.0.113.10", "port": 22, "tmux": "cc2", "back_host": "198.51.100.7"}
        self.deploy = mock.patch("cc_remote_mode.deploy_tools", return_value=True)
        self.deploy.start()
        self.addCleanup(self.deploy.stop)

    def replies(self, back="BACK_OK", key=PUB, probe=PROBE_OK):
        return [("echo uid=", (0, probe)), ("ssh-keygen", (0, key + "\n")), ("BACK_OK", (0, back + "\n" if back else "refused")), (None, (0, ""))]

    def test_connect_polls_the_new_pair_at_once(self):
        polled = []
        orig = R.fetch_limits
        R.fetch_limits = lambda mid, force=False: polled.append((mid, force))
        self.addCleanup(setattr, R, "fetch_limits", orig)
        self.test_full_connect_writes_pair_and_key()
        self.assertEqual(polled, [("prod", True)])  # без ожидания минутного цикла в панели сразу появляется карточка второго сервера

    def test_failed_first_poll_does_not_break_connect(self):
        orig = R.fetch_limits
        def boom(mid, force=False): raise OSError("нет связи")
        R.fetch_limits = boom
        self.addCleanup(setattr, R, "fetch_limits", orig)
        self.test_full_connect_writes_pair_and_key()

    def test_full_connect_writes_pair_and_key(self):
        with self.ssh(self.replies()):
            ok, msg, steps = S.connect(self.fields)
        self.assertTrue(ok, (msg, steps))
        self.assertTrue(all(s["ok"] for s in steps), steps)
        rec = json.load(open(R.MEMBERS_FILE))["prod"]
        self.assertEqual((rec["host"], rec["tmux"], rec["back_host"], rec["back_key"], rec["user"]), ("203.0.113.10", "cc2", "198.51.100.7", S.BACK_KEY, "root"))
        self.assertNotIn("port", rec)
        self.assertEqual(rec["key"], S.KEY_PATH)
        self.assertEqual(stat.S_IMODE(os.stat(R.MEMBERS_FILE).st_mode), 0o600)
        auth = open(S.AUTH_FILE).read()
        self.assertIn('from="203.0.113.10"', auth)
        self.assertIn(PUB.split()[1], auth)
        back_cmd = [c for _, c in self.calls if "BACK_OK" in c][0]
        self.assertIn("root@198.51.100.7", back_cmd)
        self.assertIn(S.BACK_KEY, back_cmd)

    def test_port_and_existing_extra_keys_are_kept(self):
        json.dump({"prod": {"label": "Мой второй", "host": "old.example", "extra": 1}}, open(R.MEMBERS_FILE, "w"))
        with self.ssh(self.replies()):
            ok, _, _ = S.connect(dict(self.fields, host="old.example", port=2200))
        self.assertTrue(ok)
        rec = json.load(open(R.MEMBERS_FILE))["prod"]
        self.assertEqual((rec["label"], rec["extra"], rec["port"]), ("Мой второй", 1, 2200))

    def test_not_ready_server_is_refused_with_reasons(self):
        with self.ssh([(None, (0, PROBE_BARE))]):
            ok, msg, steps = S.connect(self.fields)
        self.assertFalse(ok)
        self.assertIn("tmux", msg)
        self.assertFalse(os.path.exists(R.MEMBERS_FILE))
        self.assertFalse(os.path.exists(S.AUTH_FILE))

    def test_tools_failure_stops_before_any_key(self):
        self.deploy.stop()
        with mock.patch("cc_remote_mode.deploy_tools", return_value=False), self.ssh(self.replies()):
            ok, msg, _ = S.connect(self.fields)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(S.AUTH_FILE))
        self.deploy.start()

    def test_no_reverse_access_removes_the_key_and_writes_nothing(self):
        with self.ssh(self.replies(back="")):
            ok, msg, steps = S.connect(self.fields)
        self.assertFalse(ok)
        self.assertIn("198.51.100.7", msg)
        self.assertFalse(os.path.exists(R.MEMBERS_FILE))
        self.assertNotIn("cc-fleet-back", open(S.AUTH_FILE).read() if os.path.exists(S.AUTH_FILE) else "")

    def test_broken_key_output(self):
        with self.ssh(self.replies(key="ошибка")):
            ok, _, steps = S.connect(self.fields)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(S.AUTH_FILE))

    def test_back_host_default_when_empty(self):
        with mock.patch.object(S, "default_back_host", return_value="192.0.2.5"), self.ssh(self.replies()):
            ok, _, _ = S.connect(dict(self.fields, back_host=""))
        self.assertTrue(ok)
        self.assertEqual(json.load(open(R.MEMBERS_FILE))["prod"]["back_host"], "192.0.2.5")
        with mock.patch.object(S, "default_back_host", return_value=""), self.ssh(self.replies()):
            ok, msg, _ = S.connect(dict(self.fields, back_host=""))
        self.assertFalse(ok)
        self.assertIn("Адрес этого сервера", msg)

    def test_remove(self):
        with self.ssh(self.replies()):
            S.connect(self.fields)
        ok, msg = S.remove()
        self.assertTrue(ok, msg)
        self.assertEqual(json.load(open(R.MEMBERS_FILE)), {})
        self.assertNotIn("cc-fleet-back", open(S.AUTH_FILE).read())
        self.assertFalse(S.remove()[0])

    def test_status(self):
        st = S.status()
        self.assertTrue(st["ok"] and st["pub"].startswith("ssh-ed25519 "))
        self.assertIsNone(st["member"])
        with self.ssh(self.replies()):
            S.connect(self.fields)
        st = S.status()
        self.assertEqual((st["member"]["host"], st["member"]["tmux"], st["member"]["back_host"]), ("203.0.113.10", "cc2", "198.51.100.7"))
        self.assertNotIn("key", st["member"])


class Jobs(Base):
    def test_single_job_and_result(self):
        gate = threading.Event()
        ok, jid = S.start_job("Работаю", lambda: (gate.wait(5), {"ok": True, "message": "готово", "steps": [{"label": "x", "ok": True}]})[1])
        self.assertTrue(ok)
        self.assertEqual(S.job_view()["state"], "running")
        ok2, why = S.start_job("Ещё", lambda: {"ok": True})
        self.assertFalse(ok2)
        self.assertIn("Уже идёт", why)
        gate.set()
        for _ in range(100):
            if S.job_view()["state"] != "running":
                break
            time.sleep(0.02)
        v = S.job_view()
        self.assertEqual((v["state"], v["message"], v["steps"][0]["label"]), ("ok", "готово", "x"))

    def test_crash_is_reported(self):
        S.start_job("Сбой", lambda: 1 / 0)
        for _ in range(100):
            if S.job_view()["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(S.job_view()["state"], "error")


class FakeBase:
    sent = []
    authed = True

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        FakeBase.sent.append((code, body))

    def _authed(self):
        return FakeBase.authed

    def do_GET(self):
        FakeBase.sent.append(("base_get", self.path))

    def do_POST(self):
        FakeBase.sent.append(("base_post", self.path))


class Routes(Base):
    def setUp(self):
        super().setUp()
        self.fake_key()
        FakeBase.sent, FakeBase.authed = [], True
        self.ns = {"H": FakeBase, "PAGE": "<html><body>x</body></html>"}
        S.install(self.ns)
        self.h = self.ns["H"].__new__(self.ns["H"])

    def req(self, method, path, body=None):
        self.h.path = path
        raw = json.dumps(body).encode() if body is not None else b""
        self.h.headers = {"Content-Length": str(len(raw))}
        self.h.rfile = io.BytesIO(raw)
        FakeBase.sent = []
        getattr(self.h, "do_" + method)()
        return FakeBase.sent[-1]

    def test_status_check_and_auth(self):
        code, body = self.req("GET", "/api/remote/setup")
        self.assertEqual((code, body["ok"]), (200, True))
        with self.ssh([(None, (0, PROBE_OK))]), mock.patch.object(S, "local_checks", return_value=[]):
            code, body = self.req("POST", "/api/remote/setup/check", {"host": "203.0.113.10"})
        self.assertEqual((code, body["ready"]), (200, True))
        FakeBase.authed = False
        for method, path in (("GET", "/api/remote/setup"), ("GET", "/api/remote/setup/job"), ("POST", "/api/remote/setup/check"),
                             ("POST", "/api/remote/setup/connect"), ("POST", "/api/remote/setup/remove")):
            self.assertEqual(self.req(method, path, {})[0], 403, path)
        FakeBase.authed = True
        self.assertEqual(self.req("GET", "/api/other")[0], "base_get")
        self.assertEqual(self.req("POST", "/api/other", {})[0], "base_post")

    def test_connect_runs_as_job(self):
        with mock.patch("cc_remote_mode.deploy_tools", return_value=True), \
                self.ssh([("echo uid=", (0, PROBE_OK)), ("ssh-keygen", (0, PUB + "\n")), ("BACK_OK", (0, "BACK_OK\n")), (None, (0, ""))]):
            code, body = self.req("POST", "/api/remote/setup/connect", {"host": "203.0.113.10", "back_host": "198.51.100.7"})
            self.assertEqual((code, body["ok"]), (200, True))
            for _ in range(200):
                if S.job_view()["state"] != "running":
                    break
                time.sleep(0.02)
        code, view = self.req("GET", "/api/remote/setup/job")
        self.assertEqual(view["state"], "ok", view)
        self.assertTrue(all(s["ok"] for s in view["steps"]))
        self.assertIn("prod", json.load(open(R.MEMBERS_FILE)))
        code, body = self.req("POST", "/api/remote/setup/remove", {})
        self.assertEqual((code, body["ok"]), (200, True))

    def test_page_has_the_wizard(self):
        page = self.ns["PAGE"]
        self.assertIn("fleetRemoteSetup", page)
        self.assertIn("Второй сервер", page)
        self.assertIn("remote/setup/check", page)
        for n in (1, 2, 3):  # прогресс «шаг N из M»: следующий шаг недоступен, пока предыдущий не пройден (кнопка «Подключить» закрыта до успешной проверки)
            self.assertIn("Шаг %d из 3" % n, page)
        self.assertIn('id="rsGo" disabled', page)
        self.assertLess(page.index("fleetRemoteSetup"), page.index("</body>"))


class Wiring(Base):
    def test_tmux_name_goes_with_every_ctl_call(self):
        import cc_remote_mode as M
        seen = []
        with mock.patch.object(R, "ssh_run", side_effect=lambda m, cmd, timeout=0, inp=None: seen.append(cmd) or (0, '{"ok": true}')):
            M.ctl({"host": "h", "tmux": "friend"}, "status")
            M.ctl({"host": "h"}, "status")
            M.ctl({"host": "h", "tmux": "bad name;rm"}, "status")
        self.assertEqual(seen[0], "CC_REMOTE_TMUX=friend python3 /root/cc-remote/ctl.py status")
        self.assertEqual(seen[1], "python3 /root/cc-remote/ctl.py status")
        self.assertEqual(seen[2], "CC_REMOTE_TMUX=badnamerm python3 /root/cc-remote/ctl.py status")   # вредного не пропускаем

    def test_default_tmux_name_is_neutral(self):
        root = os.path.dirname(os.path.abspath(S.__file__))
        self.assertIn('or "ccfleet"', open(os.path.join(root, "remote_ctl.py"), encoding="utf-8").read())
        self.assertIn('m.get("tmux", "ccfleet")', open(os.path.join(root, "cc_remote.py"), encoding="utf-8").read())

    def test_installed_by_fleet_and_shipped(self):
        root = os.path.dirname(os.path.abspath(S.__file__))
        self.assertIn("cc_remote_setup.install(ns)", open(os.path.join(root, "cc_fleet.py"), encoding="utf-8").read())
        self.assertIn('"src": "cc_remote_setup.py"', open(os.path.join(root, "update_manifest.json"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
