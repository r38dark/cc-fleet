# Тесты правил темпа опроса: python3 -m unittest test_cc_poll -v  (pytest не нужен)
import unittest

import cc_poll as P

NOW = 1_800_000_000.0
D = P.DEFAULTS


class RetryAfter(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(P.parse_retry_after("120"), 120.0)
        self.assertEqual(P.parse_retry_after(" 7 "), 7.0)

    def test_http_date(self):
        # 1_800_000_000 = Sun, 15 Jan 2027 08:00:00 GMT
        self.assertEqual(P.parse_retry_after("Fri, 15 Jan 2027 08:01:00 GMT", NOW), 60.0)
        self.assertEqual(P.parse_retry_after("Fri, 15 Jan 2027 07:00:00 GMT", NOW), 0.0)  # дата в прошлом

    def test_garbage(self):
        for v in (None, "", "abc", "-5", "nan", "inf"):
            self.assertIsNone(P.parse_retry_after(v), v)


class Backoff(unittest.TestCase):
    def test_retry_after_wins(self):
        self.assertEqual(P.backoff_seconds(600, 1), 630)

    def test_retry_after_capped_at_hour(self):
        self.assertEqual(P.backoff_seconds(99999, 1), 3600 + D["ra_slack"])

    def test_zero_or_missing_grows(self):
        # Retry-After: 0 приходит с edge — это не «ждать 0 секунд»
        self.assertEqual(P.backoff_seconds(0, 1), 300)
        self.assertEqual(P.backoff_seconds(None, 2), 450)
        self.assertEqual(P.backoff_seconds(None, 3), 675)
        self.assertEqual(P.backoff_seconds(None, 99), 1800)


class Budget(unittest.TestCase):
    def test_under_budget(self):
        self.assertEqual(P.budget_wait([NOW - 10 * i for i in range(19)], NOW, 20), 0.0)

    def test_at_budget_waits_for_oldest(self):
        hist = [NOW - 3500 + 10 * i for i in range(20)]  # самый старый вышел бы из окна через 100 с
        self.assertAlmostEqual(P.budget_wait(hist, NOW, 20), 101.0)

    def test_old_requests_ignored(self):
        self.assertEqual(P.budget_wait([NOW - 4000] * 50, NOW, 20), 0.0)


class Interval(unittest.TestCase):
    def test_active_base_and_idle_growth(self):
        kw = dict(is_active=True, near=False, reset_in=None, p=D)
        self.assertEqual(P.interval(still=0, **kw), 180)
        self.assertEqual(P.interval(still=1, **kw), 220)
        self.assertEqual(P.interval(still=3, **kw), 300)
        self.assertEqual(P.interval(still=9, **kw), 300)  # дальше потолка не растёт

    def test_spare_slower_than_active(self):
        kw = dict(near=False, reset_in=None, p=D, still=3)
        self.assertEqual(P.interval(is_active=False, **kw), 600)
        self.assertEqual(P.interval(is_active=False, near=False, reset_in=None, p=D, still=0), 300)

    def test_near_threshold_is_fast(self):
        self.assertEqual(P.interval(is_active=True, still=0, near=True, reset_in=None, p=D), 60)

    def test_jitter_bounds(self):
        kw = dict(is_active=True, still=0, near=False, reset_in=None, p=D)
        self.assertAlmostEqual(P.interval(unit=0.0, **kw), 162)
        self.assertAlmostEqual(P.interval(unit=1.0, **kw), 198)

    def test_wakes_right_after_reset(self):
        # окно сбросится через 40 с: просыпаемся в reset + слэк, а не через 180
        self.assertAlmostEqual(P.interval(is_active=True, still=0, near=False, reset_in=40, p=D), 55)

    def test_reset_far_does_not_shorten(self):
        self.assertEqual(P.interval(is_active=True, still=0, near=False, reset_in=7200, p=D), 180)

    def test_never_below_min(self):
        self.assertEqual(P.interval(is_active=True, still=0, near=False, reset_in=0, p=D), D["min_interval"])


class AfterPoll(unittest.TestCase):
    LIM = (90, 99)

    def poll(self, st, now, pcts, **kw):
        kw.setdefault("is_active", True)
        return P.after_poll(st, now, ok=True, pcts=pcts, limits=self.LIM, **kw)

    def test_first_poll_is_base(self):
        st = self.poll(None, NOW, (10, 20))
        self.assertEqual(st["still"], 0)
        self.assertEqual(st["interval"], 180)
        self.assertEqual(st["next"], NOW + 180)

    def test_still_grows_interval(self):
        st = self.poll(None, NOW, (10, 20))
        for i in range(1, 4):
            st = self.poll(st, NOW + 200 * i, (10.4, 20.2))  # Δ<1 пп — без движения
        self.assertEqual(st["still"], 3)
        self.assertEqual(st["interval"], 300)

    def test_movement_resets_idle(self):
        st = self.poll(None, NOW, (10, 20))
        st = self.poll(st, NOW + 300, (10, 20))
        st = self.poll(st, NOW + 600, (13, 20))
        self.assertEqual(st["still"], 0)
        self.assertEqual(st["interval"], 180)

    def test_near_threshold_when_growing(self):
        st = self.poll(None, NOW, (70, 20))
        st = self.poll(st, NOW + 180, (80, 20))  # 80 → порог 90: 10 пп < 15 и растёт
        self.assertTrue(st["near"])
        self.assertEqual(st["interval"], 60)

    def test_close_to_threshold_but_not_growing_is_calm(self):
        st = self.poll(None, NOW, (85, 20))
        st = self.poll(st, NOW + 180, (85, 20))
        self.assertFalse(st["near"])

    def test_far_from_threshold_is_calm_even_growing(self):
        st = self.poll(None, NOW, (10, 20))
        st = self.poll(st, NOW + 180, (30, 20))
        self.assertFalse(st["near"])

    def test_week_cap_counts_too(self):
        st = self.poll(None, NOW, (10, 80))
        st = self.poll(st, NOW + 180, (10, 90))  # неделя к потолку 99: 9 пп и растёт
        self.assertTrue(st["near"])

    def test_dead_account_is_not_near(self):
        st = self.poll(None, NOW, (98, 20))
        st = self.poll(st, NOW + 60, (100, 20))
        self.assertFalse(st["near"])

    def test_budget_overrides_near_poll(self):
        # 20 запросов за последние 19 минут → следующий не раньше, чем освободится слот в часовом окне
        st = {"hist": [NOW - 1140 + 60 * i for i in range(20)], "pct": [80, 20]}
        st = self.poll(st, NOW, (85, 20))
        self.assertTrue(st["near"])
        self.assertGreater(st["interval"], 60)
        # в окне теперь 21 запрос (20 + этот): следующий — когда выйдут два старейших, т.е. второй (NOW-1080) через 2520 с
        self.assertAlmostEqual(st["interval"], 2521, delta=1)

    def test_hist_pruned(self):
        st = self.poll({"hist": [NOW - 5000, NOW - 100]}, NOW, (10, 20))
        self.assertEqual(st["hist"], [NOW - 100, NOW])

    def test_429_waits_retry_after_and_counts_fail(self):
        w = P.backoff_seconds(600, 1)
        st = P.after_poll({"pct": [10, 20]}, NOW, ok=False, wait429=w, is_active=True, limits=self.LIM)
        self.assertEqual(st["fails"], 1)
        self.assertEqual(st["interval"], 630)
        self.assertEqual(st["pct"], [10, 20])  # старые цифры сохранены
        self.assertEqual(len(st["hist"]), 1)  # неудачная попытка тоже в бюджете

    def test_success_clears_fails(self):
        st = P.after_poll({"fails": 3}, NOW, ok=True, pcts=(1, 1), is_active=True, limits=self.LIM)
        self.assertEqual(st["fails"], 0)

    def test_429_from_profile_with_ok_usage_still_counts(self):
        st = P.after_poll({"fails": 1}, NOW, ok=True, pcts=(1, 1), wait429=450, is_active=True, limits=self.LIM)
        self.assertEqual(st["fails"], 2)
        self.assertEqual(st["interval"], 450)

    def test_other_error_uses_normal_interval(self):
        st = P.after_poll({"pct": [10, 20], "still": 2}, NOW, ok=False, is_active=True, limits=self.LIM)
        self.assertEqual(st["fails"], 0)
        self.assertEqual(st["still"], 2)
        self.assertEqual(st["interval"], 260)

    def test_none_pcts_do_not_crash(self):
        st = self.poll(None, NOW, (None, None))
        st = self.poll(st, NOW + 180, (None, 5))
        self.assertEqual(st["still"], 1)


class Scheduling(unittest.TestCase):
    def test_due(self):
        self.assertTrue(P.due(None, NOW))
        self.assertTrue(P.due({}, NOW))
        self.assertFalse(P.due({"next": NOW + 10}, NOW))
        self.assertTrue(P.due({"next": NOW - 1}, NOW))

    def test_sleep_bounds(self):
        self.assertEqual(P.sleep_for({}, NOW), P.SLEEP_MAX)
        self.assertEqual(P.sleep_for({"a": {"next": NOW + 1}}, NOW), P.SLEEP_MIN)
        self.assertEqual(P.sleep_for({"a": {"next": NOW + 40}, "b": {"next": NOW + 900}}, NOW), 40)
        self.assertEqual(P.sleep_for({"a": {"next": NOW + 900}}, NOW), P.SLEEP_MAX)


class Retarget(unittest.TestCase):
    def test_new_active_gets_active_cadence(self):
        st = {"active": False, "next": NOW + 500, "hist": [NOW - 100]}
        self.assertEqual(P.retarget(st, True)["next"], NOW - 100 + 180)

    def test_still_spare_untouched(self):
        st = {"active": False, "next": NOW + 500, "hist": [NOW - 100]}
        self.assertIs(P.retarget(st, False), st)

    def test_already_active_untouched(self):
        st = {"active": True, "next": NOW + 500, "hist": [NOW - 100]}
        self.assertIs(P.retarget(st, True), st)

    def test_backoff_not_shortened(self):
        st = {"active": False, "next": NOW + 900, "fails": 2, "hist": [NOW - 100]}
        self.assertIs(P.retarget(st, True), st)


class Config(unittest.TestCase):
    def test_enabled(self):
        self.assertTrue(P.enabled({}))
        self.assertTrue(P.enabled({"adaptive_poll": True}))
        self.assertFalse(P.enabled({"adaptive_poll": False}))
        self.assertFalse(P.enabled({"adaptive_poll": {"enabled": False}}))
        self.assertTrue(P.enabled({"adaptive_poll": {"base_active": 200}}))

    def test_old_poll_sec_120_does_not_lower_base(self):
        self.assertEqual(P.params({"poll_sec": 120})["base_active"], 180)

    def test_slow_poll_sec_is_respected(self):
        p = P.params({"poll_sec": 600})
        self.assertEqual(p["base_active"], 600)
        self.assertGreaterEqual(p["idle_active"], 600)

    def test_slow_inactive_poll_sec_is_respected(self):
        p = P.params({"inactive_poll_sec": 900})
        self.assertEqual(p["base_spare"], 900)
        self.assertGreaterEqual(p["idle_spare"], 900)
        self.assertEqual(P.params({"inactive_poll_sec": 300})["base_spare"], 300)

    def test_overrides_ignore_garbage(self):
        p = P.params({"adaptive_poll": {"base_active": 240, "near_poll": "x", "jitter": -1, "zzz": 5}})
        self.assertEqual(p["base_active"], 240)
        self.assertEqual(p["near_poll"], 60)
        self.assertEqual(p["jitter"], 0.10)
        self.assertNotIn("zzz", p)


if __name__ == "__main__":
    unittest.main()
