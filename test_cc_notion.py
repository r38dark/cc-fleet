# Карточка Notion-агента: состояние из файла входа, без токенов в ответе и без сети.
# python3 -m unittest test_cc_notion -v
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cc_notion as N  # noqa: E402


class Public(unittest.TestCase):
    def setUp(self):
        # подмены модуля возвращаем после каждого теста: иначе они доживают до других файлов тестов в том же процессе
        # (test_cc_limits_codex_ui.NotionRoute читал бы чужой «конфиг» из последнего теста этого класса)
        saved = (N.CREDS, N.CONFIG)
        self.addCleanup(lambda: (setattr(N, "CREDS", saved[0]), setattr(N, "CONFIG", saved[1])))
        self.d = tempfile.mkdtemp(prefix="ccnt_")
        self.creds = os.path.join(self.d, "c.json")
        N.CREDS = lambda: self.creds
        self.conf = {}
        N.CONFIG = lambda: self.conf

    def write(self, doc):
        json.dump(doc, open(self.creds, "w"))

    def test_no_file_no_card(self):
        self.assertEqual(N.public(), {"available": False})

    def test_other_mcp_only_no_card(self):
        self.write({"mcpOAuth": {"plugin:context7:context7|x": {"serverName": "plugin:context7:context7",
                                                               "serverUrl": "https://mcp.context7.com/mcp", "accessToken": "t"}}})
        self.assertEqual(N.public(), {"available": False})

    def test_connected_shows_facts_without_tokens(self):
        self.write({"claudeAiOauth": {"accessToken": "SECRET-A"},
                    "mcpOAuth": {"notion|h": {"serverName": "notion", "serverUrl": "https://mcp.notion.com/mcp",
                                              "accessToken": "SECRET-N", "refreshToken": "SECRET-R",
                                              "expiresAt": 1900000000000}}})
        self.conf = {"name": "My agent", "url": "agent://s/a"}
        p = N.public()
        self.assertTrue(p["available"] and p["connected"] and p["can_refresh"])
        self.assertEqual(p["expires_at"], 1900000000)
        self.assertEqual(p["agent"], {"name": "My agent", "set": True})
        out = json.dumps(p)
        for s in ("SECRET-A", "SECRET-N", "SECRET-R", "agent://"):
            self.assertNotIn(s, out)

    def test_without_agent_in_config(self):
        self.write({"mcpOAuth": {"notion|h": {"serverName": "notion", "accessToken": "t"}}})
        p = N.public()
        self.assertEqual(p["agent"], {"name": "", "set": False})
        self.assertFalse(p["can_refresh"])
        self.assertTrue(p["connected"])

    def test_broken_file_no_card(self):
        open(self.creds, "w").write("{не json")
        self.assertEqual(N.public(), {"available": False})


class Save(unittest.TestCase):
    def test_enabled_key_is_gone(self):
        # переключателя «включить/выключить агента» больше нет: ключ enabled сервер не принимает и не хранит
        ok, conf, err = N.save({"name": "A", "url": "agent://s/a"}, {"enabled": False})
        self.assertEqual((ok, err), (True, ""))
        self.assertEqual(conf, {"name": "A", "url": "agent://s/a"})
        self.assertNotIn("enabled", N.public())
        # ключ, оставшийся в старом конфиге, при первом же сохранении исчезает
        ok, conf, _ = N.save({"name": "A", "enabled": False}, {"name": "B"})
        self.assertEqual(conf, {"name": "B"})

    def test_empty_url_keeps_old_one(self):
        ok, conf, _ = N.save({"url": "agent://s/a"}, {"name": "B", "url": ""})
        self.assertTrue(ok)
        self.assertEqual(conf, {"url": "agent://s/a", "name": "B"})

    def test_url_replace_and_clear(self):
        ok, conf, _ = N.save({"url": "agent://s/a"}, {"url": "  agent://s/b  "})
        self.assertEqual(conf["url"], "agent://s/b")
        ok, conf, _ = N.save(conf, {"clear_url": True})
        self.assertTrue(ok)
        self.assertNotIn("url", conf)
        # clear_url не строго true — не стирает
        ok, conf, _ = N.save({"url": "agent://s/a"}, {"clear_url": "yes"})
        self.assertEqual(conf["url"], "agent://s/a")

    def test_bad_url_rejected_and_conf_untouched(self):
        old = {"name": "A", "url": "agent://s/a"}
        for bad in ("http://evil", "agent://a b", "agent://x\ny", "agent://" + "x" * 300, "javascript:1"):
            ok, conf, err = N.save(old, {"url": bad})
            self.assertEqual((ok, err), (False, "url"), bad)
            self.assertEqual(conf, old)

    def test_name_rules(self):
        ok, conf, _ = N.save({}, {"name": "  Helper  "})
        self.assertEqual(conf["name"], "Helper")
        ok, conf, _ = N.save({"name": "Helper"}, {"name": "   "})
        self.assertNotIn("name", conf)
        self.assertEqual(N.save({}, {"name": "x" * 81})[2], "name")
        self.assertEqual(N.save({}, {"name": "a\x07b"})[2], "name")

    def test_source_conf_not_mutated(self):
        old = {"name": "A"}
        N.save(old, {"name": "B"})
        self.assertEqual(old, {"name": "A"})


class NoReserve(unittest.TestCase):
    """[notion-ai] Резерв убран целиком: нет сторожа, галочек, паузы и инструментов Notion для Codex."""

    def test_module_has_no_reserve_machinery(self):
        for name in ("NOTIFY", "EMERGENCY", "LEVEL", "BASE", "PAUSE", "PROFILE"):
            self.assertFalse(hasattr(N, name), name)
        self.assertFalse(N.active())
        self.assertEqual(N.codex_args(), [])
        self.assertIsNone(N.tick())

    def test_save_rejects_reserve_and_drops_old_flags(self):
        ok, conf, err = N.save({"name": "A", "reserve": {"manual": True}}, {"reserve": {"manual": True}})
        self.assertEqual((ok, err), (False, "reserve"))
        ok, conf, err = N.save({"name": "A", "reserve": {"manual": True, "auto": True}}, {"name": "B"})
        self.assertTrue(ok)
        self.assertEqual(conf, {"name": "B"})


if __name__ == "__main__":
    unittest.main()


def LV(level="hard", **kw):
    """Состояние пауз как отдаёт pause_ctl.level_state()."""
    d = {"ok": True, "level": level, "stale": False, "pause": {"override": False}, "line": "acc1 91%, acc2 96%",
         "nearest": {"resets_at": "2026-11-01T08:00:00Z"}}
    d.update(kw)
    return d


class ClaudeStatus(unittest.TestCase):
    def test_pause_levels_mean_down(self):
        self.assertEqual(N.claude_status(LV("hard")), "down")
        self.assertEqual(N.claude_status(LV("week")), "down")

    def test_working_levels_mean_up(self):
        for lvl in ("none", "gate", "weekrisk", "manual"):
            self.assertEqual(N.claude_status(LV(lvl)), "up", lvl)

    def test_manual_pick_and_disabled_pause_are_up(self):
        self.assertEqual(N.claude_status(LV("hard", manual={"account": "a"})), "up")
        self.assertEqual(N.claude_status(LV("hard", pause={"override": True})), "up")

    def test_no_trust_in_stale_or_broken_snapshot(self):
        for lv in (LV("hard", stale=True), {"ok": False, "level": "none"}, {}, None, "x", {"pause": {}}):
            self.assertEqual(N.claude_status(lv), "unknown", lv)
