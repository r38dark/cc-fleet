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
        saved = (N.CREDS, N.CONFIG, N.BASE, N.LEVEL)
        self.addCleanup(lambda: (setattr(N, "CREDS", saved[0]), setattr(N, "CONFIG", saved[1]),
                                 setattr(N, "BASE", saved[2]), setattr(N, "LEVEL", saved[3])))
        self.d = tempfile.mkdtemp(prefix="ccnt_")
        self.creds = os.path.join(self.d, "c.json")
        N.CREDS = lambda: self.creds
        self.conf = {}
        N.CONFIG = lambda: self.conf
        N.BASE = self.d  # состояние резерва — во временную папку, не в /opt/cc-limits
        N.LEVEL = lambda: {"ok": True, "level": "none", "pause": {}}

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


class ReserveConf(unittest.TestCase):
    def test_all_off_by_default(self):
        self.assertEqual(N.reserve_conf({}), {"manual": False, "auto": False, "auto_emergency": False})
        self.assertEqual(N.reserve_conf({"reserve": "x"}), {"manual": False, "auto": False, "auto_emergency": False})

    def test_only_real_true_counts(self):
        r = N.reserve_conf({"reserve": {"manual": 1, "auto": "yes", "auto_emergency": True}})
        self.assertEqual(r, {"manual": False, "auto": False, "auto_emergency": True})

    def test_save_merges_and_validates(self):
        ok, c, err = N.save({"name": "A", "reserve": {"auto": True}}, {"reserve": {"auto_emergency": True}})
        self.assertTrue(ok)
        self.assertEqual(c["reserve"], {"auto": True, "auto_emergency": True})
        self.assertEqual(c["name"], "A")
        for bad in ({"auto": "yes"}, {"auto": 1}, {"other": True}, "x", None, []):
            ok, c2, err = N.save({"reserve": {"auto": True}}, {"reserve": bad})
            self.assertFalse(ok, bad)
            self.assertEqual((err, c2), ("reserve", {"reserve": {"auto": True}}))

    def test_save_does_not_touch_source(self):
        src = {"reserve": {"auto": True}}
        N.save(src, {"reserve": {"auto": False}})
        self.assertEqual(src, {"reserve": {"auto": True}})

    def test_other_saves_keep_manual(self):
        # любое другое сохранение (имя, ссылка, авто-галочка, очистка ссылки) ручную галочку резерва не трогает
        src = {"reserve": {"manual": True, "auto": False}}
        for body in ({"name": "B"}, {"reserve": {"auto": True}}, {"clear_url": True}):
            ok, c, _ = N.save(src, body)
            self.assertTrue(ok, body)
            self.assertIs(c["reserve"]["manual"], True, body)


class FakeEmg:
    """Подставка вместо cc_codex_emergency: считает вызовы."""
    def __init__(self):
        self.on_calls, self.off_calls, self._active, self.ok, self.msg = [], [], False, True, "Проект не настроен."

    def CONFIG(self):
        return {"project": "/x"}

    def active(self):
        return self._active

    def on(self, word, lang="ru", auto=None):
        self.on_calls.append((word, auto))
        if self.ok:
            self._active = True
        return self.ok, ("ok" if self.ok else self.msg)

    def off(self, why="", lang="ru", quiet=False):
        self.off_calls.append((why, quiet))
        self._active = False
        return True, "ok"


class ReserveTick(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ccnr_")
        self.saved = (N.BASE, N.CONFIG, N.CREDS, N.LEVEL, N.NOTIFY, N.EMERGENCY, N.NOW, N.HOLD, N.PAUSE, N.PROFILE, N.APPLY)
        self.creds = os.path.join(self.d, "c.json")
        with open(self.creds, "w") as f:
            json.dump({"mcpOAuth": {"notion|h": {"serverName": "notion", "accessToken": "t", "refreshToken": "r"}}}, f)
        self.t, self.lv, self.sent = 1_000_000.0, LV("none"), []
        self.conf = {"name": "Helper", "url": "agent://s/a", "reserve": {"auto": True, "auto_emergency": True}}
        self.emg = FakeEmg()
        N.BASE, N.CONFIG, N.CREDS = self.d, (lambda: self.conf), (lambda: self.creds)
        N.LEVEL, N.NOTIFY, N.EMERGENCY = (lambda: self.lv), self.sent.append, self.emg
        N.NOW, N.HOLD = (lambda: self.t), 120
        # хуки cc_limits подменены: ни настоящая пауза, ни настоящий профиль, ни перезапуск консоли в тестах не трогаются
        self.pauses, self.profiles, self.applies = [], [], []
        N.PAUSE = self.pauses.append
        N.PROFILE = lambda active, flipped: self.profiles.append((active, flipped))
        N.APPLY = lambda: self.applies.append(1)

    def tearDown(self):
        (N.BASE, N.CONFIG, N.CREDS, N.LEVEL, N.NOTIFY, N.EMERGENCY, N.NOW, N.HOLD, N.PAUSE, N.PROFILE, N.APPLY) = self.saved

    def run_for(self, sec, step=30):
        for _ in range(int(sec // step) + 1):
            N.tick()
            self.t += step

    def test_short_dip_does_nothing(self):
        self.lv = LV("hard")
        self.run_for(60)
        self.assertFalse(N.active())
        self.assertEqual((self.emg.on_calls, self.sent), ([], []))

    def test_limits_over_turns_on_reserve_and_emergency_with_one_message(self):
        self.lv = LV("hard")
        self.run_for(300)
        self.assertTrue(N.active())
        self.assertEqual(self.emg.on_calls, [("", "лимиты Claude кончились")])  # слово не нужно, режим включён один раз
        self.assertEqual(len(self.sent), 1)
        m = self.sent[0]
        for part in ("Лимиты всех аккаунтов Claude кончились", "acc1 91%", "РЕЗЕРВ", "Helper", "Аварийный режим ВКЛЮЧЁН", "«да»"):
            self.assertIn(part, m)
        self.assertNotIn("agent://", m)
        self.assertEqual(N.public()["role"], "reserve")

    def test_limits_back_turns_everything_off_with_one_message(self):
        self.lv = LV("hard")
        self.run_for(200)
        self.lv = LV("none")
        self.run_for(60)
        self.assertTrue(N.active())  # ещё не HOLD
        self.run_for(200)
        self.assertFalse(N.active())
        self.assertEqual(self.emg.off_calls, [("лимиты Claude снова доступны", True)])
        self.assertEqual(len(self.sent), 2)
        self.assertIn("аварийный режим снят", self.sent[1])
        self.assertFalse(self.emg.active())
        self.assertEqual(N.public()["role"], "helper")

    def test_stale_snapshot_changes_nothing_in_both_directions(self):
        self.lv = LV("hard", stale=True)
        self.run_for(600)
        self.assertFalse(N.active())
        self.lv = LV("hard")
        self.run_for(200)
        self.assertTrue(N.active())
        self.lv = LV("none", stale=True)
        self.run_for(600)
        self.assertTrue(N.active())
        self.assertEqual(self.emg.off_calls, [])

    def test_auto_checkbox_off_never_turns_on(self):
        self.conf["reserve"] = {"auto": False, "auto_emergency": True}
        self.lv = LV("hard")
        self.run_for(600)
        self.assertEqual((N.active(), self.emg.on_calls, self.sent), (False, [], []))

    def test_emergency_checkbox_off_reserve_only(self):
        self.conf["reserve"] = {"auto": True, "auto_emergency": False}
        self.lv = LV("hard")
        self.run_for(300)
        self.assertTrue(N.active())
        self.assertEqual(self.emg.on_calls, [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Аварийный режим не включался", self.sent[0])

    def test_manual_reserve_is_silent_and_has_no_emergency(self):
        self.conf["reserve"] = {"manual": True, "auto_emergency": True}
        self.run_for(120)
        self.assertTrue(N.active())
        self.assertEqual(N.public()["reserve"]["why"], "manual")
        self.assertEqual((self.emg.on_calls, self.sent), ([], []))
        self.conf["reserve"] = {}
        self.run_for(60)
        self.assertFalse(N.active())

    def test_manual_plus_limits_over_still_gets_emergency_and_message(self):
        self.conf["reserve"] = {"manual": True, "auto": True, "auto_emergency": True}
        self.lv = LV("week")
        self.run_for(300)
        self.assertEqual(len(self.emg.on_calls), 1)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("недельный потолок", self.sent[0])
        self.lv = LV("none")
        self.run_for(300)
        self.assertTrue(N.active())  # вручную включённый резерв остаётся
        self.assertEqual(len(self.emg.off_calls), 1)
        self.assertIn("остаётся включённым", self.sent[1])

    def test_manual_checkbox_pauses_claude_once_and_releases_on_clear(self):
        # сценарий 1: человек сам отключает Claude галочкой — пауза ставится один раз, а не каждый такт
        self.conf["reserve"] = {"manual": True}
        self.run_for(150)
        self.assertEqual(self.pauses, [True])
        self.assertTrue(N.public()["reserve"]["paused"])
        self.conf["reserve"] = {}
        self.run_for(90)
        self.assertEqual(self.pauses, [True, False])
        self.assertFalse(N.public()["reserve"]["paused"])
        self.run_for(90)
        self.assertEqual(self.pauses, [True, False])  # повторно не снимается

    def test_limits_case_does_not_add_its_own_pause(self):
        # сценарий 2: лимиты кончились — Claude и так на паузе по лимитам, отдельной паузы резерв не ставит
        self.lv = LV("hard")
        self.run_for(300)
        self.assertTrue(N.active())
        self.assertEqual(self.pauses, [])
        self.lv = LV("none")
        self.run_for(300)
        self.assertFalse(N.active())
        self.assertEqual(self.pauses, [])

    def test_manual_pause_survives_limits_coming_and_going(self):
        self.conf["reserve"] = {"manual": True, "auto": True}
        self.run_for(60)
        self.lv = LV("hard")
        self.run_for(240)
        self.lv = LV("none")
        self.run_for(300)
        self.assertTrue(N.active())
        self.assertEqual(self.pauses, [True])  # лимиты пришли и ушли, а галочка стоит — пауза держится

    def test_pause_released_when_agent_switched_off_during_manual(self):
        self.conf["reserve"] = {"manual": True}
        self.run_for(60)
        self.assertEqual(self.pauses, [True])
        self.conf["url"] = ""  # ссылку агента убрали: резерв невозможен — Claude нельзя держать на паузе без замены
        self.run_for(60)
        self.assertFalse(N.active())
        self.assertEqual(self.pauses, [True, False])

    def test_agent_toggle_off_releases_on_the_very_next_tick(self):
        # переключатель резерва выключили: такт, запущенный сохранением, снимает паузу и профиль сразу, без ожидания TICK
        self.conf["reserve"] = {"manual": True}
        self.run_for(60)
        self.assertEqual(self.pauses, [True])
        self.conf["reserve"] = {"manual": False}
        N.tick()  # ровно один такт, время не идёт
        self.assertFalse(N.active())
        self.assertEqual(self.pauses, [True, False])
        self.assertEqual(self.profiles[-1], (False, True))
        self.assertEqual(len(self.applies), 2)  # консоль Codex перезапущена и на включение, и на выключение
        self.conf["reserve"] = {"manual": True}  # и обратно: тоже за один такт
        N.tick()
        self.assertTrue(N.active())
        self.assertEqual(self.pauses, [True, False, True])

    def test_ticks_never_overlap_side_effects_keep_order(self):
        # быстрые щелчки: второй такт ждёт конца первого и не обгоняет его паузу (иначе Claude остался бы на паузе при выключенном резерве)
        import threading
        self.conf["reserve"] = {"manual": True}
        inside, go, done = threading.Event(), threading.Event(), []

        def slow_pause(on):
            if on:
                inside.set()
                go.wait(5)  # первая пауза «долго ставится»
            done.append(on)
        N.PAUSE = slow_pause
        a = threading.Thread(target=N.tick)
        a.start()
        self.assertTrue(inside.wait(5))
        self.conf["reserve"] = {"manual": False}  # человек успел выключить, пока первый такт ещё ставит паузу
        b = threading.Thread(target=N.tick)
        b.start()
        b.join(0.3)
        self.assertTrue(b.is_alive(), "второй такт не должен идти параллельно первому")
        go.set()
        a.join(5)
        b.join(5)
        self.assertEqual(done, [True, False])
        self.assertFalse(N.active())
        st = json.load(open(os.path.join(self.d, "notion_reserve.json")))
        self.assertIs(st["pause"], False)

    def test_manual_off_while_limits_are_still_over_says_claude_stays_paused(self):
        # резерв закончился (агент пропал), а лимиты ещё кончились: сообщение не обещает, что Claude уже может работать
        self.lv = LV("hard")
        self.run_for(300)
        self.assertEqual(len(self.sent), 1)
        self.conf["url"] = ""  # ссылку агента убрали: резерв невозможен
        N.tick()
        self.assertFalse(N.active())
        self.assertEqual(len(self.sent), 2)
        m = self.sent[1]
        for part in ("выключен вручную", "лимиты Claude всё ещё кончились", "на паузе", "аварийный режим снят"):
            self.assertIn(part, m)
        self.assertNotIn("снова может работать", m)
        self.lv = LV("none")
        self.run_for(300)
        self.assertEqual(len(self.sent), 2)  # лимиты вернулись — повторного сообщения нет

    def test_limits_back_message_still_says_claude_can_work(self):
        self.lv = LV("hard")
        self.run_for(200)
        self.lv = LV("none")
        self.run_for(300)
        self.assertIn("снова может работать", self.sent[1])
        self.assertNotIn("выключен вручную", self.sent[1])

    def test_manual_without_ready_agent_never_pauses(self):
        self.conf["url"] = ""
        self.conf["reserve"] = {"manual": True}
        self.run_for(120)
        self.assertEqual((self.pauses, self.profiles and self.profiles[0][0]), ([], False))

    def test_pause_not_repeated_after_restart(self):
        self.conf["reserve"] = {"manual": True}
        self.run_for(60)
        self.assertEqual(self.pauses, [True])
        self.run_for(60)  # «перезапуск»: состояние читается с диска, флаг паузы уже в нём
        self.assertEqual(self.pauses, [True])
        st = json.load(open(os.path.join(self.d, "notion_reserve.json")))
        self.assertIs(st["pause"], True)

    def test_profile_hook_flips_once_on_and_keeps_calling_until_back(self):
        self.conf["reserve"] = {"manual": True}
        self.run_for(90)
        on = [x for x in self.profiles if x[0]]
        self.assertEqual([f for _, f in on], [True] + [False] * (len(on) - 1))  # «включился» сообщается только раз
        self.conf["reserve"] = {}
        self.run_for(90)
        off = [x for x in self.profiles if not x[0]]
        self.assertTrue(len(off) >= 3)  # возврат профиля повторяется каждый такт: отложенный возврат не теряется
        self.assertEqual(off[0], (False, True))

    def test_console_restart_hook_only_on_flip(self):
        self.conf["reserve"] = {"manual": True}
        self.run_for(150)
        self.assertEqual(len(self.applies), 1)
        self.conf["reserve"] = {}
        self.run_for(150)
        self.assertEqual(len(self.applies), 2)

    def test_broken_hooks_do_not_break_tick(self):
        def boom(*a):
            raise RuntimeError("x")
        N.PAUSE, N.PROFILE, N.APPLY = boom, boom, boom
        self.conf["reserve"] = {"manual": True}
        self.run_for(90)
        self.assertTrue(N.active())  # хуки упали — резерв всё равно включён и состояние записано

    def test_codex_args_and_note_exist_only_while_reserve_is_on(self):
        self.assertEqual((N.codex_args(), N.codex_note()), ([], ""))  # вне резерва Notion Codex не виден
        self.conf["reserve"] = {"manual": True}
        self.run_for(60)
        a = N.codex_args()
        self.assertEqual(a[0::2], ["-c", "-c", "-c"])
        self.assertEqual(a[1], 'mcp_servers.notion.url="%s"' % N.MCP_URL)
        # открыты ровно четыре инструмента агента, ничего лишнего, и без вопроса на каждый вызов
        self.assertEqual(a[3], "mcp_servers.notion.enabled_tools=[%s]" % ",".join('"%s"' % t for t in N.CODEX_TOOLS))
        self.assertEqual(len(N.CODEX_TOOLS), 4)
        self.assertEqual(a[5], 'mcp_servers.notion.default_tools_approval_mode="approve"')
        note = N.codex_note()
        self.assertIn("Helper", note)
        self.assertNotIn("agent://", note)  # ссылка агента в текст сообщения не попадает
        for t in N.CODEX_TOOLS:
            self.assertIn(t, note)
        self.conf["reserve"] = {}
        self.run_for(400)
        self.assertEqual((N.codex_args(), N.codex_note()), ([], ""))  # резерв кончился — ключи и напоминание сняты

    def test_codex_note_names_the_real_cause(self):
        self.conf["reserve"] = {"manual": True}
        self.run_for(60)
        self.assertIn("отключён человеком вручную", N.codex_note())
        self.assertNotIn("лимиты кончились", N.codex_note())
        self.conf["reserve"] = {"auto": True}
        self.lv = LV("hard")
        self.run_for(400)
        self.assertEqual(N.public()["reserve"]["why"], "claude_down")
        self.assertIn("лимиты кончились", N.codex_note())

    def test_no_agent_url_or_no_notion_means_not_ready(self):
        self.lv = LV("hard")
        for patch in ({"url": ""},):
            self.conf = dict(self.conf, **patch)
            self.run_for(300)
            self.assertFalse(N.active(), patch)
        self.assertEqual((self.emg.on_calls, self.sent), ([], []))
        self.conf = {"name": "Helper", "url": "agent://s/a", "reserve": {"auto": True}}
        os.unlink(self.creds)
        self.run_for(300)
        self.assertFalse(N.active())

    def test_agent_lost_during_case_ends_everything(self):
        self.lv = LV("hard")
        self.run_for(300)
        self.assertTrue(N.active())
        self.conf = dict(self.conf, url="")
        self.run_for(60)
        self.assertFalse(N.active())
        self.assertEqual(len(self.emg.off_calls), 1)

    def test_emergency_failure_reported_once_and_not_retried(self):
        self.emg.ok = False
        self.lv = LV("hard")
        self.run_for(600)
        self.assertTrue(N.active())
        self.assertEqual(len(self.emg.on_calls), 1)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("НЕ включился", self.sent[0])
        self.assertIn("Проект не настроен", self.sent[0])

    def test_emergency_already_on_by_human_is_left_alone(self):
        self.emg._active = True
        self.lv = LV("hard")
        self.run_for(300)
        self.assertEqual(self.emg.on_calls, [])
        self.assertIn("оставлен как есть", self.sent[0])
        self.lv = LV("none")
        self.run_for(300)
        self.assertEqual(self.emg.off_calls, [])  # чужое включение резерв не снимает
        self.assertTrue(self.emg.active())

    def test_emergency_turned_off_by_hand_is_not_turned_back_in_same_case(self):
        self.lv = LV("hard")
        self.run_for(300)
        self.assertEqual(len(self.emg.on_calls), 1)
        self.emg._active = False  # человек выключил кнопкой
        self.run_for(300)
        self.assertEqual(len(self.emg.on_calls), 1)
        self.lv = LV("none")
        self.run_for(300)
        self.lv = LV("hard")  # новый случай — можно снова
        self.run_for(300)
        self.assertEqual(len(self.emg.on_calls), 2)

    def test_state_survives_restart(self):
        self.lv = LV("hard")
        self.run_for(300)
        self.assertTrue(N.active())
        with open(os.path.join(self.d, "notion_reserve.json")) as f:
            self.assertEqual(json.load(f)["active"], True)
        self.run_for(60)  # «новый процесс»: всё берётся из файла, второго включения и сообщения нет
        self.assertEqual((len(self.emg.on_calls), len(self.sent)), (1, 1))

    def test_level_provider_failure_is_unknown_not_crash(self):
        def boom():
            raise RuntimeError("x")
        N.LEVEL = boom
        self.run_for(300)
        self.assertFalse(N.active())

    def test_public_reserve_block(self):
        self.lv = LV("hard")
        p = N.public()["reserve"]
        self.assertEqual((p["auto"], p["auto_emergency"], p["manual"], p["active"]), (True, True, False, False))
        self.assertEqual((p["claude"], p["ready"]), ("down", True))
        self.assertEqual(p["emergency"], {"configured": True, "active": False, "by_reserve": False})
        self.assertRegex(p["reset"], r"^\d\d:\d\d$")
        self.assertNotIn("agent://", json.dumps(N.public()))

    def test_state_file_private(self):
        self.lv = LV("hard")
        self.run_for(300)
        self.assertEqual(os.stat(os.path.join(self.d, "notion_reserve.json")).st_mode & 0o777, 0o600)
