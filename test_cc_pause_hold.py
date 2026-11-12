# Пауза по лимитам вокруг работы: хук инструментов, гейт фоновых прогонов, очередь входящих и работа на PROD.
# Ни Telegram, ни настоящий screen, ни боевая папка не трогаются.
# python3 -m unittest test_cc_pause_hold -v
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


class Gate(Base):
    def test_limits_pause_does_not_close_gate_by_itself(self):
        put(pc.STATE, {"active": True, "since": 1, "kind": "session", "resume_at": time.time() + 60})
        self.assertEqual(self.run_py("limits_gate.py").returncode, 0)  # без снимка гейт пропускает — как и раньше

    def test_old_service_pause_kind_does_not_close_gate(self):
        # запись прежней версии со служебным видом паузы: гейт смотрит только на лимиты
        put(pc.STATE, {"active": True, "since": 1, "kind": "reserve", "resume_at": 0})
        self.assertEqual(self.run_py("limits_gate.py").returncode, 0)


class ToolHook(Base):
    def call(self, tool="Bash", cmd="ls"):
        r = self.run_py("hooks/pause_tool_gate.py", stdin=json.dumps({"tool_name": tool, "tool_input": {"command": cmd}}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_no_pause_passes(self):
        self.assertIsNone(self.call())

    def test_limits_pause_denies_first_call_with_grace_then_passes_then_denies(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 3600})
        first = self.call()
        self.assertEqual(first["permissionDecision"], "deny")
        self.assertIn("Пауза по лимитам", first["permissionDecisionReason"])
        self.assertIn("120 с", first["permissionDecisionReason"])
        self.assertIsNone(self.call())  # в пределах GRACE дали довести начатое
        mark = os.path.join(self.d, "pause_tool_gate.json")
        m = get(mark)
        m["notice_ts"] = time.time() - 500
        put(mark, m)
        self.assertEqual(self.call()["permissionDecision"], "deny")

    def test_old_service_pause_kind_is_an_ordinary_pause(self):
        # прежний служебный вид паузы без будильника читается как обычная пауза: отказ с инструкцией, не падение
        put(pc.STATE, {"active": True, "since": 2, "reason": "старая запись", "kind": "reserve", "resume_at": 0})
        first = self.call()
        self.assertEqual(first["permissionDecision"], "deny")
        self.assertIn("Пауза по лимитам", first["permissionDecisionReason"])

    def test_pause_commands_always_allowed_as_exit(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 3600})
        self.assertIsNone(self.call(cmd="python3 /opt/cc-limits/pause_ctl.py off"))

    def test_manual_override_button_lets_everything_through(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 3600})
        pc.cmd_off(argparse.Namespace(by="тест"))
        self.assertIsNone(self.call())


class Queue(Base):
    def enqueue(self, text="привет"):
        f = os.path.join(self.d, "m.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.run_py("tg_queue.py", "enqueue", "--chat", "1", "--msg-id", "7", "--user", "u", "--text-file", f,
                           "--no-notify")

    def test_no_pause_message_goes_straight_to_claude(self):
        r = self.enqueue()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, "tg_queue.jsonl")))


class RemoteWork(Base):
    """[remote] Работа передана на Аккаунт PROD: родной Claude остановлен, будильник и кнопки паузы его не будят."""

    def setUp(self):
        super().setUp()
        saved = (pc.session_blocked, pc.week_blocked, pc.level_state)
        pc.session_blocked = lambda: (False, "окно отпустило")
        pc.week_blocked = lambda: (False, "неделя отпустила")
        pc.level_state = lambda: {"line": "acc3 0%"}

        def back():
            pc.session_blocked, pc.week_blocked, pc.level_state = saved
        self.addCleanup(back)

    def remote(self, active):
        put(os.path.join(self.d, "remote_mode.json"), {"active": active, "member": "prod"})

    def test_due_alarm_holds_pause_while_work_is_on_prod_then_lifts_once(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() - 60})
        self.remote(True)
        for _ in range(3):
            self.assertEqual(pc.cmd_wake(argparse.Namespace(if_due=True)), 0)
        st = pc.load()
        self.assertTrue(st["active"])
        self.assertTrue(st.get("remote_hold"))
        self.assertEqual((self.wakes, self.tgs), ([], []))
        self.remote(False)
        pc.cmd_wake(argparse.Namespace(if_due=True))
        st = pc.load()
        self.assertFalse(st["active"])
        self.assertNotIn("remote_hold", st)
        self.assertEqual((len(self.wakes), len(self.tgs)), (1, 1))

    def test_pause_off_button_silent_while_work_is_on_prod(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() + 600})
        self.remote(True)
        self.assertEqual(pc.cmd_off(argparse.Namespace(by="панель")), 0)
        st = pc.load()
        self.assertEqual((st["active"], st["override"]), (False, True))
        self.assertEqual((self.wakes, self.tgs), ([], []))

    def test_broken_or_missing_mode_file_does_not_hold(self):
        put(pc.STATE, {"active": True, "since": 1, "reason": "лимиты", "kind": "session", "resume_at": time.time() - 60})
        with open(os.path.join(self.d, "remote_mode.json"), "w") as f:
            f.write("{oops")
        pc.cmd_wake(argparse.Namespace(if_due=True))
        self.assertFalse(pc.load()["active"])
