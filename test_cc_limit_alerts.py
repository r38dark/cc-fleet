# [notion-ai] Сообщения о лимитах Claude в формате Codex: python3 -m unittest test_cc_limit_alerts -v
import os, sys, tempfile, unittest
from unittest import mock
TMP0 = tempfile.mkdtemp(prefix="cclim0_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP0, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP0, "profiles")
os.environ["CC_CODEX_PROFILES"] = os.path.join(TMP0, "cxprof")
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_limits as L  # noqa: E402
assert L.BASE.startswith(tempfile.gettempdir()), L.BASE


def acc(fh=None, sd=None, sd_reset="2026-11-05T18:00:00+00:00", **kw):
    r = {"five_hour": {"pct": fh, "resets_at": None}, "seven_day": {"pct": sd, "resets_at": sd_reset}, "plan": "pro"}
    r.update(kw); return r


class TestAlerts(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(L, "cfg", return_value={"tz": "Asia/Irkutsk"}); p.start(); self.addCleanup(p.stop)

    def test_warn_full_back_once(self):
        st = {}
        m, st = L.claude_limit_alerts({"a": acc(50, 92)}, st)
        self.assertEqual(m, ["⚠ Лимит Claude: окно неделя израсходовано на 92%. Сбросится в 06.11 02:00."])
        m, st = L.claude_limit_alerts({"a": acc(50, 95)}, st); self.assertEqual(m, [])  # тот же порог — тишина
        m, st = L.claude_limit_alerts({"a": acc(50, 100)}, st)
        self.assertEqual(m, ["⚠ Лимит Claude исчерпан: окно неделя. Сбросится в 06.11 02:00."])
        m, st = L.claude_limit_alerts({"a": acc(50, 100)}, st); self.assertEqual(m, [])
        m, st = L.claude_limit_alerts({"a": acc(0, 0)}, st)
        self.assertEqual(m, ["✅ Лимит Claude снова доступен: окно неделя, занято 0%."])
        m, st = L.claude_limit_alerts({"a": acc(0, 91)}, st)
        self.assertEqual(len(m), 1)  # после сброса порог снова взведён

    def test_hysteresis_and_session(self):
        st = {}
        m, st = L.claude_limit_alerts({"a": acc(90, 10)}, st)
        self.assertEqual(m, ["⚠ Лимит Claude: окно 5 ч израсходовано на 90%."])
        m, st = L.claude_limit_alerts({"a": acc(85, 10)}, st); self.assertEqual(m, [])
        m, st = L.claude_limit_alerts({"a": acc(91, 10)}, st); self.assertEqual(m, [])  # 85↔91 не шлёт по кругу
        m, st = L.claude_limit_alerts({"a": acc(5, 10)}, st); self.assertEqual(m, [])   # 90→5 — молча
        m, st = L.claude_limit_alerts({"a": acc(90, 10)}, st); self.assertEqual(len(m), 1)

    def test_names_errors_free(self):
        st = {}
        m, st = L.claude_limit_alerts({"a": acc(100, 10), "b": acc(10, 10)}, st)
        self.assertEqual(m, ["⚠ Лимит Claude (a) исчерпан: окно 5 ч."])
        m, st = L.claude_limit_alerts({"a": acc(None, None, error="429"), "b": acc(10, 10)}, st)
        self.assertEqual(m, []); self.assertEqual(st["a"]["five_hour"], 100)  # ошибка чтения — состояние не трогаем
        m, st = L.claude_limit_alerts({"a": acc(100, 100, plan="free")}, st); self.assertEqual(m, [])
        m, st = L.claude_limit_alerts({"b": acc(10, 10)}, st); self.assertNotIn("a", st)  # удалённый аккаунт забыт

    def test_tick_first_run_silent(self):
        sent = []
        with mock.patch.object(L, "tg_notify", sent.append):
            L._claude_limit_tick({"accounts": {"a": acc(0, 100)}})
            self.assertEqual(sent, [])  # первый запуск — молча запоминаем
            L._claude_limit_tick({"accounts": {"a": acc(0, 100)}})
            L._claude_limit_tick({"accounts": {"a": acc(3, 0)}})
        self.assertEqual(sent, ["✅ Лимит Claude снова доступен: окно неделя, занято 0%."])
        with mock.patch.object(L, "cfg", return_value={"limit_alerts": False}), mock.patch.object(L, "tg_notify", sent.append):
            L._claude_limit_tick({"accounts": {"a": acc(100, 100)}})
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
