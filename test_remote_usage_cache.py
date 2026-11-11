# Скрипт лимитов на втором сервере: общий кэш и пауза после 429 (2.0.33).
# Причина: при подходе к порогу и панель cc-fleet, и защита лимитов опрашивали Anthropic каждые 30 с (по два запроса за раз) —
# Anthropic отвечал 429, и на плитке Claude PROD вместо цифр висело «лимиты не обновились · 429».
# python3 -m unittest test_remote_usage_cache -v
import io
import json
import os
import runpy
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = 1_800_000_000.0


class Net:
    """Поддельный Anthropic: считает запросы, умеет отвечать 429."""

    def __init__(self):
        self.usage = 0
        self.profile = 0
        self.mode = "ok"        # ok | 429
        self.retry_after = None
        self.pct = 40

    def __call__(self, req, timeout=0):
        url = getattr(req, "full_url", req)
        if "oauth/usage" in url:
            self.usage += 1
            if self.mode == "429":
                hdr = {"Retry-After": str(self.retry_after)} if self.retry_after is not None else {}
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdr, None)
            body = {"five_hour": {"utilization": self.pct, "resets_at": "2026-11-11T11:30:00+00:00"},
                    "seven_day": {"utilization": 9, "resets_at": "y"}}
        else:
            self.profile += 1
            body = {"account": {"has_claude_max": True}, "organization": {"subscription_created_at": "2026-11-04T11:46:15Z"}}
        return io.BytesIO(json.dumps(body).encode())


def make_home():
    home = tempfile.mkdtemp(prefix="usage_cache_")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", ".credentials.json"), "w") as f:
        json.dump({"claudeAiOauth": {"accessToken": "t", "expiresAt": int((NOW + 86400) * 1000)}}, f)
    with open(os.path.join(home, ".claude.json"), "w") as f:
        json.dump({"oauthAccount": {"emailAddress": "a@example.com"}}, f)
    return home


def run(home, net, now):
    buf = io.StringIO()
    with mock.patch.dict(os.environ, {"HOME": home}), mock.patch("urllib.request.urlopen", net), \
            mock.patch("time.time", lambda: now), redirect_stdout(buf):
        try:
            runpy.run_path(os.path.join(HERE, "remote_usage.py"), run_name="__main__")
        except SystemExit:
            pass
    return json.loads(buf.getvalue().strip().splitlines()[-1])


class SharedCache(unittest.TestCase):
    def test_second_poll_inside_ttl_does_not_touch_anthropic(self):
        home, net = make_home(), Net()
        a = run(home, net, NOW)
        b = run(home, net, NOW + 30)               # то же окно 30 с: панель и защита лимитов
        self.assertEqual((net.usage, net.profile), (1, 1))
        self.assertEqual(a["five_hour"], b["five_hour"])
        self.assertTrue(b["ok"] and not b.get("stale"))
        self.assertEqual(b["plan"], "max")

    def test_after_ttl_usage_is_asked_again_but_profile_is_not(self):
        home, net = make_home(), Net()
        run(home, net, NOW)
        net.pct = 55
        b = run(home, net, NOW + 90)
        self.assertEqual(net.usage, 2)
        self.assertEqual(net.profile, 1)           # план и дата подписки — раз в 6 часов
        self.assertEqual(b["five_hour"]["pct"], 55)
        self.assertEqual(b["plan"], "max")
        run(home, net, NOW + 6 * 3600 + 100)
        self.assertEqual(net.profile, 2)


class Throttled(unittest.TestCase):
    def test_429_returns_last_numbers_without_error_and_pauses_polling(self):
        home, net = make_home(), Net()
        run(home, net, NOW)
        net.mode, net.pct = "429", 99
        b = run(home, net, NOW + 90)               # TTL вышел → запрос → 429
        self.assertTrue(b["ok"])
        self.assertTrue(b["stale"])
        self.assertEqual(b["stale_code"], 429)
        self.assertEqual(b["five_hour"]["pct"], 40)   # последние удачные цифры, не ошибка
        self.assertNotIn("error", b)
        self.assertGreater(b["retry_at"], NOW + 90)
        self.assertEqual(net.usage, 2)
        c = run(home, net, NOW + 150)              # пауза идёт — Anthropic не трогаем
        self.assertEqual(net.usage, 2)
        self.assertTrue(c["stale"])
        net.mode, net.pct = "ok", 60
        d = run(home, net, NOW + 90 + 130)         # пауза (120 с минимум) кончилась — спрашиваем снова
        self.assertEqual(net.usage, 3)
        self.assertEqual(d["five_hour"]["pct"], 60)
        self.assertFalse(d.get("stale"))

    def test_retry_after_is_honored_and_capped(self):
        home, net = make_home(), Net()
        run(home, net, NOW)
        net.mode, net.retry_after = "429", 300
        b = run(home, net, NOW + 90)
        self.assertAlmostEqual(b["retry_at"], NOW + 90 + 300, delta=1)
        home2, net2 = make_home(), Net()
        run(home2, net2, NOW)
        net2.mode, net2.retry_after = "429", 99999
        b2 = run(home2, net2, NOW + 90)
        self.assertAlmostEqual(b2["retry_at"], NOW + 90 + 900, delta=1)       # потолок 15 минут
        net3 = Net()
        net3.mode = "429"
        home3 = make_home()
        r = run(home3, net3, NOW)                  # Retry-After нет и кэша нет: ошибка как раньше, но с паузой
        self.assertEqual((r["ok"], r["error"]), (False, "http_429"))
        run(home3, net3, NOW + 30)
        self.assertEqual(net3.usage, 1)            # в паузе второй запрос не ушёл

    def test_other_errors_are_not_hidden(self):
        home, net = make_home(), Net()
        run(home, net, NOW)

        def boom(req, timeout=0):
            raise urllib.error.HTTPError("u", 503, "x", {}, None)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": home}), mock.patch("urllib.request.urlopen", boom), \
                mock.patch("time.time", lambda: NOW + 90), redirect_stdout(buf):
            try:
                runpy.run_path(os.path.join(HERE, "remote_usage.py"), run_name="__main__")
            except SystemExit:
                pass
        res = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual((res["ok"], res["error"]), (False, "http_503"))       # 5xx не маскируем: это не лимит запросов


if __name__ == "__main__":
    unittest.main()
