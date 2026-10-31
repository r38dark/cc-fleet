# Окно Codex в шапке: значок, выпадающее окно, маршруты профилей и парность русских/английских текстов.
# python3 -m unittest test_cc_limits_codex_ui -v
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="cccxui_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402  (после подмены путей)


def i18n_block(lang):
    """Тело словаря текстов одного языка из страницы."""
    m = re.search(r"\n %s:\{\n(.*?)\n \},?\n" % lang, L.PAGE, re.S)
    assert m, lang
    return m.group(1)


class Page(unittest.TestCase):
    def test_codex_lives_in_popover_not_under_cards(self):
        # на странице Codex места не занимает: секции лежат внутри скрытого окна, а не рядом с консолью
        page = L.PAGE
        self.assertIn('id="cxBtn"', page)
        pop = page.index('id="cxPop"')
        self.assertGreater(page.index('id="cx" '), pop)
        self.assertGreater(page.index('id="cxb" '), pop)
        self.assertRegex(page, r'<div id="cxPop"[^>]*\bhidden\b')

    def test_button_is_left_of_language_switch(self):
        self.assertLess(L.PAGE.index('id="cxBtn"'), L.PAGE.index('id="langSwitch"'))

    def test_texts_in_both_languages(self):
        keys = {lang: set(re.findall(r"^\s{2}(cx\w*):", i18n_block(lang), re.M)) for lang in ("ru", "en")}
        self.assertEqual(keys["ru"] ^ keys["en"], set())
        used = set(re.findall(r"tr\('(cx\w+)'", L.PAGE)) - {"cxpN_", "cxpS_"}  # эти два — начало ключей профилей
        for p in ("cxpN_", "cxpS_"):
            used |= {p + i for i in ("secretary", "orchestrator", "standby", "second", "off")}
        self.assertEqual(sorted(used - keys["ru"]), [])
        self.assertEqual(sorted(used - keys["en"]), [])

    def test_builtin_profiles_have_texts(self):
        import cc_codex_bridge as br
        ru = i18n_block("ru")
        for pid, _ in br.BUILTIN_PROFILES:
            self.assertIn("cxpN_%s:" % pid, ru)
            self.assertIn("cxpS_%s:" % pid, ru)


class Routes(unittest.TestCase):
    def post(self, action, body):
        got = []

        class Fake:
            def _send(self, code, obj):
                got.append((code, obj))
        with mock.patch.object(L, "codex_bin", return_value="/x/codex"):
            L.H._chatgpt_post(Fake(), action, body)
        return got[0]

    def test_profile_routes_delegate_to_bridge(self):
        with mock.patch.object(L.cc_codex_bridge, "apply_profile", return_value=(True, "ok")) as ap, \
                mock.patch.object(L.cc_codex_bridge, "save_profile", return_value=(True, "saved")) as sv, \
                mock.patch.object(L.cc_codex_bridge, "delete_profile", return_value=(False, "no")) as dl:
            self.assertEqual(self.post("bridge/profile/apply", {"id": "orchestrator", "confirm": "x", "lang": "en"}),
                             (200, {"ok": True, "message": "ok"}))
            ap.assert_called_once_with("orchestrator", "x", lang="en")
            self.assertEqual(self.post("bridge/profile/save", {"name": "Ночной"}), (200, {"ok": True, "message": "saved"}))
            sv.assert_called_once_with("Ночной", lang=None)
            self.assertEqual(self.post("bridge/profile/delete", {"id": "c1"}), (200, {"ok": False, "message": "no"}))
            dl.assert_called_once_with("c1", lang=None)

    def test_unknown_route_is_404(self):
        self.assertEqual(self.post("bridge/profile/nope", {})[0], 404)


class ProfilesDir(unittest.TestCase):
    def dir_for(self, cfg, env=None):
        base = tempfile.mkdtemp(prefix="cccxcfg_", dir=TMP)
        with open(os.path.join(base, "config.json"), "w") as f:
            json.dump(cfg, f)
        e = {k: v for k, v in os.environ.items() if k != "CC_CODEX_PROFILES"}
        e.update(CC_LIMITS_BASE=base, CC_LIMITS_PROFILES=os.path.join(base, "p"), **(env or {}))
        r = subprocess.run([sys.executable, "-c", "import cc_limits, cc_codex; print(cc_codex.PROFILES)"],
                           cwd=os.path.dirname(os.path.abspath(__file__)), env=e, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_config_key_sets_profiles_dir(self):
        self.assertEqual(self.dir_for({"codex_profiles": "/srv/gpt"}), "/srv/gpt")

    def test_env_wins_over_config(self):
        self.assertEqual(self.dir_for({"codex_profiles": "/srv/gpt"}, {"CC_CODEX_PROFILES": "/srv/env"}), "/srv/env")

    def test_default_without_both(self):
        self.assertEqual(self.dir_for({}), "/root/.codex-profiles")


if __name__ == "__main__":
    unittest.main()
