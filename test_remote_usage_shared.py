# Скрипт лимитов на втором сервере: общий кэш нескольких входов одного аккаунта (2.0.47).
# Причина: на одном сервере два входа в ОДИН аккаунт (например, root и обычный пользователь), у каждого свой токен и свой кэш.
# Токен одного устаревал, и его панель показывала «токен устарел» или старые цифры, пока вторая панель видела живые.
# Теперь каждый вход пишет в общий каталог свой файл <логин>.json (проценты, время сброса, тариф, хэш почты), читают все.
# python3 -m unittest test_remote_usage_shared -v
import json
import os
import pwd
import shutil
import tempfile
import unittest
from unittest import mock

from test_remote_usage_cache import NOW, Net, make_home, run

SKIP_ROOT = unittest.skipUnless(os.getuid() == 0, "нужен root: файлы общего кэша создаются от имени других логинов")


def other_login():
    for name in ("nobody", "daemon"):
        try:
            return name, pwd.getpwnam(name).pw_uid
        except KeyError:
            continue
    return None, None


class Shared(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="usage_shared_")
        os.chmod(self.dir, 0o1777)
        open(os.path.join(self.dir, ".lock"), "w").close()
        self.addCleanup(shutil.rmtree, self.dir, True)
        p = mock.patch.dict(os.environ, {"CC_FLEET_USAGE_SHARED": self.dir})
        p.start()
        self.addCleanup(p.stop)
        self.me = pwd.getpwuid(os.getuid()).pw_name

    def run_usage(self, home, net, now):
        # переменная окружения читается при загрузке скрипта: run() каждый раз запускает его заново (runpy)
        return run(home, net, now)

    def mine(self):
        return json.load(open(os.path.join(self.dir, self.me + ".json")))

    def expire_token(self, home, now=NOW):
        with open(os.path.join(home, ".claude", ".credentials.json"), "w") as f:
            json.dump({"claudeAiOauth": {"accessToken": "t", "expiresAt": int((now - 3600) * 1000)}}, f)

    def test_live_login_writes_shared_file_without_secrets(self):
        home, net = make_home(), Net()
        self.run_usage(home, net, NOW)
        doc = self.mine()
        self.assertEqual(doc["net"]["five_hour"]["pct"], 40)
        self.assertEqual(doc["net"]["plan"], "max")
        raw = open(os.path.join(self.dir, self.me + ".json")).read()
        self.assertNotIn("a@example.com", raw)                  # самой почты нет, только хэш
        self.assertNotIn("accessToken", raw)
        self.assertNotIn("raw_other", raw)
        self.assertEqual(len(doc["acct"]), 12)
        self.assertEqual(os.stat(os.path.join(self.dir, self.me + ".json")).st_mode & 0o777, 0o644)

    def test_fresh_own_cache_is_published_without_asking_anthropic(self):
        home, net = make_home(), Net()
        with mock.patch.dict(os.environ, {"CC_FLEET_USAGE_SHARED": os.path.join(self.dir, "нет")}):
            self.run_usage(home, net, NOW)                       # раньше: общего кэша не было, личный заполнился
        self.assertFalse(os.path.getsize(os.path.join(self.dir, self.me + ".json")) if os.path.exists(os.path.join(self.dir, self.me + ".json")) else 0)
        r = self.run_usage(home, net, NOW + 30)                  # личный кэш свежий, в сеть идти не надо — но в общий его положить надо
        self.assertEqual(net.usage, 1)
        self.assertTrue(r["ok"])
        self.assertEqual(self.mine()["net"]["five_hour"]["pct"], 40)
        b = make_home()
        self.expire_token(b)
        self.assertTrue(self.run_usage(b, net, NOW + 60)["shared"])   # и второй вход с устаревшим токеном их видит

    def test_expired_token_takes_numbers_of_the_other_login(self):
        a, b, net = make_home(), make_home(), Net()
        self.run_usage(a, net, NOW)                              # живой вход обновил общий кэш
        self.expire_token(b)
        r = self.run_usage(b, net, NOW + 60)                     # у второго токен устарел
        self.assertTrue(r["ok"])
        self.assertTrue(r["shared"])
        self.assertEqual(r["five_hour"]["pct"], 40)
        self.assertEqual(r["plan"], "max")
        self.assertEqual(net.usage, 1)                           # второй вход в сеть не ходил

    def test_expired_token_and_old_shared_is_still_token_expired(self):
        a, b, net = make_home(), make_home(), Net()
        self.run_usage(a, net, NOW)
        self.expire_token(b, NOW + 3 * 3600)
        r = self.run_usage(b, net, NOW + 3 * 3600)               # общие цифры старше 10 минут — живыми не считаем
        self.assertEqual(r, {"ok": False, "error": "token_expired"})

    def test_expired_token_without_shared_dir_is_token_expired_as_before(self):
        b = make_home()
        self.expire_token(b)
        with mock.patch.dict(os.environ, {"CC_FLEET_USAGE_SHARED": os.path.join(self.dir, "нет")}):
            self.assertEqual(self.run_usage(b, Net(), NOW), {"ok": False, "error": "token_expired"})

    def test_fresh_numbers_of_the_other_login_save_a_request(self):
        a, b, net = make_home(), make_home(), Net()
        self.run_usage(a, net, NOW)
        r = self.run_usage(b, net, NOW + 30)                     # оба живые, второй пришёл в окно TTL первого
        self.assertEqual((net.usage, net.profile), (1, 1))
        self.assertTrue(r["ok"] and r["shared"])
        self.assertEqual(r["five_hour"]["pct"], 40)

    def test_after_ttl_the_login_asks_anthropic_and_updates_shared(self):
        a, b, net = make_home(), make_home(), Net()
        self.run_usage(a, net, NOW)
        net.pct = 77
        r = self.run_usage(b, net, NOW + 200)
        self.assertEqual(net.usage, 2)
        self.assertEqual(r["five_hour"]["pct"], 77)
        self.assertNotIn("shared", r)
        self.assertEqual(self.mine()["net"]["five_hour"]["pct"], 77)

    def test_429_pause_is_shared_between_logins(self):
        a, b, net = make_home(), make_home(), Net()
        self.run_usage(a, net, NOW)
        net.mode, net.retry_after = "429", 300
        r = self.run_usage(a, net, NOW + 200)                    # a упёрся в 429
        self.assertTrue(r["ok"] and r["stale"])
        asked = net.usage
        r = self.run_usage(b, net, NOW + 250)                    # b до конца паузы Anthropic не трогает
        self.assertEqual(net.usage, asked)
        self.assertTrue(r["ok"] and r["stale"])
        self.assertEqual(r["five_hour"]["pct"], 40)              # отдаёт последние удачные цифры
        self.assertEqual(r["retry_at"], NOW + 200 + 300)

    @SKIP_ROOT
    def test_files_of_other_logins_are_read_only_if_owned_by_that_login(self):
        name, uid = other_login()
        if not name:
            self.skipTest("нет вспомогательного логина")
        b = make_home()
        self.expire_token(b)
        path = os.path.join(self.dir, name + ".json")
        acct = "x"
        # свой аккаунт (тот же хэш почты) — прочитать как у любого входа
        a = make_home()
        self.run_usage(a, Net(), NOW)
        good = self.mine()
        os.unlink(os.path.join(self.dir, self.me + ".json"))
        with open(path, "w") as f:
            json.dump(good, f)
        # 1) владелец файла — не тот логин (root вместо nobody) → игнор
        self.assertEqual(self.run_usage(b, Net(), NOW + 30), {"ok": False, "error": "token_expired"})
        # 2) владелец тот → цифры берём
        os.chown(path, uid, -1)
        r = self.run_usage(b, Net(), NOW + 30)
        self.assertTrue(r["ok"] and r["shared"])
        # 3) другой аккаунт (хэш почты не совпал) → игнор
        os.chown(path, 0, -1)
        doc = dict(good, acct="0" * 12)
        with open(path, "w") as f:
            json.dump(doc, f)
        os.chown(path, uid, -1)
        self.assertEqual(self.run_usage(b, Net(), NOW + 30), {"ok": False, "error": "token_expired"})
        # 4) симлинк вместо файла → игнор
        os.unlink(path)
        real = os.path.join(self.dir, "real.txt")
        with open(real, "w") as f:
            json.dump(good, f)
        os.chown(real, uid, -1)
        os.symlink(real, path)
        self.assertEqual(self.run_usage(b, Net(), NOW + 30), {"ok": False, "error": "token_expired"})
        # 5) логин, которого нет в системе → игнор
        os.unlink(path)
        ghost = os.path.join(self.dir, "нет_такого_логина_123.json")
        with open(ghost, "w") as f:
            json.dump(good, f)
        self.assertEqual(self.run_usage(b, Net(), NOW + 30), {"ok": False, "error": "token_expired"})

    def test_broken_shared_file_does_not_break_polling(self):
        open(os.path.join(self.dir, self.me + ".json"), "w").write("{не json")
        home, net = make_home(), Net()
        r = self.run_usage(home, net, NOW)
        self.assertTrue(r["ok"])
        self.assertEqual(r["five_hour"]["pct"], 40)
        self.assertEqual(self.mine()["net"]["five_hour"]["pct"], 40)        # и файл починился

    def test_no_lock_file_is_fine_and_not_created(self):
        os.unlink(os.path.join(self.dir, ".lock"))
        r = self.run_usage(make_home(), Net(), NOW)
        self.assertTrue(r["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".lock")))   # замок создаёт администратор, не скрипт


if __name__ == "__main__":
    unittest.main()
