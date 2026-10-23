# Регресс-тест: снимок (SNAPSHOT) показывает ПОДТВЕРЖДЁННЫЙ план (после 2 одинаковых
# подряд чтений), а не сырое чтение этого цикла — иначе бейдж в UI и cc_avail.availability()
# мигают вслед за дребезгом Anthropic на грани подписки (найдено на acc2, 23.10.26).
# python3 -m unittest test_cc_limits_plan_debounce -v
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="ccplan_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402  (после подмены путей)
import cc_avail  # noqa: E402

USAGE = {"five_hour": {"pct": 10, "resets_at": "2099-01-01T00:00:00+00:00"},
         "seven_day": {"pct": 5, "resets_at": "2099-01-05T00:00:00+00:00"}}


class PlanDebounce(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for p in (L.PROFILES, L.BASE):
            shutil.rmtree(p, ignore_errors=True)
            os.makedirs(p)
        far = int((time.time() + 86400) * 1000)
        d = os.path.join(L.PROFILES, "acc1")
        os.makedirs(d)
        L.jsave(os.path.join(d, "credentials.json"), {"claudeAiOauth": {
            "accessToken": "tok", "refreshToken": "r-tok", "expiresAt": far}})
        L.jsave(os.path.join(d, "oauth_account.json"), {"accountUuid": "u-acc1", "emailAddress": "acc1@example.com"})
        L.LIVE_CREDS = os.path.join(TMP, "live_credentials.json")
        L.LIVE_CFG = os.path.join(TMP, "live_claude.json")
        L.jsave(L.LIVE_CREDS, {"claudeAiOauth": {"accessToken": "tok", "refreshToken": "r-tok", "expiresAt": far}})
        L.jsave(L.LIVE_CFG, {"oauthAccount": {"accountUuid": "u-acc1"}})
        L.jsave(L.CONFIG, {"threshold": 90, "weekly_cap": 99, "adaptive_poll": False})
        L.backoff_until.clear()
        L._plan_cache.clear()

    def collect_with_plan(self, plan):
        with mock.patch.object(L, "get_access", lambda n, act: "tok"), \
                mock.patch.object(L, "fetch_usage", lambda access: dict(USAGE)), \
                mock.patch.object(L, "fetch_plan", lambda n, access: plan):
            return L.collect(force=True)

    def snap_plan(self):
        return (L.jload(L.SNAPSHOT) or {}).get("accounts", {}).get("acc1", {}).get("plan")

    def test_single_flaky_reading_does_not_flip_snapshot(self):
        self.collect_with_plan("pro")
        self.assertEqual(self.snap_plan(), "pro")  # первое наблюдение фиксируется сразу

        self.collect_with_plan("free")  # один дребезг
        self.assertEqual(self.snap_plan(), "pro", "снимок не должен мигнуть на одно сырое чтение")

        self.collect_with_plan("pro")  # дребезг отменился сам
        self.assertEqual(self.snap_plan(), "pro")

    def test_two_consecutive_readings_flip_snapshot(self):
        self.collect_with_plan("pro")
        self.collect_with_plan("free")
        self.collect_with_plan("free")  # второе подряд — подтверждено
        self.assertEqual(self.snap_plan(), "free")

    def test_availability_follows_debounced_snapshot_not_raw_read(self):
        self.collect_with_plan("pro")
        snap = self.collect_with_plan("free")  # дребезг, ещё не подтверждён
        row = snap["accounts"]["acc1"]
        self.assertEqual(row["plan"], "pro")
        ok, _, why = cc_avail.availability(row, 90, 99)
        self.assertTrue(ok, "неподтверждённый free не должен блокировать доступность")
        self.assertNotEqual(why, "free")

    # (plan-vs-backoff 23.10.26) acc2 на торговой ВМ: usage сутками 403, backoff_until
    # держит стейл почти постоянно. До фикса stale_ok выходил из collect() ДО вызова
    # fetch_plan() и подставлял замороженный good[n]["plan"] — живой profile честно
    # отдавал "free", но дебаунс "2 подряд" никогда не видел этого свежего чтения и
    # сбрасывался обратно в 0 на следующем же стейл-цикле. План должен читаться
    # свежим даже под бэкоффом usage — это независимый эндпойнт.
    def collect_stale_usage_with_plan(self, plan):
        calls = {"usage": 0}

        def boom(_access):
            calls["usage"] += 1
            raise AssertionError("fetch_usage не должен вызываться во время бэкоффа usage")

        with mock.patch.object(L, "get_access", lambda n, act: "tok"), \
                mock.patch.object(L, "fetch_usage", boom), \
                mock.patch.object(L, "fetch_plan", lambda n, access: plan):
            snap = L.collect(force=True)
        self.assertEqual(calls["usage"], 0)
        return snap

    def test_plan_keeps_refreshing_during_usage_backoff(self):
        self.collect_with_plan("pro")  # удачный цикл: good["acc1"]["ts"] выставлен
        self.assertEqual(self.snap_plan(), "pro")

        L.backoff_until["acc1"] = time.time() + 1000  # как после живого 403 на usage

        self.collect_stale_usage_with_plan("free")  # первое дребезг-чтение под бэкоффом
        self.assertEqual(self.snap_plan(), "pro", "один свежий free под бэкоффом — ещё не подтверждение")

        self.collect_stale_usage_with_plan("free")  # второе подряд — под тем же бэкоффом
        self.assertEqual(self.snap_plan(), "free",
                          "план обязан подтвердиться даже когда usage всё время в бэкоффе")


if __name__ == "__main__":
    unittest.main()
