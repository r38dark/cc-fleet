"""Unit tests for Antigravity (agy) independent executor modules."""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cc_agy
import cc_agy_bridge
import cc_agy_limits
import cc_agy_quota
import cc_agy_ui


SAMPLE_USAGE = """
Antigravity CLI 1.5.18
user@example.com (Google AI Pro)
GEMINI MODELS
Models within this group: Gemini 4 Neon, Gemini 4 Carbon, Gemini 4 Hydrogen
Weekly Limit Remaining
[████████████████████] 97.50%
Refreshes in 6d 10h 30m
Five Hour Limit Remaining
[██████████████████░░] 89.20%
Refreshes in 3h 15m
CLAUDE AND GPT MODELS
Weekly Limit Remaining
[████████████████████] 100.00%
Quota available
Five Hour Limit Remaining
[████████████████████] 100.00%
Quota available
"""


class TestAgyParsing(unittest.TestCase):
    def test_parse_usage_gemini_only(self):
        now = 1795800000.0
        parsed = cc_agy.parse_usage_text(SAMPLE_USAGE, fetched_at=now)
        self.assertEqual(parsed["email"], "user@example.com")
        self.assertEqual(parsed["plan"], "pro")
        self.assertEqual(parsed["plan_label"], "PRO")
        wins = {w["mins"]: w for w in parsed["windows"]}
        self.assertEqual(set(wins), {300, 10080})
        self.assertAlmostEqual(wins[300]["pct"], 10.8, places=1)
        self.assertAlmostEqual(wins[10080]["pct"], 2.5, places=1)
        self.assertTrue(wins[300]["resets_at"].endswith("Z"))
        self.assertTrue(wins[10080]["resets_at"].endswith("Z"))

    def test_sub_date_parsing(self):
        self.assertEqual(cc_agy.normalize_sub_until("28.12.2026"), "2026-12-28")
        self.assertEqual(cc_agy.normalize_sub_until("2026-12-28"), "2026-12-28")
        self.assertIsNone(cc_agy.normalize_sub_until("not-a-date"))
        self.assertEqual(cc_agy.normalize_sub_until(""), "")


class TestAgyLimitsAndOverride(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test-agy-lim-")
        self.orig_base = cc_agy.BASE
        cc_agy.BASE = self.tmp

    def tearDown(self):
        cc_agy.BASE = self.orig_base

    def _make_account(self, p5, p7, now, r5=3600, r7=86400):
        iso5 = dt.datetime.fromtimestamp(now + r5, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        iso7 = dt.datetime.fromtimestamp(now + r7, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "slot": cc_agy.SLOT,
            "label": "Antigravity",
            "email": "user@example.com",
            "plan": "pro",
            "windows": [
                {"mins": 300, "pct": p5, "resets_at": iso5},
                {"mins": 10080, "pct": p7, "resets_at": iso7},
            ],
            "reached": p5 >= 100 or p7 >= 100,
            "usage_allowed": not (p5 >= 100 or p7 >= 100),
            "ts": now,
        }

    def test_weekly_cap_99_pause_and_last_percent_override(self):
        now = time.time()
        lim = cc_agy_limits.AccountLimits(self.tmp, cc_agy, None, lambda: "/bin/true", None)
        lim.accounts = [self._make_account(40.0, 99.0, now)]

        # 99% weekly triggers soft policy pause (can_override=True)
        pause = lim.limit_pause(now=now)
        self.assertTrue(pause["active"])
        self.assertTrue(pause["policy"])
        self.assertFalse(pause["hard"])
        self.assertTrue(pause["can_override"])
        self.assertIn(10080, pause["windows"])

        # User disables pause to work on the last 1% of the week
        ok, _ = lim.configure({"pause_override": True})
        self.assertTrue(ok)
        pause2 = lim.limit_pause(now=now)
        self.assertFalse(pause2["active"])
        self.assertTrue(pause2["override"])

        # Notice remains visible for UI so "Включить паузу" stays shown
        notice = lim.limit_notice(now=now)
        self.assertTrue(notice["active"])
        self.assertTrue(notice["override"])

        # Once weekly window resets (pct drops), override auto-clears
        lim.accounts = [self._make_account(10.0, 1.0, now + 10)]
        pause3 = lim.limit_pause(now=now + 10)
        self.assertFalse(pause3["active"])
        self.assertFalse(pause3["override"])
        self.assertFalse(lim.state["pause_override"])

    def test_hard_100_rejects_override(self):
        now = time.time()
        lim = cc_agy_limits.AccountLimits(self.tmp, cc_agy, None, lambda: "/bin/true", None)
        lim.accounts = [self._make_account(50.0, 100.0, now)]

        pause = lim.limit_pause(now=now)
        self.assertTrue(pause["active"])
        self.assertTrue(pause["hard"])
        self.assertFalse(pause["can_override"])

        ok, _ = lim.configure({"pause_override": True})
        self.assertFalse(ok)

    def test_quota_guard_fallback_holds_active_pause_on_unknown(self):
        now = time.time()
        lim = cc_agy_limits.AccountLimits(self.tmp, cc_agy, None, lambda: "/bin/true", None)
        guard = cc_agy_quota.Guard(self.tmp, lim, None, None)
        guard.state = {"last_pause": {"active": True, "hard": False, "resume_at": now + 600}}
        res = guard.fallback({"active": False, "unknown": True}, override=False)
        self.assertTrue(res["active"])
        self.assertTrue(res["unknown"])

        # Expired resume_at releases fallback
        guard.state = {"last_pause": {"active": True, "hard": False, "resume_at": now - 300}}
        res2 = guard.fallback({"active": False, "unknown": True}, override=False)
        self.assertFalse(res2["active"])


class TestAgyBridgeAndUI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test-agy-br-")
        self.orig_base = cc_agy_bridge.BASE
        cc_agy_bridge.BASE = self.tmp

    def tearDown(self):
        cc_agy_bridge.BASE = self.orig_base

    def test_markdown_and_image_extraction(self):
        html_out = cc_agy_bridge.markdown_to_telegram_html("### Заголовок\n**жирный** и `код` [f.py](file:///tmp/f.py)")
        self.assertIn("<b>Заголовок</b>", html_out)
        self.assertIn("<b>жирный</b>", html_out)
        self.assertIn("<code>код</code>", html_out)
        self.assertIn("f.py", html_out)
        self.assertNotIn("<code>f.py</code>", html_out)

        img_path = Path(self.tmp) / "pic.png"
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="PNG")
        img_path.write_bytes(buf.getvalue())

        clean, imgs = cc_agy_bridge.extract_outgoing_images(
            f"Текст\n![Подпись]({img_path})\n```\n![В коде]({img_path})\n```",
            self.tmp,
        )
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0][2], "image/png")
        self.assertIn("![В коде]", clean)
        self.assertNotIn(f"![Подпись]({img_path})", clean)

    def test_render_limits_card_png_gemini_only(self):
        acc = {
            "email": "user@example.com",
            "plan_label": "PRO",
            "sub_until": "2026-12-28",
            "model": "Gemini 4 Neon (High)",
            "windows": [
                {"mins": 300, "pct": 12.5, "resets_at": "2026-11-28T15:00:00Z"},
                {"mins": 10080, "pct": 3.0, "resets_at": "2026-12-05T10:00:00Z"},
            ],
            "ts": time.time(),
        }
        png = cc_agy_bridge.render_limits_card_png(acc, {"context_tokens": 12000, "turns": 5}, True, False, {})
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_reserved_token_protection(self):
        orig_res = cc_agy_bridge.RESERVED_TOKENS
        try:
            cc_agy_bridge.RESERVED_TOKENS = lambda: {"123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ12345"}
            ok, msg = cc_agy_bridge.set_token("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ12345")
            self.assertFalse(ok)
            self.assertIn("уже используется", msg)
        finally:
            cc_agy_bridge.RESERVED_TOKENS = orig_res

    def test_ui_inject(self):
        page = "<html><head></head><body><div>ok</div></body></html>"
        out = cc_agy_ui.inject(page)
        self.assertIn('id="fleetAgyStyle"', out)
        self.assertIn('id="fleetAgyScript"', out)
        self.assertIn("agyInstPop", out)
        self.assertIn("agy/install/start", out)
        self.assertIn("agy/login/submit", out)

    def test_extract_wrapped_oauth_url(self):
        screen = (
            "Your browser should open automatically. If not:\n"
            "https://accounts.google.com/o/oauth2/auth?access_type=offline&client_id=12345.apps\n"
            ".googleusercontent.com&response_type=code&state=abc123\n"
            "If you aren't automatically redirected, paste the authorization code below:\n"
            "authorization code...\n"
        )
        url = cc_agy._extract_oauth_url(screen)
        self.assertEqual(
            url,
            "https://accounts.google.com/o/oauth2/auth?access_type=offline&client_id=12345.apps.googleusercontent.com&response_type=code&state=abc123",
        )

    def test_install_and_login_status_shapes(self):
        ins = cc_agy.install_status()
        self.assertTrue(ins["ok"])
        self.assertIn("installed", ins)
        self.assertIn("state", ins)
        lg = cc_agy.login_status()
        self.assertTrue(lg["ok"])
        self.assertIn("signed_in", lg)
        ok, _ = cc_agy.login_submit("")
        self.assertFalse(ok)

    def test_bootstrap_config_and_onboarding_action(self):
        with tempfile.TemporaryDirectory(prefix="test-agy-boot-") as td:
            sp = Path(td) / "settings.json"
            jp = Path(td) / "jetski_state.pbtxt"
            ob = Path(td) / "cache" / "onboarding.json"
            gp = Path(td) / "config" / "GEMINI.md"
            gp.parent.mkdir(parents=True, exist_ok=True)
            gp.write_text("# My Custom Rule\n- keep me\n", encoding="utf-8")
            with mock.patch.object(cc_agy, "SETTINGS_PATH", sp), \
                 mock.patch.object(cc_agy, "JETSKI_STATE_PATH", jp), \
                 mock.patch.object(cc_agy, "ONBOARDING_CACHE_PATH", ob), \
                 mock.patch.object(cc_agy, "GEMINI_MD_PATH", gp):
                ok, changed = cc_agy.ensure_bootstrap_config(workdir=td)
                self.assertTrue(ok)
                self.assertEqual(set(changed), {"settings.json", "jetski_state.pbtxt", "onboarding.json", "GEMINI.md"})
                ob_data = json.loads(ob.read_text(encoding="utf-8"))
                self.assertTrue(ob_data["onboardingComplete"])
                self.assertTrue(ob_data["consumerOnboardingComplete"])
                cfg = json.loads(sp.read_text(encoding="utf-8"))
                self.assertTrue(cfg["allowNonWorkspaceAccess"])
                self.assertEqual(cfg["toolPermission"], "always-proceed")
                self.assertEqual(cfg["artifactReviewPolicy"], "always-proceed")
                self.assertIn(td, cfg["trustedWorkspaces"])
                self.assertIn("POST_ONBOARDING_STEP_TYPE_ADD_WORKSPACE", jp.read_text(encoding="utf-8"))
                md = gp.read_text(encoding="utf-8")
                self.assertIn("# My Custom Rule", md)
                self.assertIn(cc_agy.TELEGRAM_GUIDELINES_MARKER, md)
                # Second call is idempotent
                ok2, changed2 = cc_agy.ensure_bootstrap_config(workdir=td)
                self.assertTrue(ok2)
                self.assertEqual(changed2, [])

        self.assertEqual(cc_agy._onboarding_action("Terms of Service\n> Previous   [Done]Confirm"), (b"\t", b"\x1b[C", b"\r"))
        self.assertEqual(cc_agy._onboarding_action("Do you trust this workspace?"), (b"\r",))
        self.assertIsNone(cc_agy._onboarding_action("? for shortcuts"))

    def test_cli_status_and_gemini_model_filter(self):
        self.assertEqual(cc_agy._vtuple("1.5.19"), (1, 5, 19))
        self.assertTrue(cc_agy._vtuple("1.6.0") > cc_agy._vtuple("1.5.19"))
        filtered = cc_agy.gemini_models_only([
            {"id": "gemini-4-neon-high", "name": "Gemini 4 Neon"},
            {"id": "claude-opus-5", "name": "Claude Opus 5"},
            {"id": "gpt-oss-120b", "name": "GPT"},
        ])
        self.assertEqual([m["id"] for m in filtered], ["gemini-4-neon-high"])
        st = cc_agy.cli_status(check=False, running=True, busy=False, started_version="1.5.18")
        self.assertTrue(st["ok"])
        self.assertIn("restart", st)
        out = cc_agy_ui.inject("<html><head></head><body></body></html>")
        self.assertIn("window.limxState", out)
        self.assertIn("window.ccpsWindows", out)
        self.assertIn("window.ccliPvInfo", out)
        self.assertIn("agy/models/check", out)
        self.assertIn("'gemini-4-hydrogen-high':'4 Hydrogen'", out)

    def test_ask_skips_empty_transient_planner_response_before_retry(self):
        import cc_agy_console
        src = Path(cc_agy_console.__file__).read_text(encoding="utf-8")
        self.assertIn('if ev.get("status") == "DONE" and not tcs and content:', src)
        self.assertIn("if _tui_busy():", src)

    def test_desktop_console_fit_and_top_tab_limit_bars_injected(self):
        out = cc_agy_ui.inject("<html><head></head><body></body></html>")
        self.assertIn("fitDesktopConsole", out)
        self.assertIn("--agy-desk-term-h", out)
        self.assertIn("--agy-desk-split-h", out)
        self.assertIn("renderTabLimits", out)
        self.assertIn("agy-tab-lim", out)
        self.assertIn("syncWkAgy", out)


if __name__ == "__main__":
    unittest.main()
