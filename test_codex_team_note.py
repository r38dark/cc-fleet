"""Фраза про других исполнителей для Codex и права записи сверх своей папки — из config.json балансера.
Без ключей в config.json всё как раньше; с ключами — текст владельца в developer_instructions, AGENTS.md и строке в начале сообщений."""
import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path

import cc_codex_bridge as B
import cc_profiles as P

HERE = Path(__file__).parent
TEAM = ("Claude и Codex — одна команда. Они переписываются напрямую через почту в общей папке {без подтверждения}. "
        "Балансер задания между ними не передаёт.")
OLD_BRIDGE = "Claude не используется."
OLD_PROFILE = "Другой исполнитель не используется."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_base = B.BASE
        B.BASE = self.tmp.name
        self.addCleanup(setattr, B, "BASE", self.old_base)

    def config(self, **kw):
        (Path(self.tmp.name) / "config.json").write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")


class TeamNote(Base):
    def test_default_when_no_config_or_key_is_empty_or_wrong_type(self):
        self.assertEqual(B.team_note(OLD_BRIDGE), OLD_BRIDGE)            # config.json нет
        for bad in (None, "", "   ", 5, ["x"], {"a": 1}):
            self.config(codex_team_note=bad)
            self.assertEqual(B.team_note(OLD_BRIDGE), OLD_BRIDGE, bad)
        (Path(self.tmp.name) / "config.json").write_text("{не json", encoding="utf-8")
        self.assertEqual(B.team_note(OLD_BRIDGE), OLD_BRIDGE)            # битый файл не ломает запуск Codex

    def test_note_from_config_is_used_and_trimmed_and_picked_up_without_restart(self):
        self.config(codex_team_note="  " + TEAM + "\n")
        self.assertEqual(B.team_note(OLD_BRIDGE), TEAM)
        self.config(codex_team_note="другое")
        self.assertEqual(B.team_note(OLD_BRIDGE), "другое")              # читается при каждом вызове

    def test_writable_roots_only_absolute_strings_from_a_list(self):
        self.assertEqual(B.extra_writable_roots(), [])                  # ключа нет
        self.config(codex_writable_roots=["/srv/team-mail", "relative/dir", 5, None, "/srv/x"])
        self.assertEqual(B.extra_writable_roots(), ["/srv/team-mail", "/srv/x"])
        for bad in ("/srv/team-mail", {"a": "/x"}, 7):
            self.config(codex_writable_roots=bad)
            self.assertEqual(B.extra_writable_roots(), [], bad)          # не список — игнорируем, а не режем строку по буквам


class Places(Base):
    """Все три места, где Codex читал «другой исполнитель не используется»."""

    def test_developer_instructions_solo_profile(self):
        state = types.SimpleNamespace(public=lambda: {"engines": {"codex": {"label": "Codex Full · самостоятельно", "role": "solo"}}})
        fake = types.SimpleNamespace(bridge=B)
        before = P.NativeProfiles.prompt(fake, state, "codex")
        self.assertIn(OLD_PROFILE, before)                              # по умолчанию — прежний текст
        self.config(codex_team_note=TEAM)
        after = P.NativeProfiles.prompt(fake, state, "codex")
        self.assertIn(TEAM, after)
        self.assertNotIn(OLD_PROFILE, after)
        for keep in ("[Профиль балансера: Codex Full · самостоятельно.]", "Согласование изменений с человеком сохраняется", "секреты не выводи"):
            self.assertIn(keep, after)                                  # остальной текст профиля на месте

    def test_note_at_start_of_messages(self):
        old = B.SOLO_PROFILE
        B.SOLO_PROFILE = lambda: True
        self.addCleanup(setattr, B, "SOLO_PROFILE", old)
        self.assertIn(OLD_BRIDGE, B.solo_note())
        self.config(codex_team_note=TEAM)
        note = B.solo_note()
        self.assertTrue(note.startswith("[Профиль Codex Full: работаешь самостоятельно. ") and note.endswith("]"))
        self.assertIn(TEAM, note)
        self.assertNotIn(OLD_BRIDGE, note)
        B.SOLO_PROFILE = lambda: False
        self.assertEqual(B.solo_note(), "")                            # вне самостоятельного профиля строки нет, как раньше

    def test_agents_md_is_rewritten_while_it_has_our_mark_and_left_alone_after_a_human_edit(self):
        ws = Path(self.tmp.name) / "work"
        saved = {k: getattr(B, k) for k in ("workspace_dir", "active_profile", "project_dir", "image_output_note", "PROFILE_NOTE")}
        B.workspace_dir = lambda: str(ws)
        B.active_profile = lambda s: "codex_solo_full"
        B.project_dir = lambda s: "/proj"
        B.image_output_note = lambda s: ""
        B.PROFILE_NOTE = lambda: ""
        old_own = B.cc_codex.own
        B.cc_codex.own = lambda p: None
        self.addCleanup(lambda: [setattr(B, k, v) for k, v in saved.items()])
        self.addCleanup(setattr, B.cc_codex, "own", old_own)
        s = {"access": "full", "workdir": str(ws), "mode": "self"}
        B.ensure_workspace(s)
        agents = ws / "AGENTS.md"
        self.assertIn(OLD_BRIDGE, agents.read_text(encoding="utf-8"))
        self.config(codex_team_note=TEAM)
        B.ensure_workspace(s)                                            # смена настройки доезжает в файл, пока метка на месте
        text = agents.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(B.AGENTS_MARK))
        self.assertIn(TEAM, text)
        self.assertNotIn(OLD_BRIDGE, text)
        for keep in ("Секреты не выводи", "согласование изменений с человеком", "Выполняй работу самостоятельно"):
            self.assertIn(keep, text)
        agents.write_text("правка человека без метки", encoding="utf-8")
        B.ensure_workspace(s)
        self.assertEqual(agents.read_text(encoding="utf-8"), "правка человека без метки")

    def test_braces_in_note_do_not_break_the_agents_template(self):
        self.assertIn("{team}", B.AGENTS_SELF_FULL_TEXT)                # подстановка через format: фигурные скобки в тексте владельца безопасны
        self.assertEqual(B.AGENTS_SELF_FULL_TEXT.format(project="p", team="{x}").count("{x}"), 1)


class RoleText(Base):
    """Текст роли для Claude на втором сервере (профиль Full): та же фраза из config.json."""

    def sent(self):
        import cc_remote_mode as M
        sent = []
        saved = {k: getattr(M, k) for k in ("_member_id", "prod_send")}
        saved_members = M.R.members
        M._member_id = lambda: "p"
        M.R.members = lambda: {"p": {"host": "h"}}
        M.prod_send = lambda text, wait=30: (sent.append(text), (True, ""))[1]
        self.addCleanup(lambda: [setattr(M, k, v) for k, v in saved.items()])
        self.addCleanup(setattr, M.R, "members", saved_members)
        self.assertTrue(M.announce_role("solo"))
        return sent[0]

    def test_default_text_without_key_and_team_text_with_key(self):
        self.assertIn("Второй исполнитель (Codex) не используется.", self.sent())
        self.config(codex_team_note=TEAM)
        text = self.sent()
        self.assertIn(TEAM, text)
        self.assertNotIn("не используется", text)
        for keep in ("Профиль балансера: Claude PROD Full", "Telegram у тебя включён", "telegram reply"):
            self.assertIn(keep, text)

    def test_percent_sign_in_note_is_safe(self):
        self.config(codex_team_note="лимит 50% и %(orch)s")              # значение подставляется как есть, второй раз не разбирается
        self.assertIn("лимит 50% и %(orch)s", self.sent())


class Wiring(unittest.TestCase):
    def test_codex_launch_args_take_extra_roots_and_panel_text_has_no_voice_remark(self):
        src = (HERE / "cc_profiles.py").read_text(encoding="utf-8")
        m = re.search(r"def codex_mcp\(\):.*?\n    console\.MCP", src, re.S)
        self.assertIn("native.bridge.extra_writable_roots()", m.group(0))   # writable_roots = своя папка обмена + из config.json
        self.assertIn("sandbox_workspace_write.writable_roots=", m.group(0))
        self.assertLess(m.group(0).index("bridge.ensure_exchange()"), m.group(0).index("sandbox_workspace_write"))   # AGENTS.md свежий до запуска Codex
        panel = (HERE / "cc_remote_mode.py").read_text(encoding="utf-8")
        self.assertNotIn("голос .ogg", panel)
        self.assertNotIn("как требует CLAUDE.md", panel)
        self.assertIn("отвечай владельцу через telegram reply.", panel)     # остальное указание гостю на месте


if __name__ == "__main__":
    unittest.main()
