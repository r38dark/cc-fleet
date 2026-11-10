"""Обновление Claude Code из панели: модуль claude_cli.py (версия, обновление, возврат) на подставных npm/node в временной папке.
Запуск: python3 -m unittest test_claude_cli -v. Настоящий npm и настоящие сессии не трогаются."""
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

HERE = Path(__file__).parent
MOD = str(HERE / "claude_cli.py")

FAKE_NPM = """#!/bin/sh
# подделка npm: view -> FAKE_LATEST; install -g --prefix P pkg@V -> кладёт package.json версии V (latest -> FAKE_LATEST)
if [ "$1" = "view" ]; then [ -n "$FAKE_VIEW_FAIL" ] && exit 1; echo "${FAKE_LATEST:-2.1.322}"; exit 0; fi
if [ "$1" = "install" ]; then
  [ -n "$FAKE_INSTALL_FAIL" ] && { echo "npm ERR! simulated failure" >&2; exit 1; }
  sleep "${FAKE_DELAY:-0}"
  prefix="$4"; spec="$5"; ver="${spec##*@}"; [ "$ver" = "latest" ] && ver="${FAKE_LATEST:-2.1.322}"
  d="$prefix/lib/node_modules/@anthropic-ai/claude-code"; mkdir -p "$d"
  printf '{"name":"@anthropic-ai/claude-code","version":"%s"}' "$ver" > "$d/package.json"
  echo "added 1 package"; exit 0
fi
exit 2
"""


def script(path, text):
    Path(path).write_text(text)
    os.chmod(path, 0o755)


class CliCase(unittest.TestCase):
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
        self.env = dict(os.environ, PATH="%s:/usr/bin:/bin" % self.bin, CC_CLI_STATE_DIR=str(self.state),
                        CC_CLI_NPM=str(self.bin / "npm"), CC_CLI_NODE=str(self.bin / "node"), HOME=self.tmp.name)
        self.env.pop("FAKE_INSTALL_FAIL", None)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, **extra_env):
        r = subprocess.run([sys.executable, MOD, *args], capture_output=True, text=True, timeout=60, env=dict(self.env, **extra_env))
        return json.loads(r.stdout.strip().splitlines()[-1])

    def wait(self, tries=60):
        for _ in range(tries):
            d = self.cli("status")
            if d["state"] != "running":
                return d
            time.sleep(0.2)
        self.fail("npm не закончил")


class Status(CliCase):
    def test_reads_installed_version_without_network(self):
        d = self.cli("status")
        self.assertEqual((d["kind"], d["version"], d["latest"], d["state"]), ("npm", "2.1.319", None, "idle"))
        self.assertTrue(d["can_update"])
        self.assertFalse(d["update_available"])

    def test_check_asks_registry(self):
        d = self.cli("status", "check")
        self.assertEqual(d["latest"], "2.1.322")
        self.assertTrue(d["update_available"])

    def test_registry_down_is_not_an_error(self):
        d = self.cli("status", "check", FAKE_VIEW_FAIL="1")
        self.assertTrue(d["ok"])
        self.assertIsNone(d["latest"])
        self.assertFalse(d["update_available"])

    def test_native_install_is_not_touched(self):
        (self.prefix / "lib/node_modules/@anthropic-ai/claude-code/package.json").unlink()
        (self.bin / "claude").unlink()
        script(self.bin / "claude", "#!/bin/sh\nexit 0\n")   # обычный файл вне npm-пакета = нативная установка
        d = self.cli("status")
        self.assertEqual(d["kind"], "native")
        self.assertFalse(d["can_update"])
        self.assertEqual(self.cli("update")["error"], "not_npm")

    def test_old_node_blocks_update(self):
        script(self.bin / "node", "#!/bin/sh\necho v16.0.0\n")
        d = self.cli("status")
        self.assertFalse(d["node"]["ready"])
        self.assertFalse(d["can_update"])
        self.assertEqual(self.cli("update")["error"], "no_node")


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

    def test_killed_npm_is_reported_as_failed(self):
        (self.state / "claude_cli_state.json").write_text(json.dumps(
            {"state": "running", "pid": 99999999, "started": time.time(), "op": "update", "from_version": "2.1.319"}))
        d = self.cli("status")
        self.assertEqual(d["state"], "failed")
        self.assertIn("остановлен", d["err"])


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
    d = {"ok": True, "kind": "npm", "version": "2.1.319", "latest": "2.1.322", "update_available": True, "prev_version": "", "state": "idle", "op": "",
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
                     '"/api/claude-cli/update", "/api/claude-cli/rollback"', "def claude_cli_view(", "def claude_cli_action("):
            self.assertIn(part, SRC, part)

    def test_update_button_and_check(self):
        h = render([{"local": row(), "remote": None}])[0]
        self.assertIn('data-ccli="update"', h)
        self.assertIn("ccliBtnUpdate(2.1.322)", h)
        self.assertIn("ccliLatest(2.1.322)", h)
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
        h = render([{"local": row(state="done", op="update", from_version="2.1.319", version_after="2.1.322", version="2.1.322", update_available=False, prev_version="2.1.319"), "remote": None}])[0]
        self.assertIn("ccliDone(2.1.319|2.1.322)", h)
        self.assertIn('data-ccli="rollback"', h)
        self.assertIn("ccliBtnRollback(2.1.319)", h)
        self.assertNotIn('data-ccli="update"', h)

    def test_native_and_missing_node_and_no_link(self):
        h = render([{"local": row(kind="native", path="/root/.local/bin/claude", can_update=False, update_available=False), "remote": None},
                    {"local": row(node={"ready": False}, can_update=False), "remote": None},
                    {"local": row(), "remote": {"ok": False, "error": "ssh"}},
                    {"local": row(kind=None, version=None, can_update=False), "remote": None}])
        self.assertIn("ccliNative(/root/.local/bin/claude)", h[0])
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
