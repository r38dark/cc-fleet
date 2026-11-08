# Создание агентов Notion (notion_ai/web/nagents.py, notion_ai/bin/notion-ai-reply): этапы и полоса по времени, ключ доступа
# (добавлен → агенту сказано → вход проверен), Telegram у агента, инструкция без личных данных.
# Ни сеть, ни Notion, ни настоящий sshd не трогаются: модуль грузится из исходника, всё внешнее подменено.
# python3 -m unittest test_cc_notion_agents -v
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def keygen(d):
    k = os.path.join(d, "k")
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "t", "-f", k], check=True)
    return open(k + ".pub").read().strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="nagents_")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.m = load(os.path.join(HERE, "notion_ai", "web", "nagents.py"), "nagents_under_test")
        m = self.m
        m.REG = os.path.join(self.d, "nagents.json")
        m.INSTR = os.path.join(HERE, "notion_ai", "web", "agent_instructions.md")
        m.INSTR_LOCAL = os.path.join(self.d, "agent_instructions.local.md")
        m.NAI_CFG = os.path.join(self.d, "notion_ai.json")
        m.AUTH_KEYS = os.path.join(self.d, "authorized_keys")
        m.HANDOFF = os.path.join(self.d, "handoff")
        os.makedirs(m.HANDOFF)
        self.cfg(owner="Аня", ssh_host="srv.example.org")

    def cfg(self, **kw):
        with open(self.m.NAI_CFG, "w") as f:
            json.dump(kw, f)


class Steps(Base):
    def test_defaults_come_from_the_first_measured_run(self):
        plan = self.m.step_plan(True)
        self.assertEqual(plan[-2:], ["key", "login"])
        est = self.m.step_estimates(plan)
        self.assertEqual(est["finish"], 51)
        self.assertEqual(sum(est.values()), 218)  # 188 с замера + 30 с на проверку входа
        self.assertNotIn("key", self.m.step_plan(False))
        self.assertNotIn("login", self.m.step_plan(False))

    def test_history_replaces_defaults_and_keeps_last_five(self):
        for sec in (10, 20, 30, 40, 50, 60):
            self.m.timing_record({"done": {"finish": sec}})
        hist = self.m.reg_load()["timing"]["finish"]
        self.assertEqual(hist, [20, 30, 40, 50, 60])
        self.assertEqual(self.m.step_estimates(["finish"])["finish"], 40)

    def job(self, ssh=True):
        j = {"kind": "create", "status": "running", "plan": self.m.step_plan(ssh), "id": "t"}
        j["est"] = self.m.step_estimates(j["plan"])
        return j

    def test_progress_is_monotonic_and_never_100_until_done(self):
        j = self.job()
        t0 = 1000.0
        self.assertEqual(self.m.progress_of(j, t0)["pct"], 0)
        seen = []
        now = t0
        for key in j["plan"]:
            self.m.step_mark(j, key, now)
            now += j["est"][key]
            seen.append(self.m.progress_of(j, now - 0.1))
        pcts = [x["pct"] for x in seen]
        self.assertEqual(pcts, sorted(pcts))
        self.assertLess(pcts[-1], 100)
        self.assertEqual([x["step"] for x in seen], list(range(1, len(j["plan"]) + 1)))
        self.assertEqual(seen[0]["steps"], len(j["plan"]))
        self.m.step_close(j, now)
        j["status"] = "done"
        self.assertEqual(self.m.progress_of(j), dict(pct=100, eta=0, step=len(j["plan"]), steps=len(j["plan"])))

    def test_slow_step_does_not_push_the_bar_past_its_share(self):
        j = self.job()
        self.m.step_mark(j, "tpl", 0)
        slow = self.m.progress_of(j, 10 * 60)  # шаг идёт в 30 раз дольше обычного
        share = j["est"]["tpl"] / sum(j["est"].values())
        self.assertLessEqual(slow["pct"], int(100 * share) + 1)
        self.assertGreaterEqual(slow["eta"], sum(j["est"][k] for k in j["plan"][1:]))  # «осталось» не обнуляется, пока этапы впереди

    def test_log_texts_map_to_steps_and_other_jobs_have_no_progress(self):
        j = self.job()
        log = self.m.make_log(j)
        for _, text, _ in self.m.CREATE_STEPS:
            log(text)
        self.assertEqual(j["cur"], "login")
        self.assertEqual(set(j["done"]), set(self.m.step_plan(True)[:-1]))
        s = {"kind": "settings", "status": "running", "id": "s"}
        self.m.make_log(s)("модель и effort в настройках агента…")
        self.assertEqual(self.m.progress_of(s), {})

    def test_job_public_carries_progress_only_for_create(self):
        j = self.job()
        self.m.step_mark(j, "name", 5)
        pub = self.m.job_public(j)
        for k in ("pct", "eta", "step", "steps"):
            self.assertIn(k, pub)
        self.assertNotIn("pct", self.m.job_public({"kind": "delete", "status": "running", "id": "d"}))

    def test_submit_checks_telegram_id_and_server_address(self):
        with self.assertRaises(ValueError):
            self.m.submit("create", name="Агент", tg_chat_id="abc")
        self.cfg(owner="Аня", ssh_host="")
        with mock.patch.object(self.m, "server_host", return_value=""):
            with self.assertRaises(ValueError):
                self.m.submit("create", name="Агент", ssh=True)
        for good in ("", "-1001234567890", "123456", "@trade_channel"):
            self.m.jobs.clear()
            self.m.job_q.clear()
            j = self.m.submit("create", name="Агент", tg_chat_id=good, ssh=False)
            self.assertEqual(j["plan"], self.m.step_plan(False))


class Instructions(Base):
    def test_no_personal_data_and_placeholders_are_filled(self):
        t = self.m.instructions_for("Торговля", "Торговля")
        for bad in ("Ден" + "ис", "desk" + "pharm", "farm" + "garant", "dar" + "qai", "иркутск", "{", "}"):  # личное владельца не должно попасть в общую инструкцию
            self.assertNotIn(bad, t, bad)
        self.assertIn("ssh root@srv.example.org", t)
        self.assertIn("Владелец — Аня", t)
        self.assertIn("«Торговля»", t)
        self.assertIn("notion-ai-reply --agent 'Торговля' --voice", t)

    def test_agent_name_with_spaces_and_quotes_is_shell_safe(self):
        t = self.m.instructions_for("Проект «Деск» О'Нил", "x")
        self.assertIn("notion-ai-reply --agent 'Проект «Деск» О'\"'\"'Нил' --voice", t)

    def test_agent_is_told_the_panel_adds_the_key(self):
        t = self.m.instructions_for("А", "А")
        self.assertIn("Панель балансера сама добавит её на сервер", t)
        self.assertNotIn("Владелец добавит её на сервер", t)

    def test_local_rules_are_appended_and_last_file_is_detected(self):
        open(self.m.INSTR_LOCAL, "w").write("- Личное правило сервера.\n")
        open(os.path.join(self.m.HANDOFF, "boss_last.md"), "w").write("x")
        t = self.m.instructions_for("А", "А")
        self.assertIn("Личное правило сервера.", t)
        self.assertIn("`boss_last.md`", t)

    def test_server_address_falls_back_to_external_ip(self):
        self.cfg(owner="Аня", ssh_host="")
        self.m._HOST.update(ts=0, v="")

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return b"203.0.113.7\n"
        with mock.patch.object(self.m.urllib.request, "urlopen", return_value=R()):
            self.assertEqual(self.m.server_host(), "203.0.113.7")
        self.m._HOST.update(ts=0, v="")
        with mock.patch.object(self.m.urllib.request, "urlopen", side_effect=OSError("нет сети")), \
                mock.patch.object(subprocess, "run", side_effect=OSError("нет hostname")):
            self.assertEqual(self.m.server_host(), "")


@unittest.skipUnless(shutil.which("ssh-keygen"), "нужен ssh-keygen")
class Keys(Base):
    def test_fingerprint_matches_ssh_keygen(self):
        pub = keygen(self.d)
        out = subprocess.run(["ssh-keygen", "-lf", os.path.join(self.d, "k.pub")], capture_output=True, text=True).stdout.split()[1]
        self.assertEqual(self.m.key_fingerprint(pub), out)

    def test_login_is_seen_only_for_this_key_and_only_after_the_moment(self):
        pub = keygen(self.d)
        fp = self.m.key_fingerprint(pub)
        line = "Accepted publickey for root from 198.51.100.1 port 5 ssh2: ED25519 " + fp
        other = "Accepted publickey for root from 198.51.100.1 port 5 ssh2: ED25519 SHA256:" + "A" * 43
        ran = []

        def fake(cmd, **kw):
            ran.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=line + "\n", stderr="")
        with mock.patch.object(subprocess, "run", fake):
            self.assertTrue(self.m.ssh_login_seen(pub, 1_700_000_000))
        self.assertIn("--since", ran[0])
        with mock.patch.object(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=other + "\n", stderr="")):
            self.assertFalse(self.m.ssh_login_seen(pub, 1_700_000_000))
        with mock.patch.object(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="Failed publickey for root " + fp + "\n", stderr="")):
            self.assertFalse(self.m.ssh_login_seen(pub, 1_700_000_000))  # неудачная попытка не считается входом


@unittest.skipUnless(shutil.which("ssh-keygen"), "нужен ssh-keygen")
class Create(Base):
    """run_create целиком, с подставным Notion: порядок этапов, сообщение агенту о ключе, итог проверки входа."""

    def run_create(self, ssh=True, seen=True, tg="-100777"):
        m = self.m
        pub = keygen(self.d)
        sent, ai = [], {"n": 0}
        replies = ["готов", pub + " notion-agent", "доступ есть" if seen else "Permission denied (publickey)"]
        m.list_agents = lambda *a, **k: []
        m.main_aid = lambda: "main-aid"
        m.create_from_template = lambda pg, log: (log("Notion настраивает агента…"), log("агент создан, Notion дописывает настройку…"), ("a1b2c3d4-0000-0000-0000-000000000000", "https://setup"))[2]
        m.api = lambda *a, **k: {}
        m.set_settings = lambda *a, **k: {"model": "Sonnet 5.5", "effort": "High", "web": True}
        m.delete_chat = lambda *a, **k: None
        m.new_chat = lambda pg, aid, text: "11111111-1111-1111-1111-111111111111"
        m.rename_chat = lambda *a, **k: None
        m.last_seq = lambda sid: ai["n"]
        m.goto = lambda *a, **k: None
        m.open_chat_input = lambda pg: None
        m.type_send = lambda pg, box, text: sent.append(text)

        def wait_reply(sid, after, timeout=240):
            ai["n"] += 1
            return replies.pop(0) if replies else ""
        m.wait_reply = wait_reply
        m.ssh_login_seen = lambda p, since: seen
        j = {"kind": "create", "id": "t", "status": "running", "name": "Торговля", "model": "", "effort": "", "ssh": ssh, "tg_chat_id": tg}
        j["plan"] = m.step_plan(ssh); j["est"] = m.step_estimates(j["plan"])
        log = m.make_log(j)
        stages = []
        orig = log
        log = lambda s: (stages.append(s), orig(s))
        with mock.patch.object(m.time, "sleep", lambda s: None):
            m.run_create(None, j, log)
        m.step_close(j)
        return j, sent, stages

    def test_ssh_flow_tells_the_agent_and_verifies_login(self):
        j, sent, stages = self.run_create()
        self.assertEqual(stages, [t for _, t, _ in self.m.CREATE_STEPS])  # этапы идут ровно в заданном порядке
        self.assertEqual(set(j["done"]), set(self.m.step_plan(True)))
        self.assertTrue(any("уже добавлен на сервер автоматически" in s and "root@srv.example.org" in s and "доступ есть" in s for s in sent), sent)
        self.assertNotIn("warn", j)
        self.assertIs(j["result"]["ssh_ok"], True)
        a = self.m.reg_load()["agents"]["a1b2c3d4-0000-0000-0000-000000000000"]
        self.assertEqual((a["state"], a["ssh_ok"], a["name"], a["tg_chat_id"]), ("ready", True, "Торговля", "-100777"))
        self.assertIn("ccfleet-notion-ai", open(self.m.AUTH_KEYS).read())  # ключ в authorized_keys с меткой панели

    def test_agent_that_cannot_log_in_gives_a_visible_warning_not_ready_silence(self):
        j, sent, _ = self.run_create(seen=False)
        self.assertIn("не зашёл", j["warn"])
        self.assertIn("Permission denied", j["warn"])
        self.assertIs(j["result"]["ssh_ok"], False)
        self.assertIs(self.m.reg_load()["agents"]["a1b2c3d4-0000-0000-0000-000000000000"]["ssh_ok"], False)
        self.assertEqual(self.m.job_public(j)["warn"], j["warn"])

    def test_without_ssh_there_is_no_key_step_and_no_message(self):
        j, sent, stages = self.run_create(ssh=False, tg="")
        self.assertEqual(len(stages), len(self.m.CREATE_STEPS) - 2)
        self.assertEqual(sent, [])
        self.assertIsNone(j["result"]["ssh_ok"])
        self.assertEqual(self.m.reg_load()["agents"]["a1b2c3d4-0000-0000-0000-000000000000"]["tg_chat_id"], "")


class Telegram(Base):
    AID = "a1b2c3d4-0000-0000-0000-000000000000"

    def setUp(self):
        super().setUp()
        self.m.main_aid = lambda: ""

    def test_set_tg_validates_and_saves_per_agent(self):
        self.m.reg_set(self.AID, name="Торговля")
        self.assertTrue(self.m.set_tg(self.AID, "-1001234567890")["ok"])
        self.assertEqual(self.m.reg_load()["agents"][self.AID]["tg_chat_id"], "-1001234567890")
        self.assertIn("основной канал", self.m.set_tg(self.AID, "")["message"])
        with self.assertRaises(ValueError):
            self.m.set_tg(self.AID, "chat 1")
        with self.assertRaises(ValueError):
            self.m.set_tg("ffffffff-0000-0000-0000-000000000000", "-100123456")  # такого агента нет

    def test_list_shows_agent_chat(self):
        self.m.reg_set(self.AID, name="Торговля", tg_chat_id="-100777", ssh=True, ssh_ok=False, chat_sid="s")
        self.m.api = lambda method, path, body=None, **k: {"results": [{"id": self.AID, "agent_type": "custom_agent", "status": "active", "name": "Торговля", "model": {}}]}
        row = self.m.list_agents("", fresh=True)[0]
        self.assertEqual((row["tg"], row["ssh"], row["ssh_ok"]), ("-100777", True, False))

    def test_list_syncs_names_into_registry_and_keeps_the_old_one(self):
        self.m.reg_set(self.AID, name="Торговля", tg_chat_id="-100777", chat_sid="s")
        self.m.api = lambda method, path, body=None, **k: {"results": [{"id": self.AID, "agent_type": "custom_agent", "status": "active", "name": "Торговля 2", "model": {}}]}
        self.m.list_agents("", fresh=True)
        a = self.m.reg_load()["agents"][self.AID]
        self.assertEqual((a["name"], a["old_names"], a["tg_chat_id"]), ("Торговля 2", ["Торговля"], "-100777"))  # чат Telegram не потерялся
        # агент, созданный до этой версии, получает имя в реестре сам
        self.m.reg_set(self.AID, name="")
        self.m.list_agents("", fresh=True)
        self.assertEqual(self.m.reg_load()["agents"][self.AID]["name"], "Торговля 2")

    def test_tg_test_runs_the_reply_tool_and_shows_its_error(self):
        tool = os.path.join(self.d, "reply")
        open(tool, "w").write("#!/bin/sh\necho '{\"ok\": false, \"chat\": \"-1\", \"error\": \"chat not found\"}'\n")
        os.chmod(tool, 0o755)
        with mock.patch.dict(os.environ, {"CC_NAI_REPLY": tool}):
            r = self.m.tg_test("Торговля", "-1001234567890")
        self.assertFalse(r["ok"])
        self.assertIn("chat not found", r["message"])
        open(tool, "w").write("#!/bin/sh\necho '{\"ok\": true, \"chat\": \"-1001\"}'\n")
        with mock.patch.dict(os.environ, {"CC_NAI_REPLY": tool}):
            self.assertTrue(self.m.tg_test("Торговля", "")["ok"])
        with self.assertRaises(ValueError):
            self.m.tg_test("Торговля", "кривой id")


class ReplyTool(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="nairep_")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.m = load(os.path.join(HERE, "notion_ai", "bin", "notion-ai-reply"), "notion_ai_reply_under_test")
        m = self.m
        m.NAGENTS = os.path.join(self.d, "nagents.json")
        m.NAI_CFG = os.path.join(self.d, "notion_ai.json")
        m.CFG = os.path.join(self.d, "config.json")
        m.LOG = os.path.join(self.d, "log")
        json.dump({"agents": {"a": {"name": "Торговля", "old_names": ["Старое имя"], "tg_chat_id": "-100777"},
                              "b": {"name": "ДескФарм", "tg_chat_id": ""}}}, open(m.NAGENTS, "w"))
        json.dump({"chat_id": "555"}, open(m.CFG, "w"))
        json.dump({"voice": False}, open(m.NAI_CFG, "w"))
        self.sent = []
        m.api = lambda method, payload, timeout=30: self.sent.append((method, payload)) or {"ok": True}
        m.token = lambda: "1:x"

    def run_main(self, *argv):
        with mock.patch.object(sys, "argv", ["notion-ai-reply"] + list(argv)), mock.patch("sys.stdout"):
            self.m.main()

    def test_agent_name_finds_its_chat_also_after_rename(self):
        self.assertEqual(self.m.chat_id(self.m.agent_entry("торговля")), "-100777")
        self.assertEqual(self.m.chat_id(self.m.agent_entry("Старое  имя")), "-100777")
        self.assertEqual(self.m.chat_id(self.m.agent_entry("ДескФарм")), "555")  # свой чат не задан — основной канал балансера
        self.assertEqual(self.m.chat_id(None), "555")
        self.assertIsNone(self.m.agent_entry("нет такого"))

    def test_reply_goes_to_agent_chat_with_a_name_tag(self):
        self.run_main("--agent", "Торговля", "--no-voice", "Сделал")
        self.assertEqual(self.sent, [("sendMessage", {"chat_id": "-100777", "text": "[Торговля] Сделал"})])

    def test_main_agent_without_flag_is_unchanged(self):
        self.run_main("--no-voice", "Привет")
        self.assertEqual(self.sent, [("sendMessage", {"chat_id": "555", "text": "Привет"})])

    def test_unknown_agent_still_reaches_the_main_channel_with_the_tag(self):
        self.run_main("--agent", "Новенький", "--no-voice", "Привет")
        self.assertEqual(self.sent[0][1], {"chat_id": "555", "text": "[Новенький] Привет"})

    def test_tag_only_on_the_first_part_of_a_long_answer(self):
        self.run_main("--agent", "ДескФарм", "--no-voice", ("абв " * 1500).strip())
        self.assertGreater(len(self.sent), 1)
        self.assertTrue(self.sent[0][1]["text"].startswith("[ДескФарм] "))
        self.assertFalse(self.sent[1][1]["text"].startswith("["))

    def test_voice_names_the_agent(self):
        json.dump({"voice": True}, open(self.m.NAI_CFG, "w"))
        said = []
        self.m.tts_ok = lambda: True
        self.m.subprocess = mock.Mock(run=lambda cmd, **k: (said.append(cmd[1]), mock.Mock(returncode=1))[1])
        self.run_main("--agent", "Торговля", "Сделал всё")
        self.assertTrue(said and said[0].startswith("Отвечает Торговля. "), said)

    def test_test_mode_reports_ok_and_telegram_errors(self):
        out = []
        with mock.patch.object(sys, "argv", ["r", "--test", "--agent", "Торговля", "--chat", "-100999"]), mock.patch("builtins.print", lambda s: out.append(json.loads(s))):
            self.m.main()
        self.assertEqual(out[-1], {"ok": True, "chat": "-100999"})
        self.assertIn("✅ Проверка", self.sent[-1][1]["text"])
        import io
        import urllib.error

        def boom(method, payload, timeout=30):
            raise urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(json.dumps({"description": "Bad Request: chat not found"}).encode()))
        self.m.api = boom
        with mock.patch.object(sys, "argv", ["r", "--test", "--chat", "-100999"]), mock.patch("builtins.print", lambda s: out.append(json.loads(s))):
            self.m.main()
        self.assertFalse(out[-1]["ok"])
        self.assertIn("chat not found", out[-1]["error"])
        self.assertIn("бот добавлен", out[-1]["error"])


if __name__ == "__main__":
    unittest.main()
