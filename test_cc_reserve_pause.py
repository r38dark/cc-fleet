# Пауза резерва: резерв включён галочкой вручную → Claude отключён (аккаунты не тратятся), входящие ждут в очереди,
# снятие галочки — Claude просыпается. Ни Telegram, ни настоящий screen, ни боевая папка не трогаются.
# python3 -m unittest test_cc_reserve_pause -v
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pause_ctl as pc  # noqa: E402


def put(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)


def get(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ccrp_")
        self.addCleanup(shutil.rmtree, self.d, True)
        for n in ("pause_ctl.py", "limits_gate.py", "tg_queue.py", "cc_avail.py"):  # пакет в чистой папке: скрипты берут пути от неё
            shutil.copy(os.path.join(HERE, n), self.d)
        os.makedirs(os.path.join(self.d, "hooks"))
        shutil.copy(os.path.join(HERE, "hooks", "pause_tool_gate.py"), os.path.join(self.d, "hooks"))
        self.saved = (pc.BASE, pc.STATE, pc.SNAP, pc.CONFIG, pc.CC_STATE, pc.GATE, pc._wake_session, pc._tg, pc._log)
        pc.BASE = self.d
        pc.STATE, pc.SNAP, pc.CONFIG = (os.path.join(self.d, n) for n in ("pause_state.json", "snapshot.json", "config.json"))
        pc.CC_STATE = os.path.join(self.d, "state.json")
        pc.GATE = os.path.join(self.d, "limits_gate.py")
        self.wakes, self.tgs = [], []
        pc._wake_session = self.wakes.append  # настоящий screen не дёргаем
        pc._tg = lambda text, force=False: self.tgs.append(text)
        pc._log = lambda m: None
        self.addCleanup(self.restore)

    def restore(self):
        (pc.BASE, pc.STATE, pc.SNAP, pc.CONFIG, pc.CC_STATE, pc.GATE, pc._wake_session, pc._tg, pc._log) = self.saved

    def env(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith("CC_LIMITS")}
        e.update(CC_LIMITS_BASE=self.d, CC_LIMITS_DIR=self.d, CLAUDE_CONFIG_DIR=os.path.join(self.d, "claude"))
        return e

    def run_py(self, script, *args, stdin=""):
        return subprocess.run([sys.executable, "-I", os.path.join(self.d, script), *args], input=stdin, text=True,
                              capture_output=True, timeout=60, env=self.env(), cwd=self.d)


class HoldRelease(Base):
    def test_hold_pauses_without_alarm(self):
        self.assertTrue(pc.reserve_hold("резерв: тест"))
        st = pc.load()
        self.assertTrue(st["active"])
        self.assertEqual((st["kind"], st["resume_at"], st["reason"]), ("reserve", 0, "резерв: тест"))
        self.assertEqual(pc.level_state()["pause"]["kind"], "reserve")

    def test_hold_is_idempotent(self):
        pc.reserve_hold("a")
        since = pc.load()["since"]
        time.sleep(0.01)
        pc.reserve_hold("b")
        st = pc.load()
        self.assertEqual((st["since"], st["reason"]), (since, "a"))  # повторно не переставляется

    def test_hold_overwrites_limits_pause_and_manual_override(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 60,
                       "override": True})
        pc.reserve_hold("резерв")
        st = pc.load()
        self.assertEqual((st["kind"], st["resume_at"], bool(st.get("override"))), ("reserve", 0, False))

    def test_release_lifts_pause_and_wakes_session_once(self):
        pc.reserve_hold("резерв")
        self.assertTrue(pc.reserve_release())
        self.assertFalse(pc.load()["active"])
        self.assertEqual(len(self.wakes), 1)
        self.assertIn("Reserve mode is off", self.wakes[0])
        self.assertFalse(pc.reserve_release())  # повтор каждый такт ничего не будит
        self.assertEqual(len(self.wakes), 1)

    def test_release_never_touches_limits_pause(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 60})
        self.assertFalse(pc.reserve_release())
        self.assertTrue(pc.load()["active"])
        self.assertEqual(self.wakes, [])

    def test_alarm_cron_does_not_lift_reserve_pause(self):
        pc.reserve_hold("резерв")
        for if_due in (True, False):
            self.assertEqual(pc.cmd_wake(argparse.Namespace(if_due=if_due)), 0)
            self.assertTrue(pc.load()["active"])
        self.assertEqual(self.wakes, [])

    def test_emergency_exit_button_then_release_does_not_wake_twice(self):
        pc.reserve_hold("резерв")
        pc.cmd_off(argparse.Namespace(by="тест"))  # кнопка «Отключить паузу»
        st = pc.load()
        self.assertEqual((st["active"], st["override"]), (False, True))
        self.assertEqual(len(self.wakes), 1)
        self.assertFalse(pc.reserve_release())  # потом снятая галочка: будить уже некого
        self.assertEqual(len(self.wakes), 1)

    def test_queue_is_announced_in_wake_text(self):
        # входящие, что копились на паузе, не теряются: пробуждение называет команду разбора
        pc._wake_session = self.restore_wake = self.saved[6]
        calls = []
        orig_run = subprocess.run
        subprocess.run = lambda *a, **k: calls.append(a[0]) or subprocess.CompletedProcess(a[0], 0, "", "")
        self.addCleanup(setattr, subprocess, "run", orig_run)
        orig_sleep = time.sleep
        time.sleep = lambda s: None
        self.addCleanup(setattr, time, "sleep", orig_sleep)
        pc._queued = lambda: 2
        self.addCleanup(delattr, pc, "_queued")
        pc.reserve_hold("резерв")
        pc.reserve_release()
        text = [c[-1] for c in calls if c[:2] == ["screen", "-S"] and "-X" in c and "stuff" in c and len(c[-1]) > 2]
        self.assertTrue(any("2 incoming message(s)" in t and "tg_queue.py" in t for t in text), calls)


class Gate(Base):
    def test_background_gate_closed_while_reserve_pause_stands(self):
        pc.reserve_hold("резерв")
        r = self.run_py("limits_gate.py")
        self.assertEqual(r.returncode, 10, r.stdout + r.stderr)
        self.assertIn("резерв", r.stdout)

    def test_gate_open_after_release(self):
        pc.reserve_hold("резерв")
        pc.reserve_release()
        self.assertEqual(self.run_py("limits_gate.py").returncode, 0)

    def test_gate_open_after_emergency_exit_button(self):
        pc.reserve_hold("резерв")
        pc.cmd_off(argparse.Namespace(by="тест"))
        self.assertEqual(self.run_py("limits_gate.py").returncode, 0)

    def test_limits_pause_does_not_close_gate_by_itself(self):
        put(pc.STATE, {"active": True, "since": 1, "kind": "session", "resume_at": time.time() + 60})
        self.assertEqual(self.run_py("limits_gate.py").returncode, 0)  # без снимка гейт пропускает — как и раньше


class ToolHook(Base):
    def call(self, tool="Bash", cmd="ls"):
        r = self.run_py("hooks/pause_tool_gate.py", stdin=json.dumps({"tool_name": tool, "tool_input": {"command": cmd}}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_no_pause_passes(self):
        self.assertIsNone(self.call())

    def test_reserve_denies_first_call_with_grace_then_passes_then_denies(self):
        pc.reserve_hold("резерв")
        first = self.call()
        self.assertEqual(first["permissionDecision"], "deny")
        self.assertIn("Включён резерв", first["permissionDecisionReason"])
        self.assertIn("снять галочку", first["permissionDecisionReason"])  # человек знает, как вернуть Claude
        self.assertIn("120 с", first["permissionDecisionReason"])
        self.assertIsNone(self.call())  # в пределах GRACE дали довести начатое
        mark = os.path.join(self.d, "pause_tool_gate.json")
        m = get(mark)
        m["notice_ts"] = time.time() - 500
        put(mark, m)
        late = self.call()
        self.assertEqual(late["permissionDecision"], "deny")
        self.assertIn("Включён резерв (Codex", late["permissionDecisionReason"])
        self.assertIn("заблокированы", late["permissionDecisionReason"])

    def test_reserve_pause_has_no_alarm_so_it_is_never_treated_as_overdue(self):
        pc.reserve_hold("резерв")
        self.call()
        mark = os.path.join(self.d, "pause_tool_gate.json")
        m = get(mark)
        m["notice_ts"] = time.time() - 500
        put(mark, m)
        self.assertEqual(self.call()["permissionDecision"], "deny")  # resume_at=0 не «будильник просрочен»

    def test_pause_commands_always_allowed_as_exit(self):
        pc.reserve_hold("резерв")
        self.assertIsNone(self.call(cmd="python3 /opt/cc-limits/pause_ctl.py off"))

    def test_manual_override_button_lets_everything_through(self):
        pc.reserve_hold("резерв")
        pc.cmd_off(argparse.Namespace(by="тест"))
        self.assertIsNone(self.call())

    def test_released_pause_passes(self):
        pc.reserve_hold("резерв")
        pc.reserve_release()
        self.assertIsNone(self.call())


class GraceForBanner(Base):
    """Баннер паузы резерва показывает отсчёт «Claude доделывает начатое»: его начало знает только хук (первый отказ инструмента)."""

    def test_grace_equals_the_hook_constant(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ptg", os.path.join(HERE, "hooks", "pause_tool_gate.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(pc.RESERVE_GRACE, m.GRACE)

    def test_no_refusal_yet_means_no_countdown_start(self):
        pc.reserve_hold("резерв")
        p = pc.level_state()["pause"]
        self.assertEqual((p["notice_ts"], p["grace"]), (0, pc.RESERVE_GRACE))

    def test_first_hook_refusal_starts_the_countdown(self):
        pc.reserve_hold("резерв")
        r = self.run_py("hooks/pause_tool_gate.py", stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertEqual(r.returncode, 0, r.stderr)
        mark = get(os.path.join(self.d, "pause_tool_gate.json"))
        p = pc.level_state()["pause"]
        self.assertEqual(p["notice_ts"], mark["notice_ts"])
        self.assertGreater(p["notice_ts"], 0)

    def test_mark_of_an_older_pause_is_not_used(self):
        pc.reserve_hold("резерв")
        put(os.path.join(self.d, "pause_tool_gate.json"), {"since": 12345.0, "notice_ts": time.time()})
        self.assertEqual(pc.level_state()["pause"]["notice_ts"], 0)  # отметка от прошлой паузы — отсчёт не наш

    def test_limits_pause_has_no_grace_fields(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 60})
        p = pc.level_state()["pause"]
        self.assertNotIn("notice_ts", p)
        self.assertNotIn("grace", p)

    def test_broken_mark_file_does_not_break_state(self):
        pc.reserve_hold("резерв")
        with open(os.path.join(self.d, "pause_tool_gate.json"), "w") as f:
            f.write("{не json")
        self.assertEqual(pc.level_state()["pause"]["notice_ts"], 0)


class Queue(Base):
    def enqueue(self, text="привет"):
        f = os.path.join(self.d, "m.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.run_py("tg_queue.py", "enqueue", "--chat", "1", "--msg-id", "7", "--user", "u", "--text-file", f,
                           "--no-notify")

    def test_message_queued_with_reserve_reply_while_limits_are_green(self):
        pc.reserve_hold("резерв")
        r = self.enqueue()
        self.assertEqual(r.returncode, 10, r.stdout + r.stderr)
        self.assertIn("Reserve mode is on", r.stdout)
        self.assertIn("1 waiting", r.stdout)
        with open(os.path.join(self.d, "tg_queue.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual([x["text"] for x in rows], ["привет"])

    def test_custom_reserve_reply_from_config(self):
        put(os.path.join(self.d, "config.json"), {"queue_ack_reserve_message": "Резерв: ждёт {n}"})
        pc.reserve_hold("резерв")
        self.assertIn("Резерв: ждёт 1", self.enqueue().stdout)

    def test_no_pause_message_goes_straight_to_claude(self):
        r = self.enqueue()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, "tg_queue.jsonl")))

    def test_after_emergency_exit_button_messages_go_straight(self):
        pc.reserve_hold("резерв")
        pc.cmd_off(argparse.Namespace(by="тест"))
        self.assertEqual(self.enqueue().returncode, 0)

    def test_after_release_messages_go_straight(self):
        pc.reserve_hold("резерв")
        pc.reserve_release()
        self.assertEqual(self.enqueue().returncode, 0)


if __name__ == "__main__":
    unittest.main()
