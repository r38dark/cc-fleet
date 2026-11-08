# Копии профилей аккаунтов (cc_backup) и их окно в ⚙: python3 -m unittest test_cc_backup -v
# Все пути — во временную папку ДО импорта cc_limits (иначе общий прогон заденет живые профили).
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

TMP0 = tempfile.mkdtemp(prefix="ccbk0_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP0, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP0, "profiles")
os.environ["CC_CODEX_PROFILES"] = os.path.join(TMP0, "cxprof")
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cc_backup as B  # noqa: E402
import cc_limits as L  # noqa: E402

# защита: тест не должен видеть живые папки ни при каком порядке импорта
assert L.PROFILES.startswith(tempfile.gettempdir()) and L.BASE.startswith(tempfile.gettempdir()), (L.PROFILES, L.BASE)

def put(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def get(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


T0 = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ccbk_")
        self.prof = os.path.join(self.d, "profiles")
        self.dest = os.path.join(self.d, "backups")
        os.makedirs(self.prof)
        B._st.update({"sig": None, "covered": None, "err": ""})

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def acc(self, name, uuid=None, token="t1", real=True):
        """Профиль на диске: настоящий (с accountUuid и токенами) или пустой слот установщика."""
        p = os.path.join(self.prof, name)
        os.makedirs(p, exist_ok=True)
        if real:
            uuid = uuid or "u-" + name
            put(p + "/oauth_account.json", {"accountUuid": uuid, "emailAddress": name + "@x.io"})
            put(p + "/credentials.json", {"claudeAiOauth": {"accessToken": token}})
        else:
            put(p + "/oauth_account.json", {})
        return p

    def names_in(self, path):
        return sorted(B.archive_names(path))


class Make(Base):
    def test_dated_copy_and_latest_are_private_and_hold_only_profiles(self):
        self.acc("acc1")
        self.acc("acc2", token="t2")
        r = B.make(self.prof, self.dest, now=T0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["profiles"], 2)
        self.assertRegex(r["name"], r"^profiles_20261101_120000_n2\.tar\.gz$")
        self.assertEqual(stat.S_IMODE(os.stat(self.dest).st_mode), 0o700)
        for f in (r["name"], B.LATEST):
            path = os.path.join(self.dest, f)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600, f)
            self.assertEqual(self.names_in(path), ["acc1", "acc2"])
            with tarfile.open(path) as tf:
                self.assertEqual(sorted(m.name for m in tf), sorted(f"{n}/{x}" for n in ("acc1", "acc2") for x in B.FILES))
        self.assertEqual([x for x in os.listdir(self.dest) if x.endswith(".part")], [])

    def test_empty_slot_is_not_a_profile(self):
        self.acc("acc1", real=False)
        self.assertEqual(B.real_names(self.prof), [])
        r = B.make(self.prof, self.dest, now=T0)
        self.assertEqual((r["ok"], r["why"]), (False, "empty"))
        self.assertFalse(os.path.exists(self.dest))

    def test_nothing_real_never_touches_old_copies(self):
        self.acc("acc1")
        B.make(self.prof, self.dest, now=T0)
        shutil.rmtree(self.prof)
        os.makedirs(self.prof)
        self.acc("acc1", real=False)
        self.assertFalse(B.make(self.prof, self.dest, now=T0 + 10)["ok"])
        self.assertIsNone(B.tick(self.prof, self.dest, True, now=T0 + 5 * 86400))
        self.assertEqual(len(B._dated(self.dest)), 1)
        self.assertEqual(self.names_in(os.path.join(self.dest, B.LATEST)), ["acc1"])

    def test_rotation_keeps_newest_only_after_new_copy_is_written(self):
        self.acc("acc1")
        for i in range(B.KEEP + 3):
            self.assertTrue(B.make(self.prof, self.dest, now=T0 + i)["ok"])
        got = B._dated(self.dest)
        self.assertEqual(len(got), B.KEEP)
        self.assertEqual(got[0][0], T0 + B.KEEP + 2)  # самая свежая на месте
        self.assertEqual(got[-1][0], T0 + 3)  # три самые старые стёрты

    def test_files_outside_profile_are_not_copied(self):
        p = self.acc("acc1")
        with open(p + "/secret_note.txt", "w") as f:
            f.write("x")
        r = B.make(self.prof, self.dest, now=T0)
        with tarfile.open(os.path.join(self.dest, r["name"])) as tf:
            self.assertEqual(sorted(m.name for m in tf), ["acc1/credentials.json", "acc1/oauth_account.json"])


class Tick(Base):
    def test_daily_event_and_latest_schedule(self):
        self.acc("acc1")
        self.assertEqual(B.tick(self.prof, self.dest, True, now=T0), "daily")  # первая копия
        self.assertIsNone(B.tick(self.prof, self.dest, True, now=T0 + 60))  # ничего не изменилось
        # Claude обновил токен: датированной копии нет, «свежая» обновилась
        self.acc("acc1", token="NEW")
        self.assertEqual(B.tick(self.prof, self.dest, True, now=T0 + 120), "latest")
        with tarfile.open(os.path.join(self.dest, B.LATEST)) as tf:
            self.assertIn(b"NEW", tf.extractfile("acc1/credentials.json").read())
        self.assertEqual(len(B._dated(self.dest)), 1)
        # новый вход, час ещё не прошёл: датированной нет, но «свежая» уже со вторым аккаунтом
        self.acc("acc2")
        self.assertEqual(B.tick(self.prof, self.dest, True, now=T0 + 600), "latest")
        self.assertEqual(self.names_in(os.path.join(self.dest, B.LATEST)), ["acc1", "acc2"])
        self.assertEqual(len(B._dated(self.dest)), 1)
        # час прошёл — внеочередная датированная копия по событию
        self.assertEqual(B.tick(self.prof, self.dest, True, now=T0 + B.EVENT_GAP + 5), "event")
        self.assertEqual(len(B._dated(self.dest)), 2)
        self.assertIsNone(B.tick(self.prof, self.dest, True, now=T0 + B.EVENT_GAP + 65))
        # сутки без событий — плановая
        self.assertEqual(B.tick(self.prof, self.dest, True, now=T0 + B.EVENT_GAP + B.DAY + 10), "daily")

    def test_disabled_and_restart_do_not_duplicate(self):
        self.acc("acc1")
        self.assertIsNone(B.tick(self.prof, self.dest, False, now=T0))
        self.assertFalse(os.path.exists(self.dest))
        B.tick(self.prof, self.dest, True, now=T0)
        B._st.update({"sig": None, "covered": None})  # как после перезапуска службы
        self.assertEqual(B.tick(self.prof, self.dest, True, now=T0 + 60), "latest")  # токены заново сверены, датированная не дублируется
        self.assertEqual(len(B._dated(self.dest)), 1)


class Restore(Base):
    def wipe(self):
        shutil.rmtree(self.prof)
        os.makedirs(self.prof)

    def test_missing_profiles_come_back_from_latest_and_live_ones_stay(self):
        self.acc("acc1", token="old1")
        self.acc("acc2", token="old2")
        B.make(self.prof, self.dest, now=T0)
        self.acc("acc1", token="NEWER")  # живой аккаунт обновил токен после копии
        shutil.rmtree(os.path.join(self.prof, "acc2"))
        self.assertEqual(B.missing(self.prof, self.dest), ["acc2"])
        r = B.restore_missing(self.prof, self.dest)
        self.assertEqual(r["restored"], ["acc2"])
        self.assertEqual(get(self.prof + "/acc1/credentials.json")["claudeAiOauth"]["accessToken"], "NEWER")
        self.assertEqual(get(self.prof + "/acc2/credentials.json")["claudeAiOauth"]["accessToken"], "old2")
        for f in B.FILES:
            self.assertEqual(stat.S_IMODE(os.stat(f"{self.prof}/acc2/{f}").st_mode), 0o600)
        self.assertEqual(B.missing(self.prof, self.dest), [])
        self.assertEqual(B.restore_missing(self.prof, self.dest)["restored"], [])

    def test_empty_slot_is_filled_and_total_wipe_is_recoverable(self):
        self.acc("acc1")
        self.acc("acc3")
        B.make(self.prof, self.dest, now=T0)
        self.wipe()
        self.acc("acc1", real=False)  # слот установщика на месте стёртого профиля
        self.assertEqual(B.restore_missing(self.prof, self.dest)["restored"], ["acc1", "acc3"])
        self.assertEqual(B.real_names(self.prof), ["acc1", "acc3"])

    def test_deleted_by_button_and_relogin_duplicates_are_not_offered(self):
        self.acc("acc1")
        self.acc("acc2")
        self.acc("acc3")
        B.make(self.prof, self.dest, now=T0)
        B.note_deleted(self.dest, "u-acc2")  # «Удалить» нажали на acc2
        shutil.rmtree(self.prof + "/acc2")
        shutil.rmtree(self.prof + "/acc3")
        self.acc("acc5", uuid="u-acc3", token="relogin")  # acc3 вошли заново под другим именем
        self.assertEqual(B.missing(self.prof, self.dest), [])
        self.assertEqual(B.restore_missing(self.prof, self.dest)["restored"], [])
        self.assertFalse(os.path.exists(self.prof + "/acc2") or os.path.exists(self.prof + "/acc3"))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dest, B.DELETED)).st_mode), 0o600)

    def test_old_dated_copy_is_used_when_latest_is_broken(self):
        self.acc("acc1")
        self.acc("acc2")
        B.make(self.prof, self.dest, now=T0)
        with open(os.path.join(self.dest, B.LATEST), "wb") as f:
            f.write(b"not a tar")
        shutil.rmtree(self.prof + "/acc2")
        self.assertEqual(B.restore_missing(self.prof, self.dest)["restored"], ["acc2"])
        info = B.listing(self.prof, self.dest)
        self.assertTrue(info["latest"]["bad"])
        self.assertEqual(info["missing"], [])

    def test_hostile_archive_members_are_ignored(self):
        os.makedirs(self.dest)
        path = os.path.join(self.dest, B.LATEST)
        with tarfile.open(path, "w:gz") as tf:
            def add(name, data=b'{"accountUuid":"u-x"}', typ=tarfile.REGTYPE, link=""):
                ti = tarfile.TarInfo(name)
                ti.type, ti.linkname = typ, link
                ti.size = len(data) if typ == tarfile.REGTYPE else 0
                tf.addfile(ti, io.BytesIO(data) if typ == tarfile.REGTYPE else None)
            add("../evil/credentials.json")
            add("/abs/credentials.json")
            add("acc1/../../x/credentials.json")
            add("acc1/other.txt")
            add("acc1/credentials.json", typ=tarfile.SYMTYPE, link="/etc/passwd")
            add("acc1/oauth_account.json")  # без credentials.json профиль неполный
            add("notacc/credentials.json")
            add("notacc/oauth_account.json")
        self.assertEqual(B.archive_names(path), [])
        self.assertEqual(B.restore_missing(self.prof, self.dest)["restored"], [])
        self.assertEqual(os.listdir(self.prof), [])
        self.assertFalse(os.path.exists(os.path.join(self.d, "evil")))

    def test_copy_made_by_tar_from_profiles_root_is_understood(self):
        self.acc("acc1")
        os.makedirs(self.dest)
        with tarfile.open(os.path.join(self.dest, "profiles_20261101_010000_n1.tar.gz"), "w:gz") as tf:
            tf.add(self.prof, arcname=".claude-profiles")  # как делает ночной скрипт на сервере
        shutil.rmtree(self.prof + "/acc1")
        self.assertEqual(B.restore_missing(self.prof, self.dest)["restored"], ["acc1"])


# --- окно ⚙ и маршруты панели ---------------------------------------------------------------------

class Api(Base):
    def setUp(self):
        super().setUp()
        self.cfgf = os.path.join(self.d, "claude.json")
        put(self.cfgf, {"oauthAccount": {"accountUuid": "u-other"}})
        self.base = os.path.join(self.d, "base")
        os.makedirs(self.base)
        self.patches = [mock.patch.object(L, n, v) for n, v in (
            ("PROFILES", self.prof), ("BACKUP_DIR", self.dest), ("LIVE_CFG", self.cfgf), ("BASE", self.base),
            ("CONFIG", os.path.join(self.base, "config.json")), ("STATE", os.path.join(self.base, "state.json")),
            ("SNAPSHOT", os.path.join(self.base, "snapshot.json")), ("GOOD", os.path.join(self.base, "good.json")))]
        self.patches.append(mock.patch.object(L, "tg_notify", lambda *a, **k: None))  # удаление шлёт сообщение в Telegram
        for p in self.patches:
            p.start()
        self.auth = mock.patch.object(L.H, "_authed", return_value=True)
        self.auth.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), L.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.auth.stop()
        for p in self.patches:
            p.stop()
        super().tearDown()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def test_status_now_restore_and_switch(self):
        self.acc("acc1")
        self.acc("acc2")
        st = self.call("/api/backup")
        self.assertEqual((st["enabled"], st["keep"], st["profiles"], st["items"], st["missing"]), (True, 14, 2, [], []))
        r = self.call("/api/backup/now", {})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["n"], 2)
        shutil.rmtree(self.prof + "/acc2")
        self.assertEqual(self.call("/api/backup")["missing"], ["acc2"])
        r = self.call("/api/backup/restore", {})
        self.assertEqual((r["ok"], r["restored"], r["missing"]), (True, ["acc2"], []))
        self.assertEqual(B.real_names(self.prof), ["acc1", "acc2"])
        self.call("/api/config", {"profile_backup": False})
        self.assertFalse(self.call("/api/backup")["enabled"])
        self.call("/api/config", {"profile_backup": True})
        self.assertTrue(self.call("/api/backup")["enabled"])

    def test_now_with_nothing_real_says_why(self):
        self.acc("acc1", real=False)
        r = self.call("/api/backup/now", {})
        self.assertEqual((r["ok"], r["why"]), (False, "empty"))

    def test_routes_need_auth(self):
        with mock.patch.object(L.H, "_authed", return_value=False):
            for path, body in (("/api/backup", None), ("/api/backup/now", {}), ("/api/backup/restore", {})):
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self.call(path, body)
                self.assertEqual(cm.exception.code, 403, path)

    def test_delete_button_remembers_the_account_and_it_is_not_offered_back(self):
        self.acc("acc1")
        self.acc("acc2")
        self.assertTrue(B.make(self.prof, self.dest, now=T0)["ok"])
        r = self.call("/api/account/delete", {"account": "acc2", "confirm": "подтверждаю"})
        self.assertTrue(r.get("ok"), r)
        self.assertFalse(os.path.exists(self.prof + "/acc2"))
        self.assertEqual(self.call("/api/backup")["missing"], [])
        self.assertEqual(self.call("/api/backup/restore", {})["restored"], [])


def i18n_block(lang):
    """Тело словаря текстов одного языка из страницы."""
    import re
    m = re.search(r"\n %s:\{\n(.*?)\n \},?\n" % lang, L.PAGE, re.S)
    assert m, lang
    return m.group(1)


class Page(unittest.TestCase):
    def test_settings_block_and_texts_in_both_languages(self):
        import re
        page = L.PAGE
        self.assertIn('id="bkBox"', page)
        self.assertIn("function bkRender", page)
        keys = {lang: set(re.findall(r"^\s{2}(bk\w*):", i18n_block(lang), re.M)) for lang in ("ru", "en")}
        self.assertGreaterEqual(len(keys["ru"]), 10)
        self.assertEqual(keys["ru"], keys["en"])  # каждая подпись есть и по-русски, и по-английски
        self.assertIn("Копии аккаунтов", i18n_block("ru"))
        self.assertIn("Account backups", i18n_block("en"))

    def test_module_ships_with_release(self):
        here = os.path.dirname(os.path.abspath(__file__))
        m = get(os.path.join(here, "update_manifest.json"))
        ent = [e for e in m["files"] if e["src"] == "cc_backup.py"]
        self.assertEqual(len(ent), 1)
        self.assertNotIn("dst", ent[0])
        with open(os.path.join(here, "install.sh"), encoding="utf-8") as f:
            t = f.read()
        # установщик ставит файлы из манифеста (module_list), отдельной строки про модуль в нём нет
        self.assertIn("module_list", t)
        self.assertIn('"$SCRIPT_DIR/$src"', t)


if __name__ == "__main__":
    unittest.main()
