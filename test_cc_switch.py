# Тест cc-switch как процесса, на временной копии «домашней папки»: python3 -m unittest test_cc_switch -v
# Живые ~/.claude*, профили и /opt/cc-limits не затрагиваются (CC_SWITCH_HOME / CC_LIMITS_BASE).
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SWITCH = os.path.join(HERE, "cc-switch")
sys.path.insert(0, HERE)
import cc_lock as K  # noqa: E402


class SwitchProc(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ccsw_")
        self.home = os.path.join(self.d, "home")
        self.base = os.path.join(self.d, "base")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(self.base)
        shutil.copy(os.path.join(HERE, "cc_lock.py"), self.base)
        self.live = os.path.join(self.home, ".claude", ".credentials.json")
        self.cfg = os.path.join(self.home, ".claude.json")
        for n in ("acc1", "acc2"):
            pd = os.path.join(self.home, ".claude-profiles", n)
            os.makedirs(pd)
            json.dump({"claudeAiOauth": {"accessToken": "tok-" + n}}, open(os.path.join(pd, "credentials.json"), "w"))
            json.dump({"accountUuid": "u-" + n, "emailAddress": n + "@x"}, open(os.path.join(pd, "oauth_account.json"), "w"))
        # живая сессия сейчас на acc1, и её токен успел обновиться (отличается от профильного)
        json.dump({"claudeAiOauth": {"accessToken": "tok-acc1-REFRESHED"}}, open(self.live, "w"))
        json.dump({"theme": "dark", "oauthAccount": {"accountUuid": "u-acc1", "emailAddress": "acc1@x"}}, open(self.cfg, "w"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_switch(self, *args, base=None, timeout_env="2"):
        env = dict(os.environ, CC_SWITCH_HOME=self.home, CC_LIMITS_BASE=base or self.base, CC_LOCK_TIMEOUT=timeout_env)
        return subprocess.run([sys.executable, SWITCH, *args], capture_output=True, text=True, env=env, timeout=60)

    def live_tok(self):
        return json.load(open(self.live))["claudeAiOauth"]["accessToken"]

    def leftovers(self):
        out = []
        for root, dirs, files in os.walk(self.d):
            out += [os.path.join(root, x) for x in dirs + files if x.endswith(".lock") or x.endswith(".tmp")]
        return out

    def test_switch_syncs_back_and_swaps(self):
        r = self.run_switch("acc2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.live_tok(), "tok-acc2")
        cfg = json.load(open(self.cfg))
        self.assertEqual(cfg["oauthAccount"]["accountUuid"], "u-acc2")
        self.assertEqual(cfg["theme"], "dark")  # чужие ключи .claude.json целы
        back = json.load(open(os.path.join(self.home, ".claude-profiles", "acc1", "credentials.json")))
        self.assertEqual(back["claudeAiOauth"]["accessToken"], "tok-acc1-REFRESHED")  # обновлённый токен не потерян
        self.assertEqual(oct(os.stat(self.live).st_mode & 0o777), "0o600")
        self.assertEqual(self.leftovers(), [])

    def test_waits_for_cli_lock_then_succeeds(self):
        lock = K.DirLock(os.path.join(self.home, ".claude", ".oauth_refresh.lock"), 60)
        lock.acquire()
        threading.Timer(1.0, lock.release).start()
        t0 = time.time()
        r = self.run_switch("acc2", timeout_env="8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreaterEqual(time.time() - t0, 0.8)
        self.assertEqual(self.live_tok(), "tok-acc2")

    def test_busy_lock_changes_nothing(self):
        os.mkdir(os.path.join(self.home, ".claude", ".oauth_refresh.lock"))  # CLI держит и не отпускает
        r = self.run_switch("acc2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("повтори", r.stderr)
        self.assertEqual(self.live_tok(), "tok-acc1-REFRESHED")
        self.assertEqual(json.load(open(self.cfg))["oauthAccount"]["accountUuid"], "u-acc1")
        back = json.load(open(os.path.join(self.home, ".claude-profiles", "acc1", "credentials.json")))
        self.assertEqual(back["claudeAiOauth"]["accessToken"], "tok-acc1")  # профиль тоже не тронут

    def test_stale_cli_lock_is_taken_over(self):
        p = os.path.join(self.home, ".claude", ".oauth_refresh.lock")
        os.mkdir(p)
        os.utime(p, (time.time() - 300, time.time() - 300))
        r = self.run_switch("acc2")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_failed_config_write_rolls_back_credentials(self):
        os.mkdir(self.cfg + ".lock")  # .claude.json правит кто-то другой и не отпускает
        r = self.run_switch("acc2")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.live_tok(), "tok-acc1-REFRESHED")  # откат: токены не от другого аккаунта
        self.assertEqual(json.load(open(self.cfg))["oauthAccount"]["accountUuid"], "u-acc1")

    def test_without_cc_lock_module_still_works(self):
        empty = os.path.join(self.d, "nobase")
        os.makedirs(empty)
        r = self.run_switch("acc2", base=empty)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.live_tok(), "tok-acc2")
        self.assertEqual(json.load(open(self.cfg))["oauthAccount"]["accountUuid"], "u-acc2")

    def test_save_is_atomic_copy(self):
        r = self.run_switch("save", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        p = os.path.join(self.home, ".claude-profiles", "acc3", "credentials.json")
        self.assertEqual(json.load(open(p))["claudeAiOauth"]["accessToken"], "tok-acc1-REFRESHED")

    def test_unsaved_current_account_goes_to_backup(self):
        json.dump({"oauthAccount": {"accountUuid": "u-stranger", "emailAddress": "s@x"}}, open(self.cfg, "w"))
        r = self.run_switch("acc2")
        self.assertEqual(r.returncode, 0, r.stderr)
        baks = [x for x in os.listdir(os.path.join(self.home, ".claude-profiles")) if x.startswith("_unsaved_")]
        self.assertEqual(len(baks), 1)
        self.assertEqual(json.load(open(os.path.join(self.home, ".claude-profiles", baks[0], "credentials.json")))
                         ["claudeAiOauth"]["accessToken"], "tok-acc1-REFRESHED")


if __name__ == "__main__":
    unittest.main()
