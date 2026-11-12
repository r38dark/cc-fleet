"""Обновление Claude Code и Codex из панели: модуль claude_cli.py (версия, обновление, возврат; npm и нативная установка) на подставных npm/node/claude
во временной папке, плюс блок страницы. Запуск: python3 -m unittest test_claude_cli -v. Настоящие npm и сессии не трогаются."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
MOD = str(HERE / "claude_cli.py")

# подделка npm: view -> FAKE_LATEST; install [-g] --prefix P pkg@V -> кладёт package.json версии V (latest -> FAKE_LATEST) в P/lib/node_modules/pkg (-g) или P/node_modules/pkg
FAKE_NPM = """#!/bin/sh
if [ "$1" = "view" ]; then [ -n "$FAKE_VIEW_FAIL" ] && exit 1; echo "${FAKE_LATEST:-2.1.322}"; exit 0; fi
if [ "$1" = "install" ]; then
  [ -n "$FAKE_INSTALL_FAIL" ] && { echo "npm ERR! simulated failure" >&2; exit 1; }
  sleep "${FAKE_DELAY:-0}"
  shift; glob=0; prefix=""; spec=""
  while [ $# -gt 0 ]; do case "$1" in -g) glob=1;; --prefix) shift; prefix="$1";; *) spec="$1";; esac; shift; done
  name="${spec%@*}"; ver="${spec##*@}"; [ "$ver" = "latest" ] && ver="${FAKE_LATEST:-2.1.322}"
  if [ "$glob" = 1 ]; then d="$prefix/lib/node_modules/$name"; else d="$prefix/node_modules/$name"; fi
  mkdir -p "$d"
  printf '{"name":"%s","version":"%s"}' "$name" "$ver" > "$d/package.json"
  echo "added 1 package"; exit 0
fi
exit 2
"""


def script(path, text):
    Path(path).write_text(text)
    os.chmod(path, 0o755)


class CliCase(unittest.TestCase):
    """npm-установка Claude Code в <tmp>/prefix, подставные npm и node в <tmp>/bin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.state, self.bin, self.prefix = t / "state", t / "bin", t / "prefix"
        for d in (self.state, self.bin):
            d.mkdir()
        pkg = self.prefix / "lib/node_modules/@anthropic-ai/claude-code"
        (pkg / "bin").mkdir(parents=True)
        (pkg / "package.json").write_text(json.dumps({"name": "@anthropic-ai/claude-code", "version": "2.1.319"}))
        script(pkg / "bin/claude.exe", "#!/bin/sh\nexit 0\n")
        (self.bin / "claude").symlink_to(pkg / "bin/claude.exe")
        script(self.bin / "npm", FAKE_NPM)
        script(self.bin / "node", "#!/bin/sh\necho v20.1.0\n")
        self.env = dict(os.environ, PATH="%s:/usr/bin:/bin" % self.bin, CC_CLI_STATE_DIR=str(self.state), CC_CLI_REGISTRY="npm",
                        CC_CLI_NPM=str(self.bin / "npm"), CC_CLI_NODE=str(self.bin / "node"), HOME=self.tmp.name)
        for k in ("FAKE_INSTALL_FAIL", "FAKE_VIEW_FAIL", "CC_CLI_LATEST"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, **extra_env):
        r = subprocess.run([sys.executable, MOD, *args], capture_output=True, text=True, timeout=60, env=dict(self.env, **extra_env))
        return json.loads(r.stdout.strip().splitlines()[-1])

    def py(self, code, **extra_env):
        """Вызов функций модуля напрямую (Codex доступен только панели, в ctl.py его нет)."""
        r = subprocess.run([sys.executable, "-c", "import json,sys;sys.path.insert(0,%r);import claude_cli as c;%s" % (str(HERE), code)],
                           capture_output=True, text=True, timeout=60, env=dict(self.env, **extra_env))
        return json.loads(r.stdout.strip().splitlines()[-1])

    def wait(self, tries=60, call=None):
        for _ in range(tries):
            d = call() if call else self.cli("status")
            if d["state"] != "running":
                return d
            time.sleep(0.2)
        self.fail("обновление не закончилось")


class Status(CliCase):
    def test_reads_installed_version_without_network(self):
        d = self.cli("status")
        self.assertEqual((d["kind"], d["version"], d["latest"], d["state"]), ("npm", "2.1.319", None, "idle"))
        self.assertTrue(d["can_update"])
        self.assertFalse(d["update_available"])

    def test_reports_when_the_package_was_installed(self):
        d = self.cli("status")
        pkg = self.prefix / "lib/node_modules/@anthropic-ai/claude-code/package.json"
        self.assertAlmostEqual(d["pkg_mtime"], os.path.getmtime(pkg), delta=1)
        self.assertEqual((d["started"], d["finished"]), (0, 0))

    def test_check_asks_registry(self):
        d = self.cli("status", "check")
        self.assertEqual(d["latest"], "2.1.322")
        self.assertTrue(d["update_available"])

    def test_registry_down_is_not_an_error(self):
        d = self.cli("status", "check", FAKE_VIEW_FAIL="1")
        self.assertTrue(d["ok"])
        self.assertIsNone(d["latest"])
        self.assertFalse(d["update_available"])

    def test_old_node_blocks_npm_update(self):
        script(self.bin / "node", "#!/bin/sh\necho v16.0.0\n")
        d = self.cli("status")
        self.assertFalse(d["node"]["ready"])
        self.assertFalse(d["can_update"])
        self.assertEqual(self.cli("update")["error"], "no_node")

    def test_unknown_binary_is_not_touched(self):
        (self.prefix / "lib/node_modules/@anthropic-ai/claude-code/package.json").unlink()
        (self.bin / "claude").unlink()
        script(self.bin / "claude", "#!/bin/sh\nexit 0\n")   # обычный файл вне npm-пакета и вне папки versions
        d = self.cli("status")
        self.assertEqual(d["kind"], "native")
        self.assertIsNone(d["version"])
        self.assertFalse(d["can_update"])
        self.assertEqual(self.cli("update")["error"], "not_npm")


class Update(CliCase):
    def test_update_then_rollback(self):
        d = self.cli("update", FAKE_DELAY="1")
        self.assertTrue(d["ok"])
        self.assertEqual(d["state"], "running")
        self.assertFalse(d["can_update"])                       # пока идёт, вторую кнопку не даём
        self.assertTrue(self.cli("update")["ok"])               # повторный запуск не плодит второй npm
        d = self.wait()
        self.assertEqual((d["state"], d["version"], d["prev_version"]), ("done", "2.1.322", "2.1.319"))
        self.assertIn("added 1 package", d["log"])
        self.assertTrue(d["started"] > 0 and d["finished"] >= d["started"])      # по ним страница считает «идёт N с» и «только что установлено»
        self.assertAlmostEqual(d["pkg_mtime"], os.path.getmtime(self.prefix / "lib/node_modules/@anthropic-ai/claude-code/package.json"), delta=1)
        d = self.cli("rollback")
        self.assertEqual(d["op"], "rollback")
        d = self.wait()
        self.assertEqual((d["state"], d["version"], d["prev_version"]), ("done", "2.1.319", ""))
        self.assertEqual(self.cli("rollback")["error"], "nothing_to_rollback")

    def test_failed_update_keeps_old_version_and_shows_reason(self):
        self.cli("update", FAKE_INSTALL_FAIL="1")
        d = self.wait()
        self.assertEqual((d["state"], d["version"], d["prev_version"]), ("failed", "2.1.319", ""))
        self.assertIn("simulated failure", d["err"])
        self.assertTrue(d["can_update"])                        # после ошибки можно повторить

    def test_specific_version_and_bad_target(self):
        self.assertEqual(self.cli("update", "2.1.320")["ok"], True)
        self.assertEqual(self.wait()["version"], "2.1.320")
        for bad in ("1.2; rm -rf /", "latest;id", "../x", "2.1"):
            self.assertEqual(self.cli("update", bad)["error"], "bad_target", bad)

    def test_killed_process_is_reported_as_failed(self):
        (self.state / "claude_cli_state.json").write_text(json.dumps(
            {"state": "running", "pid": 99999999, "started": time.time(), "op": "update", "from_version": "2.1.319"}))
        d = self.cli("status")
        self.assertEqual(d["state"], "failed")
        self.assertIn("остановлено", d["err"])


class Native(unittest.TestCase):
    """Нативная установка Claude Code: ~/.local/bin/claude -> ~/.local/share/claude/versions/X.Y.Z, обновление — `claude update`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.state = t / "home", t / "state"
        self.bin, self.vers = self.home / ".local/bin", self.home / ".local/share/claude/versions"
        for d in (self.state, self.bin, self.vers):
            d.mkdir(parents=True)
        fake = """#!/bin/sh
# подделка нативного claude: update кладёт версию 2.1.322 и переставляет ссылку (как делает настоящая)
if [ "$1" = "update" ]; then
  [ -n "$FAKE_UPDATE_FAIL" ] && { echo "update failed: simulated" >&2; exit 1; }
  cp "%(v)s/2.1.319" "%(v)s/2.1.322" && ln -sfn "%(v)s/2.1.322" "%(b)s/claude" && echo "Updated to 2.1.322"; exit 0
fi
exit 0
""" % {"v": self.vers, "b": self.bin}
        script(self.vers / "2.1.319", fake)
        script(self.vers / "2.1.316", "#!/bin/sh\nexit 0\n")
        (self.bin / "claude").symlink_to(self.vers / "2.1.319")
        self.env = dict(os.environ, PATH="%s:/usr/bin:/bin" % self.bin, CC_CLI_STATE_DIR=str(self.state), CC_CLI_LATEST="2.1.322", HOME=str(self.home))
        for k in ("FAKE_UPDATE_FAIL", "CC_CLI_NPM", "CC_CLI_NODE"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, **extra_env):
        r = subprocess.run([sys.executable, MOD, *args], capture_output=True, text=True, timeout=60, env=dict(self.env, **extra_env))
        return json.loads(r.stdout.strip().splitlines()[-1])

    def wait(self):
        for _ in range(60):
            d = self.cli("status")
            if d["state"] != "running":
                return d
            time.sleep(0.2)
        self.fail("обновление не закончилось")

    def link(self):
        return os.path.basename(os.path.realpath(self.bin / "claude"))

    def test_status_reads_version_from_folder_and_offers_older_one(self):
        d = self.cli("status", "check")
        self.assertEqual((d["kind"], d["version"], d["latest"], d["can_update"], d["prev_version"]), ("native", "2.1.319", "2.1.322", True, "2.1.316"))
        self.assertTrue(d["update_available"])

    def test_update_runs_the_native_updater_and_keeps_old_version(self):
        self.assertTrue(self.cli("update")["ok"])
        d = self.wait()
        self.assertEqual((d["state"], d["version"], d["prev_version"]), ("done", "2.1.322", "2.1.319"))
        self.assertEqual(self.link(), "2.1.322")
        self.assertTrue((self.vers / "2.1.319").exists())      # старая версия осталась на диске
        self.assertIn("Updated to 2.1.322", d["log"])

    def test_rollback_switches_the_link_back_without_a_process(self):
        self.cli("update")
        self.wait()
        d = self.cli("rollback")
        self.assertEqual((d["ok"], d["state"], d["op"], d["version"]), (True, "done", "rollback", "2.1.319"))
        self.assertEqual(self.link(), "2.1.319")
        self.assertEqual(self.cli("rollback")["ok"], True)     # дальше можно вернуться и на 2.1.316 (самая новая из старых)
        self.assertEqual(self.link(), "2.1.316")

    def test_rollback_without_saved_older_version(self):
        (self.vers / "2.1.316").unlink()
        self.assertEqual(self.cli("rollback")["error"], "nothing_to_rollback")

    def test_failed_native_update_keeps_the_link(self):
        self.cli("update", FAKE_UPDATE_FAIL="1")
        d = self.wait()
        self.assertEqual((d["state"], d["version"]), ("failed", "2.1.319"))
        self.assertIn("simulated", d["err"])
        self.assertEqual(self.link(), "2.1.319")

    def test_native_does_not_need_node_and_ignores_requested_version(self):
        self.assertTrue(self.cli("update", "2.1.320")["ok"])    # номер версии у нативного апдейтера выбрать нельзя
        d = self.wait()
        self.assertEqual((d["state"], d["version"], d["target"]), ("done", "2.1.322", "latest"))


class Codex(CliCase):
    """Codex ставится в <папка>/node_modules (как на нашем деве) или глобально; подсказка о его бинарнике приходит от панели."""

    def local_codex(self):
        d = Path(self.tmp.name) / "codexdir"
        pkg = d / "node_modules/@openai/codex"
        (pkg / "bin").mkdir(parents=True)
        (pkg / "package.json").write_text(json.dumps({"name": "@openai/codex", "version": "0.166.0"}))
        script(pkg / "bin/codex.js", "#!/bin/sh\nexit 0\n")
        (d / "node_modules/.bin").mkdir()
        (d / "node_modules/.bin/codex").symlink_to(pkg / "bin/codex.js")
        return d

    def test_local_install_is_updated_with_prefix_and_without_g(self):
        d = self.local_codex()
        hint = "c.BIN_HINT['codex']=%r;" % str(d / "node_modules/.bin/codex")
        s = self.py(hint + "print(json.dumps(c.status(check=True,tool='codex')))", CC_CLI_LATEST="0.167.0")
        self.assertEqual((s["tool"], s["kind"], s["version"], s["latest"], s["update_available"]), ("codex", "npm", "0.166.0", "0.167.0", True))
        self.assertTrue(self.py(hint + "print(json.dumps(c.start('latest',tool='codex')))", FAKE_LATEST="0.167.0")["ok"])
        s = self.wait(call=lambda: self.py(hint + "print(json.dumps(c.status(tool='codex')))"))
        self.assertEqual((s["state"], s["version"], s["prev_version"]), ("done", "0.167.0", "0.166.0"))
        self.assertTrue((d / "node_modules/@openai/codex/package.json").exists())      # обновилась именно локальная папка
        self.assertFalse((d / "lib").exists())                                          # и без глобальной раскладки
        s = self.py(hint + "print(json.dumps(c.rollback(tool='codex')))")
        s = self.wait(call=lambda: self.py(hint + "print(json.dumps(c.status(tool='codex')))"))
        self.assertEqual((s["state"], s["version"]), ("done", "0.166.0"))

    def test_codex_state_is_separate_from_claude(self):
        d = self.local_codex()
        hint = "c.BIN_HINT['codex']=%r;" % str(d / "node_modules/.bin/codex")
        self.py(hint + "print(json.dumps(c.start('latest',tool='codex')))", FAKE_INSTALL_FAIL="1")
        self.wait(call=lambda: self.py(hint + "print(json.dumps(c.status(tool='codex')))"))
        self.assertEqual(self.cli("status")["state"], "idle")                           # у Claude Code состояния не появилось
        self.assertTrue((self.state / "codex_cli_state.json").exists())

    def test_no_codex_no_row(self):
        s = self.py("print(json.dumps(c.status(tool='codex')))")
        self.assertIsNone(s["kind"])
        self.assertFalse(s["can_update"])


SRC = (HERE / "cc_limits.py").read_text(encoding="utf-8")


def cut(pattern, what):
    m = re.search(pattern, SRC, re.S | re.M)
    assert m, "в cc_limits.py не найдено: " + what
    return m.group(0)


HARNESS = r"""
const LANG='ru';
function tr(k,...a){return k+'('+a.join('|')+')';}
const box={innerHTML:''};const scrim={hidden:false};
function $(s){return s==='#ccliBox'?box:s==='#scrim'?scrim:null;}
let ccliData=null,ccliMsg='';
%s
const out=[];for(const d of CASES){ccliData=d;ccliMsg=d._msg||'';box.innerHTML='';ccliRender();out.push(box.innerHTML);}
console.log(JSON.stringify(out));
"""


def render(cases):
    js = "\n".join([cut(r"^const ccpEsc=.*?;$", "ccpEsc"), cut(r"^function ccliRow\(k,d\)\{.*?^\}$", "ccliRow"), cut(r"^function ccliRender\(\)\{.*?^\}$", "ccliRender")])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        Path(p).write_text(("const CASES=%s;\n" % json.dumps(cases, ensure_ascii=False)) + HARNESS % js, encoding="utf-8")
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout)


def row(**kw):
    d = {"ok": True, "tool": "claude", "kind": "npm", "version": "2.1.319", "latest": "2.1.322", "update_available": True, "prev_version": "", "state": "idle", "op": "",
         "target": "", "from_version": "", "version_after": "", "err": "", "log": "", "node": {"ready": True}, "can_update": True, "path": ""}
    d.update(kw)
    return d


@unittest.skipUnless(shutil.which("node"), "нет node")
class Page(unittest.TestCase):
    def test_scripts_of_the_page_parse(self):
        tmp = tempfile.mkdtemp(prefix="cccli_")
        os.environ["CC_LIMITS_BASE"] = os.path.join(tmp, "base")
        os.environ["CC_LIMITS_PROFILES"] = os.path.join(tmp, "profiles")
        os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
        import cc_limits as L
        scripts = re.findall(r"<script>(.*?)</script>", L.PAGE, re.S)
        self.assertTrue(scripts)
        for i, code in enumerate(scripts):
            p = os.path.join(tmp, "s%d.js" % i)
            Path(p).write_text(code, encoding="utf-8")
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr[-600:])

    def test_block_and_routes_are_wired(self):
        for part in ('id="ccliBox"', 'id="ccliHdr"', "API+'claude-cli?token='", "API+'claude-cli/'+p+'?token='", "ccliLoad(", 'u.path == "/api/claude-cli"',
                     '"/api/claude-cli/update", "/api/claude-cli/rollback"', "def claude_cli_view(", "def claude_cli_action(", "BIN_HINT"):
            self.assertIn(part, SRC, part)

    def test_update_button_and_check(self):
        h = render([{"local": row(), "remote": None}])[0]
        self.assertIn('data-ccli="update"', h)
        self.assertIn("ccliBtnUpdate(2.1.322)", h)
        self.assertIn("ccliLatest(2.1.322)", h)
        self.assertIn("ccliLine(Claude Code|ccliThis()|2.1.319)", h)
        self.assertIn('data-ccli="check"', h)
        self.assertNotIn('data-ccli="rollback"', h)
        self.assertEqual(h.count('class="updrow"'), 1)          # второго сервера нет — одна строка

    def test_running_has_no_buttons_but_shows_log(self):
        h = render([{"local": row(state="running", op="update", target="latest", can_update=False, log="npm http fetch"), "remote": None}])[0]
        self.assertIn("ccliRunning(", h)
        self.assertNotIn("data-ccli=", h)
        self.assertIn("<pre>npm http fetch</pre>", h)

    def test_failed_offers_retry_and_shows_reason(self):
        h = render([{"local": row(state="failed", err="npm ERR! boom", log="line1"), "remote": None}])[0]
        self.assertIn("ccliFailed(npm ERR! boom)", h)
        self.assertIn("ccliBtnRetry", h)
        self.assertIn("<pre>line1</pre>", h)

    def test_done_offers_rollback(self):
        h = render([{"local": row(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, prev_version="2.1.319", finished=time.time()), "remote": None}])[0]
        self.assertIn("ccliOkTitle(Claude Code|2.1.319|2.1.322)", h)
        self.assertIn('data-ccli="rollback"', h)
        self.assertIn("ccliBtnRollback(2.1.319)", h)
        self.assertNotIn('data-ccli="update"', h)

    def test_native_install_has_buttons_and_needs_no_node(self):
        h = render([{"local": row(kind="native", node={"ready": False}, path="/root/.local/bin/claude", prev_version="2.1.316"), "remote": None}])[0]
        self.assertIn('data-ccli="update"', h)
        self.assertIn('data-ccli="rollback"', h)
        self.assertNotIn("ccliNoNode", h)

    def test_unknown_binary_missing_node_no_link_and_not_found(self):
        h = render([{"local": row(kind="native", version=None, path="/opt/x/claude", can_update=False, update_available=False), "remote": None},
                    {"local": row(node={"ready": False}, can_update=False), "remote": None},
                    {"local": row(), "remote": {"ok": False, "error": "ssh"}},
                    {"local": row(kind=None, version=None, can_update=False), "remote": None}])
        self.assertIn("ccliNative(/opt/x/claude)", h[0])
        self.assertNotIn("data-ccli=", h[0])
        self.assertIn("ccliNoNode", h[1])
        self.assertNotIn('data-ccli="update"', h[1])
        self.assertIn("ccliNoLink", h[2])
        self.assertIn("ccliNone", h[3])

    def test_second_server_row_is_separate_and_text_is_escaped(self):
        h = render([{"local": row(), "remote": row(version="2.1.300", err='<img src=x onerror=alert(1)>', state="failed")}])[0]
        self.assertEqual(h.count('class="updrow"'), 2)
        self.assertIn('data-k="remote"', h)
        self.assertNotIn("<img", h)
        self.assertIn("&lt;img", h)

    def test_running_shows_moving_bar_elapsed_time_and_log(self):
        h = render([{"local": row(state="running", op="update", target="latest", can_update=False, started=time.time() - 12, log="npm http fetch GET 200"), "remote": None}])[0]
        self.assertIn('class="upd-bar ccli-bar"', h)
        self.assertRegex(h, r"ccliSec\((1[1-4])\)")
        self.assertIn("<pre>npm http fetch GET 200</pre>", h)
        self.assertNotIn("data-ccli=", h)

    def test_fresh_install_is_green_and_tells_what_to_do_next(self):
        fresh = row(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, finished=time.time() - 30)
        old = row(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, finished=time.time() - 7200)
        h = render([{"local": fresh, "remote": None}, {"local": old, "remote": None}])
        self.assertIn('class="updsub ok"', h[0])
        self.assertIn("ccliNextClaude", h[0])
        self.assertNotIn("ccliOkTitle", h[1])                    # через десять минут это обычная строка, не вечное «установлено»
        self.assertNotIn("ccliNextClaude", h[1])

    def test_codex_after_update_offers_restart_and_says_why(self):
        cx = row(tool="codex", version="0.167.0", latest="0.167.0", update_available=False, state="done", op="update", from_version="0.166.0",
                 version_after="0.167.0", finished=time.time() - 20, restart={"running": True, "stale": True, "busy": False})
        h = render([{"local": row(update_available=False), "remote": None, "codex": cx}])[0]
        self.assertIn("ccliOkTitle(Codex|0.166.0|0.167.0)", h)
        self.assertIn("ccliNextCodex", h)
        self.assertIn('data-ccli="restart" data-k="codex"', h)
        self.assertIn("ccliRestartBtn", h)

    def test_stale_console_keeps_the_restart_button_after_the_message_is_gone(self):
        cx = row(tool="codex", version="0.167.0", latest="0.167.0", update_available=False, state="done", finished=time.time() - 7200,
                 restart={"running": True, "stale": True, "busy": False})
        h = render([{"local": row(update_available=False), "remote": None, "codex": cx}])[0]
        self.assertIn("ccliStaleNote", h)
        self.assertIn('data-ccli="restart"', h)

    def test_restart_is_disabled_while_codex_answers_and_absent_when_console_is_fresh_or_stopped(self):
        base = dict(tool="codex", version="0.167.0", latest="0.167.0", update_available=False)
        busy = row(**base, restart={"running": True, "stale": True, "busy": True})
        fresh = row(**base, restart={"running": True, "stale": False, "busy": False})
        stopped = row(**base, restart={"running": False, "stale": False, "busy": False})
        h = render([{"local": row(update_available=False), "remote": None, "codex": c} for c in (busy, fresh, stopped)])
        self.assertIn('data-ccli="restart" data-k="codex" disabled', h[0])
        self.assertNotIn('data-ccli="restart"', h[1])
        self.assertNotIn('data-ccli="restart"', h[2])

    def test_what_next_depends_on_whether_the_program_is_running(self):
        done = dict(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, finished=time.time())
        cx = dict(tool="codex", version="0.167.0", update_available=False, state="done", op="update", from_version="0.166.0", version_after="0.167.0", finished=time.time())
        h = render([{"local": row(**done, restart={"running": False, "stale": False, "busy": False}), "remote": None, "codex": row(**cx, restart={"running": False, "stale": False, "busy": False})},
                    {"local": row(**done, restart={"running": True, "stale": False, "busy": False}), "remote": None, "codex": row(**cx, restart={"running": True, "stale": True, "busy": False})}])
        self.assertIn("ccliNextClaudeStopped", h[0])
        self.assertIn("ccliNextCodexStopped", h[0])
        self.assertNotIn("ccliNextClaude(", h[0])
        self.assertIn("ccliNextClaude", h[1])
        self.assertNotIn("Stopped", h[1])

    def test_claude_restart_button_for_this_server_and_second_server(self):
        stale = {"running": True, "stale": True, "busy": False}
        h = render([{"local": row(update_available=False, restart=stale), "remote": row(update_available=False, restart=stale), "codex": None}])[0]
        self.assertIn('data-ccli="restart" data-k="local"', h)
        self.assertIn('data-ccli="restart" data-k="remote"', h)
        self.assertEqual(h.count("ccliRestartClaude"), 2)
        self.assertEqual(h.count("ccliStaleClaude"), 2)

    def test_claude_restart_after_a_fresh_install_and_no_button_when_it_is_not_running(self):
        done = dict(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, finished=time.time())
        h = render([{"local": row(**done, restart={"running": True, "stale": False, "busy": False}), "remote": None},
                    {"local": row(**done, restart={"running": False, "stale": False, "busy": False}), "remote": None},
                    {"local": row(update_available=False, restart=None), "remote": None}])
        self.assertIn('data-ccli="restart" data-k="local"', h[0])
        self.assertNotIn('data-ccli="restart"', h[1])
        self.assertIn("ccliNextClaude", h[1])                                       # остановлен: новая версия включится при запуске
        self.assertNotIn('data-ccli="restart"', h[2])

    def test_codex_row(self):
        h = render([{"local": row(), "remote": None, "codex": row(tool="codex", version="0.166.0", latest="0.167.0")}])[0]
        self.assertEqual(h.count('class="updrow"'), 2)
        self.assertIn('data-k="codex"', h)
        self.assertIn("ccliLine(Codex|ccliThis()|0.166.0)", h)
        self.assertIn("ccliBtnUpdate(0.167.0)", h)
        h = render([{"local": row(), "remote": None, "codex": None}])[0]
        self.assertEqual(h.count('class="updrow"'), 1)          # Codex не установлен — строки нет


BADGE_HARNESS = r"""
const LANG='ru';
function tr(k,...a){return k+'('+a.join('|')+')';}
const badge={hidden:true,title:'',_n:{textContent:''},querySelector:s=>badge._n};
const pop={hidden:true,innerHTML:'',style:{}};
function $(s){return s==='#ccliBadge'?badge:s==='#ccliPop'?pop:null;}
let ccliData=null,ccliMsg='',ccliPopOpen=false;
%s
const out=[];for(const c of CASES){ccliData=c.data;ccliPopOpen=!!c.open;ccliMsg=c.msg||'';badge.hidden=true;badge._n.textContent='';pop.innerHTML='';ccliBadgeRender();out.push({hidden:badge.hidden,n:badge._n.textContent,title:badge.title,html:pop.innerHTML});}
console.log(JSON.stringify(out));
"""


def badge(cases):
    js = "\n".join([cut(r"^const ccpEsc=.*?;$", "ccpEsc"), cut(r"^function ccliNews\(\)\{.*?^\}$", "ccliNews"), cut(r"^function ccliPopRender\(\)\{.*?^\}$", "ccliPopRender"),
                    cut(r"^function ccliBadgeRender\(\)\{.*?^\}$", "ccliBadgeRender")])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.js")
        Path(p).write_text(("const CASES=%s;\n" % json.dumps(cases, ensure_ascii=False)) + BADGE_HARNESS % js, encoding="utf-8")
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "нет node")
class Badge(unittest.TestCase):
    def test_hidden_when_everything_is_fresh_or_nothing_loaded(self):
        r = badge([{"data": None}, {"data": {"local": row(update_available=False), "remote": row(update_available=False), "codex": None}}])
        self.assertTrue(r[0]["hidden"])
        self.assertTrue(r[1]["hidden"])
        self.assertEqual(r[1]["n"], "0")

    def test_shown_with_count_and_window_lists_updates_with_update_and_cancel(self):
        data = {"local": row(), "remote": row(version="2.1.322", update_available=False), "codex": row(tool="codex", version="0.166.0", latest="0.167.0")}
        r = badge([{"data": data}, {"data": data, "open": True}])
        self.assertFalse(r[0]["hidden"])
        self.assertEqual(r[0]["n"], "2")
        self.assertIn("ccliBadgeTitle(2)", r[0]["title"])
        self.assertEqual(r[0]["html"], "")                       # окошко закрыто — не рисуем
        h = r[1]["html"]
        self.assertIn("ccliPopTitle", h)
        self.assertIn("ccliPopSub(2.1.319|2.1.322)", h)
        self.assertIn("ccliPopSub(0.166.0|0.167.0)", h)
        self.assertEqual(h.count('data-ccli-pop="update"'), 2)
        self.assertIn('data-k="local"', h)
        self.assertIn('data-k="codex"', h)
        self.assertNotIn('data-k="remote"', h)                   # на PROD уже последняя
        self.assertIn('data-ccli-pop="close"', h)
        self.assertIn("ccliPopCancel", h)
        self.assertIn("ccliPopNote", h)

    def test_not_counted_when_it_cannot_be_updated_from_the_panel_or_second_server_is_down(self):
        r = badge([{"data": {"local": row(can_update=False), "remote": {"ok": False, "error": "ssh"}, "codex": row(tool="codex", kind=None)}}])
        self.assertTrue(r[0]["hidden"])

    def test_running_keeps_badge_and_shows_progress_without_button(self):
        r = badge([{"data": {"local": row(state="running", op="update", target="latest", can_update=False), "remote": None, "codex": None}, "open": True}])
        self.assertFalse(r[0]["hidden"])
        self.assertIn("ccliRunning(Claude Code|ccliThis()|2.1.322)", r[0]["html"])
        self.assertNotIn('data-ccli-pop="update"', r[0]["html"])

    def test_done_and_failed_are_visible_only_while_the_window_is_open(self):
        done = row(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, finished=time.time())
        failed = row(state="failed", err='<b>boom</b>')
        r = badge([{"data": {"local": done, "remote": None, "codex": None}}, {"data": {"local": done, "remote": None, "codex": None}, "open": True},
                   {"data": {"local": failed, "remote": None, "codex": None}, "open": True}])
        self.assertTrue(r[0]["hidden"])
        self.assertIn("ccliOkTitle(Claude Code|2.1.319|2.1.322)", r[1]["html"])
        self.assertIn("ccliFailed(&lt;b&gt;boom&lt;/b&gt;)", r[2]["html"])      # текст из ответа экранирован

    def test_failed_popup_offers_retry_for_each_updatable_tool(self):
        for tool in ("local", "remote", "codex"):
            data = {"local": None, "remote": None, "codex": None}
            data[tool] = row(tool="codex" if tool == "codex" else "claude", state="failed", err="npm error E404")
            html = badge([{"data": data, "open": True}])[0]["html"]
            self.assertIn('data-ccli-pop="update" data-k="'+tool+'" data-v="latest"', html)
            self.assertIn("ccliBtnRetry", html)
            self.assertIn("ccliFailed(npm error E404)", html)

    def test_failed_popup_without_update_support_does_not_offer_retry(self):
        html = badge([{"data": {"local": None, "remote": None, "codex": row(state="failed", can_update=False)}, "open": True}])[0]["html"]
        self.assertNotIn('data-ccli-pop="update"', html)

    def test_running_codex_alone_schedules_status_poll(self):
        function = cut(r"^async function ccliLoad\(check\)\{.*?^\}", "ccliLoad")
        source = r"""
const API='/api/', TOKEN='fixture';
let ccliData=null,ccliTimer=null,ccliPopOpen=true;
let polls=[];
function $(s){return {hidden:true};}
function ccliRender(){} function ccliBadgeRender(){}
function clearTimeout(){} function setTimeout(callback,delay){polls.push(delay);return 1;}
let data;
async function fetch(){return {ok:true,json:async()=>data};}
""" + function + r"""
(async()=>{
 data={local:{state:'idle'},remote:null,codex:{state:'running'}};
 await ccliLoad(false);
 const running=polls.slice();polls=[];
 data={local:{state:'idle'},remote:null,codex:{state:'done'}};
 await ccliLoad(false);
 console.log(JSON.stringify({running,done:polls}));
})();
"""
        result = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), {"running": [3000], "done": []})

    def test_open_window_with_nothing_left_says_everything_is_up_to_date(self):
        r = badge([{"data": {"local": row(update_available=False), "remote": None, "codex": None}, "open": True}])
        self.assertFalse(r[0]["hidden"])                         # пока окно открыто, бейдж не пропадает из-под курсора
        self.assertIn("ccliPopNone", r[0]["html"])

    def test_markup_and_timers_are_wired(self):
        for part in ('id="ccliBadge"', 'id="ccliPop"', "setTimeout(()=>ccliLoad(true),8000)", "setInterval(()=>ccliLoad(true),1800000)", "data-ccli-pop"):
            self.assertIn(part, SRC, part)


    def test_stale_console_keeps_the_badge_lit_and_the_window_offers_restart(self):
        data = {"local": row(update_available=False), "remote": None,
                "codex": row(tool="codex", version="0.167.0", update_available=False, restart={"running": True, "stale": True, "busy": False})}
        r = badge([{"data": data}, {"data": data, "open": True}])
        self.assertFalse(r[0]["hidden"])
        self.assertEqual(r[0]["n"], "1")
        self.assertIn('data-ccli-pop="restart" data-k="codex"', r[1]["html"])
        self.assertIn("ccliStaleNote", r[1]["html"])
        self.assertNotIn('data-ccli-pop="update"', r[1]["html"])

    def test_claude_restart_in_the_window(self):
        data = {"local": row(update_available=False, restart={"running": True, "stale": True, "busy": False}), "remote": None, "codex": None}
        r = badge([{"data": data, "open": True}])
        self.assertIn('data-ccli-pop="restart" data-k="local"', r[0]["html"])
        self.assertIn("ccliRestartClaude", r[0]["html"])
        self.assertIn("ccliStaleClaude", r[0]["html"])

    def test_window_shows_bar_while_running_and_next_step_after_install(self):
        run = row(state="running", op="update", target="latest", can_update=False, started=time.time() - 5)
        done = row(tool="codex", version="0.167.0", update_available=False, state="done", op="update", from_version="0.166.0", version_after="0.167.0",
                   finished=time.time() - 5, restart={"running": True, "stale": True, "busy": False})
        r = badge([{"data": {"local": run, "remote": None, "codex": None}, "open": True}, {"data": {"local": None, "remote": None, "codex": done}, "open": True}])
        self.assertIn("upd-bar", r[0]["html"])
        self.assertIn("ccliSec(", r[0]["html"])
        self.assertIn("ccliOkTitle(Codex|0.166.0|0.167.0)", r[1]["html"])
        self.assertIn("ccliNextCodex", r[1]["html"])
        self.assertIn('data-ccli-pop="restart"', r[1]["html"])


PV_HARNESS = r"""
const LANG='ru';function tr(k,...a){return k+'('+a.join('|')+')';}
%s
const out=CASES.map(c=>ccliPvInfo(c.s,c.x));
console.log(JSON.stringify(out));
"""


def pv(cases):
    js = cut(r"^function ccliPvInfo\(s,x\)\{.*?^\}$", "ccliPvInfo")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "v.js")
        Path(p).write_text(("const CASES=%s;\n" % json.dumps(cases, ensure_ascii=False)) + PV_HARNESS % js, encoding="utf-8")
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "нет node")
class VersionLabel(unittest.TestCase):
    """Надпись версии в правом верхнем углу КАЖДОГО окна консоли: жёлтая — старая, зелёная — актуальная (владелец 63335)."""

    def test_text_follows_the_part(self):
        r = pv([{"s": "claude", "x": row(version="2.1.322", update_available=False)}, {"s": "prod", "x": row(version="2.1.321", update_available=False)},
                {"s": "codex", "x": row(tool="codex", version="0.167.0", update_available=False)}])
        self.assertEqual([x["text"] for x in r], ["Claude Code 2.1.322", "Claude Code 2.1.321", "Codex 0.167.0"])

    def test_green_when_current_yellow_when_newer_exists_or_started_before_the_update(self):
        r = pv([{"s": "claude", "x": row(update_available=False)},
                {"s": "claude", "x": row(update_available=True)},
                {"s": "codex", "x": row(tool="codex", update_available=False, restart={"running": True, "stale": True})},
                {"s": "prod", "x": row(update_available=False, restart={"running": True, "stale": True})},
                {"s": "codex", "x": row(tool="codex", update_available=False, restart={"running": True, "stale": False})}])
        self.assertEqual([x["old"] for x in r], [False, True, True, True, False])
        self.assertIn("ccliPvNew", r[0]["title"])
        self.assertIn("ccliPvOld", r[1]["title"])
        self.assertIn("ccliStaleNote", r[2]["title"])
        self.assertIn("ccliStaleClaude", r[3]["title"])

    def test_nothing_for_unknown_part_missing_data_or_unavailable_second_server(self):
        r = pv([{"s": "other", "x": row()}, {"s": "other:abc", "x": row()}, {"s": "claude", "x": None}, {"s": "prod", "x": {"ok": False}},
                {"s": "claude", "x": row(version=None)}])
        self.assertEqual(r, [None, None, None, None, None])

    def test_label_sits_below_the_part_header_in_split_mode(self):
        self.assertIn("off=wrap.classList.contains('tsplit')?40:10", SRC)
        self.assertIn("el.style.top=Math.round(r.top-wr.top+off)+'px';", SRC)

    def test_label_is_in_each_window_not_in_the_tab_row(self):
        for part in ("function ccliPartVers(){", "setInterval(ccliPartVers,2000);addEventListener('resize',ccliPartVers);", ".ccli-pv.new{color:var(--ok,#45d6ab)}", ".ccli-pv.old{color:var(--warn,#ecc277)}"):
            self.assertIn(part, SRC, part)
        self.assertNotIn('id="ccliVer"', SRC)
        self.assertNotIn("ccliVerRender", SRC)
        ov = (HERE / "cc_overview.py").read_text(encoding="utf-8")
        self.assertNotIn("ccliVer", ov)                            # из строки вкладок надпись убрана


class ClaudeRestart(unittest.TestCase):
    """Перезапуск Claude из панели: этот сервер (screen, start_claude.sh) и второй (ctl.py stop/start); новая сессия (решение владельца 63326)."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="cccli_cr_")
        os.environ["CC_LIMITS_BASE"] = os.path.join(tmp, "base")
        os.environ["CC_LIMITS_PROFILES"] = os.path.join(tmp, "profiles")
        os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
        import cc_limits as L
        cls.L = L

    def local(self, alive=True, remote=False, side=False, stop=True, start=True):
        L = self.L
        wk = mock.Mock()
        wk.side_running.return_value, wk.stop_claude.return_value, wk.start_claude.return_value = side, stop, start
        with mock.patch.object(L, "WORKERS", wk, create=True), mock.patch.object(L.cc_fleet, "claude_alive", return_value=alive), \
                mock.patch("pause_ctl._remote_active", return_value=remote):
            r = L.claude_restart_local()
        return r, [c[0] for c in wk.mock_calls]

    def test_local_stop_then_start(self):
        r, calls = self.local()
        self.assertEqual((r, calls), ({"ok": True}, ["side_running", "stop_claude", "start_claude"]))

    def test_local_not_touched_when_not_running_or_the_start_script_would_refuse(self):
        self.assertEqual(self.local(alive=False), ({"ok": False, "error": "not_running"}, []))
        self.assertEqual(self.local(remote=True), ({"ok": False, "error": "other_worker"}, []))     # работа на PROD: start_claude.sh не стартует, DEV остался бы выключен
        r, calls = self.local(side=True)
        self.assertEqual((r["error"], calls), ("side_session", ["side_running"]))

    def test_local_failures_are_reported_and_start_is_not_tried_after_a_failed_stop(self):
        r, calls = self.local(stop=False)
        self.assertEqual((r["error"], calls), ("stop_failed", ["side_running", "stop_claude"]))
        r, calls = self.local(start=False)
        self.assertEqual((r["error"], calls), ("start_failed", ["side_running", "stop_claude", "start_claude"]))

    def remote(self, members=True, job_alive=False, status=None, start=None):
        import cc_remote_mode as M
        L = self.L
        status = {"ok": True, "running": True, "tg": True} if status is None else status
        start = {"ok": True} if start is None else start
        calls = []

        def fake_ctl(mid, *a, **k):
            calls.append(a)
            return status if a[0] == "status" else ({"ok": True} if a[0] == "stop" else start)
        job = mock.Mock()
        job.is_alive.return_value = job_alive
        with mock.patch.object(M, "_member_id", return_value="m1"), mock.patch.object(L.cc_remote, "members", return_value={"m1": {"host": "h"}} if members else {}), \
                mock.patch.object(L.cc_remote, "ctl", side_effect=fake_ctl), mock.patch.dict(M._job, {"t": job}):
            r = L.claude_restart_remote()
        return r, calls

    def test_remote_stop_then_start_with_the_same_telegram_state(self):
        r, calls = self.remote()
        self.assertEqual((r, calls), ({"ok": True}, [("status",), ("stop",), ("start", "-", "1")]))
        r, calls = self.remote(status={"ok": True, "running": True, "tg": False})
        self.assertEqual(calls[-1], ("start", "-", "0"))           # Telegram не включаем, если он у второго сервера и не был включён

    def test_remote_not_touched_when_not_running_busy_or_unreachable(self):
        self.assertEqual(self.remote(status={"ok": True, "running": False}), ({"ok": False, "error": "not_running"}, [("status",)]))
        self.assertEqual(self.remote(job_alive=True), ({"ok": False, "error": "busy"}, []))          # идёт передача работы
        self.assertEqual(self.remote(members=False), ({"ok": False, "error": "ssh"}, []))

    def test_remote_unreachable_and_failed_start(self):
        import cc_remote_mode as M
        L = self.L
        with mock.patch.object(M, "_member_id", return_value="m1"), mock.patch.object(L.cc_remote, "members", return_value={"m1": {"host": "h"}}), \
                mock.patch.object(L.cc_remote, "ctl", return_value=None):
            self.assertEqual(L.claude_restart_remote(), {"ok": False, "error": "ssh"})
        r, calls = self.remote(start={"ok": False, "error": "timeout"})
        self.assertEqual((r["ok"], r["error"], r["message"]), (False, "start_failed", "timeout"))

    def test_restart_is_routed_by_target(self):
        L = self.L
        with mock.patch.object(L, "claude_restart_local", return_value={"ok": True, "w": "l"}) as lo, mock.patch.object(L, "claude_restart_remote", return_value={"ok": True, "w": "r"}) as re_:
            self.assertEqual(L.claude_cli_action("restart", {"target": "local"})["w"], "l")
            self.assertEqual(L.claude_cli_action("restart", {"target": "remote"})["w"], "r")
        self.assertEqual((lo.call_count, re_.call_count), (1, 1))

    def test_restart_info_from_second_server_stale_logic(self):
        L = self.L
        mk = lambda started, running=True, mtime=1000: {"ok": True, "pkg_mtime": mtime, "restart": {"running": running, "started": started, "tg": True}}
        self.assertTrue(L.claude_restart_info_remote(mk(500))["stale"])               # запущен до установки пакета
        self.assertFalse(L.claude_restart_info_remote(mk(1500))["stale"])
        self.assertFalse(L.claude_restart_info_remote(mk(500, running=False))["stale"])
        self.assertIsNone(L.claude_restart_info_remote({"ok": True}))                 # ctl.py старой версии — поля нет

    def test_second_server_status_carries_restart_and_old_ctl_triggers_redeploy(self):
        import cc_remote_mode as M
        calls = []

        def fake_ctl(mid, *a, **k):
            calls.append(a)
            return {"ok": True, "version": "2.1.322"} if len(calls) == 1 else {"ok": True, "version": "2.1.322", "restart": {"running": True}}
        with mock.patch.object(M, "_member_id", return_value="m1"), mock.patch.object(M.R, "members", return_value={"m1": {"host": "h"}}), \
                mock.patch.object(M.R, "ctl", side_effect=fake_ctl), mock.patch.object(M, "deploy_tools", return_value=True) as dep:
            r = M.cli_remote("status")
        self.assertEqual(dep.call_count, 1)                                            # ответ без поля restart — доставили свежий ctl.py и спросили ещё раз
        self.assertIn("restart", r)
        self.assertEqual(len(calls), 2)

    def test_ctl_cli_status_reports_restart_fields(self):
        env = dict(os.environ, CC_CLI_STATE_DIR=tempfile.mkdtemp(prefix="cccli_ctl_"), CC_REMOTE_TMUX="cc-test-no-such-session")
        r = subprocess.run([sys.executable, str(HERE / "remote_ctl.py"), "cli", "status"], capture_output=True, text=True, timeout=60, env=env)
        d = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(d["ok"])
        self.assertEqual(set(d["restart"]), {"running", "started", "tg"})
        self.assertFalse(d["restart"]["running"])


class Restart(unittest.TestCase):
    """POST /api/claude-cli/restart: перезапуск консоли Codex — не посреди запроса, сначала остановить, потом запустить."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="cccli_rs_")
        os.environ["CC_LIMITS_BASE"] = os.path.join(tmp, "base")
        os.environ["CC_LIMITS_PROFILES"] = os.path.join(tmp, "profiles")
        os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
        import cc_limits as L
        cls.L = L

    def act(self, busy=False, stop=(True, "ok"), start=(True, "ok"), target="codex", codex="/x/codex"):
        L = self.L
        order = mock.Mock()
        with mock.patch.object(L, "codex_bin", return_value=codex), mock.patch.object(L.cc_codex_console, "busy", return_value=busy), \
                mock.patch.object(L.cc_codex_console, "stop", side_effect=lambda **k: (order.stop(), stop)[1]), \
                mock.patch.object(L.cc_codex_console, "start", side_effect=lambda **k: (order.start(), start)[1]):
            r = L.claude_cli_action("restart", {"target": target})
        return r, [c[0] for c in order.mock_calls]

    def test_busy_console_is_left_alone(self):
        r, calls = self.act(busy=True)
        self.assertEqual((r["ok"], r["error"], calls), (False, "busy", []))

    def test_stop_then_start(self):
        r, calls = self.act()
        self.assertEqual((r["ok"], calls), (True, ["stop", "start"]))

    def test_failed_stop_does_not_start_and_failed_start_is_reported(self):
        r, calls = self.act(stop=(False, "x"))
        self.assertEqual((r["error"], calls), ("stop_failed", ["stop"]))
        r, calls = self.act(start=(False, "y"))
        self.assertEqual((r["error"], calls), ("start_failed", ["stop", "start"]))

    def test_only_codex_and_only_when_installed(self):
        self.assertEqual(self.act(target="bogus")[0]["error"], "not_supported")      # local и remote теперь перезапускают Claude (см. ClaudeRestart)
        self.assertEqual(self.act(target="")[0]["error"], "not_supported")
        self.assertEqual(self.act(codex="")[0]["error"], "not_installed")

    def test_route_is_registered(self):
        self.assertIn('"/api/claude-cli/restart"', SRC)
        self.assertIn("def codex_restart_info(", SRC)


class Integration(unittest.TestCase):
    def test_second_server_command_and_deploy(self):
        ctl = (HERE / "remote_ctl.py").read_text(encoding="utf-8")
        self.assertIn('c == "cli"', ctl)
        self.assertIn("claude_cli", ctl)
        self.assertIn("/root/cc-remote/claude_cli.py", (HERE / "cc_remote_mode.py").read_text(encoding="utf-8"))
        manifest = json.loads((HERE / "update_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("claude_cli.py", {f["src"] for f in manifest["files"]})


if __name__ == "__main__":
    unittest.main()
