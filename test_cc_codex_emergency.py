# Аварийный режим Codex: включение словом, права на время, откат при сбое, снятие по сроку и после перезапуска.
# Системные команды (mount, setfacl, visudo, find, getfacl) подменены записью вызовов — реальная система не трогается.
# python3 -m unittest test_cc_codex_emergency -v
import json, os, shutil, subprocess, sys, tempfile, types, unittest, unittest.mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_codex, cc_codex_bridge as br, cc_codex_emergency as em

USER = "codexu"


def put(path, text="", mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        f.write(text)


def get(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        j = self.j = lambda *p: os.path.join(self.tmp, *p)
        self.saved = (br.BASE, cc_codex.PROFILES, br.CONSOLE, br.EMERGENCY, cc_codex.EXTRA_ENV, em.BASE, em.CONFIG,
                      em.NOTIFY, em.NOW, em.RUN, em.SUDOERS, em.MOUNTINFO, em.PROC)
        br.BASE = em.BASE = j("base")
        os.makedirs(br.BASE)
        cc_codex.PROFILES = j("profiles")
        put(j("profiles", "gpt1", "auth.json"), "{}")
        br.CONSOLE = None
        br.EMERGENCY = em
        self.home = j("home")
        os.makedirs(self.home)
        self.proj = j("proj")
        put(j("proj", "app.py"), "print(1)\n")
        put(j("secrets", "env.txt"), "TOKEN=abc\n")
        put(j("keys", "id_prod"), "KEYDATA\n")
        self.cfg = {"project": self.proj, "services": ["svc-web", "svc-hub.service"], "files": [j("secrets", "env.txt")],
                    "ssh_key": j("keys", "id_prod"), "hours": 24}
        em.CONFIG = lambda: self.cfg
        self.sent = []
        em.NOTIFY = self.sent.append
        self.now = [1000.0]
        em.NOW = lambda: self.now[0]
        em.SUDOERS = j("sudoers_cc-codex-emergency")
        em.MOUNTINFO = j("mountinfo")
        put(em.MOUNTINFO, "")
        em.PROC = j("proc")
        os.makedirs(em.PROC)
        self.mounts = set()
        self.calls = []
        self.facl = ""  # что печатает getfacl
        self.fail = {}  # имя команды → код возврата
        em.RUN = self.fake_run
        cc_codex.EXTRA_ENV = em.env_extra
        pw = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=self.home)
        for pt in (unittest.mock.patch("pwd.getpwnam", lambda n: pw),
                   unittest.mock.patch.object(cc_codex, "runas_user", lambda: USER)):
            pt.start()
            self.addCleanup(pt.stop)
        self.addCleanup(self.restore)

    def restore(self):
        (br.BASE, cc_codex.PROFILES, br.CONSOLE, br.EMERGENCY, cc_codex.EXTRA_ENV, em.BASE, em.CONFIG,
         em.NOTIFY, em.NOW, em.RUN, em.SUDOERS, em.MOUNTINFO, em.PROC) = self.saved
        br.BRIDGE.stop()

    def fake_run(self, argv, timeout=60):
        self.calls.append(list(argv))
        name = os.path.basename(argv[0])
        out = ""
        if name == "mount":
            self.mounts.add(argv[-1])
            put(em.MOUNTINFO, "".join(f"1 1 0:1 / {m} rw - ext4 x rw\n" for m in sorted(self.mounts)))
        elif name == "umount":
            self.mounts.discard(argv[-1])
            put(em.MOUNTINFO, "".join(f"1 1 0:1 / {m} rw - ext4 x rw\n" for m in sorted(self.mounts)))
        elif name == "getfacl":
            out = self.facl
        elif name == "visudo":
            if self.fail.get("visudo", 0) == 0:
                pass
        rc = self.fail.get(name, 0)
        return subprocess.CompletedProcess(argv, rc, out, "ошибка " + name if rc else "")

    def names(self):
        return [os.path.basename(c[0]) for c in self.calls]

    def agents(self):
        return os.path.join(cc_codex.PROFILES, "gpt1", "AGENTS.md")


class Enable(Base):
    def test_wrong_word_changes_nothing(self):
        ok, msg = em.on("пожалуйста")
        self.assertFalse(ok)
        self.assertFalse(em.active())
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(em.SUDOERS))

    def test_not_configured(self):
        self.cfg = {}
        ok, msg = em.on("аварийный")
        self.assertFalse(ok)
        self.assertIn("не настроен", msg)
        self.assertEqual(self.calls, [])

    def test_forbidden_or_secret_project_refused(self):
        for bad in ("/root", "/", br.BASE, os.path.dirname(br.BASE)):
            self.cfg["project"] = bad
            ok, msg = em.on("аварийный")
            self.assertFalse(ok, bad)
        self.assertEqual(self.calls, [])

    def test_bad_service_name_refused(self):
        for bad in ("svc-x; rm -rf /", "a b", "../x", ""):
            self.cfg["services"] = [bad]
            ok, msg = em.on("аварийный")
            self.assertFalse(ok, bad)
        self.assertEqual(self.calls, [])

    def test_missing_file_or_key_refused(self):
        self.cfg["files"] = [self.j("nope.txt")]
        self.assertFalse(em.on("аварийный")[0])
        self.cfg["files"] = []
        self.cfg["ssh_key"] = self.j("nokey")
        self.assertFalse(em.on("аварийный")[0])
        self.assertEqual(self.calls, [])

    def test_existing_acl_in_project_refused(self):
        self.facl = "# file: proj/app.py\nuser:other:rw-\n"
        ok, msg = em.on("аварийный")
        self.assertFalse(ok)
        self.assertIn("ACL", msg)
        self.assertNotIn("mount", self.names())
        self.assertFalse(em.active())

    def test_on_gives_everything_and_switches_bridge(self):
        before = br.load()
        ok, msg = em.on("Аварийный")
        self.assertTrue(ok, msg)
        self.assertTrue(em.active())
        p = em._plan()[0]
        # проект подключён в папку Codex и открыт ему по ACL
        self.assertIn(["mount", "--bind", os.path.realpath(self.proj), p["mnt"]], self.calls)
        self.assertTrue(any(c[0] == "setfacl" and f"u:{USER}:rwX" in c and c[-1] == os.path.realpath(self.proj) for c in self.calls))
        # sudo — только перезапуск перечисленных юнитов
        sd = get(em.SUDOERS)
        self.assertIn(f"{USER} ALL=(root) NOPASSWD:", sd)
        self.assertEqual(oct(os.stat(em.SUDOERS).st_mode & 0o777), "0o440")
        cmds = sd.split("NOPASSWD:")[1].strip().split(", ")
        self.assertEqual(sorted(c.split()[-1] for c in cmds), sorted(["svc-web.service", "svc-web", "svc-hub.service", "svc-hub"]))
        self.assertTrue(all(c.split()[1] == "restart" for c in cmds))
        # копии доступов и ключ — только владельцу
        f1 = os.path.join(p["edir"], "files", "env.txt")
        k1 = os.path.join(p["edir"], "ssh", "id_prod")
        self.assertEqual(get(f1), "TOKEN=abc\n")
        self.assertEqual(oct(os.stat(f1).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(k1).st_mode & 0o777), "0o600")
        # git и AGENTS.md
        self.assertIn(f"directory = {p['mnt']}", get(p["gitconfig"]))
        self.assertEqual(em.env_extra(), {"GIT_CONFIG_GLOBAL": p["gitconfig"]})
        self.assertTrue(get(self.agents()).startswith(em.MARK))
        self.assertIn("svc-web.service", get(self.agents()))
        # на другом сервере — от пользователя приложения, не от root, с возвратом владельца
        self.assertIn("sudo -u <пользователь>", get(self.agents()))
        self.assertIn("chown <пользователь>", get(self.agents()))
        # мост: самостоятельно + полный доступ в проекте режима; прежнее запомнено
        s = br.load()
        self.assertEqual((s["mode"], s["access"], s["workdir"]), ("self", "full", p["mnt"]))
        self.assertEqual(br.plan(s), ("danger-full-access", p["mnt"]))
        self.assertEqual(em._st()["prev"]["mode"], before["mode"])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("ВКЛЮЧЁН", self.sent[0])
        self.assertIsNone(em.until())

    def test_second_on_refused(self):
        self.assertTrue(em.on("аварийный")[0])
        n = len(self.calls)
        ok, msg = em.on("аварийный")
        self.assertFalse(ok)
        self.assertIn("уже", msg)
        self.assertEqual(len(self.calls), n)

    def test_failure_rolls_everything_back(self):
        self.fail["setfacl"] = 1
        before = br.load()
        ok, msg = em.on("аварийный")
        self.assertFalse(ok)
        self.assertFalse(em.active())
        self.assertFalse(os.path.exists(em.SUDOERS))
        self.assertEqual(self.mounts, set())
        s = br.load()
        self.assertEqual((s["mode"], s["access"], s["workdir"]), (before["mode"], before["access"], before["workdir"]))
        self.assertIn("ошибка включения", em._st()["last"]["why"])
        self.assertFalse(os.path.exists(self.agents()))

    def test_bad_sudoers_is_not_installed(self):
        self.fail["visudo"] = 1
        ok, msg = em.on("аварийный")
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(em.SUDOERS))
        self.assertFalse(os.path.exists(em.SUDOERS + ".tmp"))

    def test_foreign_agents_md_is_kept(self):
        put(self.agents(), "# мои правила\n")
        self.assertTrue(em.on("аварийный")[0])
        self.assertEqual(get(self.agents()), "# мои правила\n")
        self.assertTrue(em.off("тест")[0])
        self.assertEqual(get(self.agents()), "# мои правила\n")

    def test_bridge_save_frozen_while_active(self):
        self.assertTrue(em.on("аварийный")[0])
        ok, msg = br.save({"mode": "mediator", "access": "read"})
        self.assertFalse(ok)
        self.assertIn("аварийный", msg.lower())
        self.assertEqual(br.load()["mode"], "self")
        ok, msg = br.save({"chat_id": "123456"})  # то, что режим не затрагивает, меняется
        self.assertTrue(ok, msg)

    def test_status_line_and_public(self):
        self.assertEqual(em.status_line(), "")
        pub = em.public()
        self.assertTrue(pub["configured"])
        self.assertFalse(pub["active"])
        self.assertEqual(pub["services"], ["svc-web.service", "svc-hub.service"])
        self.assertEqual((pub["files"], pub["ssh"], pub["hours"]), (1, True, 0))
        self.assertTrue(em.on("аварийный")[0])
        self.assertIn("АВАРИЙНЫЙ", em.status_line())
        pub = em.public()
        self.assertTrue(pub["active"])
        dump = json.dumps(pub, ensure_ascii=False)
        for secret in (self.proj, "KEYDATA", "TOKEN=abc", self.home, self.j("secrets"), self.j("keys")):
            self.assertNotIn(secret, dump)
        self.assertTrue(any("включение" in ln for ln in pub["journal"]))

    def test_journal_of_active_mode_starts_at_current_turn_on(self):
        self.assertTrue(em.on("аварийный")[0])
        self.assertTrue(em.off("первый раз")[0])
        self.assertTrue(em.on("аварийный")[0])
        jr = em.public()["journal"]
        self.assertEqual(len([ln for ln in jr if " включение:" in ln]), 1)
        self.assertFalse(any("выключен" in ln for ln in jr))
        em.off("второй раз")
        self.assertTrue(any("выключен" in ln for ln in em.public()["journal"]))  # у выключенного режима — общий хвост журнала


class AutoOn(Base):
    """Включение резервом (лимиты Claude кончились): слово не нужно, отдельного сообщения нет — одно общее шлёт резерв."""
    def test_auto_on_needs_no_word_and_sends_no_own_message(self):
        ok, msg = em.on("", auto="лимиты Claude кончились")
        self.assertTrue(ok, msg)
        self.assertTrue(em.active())
        self.assertEqual(self.sent, [])
        self.assertEqual(em._st()["auto"], "лимиты Claude кончились")
        self.assertTrue(em.public()["auto"])
        self.assertTrue(any("само: лимиты Claude кончились" in ln for ln in em.public()["journal"]))
        s = br.load()
        self.assertEqual((s["mode"], s["access"]), ("self", "full"))  # права те же, что при включении словом

    def test_manual_on_still_needs_word_and_has_no_auto_flag(self):
        self.assertFalse(em.on("")[0])
        self.assertFalse(em.on("", auto="")[0])
        self.assertFalse(em.active())
        self.assertTrue(em.on("аварийный")[0])
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("auto", em._st())
        self.assertFalse(em.public()["auto"])

    def test_auto_on_has_the_same_checks_as_manual(self):
        self.cfg = {}
        ok, msg = em.on("", auto="x")
        self.assertFalse(ok)
        self.assertIn("не настроен", msg)
        self.assertFalse(em.active())

    def test_quiet_off_removes_everything_without_own_message(self):
        self.assertTrue(em.on("", auto="x")[0])
        ok, msg = em.off("лимиты снова есть", quiet=True)
        self.assertTrue(ok, msg)
        self.assertFalse(em.active())
        self.assertFalse(os.path.exists(em.SUDOERS))
        self.assertEqual(self.sent, [])

    def test_quiet_off_still_reports_what_stayed(self):
        self.assertTrue(em.on("", auto="x")[0])
        real = em._teardown
        em._teardown = lambda *a, **k: ["остался mount"]
        try:
            ok, msg = em.off("лимиты снова есть", quiet=True)
        finally:
            em._teardown = real
        self.assertFalse(ok)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("остался mount", self.sent[0])


class Disable(Base):
    def setUp(self):
        super().setUp()
        self.assertTrue(em.on("аварийный")[0])
        self.p = em._plan()[0]
        self.sent.clear()
        self.calls.clear()

    def test_off_removes_everything(self):
        ok, msg = em.off("кнопка")
        self.assertTrue(ok, msg)
        self.assertFalse(em.active())
        self.assertFalse(os.path.exists(em.SUDOERS))
        self.assertFalse(os.path.exists(os.path.join(self.p["edir"], "files", "env.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.p["edir"], "ssh", "id_prod")))
        self.assertFalse(os.path.exists(self.p["gitconfig"]))
        self.assertFalse(os.path.exists(self.agents()))
        self.assertEqual(self.mounts, set())
        self.assertFalse(os.path.exists(self.p["edir"]))
        self.assertEqual(em.env_extra(), {})
        # настройки моста вернулись
        s = br.load()
        self.assertNotEqual(s["workdir"], self.p["mnt"])
        self.assertEqual(s["mode"], em._st().get("prev", {"mode": s["mode"]})["mode"])
        # владельцы вернулись, ACL сняты и проверены
        self.assertTrue(any(c[0] == "find" and "-user" in c and USER in c and "chown" in c for c in self.calls))
        self.assertTrue(any(c[0] == "setfacl" and "-b" in c and c[-1] == os.path.realpath(self.proj) for c in self.calls))
        self.assertTrue(any(c[0] == "getfacl" for c in self.calls))
        self.assertIn("выключен", self.sent[0].lower())
        self.assertNotIn("не всё", self.sent[0])

    def test_off_restores_previous_settings(self):
        # до включения стоял оркестратор — он и возвращается
        em.off("тест")
        s = br.load()
        s.update(mode="orchestrator", access="read", workdir="", project="", profile="orchestrator")
        br._save(s)
        self.assertTrue(em.on("аварийный")[0])
        self.assertEqual(br.load()["mode"], "self")
        self.assertTrue(em.off("тест")[0])
        s = br.load()
        self.assertEqual((s["mode"], s["profile"]), ("orchestrator", "orchestrator"))

    def test_off_reports_what_stayed(self):
        self.fail["find"] = 1
        ok, msg = em.off("кнопка")
        self.assertFalse(ok)
        self.assertIn("не всё снято", self.sent[0])
        self.assertIn("владельцы", self.sent[0])
        self.assertFalse(em.active())  # всё остальное снято, режим не висит
        self.assertFalse(os.path.exists(em.SUDOERS))
        self.assertTrue(em._st()["last"]["problems"])

    def test_acl_left_over_is_reported(self):
        self.facl = f"# file: x\nuser::rw-\nmask::r--\n"
        ok, msg = em.off("кнопка")
        self.assertFalse(ok)
        self.assertIn("ACL", self.sent[0])

    def test_off_when_not_active_is_harmless(self):
        em.off("кнопка")
        self.calls.clear()
        ok, msg = em.off("кнопка")
        self.assertTrue(ok)
        self.assertEqual(self.calls, [])

    def test_off_kills_codex_processes_in_project(self):
        # процесс пользователя Codex с текущей папкой в проекте режима останавливается; чужие не трогаются
        procs = {"101": self.p["mnt"] + "/sub", "102": "/tmp", "103": self.p["edir"]}
        for pid, cwd in procs.items():
            os.makedirs(os.path.join(em.PROC, pid))
            os.symlink(cwd, os.path.join(em.PROC, pid, "cwd"))
        killed = []
        with unittest.mock.patch.object(em.os, "kill", lambda pid, sig: killed.append((pid, sig))), \
                unittest.mock.patch.object(em.time, "sleep", lambda s: None):
            em.off("кнопка")
        self.assertEqual(sorted({pid for pid, _ in killed}), [101, 103])


class Timer(Base):
    def setUp(self):
        super().setUp()
        self.assertTrue(em.on("аварийный")[0])
        self.sent.clear()

    def test_tick_before_deadline_does_nothing(self):
        self.now[0] += 3600
        em.tick()
        self.assertTrue(em.active())
        self.assertEqual(self.sent, [])

    def test_old_deadline_is_removed_without_warning_or_revocation(self):
        state=em._st();state['until']=1;state['plan']['hours']=24;em._st_save(state)
        self.now[0]+=25*3600;em.tick();em.reconcile();self.assertTrue(em.active());self.assertIsNone(em.until());self.assertEqual(self.sent,[])

    def test_reconcile_after_reboot_restores_access(self):
        # после перезагрузки mount пропал, а режим ещё не истёк — доступы возвращаются
        self.mounts.clear()
        put(em.MOUNTINFO, "")
        os.unlink(em.SUDOERS)
        self.calls.clear()
        em.reconcile()
        self.assertTrue(em.active())
        self.assertIn("mount", self.names())
        self.assertTrue(os.path.exists(em.SUDOERS))

    def test_reconcile_failure_switches_off(self):
        self.mounts.clear()
        put(em.MOUNTINFO, "")
        self.fail["mount"] = 32
        em.reconcile()
        self.assertFalse(em.active())
        self.assertFalse(os.path.exists(em.SUDOERS))

    def test_reconcile_cleans_stray_traces(self):
        em.off("тест")
        put(em.SUDOERS, "левое правило\n")
        em.reconcile()
        self.assertFalse(os.path.exists(em.SUDOERS))


class NoLimit(Base):
    """«hours»: 0 — режим без срока: сам не выключается и не напоминает, снимается только вручную."""

    def test_legacy_hours_cannot_reintroduce_deadline(self):
        for raw in (0,'0',None,'abc',-5,100,6,2):
            self.cfg['hours']=raw;self.assertEqual(em._plan()[0]['hours'],0)
        del self.cfg['hours'];self.assertEqual(em._plan()[0]['hours'],0)

    def test_on_without_deadline(self):
        self.cfg["hours"] = 0
        self.assertTrue(em.on("аварийный")[0])
        self.assertTrue(em.active())
        self.assertIsNone(em.until())
        self.assertIsNone(em._st()["until"])
        self.assertIn("без срока", em.status_line())
        self.assertNotIn(" до ", em.status_line())
        self.assertIn("без срока", self.sent[0])
        self.assertIn("ВКЛЮЧЁН", self.sent[0])
        self.assertIn("/emergency_off", self.sent[0])
        self.assertIn("без срока", get(em.SUDOERS).splitlines()[0])
        self.assertIn("без срока", get(self.agents()))
        self.assertNotIn("действует до", get(self.agents()))
        pub = em.public()
        self.assertTrue(pub["active"])
        self.assertEqual(pub["hours"], 0)
        self.assertIsNone(pub["until"])
        self.assertEqual(pub["since"], 1000.0)
        self.assertIn("без срока", " ".join(pub["journal"]))

    def test_tick_and_reconcile_never_switch_off_by_time(self):
        self.cfg["hours"] = 0
        self.assertTrue(em.on("аварийный")[0])
        self.sent.clear()
        self.now[0] += 1000 * 3600
        em.tick()
        self.assertTrue(em.active())
        self.assertEqual(self.sent, [])            # ни «осталось меньше часа», ни выключения
        em.reconcile()
        self.assertTrue(em.active())
        self.assertTrue(os.path.exists(em.SUDOERS))

    def test_manual_off_still_removes_everything(self):
        self.cfg["hours"] = 0
        self.assertTrue(em.on("аварийный")[0])
        self.assertTrue(em.off("кнопка")[0])
        self.assertFalse(em.active())
        self.assertFalse(os.path.exists(em.SUDOERS))
        self.assertEqual(em._st()["last"]["why"], "кнопка")


class Wrap(unittest.TestCase):
    def test_extra_env_is_merged_and_explicit_wins(self):
        saved = cc_codex.EXTRA_ENV
        self.addCleanup(setattr, cc_codex, "EXTRA_ENV", saved)
        cc_codex.EXTRA_ENV = lambda: {"GIT_CONFIG_GLOBAL": "/x/gitconfig", "A": "1"}
        with unittest.mock.patch.object(cc_codex, "runas_user", lambda: None):
            argv, env = cc_codex.wrap(["codex"], "/h", {"A": "2"})
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/x/gitconfig")
        self.assertEqual(env["A"], "2")
        self.assertEqual(env["CODEX_HOME"], "/h")

    def test_extra_env_goes_into_clean_env_of_other_user(self):
        saved = cc_codex.EXTRA_ENV
        self.addCleanup(setattr, cc_codex, "EXTRA_ENV", saved)
        cc_codex.EXTRA_ENV = lambda: {"GIT_CONFIG_GLOBAL": "/x/gitconfig"}
        pw = types.SimpleNamespace(pw_uid=1, pw_gid=1, pw_dir="/home/u")
        with unittest.mock.patch.object(cc_codex, "runas_user", lambda: "u"), unittest.mock.patch("pwd.getpwnam", lambda n: pw):
            argv, env = cc_codex.wrap(["codex"], "/h")
        self.assertIn("GIT_CONFIG_GLOBAL=/x/gitconfig", argv)
        self.assertNotIn("GIT_CONFIG_GLOBAL", env)  # на панель переменная не действует, только на запуск codex

    def test_default_hook_adds_nothing(self):
        saved = cc_codex.EXTRA_ENV
        self.addCleanup(setattr, cc_codex, "EXTRA_ENV", saved)
        cc_codex.EXTRA_ENV = lambda: {}
        with unittest.mock.patch.object(cc_codex, "runas_user", lambda: None):
            argv, env = cc_codex.wrap(["codex"], "/h")
        self.assertNotIn("GIT_CONFIG_GLOBAL", env)


if __name__ == "__main__":
    unittest.main()
