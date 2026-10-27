# Регресс-тест: аккаунт, слетевший с Pro на Free (подтверждённо, 2 чтения подряд), помечается
# «неактивным» и больше НЕ опрашивается (ни usage, ни profile, ни refresh токена), пока человек не
# нажмёт «Я продлил» (collect(renew_account=…)). Anthropic отдаёт «Pro» и у неоплаченного
# аккаунта, поэтому вечный опрос только разгонял дребезг плана (27.10.26).
# python3 -m unittest test_cc_limits_lapsed -v
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="cclapsed_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402  (после подмены путей)
import cc_avail  # noqa: E402

USAGE = {"five_hour": {"pct": 10, "resets_at": "2099-01-01T00:00:00+00:00"},
         "seven_day": {"pct": 5, "resets_at": "2099-01-05T00:00:00+00:00"}}


class Lapsed(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for p in (L.PROFILES, L.BASE):
            shutil.rmtree(p, ignore_errors=True)
            os.makedirs(p)
        far = int((time.time() + 86400) * 1000)
        for n in ("acc1", "acc2"):
            d = os.path.join(L.PROFILES, n)
            os.makedirs(d)
            L.jsave(os.path.join(d, "credentials.json"), {"claudeAiOauth": {
                "accessToken": "tok-" + n, "refreshToken": "r-" + n, "expiresAt": far}})
            L.jsave(os.path.join(d, "oauth_account.json"),
                    {"accountUuid": "u-" + n, "emailAddress": n + "@example.com"})
        L.LIVE_CREDS = os.path.join(TMP, "live_credentials.json")
        L.LIVE_CFG = os.path.join(TMP, "live_claude.json")
        L.jsave(L.LIVE_CREDS, {"claudeAiOauth": {"accessToken": "tok-acc1", "refreshToken": "r-acc1", "expiresAt": far}})
        L.jsave(L.LIVE_CFG, {"oauthAccount": {"accountUuid": "u-acc1"}})
        L.jsave(L.CONFIG, {"threshold": 90, "weekly_cap": 99, "adaptive_poll": False})
        L.backoff_until.clear()
        L._plan_cache.clear()
        self.plans = {"acc1": "pro", "acc2": "pro"}
        self.calls = {"access": [], "usage": [], "plan": []}

    def collect(self, **kw):
        """Один цикл опроса; self.plans — что «отдаёт Anthropic», self.calls — к кому ходили."""
        def get_access(n, act):
            self.calls["access"].append(n)
            return "tok-" + n

        def fetch_usage(access):
            self.calls["usage"].append(access)
            return dict(USAGE)

        def fetch_plan(n, access):
            self.calls["plan"].append(n)
            return self.plans[n]

        kw.setdefault("force", True)
        with mock.patch.object(L, "get_access", get_access), \
                mock.patch.object(L, "fetch_usage", fetch_usage), \
                mock.patch.object(L, "fetch_plan", fetch_plan), \
                mock.patch.object(L, "tg_notify", lambda *a, **k: self.notes.append(a[0])):
            return L.collect(**kw)

    notes = []

    def setUpNotes(self):
        self.notes = []

    def drop_to_free(self, n="acc2"):
        """Pro подтверждён, затем 2 чтения Free подряд → слёт."""
        self.notes = []
        self.collect()
        self.plans[n] = "free"
        self.collect()  # первое Free — ещё дребезг
        snap = self.collect()  # второе подряд — подтверждено
        return snap

    def reset_calls(self):
        for k in self.calls:
            self.calls[k] = []

    def test_confirmed_drop_marks_account_lapsed(self):
        snap = self.drop_to_free()
        row = snap["accounts"]["acc2"]
        self.assertTrue(row.get("lapsed"))
        self.assertTrue(row.get("lapsed_since"))
        self.assertEqual(row["plan"], "free")
        self.assertFalse(snap["accounts"]["acc1"].get("lapsed"))
        self.assertIn("acc2", (L.jload(L.STATE) or {}).get("lapsed", {}))
        self.assertTrue(any("слетел с Pro" in m and "опрос остановлен" in m for m in self.notes), self.notes)

    def test_single_flaky_free_does_not_lapse(self):
        self.collect()
        self.plans["acc2"] = "free"
        snap = self.collect()  # одно чтение
        self.assertFalse(snap["accounts"]["acc2"].get("lapsed"))
        self.plans["acc2"] = "pro"
        snap = self.collect()
        self.assertFalse(snap["accounts"]["acc2"].get("lapsed"))
        self.assertNotIn("lapsed", L.jload(L.STATE) or {})

    def test_lapsed_account_is_not_polled_at_all(self):
        self.drop_to_free()
        self.reset_calls()
        for _ in range(3):
            self.collect()
        self.assertNotIn("acc2", self.calls["access"], "refresh токена слетевшего не нужен")
        self.assertNotIn("acc2", self.calls["plan"], "profile слетевшего не нужен")
        self.assertNotIn("tok-acc2", self.calls["usage"], "usage слетевшего не нужен")
        self.assertIn("acc1", self.calls["plan"], "остальные аккаунты опрашиваются как прежде")

    def test_force_account_and_refresh_do_not_wake_lapsed(self):
        self.drop_to_free()
        self.reset_calls()
        snap = self.collect(force_account="acc2")  # «Обновить» в панели / перелогин
        self.assertTrue(snap["accounts"]["acc2"].get("lapsed"))
        self.assertNotIn("acc2", self.calls["plan"])
        self.assertNotIn("tok-acc2", self.calls["usage"])

    def test_lapsed_row_keeps_last_known_usage_as_stale(self):
        self.drop_to_free()
        row = self.collect()["accounts"]["acc2"]
        self.assertEqual((row.get("five_hour") or {}).get("pct"), 10)
        self.assertTrue(row.get("stale_ts"))
        self.assertFalse(row.get("error"))

    def test_lapsed_account_is_unavailable_for_rotation(self):
        row = self.drop_to_free()["accounts"]["acc2"]
        ok, _, why = cc_avail.availability(row, 90, 99)
        self.assertFalse(ok)
        self.assertEqual(why, "free")

    def test_renew_click_wakes_account_and_accepts_pro_at_once(self):
        self.drop_to_free()
        self.plans["acc2"] = "pro"  # человек оплатил, Anthropic обновился
        self.reset_calls()
        self.notes = []
        snap = self.collect(force_account="acc2", renew_account="acc2")
        row = snap["accounts"]["acc2"]
        self.assertIn("acc2", self.calls["plan"], "после «Я продлил» опрос идёт")
        self.assertEqual(row["plan"], "pro", "Pro принимается сразу, без второго чтения")
        self.assertFalse(row.get("lapsed"))
        self.assertNotIn("lapsed", L.jload(L.STATE) or {})
        self.assertTrue(any("снова PRO" in m for m in self.notes), self.notes)
        # дальше — обычная работа: аккаунт опрашивается в каждом цикле
        self.reset_calls()
        self.collect()
        self.assertIn("acc2", self.calls["plan"])

    def test_renew_click_while_still_free_stays_lapsed(self):
        self.drop_to_free()
        self.reset_calls()
        snap = self.collect(force_account="acc2", renew_account="acc2")  # оплата ещё не прошла
        self.assertIn("acc2", self.calls["plan"], "один контрольный опрос по клику всё же идёт")
        self.assertTrue(snap["accounts"]["acc2"].get("lapsed"))
        self.reset_calls()
        self.collect()
        self.assertNotIn("acc2", self.calls["plan"], "и снова стоп до следующего клика")

    def test_account_already_free_is_latched_on_first_cycle(self):
        # acc2 был Free ещё до появления отметки (state.json["plans"]) — после обновления сразу стоп
        L.jsave(L.STATE, {"plans": {"acc1": "pro", "acc2": "free"}})
        self.plans["acc2"] = "free"
        snap = self.collect()
        self.assertTrue(snap["accounts"]["acc2"].get("lapsed"))
        self.reset_calls()
        self.collect()
        self.assertNotIn("acc2", self.calls["plan"])

    def test_deleted_account_drops_lapsed_mark(self):
        self.drop_to_free()
        shutil.rmtree(os.path.join(L.PROFILES, "acc2"))
        self.collect()
        self.assertNotIn("lapsed", L.jload(L.STATE) or {})


if __name__ == "__main__":
    unittest.main()
