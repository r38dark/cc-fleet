# Опросы второго сервера идут по одному постоянному ssh-соединению, чтение при обрыве повторяется один раз (2.0.14)
# python3 -m unittest test_cc_remote_ssh_mux -v
import importlib.util
import os
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
# своя копия модуля: другие тесты подменяют cc_remote.ssh_run у общего модуля и не возвращают
_spec = importlib.util.spec_from_file_location("cc_remote_mux_real", os.path.join(HERE, "cc_remote.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

POLL = "CC_REMOTE_TMUX=friend python3 /root/cc-remote/ctl.py ansi 100 0"
WRITE = "cat > /tmp/cc_msg.txt && python3 /root/cc-remote/ctl.py send /tmp/cc_msg.txt"
M = {"host": "192.0.2.1", "user": "root"}


def done(code, out=""):
    return subprocess.CompletedProcess([], code, stdout=out, stderr="")


class Mux(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="mx_"), "m")
        p = mock.patch.object(R, "MUX_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)
        s = mock.patch.object(R.time, "sleep")
        s.start()
        self.addCleanup(s.stop)

    def run_cmd(self, cmd, results):
        with mock.patch.object(R.subprocess, "run", side_effect=results) as run:
            res = R.ssh_run(M, cmd)
        return res, run

    def test_read_polls_go_through_one_shared_connection(self):
        for c in (POLL, "python3 /root/cc-remote/usage.py", "CC_REMOTE_TMUX=x python3 /root/cc-remote/ctl.py status",
                  "tmux has-session -t friend ; echo rc=$?"):
            _, run = self.run_cmd(c, [done(0, "{}")])
            argv = run.call_args.args[0]
            self.assertIn("ControlMaster=auto", argv, c)
            self.assertIn("ControlPath=" + self.dir + "/%C", argv, c)
            self.assertIn("ControlPersist=120", argv, c)
            self.assertIn("ServerAliveInterval=5", argv, c)
            self.assertEqual(argv[-2:], ["root@192.0.2.1", c])

    def test_socket_folder_is_private(self):
        self.run_cmd(POLL, [done(0)])
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)

    def test_writes_and_setup_do_not_use_the_shared_connection(self):
        for c in (WRITE, "python3 /root/cc-remote/ctl.py key Enter", "python3 /root/cc-remote/ctl.py sendin x",
                  "mkdir -p /root/cc-remote && cat > /root/cc-remote/ctl.py", "rm -rf -- /home/x"):
            _, run = self.run_cmd(c, [done(0)])
            self.assertFalse([a for a in run.call_args.args[0] if "Control" in a], c)

    def test_read_is_retried_once_after_a_drop(self):
        res, run = self.run_cmd(POLL, [done(255), done(0, "ok")])
        self.assertEqual(res, (0, "ok"))
        self.assertEqual(run.call_count, 2)

    def test_two_drops_in_a_row_give_the_error_after_exactly_two_tries(self):
        res, run = self.run_cmd(POLL, [done(255), done(255), done(0)])
        self.assertEqual(res[0], 255)
        self.assertEqual(run.call_count, 2)

    def test_a_write_is_never_repeated(self):
        # запись не повторяем: после обрыва неизвестно, дошла ли она (дубль ввода в консоль)
        res, run = self.run_cmd(WRITE, [done(255), done(0)])
        self.assertEqual(res[0], 255)
        self.assertEqual(run.call_count, 1)

    def test_a_remote_error_is_not_a_connection_drop(self):
        res, run = self.run_cmd(POLL, [done(1, "x"), done(0)])
        self.assertEqual(res[0], 1)
        self.assertEqual(run.call_count, 1)

    def test_timeout_is_not_repeated(self):
        res, run = self.run_cmd(POLL, subprocess.TimeoutExpired("ssh", 25))
        self.assertEqual(res, (124, "timeout"))
        self.assertEqual(run.call_count, 1)

    def test_too_long_socket_path_falls_back_to_a_plain_connection(self):
        with mock.patch.object(R, "MUX_DIR", "/" + "x" * 80):
            _, run = self.run_cmd(POLL, [done(0)])
        self.assertFalse([a for a in run.call_args.args[0] if "Control" in a])

    def test_unwritable_socket_folder_falls_back_to_a_plain_connection(self):
        with mock.patch.object(R.os, "makedirs", side_effect=OSError("нет прав")):
            _, run = self.run_cmd(POLL, [done(0)])
        self.assertFalse([a for a in run.call_args.args[0] if "Control" in a])


if __name__ == "__main__":
    unittest.main()
