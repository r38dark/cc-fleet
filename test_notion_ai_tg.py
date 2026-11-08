# Мост Telegram -> чат Notion AI (notion_ai/web/notion_ai_tg.py): правило «бота слушает один агент».
# При профиле Notion AI Telegram-плагин Claude (bun ... claude-plugins-official/telegram) отключается, одно предупреждение в TG.
# Ни сеть, ни настоящие процессы, ни боевые файлы не трогаются: модуль грузится из исходника с подменённым путём .env.
# python3 -m unittest test_notion_ai_tg -v
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "notion_ai", "web", "notion_ai_tg.py")
PLUGIN = "/root/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7"


def put(path, text, binary=False):
    with open(path, "wb" if binary else "w") as f:
        f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="naitg_")
        self.addCleanup(shutil.rmtree, self.d, True)
        env = os.path.join(self.d, ".env")
        put(env, "TELEGRAM_BOT_TOKEN=123:fake\n")
        with open(SRC, encoding="utf-8") as f:
            src = f.read()
        line = 'ENV = "/root/.claude/channels/telegram/.env"'
        self.assertIn(line, src)
        self.m = types.ModuleType("notion_ai_tg_under_test")
        exec(compile(src.replace(line, "ENV = %r" % env), SRC, "exec"), self.m.__dict__)
        self.m.LOG = os.path.join(self.d, "bridge.log")
        self.proc = os.path.join(self.d, "proc")
        os.makedirs(self.proc)

    def ps(self, pid, ppid, *argv):
        p = os.path.join(self.proc, str(pid))
        os.makedirs(p)
        put(os.path.join(p, "cmdline"), b"\0".join(a.encode() for a in argv) + b"\0", binary=True)
        put(os.path.join(p, "stat"), "%s (%s) S %s 1 1 0 -1" % (pid, os.path.basename(argv[0])[:15], ppid))

    def logtext(self):
        if not os.path.exists(self.m.LOG):
            return ""
        with open(self.m.LOG, encoding="utf-8") as f:
            return f.read()


class AgentRouting(Base):
    """Сообщения из Telegram идут главному агенту или тому, кого выбрали в окне агента (tg_agent); в реестре его нет — главному."""
    AID = "a1b2c3d4-0000-0000-0000-000000000000"

    def setUp(self):
        super().setUp()
        self.m.NAI_CFG = os.path.join(self.d, "notion_ai.json")
        self.m.NAGENTS = os.path.join(self.d, "nagents.json")

    def reg(self, cfg, agents):
        import json
        put(self.m.NAI_CFG, json.dumps(cfg))
        put(self.m.NAGENTS, json.dumps({"agents": agents}))

    def test_main_agent_by_default_and_when_agent_is_unknown(self):
        self.assertEqual(self.m.tg_agent(), (None, None))  # файлов нет
        self.reg({"tg_agent": ""}, {self.AID: {"name": "Торговля"}})
        self.assertEqual(self.m.tg_agent(), (None, None))
        self.reg({"tg_agent": self.AID}, {})
        self.assertEqual(self.m.tg_agent(), (None, None))  # агента удалили — вернуться к главному

    def test_selected_agent_gets_the_messages(self):
        self.reg({"tg_agent": self.AID}, {self.AID: {"name": "Торговля"}})
        self.assertEqual(self.m.tg_agent(), (self.AID, "Торговля"))

    def test_post_adds_agent_only_when_chosen(self):
        sent = []
        self.m.dcall = lambda path, data=None, timeout=30: (sent.append((path, data)), {"id": "abcd1234", "status": "done"})[1]
        with mock.patch.object(self.m.time, "sleep", lambda s: None):
            self.assertTrue(self.m.post("привет"))
            self.assertEqual(sent[0], ("/post", {"text": "привет"}))
            self.assertTrue(self.m.post("привет", self.AID))
        self.assertEqual(sent[2], ("/post", {"text": "привет", "aid": self.AID}))


class PluginProcesses(Base):
    def tree(self):
        self.ps(50, 1, "claude", "--dangerously-skip-permissions", "--channels", "plugin:telegram@claude-plugins-official")
        self.ps(100, 50, "bun", "run", "--cwd", PLUGIN, "--shell=bun", "--silent", "start")
        self.ps(101, 100, "/root/.bun/bin/bun", "server.ts")
        self.ps(104, 101, "/root/.bun/bin/bun", "worker.ts")
        self.ps(102, 1, "bash", "-c", "pgrep -f claude-plugins-official/telegram")
        self.ps(103, 102, "grep", "claude-plugins-official/telegram")
        self.ps(105, 1, "python3", "/root/notion_web/notion_ai_tg.py")
        os.makedirs(os.path.join(self.proc, "self"))

    def test_only_bun_plugin_counts_not_shells_or_grep(self):
        self.tree()
        self.assertEqual(self.m.claude_plugin_pids(self.proc), frozenset({"100"}))

    def test_children_include_plugin_server(self):
        self.tree()
        self.assertEqual(self.m._children({"100"}, self.proc), {"100", "101", "104"})

    def test_no_plugin_nothing_found(self):
        self.ps(105, 1, "python3", "/root/notion_web/notion_ai_tg.py")
        self.assertEqual(self.m.claude_plugin_pids(self.proc), frozenset())

    def test_plugin_off_terminates_plugin_and_children_only(self):
        self.tree()
        real = (self.m.claude_plugin_pids, self.m._children)
        self.m.claude_plugin_pids = lambda: real[0](self.proc)
        self.m._children = lambda pids: real[1](pids, self.proc)
        with mock.patch("os.kill") as kill:
            killed = self.m.claude_plugin_off()
        self.assertEqual(killed, ["100", "101", "104"])
        self.assertEqual([c.args for c in kill.call_args_list], [(100, 15), (101, 15), (104, 15)])
        self.assertIn("плагин Telegram остановлен", self.logtext())

    def test_plugin_off_without_plugin_is_silent(self):
        self.m.claude_plugin_pids = lambda: frozenset()
        with mock.patch("os.kill") as kill:
            self.assertEqual(self.m.claude_plugin_off(), [])
        kill.assert_not_called()
        self.assertEqual(self.logtext(), "")


class MainLoop(Base):
    def run_main(self, modes, plugin_hits):
        modes, hits = list(modes), list(plugin_hits)
        said, polls = [], []
        self.m.mode = lambda: modes.pop(0)
        self.m.claude_plugin_off = lambda: hits.pop(0) if hits else []
        self.m.load_state = lambda: {"offset": 0}
        self.m.allowed = lambda: ["42"]
        self.m.say = lambda chat, text: said.append((chat, text))

        def tg(method, payload, timeout=40):
            polls.append(method)
            return {"result": []}
        self.m.tg = tg
        self.assertEqual(self.m.main(), 0)
        return said, polls

    def test_profile_off_exits_without_polling(self):
        said, polls = self.run_main([{"active": False}], [])
        self.assertEqual((said, polls), ([], []))
        self.assertIn("выхожу", self.logtext())

    def test_claude_plugin_found_warns_once(self):
        on = {"active": True, "since": 0}
        said, polls = self.run_main([on, on, on, {"active": False}], [["100"], ["200"], []])
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0][0], "42")
        self.assertIn("отключил ему Telegram", said[0][1])
        self.assertEqual(polls, ["getUpdates"] * 3)

    def test_no_claude_no_warning(self):
        on = {"active": True, "since": 0}
        said, polls = self.run_main([on, on, {"active": False}], [])
        self.assertEqual(said, [])
        self.assertEqual(polls, ["getUpdates"] * 2)


if __name__ == "__main__":
    unittest.main()
