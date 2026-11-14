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
import cc_remote_auto as A  # noqa: E402
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
        saved = [(A, n, getattr(A, n)) for n in ("CFG_FILE", "KICK_FILE", "HB_FILE", "MODE_FILE")]
        saved += [(R, n, getattr(R, n)) for n in ("MEMBERS_FILE", "STATE_FILE")]
        saved += [(pc, n, getattr(pc, n)) for n in ("STATE", "NOTICE_FILE", "BASE", "CONFIG", "_tg", "_log", "_threshold", "_weekly_cap")]
        saved += [(Q, "QUEUE", Q.QUEUE)]
        self.addCleanup(lambda: [setattr(o, n, v) for o, n, v in saved])
        A.CFG_FILE, A.KICK_FILE, A.HB_FILE, A.MODE_FILE = j("auto.json"), j("kick.json"), j("hb.json"), j("mode.json")
        R.MEMBERS_FILE, R.STATE_FILE = j("members.json"), j("rstate.json")
        pc.BASE = self.d
        pc.STATE, pc.NOTICE_FILE, pc.CONFIG = j("pause_state.json"), j("pause_notice.json"), j("config.json")
        Q.QUEUE = j("tg_queue.jsonl")
        pc._threshold, pc._weekly_cap = lambda: 90, lambda: 99
        self.tgs = []
        pc._tg = lambda text, force=False: self.tgs.append(text)
        pc._log = lambda m: None
        self.now = time.time()
        put(A.CFG_FILE, dict(enabled=False, dry_run=False, ticks=2, cooldown=900, resume=True, sim_level="", sim_prod=""))
        put(R.MEMBERS_FILE, {"prod": {"label": "Claude PROD", "host": "192.0.2.1"}})
        self.row = {"online": True, "error": "", "ts": self.now - 30,
                    "five_hour": {"pct": 0.0, "resets_at": None}, "seven_day": {"pct": 11.0, "resets_at": FUTURE}}
        put(R.STATE_FILE, {"prod": self.row})
        put(A.HB_FILE, {"ts": self.now - 5, "last_return": 0})
        put(A.MODE_FILE, {"active": False, "stage": ""})
        self.state = {"accounts": {"acc3": {"pct": 90.0, "wpct": 19.0, "ses_ok": False, "held": "сессия"}},
                      "line": "acc3 90%", "active": "acc3", "threshold": 90.0, "weekly_cap": 99.0}

    def auto(self, **kw):
        with open(A.CFG_FILE, encoding="utf-8") as f:
            c = json.load(f)
        c.update(kw)
        put(A.CFG_FILE, c)


class ProdHint(Base):
    def test_free_prod_and_auto_off(self):
        h = pc.prod_hint(self.now)
        self.assertEqual((h["pct"], h["wpct"], h["on"], h["why"]), (0.0, 11.0, False, "автопередача выключена"))
        self.assertEqual(pc.prod_phrase(h), "Claude PROD свободен (сессия 0%, неделя 11%), но автопередача выключена")

    def test_auto_on_says_handoff_is_on(self):
        self.auto(enabled=True)
        h = pc.prod_hint(self.now)
        self.assertTrue(h["on"])
        self.assertIn("передача работы на него включена", pc.prod_phrase(h))

    def test_auto_on_but_thread_dead_or_cooling(self):
        self.auto(enabled=True)
        put(A.HB_FILE, {"ts": self.now - 500, "last_return": 0})
        self.assertEqual(pc.prod_hint(self.now)["why"], "поток автопередачи не отвечает")
        put(A.HB_FILE, {"ts": self.now - 5, "last_return": self.now - 60})
        self.assertEqual(pc.prod_hint(self.now)["why"], "рано после переключения с PROD")
        self.assertIn("передача на него не готова: рано после", pc.prod_phrase(pc.prod_hint(self.now)))

    def test_no_hint_when_prod_is_busy_stale_missing_or_work_is_there(self):
        put(R.STATE_FILE, {"prod": dict(self.row, five_hour={"pct": 95.0, "resets_at": FUTURE})})
        self.assertEqual(pc.prod_hint(self.now), {})            # PROD тоже забит — «некуда» правда
        put(R.STATE_FILE, {"prod": dict(self.row, ts=self.now - 3000)})
        self.assertEqual(pc.prod_hint(self.now), {})            # цифры устарели
        put(R.STATE_FILE, {"prod": dict(self.row, online=False)})
        self.assertEqual(pc.prod_hint(self.now), {})            # нет связи
        put(R.STATE_FILE, {"prod": self.row})
        put(os.path.join(self.d, "remote_mode.json"), {"active": True})   # pause_ctl читает его из своей BASE
        self.assertEqual(pc.prod_hint(self.now), {})            # работа уже на PROD
        put(os.path.join(self.d, "remote_mode.json"), {"active": False})
        put(R.MEMBERS_FILE, {})
        self.assertEqual(pc.prod_hint(self.now), {})            # второго сервера нет (обычная установка)

    def test_no_recursion_with_level_state(self):
        # handoff_ready() зовёт level_state(), а тот — причину паузы, то есть prod_hint(): круга быть не должно
        with mock.patch.object(A, "handoff_ready", side_effect=AssertionError("prod_hint не должна звать handoff_ready")):
            self.assertTrue(pc.prod_hint(self.now))

    def test_reasons(self):
        self.assertEqual(pc._hard_reason(self.state),
                         "аккаунты DEV выше порога сессии (acc3 90%); Claude PROD свободен (сессия 0%, неделя 11%), но автопередача выключена")
        self.state["accounts"]["acc4"] = {"pct": 10.0, "wpct": 99.0, "ses_ok": True, "held": "неделя"}
        self.assertIn("остальные аккаунты DEV не годятся: acc4 — неделя 99%; Claude PROD свободен", pc._hard_reason(self.state))
        self.assertIn("(потолок 99%), Claude PROD свободен (сессия 0%, неделя 11%)", pc._week_reason(
            dict(self.state, weekly_cap=99.0, accounts={"acc3": {"wpct": 99.0}})))

    def test_reasons_unchanged_without_prod(self):
        put(R.MEMBERS_FILE, {})
        self.assertEqual(pc._hard_reason(self.state), "все аккаунты выше порога сессии (acc3 90%), переключаться некуда")
        self.assertTrue(pc._week_reason(dict(self.state, accounts={"acc3": {"wpct": 99.0}})).endswith("переключаться некуда"))


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
                mock.patch.object(pc, "nearest_reset", return_value=("", "")), \
                mock.patch.object(pc, "_handoff_instead", return_value=(False, "")):
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
        pc.level_state = mock.Mock(return_value=dict(level="hard", stale=False, line="acc3 90%", why="x", accounts={},
                                                      active="acc3", pause={}, nearest={}))
        out = []
        with mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))), \
                mock.patch.object(pc, "nearest_reset", return_value=("", "")), \
                mock.patch.object(pc, "_handoff_instead", return_value=(False, "")), \
                mock.patch.object(pc, "handoff_pending", return_value=False):
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

    def test_ack_is_honest_and_pause_is_not_announced_twice(self):
        ack = self._ack()
        self.assertIn("Claude PROD is free (session 0%, week 11%), but auto handoff is off", ack)
        self.assertNotIn("All limit windows are burnt", ack)
        self.assertEqual(len(self.tgs), 1)             # ответ отправителю; отдельного «⏸ пауза» нет
        self.assertTrue(self.tgs[0].startswith("Got it, queued (1 waiting)"))

    def test_ack_unchanged_without_prod(self):
        put(R.MEMBERS_FILE, {})
        ack = self._ack()
        self.assertTrue(ack.startswith("Got it, queued (1 waiting). All limit windows are burnt (acc3 90%); I will be back around "), ack)


class BalancerText(unittest.TestCase):
    ACCS = {"acc3": {"five_hour": {"pct": 90.0, "resets_at": "2026-11-14T07:10:00+00:00"},
                     "seven_day": {"pct": 19.0, "resets_at": "2026-11-14T18:00:00+00:00"}, "plan": "pro"}}
    PROD = dict(label="Claude PROD", pct=0.0, wpct=11.0, on=False, why="автопередача выключена")

    def _text(self, level, prod, why="причина"):
        ls = {"level": level, "pause": {}, "why": why, "weekly_cap": 99}
        with mock.patch.object(L, "pause_state", return_value=ls), mock.patch.object(L, "_prod_hint", return_value=prod), \
                mock.patch.object(L, "cfg", return_value={"tz": "Asia/Irkutsk"}):
            return L._nowhere_text(self.ACCS, "acc3")

    def test_hard_with_free_prod_does_not_say_nowhere(self):
        why = "аккаунты DEV выше порога сессии (acc3 90%); Claude PROD свободен (сессия 0%, неделя 11%), но автопередача выключена"
        text, lvl = self._text("hard", self.PROD, why)
        self.assertEqual(lvl, "hard")
        self.assertIn("Claude PROD свободен (сессия 0%, неделя 11%), но автопередача выключена", text)
        self.assertNotIn("переключаться некуда", text)
        self.assertIn("«Работа на PROD»", text)
        self.assertIn("«Автопередача» в «Настройки PROD»", text)
        self.assertNotIn("Раньше всех освободится", text)

    def test_week_with_free_prod(self):
        text, _ = self._text("week", self.PROD)
        self.assertIn("Claude PROD свободен", text)
        self.assertNotIn("переключаться некуда", text)

    def test_without_prod_text_is_as_before(self):
        text, _ = self._text("hard", {}, "все аккаунты выше порога сессии (acc3 90%), переключаться некуда")
        self.assertIn("переключаться некуда — Claude встаёт на паузу до сброса окна.", text)
        self.assertIn("Раньше всех освободится", text)
        text, _ = self._text("week", {})
        self.assertIn("переключаться некуда — Claude встаёт на паузу", text)

    def test_handoff_on_does_not_advise_buttons(self):
        text, _ = self._text("hard", dict(self.PROD, on=True, why=""))
        self.assertNotIn("«Работа на PROD»", text)


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


class NoticeSend(unittest.TestCase):
    def test_second_notice_is_dropped_and_failure_still_sends(self):
        with mock.patch.object(L, "tg_notify", return_value=True) as tg, mock.patch.object(L, "_pause_mod") as pm:
            pm.return_value.notice_claim.side_effect = [True, False]
            self.assertTrue(L._notice_send("a", "hard"))
            self.assertFalse(L._notice_send("b", "hard"))
            self.assertEqual([c.args[0] for c in tg.call_args_list], ["a"])
            pm.side_effect = RuntimeError("нет pause_ctl")
            L._notice_send("c", "hard")
            self.assertEqual(tg.call_args_list[-1].args[0], "c")


class Banner(unittest.TestCase):
    def test_page_has_prod_free_banner_in_both_languages(self):
        page = L.PAGE
        for key in ("ccpProdTitle", "ccpProdSub", "ccpProdSes", "ccpProdWeek", "ccpProdFree"):
            self.assertEqual(page.count("  %s:" % key) + page.count(",%s:" % key), 2, key)   # ru и en
        self.assertIn("d.prod_free&&['hard','week'].includes(mode)", page)
        with open(L.__file__, encoding="utf-8") as f:
            self.assertIn('d["prod_free"] = _prod_hint()', f.read())


if __name__ == "__main__":
    unittest.main()
