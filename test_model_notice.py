"""Сообщения в Telegram про смену модели/effort (cc_model_notice) и про обновления Claude Code и Codex (cc_cli_notice)."""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

import cc_cli_notice as C
import cc_model_notice as N

HERE = Path(__file__).parent


class ModelNotice(unittest.TestCase):
    def setUp(self):
        self.sent = []
        saved = (N.SEND, N.WINDOW, N.ENABLED)
        N.SEND = {"claude": lambda t: self.sent.append(("claude", t)), "codex": lambda t: self.sent.append(("codex", t))}
        N.WINDOW = 0.05
        N.ENABLED = lambda: True
        self.addCleanup(lambda: [setattr(N, k, v) for k, v in zip(("SEND", "WINDOW", "ENABLED"), saved)])

    def settle(self):
        time.sleep(0.4)

    def test_only_model_changed_shows_effort_as_unchanged(self):
        N.changed("Claude DEV", "claude", {"model": "Sonnet 5.5", "effort": "xhigh"}, {"model": "Opus 5.5", "effort": "xhigh"})
        self.settle()
        self.assertEqual(len(self.sent), 1)
        engine, text = self.sent[0]
        self.assertEqual(engine, "claude")
        self.assertIn("🔄 Claude DEV: сменили модель", text)
        self.assertIn("модель: Sonnet 5.5 → Opus 5.5", text)
        self.assertIn("effort: xhigh (без изменений)", text)

    def test_only_effort_changed_shows_model_as_unchanged(self):
        N.changed("Claude PROD", "claude", {"model": "Opus 5.5", "effort": "high"}, {"model": "Opus 5.5", "effort": "max"})
        self.settle()
        text = self.sent[0][1]
        self.assertIn("сменили effort", text)
        self.assertIn("effort: high → max", text)
        self.assertIn("модель: Opus 5.5 (без изменений)", text)

    def test_model_and_effort_in_a_row_are_one_message(self):
        N.changed("Claude DEV", "claude", {"model": "A", "effort": "low"}, {"model": "B", "effort": "low"})
        N.changed("Claude DEV", "claude", {"model": "B", "effort": "low"}, {"model": "B", "effort": "high"})
        self.settle()
        self.assertEqual(len(self.sent), 1)                       # «или всё вместе» — одно сообщение
        text = self.sent[0][1]
        self.assertIn("сменили модель и effort", text)
        self.assertIn("модель: A → B", text)
        self.assertIn("effort: low → high", text)

    def test_change_and_change_back_is_silent(self):
        N.changed("Claude DEV", "claude", {"model": "A", "effort": "low"}, {"model": "B", "effort": "low"})
        N.changed("Claude DEV", "claude", {"model": "B", "effort": "low"}, {"model": "A", "effort": "low"})
        self.settle()
        self.assertEqual(self.sent, [])

    def test_nothing_changed_nothing_sent(self):
        N.changed("Claude DEV", "claude", {"model": "A", "effort": "low"}, {"model": "A", "effort": "low"})
        N.changed("Claude DEV", "claude", {}, {})
        self.settle()
        self.assertEqual(self.sent, [])

    def test_changes_after_the_window_are_separate_messages(self):
        N.changed("Claude DEV", "claude", {"model": "A", "effort": "low"}, {"model": "B", "effort": "low"})
        self.settle()
        N.changed("Claude DEV", "claude", {"model": "B", "effort": "low"}, {"model": "B", "effort": "high"})
        self.settle()
        self.assertEqual(len(self.sent), 2)

    def test_different_executors_are_not_mixed(self):
        N.changed("Claude DEV", "claude", {"model": "A", "effort": "low"}, {"model": "B", "effort": "low"})
        N.changed("Codex · gpt1", "codex", {"model": "X", "effort": "low", "fast": False}, {"model": "Y", "effort": "low", "fast": False})
        self.settle()
        self.assertEqual(sorted(e for e, _ in self.sent), ["claude", "codex"])
        self.assertTrue(all("Claude DEV" in t for e, t in self.sent if e == "claude"))
        self.assertTrue(all("Codex · gpt1" in t for e, t in self.sent if e == "codex"))

    def test_codex_fast_is_reported_when_it_changed(self):
        N.changed("Codex", "codex", {"model": "X", "effort": "high", "fast": False}, {"model": "X", "effort": "high", "fast": True})
        self.settle()
        text = self.sent[0][1]
        self.assertIn("сменили Fast", text)
        self.assertIn("Fast: выкл → вкл", text)
        self.assertIn("модель: X (без изменений)", text)

    def test_unchanged_fast_is_not_mentioned(self):
        N.changed("Codex", "codex", {"model": "X", "effort": "high", "fast": True}, {"model": "Y", "effort": "high", "fast": True})
        self.settle()
        self.assertNotIn("Fast", self.sent[0][1])

    def test_switch_off_and_broken_sender_do_not_break_the_panel(self):
        N.ENABLED = lambda: False
        N.changed("Claude DEV", "claude", {"model": "A"}, {"model": "B"})
        self.settle()
        self.assertEqual(self.sent, [])
        N.ENABLED = lambda: True

        def boom(text):
            raise RuntimeError("telegram недоступен")
        N.SEND = {"claude": boom, "codex": boom}
        N.changed("Claude DEV", "claude", {"model": "A"}, {"model": "B"})
        self.settle()                                              # исключение в потоке сообщения не всплывает

    def test_empty_values_are_shown_as_dash(self):
        N.changed("Claude PROD", "claude", {"model": "A", "effort": ""}, {"model": "A", "effort": "high"})
        self.settle()
        self.assertIn("effort: — → high", self.sent[0][1])


def view(version="2.1.322", latest="", state="idle", finished=0, **kw):
    d = {"ok": True, "kind": "npm", "version": version, "latest": latest, "update_available": bool(latest and latest != version),
         "state": state, "finished": finished, "op": "update", "from_version": "", "version_after": "", "err": ""}
    d.update(kw)
    return d


class CliNotice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent = []
        saved = (C.STATE, C.SEND, C.ENABLED)
        C.STATE = str(Path(self.tmp.name) / "cli_notice.json")
        C.SEND = {"claude": lambda t: self.sent.append(("claude", t)), "codex": lambda t: self.sent.append(("codex", t))}
        C.ENABLED = lambda: True
        self.addCleanup(lambda: [setattr(C, k, v) for k, v in zip(("STATE", "SEND", "ENABLED"), saved)])

    def test_new_version_is_announced_once_per_version(self):
        v = {"claude@local": view(latest="2.1.323")}
        out = C.tick(v)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "claude")
        self.assertIn("⬆ Вышла новая версия Claude Code (DEV): 2.1.322 → 2.1.323", out[0][1])
        self.assertEqual(C.tick(v), [])                            # повторно про ту же версию не говорим
        self.assertEqual(len(C.tick({"claude@local": view(latest="2.1.324")})), 1)   # вышла следующая — снова

    def test_each_program_is_named_and_routed(self):
        out = C.tick({"claude@local": view(latest="2.1.323"), "claude@remote": view(latest="2.1.323"),
                      "codex@local": view("0.167.0", "0.168.0")})
        texts = {e: [t for ee, t in out if ee == e] for e in ("claude", "codex")}
        self.assertTrue(any("Claude Code (DEV)" in t for t in texts["claude"]))
        self.assertTrue(any("Claude Code (PROD)" in t for t in texts["claude"]))
        self.assertEqual(len(texts["codex"]), 1)
        self.assertIn("Codex: 0.167.0 → 0.168.0", texts["codex"][0])

    def test_first_run_does_not_replay_old_updates_but_next_one_is_reported(self):
        old = {"claude@local": view(state="done", finished=1000.0, from_version="2.1.319", version_after="2.1.322")}
        self.assertEqual(C.tick(old), [])                          # прошлое только запоминаем
        new = {"claude@local": view(state="done", finished=2000.0, from_version="2.1.322", version_after="2.1.323", version="2.1.323")}
        out = C.tick(new)
        self.assertEqual(len(out), 1)
        self.assertIn("✅ Claude Code (DEV) обновлён: 2.1.322 → 2.1.323", out[0][1])
        self.assertEqual(C.tick(new), [])                          # один раз на обновление

    def test_program_seen_later_with_old_history_is_silent_and_idle_first_sight_still_reports_next_update(self):
        C.tick({"claude@local": view()})                           # PROD ещё не отвечал по ssh
        out = C.tick({"claude@local": view(), "claude@remote": view(state="done", finished=50.0, from_version="2.1.300", version_after="2.1.322")})
        self.assertEqual(out, [])                                  # старое обновление PROD не пересказываем
        out = C.tick({"claude@local": view(), "claude@remote": view(state="done", finished=60.0, from_version="2.1.322", version_after="2.1.323", version="2.1.323")})
        self.assertEqual(len(out), 1)
        self.assertIn("Claude Code (PROD) обновлён: 2.1.322 → 2.1.323", out[0][1])
        C.tick({"codex@local": view("0.166.0")})                   # первый раз увидели в простое (finished=0)
        out = C.tick({"codex@local": view("0.167.0", state="done", finished=70.0, from_version="0.166.0", version_after="0.167.0")})
        self.assertEqual(len(out), 1)                              # и следующее обновление всё равно сообщили

    def test_success_hint_about_restart_only_when_running_on_old_version(self):
        C.tick({"claude@local": view()})
        done = view(state="done", finished=5.0, from_version="2.1.322", version_after="2.1.323", version="2.1.323")
        out = C.tick({"claude@local": dict(done, restart={"running": True, "stale": True})})
        self.assertIn("Перезапустить Claude", out[0][1])
        done2 = view(state="done", finished=6.0, from_version="2.1.323", version_after="2.1.324", version="2.1.324")
        out = C.tick({"claude@local": dict(done2, restart={"running": False, "stale": False})})
        self.assertNotIn("Перезапустить", out[0][1])

    def test_codex_success_and_hint(self):
        C.tick({"codex@local": view("0.166.0")})
        done = view("0.167.0", state="done", finished=9.0, from_version="0.166.0", version_after="0.167.0",
                    restart={"running": True, "stale": True})
        out = C.tick({"codex@local": done})
        self.assertEqual(out[0][0], "codex")
        self.assertIn("✅ Codex обновлён: 0.166.0 → 0.167.0", out[0][1])
        self.assertIn("Перезапустить консоль Codex", out[0][1])

    def test_failure_and_rollback_and_nothing_new(self):
        C.tick({"claude@local": view()})
        out = C.tick({"claude@local": view(state="failed", finished=3.0, err="npm: нет сети\nдальше мусор")})
        self.assertTrue(out[0][1].startswith("❌ Обновление Claude Code (DEV) не удалось: npm: нет сети"))
        out = C.tick({"claude@local": view(state="done", finished=4.0, op="rollback", version_after="2.1.319", version="2.1.319")})
        self.assertIn("↩ Claude Code (DEV) возвращён на версию 2.1.319", out[0][1])
        out = C.tick({"claude@local": view(state="done", finished=5.0, from_version="2.1.319", version_after="2.1.319", version="2.1.319")})
        self.assertIn("версия не изменилась (2.1.319)", out[0][1])

    def test_running_update_is_not_announced_as_available_and_bad_views_are_skipped(self):
        self.assertEqual(C.tick({"claude@local": view(latest="2.1.323", state="running")}), [])
        self.assertEqual(C.tick({"claude@local": {"ok": False}, "claude@remote": None, "codex@local": {"ok": True},
                                 "неизвестный": view(latest="9.9.9")}), [])

    def test_switch_off_and_broken_sender(self):
        C.ENABLED = lambda: False
        self.assertEqual(C.tick({"claude@local": view(latest="2.1.323")}), [])
        C.ENABLED = lambda: True

        def boom(text):
            raise RuntimeError("telegram недоступен")
        C.SEND = {"claude": boom, "codex": boom}
        self.assertEqual(len(C.tick({"claude@local": view(latest="2.1.323")})), 1)   # сторож не падает

    def test_state_survives_restart_of_the_panel(self):
        C.tick({"claude@local": view(latest="2.1.323")})
        self.assertEqual(json.loads(Path(C.STATE).read_text(encoding="utf-8"))["latest"], {"claude@local": "2.1.323"})
        self.assertEqual(C.tick({"claude@local": view(latest="2.1.323")}), [])        # «после перезапуска» — как будто тот же файл


class Wiring(unittest.TestCase):
    def test_panel_is_wired_to_both_notifiers(self):
        src = (HERE / "cc_limits.py").read_text(encoding="utf-8")
        for part in ('cc_model_notice.changed("Claude DEV", "claude", before, _model_notice_state())',
                     'cc_model_notice.changed("Claude DEV", "claude", before, _model_notice_state(smid, top))',
                     'name="cc-cli-notice"', "cc_cli_notice.tick(views)", "cc_cli_notice.STATE = os.path.join(BASE, \"cli_notice.json\")",
                     '"model_change_notify"', '"cli_update_notify"', "cc_codex_bridge.BRIDGE.send(text)"):
            self.assertIn(part, src, part)

    def test_codex_rotation_does_not_make_noise_and_prod_is_wired(self):
        self.assertIn("notify=False", (HERE / "cc_codex_rotation.py").read_text(encoding="utf-8"))
        self.assertIn('"Claude PROD", "claude"', (HERE / "cc_remote_mode.py").read_text(encoding="utf-8"))
        self.assertIn('def set_prefs(bin_path, slot, model, effort, fast, lang="ru", notify=True):', (HERE / "cc_codex.py").read_text(encoding="utf-8"))

    def test_modules_are_in_the_update_manifest(self):
        files = {f["src"] for f in json.loads((HERE / "update_manifest.json").read_text(encoding="utf-8"))["files"]}
        self.assertTrue({"cc_model_notice.py", "cc_cli_notice.py"} <= files)


if __name__ == "__main__":
    unittest.main()
