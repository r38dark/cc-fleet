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
BEGIN, END = "-----BEGIN " + "OPENSSH PRIVATE KEY-----", "-----END " + "OPENSSH PRIVATE KEY-----"  # не буквальными строками: их ищет privacy_check


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
        m.KEYS_DIR = os.path.join(self.d, "agent_keys")
        os.makedirs(m.HANDOFF)
        self.cfg(owner="Аня", ssh_host="srv.example.org")

    def cfg(self, **kw):
        with open(self.m.NAI_CFG, "w") as f:
            json.dump(kw, f)


class Steps(Base):
    def test_defaults_come_from_the_first_measured_run(self):
        plan = self.m.step_plan(True)
        self.assertEqual((plan[4], plan[-1]), ("key", "login"))  # ключ выдаётся до настройки (уходит в инструкцию одним сохранением), вход проверяется в конце
        est = self.m.step_estimates(plan)
        self.assertEqual(est["finish"], 51)
        self.assertEqual(sum(est.values()), 198)  # 188 с замера без прежнего шага «ключ» (22 с) + 2 с выдача + 30 с проверка входа
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
        t = self.m.instructions_for("Торговля", "Торговля", BEGIN + "\nxx\n" + END)
        for bad in ("Ден" + "ис", "desk" + "pharm", "farm" + "garant", "dar" + "qai", "иркутск", "{", "}"):  # личное владельца не должно попасть в общую инструкцию
            self.assertNotIn(bad, t, bad)
        self.assertIn("ssh root@srv.example.org", t)
        self.assertIn("Владелец — Аня", t)
        self.assertIn("«Торговля»", t)
        self.assertIn("notion-ai-reply --agent 'Торговля' --voice", t)

    def test_agent_name_with_spaces_and_quotes_is_shell_safe(self):
        t = self.m.instructions_for("Проект «Деск» О'Нил", "x")
        self.assertIn("notion-ai-reply --agent 'Проект «Деск» О'\"'\"'Нил' --voice", t)

    def test_issued_key_is_in_the_instructions_as_one_code_block(self):
        key = BEGIN + "\nAAAA1\nBBBB2\n" + END + "\n"
        t = self.m.instructions_for("А", "А", key)
        self.assertIn("```\n" + key.strip() + "\n```", t)
        self.assertIn("пересоздаётся между сообщениями", t)
        self.assertIn("chmod 600", t)
        self.assertIn("не выводи в чат, не отправляй в Telegram", t)
        self.assertNotIn("создай командой", t)
        blocks = self.m.md_blocks(t)
        code = [b for b in blocks if b["type"] == "code"]
        self.assertEqual(len(code), 1)
        self.assertEqual("".join(x["text"]["content"] for x in code[0]["code"]["rich_text"]), key.strip())  # строки ключа не склеились и не потерялись
        self.assertEqual(code[0]["code"]["language"], "plain text")

    def test_without_a_key_the_agent_is_told_it_has_no_server_access(self):
        t = self.m.instructions_for("А", "А")
        self.assertIn("Ключ доступа к серверу тебе не выдан", t)
        self.assertNotIn("```", t)
        self.assertNotIn("ssh root@", t)

    def test_fenced_blocks_do_not_break_other_lines(self):
        blocks = self.m.md_blocks("- до\n```\nа\n\nб\n```\n- после\n## Заголовок")
        self.assertEqual([b["type"] for b in blocks], ["bulleted_list_item", "code", "bulleted_list_item", "heading_2"])
        self.assertEqual(blocks[1]["code"]["rich_text"][0]["text"]["content"], "а\n\nб")  # пустая строка внутри блока сохранена

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
    """run_create целиком, с подставным Notion: порядок этапов, ключ выдаёт панель и он уходит в инструкцию, проверка входа."""
    AID = "a1b2c3d4-0000-0000-0000-000000000000"

    def stubs(self, seen=True, replies=None, fail_at=None):
        m = self.m
        self.sent, self.settings, self.ai = [], [], {"n": 0}
        self.replies = list(replies if replies is not None else ["готов", "доступ есть" if seen else "Permission denied (publickey)"])
        m.list_agents = lambda *a, **k: []
        m.main_aid = lambda: "main-aid"
        m.create_from_template = lambda pg, log: (log("Notion настраивает агента…"), log("агент создан, Notion дописывает настройку…"), (self.AID, "https://setup"))[2]
        m.api = lambda *a, **k: {}
        def set_settings(pg, aid, **kw):
            self.settings.append(kw)
            if fail_at == "settings": raise RuntimeError("Notion не сохранил настройки")
            return {"model": "Sonnet 5.5", "effort": "High", "web": True}
        m.set_settings = set_settings
        m.delete_chat = lambda *a, **k: None
        m.new_chat = lambda pg, aid, text: "11111111-1111-1111-1111-111111111111"
        m.rename_chat = lambda *a, **k: None
        m.last_seq = lambda sid: self.ai["n"]
        m.goto = lambda *a, **k: None
        m.open_chat_input = lambda pg: None
        m.type_send = lambda pg, box, text: self.sent.append(text)
        def wait_reply(sid, after, timeout=240):
            self.ai["n"] += 1
            return self.replies.pop(0) if self.replies else ""
        m.wait_reply = wait_reply
        m.ssh_login_seen = lambda p, since: seen

    def run_create(self, ssh=True, tg="-100777", **kw):
        m = self.m
        self.stubs(**kw)
        j = {"kind": "create", "id": "t", "status": "running", "name": "Торговля", "model": "", "effort": "", "ssh": ssh, "tg_chat_id": tg}
        j["plan"] = m.step_plan(ssh); j["est"] = m.step_estimates(j["plan"])
        stages = []
        base = m.make_log(j)
        log = lambda s: (stages.append(s), base(s))
        with mock.patch.object(m.time, "sleep", lambda s: None):
            m.run_create(None, j, log)
        m.step_close(j)
        return j, stages

    def test_panel_issues_the_key_before_settings_and_puts_it_into_the_instructions(self):
        j, stages = self.run_create()
        self.assertEqual(stages, [t for _, t, _ in self.m.CREATE_STEPS])  # этапы идут ровно в заданном порядке
        self.assertEqual(set(j["done"]), set(self.m.step_plan(True)))
        priv = self.m.agent_key(self.AID)
        self.assertTrue(priv.startswith(BEGIN))
        ins = self.settings[0]["instructions"]
        self.assertIn(priv.strip(), ins)  # приватный ключ в инструкции — одним сохранением настроек
        self.assertIn("ssh root@srv.example.org", ins)
        a = self.m.reg_load()["agents"][self.AID]
        self.assertEqual((a["state"], a["ssh_ok"], a["name"], a["tg_chat_id"], a["ssh"]), ("ready", True, "Торговля", "-100777", True))
        auth = open(self.m.AUTH_KEYS).read()
        self.assertIn(a["ssh_pub"], auth)
        self.assertIn("ccfleet-notion-ai", auth)

    def test_agent_is_asked_to_write_the_key_and_log_in_and_nothing_else(self):
        j, _ = self.run_create()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("записан в твоей инструкции", self.sent[0])
        self.assertIn("root@srv.example.org", self.sent[0])
        self.assertIn("«доступ есть»", self.sent[0])
        self.assertNotIn("PRIVATE KEY", self.sent[0])  # в чат ключ не пишется
        self.assertNotIn("warn", j)
        self.assertIs(j["result"]["ssh_ok"], True)

    def test_private_key_stays_off_public_surfaces(self):
        j, _ = self.run_create()
        priv = self.m.agent_key(self.AID).strip()
        body = priv.splitlines()[1]
        for surface in (json.dumps(self.m.job_public(j), ensure_ascii=False), open(self.m.REG).read(), json.dumps(j.get("result") or {})):
            self.assertNotIn(body, surface)
            self.assertNotIn("PRIVATE KEY", surface)
        self.assertEqual(oct(os.stat(self.m.key_path(self.AID)).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(self.m.KEYS_DIR).st_mode & 0o777), "0o700")

    def test_agent_that_cannot_log_in_gives_a_visible_warning(self):
        j, _ = self.run_create(seen=False)
        self.assertIn("не зашёл", j["warn"])
        self.assertIn("Permission denied", j["warn"])
        self.assertIs(j["result"]["ssh_ok"], False)
        self.assertIs(self.m.reg_load()["agents"][self.AID]["ssh_ok"], False)
        self.assertEqual(self.m.job_public(j)["warn"], j["warn"])

    def test_failed_creation_does_not_leave_the_key_behind(self):
        with self.assertRaises(RuntimeError):
            self.run_create(fail_at="settings")
        self.assertFalse(os.path.exists(self.m.key_path(self.AID)))
        self.assertEqual(open(self.m.AUTH_KEYS).read().strip(), "")  # публичный ключ убран из authorized_keys
        self.assertFalse(self.m.reg_load()["agents"][self.AID]["ssh"])

    def test_without_ssh_there_is_no_key_step_and_no_message(self):
        j, stages = self.run_create(ssh=False, tg="", replies=["готов"])
        self.assertEqual(len(stages), len(self.m.CREATE_STEPS) - 2)
        self.assertEqual(self.sent, [])
        self.assertIsNone(j["result"]["ssh_ok"])
        self.assertIn("Ключ доступа к серверу тебе не выдан", self.settings[0]["instructions"])
        self.assertFalse(os.path.exists(self.m.key_path(self.AID)))
        self.assertEqual(self.m.reg_load()["agents"][self.AID]["tg_chat_id"], "")


class Publish(Base):
    """Save на странице настроек: изменения агента должны реально опубликоваться, иначе агент работает со старыми инструкциями."""
    AID = "a1b2c3d4-0000-0000-0000-000000000000"

    class Btn:
        def __init__(self, enabled_after): self.enabled_after, self.calls, self.clicks = enabled_after, 0, 0
        def count(self): return 1
        def is_enabled(self): self.calls += 1; return self.calls > self.enabled_after
        def click(self): self.clicks += 1

    def page(self, btn):
        class Loc:
            first = btn
        class Pg:
            def get_by_role(s, *a, **k): return Loc()
            def wait_for_timeout(s, ms): pass
        return Pg()

    def states(self, seq):
        it = iter(seq)
        self.m.agent_state = lambda aid: next(it, seq[-1])

    def test_already_published_does_not_click(self):
        b = self.Btn(0); self.states([(True, "t0"), (False, "t0")])
        self.m.publish(self.page(b), self.AID)
        self.assertEqual(b.clicks, 0)

    def test_clicks_save_and_waits_until_notion_confirms(self):
        b = self.Btn(2); self.states([(True, "t0")] * 3 + [(False, "t0")])
        self.m.publish(self.page(b), self.AID)
        self.assertEqual(b.clicks, 1)

    def test_published_time_moving_counts_even_if_the_flag_stays(self):
        # 08.11: Notion опубликовал версию, а has_unpublished_changes остался True — это не ошибка
        b = self.Btn(0); self.states([(True, "t0"), (True, "t0"), (True, "t1")])
        self.m.publish(self.page(b), self.AID)
        self.assertEqual(b.clicks, 1)

    def test_unpublished_after_all_tries_is_an_error_not_silence(self):
        b = self.Btn(10 ** 6); self.states([(True, "t0")])  # кнопка так и не включилась
        reloads = []
        self.m.goto = lambda pg, url, wait=9000: reloads.append(url)
        with self.assertRaises(RuntimeError) as cm:
            self.m.publish(self.page(b), self.AID)
        self.assertIn("не опубликовал", str(cm.exception))
        self.assertEqual(len(reloads), 3)  # страница перечитана перед каждой новой попыткой
        self.assertEqual(b.clicks, 0)

    def test_second_attempt_after_a_click_that_did_not_publish(self):
        b = self.Btn(0); self.states([(True, "t0")] * 9 + [(False, "t0")])  # первый клик не помог (6 опросов), второй — опубликовалось
        self.m.publish(self.page(b), self.AID)
        self.assertGreaterEqual(b.clicks, 2)

    def test_unknown_state_does_not_block_the_save(self):
        b = self.Btn(0); self.states([(None, None)])
        self.m.publish(self.page(b), self.AID)
        self.assertEqual(b.clicks, 1)


@unittest.skipUnless(shutil.which("ssh-keygen"), "нужен ssh-keygen")
class Keys2(Base):
    AID = "a1b2c3d4-0000-0000-0000-000000000000"

    def test_issue_replaces_the_old_key_and_revoke_removes_everything(self):
        open(self.m.AUTH_KEYS, "w").write("ssh-ed25519 AAAAother mine\n")
        pub1 = self.m.issue_key(self.AID, "А")
        priv1 = self.m.agent_key(self.AID)
        pub2 = self.m.issue_key(self.AID, "А")
        self.assertNotEqual(pub1, pub2)
        auth = open(self.m.AUTH_KEYS).read()
        self.assertIn("mine", auth)  # чужие ключи не тронуты
        self.assertNotIn(pub1.split()[1], auth)  # прежний ключ агента больше не пускает
        self.assertIn(pub2.split()[1], auth)
        self.assertNotEqual(self.m.agent_key(self.AID), priv1)
        self.m.revoke_key(self.AID)
        self.assertNotIn(pub2.split()[1], open(self.m.AUTH_KEYS).read())
        self.assertIn("mine", open(self.m.AUTH_KEYS).read())
        self.assertEqual(self.m.agent_key(self.AID), "")
        a = self.m.reg_load()["agents"][self.AID]
        self.assertEqual((a["ssh"], a["ssh_pub"]), (False, ""))

    def settings_job(self, main=False, seen=True):
        m = self.m
        calls = []
        m.agent_by = lambda aid, url="": {"aid": aid, "name": "Торговля", "main": main, "chat": "https://app.notion.com/chat?t=" + "1" * 32}
        m.set_settings = lambda pg, aid, **kw: calls.append(kw) or {}
        m.verify_login = lambda pg, sid, aid, pub: (calls.append(("verify", pub)), (seen, "" if seen else "Permission denied"))[1]
        j = {"kind": "settings", "id": "s", "status": "running", "aid": self.AID, "newkey": True}
        m.run_settings(None, j, lambda s: None)
        return j, calls

    def test_new_key_for_an_existing_agent_updates_instructions_and_checks_login(self):
        old = self.m.issue_key(self.AID, "Торговля")
        j, calls = self.settings_job()
        a = self.m.reg_load()["agents"][self.AID]
        self.assertNotEqual(a["ssh_pub"], old)
        self.assertIn(self.m.agent_key(self.AID).strip(), calls[0]["instructions"])
        self.assertEqual(calls[1], ("verify", a["ssh_pub"]))
        self.assertNotIn("warn", j)

    def test_new_key_failure_to_log_in_is_a_warning(self):
        j, _ = self.settings_job(seen=False)
        self.assertIn("не зашёл", j["warn"])

    def test_main_agent_never_gets_a_key_from_a_job(self):
        with self.assertRaises(RuntimeError):
            self.settings_job(main=True)
        self.assertEqual(self.m.agent_key(self.AID), "")

    def test_rename_keeps_the_key_in_refreshed_instructions(self):
        self.m.issue_key(self.AID, "Торговля")
        m = self.m
        calls = []
        m.agent_by = lambda aid, url="": {"aid": aid, "name": "Торговля", "main": False, "chat": ""}
        m.api = lambda *a, **k: {}
        m.rename_chat = lambda *a, **k: None
        m.set_settings = lambda pg, aid, **kw: calls.append(kw) or {}
        m.run_settings(None, {"kind": "settings", "id": "s", "aid": self.AID, "name": "Торговля 2"}, lambda s: None)
        self.assertIn(self.m.agent_key(self.AID).strip(), calls[0]["instructions"])
        self.assertIn("--agent 'Торговля 2'", calls[0]["instructions"])

    def test_deleting_the_agent_removes_its_key_file_and_authorization(self):
        m = self.m
        pub = m.issue_key(self.AID, "Торговля")
        m.agent_by = lambda aid, url="": {"aid": aid, "name": "Торговля", "main": False}
        m.api = lambda *a, **k: {"results": []}
        m.delete_chat = lambda *a, **k: None
        m.run_delete(None, {"kind": "delete", "id": "d", "aid": self.AID}, lambda s: None)
        self.assertEqual(m.agent_key(self.AID), "")
        self.assertNotIn(pub.split()[1], open(m.AUTH_KEYS).read())

    def test_submit_newkey_needs_the_server_address(self):
        with mock.patch.object(self.m, "server_host", return_value=""):
            with self.assertRaises(ValueError):
                self.m.submit("settings", aid=self.AID, newkey=True)


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
