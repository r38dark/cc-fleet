"""Перезапуск панели при живой screen-сессии не откладывает лог консоли (иначе на экране нет начала кадра:
пропадают рамка ввода и полоски лимитов), а новая сессия лог откладывает.
python3 -m unittest test_console_log_keep -v"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.mkdtemp(prefix="cclogkeep_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)

import cc_limits as L  # noqa: E402


class Calls(list):
    def __call__(self, cmd, *a, **k):
        self.append(cmd)

        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()


class ConsoleLogKeepTests(unittest.TestCase):
    def setUp(self):
        self.log = Path(L.CONSOLE_LOG)
        for p in (self.log, Path(L.CONSOLE_LOG + ".prev"), Path(L.CONSOLE_LOG_OWNER)):
            if p.exists():
                p.unlink()
        self.calls = Calls()
        for pt in (patch.object(L.subprocess, "run", self.calls), patch.object(L, "_current_screen_pid", return_value="4242"),
                   patch.object(L, "cfg", return_value={"screen_session": "work"})):
            pt.start()
            self.addCleanup(pt.stop)
        L._console_log_ready = False
        L._console_screen_pid = None

    def owner(self, ticks):
        return patch.object(L, "_console_owner_id", return_value="4242:%s" % ticks)

    def test_panel_restart_keeps_log_of_same_session(self):
        self.log.write_bytes(b"BASE-FRAME")
        Path(L.CONSOLE_LOG_OWNER).write_text("4242:777")
        with self.owner(777):
            L._console_ensure_logging()
        self.assertEqual(self.log.read_bytes(), b"BASE-FRAME")
        self.assertFalse(Path(L.CONSOLE_LOG + ".prev").exists())
        self.assertTrue(L._console_log_ready)
        self.assertEqual(L._console_offset, 0)
        self.assertFalse(any("logfile" in c for c in self.calls), "логфайл заново не назначаем")

    def test_new_session_moves_old_log_aside_and_remembers_owner(self):
        self.log.write_bytes(b"OLD-SESSION")
        Path(L.CONSOLE_LOG_OWNER).write_text("4242:111")   # тот же PID, но другое время старта (после перезагрузки)
        with self.owner(999):
            L._console_ensure_logging()
        self.assertEqual(Path(L.CONSOLE_LOG + ".prev").read_bytes(), b"OLD-SESSION")
        self.assertFalse(self.log.exists())
        self.assertEqual(Path(L.CONSOLE_LOG_OWNER).read_text(), "4242:999")
        self.assertTrue(any("logfile" in c for c in self.calls))

    def test_no_marker_behaves_as_before_and_writes_it(self):
        self.log.write_bytes(b"LEGACY")
        with self.owner(5):
            L._console_ensure_logging()
        self.assertEqual(Path(L.CONSOLE_LOG + ".prev").read_bytes(), b"LEGACY")
        self.assertEqual(Path(L.CONSOLE_LOG_OWNER).read_text(), "4242:5")

    def test_second_restart_after_marker_keeps_log(self):
        with self.owner(5):
            L._console_ensure_logging()          # первый запуск: маркер записан
            self.log.write_bytes(b"FRAME-AFTER")
            L._console_log_ready = False         # «перезапуск панели»
            L._console_ensure_logging()
        self.assertEqual(self.log.read_bytes(), b"FRAME-AFTER")

    def test_owner_id_uses_process_start_time(self):
        self.assertEqual(L._console_owner_id(os.getpid()).split(":")[0], str(os.getpid()))
        self.assertNotEqual(L._console_owner_id(os.getpid()).split(":")[1], "")
        self.assertEqual(L._console_owner_id(99999999), "")


if __name__ == "__main__":
    unittest.main()
