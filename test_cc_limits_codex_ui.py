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

    def test_header_split_group_profile_menu_and_gear(self):
        # «>_ Профиль ▾» и шестерёнка — одна группа; меню профилей и окно настроек — разные панели
        page = L.PAGE
        grp = re.search(r'<div class="cxgrp" id="cxGrp"[^>]*>(.*?)</div><div id="langSwitch"', page, re.S)
        self.assertTrue(grp)
        self.assertLess(grp.group(1).index('id="cxBtn"'), grp.group(1).index('id="cxGear"'))
        menu = re.search(r'<div id="cxMenu".*?</div></div>', page, re.S).group(0)
        self.assertIn('id="cxp"', menu)
        pop = page[page.index('id="cxPop"'):]
        self.assertNotIn('id="cxp"', pop[:pop.index('id="cxPopX"') + 400])

    def test_feed_markup(self):
        for i in ('id="cxFeed"', 'id="cxBar"', 'id="cvFeed"', 'id="cvScreen"', 'id="cxStatD"', 'id="cxStatT"'):
            self.assertEqual(L.PAGE.count(i), 1, i)

    def test_status_dots_reset_global_err_margin(self):
        # глобальное .err{margin-top:8px} сдвигало точки с классом err вниз от центра текста
        self.assertIn(".err{color:var(--bad);font-size:13px;margin-top:8px}", L.PAGE)
        for sel in (".cxdot.err", ".cxfsd.err", ".termdot.err"):
            m = re.search(re.escape(sel) + r"\{([^}]*)\}", L.PAGE)
            self.assertTrue(m, sel)
            self.assertIn("margin:0", m.group(1), sel)

    def test_texts_in_both_languages(self):
        keys = {lang: set(re.findall(r"^\s{2}(cx\w*):", i18n_block(lang), re.M)) for lang in ("ru", "en")}
        self.assertEqual(keys["ru"] ^ keys["en"], set())
        # cxpN_/cxpS_/cxpWhen_ — начало ключей профилей; cxoMode_/cxoAcc_/cxoRt_ — описания вариантов состава
        dyn = {"cxpN_", "cxpS_", "cxpWhen_", "cxoMode_", "cxoAcc_", "cxoRt_"}
        used = set(re.findall(r"tr\('(cx\w+)'", L.PAGE)) - dyn
        for p in ("cxpN_", "cxpS_", "cxpWhen_"):
            used |= {p + i for i in ("secretary", "orchestrator", "standby", "second", "off")}
        used |= {"cxoMode_" + i for i in ("mediator", "orchestrator", "self")}
        used |= {"cxoAcc_" + i for i in ("read", "write", "full")}
        used |= {"cxoRt_" + i for i in ("read", "dev", "full")}
        self.assertEqual(sorted(used - keys["ru"]), [])
        self.assertEqual(sorted(used - keys["en"]), [])

    def test_builtin_profiles_have_texts(self):
        import cc_codex_bridge as br
        ru = i18n_block("ru")
        for pid, _ in br.BUILTIN_PROFILES:
            self.assertIn("cxpN_%s:" % pid, ru)
            self.assertIn("cxpS_%s:" % pid, ru)


class Compose(unittest.TestCase):
    def test_save_block_moved_from_menu_to_popover(self):
        page = L.PAGE
        menu = re.search(r'<div id="cxMenu".*?</div></div>', page, re.S).group(0)
        self.assertNotIn("cxpc", menu)
        self.assertGreater(page.index('id="cxpc"'), page.index('id="cxPop"'))
        self.assertEqual(page.count('id="cxLim"'), 1)
        # старый блок «Сохранить текущие настройки» из меню профилей убран
        self.assertNotIn("cxpSaveLbl", page)
        self.assertNotIn("cxpCustom", page)

    def test_save_sends_composed_set_not_live_settings(self):
        m = re.search(r"async function cxpSave\(\)\{.*?\n\}\n", L.PAGE, re.S)
        self.assertTrue(m)
        self.assertIn("mode:d.mode,access:d.access,task_rights:d.task_rights", m.group(0))


LIM_JS = """
const LANG='ru';
const tr=(k,...a)=>a.length?k+'('+a.join(',')+')':k;
const acctEsc=s=>String(s==null?'':s);
const cxDate=i=>'D'+i.slice(0,10);
let cxData=null,cxbData=null;
%s
const now=Date.now(),iso=ms=>new Date(now+ms).toISOString();
const W=(mins,pct)=>({mins,pct,resets_at:iso(3600e3)});
const out={};
out.ok=cxLimSegs({windows:[W(300,4),W(10080,1)]});
out.levels=[80,94,95,100].map(p=>cxLimSegs({windows:[W(300,p)]})[0].lvl+(cxLimSegs({windows:[W(300,p)]})[0].full?'!':''));
out.reached=cxLimSegs({reached:true,windows:[W(300,99),W(10080,10)]}).map(s=>s.full);
out.blocked_has100=cxLimSegs({usage_allowed:false,windows:[W(300,100),W(10080,10)]}).map(s=>s.full);
out.nodata=cxLimSegs({windows:[]}).length;
out.order=cxLimSegs({windows:[W(10080,1),W(300,4)]}).map(s=>s.label);
const day=86400e3;
out.sub=[30,7,5,3,2,-1].map(d=>{const s=cxLimSub({sub_until:iso(d*day-3600e3)});return s?s.lvl+':'+s.txt:null;});
out.nosub=cxLimSub({});
out.login=cxLimHtml({login_required:true});
out.html=cxLimHtml({windows:[W(300,100),W(10080,45)],sub_until:iso(2*day)});
cxData={accounts:[{slot:'a'},{slot:'b'}]};cxbData={bridge:{slot:'b'}};out.pickB=cxLimAcc().slot;
cxbData={bridge:{slot:''}};out.pickFirst=cxLimAcc().slot;
cxData={accounts:[]};out.none=cxLimAcc();
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(__import__("shutil").which("node"), "нет node")
class Counters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        i = L.PAGE.index("function cxLimAcc(){")
        j = L.PAGE.index("function cxAccSummary(){")
        code = LIM_JS % L.PAGE[i:j]
        path = os.path.join(TMP, "lim.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout)

    def test_windows_are_5h_then_week(self):
        self.assertEqual([s["label"] for s in self.o["ok"]], ["cxS5", "cxS7"])
        self.assertEqual([s["pct"] for s in self.o["ok"]], [4, 1])
        self.assertEqual(self.o["order"], ["cxS5", "cxS7"])
        self.assertEqual(self.o["nodata"], 0)

    def test_levels_warn_80_bad_95_full_100(self):
        self.assertEqual(self.o["levels"], ["warn", "warn", "bad", "bad!"])

    def test_reached_marks_short_window_full_when_number_lags(self):
        self.assertEqual(self.o["reached"], [True, False])
        self.assertEqual(self.o["blocked_has100"], [True, False])

    def test_subscription_shown_in_header_only_in_last_week(self):
        self.assertEqual(self.o["sub"], [None, "warn:cxLimSubD(7)", "warn:cxLimSubD(5)", "bad:cxLimSubD(3)",
                                         "bad:cxLimSubD(2)", "bad:cxLimSubEnd"])
        self.assertIsNone(self.o["nosub"])

    def test_html_states(self):
        self.assertIn("cxl bad nobar", self.o["login"])
        self.assertIn("cxLimLogin", self.o["login"])
        self.assertIn("cxl bad", self.o["html"])                  # 5 ч исчерпано → красный
        self.assertIn("cxLimUntil(", self.o["html"])              # вместо процента — «до HH:MM»
        self.assertIn("45%", self.o["html"])
        self.assertIn("cxLimSub", self.o["html"])                 # подписка ≤ 7 дн. видна в шапке

    def test_account_is_the_one_bridge_uses(self):
        self.assertEqual(self.o["pickB"], "b")
        self.assertEqual(self.o["pickFirst"], "a")
        self.assertIsNone(self.o["none"])


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
            sv.assert_called_once_with("Ночной", lang=None, spec={})
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
