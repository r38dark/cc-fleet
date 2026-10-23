# Регресс-тест: прогноз обвала Pro→Free (_renewal_next) не должен навечно
# застревать в прошлом, если подписка продлилась тихо, без видимого провала
# в Free (анкор confirmed_ts не обновился) — иначе чип на странице вечно
# показывает "ждём сегодня" (найдено на acc2, 23.10.26).
# python3 -m unittest test_cc_limits_renewal_stale -v
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

TMP = tempfile.mkdtemp(prefix="ccrenew_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402  (после подмены путей)


class RenewalStale(unittest.TestCase):
    def test_future_anchor_unchanged(self):
        confirmed = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp()
        nxt = datetime.fromisoformat(L._renewal_next(confirmed))
        self.assertGreater(nxt, datetime.now(timezone.utc))
        self.assertLess(nxt, datetime.now(timezone.utc) + timedelta(days=28))

    def test_one_cycle_overdue_rolls_to_future(self):
        # якорь — ~1.3 месяца назад: наивный anchor+1мес уже в прошлом
        confirmed = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
        nxt = datetime.fromisoformat(L._renewal_next(confirmed))
        self.assertGreater(nxt, datetime.now(timezone.utc), "не должно виснуть в прошлом")

    def test_many_cycles_overdue_rolls_to_future(self):
        # якорь не обновлялся МЕСЯЦАМИ (например, забытый тестовый аккаунт) —
        # всё равно должен докрутиться до ближайшей будущей даты, не зависать
        confirmed = (datetime.now(timezone.utc) - timedelta(days=200)).timestamp()
        nxt = datetime.fromisoformat(L._renewal_next(confirmed))
        now = datetime.now(timezone.utc)
        self.assertGreater(nxt, now)
        self.assertLess(nxt, now + timedelta(days=32))


if __name__ == "__main__":
    unittest.main()
