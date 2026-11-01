# Карточка Notion-агента: состояние из файла входа, без токенов в ответе и без сети.
# python3 -m unittest test_cc_notion -v
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cc_notion as N  # noqa: E402


class Public(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ccnt_")
        self.creds = os.path.join(self.d, "c.json")
        N.CREDS = lambda: self.creds
        self.conf = {}
        N.CONFIG = lambda: self.conf

    def write(self, doc):
        json.dump(doc, open(self.creds, "w"))

    def test_no_file_no_card(self):
        self.assertEqual(N.public(), {"available": False})

    def test_other_mcp_only_no_card(self):
        self.write({"mcpOAuth": {"plugin:context7:context7|x": {"serverName": "plugin:context7:context7",
                                                               "serverUrl": "https://mcp.context7.com/mcp", "accessToken": "t"}}})
        self.assertEqual(N.public(), {"available": False})

    def test_connected_shows_facts_without_tokens(self):
        self.write({"claudeAiOauth": {"accessToken": "SECRET-A"},
                    "mcpOAuth": {"notion|h": {"serverName": "notion", "serverUrl": "https://mcp.notion.com/mcp",
                                              "accessToken": "SECRET-N", "refreshToken": "SECRET-R",
                                              "expiresAt": 1900000000000}}})
        self.conf = {"name": "My agent", "url": "agent://s/a"}
        p = N.public()
        self.assertTrue(p["available"] and p["connected"] and p["can_refresh"])
        self.assertEqual(p["expires_at"], 1900000000)
        self.assertEqual(p["agent"], {"name": "My agent", "set": True})
        out = json.dumps(p)
        for s in ("SECRET-A", "SECRET-N", "SECRET-R", "agent://"):
            self.assertNotIn(s, out)

    def test_without_agent_in_config(self):
        self.write({"mcpOAuth": {"notion|h": {"serverName": "notion", "accessToken": "t"}}})
        p = N.public()
        self.assertEqual(p["agent"], {"name": "", "set": False})
        self.assertFalse(p["can_refresh"])
        self.assertTrue(p["connected"])

    def test_broken_file_no_card(self):
        open(self.creds, "w").write("{не json")
        self.assertEqual(N.public(), {"available": False})


if __name__ == "__main__":
    unittest.main()
