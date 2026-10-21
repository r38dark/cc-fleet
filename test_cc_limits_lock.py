# Интеграция замка Claude Code в cc_limits.py: python3 -m unittest test_cc_limits_lock -v
# Настоящие refresh_tokens()/relogin_submit() против подставного сервера на localhost.
# Живой логин и /opt/cc-limits не затрагиваются: BASE/PROFILES/LIVE_* уводятся во временную папку.
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

TMP = tempfile.mkdtemp(prefix="cclocklim_")
os.environ.setdefault("CC_LIMITS_BASE", os.path.join(TMP, "base"))
os.environ.setdefault("CC_LIMITS_PROFILES", os.path.join(TMP, "profiles"))

import cc_limits as L  # noqa: E402  (после подмены путей)
import cc_lock as K  # noqa: E402


class Fake(http.server.BaseHTTPRequestHandler):
    token_posts = []     # тела POST на обмен токена
    usage_tokens = []    # токены, с которыми приходили за usage

    def log_message(self, *a):
        pass

    def _send(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        Fake.token_posts.append(json.loads(self.rfile.read(n) or b"{}"))
        self._send({"access_token": "NEW-ACCESS", "refresh_token": "NEW-REFRESH", "expires_in": 28800})

    def do_GET(self):
        tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        if self.path.startswith("/api/oauth/usage"):
            Fake.usage_tokens.append(tok)
            self._send({"five_hour": {"utilization": 10, "resets_at": "2099-01-01T00:00:00+00:00"},
                        "seven_day": {"utilization": 5, "resets_at": "2099-01-05T00:00:00+00:00"}})
        else:
            self._send({"account": {"has_claude_pro": True}})


class FakeChild:
    before = ""

    def sendline(self, *_):
        pass

    def expect(self, *_a, **_k):
        pass

    def close(self, force=False):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base_url = "http://127.0.0.1:%d" % cls.srv.server_port
        cls._orig_http = L.http_json

        def fake_http(url, payload=None, headers=None, timeout=20):
            url = url.replace("https://api.anthropic.com", cls.base_url).replace("https://platform.claude.com", cls.base_url)
            return cls._orig_http(url, payload, headers, timeout)
        L.http_json = fake_http

    @classmethod
    def tearDownClass(cls):
        L.http_json = cls._orig_http
        cls.srv.shutdown()

    def setUp(self):
        Fake.token_posts.clear()
        Fake.usage_tokens.clear()
        self.d = tempfile.mkdtemp(prefix="cclocklim_t_")
        for p in (L.PROFILES, L.BASE):
            shutil.rmtree(p, ignore_errors=True)
            os.makedirs(p)
        self.claude_dir = os.path.join(self.d, ".claude")
        os.makedirs(self.claude_dir)
        L.LIVE_CREDS = os.path.join(self.claude_dir, ".credentials.json")
        L.LIVE_CFG = os.path.join(self.d, ".claude.json")
        d = os.path.join(L.PROFILES, "acc1")
        os.makedirs(d)
        L.jsave(os.path.join(d, "credentials.json"), {"claudeAiOauth": {"accessToken": "old-p", "refreshToken": "r-p", "expiresAt": 1}})
        L.jsave(os.path.join(d, "oauth_account.json"), {"accountUuid": "u-acc1", "emailAddress": "acc1@example.com"})
        L.jsave(L.LIVE_CFG, {"theme": "dark", "oauthAccount": {"accountUuid": "u-acc1", "emailAddress": "acc1@example.com"}})
        L.jsave(L.CONFIG, {"threshold": 90, "weekly_cap": 99})
        L.backoff_until.clear()
        L._plan_cache.clear()
        self.patch = mock.patch.object(K, "oauth_lock", self._short_oauth_lock(K.oauth_lock))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.d, ignore_errors=True)

    @staticmethod
    def _short_oauth_lock(orig):
        return lambda claude_dir, home, timeout=0.6: orig(claude_dir, home, min(timeout, 0.6))  # в тестах долго не ждём

    def live(self, expires_ms, **extra):
        data = {"claudeAiOauth": {"accessToken": "live-old", "refreshToken": "r-live", "expiresAt": expires_ms}}
        data.update(extra)
        L.jsave(L.LIVE_CREDS, data)

    def lock_dir(self):
        return os.path.join(self.claude_dir, ".oauth_refresh.lock")


class RefreshUnderLock(Base):
    def test_expired_live_token_is_refreshed_keeps_other_keys_and_frees_lock(self):
        self.live(1, mcpOAuth={"srv": "keep-me"})
        snap = L.collect(force=True)
        self.assertEqual(len(Fake.token_posts), 1)
        self.assertEqual(Fake.token_posts[0]["refresh_token"], "r-live")
        data = L.jload(L.LIVE_CREDS)
        self.assertEqual(data["claudeAiOauth"]["accessToken"], "NEW-ACCESS")
        self.assertEqual(data["claudeAiOauth"]["refreshToken"], "NEW-REFRESH")
        self.assertEqual(data["mcpOAuth"], {"srv": "keep-me"})  # чужие ключи живого файла целы
        self.assertEqual(Fake.usage_tokens, ["NEW-ACCESS"])
        self.assertEqual(L.jload(os.path.join(L.PROFILES, "acc1", "credentials.json"))["claudeAiOauth"]["accessToken"], "NEW-ACCESS")
        self.assertNotIn("error", snap["accounts"]["acc1"])
        self.assertFalse(os.path.exists(self.lock_dir()))
        self.assertFalse(os.path.exists(os.path.join(self.d, ".claude.lock")))
        self.assertEqual(oct(os.stat(L.LIVE_CREDS).st_mode & 0o777), "0o600")

    def test_fresh_live_token_is_not_refreshed(self):
        self.live(int((time.time() + 3600) * 1000))
        L.collect(force=True)
        self.assertEqual(Fake.token_posts, [])
        self.assertEqual(Fake.usage_tokens, ["live-old"])

    def test_cli_refreshed_while_we_waited_no_second_exchange(self):
        # refresh-токен одноразовый: если Claude Code обновил логин, пока мы ждали замок,
        # повторный обмен старым refresh-токеном сбросил бы логин
        self.live(1)
        os.mkdir(self.lock_dir())

        def cli_finishes():
            time.sleep(0.25)
            L.jsave(L.LIVE_CREDS, {"claudeAiOauth": {"accessToken": "cli-fresh", "refreshToken": "r-cli",
                                                      "expiresAt": int((time.time() + 28000) * 1000)}})
            os.rmdir(self.lock_dir())
        t = threading.Thread(target=cli_finishes)
        t.start()
        L.collect(force=True)
        t.join()
        self.assertEqual(Fake.token_posts, [])
        self.assertEqual(Fake.usage_tokens, ["cli-fresh"])
        self.assertEqual(L.jload(L.LIVE_CREDS)["claudeAiOauth"]["refreshToken"], "r-cli")

    def test_busy_lock_means_error_card_and_no_requests(self):
        self.live(1)
        os.mkdir(self.lock_dir())  # CLI держит замок и не отпускает
        snap = L.collect(force=True)
        row = snap["accounts"]["acc1"]
        self.assertIn("Claude Code сейчас обновляет логин", row["error"])
        self.assertEqual(Fake.token_posts, [])
        self.assertEqual(Fake.usage_tokens, [])
        self.assertEqual(L.jload(L.LIVE_CREDS)["claudeAiOauth"]["refreshToken"], "r-live")  # файл не тронут

    def test_non_live_profile_refresh_needs_no_lock(self):
        os.mkdir(self.lock_dir())
        p = os.path.join(L.PROFILES, "acc1", "credentials.json")
        c = L.refresh_tokens(p)
        self.assertEqual(c["accessToken"], "NEW-ACCESS")
        self.assertEqual(L.jload(p)["claudeAiOauth"]["refreshToken"], "NEW-REFRESH")


class ReloginLive(Base):
    def setUp(self):
        super().setUp()
        self.live(int((time.time() + 3600) * 1000))
        self.home = tempfile.mkdtemp(prefix="relogin_home_", dir=self.d)
        os.makedirs(os.path.join(self.home, ".claude"))
        L.jsave(os.path.join(self.home, ".claude", ".credentials.json"),
                {"claudeAiOauth": {"accessToken": "relogged", "refreshToken": "r-relogged", "expiresAt": int((time.time() + 9999) * 1000)}})
        L.jsave(os.path.join(self.home, ".claude.json"),
                {"oauthAccount": {"accountUuid": "u-acc1", "emailAddress": "acc1@example.com", "extra": 1}})
        L._relogin["acc1"] = {"child": FakeChild(), "home": self.home, "started": time.time(), "new": False}

    def tearDown(self):
        L._relogin.pop("acc1", None)
        super().tearDown()

    def test_active_profile_relogin_writes_live_files_under_lock(self):
        ok, msg, snap = L.relogin_submit("acc1", "code")
        self.assertTrue(ok, msg)
        self.assertEqual(L.jload(L.LIVE_CREDS)["claudeAiOauth"]["accessToken"], "relogged")
        cfg = L.jload(L.LIVE_CFG)
        self.assertEqual(cfg["oauthAccount"]["extra"], 1)
        self.assertEqual(cfg["theme"], "dark")
        self.assertEqual(L.jload(os.path.join(L.PROFILES, "acc1", "credentials.json"))["claudeAiOauth"]["accessToken"], "relogged")
        self.assertNotIn("acc1", L._relogin)
        self.assertFalse(os.path.exists(self.lock_dir()))

    def test_busy_lock_keeps_login_and_retry_succeeds(self):
        os.mkdir(self.lock_dir())
        ok, msg, _ = L.relogin_submit("acc1", "code")
        self.assertFalse(ok)
        self.assertIn("Claude Code сейчас обновляет логин", msg)
        self.assertEqual(L.jload(L.LIVE_CREDS)["claudeAiOauth"]["accessToken"], "live-old")  # живая сессия не тронута
        self.assertIn("acc1", L._relogin)  # вход не потерян
        self.assertTrue(os.path.isdir(self.home))
        os.rmdir(self.lock_dir())
        ok, msg, _ = L.relogin_submit("acc1", "code")
        self.assertTrue(ok, msg)
        self.assertEqual(L.jload(L.LIVE_CREDS)["claudeAiOauth"]["accessToken"], "relogged")
        self.assertNotIn("acc1", L._relogin)


class JsaveAtomic(Base):
    def test_unique_tmp_and_mode(self):
        p = os.path.join(L.BASE, "x.json")
        L.jsave(p, {"a": 1})
        self.assertEqual(L.jload(p), {"a": 1})
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")
        self.assertEqual([x for x in os.listdir(L.BASE) if x.endswith(".tmp")], [])

    def test_parallel_writers_never_leave_broken_file(self):
        p = os.path.join(L.BASE, "x.json")
        L.jsave(p, {"n": 0})
        stop = time.time() + 1.0
        bad = []

        def writer(i):
            while time.time() < stop:
                L.jsave(p, {"n": i, "pad": "x" * 5000})

        def reader():
            while time.time() < stop:
                with open(p) as f:
                    try:
                        json.load(f)
                    except ValueError:
                        bad.append(1)
        ts = [threading.Thread(target=writer, args=(i,)) for i in range(4)] + [threading.Thread(target=reader)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(bad, [])
        self.assertEqual([x for x in os.listdir(L.BASE) if x.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
