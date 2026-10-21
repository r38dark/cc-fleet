# Тесты замков и атомарной записи: python3 -m unittest test_cc_lock -v
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest

import cc_lock as K


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cclock_")
        self.claude_dir = os.path.join(self.d, ".claude")
        os.makedirs(self.claude_dir)
        self.creds = os.path.join(self.claude_dir, ".credentials.json")
        self.cfg = os.path.join(self.d, ".claude.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)


class AtomicWrite(Base):
    def test_content_mode_and_no_tmp_left(self):
        p = os.path.join(self.d, "f.json")
        K.atomic_write(p, '{"a": 1}', 0o600)
        self.assertEqual(open(p).read(), '{"a": 1}')
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual([x for x in os.listdir(self.d) if x.endswith(".tmp")], [])

    def test_overwrite_and_bytes(self):
        p = os.path.join(self.d, "f")
        K.atomic_write(p, b"old")
        K.atomic_write(p, b"new")
        self.assertEqual(open(p, "rb").read(), b"new")

    def test_failure_keeps_old_file_and_cleans_tmp(self):
        p = os.path.join(self.d, "f")
        K.atomic_write(p, "old")
        with self.assertRaises(Exception):
            K.atomic_write(p, 12345)  # не str/bytes → падает до замены
        self.assertEqual(open(p).read(), "old")
        self.assertEqual([x for x in os.listdir(self.d) if x.endswith(".tmp")], [])


class Lock(Base):
    def test_exclusive_then_released(self):
        p = os.path.join(self.d, "x.lock")
        with K.DirLock(p, 60):
            with self.assertRaises(K.LockTimeout):
                K.DirLock(p, 60, timeout=0.3).acquire()
        with K.DirLock(p, 60, timeout=0.3):  # после отпускания берётся
            pass
        self.assertFalse(os.path.exists(p))

    def test_stale_lock_is_broken(self):
        p = os.path.join(self.d, "x.lock")
        os.mkdir(p)
        old = time.time() - 120
        os.utime(p, (old, old))
        with K.DirLock(p, 60, timeout=1):
            pass

    def test_stale_lock_with_owner_file_is_broken(self):
        p = os.path.join(self.d, "x.lock")
        os.mkdir(p)
        open(os.path.join(p, ".oauth_refresh.lock.owner"), "w").write("{}")
        old = time.time() - 120
        os.utime(p, (old, old))
        with K.DirLock(p, 60, timeout=1):
            pass

    def test_fresh_foreign_lock_is_respected(self):
        p = os.path.join(self.d, "x.lock")
        os.mkdir(p)  # свежий, чужой
        with self.assertRaises(K.LockTimeout):
            K.DirLock(p, 60, timeout=0.3).acquire()
        self.assertTrue(os.path.isdir(p))

    def test_touch_keeps_held_lock_alive(self):
        p = os.path.join(self.d, "x.lock")
        with K.DirLock(p, stale=1, touch_every=0.2):
            time.sleep(1.6)  # дольше stale: без touch замок сочли бы брошенным
            with self.assertRaises(K.LockTimeout):
                K.DirLock(p, 1, timeout=0.3).acquire()

    def test_no_lost_updates_under_contention(self):
        p = os.path.join(self.d, "x.lock")
        counter = os.path.join(self.d, "n")
        open(counter, "w").write("0")

        def work():
            for _ in range(15):
                with K.DirLock(p, 60, timeout=30):
                    n = int(open(counter).read())
                    time.sleep(0.001)
                    open(counter, "w").write(str(n + 1))
        ts = [threading.Thread(target=work) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(int(open(counter).read()), 90)

    def test_oauth_lock_takes_both_paths_and_frees_them(self):
        with K.oauth_lock(self.claude_dir, self.d):
            self.assertTrue(os.path.isdir(os.path.join(self.claude_dir, ".oauth_refresh.lock")))
            self.assertTrue(os.path.isdir(os.path.join(self.d, ".claude.lock")))
        self.assertFalse(os.path.exists(os.path.join(self.claude_dir, ".oauth_refresh.lock")))
        self.assertFalse(os.path.exists(os.path.join(self.d, ".claude.lock")))

    def test_oauth_lock_held_by_cli_blocks_us(self):
        os.mkdir(os.path.join(self.claude_dir, ".oauth_refresh.lock"))  # CLI обновляет токен
        with self.assertRaises(K.LockTimeout):
            with K.oauth_lock(self.claude_dir, self.d, timeout=0.3):
                pass
        self.assertFalse(os.path.exists(os.path.join(self.d, ".claude.lock")))  # второй замок не остался


class SwapLive(Base):
    def setUp(self):
        super().setUp()
        K.atomic_write(self.creds, json.dumps({"claudeAiOauth": {"accessToken": "OLD"}}), 0o600)
        K.atomic_write(self.cfg, json.dumps({"keep": [1, 2], "oauthAccount": {"emailAddress": "old@x"}}), 0o644)

    def swap(self, **kw):
        K.swap_live(self.creds, {"claudeAiOauth": {"accessToken": "NEW"}}, self.cfg,
                    {"emailAddress": "new@x"}, self.claude_dir, self.d, **kw)

    def test_success_writes_both_and_keeps_rest(self):
        self.swap()
        self.assertEqual(json.load(open(self.creds))["claudeAiOauth"]["accessToken"], "NEW")
        cfg = json.load(open(self.cfg))
        self.assertEqual(cfg["oauthAccount"]["emailAddress"], "new@x")
        self.assertEqual(cfg["keep"], [1, 2])
        self.assertEqual(stat.S_IMODE(os.stat(self.creds).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.cfg).st_mode), 0o644)
        self.assertFalse(os.path.exists(os.path.join(self.claude_dir, ".oauth_refresh.lock")))
        self.assertFalse(os.path.exists(self.cfg + ".lock"))

    def test_second_write_failure_rolls_back_credentials(self):
        open(self.cfg, "w").write("{ битый json")  # вторая запись упадёт при чтении
        with self.assertRaises(ValueError):
            self.swap()
        self.assertEqual(json.load(open(self.creds))["claudeAiOauth"]["accessToken"], "OLD")
        self.assertFalse(os.path.exists(os.path.join(self.claude_dir, ".oauth_refresh.lock")))

    def test_config_lock_timeout_rolls_back_and_releases(self):
        os.mkdir(self.cfg + ".lock")  # кто-то правит .claude.json
        with self.assertRaises(K.LockTimeout):
            self.swap(timeout=0.3)
        self.assertEqual(json.load(open(self.creds))["claudeAiOauth"]["accessToken"], "OLD")
        self.assertEqual(json.load(open(self.cfg))["oauthAccount"]["emailAddress"], "old@x")
        self.assertFalse(os.path.exists(os.path.join(self.claude_dir, ".oauth_refresh.lock")))

    def test_oauth_lock_timeout_changes_nothing(self):
        os.mkdir(os.path.join(self.claude_dir, ".oauth_refresh.lock"))
        with self.assertRaises(K.LockTimeout):
            self.swap(timeout=0.3)
        self.assertEqual(json.load(open(self.creds))["claudeAiOauth"]["accessToken"], "OLD")
        self.assertEqual(json.load(open(self.cfg))["oauthAccount"]["emailAddress"], "old@x")

    def test_before_runs_under_lock_and_sees_old_creds(self):
        seen = {}

        def before():
            seen["lock"] = os.path.isdir(os.path.join(self.claude_dir, ".oauth_refresh.lock"))
            seen["tok"] = json.load(open(self.creds))["claudeAiOauth"]["accessToken"]
        self.swap(before=before)
        self.assertEqual(seen, {"lock": True, "tok": "OLD"})

    def test_before_failure_changes_nothing(self):
        def before():
            raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            self.swap(before=before)
        self.assertEqual(json.load(open(self.creds))["claudeAiOauth"]["accessToken"], "OLD")
        self.assertFalse(os.path.exists(os.path.join(self.claude_dir, ".oauth_refresh.lock")))

    def test_missing_creds_file_rollback_removes_new_one(self):
        os.unlink(self.creds)
        open(self.cfg, "w").write("{ битый json")
        with self.assertRaises(ValueError):
            self.swap()
        self.assertFalse(os.path.exists(self.creds))


if __name__ == "__main__":
    unittest.main()
