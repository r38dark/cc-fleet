# Названия двух серверов из настроек (config.json «labels»): подмена DEV/PROD на границах вывода, настройки, установщик
# python3 -m unittest test_cc_labels -v
import io
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

import cc_labels as L


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cclab_")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.old = L.BASE
        L.BASE = self.tmp
        L._cache.update(mtime=None, names=dict(L.DEFAULTS))
        self.addCleanup(self.restore)

    def restore(self):
        L.BASE = self.old
        L._cache.update(mtime=None, names=dict(L.DEFAULTS))

    def put(self, labels=None, **extra):
        cfg = dict(extra)
        if labels is not None:
            cfg["labels"] = labels
        with open(os.path.join(self.tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        L._cache["mtime"] = None
        return os.path.join(self.tmp, "config.json")


class Names(Base):
    def test_without_settings_nothing_changes(self):
        self.assertEqual(L.names(), {"main": "DEV", "remote": "PROD"})
        self.assertFalse(L.active())
        self.assertEqual(L.text("Claude DEV → Claude PROD"), "Claude DEV → Claude PROD")
        self.put(labels=None, chat_id="1")
        self.assertFalse(L.active())
        self.assertEqual(L.text("PROD"), "PROD")

    def test_new_install_names_replace_whole_words_only(self):
        self.put({"main": "A", "remote": "B"})
        self.assertTrue(L.active())
        self.assertEqual(L.text("Claude DEV ↔ Claude PROD · DEVICE PRODUCT dev prod"), "Claude A ↔ Claude B · DEVICE PRODUCT dev prod")
        self.assertEqual(L.text("Работа на PROD: DEV остановлен"), "Работа на B: A остановлен")

    def test_bad_names_fall_back_to_defaults(self):
        for bad in ("", "очень-длинное-название", "с пробелом", "Сервер", "a b", "x" * 13):
            self.put({"main": bad, "remote": "B"})
            self.assertEqual(L.names(), {"main": "DEV", "remote": "B"}, bad)

    def test_one_name_set(self):
        self.put({"main": "Home"})
        self.assertEqual(L.text("DEV и PROD"), "Home и PROD")

    def test_config_change_is_picked_up(self):
        self.put({"main": "A", "remote": "B"})
        self.assertEqual(L.text("DEV"), "A")
        self.put({"main": "Hub", "remote": "Spare"})
        os.utime(os.path.join(self.tmp, "config.json"), (1, 2))  # другой mtime
        self.assertEqual(L.text("DEV PROD"), "Hub Spare")

    def test_obj_replaces_values_not_keys(self):
        self.put({"main": "A", "remote": "B"})
        data = {"DEV": "Claude DEV", "list": ["PROD", 5, None, {"k": "на PROD"}], "n": 3}
        self.assertEqual(L.obj(data), {"DEV": "Claude A", "list": ["B", 5, None, {"k": "на B"}], "n": 3})

    def test_finish_html_json_and_binary(self):
        self.put({"main": "A", "remote": "B"})
        self.assertEqual(L.finish("<b>Claude DEV</b>".encode(), "text/html; charset=utf-8"), "<b>Claude A</b>".encode())
        self.assertEqual(L.finish('{"m":"Claude PROD"}'.encode(), "application/json; charset=utf-8"), '{"m":"Claude B"}'.encode())
        png = b"\x89PNG DEV \xff\xfe"
        self.assertEqual(L.finish(png, "image/png"), png)
        self.assertEqual(L.finish(b"\xff\xfe DEV", "text/html"), b"\xff\xfe DEV")  # не UTF-8 — как есть
        self.assertEqual(L.finish({"a": "DEV"}, ""), {"a": "A"})

    def test_finish_does_nothing_without_labels(self):
        body = {"a": "DEV"}
        self.assertIs(L.finish(body, "application/json"), body)


class Save(Base):
    def test_save_writes_config_and_keeps_other_keys(self):
        path = self.put(None, chat_id="42", tz="Asia/Irkutsk")
        ok, msg = L.save("Home", "Spare")
        self.assertTrue(ok, msg)
        cfg = json.load(open(path))
        self.assertEqual(cfg["labels"], {"main": "Home", "remote": "Spare"})
        self.assertEqual((cfg["chat_id"], cfg["tz"]), ("42", "Asia/Irkutsk"))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(L.names(), {"main": "Home", "remote": "Spare"})

    def test_default_names_remove_the_key(self):
        path = self.put({"main": "A", "remote": "B"}, chat_id="1")
        ok, _ = L.save("DEV", "PROD")
        self.assertTrue(ok)
        self.assertNotIn("labels", json.load(open(path)))
        self.assertFalse(L.active())

    def test_invalid_and_equal_names_are_refused(self):
        path = self.put(None)
        for main, remote in (("плохо", "B"), ("A", "с пробелом"), ("x" * 13, "B"), ("A", "a"), ("ab", "AB")):
            ok, msg = L.save(main, remote)
            self.assertFalse(ok, (main, remote))
            self.assertTrue(msg)
        self.assertNotIn("labels", json.load(open(path)))

    def test_save_uses_given_jload_jsave(self):
        path = self.put(None, k=1)
        seen = []
        ok, _ = L.save("A", "B", jload=lambda p, d: {"k": 1}, jsave=lambda p, c: seen.append((p, c)), path=path)
        self.assertTrue(ok)
        self.assertEqual(seen, [(path, {"k": 1, "labels": {"main": "A", "remote": "B"}})])


class NewInstall(Base):
    def test_fresh_config_gets_a_and_b(self):
        path = self.put(None, hook_token="t")
        self.assertTrue(L.init_new_install(path))
        self.assertEqual(json.load(open(path))["labels"], {"main": "A", "remote": "B"})
        self.assertEqual(L.text("Claude DEV и Claude PROD"), "Claude A и Claude B")

    def test_existing_labels_are_kept(self):
        path = self.put({"main": "Home", "remote": "Spare"})
        self.assertFalse(L.init_new_install(path))
        self.assertEqual(json.load(open(path))["labels"], {"main": "Home", "remote": "Spare"})

    def test_installer_writes_labels_only_for_a_new_config_and_manifest_ships_the_module(self):
        root = os.path.dirname(os.path.abspath(L.__file__))
        sh = open(os.path.join(root, "install.sh"), encoding="utf-8").read()
        self.assertIn("fresh = not os.path.exists(path)", sh)
        self.assertIn('if fresh: cfg["labels"] = {"main": "A", "remote": "B"}', sh)
        self.assertIn('"src": "cc_labels.py"', open(os.path.join(root, "update_manifest.json"), encoding="utf-8").read())


class FakeBase:
    """Обработчик панели: _send складывает ответ, _authed решается флагом, остальное — «дальше по цепочке»."""
    sent = []
    authed = True

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        FakeBase.sent.append((code, body, ctype))

    def _authed(self):
        return FakeBase.authed

    def do_GET(self):
        FakeBase.sent.append(("base_get", self.path, None))

    def do_POST(self):
        FakeBase.sent.append(("base_post", self.path, None))


class Handler(Base):
    def setUp(self):
        super().setUp()
        FakeBase.sent = []
        FakeBase.authed = True
        self.notes, self.calls = [], []
        self.cfg_path = os.path.join(self.tmp, "config.json")
        self.ns = {"H": FakeBase, "PAGE": "<html><body>Claude DEV</body></html>",
                   "jload": lambda p, d: json.load(open(p)) if os.path.exists(p) else d,
                   "jsave": lambda p, c: json.dump(c, open(p, "w")), "CONFIG": self.cfg_path,
                   "tg_notify": lambda text: self.notes.append(text),
                   "_tg_call": lambda method, payload=None: self.calls.append((method, payload))}
        L.install(self.ns)
        self.h = self.ns["H"].__new__(self.ns["H"])

    def request(self, method, path, body=None):
        self.h.path = path
        raw = json.dumps(body).encode() if body is not None else b""
        self.h.headers = {"Content-Length": str(len(raw))}
        self.h.rfile = io.BytesIO(raw)
        FakeBase.sent = []
        getattr(self.h, "do_" + method)()
        return FakeBase.sent[-1]

    def test_every_response_gets_the_names(self):
        self.put({"main": "A", "remote": "B"})
        self.h._send(200, {"m": "Claude PROD работает"})
        self.h._send(200, "<p>DEV</p>".encode(), "text/html; charset=utf-8")
        self.assertEqual([x[1] for x in FakeBase.sent], [{"m": "Claude B работает"}, "<p>A</p>".encode()])

    def test_no_labels_means_no_change(self):
        self.h._send(200, {"m": "Claude PROD"})
        self.assertEqual(FakeBase.sent[-1][1], {"m": "Claude PROD"})

    def test_console_screens_and_chats_are_not_rewritten(self):
        self.put({"main": "A", "remote": "B"})
        for path in ("/api/console?s=prod", "/api/remote/console", "/api/notion-ai/view", "/api/notion-ai/agents/view/ag1"):
            self.h.path = path
            self.h._send(200, {"current": "git push to PROD, DEV ok"})
            self.assertEqual(FakeBase.sent[-1][1], {"current": "git push to PROD, DEV ok"}, path)
        self.h.path = "/api/limits"
        self.h._send(200, {"m": "PROD"})
        self.assertEqual(FakeBase.sent[-1][1], {"m": "B"})

    def test_labels_api_reads_and_saves(self):
        code, body, _ = self.request("GET", "/api/labels")
        self.assertEqual((code, body["ok"], body["custom"]), (200, True, False))
        code, body, _ = self.request("POST", "/api/labels", {"main": "Home", "remote": "Spare"})
        self.assertEqual((code, body["ok"]), (200, True))
        self.assertEqual(json.load(open(self.cfg_path))["labels"], {"main": "Home", "remote": "Spare"})
        code, body, _ = self.request("GET", "/api/labels")
        self.assertEqual((body["main"], body["remote"], body["custom"]), ("Home", "Spare", True))
        code, body, _ = self.request("POST", "/api/labels", {"main": "плохо", "remote": "B"})
        self.assertEqual((code, body["ok"]), (400, False))

    def test_labels_api_needs_auth_and_other_paths_go_on(self):
        FakeBase.authed = False
        self.assertEqual(self.request("GET", "/api/labels")[0], 403)
        self.assertEqual(self.request("POST", "/api/labels", {"main": "A", "remote": "B"})[0], 403)
        self.assertNotIn("labels", self.ns["jload"](self.cfg_path, {}))
        FakeBase.authed = True
        self.assertEqual(self.request("GET", "/api/other")[0], "base_get")
        self.assertEqual(self.request("POST", "/api/other", {})[0], "base_post")

    def test_page_gets_the_settings_block(self):
        page = self.ns["PAGE"]
        self.assertIn("s.id='fleetLabels'", page)
        self.assertIn('#fleetLabels .fl-row', page)
        self.assertIn("api('labels'", page)
        self.assertLess(page.index("fleetLabels"), page.index("</body>"))
        self.assertIn("Названия серверов", page)

    def test_telegram_texts_get_the_names(self):
        self.put({"main": "A", "remote": "B"})
        self.ns["tg_notify"]("🔁 Переход на Claude PROD")
        self.ns["_tg_call"]("sendMessage", {"chat_id": 1, "text": "Лимиты у DEV"})
        self.ns["_tg_call"]("answerCallbackQuery", {"callback_query_id": "x"})
        self.assertEqual(self.notes, ["🔁 Переход на Claude B"])
        self.assertEqual(self.calls, [("sendMessage", {"chat_id": 1, "text": "Лимиты у A"}), ("answerCallbackQuery", {"callback_query_id": "x"})])


class Boundaries(Base):
    def test_text_for_the_second_server_console_uses_names(self):
        import cc_remote_mode as M
        self.put({"main": "A", "remote": "B"})
        sent = {}
        with mock.patch.object(M, "_cin_lock", mock.MagicMock(acquire=lambda timeout=0: True, release=lambda: None)), \
                mock.patch.object(M, "_member_id", return_value="prod"), \
                mock.patch.object(M.R, "ctl", side_effect=lambda mid, op, inp="", timeout=0: sent.update(inp=inp) or {"ok": True}):
            ok, code = M.prod_send_once("[PANEL 10:00] Работа передана тебе (Claude PROD). Бот на dev остановлен, DEV спит")
        self.assertTrue(ok)
        self.assertIn("Работа передана тебе (Claude B)", sent["inp"])
        self.assertIn("A спит", sent["inp"])

    def test_handoff_text_has_no_main_claude_wording(self):
        root = os.path.dirname(os.path.abspath(L.__file__))
        src = open(os.path.join(root, "cc_remote_mode.py"), encoding="utf-8").read()
        self.assertNotIn("Ты теперь основной Claude", src)
        self.assertIn("Работа теперь у тебя: Telegram включён", src)

    def test_pause_notification_uses_names(self):
        import pause_ctl as P
        self.put({"main": "A", "remote": "B"}, chat_id="7", bot_token="1:x")
        got = []
        with mock.patch.object(P, "_cfg", return_value={"chat_id": "7", "bot_token": "1:x", "pause_notify": True}), \
                mock.patch.object(P.urllib.request, "urlopen", side_effect=lambda req, timeout=0: got.append(json.loads(req.data)) or mock.MagicMock(read=lambda: b"{}")), \
                mock.patch.object(P, "TG_ENV", os.path.join(self.tmp, "no.env")):
            P._tg("⏸ Claude PROD остановлен, DEV ждёт")
        self.assertTrue(got, "уведомление не отправлено")
        self.assertEqual(got[0]["text"], "⏸ Claude B остановлен, A ждёт")

    def test_fleet_install_connects_labels_before_remote(self):
        root = os.path.dirname(os.path.abspath(L.__file__))
        src = open(os.path.join(root, "cc_fleet.py"), encoding="utf-8").read()
        self.assertIn("cc_labels.install(ns)", src)
        self.assertLess(src.index("cc_labels.install(ns)"), src.index("cc_remote_mode.install(ns)"))  # копии tg_notify там уже обёрнуты


if __name__ == "__main__":
    unittest.main()
