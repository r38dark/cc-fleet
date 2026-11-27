"""Upgrade coverage for saved logins left behind by account switching."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cc_codex
import cc_remote
import cc_remote_mode


class Connections(unittest.TestCase):
    def test_upgrade_keeps_the_running_codex_slot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cc_codex, "PROFILES", directory):
            path = Path(directory)
            for slot in ("gpt1", "gpt2"):
                (path / slot).mkdir()
                (path / slot / "auth.json").write_text("{}")
            cc_codex.select_existing("gpt2")
            self.assertEqual(cc_codex.profile_slots(), ["gpt2"])
            cc_codex.select_existing("gpt1")
            self.assertEqual(cc_codex.profile_slots(), ["gpt2"])
            (path / "gpt2" / "auth.json").unlink()
            self.assertEqual(cc_codex.profile_slots(), [])
            self.assertTrue((path / "gpt1" / "auth.json").exists())

    def test_multiple_unselected_codex_logins_are_not_activated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cc_codex, "PROFILES", directory):
            for slot in ("gpt1", "gpt2"):
                path = Path(directory) / slot
                path.mkdir()
                (path / "auth.json").write_text("{}")
            cc_codex.select_existing()
            self.assertEqual(cc_codex.profile_slots(), [])

    def test_only_the_configured_claude_server_is_polled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            members = root / "remote_members.json"
            rows = {"unused": {"host": "192.0.2.11"}, "current": {"host": "192.0.2.12"}}
            members.write_text(json.dumps(rows))
            (root / "remote_mode.json").write_text(json.dumps({"active": True, "member": "current"}))
            with patch.object(cc_remote, "MEMBERS_FILE", str(members)):
                self.assertEqual(cc_remote.members(), {"current": rows["current"]})

    def test_remote_claude_cannot_transfer_to_local_claude(self):
        with patch.object(cc_remote_mode, "handoff_lock_message", return_value=""),                 patch.object(cc_remote_mode, "_wk", return_value=object()),                 patch.object(cc_remote_mode, "busy", return_value=False),                 patch.object(cc_remote_mode, "worker", return_value="prod"),                 patch.object(cc_remote_mode, "_member_id", return_value="current"),                 patch.object(cc_remote_mode, "_hand_job") as job:
            self.assertFalse(cc_remote_mode.handoff("dev")["ok"])
            job.assert_not_called()
