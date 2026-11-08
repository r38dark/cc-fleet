# Консольные команды балансера cl / cla / cln / clw / cxw: скрипт cc-cmd, ссылки в bin при старте сервиса, состав релиза.
# python3 -m unittest test_cc_cmd -v
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="cccmd_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base0")
# профили Claude и Codex тоже во временную папку: при общем прогоне (discover) cc_limits импортируется один раз, отсюда
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.environ["CC_CODEX_PROFILES"] = os.path.join(TMP, "cxprof")
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)
sys.path.insert(0, HERE)

import cc_limits as L  # noqa: E402  (после подмены путей)

SCRIPT = os.path.join(HERE, "cc-cmd")
# поддельный screen: пишет аргументы в журнал; «живые» сессии берёт из файла alive (по строке), как это делает screen -ls
FAKE_SCREEN = r'''#!/bin/bash
echo "$*" >> "$FAKE_LOG"
case "$1" in
    -wipe) exit 0 ;;
    -ls) [ -f "$FAKE_ALIVE" ] && while read -r n; do printf '\t1234.%s\t(Detached)\n' "$n"; done < "$FAKE_ALIVE"; exit 0 ;;
esac
exit 0
'''


def put(path, text, mode=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


class Links(unittest.TestCase):
    """cc_limits.ensure_cmd_links: ссылки создаются, чужое не трогается."""

    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        self.base = os.path.join(self.d, "base")
        self.bin = os.path.join(self.d, "bin")
        os.makedirs(self.base)
        os.makedirs(self.bin)
        put(os.path.join(self.base, "cc-cmd"), "#!/bin/bash\n", 0o755)
        p = mock.patch.object(L, "BASE", self.base)
        p.start()
        self.addCleanup(p.stop)
        # PATH — только своя папка: настоящие cl/cla/... машины разработчика результат не искажают
        p2 = mock.patch.dict(os.environ, {"PATH": self.bin})
        p2.start()
        self.addCleanup(p2.stop)

    def test_creates_all_and_is_idempotent(self):
        r = L.ensure_cmd_links(self.bin)
        self.assertEqual(set(r), {"cl", "cla", "cln", "clw", "cxw"})
        self.assertEqual(set(r.values()), {"создана"})
        for n in r:
            self.assertEqual(os.readlink(os.path.join(self.bin, n)), os.path.join(self.base, "cc-cmd"))
        self.assertEqual(set(L.ensure_cmd_links(self.bin).values()), {"есть"})

    def test_foreign_file_and_symlink_untouched(self):
        put(os.path.join(self.bin, "cl"), "чужой скрипт\n", 0o755)
        os.symlink("/usr/bin/true", os.path.join(self.bin, "cla"))
        r = L.ensure_cmd_links(self.bin)
        self.assertTrue(r["cl"].startswith("пропущена"), r)
        self.assertTrue(r["cla"].startswith("пропущена"), r)
        self.assertEqual(r["cln"], "создана")
        with open(os.path.join(self.bin, "cl"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "чужой скрипт\n")
        self.assertEqual(os.readlink(os.path.join(self.bin, "cla")), "/usr/bin/true")

    def test_name_taken_elsewhere_in_path(self):
        other = os.path.join(self.d, "other")
        os.makedirs(other)
        put(os.path.join(other, "clw"), "#!/bin/sh\n", 0o755)
        with mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + other}):
            r = L.ensure_cmd_links(self.bin)
        self.assertTrue(r["clw"].startswith("пропущена"), r)
        self.assertFalse(os.path.lexists(os.path.join(self.bin, "clw")))

    def test_own_old_link_is_moved(self):
        # установка переехала в другую папку: наша старая ссылка (имя cc-cmd) перекладывается на новое место
        os.symlink("/opt/old-place/cc-cmd", os.path.join(self.bin, "cl"))
        r = L.ensure_cmd_links(self.bin)
        self.assertEqual(r["cl"], "создана")
        self.assertEqual(os.readlink(os.path.join(self.bin, "cl")), os.path.join(self.base, "cc-cmd"))

    def test_no_script_no_links(self):
        os.remove(os.path.join(self.base, "cc-cmd"))
        self.assertEqual(L.ensure_cmd_links(self.bin), {})
        self.assertEqual(os.listdir(self.bin), [])

    def test_unwritable_dir_does_not_raise(self):
        r = L.ensure_cmd_links(os.path.join(self.d, "нет-такой-папки"))
        self.assertTrue(all(v.startswith("пропущена") for v in r.values()), r)


class Script(unittest.TestCase):
    """Сам cc-cmd: имя сессии и команда запуска из config.json, поведение каждой команды (screen — поддельный)."""

    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        self.base = os.path.join(self.d, "base")
        self.fb = os.path.join(self.d, "fakebin")
        os.makedirs(self.base)
        os.makedirs(self.fb)
        shutil.copy(SCRIPT, os.path.join(self.base, "cc-cmd"))
        # No privileged helper or real terminal access in shell unit tests.
        helper = os.path.join(self.fb, "helper")
        put(helper, "#!/bin/sh\nexit 0\n", 0o755)
        path = os.path.join(self.base, "cc-cmd")
        with open(path) as stream:
            code = stream.read().replace("/usr/local/sbin/cc-codex-console-localize", helper)
        put(path, code)
        put(os.path.join(self.fb, "sudo"), '#!/bin/sh\nshift\nexec "$@"\n', 0o755)
        put(os.path.join(self.base, "cc_codex_terminal.py"),
            "print("+repr(os.path.join(self.fb, "screen"))+")\nprint('')\n")
        os.chmod(os.path.join(self.base, "cc-cmd"), 0o755)
        for n in ("cl", "cla", "cln", "clw", "cxw"):
            os.symlink(os.path.join(self.base, "cc-cmd"), os.path.join(self.fb, n))
        put(os.path.join(self.fb, "screen"), FAKE_SCREEN, 0o755)
        self.log = os.path.join(self.d, "screen.log")
        self.alive = os.path.join(self.d, "alive")

    def cfg(self, **kw):
        put(os.path.join(self.base, "config.json"), json.dumps(kw))

    def run_cmd(self, name, *args, alive=(), inp=None):
        put(self.alive, "".join(a + "\n" for a in alive))
        env = {"PATH": self.fb + ":/usr/bin:/bin", "FAKE_LOG": self.log, "FAKE_ALIVE": self.alive, "HOME": self.d}
        r = subprocess.run([os.path.join(self.fb, name), *args], env=env, capture_output=True, text=True, timeout=30, input=inp or "")
        calls = []
        if os.path.exists(self.log):
            with open(self.log, encoding="utf-8") as f:
                calls = [l.rstrip("\n") for l in f if not l.startswith(("-wipe", "-ls"))]
            os.remove(self.log)
        return r, calls

    def test_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", SCRIPT]).returncode, 0)
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)

    def test_cl_creates_session_with_continue(self):
        self.cfg(screen_session="mysess", claude_cmd="IS_SANDBOX=1 claude --dangerously-skip-permissions")
        r, calls = self.run_cmd("cl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls[0], "-S mysess -dm bash -lc IS_SANDBOX=1 claude --dangerously-skip-permissions --continue || IS_SANDBOX=1 claude --dangerously-skip-permissions")
        self.assertEqual(calls[1], "-r mysess")

    def test_defaults_without_config(self):
        r, calls = self.run_cmd("cl")
        self.assertEqual(calls[0], "-S claude -dm bash -lc claude --continue || claude")

    def test_cl_attaches_when_alive(self):
        self.cfg(screen_session="mysess")
        r, calls = self.run_cmd("cl", alive=["mysess"])
        self.assertEqual(calls, ["-DR mysess"])

    def test_session_name_is_sanitized(self):
        # имя уходит в регулярку и в аргументы screen: с пробелом/служебными символами берём безопасное claude
        self.cfg(screen_session="a b;rm -rf")
        r, calls = self.run_cmd("cl")
        self.assertTrue(calls[0].startswith("-S claude -dm"), calls)

    def test_cla_needs_live_session(self):
        self.cfg(screen_session="mysess")
        r, calls = self.run_cmd("cla")
        self.assertEqual(r.returncode, 1)
        self.assertIn("mysess", r.stdout)
        self.assertEqual(calls, [])
        r, calls = self.run_cmd("cla", alive=["mysess"])
        self.assertEqual(calls, ["-DR mysess"])

    def test_cln_new_session_has_persistence_flag(self):
        self.cfg(screen_session="mysess", claude_cmd="claude --x")
        r, calls = self.run_cmd("cln")
        self.assertEqual(calls[0], "-S mysess -dm bash -lc CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 claude --x")

    def test_clw_recreates_with_resume(self):
        self.cfg(screen_session="mysess", claude_cmd="claude --x")
        r, calls = self.run_cmd("clw")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls[0], "-S mysess -X quit")
        self.assertEqual(calls[1], "-S mysess -dm bash -lc CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 claude --x --resume")

    def test_clw_refuses_inside_screen(self):
        env = {"PATH": self.fb + ":/usr/bin:/bin", "FAKE_LOG": self.log, "FAKE_ALIVE": self.alive, "HOME": self.d, "STY": "1.x"}
        r = subprocess.run([os.path.join(self.fb, "clw")], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("detach", r.stdout)

    def test_cxw_without_user(self):
        self.cfg(codex_user="нет_такого_пользователя_xyz")
        r, calls = self.run_cmd("cxw")
        self.assertEqual(r.returncode, 1)
        self.assertIn("не найден", r.stdout)
        self.assertEqual(calls, [])

    def test_cxw_no_session_hint(self):
        self.cfg(codex_user="root")
        r, calls = self.run_cmd("cxw")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cc-codex", r.stdout)

    def test_unknown_name(self):
        r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)

    def test_direct_call_takes_name_from_argument(self):
        self.cfg(screen_session="mysess")
        env = {"PATH": self.fb + ":/usr/bin:/bin", "FAKE_LOG": self.log, "FAKE_ALIVE": self.alive, "HOME": self.d}
        put(self.alive, "mysess\n")
        subprocess.run([os.path.join(self.base, "cc-cmd"), "cla"], env=env, capture_output=True, text=True, timeout=30)
        with open(self.log, encoding="utf-8") as f:
            self.assertIn("-DR mysess", f.read())

    # [notion-ai] 06.11: при профиле Notion AI бота Telegram слушает Notion AI — новую сессию Claude cl/cln/clw не создают
    def nai(self, doc):
        put(os.path.join(self.base, "notion_ai_mode.json"), doc if isinstance(doc, str) else json.dumps(doc))

    def test_notion_ai_profile_blocks_new_claude(self):
        self.cfg(screen_session="mysess", claude_cmd="claude --x")
        self.nai({"active": True, "kind": "solo"})
        for name in ("cl", "cln", "clw"):
            r, calls = self.run_cmd(name)
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("Notion AI", r.stdout)
            self.assertIn("notion-ai-mode off", r.stdout)
            self.assertFalse([c for c in calls if "-dm" in c or "quit" in c], (name, calls))

    def test_notion_ai_profile_still_attaches_to_live_session(self):
        self.cfg(screen_session="mysess")
        self.nai({"active": True})
        r, calls = self.run_cmd("cl", alive=["mysess"])
        self.assertEqual(calls, ["-DR mysess"])
        r, calls = self.run_cmd("cla", alive=["mysess"])
        self.assertEqual(calls, ["-DR mysess"])

    def test_notion_ai_profile_off_or_broken_file_launches_as_usual(self):
        self.cfg(screen_session="mysess", claude_cmd="claude --x")
        for doc in ({"active": False}, "{broken", "[]"):
            self.nai(doc)
            r, calls = self.run_cmd("clw")
            self.assertEqual(r.returncode, 0, (doc, r.stdout, r.stderr))
            self.assertEqual(calls[:2], ["-S mysess -X quit", "-S mysess -dm bash -lc CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 claude --x --resume"])


class Release(unittest.TestCase):
    """Скрипт входит в релиз: в манифесте автообновления и в install.sh."""

    def test_manifest_ships_cc_cmd(self):
        with open(os.path.join(HERE, "update_manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        ent = [e for e in m["files"] if e["src"] == "cc-cmd"]
        self.assertEqual(len(ent), 1)
        self.assertEqual(ent[0]["mode"], "755")
        # старый апдейтер отвергает НОВЫЕ абсолютные пути вне белого списка — файл должен ехать относительным
        self.assertNotIn("dst", ent[0])

    def test_install_script_copies_cc_cmd(self):
        with open(os.path.join(HERE, "install.sh"), encoding="utf-8") as f:
            t = f.read()
        # установщик копирует всё из update_manifest.json (module_list), поэтому cc-cmd ставится вместе с остальными файлами пакета
        self.assertIn("module_list", t)
        self.assertIn('"$SCRIPT_DIR/$src"', t)
        with open(os.path.join(HERE, "update_manifest.json"), encoding="utf-8") as f:
            self.assertIn("cc-cmd", [e["src"] for e in json.load(f)["files"]])

    def test_service_makes_links_on_start(self):
        with open(os.path.join(HERE, "cc_limits.py"), encoding="utf-8") as f:
            t = f.read()
        self.assertIn("ensure_cmd_links()", t.split('if __name__ == "__main__"')[-1])


if __name__ == "__main__":
    unittest.main()
