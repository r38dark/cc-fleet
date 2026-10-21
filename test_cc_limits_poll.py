# Интеграционный тест опроса: python3 -m unittest test_cc_limits_poll -v
# Настоящий collect() из cc_limits.py против подставного сервера лимитов на localhost
# (нужны pyte и pexpect — как для самого cc_limits). Ни /opt/cc-limits, ни живой логин
# Claude Code не затрагиваются: BASE/PROFILES/LIVE_* уводятся во временную папку.
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

TMP = tempfile.mkdtemp(prefix="ccpoll_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402  (после подмены путей)

ACCOUNTS = {"acc1": "tokA", "acc2": "tokB", "acc3": "tokC"}


class Fake(http.server.BaseHTTPRequestHandler):
    calls = []          # [(path, токен)]
    mode = {}           # токен → ("ok", pct) | ("429", retry_after | None)

    def log_message(self, *a):
        pass

    def do_GET(self):
        tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        Fake.calls.append((self.path, tok))
        kind, arg = Fake.mode.get(tok, ("ok", 10))
        if kind == "429" and self.path.startswith("/api/oauth/usage"):
            self.send_response(429)
            if arg is not None:
                self.send_header("Retry-After", str(arg))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": {"type": "rate_limit_error", "message": "slow down"}}')
            return
        if self.path.startswith("/api/oauth/usage"):
            body = {"five_hour": {"utilization": arg, "resets_at": "2099-01-01T00:00:00+00:00"},
                    "seven_day": {"utilization": 5, "resets_at": "2099-01-05T00:00:00+00:00"}}
        else:
            body = {"account": {"has_claude_pro": True}}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)


def usage_calls(tok=None):
    return [c for c in Fake.calls if c[0].startswith("/api/oauth/usage") and (tok is None or c[1] == tok)]


class CollectPoll(unittest.TestCase):
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
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        Fake.calls.clear()
        Fake.mode = {}
        for p in (L.PROFILES, L.BASE):
            shutil.rmtree(p, ignore_errors=True)
            os.makedirs(p)
        far = int((time.time() + 86400) * 1000)
        for n, tok in ACCOUNTS.items():
            d = os.path.join(L.PROFILES, n)
            os.makedirs(d)
            L.jsave(os.path.join(d, "credentials.json"), {"claudeAiOauth": {
                "accessToken": tok, "refreshToken": "r-" + tok, "expiresAt": far}})
            L.jsave(os.path.join(d, "oauth_account.json"), {"accountUuid": "u-" + n, "emailAddress": n + "@example.com"})
        L.LIVE_CREDS = os.path.join(TMP, "live_credentials.json")
        L.LIVE_CFG = os.path.join(TMP, "live_claude.json")
        L.jsave(L.LIVE_CREDS, {"claudeAiOauth": {"accessToken": "tokA", "refreshToken": "r-tokA", "expiresAt": far}})
        L.jsave(L.LIVE_CFG, {"oauthAccount": {"accountUuid": "u-acc1"}})  # активный — acc1
        L.jsave(L.CONFIG, {"threshold": 90, "weekly_cap": 99})
        L.backoff_until.clear()
        L._plan_cache.clear()

    def state(self):
        return L.jload(L.POLL_STATE, {})

    def make_due(self, *names):
        st = self.state()
        for n in names:
            st[n]["next"] = time.time() - 1
        L.jsave(L.POLL_STATE, st)

    def fail_rows(self):
        try:
            with open(L.FAIL_LOG) as f:
                return [json.loads(x) for x in f]
        except OSError:
            return []

    # --- цикл опроса
    def _loop_wait(self):
        waits = []

        class Stop(Exception):
            pass

        class Wake:
            def wait(self, t):
                waits.append(t)
                raise Stop()

            def clear(self):
                pass
        with mock.patch.object(L, "_POLL_WAKE", Wake()), \
                mock.patch.object(L, "collect", lambda force=False, force_account=None: {}), \
                mock.patch.object(L, "switch_policy_check", lambda snap: None):
            with self.assertRaises(Stop):
                L.poll_loop()
        return waits[0]

    def test_poll_loop_sleeps_until_nearest_deadline(self):
        L.collect(force=True)
        st = self.state()
        now = time.time()
        st["acc1"]["next"], st["acc2"]["next"], st["acc3"]["next"] = now + 40, now + 500, now + 500
        L.jsave(L.POLL_STATE, st)
        self.assertTrue(38 <= self._loop_wait() <= 41)
        st["acc1"]["next"] = now + 900  # все сроки далеко — просыпаемся не реже SLEEP_MAX
        st["acc2"]["next"] = st["acc3"]["next"] = now + 900
        L.jsave(L.POLL_STATE, st)
        self.assertEqual(self._loop_wait(), 120)

    def test_poll_loop_old_pace_when_adaptive_off(self):
        L.jsave(L.CONFIG, {"adaptive_poll": False, "poll_sec": 77})
        self.assertEqual(self._loop_wait(), 77)

    # --- темп
    def test_first_collect_polls_everyone_and_sets_schedule(self):
        L.collect(force=True)
        self.assertEqual(len(usage_calls()), 3)
        st = self.state()
        self.assertEqual(set(st), set(ACCOUNTS))
        now = time.time()
        self.assertTrue(162 - 2 <= st["acc1"]["next"] - now <= 198 + 2, st["acc1"])  # активный: 180 ±10 %
        self.assertTrue(270 - 2 <= st["acc2"]["next"] - now <= 330 + 2, st["acc2"])  # запасной: 300 ±10 %
        self.assertTrue(st["acc1"]["active"] and not st["acc2"]["active"])

    def test_second_collect_makes_no_requests_and_keeps_numbers(self):
        s1 = L.collect(force=True)
        Fake.calls.clear()
        s2 = L.collect(force=True)
        self.assertEqual(usage_calls(), [])
        self.assertEqual(s2["accounts"]["acc1"]["five_hour"], s1["accounts"]["acc1"]["five_hour"])
        self.assertEqual(s2["active"], "acc1")

    def test_only_due_account_is_polled(self):
        L.collect(force=True)
        Fake.calls.clear()
        self.make_due("acc2")
        L.collect(force=True)
        self.assertEqual([c[1] for c in usage_calls()], ["tokB"])

    def test_still_numbers_slow_polling_down(self):
        L.collect(force=True)
        for _ in range(3):
            self.make_due("acc1")
            L.collect(force=True)
        self.assertEqual(self.state()["acc1"]["still"], 3)
        self.assertGreaterEqual(self.state()["acc1"]["interval"], 270)

    def test_growth_near_threshold_speeds_polling_up(self):
        Fake.mode["tokA"] = ("ok", 70)
        L.collect(force=True)
        Fake.mode["tokA"] = ("ok", 82)
        self.make_due("acc1")
        L.collect(force=True)
        st = self.state()["acc1"]
        self.assertTrue(st["near"])
        self.assertTrue(54 <= st["interval"] <= 66, st)

    def test_force_account_bypasses_schedule_but_not_min_interval(self):
        L.collect(force=True)
        Fake.calls.clear()
        L.collect(force=True, force_account="acc2")  # только что опрошен — рано
        self.assertEqual(usage_calls(), [])
        st = self.state()
        st["acc2"]["hist"] = [time.time() - 60]
        L.jsave(L.POLL_STATE, st)
        L.collect(force=True, force_account="acc2")
        self.assertEqual([c[1] for c in usage_calls()], ["tokB"])

    def test_budget_caps_requests_per_hour(self):
        L.collect(force=True)
        st = self.state()
        st["acc1"]["hist"] = [time.time() - 600 + 20 * i for i in range(25)]
        st["acc1"]["next"] = time.time() - 1
        L.jsave(L.POLL_STATE, st)
        L.collect(force=True)
        self.assertGreater(self.state()["acc1"]["interval"], 1500)

    # --- 429 и Retry-After
    def test_429_with_retry_after_is_obeyed_and_logged(self):
        L.collect(force=True)
        Fake.mode["tokA"] = ("429", 600)
        self.make_due("acc1")
        before = time.time()
        snap = L.collect(force=True)
        a = self.state()["acc1"]
        self.assertTrue(630 - 3 <= a["next"] - before <= 630 + 3, a)
        self.assertTrue(630 - 3 <= L.backoff_until["acc1"] - before <= 630 + 3)
        self.assertIn("429", snap["accounts"]["acc1"]["error"])
        self.assertIsNotNone(snap["accounts"]["acc1"].get("five_hour"))  # цифры из кэша не потеряны
        rows = self.fail_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["account"], rows[0]["stage"], rows[0]["code"], rows[0]["retry_after"]),
                         ("acc1", "usage", 429, "600"))
        self.assertIsNotNone(rows[0]["calls_1h"])
        # пока пауза — аккаунт не трогаем, даже если расписание «просрочено» и есть force_account
        Fake.calls.clear()
        self.make_due("acc1")
        L.collect(force=True, force_account="acc1")
        self.assertEqual(usage_calls("tokA"), [])

    def test_429_without_retry_after_grows(self):
        L.collect(force=True)
        Fake.mode["tokA"] = ("429", None)
        waits = []
        for _ in range(3):
            self.make_due("acc1")
            L.backoff_until.clear()
            t0 = time.time()
            L.collect(force=True)
            waits.append(round(self.state()["acc1"]["next"] - t0))
        self.assertEqual(waits, [300, 450, 675])
        self.assertEqual(self.state()["acc1"]["fails"], 3)

    def test_429_zero_retry_after_treated_as_unknown(self):
        L.collect(force=True)
        Fake.mode["tokA"] = ("429", 0)
        self.make_due("acc1")
        t0 = time.time()
        L.collect(force=True)
        self.assertTrue(297 <= self.state()["acc1"]["next"] - t0 <= 303)

    def test_recovery_resets_fail_counter(self):
        L.collect(force=True)
        Fake.mode["tokA"] = ("429", 60)
        self.make_due("acc1")
        L.collect(force=True)
        Fake.mode = {}
        L.backoff_until.clear()
        self.make_due("acc1")
        L.collect(force=True)
        self.assertEqual(self.state()["acc1"]["fails"], 0)

    def test_fail_log_has_no_secrets(self):
        L.collect(force=True)
        Fake.mode["tokA"] = ("429", 30)
        self.make_due("acc1")
        L.collect(force=True)
        with open(L.FAIL_LOG) as f:
            raw = f.read()
        self.assertNotIn("tokA", raw)
        self.assertNotIn("@example.com", raw)

    # --- выключатель
    def test_adaptive_off_keeps_old_behaviour(self):
        L.jsave(L.CONFIG, {"threshold": 90, "weekly_cap": 99, "adaptive_poll": False, "poll_sec": 120})
        L.collect(force=True)
        Fake.calls.clear()
        L.collect(force=True)
        self.assertEqual([c[1] for c in usage_calls()], ["tokA"])  # активный — каждый тик, запасные — из кэша
        self.assertFalse(os.path.exists(L.POLL_STATE))
        Fake.mode["tokA"] = ("429", 600)
        L.collect(force=True)
        self.assertTrue(235 <= L.backoff_until["acc1"] - time.time() <= 241)  # прежние 2×poll_sec, Retry-After не читаем

    def test_becoming_active_pulls_schedule_in(self):
        L.collect(force=True)
        st = self.state()
        st["acc2"]["next"] = time.time() + 550
        st["acc2"]["hist"] = [time.time() - 200]
        L.jsave(L.POLL_STATE, st)
        L.jsave(L.LIVE_CFG, {"oauthAccount": {"accountUuid": "u-acc2"}})  # переключились на acc2
        L.jsave(L.LIVE_CREDS, {"claudeAiOauth": {"accessToken": "tokB", "refreshToken": "r-tokB",
                                                 "expiresAt": int((time.time() + 86400) * 1000)}})
        Fake.calls.clear()
        L.collect(force=True)
        self.assertEqual([c[1] for c in usage_calls()], ["tokB"])  # 200 с > базы активного 180


if __name__ == "__main__":
    unittest.main()
