# Кнопка «Перезапустить консоль Codex»: незакрытый ход брошенной сессии не держит её серой вечно.
# python3 -m unittest test_cc_busy_restart -v
import json
import os
import tempfile
import time
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="ccbusyrs_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_codex  # noqa: E402,F401
import cc_codex_console as C  # noqa: E402
import cc_limits as L  # noqa: E402,F401


def event(kind, turn, ts):
    return json.dumps({"type": "event_msg", "timestamp": ts, "payload": {"type": kind, "turn_id": turn}}) + "\n"


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


class BusyForRestart(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=TMP), "rollout.jsonl")
        self.patches = [mock.patch.object(C, "_pid", lambda: 123), mock.patch.object(C, "_meta", lambda: {"started": 0, "slot": "x"}),
                        mock.patch.object(C, "active_settings", lambda: {"rollout_path": self.path})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_abandoned_open_turn_does_not_block_restart(self):
        with open(self.path, "w") as f:
            f.write(event("task_started", "t1", iso(time.time() - 7200)))
        os.utime(self.path, (time.time() - 7200, time.time() - 7200))
        self.assertFalse(C.busy_for_restart())
        self.assertTrue(C.busy(), "обычная проверка занятости не меняется: в такую консоль печатать нельзя")

    def test_fresh_open_turn_blocks_restart(self):
        with open(self.path, "w") as f:
            f.write(event("task_started", "t1", iso(time.time())))
        self.assertTrue(C.busy_for_restart())

    def test_closed_turn_does_not_block(self):
        with open(self.path, "w") as f:
            f.write(event("task_started", "t1", iso(time.time() - 5)) + event("task_complete", "t1", iso(time.time())))
        self.assertFalse(C.busy_for_restart())

    def test_running_ask_blocks(self):
        C._ask_lock.acquire()
        try:
            self.assertTrue(C.busy_for_restart())
        finally:
            C._ask_lock.release()

    def test_not_running_console_never_busy(self):
        with mock.patch.object(C, "_pid", lambda: 0):
            self.assertFalse(C.busy_for_restart())

    def test_restart_info_and_api_use_it(self):
        import inspect
        src = inspect.getsource(L)
        self.assertIn("cc_codex_console.busy_for_restart()", src)
        self.assertEqual(src.count("cc_codex_console.busy_for_restart()"), 2)


if __name__ == "__main__":
    unittest.main()
