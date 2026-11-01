import json, os, sys, tempfile, threading, time, types, unittest, unittest.mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_codex, cc_codex_bridge as br

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
prompt = a[a.index("--") + 1]
log = os.environ.get("FAKE_LOG")
with open(log, "a") as f:
    f.write(json.dumps({"argv": a, "cwd": os.getcwd(), "home": os.environ.get("CODEX_HOME")}) + "\n")
if prompt == "падение":
    print("boom: что-то сломалось")
    sys.exit(1)
if prompt == "401":
    print("401 Unauthorized, sign in again")
    sys.exit(1)
print(json.dumps({"type": "thread.started", "thread_id": "T-" + (a[2] if a[1] == "resume" else "NEW")}))
print(json.dumps({"type": "turn.started"}))
if "оформи" in prompt:
    os.makedirs("outbox", exist_ok=True)
    with open("outbox/task.md", "w") as f:
        f.write(os.environ.get("FAKE_DRAFT", "права: полные\nсделай X в проекте\n"))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ответ: " + prompt}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}))
'''


def put(path, text="", mode="w"):
    with open(path, mode, encoding="utf-8") as f:
        f.write(text)


def get(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        j = lambda *p: os.path.join(self.tmp, *p)
        os.makedirs(j("profiles", "gpt1"))
        put(j("profiles", "gpt1", "auth.json"), "{}")
        os.makedirs(j("proj"))
        self.fake = j("codex")
        put(self.fake, FAKE)
        os.chmod(self.fake, 0o755)
        self.log = j("fake.log")
        os.environ["FAKE_LOG"] = self.log
        os.environ.pop("FAKE_DRAFT", None)
        self.saved = (br.BASE, br.BIN, br.DELIVER, br.tg_api, br.NOW, cc_codex.PROFILES, br.DEFAULT_CHAT,
                      br.RESERVED_TOKENS, br.ACK_TIMEOUT, br.CONSOLE)
        br.CONSOLE = None
        br.BASE = j("base")
        os.makedirs(br.BASE)
        cc_codex.PROFILES = j("profiles")
        br.BIN = lambda: self.fake
        self.sent = []  # сообщения человеку
        self.console = []  # строки в консоль Claude
        self.delivered_ok = True
        br.DELIVER = lambda t: (self.console.append(t), self.delivered_ok)[1]

        def fake_api(token, method, payload=None, timeout=30):
            if method == "sendMessage":
                self.sent.append(payload["text"])
            if method == "getMe":
                return {"ok": True, "result": {"username": "cx_bot"}}
            return {"ok": True, "result": []}
        br.tg_api = fake_api
        self.now = [1000.0]
        br.NOW = lambda: self.now[0]
        br.DEFAULT_CHAT = lambda: None
        br.RESERVED_TOKENS = lambda: []
        self.addCleanup(self.restore)
        # токен и чат — прямо в файл настроек (UI-путь проверяется отдельно)
        s = br.load()
        s.update(token="123456:" + "A" * 30, chat_id="100200300", enabled=True, workdir=j("proj"), slot="")
        br._save(s)
        self.ex = br.ensure_exchange()
        self.proj = j("proj")

    def restore(self):
        # потоки моста гасим ДО возврата настоящих BASE и tg_api: иначе они пишут состояние в боевую папку и ходят в настоящий Telegram
        br.BRIDGE.stop()
        for t in (br.BRIDGE.poll_t, br.BRIDGE.watch_t, br.BRIDGE.lim_t):
            if t:
                t.join(5)
        (br.BASE, br.BIN, br.DELIVER, br.tg_api, br.NOW, cc_codex.PROFILES, br.DEFAULT_CHAT,
         br.RESERVED_TOKENS, br.ACK_TIMEOUT, br.CONSOLE) = self.saved

    def say(self, text, chat=100200300):
        br.BRIDGE.handle_update({"update_id": 1, "message": {"chat": {"id": chat}, "text": text}})
        w = br.BRIDGE.worker
        if w:
            w.join(20)

    def runs(self):
        return [json.loads(l) for l in get(self.log).splitlines()] if os.path.exists(self.log) else []


class Settings(Base):
    def test_plan_modes(self):
        s = br.load()
        self.assertEqual(br.plan(s), ("workspace-write", self.ex))
        for acc, sb in (("read", "read-only"), ("write", "workspace-write"), ("full", "danger-full-access")):
            s.update(mode="self", access=acc)
            self.assertEqual(br.plan(s), (sb, self.proj))

    def test_save_validates(self):
        self.assertFalse(br.save({"mode": "bogus"})[0])
        self.assertFalse(br.save({"access": "root"})[0])
        self.assertFalse(br.save({"task_rights": "all"})[0])
        self.assertFalse(br.save({"slot": "../x"})[0])
        self.assertFalse(br.save({"chat_id": "abc"})[0])

    def test_forbidden_workdir(self):
        for bad in ("/", "/root", "/etc", "/home", br.BASE, os.path.join(br.BASE, "x"), "relative", "/нет/такой"):
            ok, msg = br.save({"mode": "self", "workdir": bad})
            self.assertFalse(ok, bad)
        self.assertTrue(br.save({"mode": "self", "access": "read", "workdir": self.proj})[0])

    def test_full_needs_confirm_word(self):
        ok, msg = br.save({"mode": "self", "access": "full", "workdir": self.proj})
        self.assertFalse(ok)
        self.assertIn("подтверждаю", msg)
        self.assertEqual(br.load()["access"], "read")  # не сохранилось
        self.assertTrue(br.save({"mode": "self", "access": "full", "workdir": self.proj, "confirm": "подтверждаю"})[0])
        # повторное сохранение без смены не требует слова снова
        self.assertTrue(br.save({"mode": "self", "access": "full", "workdir": self.proj})[0])
        # полные права заданий — тоже за словом
        self.assertFalse(br.save({"task_rights": "full"})[0])
        self.assertTrue(br.save({"task_rights": "full", "confirm": "confirm"})[0])

    def test_token_hidden(self):
        pub = br.public()
        self.assertNotIn("token", pub)
        self.assertTrue(pub["token_set"])
        self.assertEqual(pub["token_tail"], "AAAA")
        self.assertNotIn("AAAAAAAAAA", json.dumps(pub))
        self.assertEqual(oct(os.stat(br.settings_path()).st_mode & 0o777), "0o600")

    def test_set_token(self):
        self.assertFalse(br.set_token("not a token")[0])
        good = "999999:" + "B" * 30
        br.RESERVED_TOKENS = lambda: [good]
        ok, msg = br.set_token(good)
        self.assertFalse(ok)
        self.assertIn("отдельный бот", msg)
        br.RESERVED_TOKENS = lambda: []
        ok, msg = br.set_token(good)
        self.assertTrue(ok)
        self.assertIn("@cx_bot", msg)
        self.assertEqual(br.load()["token"], good)
        br.clear_token()
        self.assertEqual(br.load()["token"], "")
        self.assertFalse(br.load()["enabled"])

    def test_enable_needs_token(self):
        br.clear_token()
        self.assertFalse(br.save({"enabled": True})[0])


class Chat(Base):
    def test_foreign_chat_ignored(self):
        self.say("привет", chat=111)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sent, [])

    def test_answer_and_resume(self):
        self.say("вопрос 1")
        self.assertEqual(self.sent[-1], "ответ: вопрос 1")
        r = self.runs()[0]
        self.assertEqual(r["cwd"], self.ex)
        self.assertIn("workspace-write", r["argv"])
        self.assertEqual(r["argv"][r["argv"].index("-C") + 1], self.ex)
        self.assertEqual(r["argv"][-2:], ["--", "вопрос 1"])
        self.assertEqual(r["home"], os.path.join(cc_codex.PROFILES, "gpt1"))
        self.say("вопрос 2")
        r2 = self.runs()[1]
        self.assertEqual(r2["argv"][:3], ["exec", "resume", "T-NEW"])
        self.assertIn('sandbox_mode="workspace-write"', r2["argv"])
        self.assertEqual(r2["cwd"], self.ex)
        self.say("/new")
        self.say("вопрос 3")
        self.assertNotIn("resume", self.runs()[2]["argv"])

    def test_self_mode_cwd_and_sandbox(self):
        br.save({"mode": "self", "access": "write", "workdir": self.proj})
        self.say("правь")
        r = self.runs()[0]
        self.assertEqual(r["cwd"], self.proj)
        self.assertEqual(r["argv"][r["argv"].index("-s") + 1], "workspace-write")
        br.save({"mode": "self", "access": "full", "workdir": self.proj, "confirm": "подтверждаю"})
        self.say("ещё")
        r = self.runs()[1]  # другой доступ → тот же разговор, но песочница переопределена
        self.assertEqual(r["argv"][:2], ["exec", "resume"])
        self.assertIn('sandbox_mode="danger-full-access"', r["argv"])
        self.assertFalse(os.path.exists(os.path.join(self.proj, "outbox")))  # черновик ищется только в «Посреднике»

    def test_prompt_with_dash_is_not_an_option(self):
        self.say("--help")
        self.assertEqual(self.sent[-1], "ответ: --help")

    def test_errors(self):
        self.say("падение")
        self.assertTrue(self.sent[-1].startswith("⚠️"))
        self.assertIn("boom", self.sent[-1])
        self.say("401")
        self.assertIn("Вход в ChatGPT истёк", self.sent[-1])
        os.remove(os.path.join(cc_codex.PROFILES, "gpt1", "auth.json"))
        self.say("а теперь")
        self.assertIn("Нет входа в ChatGPT", self.sent[-1])

    def test_long_answer_chunked(self):
        self.assertEqual([len(c) for c in br.chunks("a" * 9000)], [4000, 4000, 1000])
        parts = br.chunks("строка\n" * 1000, 4000)
        self.assertTrue(all(len(p) <= 4000 for p in parts))
        self.assertEqual("".join(parts).replace("\n", ""), "строка" * 1000)

    def test_busy(self):
        ev = threading.Event()
        br.BRIDGE.worker = threading.Thread(target=ev.wait)
        br.BRIDGE.worker.start()
        self.addCleanup(br.BRIDGE.worker.join, 5)  # дождаться выхода: живой воркер портил бы следующий тест («ещё работает»)
        self.addCleanup(ev.set)
        br.BRIDGE.handle_text("ещё вопрос")
        self.assertIn("ещё работает", self.sent[-1])
        self.assertEqual(self.runs(), [])


class Tasks(Base):
    def draft(self):
        self.say("оформи задание")
        return br._state()["pending"]

    def test_draft_shown_and_capped(self):
        p = self.draft()
        self.assertEqual(p["n"], 1)
        self.assertEqual(p["rights"], "dev")  # потолок по умолчанию «Дев», Codex просил «Полные»
        self.assertEqual(p["asked"], "full")
        shown = self.sent[-1]
        self.assertIn("Задание для Claude #1", shown)
        self.assertIn("сделай X в проекте", shown)
        self.assertIn("Права: Дев", shown)
        self.assertIn("Просили «Полные»", shown)
        self.assertFalse(os.path.exists(os.path.join(self.ex, "outbox", "task.md")))  # забран
        self.assertEqual(self.console, [])  # до «да» Claude не трогаем

    def test_no_rights_line_defaults_to_dev(self):
        os.environ["FAKE_DRAFT"] = "просто текст без прав\n"
        self.assertEqual(self.draft()["rights"], "dev")
        self.assertEqual(self.draft()["asked"], "")

    def test_ceiling_read_blocks_dev(self):
        br.save({"task_rights": "read"})
        os.environ["FAKE_DRAFT"] = "права: дев\nправка\n"
        self.assertEqual(self.draft()["rights"], "read")

    def test_yes_with_unwritable_folder_keeps_task_pending(self):
        # не удалось записать task.md — задание не теряется молча: «да/нет» остаётся, человек видит причину
        self.draft()
        with unittest.mock.patch("cc_codex_bridge.os.makedirs", side_effect=PermissionError(13, "Permission denied")):
            self.say("да")
        self.assertIsNotNone(br._state()["pending"])
        self.assertIn("Не смог записать", self.sent[-1])
        self.assertIn("Permission denied", self.sent[-1])
        self.assertEqual(self.console, [])
        self.say("да")  # после починки второе «да» отправляет как обычно
        self.assertIsNone(br._state()["pending"])
        self.assertEqual(len(self.console), 1)

    def test_yes_delivers(self):
        self.draft()
        self.say("да")
        self.assertEqual(len(self.console), 1)
        line = self.console[0]
        d = os.path.join(self.ex, "tasks", "1")
        self.assertIn("[TASK FROM CODEX #1, rights: dev", line)
        self.assertTrue(line.isascii(), "кириллица через screen stuff портится")
        self.assertIn(f"{d}/task.md", line)
        self.assertIn(f"{d}/ack", line)
        self.assertIn(f"{d}/result.md", line)
        self.assertNotRegex(line, r"[\n$\\^\"'`]")
        body = get(os.path.join(d, "task.md"))
        self.assertIn("сделай X в проекте", body)
        self.assertIn("Права: Дев", body)
        self.assertEqual(br._state()["tasks"]["1"]["state"], "sent")
        self.assertIsNone(br._state()["pending"])
        self.assertIn("ушло Claude", self.sent[-1])

    def test_yes_with_rights_override(self):
        self.draft()
        self.say("Да, права: полные")
        self.assertIn("rights: full", self.console[0])
        self.assertEqual(br._state()["tasks"]["1"]["rights"], "full")

    def test_yes_bad_rights_keeps_pending(self):
        self.draft()
        self.say("да, права: непонятно")
        self.assertEqual(self.console, [])
        self.assertIsNotNone(br._state()["pending"])

    def test_no_drops(self):
        self.draft()
        self.say("нет")
        self.assertEqual(self.console, [])
        self.assertIsNone(br._state()["pending"])
        self.assertIn("отменено", self.sent[-1])

    def test_question_with_yes_word_goes_to_codex(self):
        self.draft()
        n = len(self.runs())
        self.say("да как это работает?")
        self.assertEqual(self.console, [])
        self.assertEqual(len(self.runs()), n + 1)
        self.assertIsNotNone(br._state()["pending"])

    def test_task_dir_not_writable_text_is_fixed_after_yes(self):
        self.draft()
        self.say("да")
        d = os.path.join(self.ex, "tasks", "1")
        self.assertEqual(oct(os.stat(d).st_mode & 0o777), "0o755")

    def test_watch_ack_result(self):
        self.draft()
        self.say("да")
        d = os.path.join(self.ex, "tasks", "1")
        br.BRIDGE.watch_once()
        self.assertNotIn("взял", self.sent[-1])
        put(os.path.join(d, "ack"))
        br.BRIDGE.watch_once()
        self.assertIn("Claude взял задание #1", self.sent[-1])
        self.assertEqual(br._state()["tasks"]["1"]["state"], "accepted")
        n = len(self.sent)
        br.BRIDGE.watch_once()
        self.assertEqual(len(self.sent), n)  # повторно не сообщает
        put(os.path.join(d, "result.md"), "Готово: правка сделана, коммит abc123\n")
        br.BRIDGE.watch_once()
        self.assertIn("Claude выполнил #1", self.sent[-1])
        self.assertIn("коммит abc123", self.sent[-1])
        self.assertEqual(br._state()["tasks"]["1"]["state"], "done")

    def test_watch_result_without_ack(self):
        self.draft()
        self.say("да")
        put(os.path.join(self.ex, "tasks", "1", "result.md"), "сразу готово")
        br.BRIDGE.watch_once()
        self.assertIn("сразу готово", self.sent[-1])

    def test_timeout_and_retry(self):
        self.draft()
        self.say("да")
        self.now[0] += br.ACK_TIMEOUT - 1
        br.BRIDGE.watch_once()
        self.assertNotIn("не ответил", self.sent[-1])
        self.now[0] += 2
        br.BRIDGE.watch_once()
        self.assertIn("Claude не ответил на #1", self.sent[-1])
        self.assertEqual(br._state()["tasks"]["1"]["state"], "timeout")
        self.say("повтори 1")
        self.assertEqual(len(self.console), 2)
        self.assertEqual(br._state()["tasks"]["1"]["state"], "sent")
        self.say("повтори 99")
        self.assertIn("не найдено", self.sent[-1])

    def test_console_refused(self):
        self.delivered_ok = False
        self.draft()
        self.say("да")
        self.assertIn("не приняла", self.sent[-1])
        self.assertFalse(br._state()["tasks"]["1"]["delivered"])

    def test_numbers_increase_and_survive_state_reload(self):
        self.draft()
        self.say("нет")
        self.assertEqual(self.draft()["n"], 2)

    def test_self_mode_has_no_drafts(self):
        br.save({"mode": "self", "access": "read", "workdir": self.proj})
        self.say("оформи задание")
        self.assertIsNone(br._state()["pending"])

    def test_agents_md_written(self):
        t = get(os.path.join(self.ex, "AGENTS.md"))
        self.assertIn(self.proj, t)
        self.assertIn("outbox/task.md", t)

    def test_deliver_text_then_enter(self):
        """Текст и Enter — два вызова screen: длинный ввод одним куском TUI принимает за вставку."""
        calls = []
        real_run, real_delay = br.subprocess.run, br.ENTER_DELAY
        br.subprocess.run = lambda cmd, **kw: (calls.append(cmd), types.SimpleNamespace(returncode=0))[1]
        br.ENTER_DELAY = 0
        try:
            self.assertTrue(br.deliver_to_claude("a $b"))
        finally:
            br.subprocess.run, br.ENTER_DELAY = real_run, real_delay
        self.assertEqual([c[-1] for c in calls], ["a  b", "\r"])
        self.assertEqual(calls[0][:5], ["screen", "-S", br.SESSION(), "-p", "0"])

    def test_scr_safe(self):
        self.assertEqual(br._scr_safe('a$b\\c^d"e\'f`g\nh'), "a b c d e f g h")


class Profiles(Base):
    def test_builtin_apply(self):
        want = {"orchestrator": ("orchestrator", "read", "dev"), "codex": ("self", "write", "dev")}
        for pid, (mode, acc, rights) in want.items():
            ok, msg = br.apply_profile(pid)
            self.assertTrue(ok, msg)
            s = br.load()
            self.assertEqual((s["mode"], s["access"], s["task_rights"], s["enabled"]), (mode, acc, rights, True), pid)
            self.assertEqual(br.public()["profile"], pid)

    def test_switch_is_not_a_profile(self):
        """Выключатель бота живёт отдельно от профиля: профиль остаётся выбранным, профиль выключатель не трогает."""
        self.assertTrue(br.apply_profile("orchestrator")[0])
        self.assertTrue(br.save({"enabled": False})[0])
        self.assertEqual(br.public()["profile"], "orchestrator")
        self.assertFalse(br.running())
        ok, msg = br.apply_profile("codex")
        self.assertTrue(ok)
        self.assertIn("Бот выключен", msg)
        self.assertFalse(br.load()["enabled"])
        self.assertEqual(br.public()["profile"], "codex")
        self.assertTrue(br.save({"enabled": True})[0])
        self.assertTrue(br.running())
        self.assertTrue(br.apply_profile("orchestrator")[0])
        self.assertTrue(br.load()["enabled"])

    def test_legacy_profile_ids(self):
        """Профили прежних версий: «Запасной» стал «Codex» (тот же состав), остальные выбором не считаются."""
        self.assertTrue(br.save({"mode": "self", "access": "write"})[0])
        for old, want in (("standby", "codex"), ("second", ""), ("secretary", ""), ("off", "")):
            s = br.load()
            s["profile"] = old
            br._save(s)
            self.assertEqual(br.public()["profile"], want, old)
        self.assertTrue(br.save({"mode": "self", "access": "read"})[0])  # «Второй ИИ» (чтение) — не «Codex»
        s = br.load()
        s["profile"] = "second"
        br._save(s)
        self.assertEqual(br.public()["profile"], "")

    def test_no_token_applies_but_stays_off(self):
        s = br.load()
        s["token"], s["enabled"] = "", False
        br._save(s)
        ok, msg = br.apply_profile("orchestrator")
        self.assertTrue(ok)
        self.assertIn("подключишь бота", msg)
        s = br.load()
        self.assertEqual((s["mode"], s["enabled"]), ("orchestrator", False))
        self.assertEqual(br.public()["profile"], "orchestrator")

    def test_token_after_profile_turns_bridge_on(self):
        """Профиль выбран до токена → после подключения бота мост включается сам (баг 60075: оставался выключенным)."""
        s = br.load()
        s["token"], s["enabled"] = "", False
        br._save(s)
        self.assertTrue(br.apply_profile("orchestrator")[0])
        self.assertFalse(br.load()["enabled"])
        br.RESERVED_TOKENS = lambda: []
        ok, msg = br.set_token("999999:" + "B" * 30)
        self.assertTrue(ok, msg)
        self.assertIn("мост включён", msg)
        self.assertTrue(br.load()["enabled"])
        self.assertTrue(br.public()["enabled"])
        self.assertEqual(br.public()["profile"], "orchestrator")

    def test_token_without_profile_stays_off(self):
        s = br.load()
        s["token"], s["profile"], s["enabled"] = "", "", False
        br._save(s)
        br.RESERVED_TOKENS = lambda: []
        self.assertTrue(br.set_token("999999:" + "B" * 30)[0])
        self.assertFalse(br.load()["enabled"])

    def test_codex_profile_gets_default_workspace(self):
        """Рабочая папка не выбрана → профиль «Codex» берёт свою по умолчанию и кладёт в неё AGENTS.md; правленный человеком не трогает."""
        s = br.load()
        s["workdir"], s["project"] = "", os.path.join(self.tmp, "proj")
        br._save(s)
        ok, msg = br.apply_profile("codex")
        self.assertTrue(ok, msg)
        ws = br.workspace_dir()
        self.assertEqual(br.load()["workdir"], ws)
        self.assertEqual(br.public()["profile"], "codex")
        t = get(os.path.join(ws, "AGENTS.md"))
        self.assertIn(br.AGENTS_MARK, t)
        self.assertIn(os.path.join(self.tmp, "proj"), t)
        # проект сменили — наш файл обновляется
        other = os.path.join(self.tmp, "proj2")
        os.makedirs(other)
        self.assertTrue(br.save({"project": other})[0])
        self.assertIn(other, get(os.path.join(ws, "AGENTS.md")))
        # человек убрал метку и правил файл — больше не трогаем
        put(os.path.join(ws, "AGENTS.md"), "мой текст")
        self.assertTrue(br.save({"project": os.path.join(self.tmp, "proj")})[0])
        self.assertEqual(get(os.path.join(ws, "AGENTS.md")), "мой текст")

    def test_codex_profile_keeps_chosen_workdir(self):
        mine = os.path.join(self.tmp, "mine")
        os.makedirs(mine)
        self.assertTrue(br.save({"workdir": mine})[0])
        self.assertTrue(br.apply_profile("codex")[0])
        self.assertEqual(br.load()["workdir"], mine)
        self.assertFalse(os.path.exists(os.path.join(mine, "AGENTS.md")))  # чужую папку не засоряем

    def test_project_is_separate_from_workdir(self):
        """«Проект» (читает) и «Рабочая папка» (пишет) — разные папки; пока проект не задан, им служит рабочая."""
        self.assertEqual(br.project_dir(), br.load()["workdir"])
        proj = os.path.join(self.tmp, "snap")
        os.makedirs(proj)
        self.assertTrue(br.save({"project": proj})[0])
        s = br.load()
        self.assertEqual((s["project"], br.project_dir()), (proj, proj))
        self.assertEqual(s["workdir"], os.path.join(self.tmp, "proj"))
        self.assertEqual(br.public()["project"], proj)
        ok, msg = br.save({"project": "/etc"})
        self.assertFalse(ok)
        self.assertIn("Проект", msg)
        self.assertEqual(br.load()["project"], proj)

    def test_unknown_profile(self):
        self.assertFalse(br.apply_profile("nope")[0])

    def test_builtins_never_full(self):
        for pid, d in br.BUILTIN_PROFILES:
            self.assertNotEqual(d.get("access"), "full", pid)
            self.assertNotEqual(d.get("task_rights"), "full", pid)

    def seed_custom(self, pid, name, mode, access, rights):
        """Свой профиль прежней версии панели: новые не собираются, но сохранённые должны работать."""
        with br._lock:
            s = br.load()
            s["profiles"] = (s.get("profiles") or []) + [
                {"id": pid, "name": name, "mode": mode, "access": access, "task_rights": rights}]
            br._save(s)

    def test_legacy_custom_apply_delete_and_full_word(self):
        self.seed_custom("c1", "Мой полный", "self", "full", "dev")
        self.assertTrue(br.apply_profile("orchestrator")[0])
        ok, msg = br.apply_profile("c1")  # поднимать до полного — только со словом
        self.assertFalse(ok)
        self.assertIn("подтверждаю", msg)
        self.assertEqual(br.load()["mode"], "orchestrator")
        self.assertTrue(br.apply_profile("c1", "подтверждаю")[0])
        self.assertEqual(br.load()["access"], "full")
        self.assertEqual(br.public()["profile"], "c1")
        self.assertFalse(br.delete_profile("orchestrator")[0])  # встроенные не удаляются
        self.assertTrue(br.delete_profile("c1")[0])
        self.assertEqual(br.load()["profiles"], [])
        self.assertEqual(br.public()["profile"], "")

    def test_save_profile_is_gone(self):
        """Сборка своего профиля убрана: ни функции, ни лимита."""
        self.assertFalse(hasattr(br, "save_profile"))
        self.assertFalse(hasattr(br, "MAX_CUSTOM_PROFILES"))

    def test_manual_edit_drops_profile_mark(self):
        self.assertTrue(br.apply_profile("orchestrator")[0])
        self.assertEqual(br.public()["profile"], "orchestrator")
        self.assertTrue(br.save({"task_rights": "read"})[0])
        self.assertEqual(br.public()["profile"], "")

    def test_public_lists_profiles(self):
        pub = br.public()
        self.assertEqual([p["id"] for p in pub["profiles"]], ["orchestrator", "codex"])
        self.assertTrue(all(p["builtin"] for p in pub["profiles"]))
        self.seed_custom("c1", "Свой", "self", "write", "dev")
        self.assertEqual(br.public()["profiles"][-1]["name"], "Свой")
        self.assertFalse(br.public()["profiles"][-1]["builtin"])


class Orchestrator(Base):
    def setUp(self):
        super().setUp()
        self.assertTrue(br.save({"mode": "orchestrator"})[0])
        self.ex = br.exchange_dir()

    def draft(self):
        self.say("оформи задание")
        return br._state()["pending"]

    def done_task(self, text="Готово: коммит abc123"):
        self.draft()
        self.say("да")
        put(os.path.join(self.ex, "tasks", "1", "result.md"), text)
        br.BRIDGE.watch_once()
        w = br.BRIDGE.worker
        if w:
            w.join(20)

    def test_plan_and_agents(self):
        self.assertEqual(br.plan(br.load()), ("workspace-write", self.ex))
        t = get(os.path.join(self.ex, "AGENTS.md"))
        self.assertIn("оркестратор", t)
        self.assertIn("RESULT OF TASK", t)
        self.assertIn("На вопросы по проекту", t)  # на вопросы отвечает сам, шаг для Claude — только когда нужна правка или запуск

    def test_agents_back_to_secretary(self):
        self.assertTrue(br.save({"mode": "mediator"})[0])
        self.assertIn("секретарь", get(os.path.join(self.ex, "AGENTS.md")))

    def test_draft_still_needs_yes(self):
        p = self.draft()
        self.assertEqual(p["n"], 1)
        self.assertEqual(self.console, [])

    def test_result_goes_back_to_codex(self):
        self.done_task()
        last = self.runs()[-1]
        prompt = last["argv"][last["argv"].index("--") + 1]
        self.assertIn("[RESULT OF TASK #1 FROM CLAUDE]", prompt)
        self.assertIn("коммит abc123", prompt)
        self.assertIn("ответ: [RESULT OF TASK #1", self.sent[-1])  # ответ Codex ушёл человеку
        self.assertNotIn("feed", br._state()["tasks"]["1"])  # отдано один раз
        n = len(self.runs())
        br.BRIDGE.watch_once()
        self.assertEqual(len(self.runs()), n)

    def test_next_step_still_needs_yes(self):
        os.environ["FAKE_DRAFT"] = "права: дев\nследующий шаг\n"
        self.draft()
        self.say("да")
        put(os.path.join(self.ex, "tasks", "1", "result.md"), "ок")
        os.environ["FAKE_DRAFT"] = "права: дев\nшаг 2\n"
        # Codex на результат оформляет шаг 2 — подставляем «оформи» в тело, чтобы фейк записал черновик
        put(os.path.join(self.ex, "tasks", "1", "result.md"), "оформи шаг 2")
        br.BRIDGE.watch_once()
        br.BRIDGE.worker.join(20)
        self.assertEqual(br._state()["pending"]["n"], 2)
        self.assertEqual(len(self.console), 1)  # в консоль ушёл только шаг 1; шаг 2 ждёт «да»

    def test_feed_waits_while_busy(self):
        self.draft()
        self.say("да")
        put(os.path.join(self.ex, "tasks", "1", "result.md"), "ок")
        gate = threading.Event()
        br.BRIDGE.worker = threading.Thread(target=gate.wait, daemon=True)
        br.BRIDGE.worker.start()
        before = len(self.runs())
        br.BRIDGE.watch_once()
        self.assertEqual(len(self.runs()), before)
        self.assertTrue(br._state()["tasks"]["1"]["feed"])
        gate.set()
        br.BRIDGE.worker.join(5)
        br.BRIDGE.watch_once()
        br.BRIDGE.worker.join(20)
        self.assertEqual(len(self.runs()), before + 1)

    def test_mediator_does_not_feed_back(self):
        self.assertTrue(br.save({"mode": "mediator"})[0])
        self.draft()
        self.say("да")
        before = len(self.runs())
        put(os.path.join(self.ex, "tasks", "1", "result.md"), "ок")
        br.BRIDGE.watch_once()
        self.assertEqual(len(self.runs()), before)
        self.assertNotIn("feed", br._state()["tasks"]["1"])

    def test_feed_hidden_from_public(self):
        self.draft()
        self.say("да")
        put(os.path.join(self.ex, "tasks", "1", "result.md"), "ок")
        gate = threading.Event()
        br.BRIDGE.worker = threading.Thread(target=gate.wait, daemon=True)
        br.BRIDGE.worker.start()
        br.BRIDGE.watch_once()
        self.assertNotIn("feed", br.public()["tasks"][0])
        gate.set()

    def test_stop_word_clears_pending(self):
        self.draft()
        self.say("стоп")
        self.assertIsNone(br._state()["pending"])
        self.assertIn("Остановил", self.sent[-1])
        self.assertEqual(self.console, [])
        self.say("стоп")
        self.assertIn("ничего не запущено", self.sent[-1])


class FakeConsole:
    """Подставная консоль Codex: ask() отдаёт заранее заданное или ждёт, пока её прервут."""
    class ConsoleError(Exception):
        pass

    class Aborted(ConsoleError):
        pass

    def __init__(self):
        self.asked, self.interrupted, self.forgotten = [], 0, 0
        self.ok = True
        self.script = [("ответ из консоли", "TID-CON")]
        self.started = threading.Event()
        self.hold = None  # Event: ask ждёт его или abort

    def usable(self):
        return self.ok

    def ask(self, prompt, abort=None, timeout=None):
        self.asked.append(prompt)
        self.started.set()
        if self.hold is not None:
            t0 = time.time()
            while not self.hold.is_set() and time.time() - t0 < 10:
                if abort is not None and abort.is_set():
                    raise self.Aborted("остановлено")
                time.sleep(0.01)
        item = self.script.pop(0) if self.script else ("ещё ответ", "TID-CON")
        if isinstance(item, Exception):
            raise item
        return item

    def interrupt(self):
        self.interrupted += 1
        return True

    def forget(self):
        self.forgotten += 1


class ConsoleChat(Base):
    """Разговор Telegram ↔ консоль Codex: мост вводит сообщения в живой Codex, а не гоняет отдельный codex exec."""

    def setUp(self):
        super().setUp()
        self.con = FakeConsole()
        br.CONSOLE = self.con

    def test_answer_comes_from_console_not_exec(self):
        self.say("Привет из Telegram")
        self.assertEqual(self.sent[-1], "ответ из консоли")
        self.assertEqual(self.con.asked, ["Привет из Telegram"])
        self.assertEqual(self.runs(), [], "codex exec не запускался")
        self.assertEqual(br._state()["threads"], {"mediator|" + self.ex: "TID-CON"})
        self.assertFalse(br.BRIDGE.in_console)

    def test_console_not_usable_falls_back_to_exec(self):
        self.con.ok = False
        self.say("вопрос 1")
        self.assertEqual(self.sent[-1], "ответ: вопрос 1")
        self.assertEqual(self.con.asked, [])
        self.assertEqual(len(self.runs()), 1)

    def test_console_error_is_reported(self):
        self.con.script = [FakeConsole.ConsoleError("Консоль Codex закрылась, пока он отвечал.")]
        self.say("вопрос")
        self.assertEqual(self.sent[-1], "⚠️ Консоль Codex закрылась, пока он отвечал.")
        self.assertEqual(self.runs(), [])
        self.assertFalse(br.BRIDGE.in_console)

    def test_stop_presses_escape_and_stays_quiet_about_error(self):
        self.con.hold = threading.Event()
        br.BRIDGE.handle_update({"update_id": 1, "message": {"chat": {"id": 100200300}, "text": "долгий вопрос"}})
        self.assertTrue(self.con.started.wait(5))
        for _ in range(100):
            if br.BRIDGE.in_console:
                break
            time.sleep(0.01)
        self.assertTrue(br.BRIDGE.in_console)
        br.BRIDGE.handle_update({"update_id": 2, "message": {"chat": {"id": 100200300}, "text": "/stop"}})
        br.BRIDGE.worker.join(10)
        self.assertEqual(self.con.interrupted, 1)
        self.assertEqual(self.sent, ["Остановил."], "ни «⚠️», ни пустого ответа")
        self.assertFalse(br.BRIDGE.in_console)

    def test_stop_with_nothing_running(self):
        self.say("/stop")
        self.assertIn("ничего не запущено", self.sent[-1])
        self.assertEqual(self.con.interrupted, 0)

    def test_new_forgets_conversation_in_console(self):
        self.say("вопрос")
        self.say("/new")
        self.assertEqual(self.con.forgotten, 1)
        self.assertEqual(br._state()["threads"], {})
        self.assertIn("начат заново", self.sent[-1])

    def test_new_drops_request_in_flight(self):
        self.con.hold = threading.Event()
        br.BRIDGE.handle_update({"update_id": 1, "message": {"chat": {"id": 100200300}, "text": "долгий вопрос"}})
        self.assertTrue(self.con.started.wait(5))
        for _ in range(100):
            if br.BRIDGE.in_console:
                break
            time.sleep(0.01)
        br.BRIDGE.handle_update({"update_id": 2, "message": {"chat": {"id": 100200300}, "text": "/new"}})
        br.BRIDGE.worker.join(10)
        self.assertEqual(self.sent, ["Разговор начат заново."], "ответ на снятый запрос не уходит")

    def test_self_mode_thread_key_follows_workdir(self):
        br.save({"mode": "self", "access": "write", "workdir": self.proj})
        self.say("правь")
        self.assertEqual(br._state()["threads"], {"self|" + self.proj: "TID-CON"})


class LimitAlerts(Base):
    """Предупреждения о лимите и подписке: по одному сообщению на порог."""
    def acc(self, p5=10, p7=5, **kw):
        a = {"slot": "gpt1", "windows": [{"mins": 300, "pct": p5, "resets_at": "2026-10-31T11:47:58Z"},
                                          {"mins": 10080, "pct": p7, "resets_at": "2026-11-07T06:47:58Z"}]}
        a.update(kw)
        return a

    def test_quiet_while_far_from_limit(self):
        self.assertEqual(br.limit_alerts(self.acc(), {})[0], [])

    def test_warn_once_then_exhausted_then_available_again(self):
        msgs, st = br.limit_alerts(self.acc(p5=92), {})
        self.assertEqual(len(msgs), 1)
        self.assertIn("5 ч", msgs[0])
        self.assertIn("92%", msgs[0])
        self.assertEqual(br.limit_alerts(self.acc(p5=95), st)[0], [])  # повторно на том же пороге — тишина
        msgs, st = br.limit_alerts(self.acc(p5=100), st)
        self.assertEqual(len(msgs), 1)
        self.assertIn("исчерпан", msgs[0])
        msgs, st = br.limit_alerts(self.acc(p5=3), st)
        self.assertEqual(len(msgs), 1)
        self.assertIn("снова доступен", msgs[0])
        self.assertEqual(br.limit_alerts(self.acc(p5=3), st)[0], [])

    def test_jump_straight_to_exhausted_is_one_message(self):
        msgs, _ = br.limit_alerts(self.acc(p7=100), {})
        self.assertEqual(len(msgs), 1)
        self.assertIn("неделя", msgs[0])

    def test_hysteresis_no_flapping_around_threshold(self):
        _, st = br.limit_alerts(self.acc(p5=91), {})
        for p in (88, 91, 85, 92):
            self.assertEqual(br.limit_alerts(self.acc(p5=p), st)[0], [], p)
            st = br.limit_alerts(self.acc(p5=p), st)[1]
        _, st = br.limit_alerts(self.acc(p5=10), st)  # реально упало (сброс) — порог взведён заново
        self.assertEqual(len(br.limit_alerts(self.acc(p5=93), st)[0]), 1)

    def test_service_says_reached_before_percent_catches_up(self):
        msgs, _ = br.limit_alerts(self.acc(p5=97, reached="primary"), {})
        self.assertIn("исчерпан", msgs[0])
        msgs, _ = br.limit_alerts(self.acc(usage_allowed=False), {})
        self.assertIn("исчерпан", msgs[0])

    def test_no_data_changes_nothing(self):
        for bad in ({"error": "boom"}, {"stale": True}, {"login_required": True}):
            msgs, st = br.limit_alerts(self.acc(p5=100, **bad), {"w300": 90})
            self.assertEqual((msgs, st), ([], {"w300": 90}))

    def test_subscription_steps(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 31, 10, 0, tzinfo=dt.timezone.utc)
        until = lambda days: (now + dt.timedelta(days=days)).isoformat()
        self.assertEqual(br.limit_alerts(self.acc(sub_until=until(30)), {}, now)[0], [])
        msgs, st = br.limit_alerts(self.acc(sub_until=until(6.5)), {}, now)
        self.assertIn("через 7 дн", msgs[0])
        self.assertEqual(br.limit_alerts(self.acc(sub_until=until(5)), st, now)[0], [])  # тот же шаг — молчим
        msgs, st = br.limit_alerts(self.acc(sub_until=until(2.5)), st, now)
        self.assertIn("через 3 дн", msgs[0])
        msgs, st = br.limit_alerts(self.acc(sub_until=until(-0.2)), st, now)
        self.assertIn("закончилась", msgs[0])
        _, st = br.limit_alerts(self.acc(sub_until=until(30)), st, now)  # продлили
        self.assertNotIn("sub", st)

    def test_lapsed_to_free_one_message_then_back(self):
        a = self.acc(plan="free", lapsed=True, paid_plan="plus")
        msgs, st = br.limit_alerts(a, {})
        self.assertEqual(len(msgs), 1)
        self.assertIn("слетела на Free", msgs[0])
        self.assertIn("Plus", msgs[0])
        self.assertIn("Я продлил", msgs[0])
        self.assertEqual(br.limit_alerts(a, st)[0], [])  # пока Free — тишина
        msgs, st = br.limit_alerts(self.acc(plan="plus", lapsed=False), st)
        self.assertEqual(len(msgs), 1)
        self.assertIn("снова Plus", msgs[0])
        self.assertNotIn("lapsed", st)
        self.assertEqual(br.limit_alerts(self.acc(plan="plus", lapsed=False), st)[0], [])
        msgs, _ = br.limit_alerts(a, st)  # слетел второй раз — снова скажем
        self.assertEqual(len(msgs), 1)

    def test_lapsed_with_stale_sub_date_no_double_message(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 31, 10, 0, tzinfo=dt.timezone.utc)
        a = self.acc(plan="free", lapsed=True, paid_plan="plus", sub_until=(now - dt.timedelta(days=1)).isoformat())
        msgs, st = br.limit_alerts(a, {}, now)
        self.assertEqual(len(msgs), 1)
        self.assertIn("Free", msgs[0])
        self.assertEqual(br.limit_alerts(a, st, now)[0], [])

    def test_always_free_account_is_silent(self):
        self.assertEqual(br.limit_alerts(self.acc(plan="free", lapsed=False), {})[0], [])

    def test_lapsed_no_message_when_data_unreadable(self):
        a = self.acc(plan="free", lapsed=True, paid_plan="plus", error="boom")
        self.assertEqual(br.limit_alerts(a, {}), ([], {}))

    def test_tick_sends_to_telegram_once_and_remembers(self):
        cards = [self.acc(p5=95, sub_until=None)]
        with unittest.mock.patch.object(cc_codex, "get_accounts", lambda b, force=False: cards):
            br.BRIDGE.limits_tick()
            br.BRIDGE.limits_tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Лимит Codex", self.sent[0])
        self.assertEqual(br._state()["limits"]["gpt1"]["w300"], 90)

    def test_tick_other_account_is_not_watched(self):
        s = br.load()
        s["slot"] = "gpt2"
        br._save(s)
        with unittest.mock.patch.object(cc_codex, "get_accounts", lambda b, force=False: [self.acc(p5=99)]):
            br.BRIDGE.limits_tick()
        self.assertEqual(self.sent, [])


class LimitsThread(Base):
    """Пуши о лимите и подписке живут, пока у моста есть токен бота и чат, — в том числе при «Выключен»."""

    def setUp(self):
        super().setUp()
        inner = br.tg_api

        def slow_api(token, method, payload=None, timeout=30):
            if method == "getUpdates":
                time.sleep(0.05)  # настоящий long-poll ждёт; без паузы поток опроса крутился бы вхолостую
            return inner(token, method, payload, timeout)
        br.tg_api = slow_api

    def off(self):
        s = br.load()
        s["enabled"] = False
        br._save(s)
        br.BRIDGE.sync()

    def test_off_keeps_only_limits_thread(self):
        self.off()
        self.assertTrue(br.BRIDGE.lim_t.is_alive())
        self.assertFalse(br.running())  # опрос Telegram и наблюдатель остановлены

    def test_enabled_then_off_does_not_restart_limits_thread(self):
        br.BRIDGE.sync()
        self.assertTrue(br.running())
        lim = br.BRIDGE.lim_t
        self.assertTrue(lim.is_alive())
        self.off()
        self.assertFalse(br.running())
        self.assertTrue(lim.is_alive())
        self.assertIs(br.BRIDGE.lim_t, lim)

    def test_sync_twice_gives_one_thread(self):
        br.BRIDGE.sync()
        lim = br.BRIDGE.lim_t
        br.BRIDGE.sync()
        self.assertIs(br.BRIDGE.lim_t, lim)

    def test_no_token_or_chat_stops_it(self):
        br.BRIDGE.sync()
        lim = br.BRIDGE.lim_t
        s = br.load()
        s["token"] = ""
        br._save(s)
        br.BRIDGE.sync()
        lim.join(5)
        self.assertFalse(lim.is_alive())
        self.assertFalse(br.running())

    def test_tick_sends_when_off(self):
        s = br.load()
        s["enabled"] = False
        br._save(s)
        cards = [{"slot": "gpt1", "windows": [{"mins": 300, "pct": 95, "resets_at": "2026-10-31T11:47:58Z"},
                                              {"mins": 10080, "pct": 10, "resets_at": "2026-11-07T06:47:58Z"}]}]
        with unittest.mock.patch.object(cc_codex, "get_accounts", lambda b, force=False: cards):
            br.BRIDGE.limits_tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Лимит Codex", self.sent[0])


class PollError(Base):
    def test_stale_error_cleared_after_good_poll(self):
        st = br._state()
        st["last_error"] = "Telegram недоступен: TimeoutError"
        br._state_save(st)
        ev = threading.Event()

        def api(token, method, payload=None, timeout=30):
            if method == "getUpdates":
                ev.set()  # один успешный опрос без сообщений, дальше цикл выходит
            return {"ok": True, "result": []}
        br.tg_api = api
        br.BRIDGE.poll_loop(ev)
        self.assertEqual(br._state().get("last_error"), "")

JPG = b"\xff\xd8\xff\xe0" + b"jpeg-body" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body" * 20
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"webp-body" * 10


class ImagesBase(Base):
    """Фото из Telegram → файл в <обмен>/inbox/images, а в запрос к Codex идёт подпись и абсолютный путь (view_image)."""
    TOKEN = "123456:" + "A" * 30

    def setUp(self):
        super().setUp()
        self.api = []  # вызовы getFile
        self.files = {"fid-big": ("photos/big.jpg", JPG), "fid-small": ("photos/small.jpg", JPG[:30]),
                      "fid-png": ("documents/file_1.png", PNG), "fid-webp": ("documents/f.webp", WEBP),
                      "fid-text": ("documents/f.png", "это вообще не картинка".encode())}
        self.downloads = []
        inner = br.tg_api

        def api(token, method, payload=None, timeout=30):
            if method == "getFile":
                self.api.append(payload["file_id"])
                if payload["file_id"] == "fid-gone":
                    raise br.TgError(400, "Bad Request: file is too big")
                if payload["file_id"] == "fid-badpath":
                    return {"ok": True, "result": {"file_path": "../../etc/passwd"}}
                fp = self.files[payload["file_id"]][0]
                return {"ok": True, "result": {"file_id": payload["file_id"], "file_path": fp, "file_size": len(self.files[payload["file_id"]][1])}}
            return inner(token, method, payload, timeout)
        br.tg_api = api

        def download(token, file_path, limit=br.IMG_MAX_BYTES):
            self.downloads.append(file_path)
            for fid, (fp, data) in self.files.items():
                if fp == file_path:
                    if len(data) > limit:
                        raise br.ImageError("Картинка больше 10 МБ, не принимаю.")
                    return data
            raise br.ImageError("Telegram не отдал файл (код 404).")
        br.tg_download = download
        self.addCleanup(setattr, br, "tg_download", self._orig_dl)
        self.images = os.path.join(self.ex, "inbox", "images")

    _orig_dl = br.tg_download

    def photo(self, caption=None, sizes=None, chat=100200300, doc=None):
        m = {"chat": {"id": chat}}
        if doc:
            m["document"] = doc
        else:
            m["photo"] = sizes or [{"file_id": "fid-small", "width": 90, "height": 60, "file_size": 30},
                                   {"file_id": "fid-big", "width": 1280, "height": 960, "file_size": 400}]
        if caption is not None:
            m["caption"] = caption
        br.BRIDGE.handle_update({"update_id": 1, "message": m})
        w = br.BRIDGE.worker
        if w:
            w.join(20)

    def imgs(self):
        return sorted(os.listdir(self.images)) if os.path.isdir(self.images) else []


class Images(ImagesBase):
    def test_photo_with_caption_reaches_exec_with_path(self):
        self.photo("что на скрине?")
        self.assertEqual(self.api, ["fid-big"], "взят самый крупный вариант фото")
        (name,) = self.imgs()
        self.assertRegex(name, r"^img_\d{8}_\d{6}_[0-9a-f]{8}\.jpg$")
        path = os.path.join(self.images, name)
        self.assertEqual(get_bytes(path), JPG)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        prompt = self.runs()[0]["argv"][-1]
        self.assertTrue(prompt.startswith("что на скрине?"))
        self.assertIn("view_image", prompt)
        self.assertIn(path, prompt)
        self.assertTrue(os.path.isabs(path))
        self.assertEqual(self.sent[-1], "ответ: " + prompt)

    def test_photo_without_caption_is_delivered(self):
        self.photo()
        prompt = self.runs()[0]["argv"][-1]
        self.assertIn("без подписи", prompt)
        self.assertIn(os.path.join(self.images, self.imgs()[0]), prompt)

    def test_documents_png_and_webp(self):
        self.photo("док", doc={"file_id": "fid-png", "mime_type": "image/png", "file_name": "../../evil.sh"})
        self.photo("док2", doc={"file_id": "fid-webp", "mime_type": "image/webp"})
        exts = sorted(n.rsplit(".", 1)[1] for n in self.imgs())
        self.assertEqual(exts, ["png", "webp"])
        self.assertNotIn("evil", " ".join(self.imgs()), "присланное имя в путь не попадает")
        self.assertEqual(len(self.runs()), 2)

    def test_non_image_document_refused_without_codex(self):
        self.photo("pdf", doc={"file_id": "fid-big", "mime_type": "application/pdf"})
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.api, [])
        self.assertIn("не принимаю", self.sent[-1])

    def test_fake_image_content_refused(self):
        self.photo("подделка", doc={"file_id": "fid-text", "mime_type": "image/png"})
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.imgs(), [])
        self.assertIn("Это не JPEG", self.sent[-1])

    def test_other_attachment_is_not_silent(self):
        br.BRIDGE.handle_update({"update_id": 1, "message": {"chat": {"id": 100200300}, "voice": {"file_id": "v"}}})
        self.assertIn("картинки", self.sent[-1])
        self.assertEqual(self.runs(), [])

    def test_plain_text_unchanged(self):
        self.say("вопрос")
        self.assertEqual(self.runs()[0]["argv"][-1], "вопрос")
        self.assertEqual(self.api, [])

    def test_too_big_is_reported(self):
        self.photo("огромное", sizes=[{"file_id": "fid-big", "width": 9000, "height": 9000, "file_size": br.IMG_MAX_BYTES + 1}])
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.api, [])
        self.assertIn("не принимаю", self.sent[-1])
        self.photo("большой документ", doc={"file_id": "fid-png", "mime_type": "image/png", "file_size": br.IMG_MAX_BYTES + 1})
        self.assertIn("не принимаю", self.sent[-1])

    def test_download_failures_are_explicit_and_token_free(self):
        self.photo("а", sizes=[{"file_id": "fid-gone", "width": 5, "height": 5}])
        self.assertIn("⚠️", self.sent[-1])
        self.assertIn("too big", self.sent[-1])
        self.photo("б", sizes=[{"file_id": "fid-badpath", "width": 5, "height": 5}])
        self.assertEqual(self.runs(), [])
        self.assertNotIn(self.TOKEN, "\n".join(self.sent))

    def test_real_download_rejects_bad_path_and_hides_token(self):
        real = type(self)._orig_dl
        for bad in ("../x.jpg", "/etc/passwd", "a/../../b.jpg", ""):
            with self.assertRaises(br.ImageError):
                real(self.TOKEN, bad)
        old = br.TG_API
        br.TG_API = "http://127.0.0.1:9"  # порт закрыт
        try:
            with self.assertRaises(br.ImageError) as c:
                real(self.TOKEN, "photos/a.jpg")
        finally:
            br.TG_API = old
        self.assertNotIn("A" * 30, str(c.exception))
        self.assertNotIn("127.0.0.1", str(c.exception))

    def test_foreign_chat_ignored(self):
        self.photo("чужое", chat=111)
        self.assertEqual(self.api, [])
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sent, [])

    def test_yes_caption_does_not_confirm_task(self):
        self.say("оформи задание")
        self.assertIsNotNone(br._state()["pending"])
        self.photo("да")
        self.assertIsNotNone(br._state()["pending"], "задание всё ещё ждёт слова «да»")
        self.assertEqual(self.console, [], "Claude не вызван")
        self.assertTrue(self.runs()[-1]["argv"][-1].startswith("да\n\n"), "подпись ушла в Codex как обычный текст")

    def test_stop_caption_does_not_stop_or_reset(self):
        self.say("первый")
        self.photo("/new")
        self.assertNotIn("Разговор начат заново.", self.sent)
        self.assertEqual(self.runs()[-1]["argv"][:2], ["exec", "resume"], "тот же разговор")
        self.assertTrue(self.runs()[-1]["argv"][-1].startswith("/new"))

    def test_busy_is_reported_not_dropped_silently(self):
        gate = threading.Event()
        br.BRIDGE.worker = threading.Thread(target=gate.wait, args=(10,), daemon=True)
        br.BRIDGE.worker.start()
        try:
            br.BRIDGE.handle_update({"update_id": 1, "message": {"chat": {"id": 100200300}, "photo": [{"file_id": "fid-big", "width": 9, "height": 9}]}})
        finally:
            gate.set()
            br.BRIDGE.worker.join(5)
        self.assertIn("картинку не принял", self.sent[-1])
        self.assertEqual(self.api, [])
        self.assertEqual(self.imgs(), [])

    def test_old_images_pruned_new_kept(self):
        self.photo("1")
        old = os.path.join(self.images, self.imgs()[0])
        keep = os.path.join(self.images, "notes.txt")
        put(keep, "чужой файл не трогаем")
        os.utime(old, (1, 1))
        os.utime(keep, (1, 1))
        br.NOW = lambda: time.time()
        self.photo("2")
        left = self.imgs()
        self.assertEqual(len(left), 2)
        self.assertNotIn(os.path.basename(old), left)
        self.assertIn("notes.txt", left)

    def test_unreadable_for_codex_is_error_and_file_removed(self):
        orig = br._readable_by_codex
        br._readable_by_codex = lambda p: False
        try:
            self.photo("нечитаемо")
        finally:
            br._readable_by_codex = orig
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.imgs(), [])
        self.assertIn("не может её прочитать", self.sent[-1])

    def test_readable_check_runs_as_codex_user(self):
        calls = []
        real_run = br.subprocess.run
        br.subprocess.run = lambda argv, **kw: (calls.append(argv), types.SimpleNamespace(returncode=0))[1]
        old = cc_codex.RUN_AS
        try:
            with unittest.mock.patch.object(cc_codex, "runas_user", return_value="codexuser"), \
                    unittest.mock.patch.object(cc_codex.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_dir="/home/codexuser")):
                self.assertTrue(br._readable_by_codex("/x/y.jpg"))
        finally:
            br.subprocess.run = real_run
            cc_codex.RUN_AS = old
        self.assertEqual(calls[0][:4], ["runuser", "-u", "codexuser", "--"])
        self.assertEqual(calls[0][-2:], ["-r", "/x/y.jpg"])


class Albums(ImagesBase):
    """Альбом Telegram приходит отдельными update с общим media_group_id: все фото уходят в Codex одним сообщением."""

    def setUp(self):
        super().setUp()
        for n in "abc":
            self.files["fid-" + n] = ("photos/%s.jpg" % n, JPG)
        self._wait = br.ALBUM_WAIT
        br.ALBUM_WAIT = 0.15
        self.addCleanup(setattr, br, "ALBUM_WAIT", self._wait)

    def album(self, ids, captions=None, gid="grp1", chat=100200300, wait=True):
        for i, fid in enumerate(ids):
            m = {"chat": {"id": chat}, "media_group_id": gid,
                 "photo": [{"file_id": fid, "width": 100, "height": 100, "file_size": len(self.files[fid][1])}]}
            if captions and captions[i]:
                m["caption"] = captions[i]
            br.BRIDGE.handle_update({"update_id": i, "message": m})
        if wait:
            end = time.time() + 10
            while br.BRIDGE.albums and time.time() < end:
                time.sleep(0.02)
            w = br.BRIDGE.worker
            if w:
                w.join(20)

    def test_album_goes_to_codex_as_one_message(self):
        self.album(["fid-a", "fid-b", "fid-c"], ["подпись к альбому", None, None], wait=False)
        self.assertEqual(self.api, [], "пока ждём остальные фото, ничего не качаем и Codex не зовём")
        self.assertEqual(self.runs(), [])
        self.album([], wait=True)
        self.assertEqual(self.api, ["fid-a", "fid-b", "fid-c"], "порядок фото сохранён")
        self.assertEqual(len(self.runs()), 1, "один запрос к Codex на весь альбом")
        names = self.imgs()
        self.assertEqual(len(names), 3)
        prompt = self.runs()[0]["argv"][-1]
        self.assertTrue(prompt.startswith("подпись к альбому"))
        paths = [os.path.join(self.images, n) for n in names]
        for p in paths:
            self.assertIn(p, prompt)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("не принял", self.sent[0])

    def test_album_caption_on_last_photo_is_used(self):
        self.album(["fid-a", "fid-b"], [None, "что тут?"])
        self.assertTrue(self.runs()[0]["argv"][-1].startswith("что тут?"))

    def test_album_without_caption_says_how_many(self):
        self.album(["fid-a", "fid-b", "fid-c"])
        self.assertIn("изображения (3 шт.) без подписи", self.runs()[0]["argv"][-1])

    def test_album_with_unacceptable_photo_is_refused_whole(self):
        self.album(["fid-a", "fid-text", "fid-c"], ["тест", None, None])
        self.assertEqual(self.runs(), [], "Codex не отвечает по части альбома")
        self.assertEqual(self.imgs(), [], "уже сохранённые фото убраны")
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0].startswith("⚠️ Фото 2 из 3:"), self.sent[0])
        self.assertNotIn(self.TOKEN, self.sent[0])

    def test_album_while_busy_is_reported_once(self):
        gate = threading.Event()
        br.BRIDGE.worker = threading.Thread(target=gate.wait, args=(10,), daemon=True)
        br.BRIDGE.worker.start()
        try:
            self.album(["fid-a", "fid-b"], wait=False)
            end = time.time() + 10
            while br.BRIDGE.albums and time.time() < end:
                time.sleep(0.02)
        finally:
            gate.set()
            br.BRIDGE.worker.join(5)
        self.assertEqual(len(self.sent), 1, "одно сообщение на весь альбом, а не по числу фото")
        self.assertIn("картинки не принял", self.sent[0])
        self.assertEqual(self.api, [])
        self.assertEqual(self.imgs(), [])

    def test_two_albums_do_not_mix(self):
        self.album(["fid-a"], gid="g1", wait=False)
        self.album(["fid-b", "fid-c"], gid="g2", wait=False)
        self.assertEqual(sorted(br.BRIDGE.albums), ["g1", "g2"])
        end = time.time() + 10
        while br.BRIDGE.albums and time.time() < end:
            time.sleep(0.02)
        w = br.BRIDGE.worker
        if w:
            w.join(20)
        # второй альбом пришёл, пока Codex занят первым → ему сказано прислать снова, а не склеено с первым
        self.assertEqual(len(self.runs()), 1)
        n = len(self.imgs())  # какой из альбомов успел первым, неважно: в запрос идёт ровно он
        self.assertIn(n, (1, 2))
        self.assertEqual(self.runs()[0]["argv"][-1].count("img_"), n)
        self.assertTrue(any("не принял" in m for m in self.sent), self.sent)

    def test_album_from_foreign_chat_ignored(self):
        self.album(["fid-a", "fid-b"], chat=555)
        self.assertEqual(self.api, [])
        self.assertEqual(self.runs(), [])
        self.assertEqual(br.BRIDGE.albums, {})

    def test_yes_caption_in_album_does_not_confirm_task(self):
        self.say("оформи задание")
        self.assertIsNotNone(br._state()["pending"])
        self.album(["fid-a", "fid-b"], ["да", None])
        self.assertIsNotNone(br._state()["pending"], "задание всё ещё ждёт слова «да»")
        self.assertEqual(self.console, [], "Claude не вызван")

    def test_single_photo_without_group_is_not_delayed(self):
        t = time.time()
        br.ALBUM_WAIT = 30
        self.photo("одиночное")
        self.assertLess(time.time() - t, 10)
        self.assertEqual(len(self.runs()), 1)


class ImagesConsole(ImagesBase):
    """Тот же путь через живую консоль: в неё уходит та же строка с подписью и абсолютным путём."""

    def setUp(self):
        super().setUp()
        self.con = FakeConsole()
        br.CONSOLE = self.con

    def test_photo_goes_to_console_not_exec(self):
        self.photo("что тут?")
        self.assertEqual(self.runs(), [])
        (prompt,) = self.con.asked
        self.assertTrue(prompt.startswith("что тут?"))
        self.assertIn(os.path.join(self.images, self.imgs()[0]), prompt)
        self.assertEqual(self.sent[-1], "ответ из консоли")

    def test_caption_with_slash_is_made_safe_for_console(self):
        import cc_codex_console as cc
        self.photo("/status")
        (prompt,) = self.con.asked
        self.assertTrue(cc._paste_text(prompt).startswith("» /status"), "консоль не примет подпись за свою команду")



if __name__ == "__main__":
    unittest.main()
