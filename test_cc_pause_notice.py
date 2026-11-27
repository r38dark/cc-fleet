# Сообщения о лимите не врут и не дублируются: Claude PROD свободен, а автопередача выключена — так и пишем,
# и на один эпизод — одно сообщение (пауза, «некуда» балансера, «⚠ Лимит Claude», ответ очереди).
# Ни боевая папка, ни Telegram, ни ssh не трогаются: все файлы во временной папке.
# python3 -m unittest test_cc_pause_notice -v
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

TMP0 = tempfile.mkdtemp(prefix="ccpn0_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP0, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP0, "profiles")
os.environ["CC_CODEX_PROFILES"] = os.path.join(TMP0, "cxprof")
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cc_remote as R  # noqa: E402
import pause_ctl as pc  # noqa: E402
import tg_queue as Q  # noqa: E402
import cc_limits as L  # noqa: E402

FUTURE = "2099-01-01T00:00:00+00:00"


def put(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)


class Base(unittest.TestCase):
    """Все файлы pause_ctl / cc_remote / cc_remote_auto — во временной папке; PROD свободен, автопередача выключена."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ccpn_")
        self.addCleanup(shutil.rmtree, self.d, True)
        j = lambda n: os.path.join(self.d, n)
        saved = [(R, n, getattr(R, n)) for n in ("MEMBERS_FILE", "STATE_FILE")]
        saved += [(pc, n, getattr(pc, n)) for n in ("STATE", "NOTICE_FILE", "BASE", "CONFIG", "_tg", "_log", "_threshold", "_weekly_cap")]
        saved += [(Q, "QUEUE", Q.QUEUE)]
        self.addCleanup(lambda: [setattr(o, n, v) for o, n, v in saved])
        R.MEMBERS_FILE, R.STATE_FILE = j("members.json"), j("rstate.json")
        pc.BASE = self.d
        pc.STATE, pc.NOTICE_FILE, pc.CONFIG = j("pause_state.json"), j("pause_notice.json"), j("config.json")
        Q.QUEUE = j("tg_queue.jsonl")
        pc._threshold, pc._weekly_cap = lambda: 90, lambda: 99
        self.tgs = []
        pc._tg = lambda text, force=False: self.tgs.append(text)
        pc._log = lambda m: None
        self.now = time.time()
        put(R.MEMBERS_FILE, {"prod": {"label": "Claude PROD", "host": "192.0.2.1"}})
        self.row = {"online": True, "error": "", "ts": self.now - 30,
                    "five_hour": {"pct": 0.0, "resets_at": None}, "seven_day": {"pct": 11.0, "resets_at": FUTURE}}
        put(R.STATE_FILE, {"prod": self.row})
        self.state = {"accounts": {"acc3": {"pct": 90.0, "wpct": 19.0, "ses_ok": False, "held": "сессия"}},
                      "line": "acc3 90%", "active": "acc3", "threshold": 90.0, "weekly_cap": 99.0}



class OneNotice(Base):
    def test_claim_once_per_key_and_ttl(self):
        self.assertTrue(pc.notice_claim("hard", self.now))
        self.assertFalse(pc.notice_claim("hard", self.now + 10))
        self.assertTrue(pc.notice_claim("week", self.now + 10))          # другой эпизод — своё сообщение
        self.assertTrue(pc.notice_fresh("hard", self.now + 20))
        self.assertTrue(pc.notice_claim("hard", self.now + pc.NOTICE_TTL + 1))
        pc.notice_clear()
        self.assertFalse(pc.notice_fresh("week", self.now + 20))
        self.assertTrue(pc.notice_claim("week", self.now + 20))

    def test_broken_file_does_not_silence(self):
        with open(pc.NOTICE_FILE, "w") as f:
            f.write("{не json")
        self.assertTrue(pc.notice_claim("hard", self.now))

    def _set(self, **kw):
        ls = dict(level="hard", stale=False, line="acc3 90%", why="причина", accounts={}, active="acc3")
        with mock.patch.object(pc, "level_state", return_value=ls), \
                mock.patch.object(pc, "nearest_reset", return_value=("", "")):
            return pc.cmd_set(argparse.Namespace(reason="r", resume_at="", note="", **kw))

    def test_pause_message_goes_once(self):
        self._set()
        self._set()
        self.assertEqual(len(self.tgs), 1)

    def test_pause_message_silent_after_balancer_notice(self):
        pc.notice_claim("hard")                        # балансер уже написал «⛔ … встаёт на паузу»
        self._set()
        self.assertEqual(self.tgs, [])

    def test_quiet_set_for_queue_and_wake_resets(self):
        self._set(quiet=True)
        self.assertEqual(self.tgs, [])
        self.assertFalse(pc.notice_fresh("hard"))      # тихая постановка отметку не занимает: её заменит ответ очереди
        pc.notice_claim("hard")
        pc.cmd_clear(None)                             # пауза снята — следующий эпизод снова получит сообщение
        self.assertTrue(pc.notice_claim("hard"))


class QueueAck(Base):
    def _ack(self):
        state = dict(level="hard", stale=False, line="acc3 90%", why="x", accounts={},
                     active="acc3", pause={}, nearest={})
        out = []
        with mock.patch.object(pc, "level_state", return_value=state), \
                mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))), \
                mock.patch.object(pc, "nearest_reset", return_value=("", "")):
            rc = Q.cmd_enqueue(argparse.Namespace(chat="1", msg_id="7", user="u", ts="", text_file="", notify=True))
        self.assertEqual(rc, 10)
        return out[-1]

    def setUp(self):
        super().setUp()
        saved = pc.level_state
        self.addCleanup(lambda: setattr(pc, "level_state", saved))
        sys.stdin = self.null = open(os.devnull)
        self.addCleanup(self.null.close)
        self.addCleanup(lambda: setattr(sys, "stdin", sys.__stdin__))


    def test_ack_unchanged_without_prod(self):
        put(R.MEMBERS_FILE, {})
        ack = self._ack()
        self.assertTrue(ack.startswith("Got it, queued (1 waiting). Claude is waiting for its limit reset (acc3 90%); I will be back around "), ack)




class LimitAlertHush(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(L, "cfg", return_value={"tz": "Asia/Irkutsk"})
        p.start()
        self.addCleanup(p.stop)

    ACC = {"a": {"five_hour": {"pct": 90, "resets_at": None}, "seven_day": {"pct": 19, "resets_at": None}, "plan": "pro"}}

    def test_hushed_warning_is_remembered_silently(self):
        m, st = L.claude_limit_alerts(self.ACC, {}, hush={"five_hour"})
        self.assertEqual(m, [])
        m, st = L.claude_limit_alerts(self.ACC, st)         # порог уже запомнен — позже не всплывёт
        self.assertEqual(m, [])

    def test_exhausted_and_back_are_never_hushed(self):
        acc = {"a": {"five_hour": {"pct": 100, "resets_at": None}, "seven_day": {"pct": 19, "resets_at": None}, "plan": "pro"}}
        m, st = L.claude_limit_alerts(acc, {}, hush={"five_hour", "seven_day"})
        self.assertEqual(m, ["⚠ Лимит Claude исчерпан: окно 5 ч."])
        m, st = L.claude_limit_alerts(self.ACC | {"a": dict(self.ACC["a"], five_hour={"pct": 0, "resets_at": None})}, st, hush={"five_hour"})
        self.assertEqual(len(m), 1)
        self.assertTrue(m[0].startswith("✅ Лимит Claude снова доступен"))

    def test_other_window_still_warns(self):
        acc = {"a": {"five_hour": {"pct": 90, "resets_at": None}, "seven_day": {"pct": 93, "resets_at": None}, "plan": "pro"}}
        m, _ = L.claude_limit_alerts(acc, {}, hush={"five_hour"})
        self.assertEqual(m, ["⚠ Лимит Claude: окно неделя израсходовано на 93%."])

    def test_remote_accounts_are_not_hushed(self):
        acc = {"remote:prod": {"five_hour": {"pct": 91, "resets_at": None}, "seven_day": {"pct": 1, "resets_at": None}, "plan": "pro",
                               "limit_label": "Claude PROD"}, "a": self.ACC["a"]}
        m, _ = L.claude_limit_alerts(acc, {}, hush={"five_hour"})
        self.assertEqual(m, ["⚠ Лимит Claude (Claude PROD): окно 5 ч израсходовано на 91%."])






if __name__ == "__main__":
    unittest.main()
