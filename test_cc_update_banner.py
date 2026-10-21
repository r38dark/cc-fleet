# Тест плашки «Обновлено до версии …» и интервала проверки: python3 -m unittest test_cc_update_banner -v
# Настоящий JS из cc_limits.py (updOkNotes/updOkLoad) гоняется под node с подставными tr/fetch;
# без node тесты плашки пропускаются. Ни панель, ни /opt/cc-limits не затрагиваются.
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import cc_update

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "cc_limits.py"), encoding="utf-8").read()


def _cut(pattern, what):
    m = re.search(pattern, SRC, re.S | re.M)
    assert m, "в cc_limits.py не найдено: " + what
    return m.group(0)


ESC = _cut(r"^const ccpEsc=.*?;$", "ccpEsc")
LOGTXT = _cut(r"^function updLogTxt\(s\)\{.*?\}$", "updLogTxt")
BLOCK = _cut(r"^let updOkTry='';.*?(?=^function updSettingsRender\(\))", "updOkNotes/updOkLoad")

HARNESS = r"""
let LANG='ru';const I18N={ru:{updNotes:'Что нового'},en:{updNotes:'What’s new'}};
function tr(k){return I18N[LANG][k];}
let updLogData=INITIAL;const API='/api/',TOKEN='t';let renders=0;function updRender(){renders++;}
const fetches=[];globalThis.fetch=async u=>{fetches.push(u);return {ok:FRESH_OK,status:500,json:async()=>(FRESH)};};
%s
%s
%s
(async()=>{
 const out={};
 out.ru=updOkNotes('1.22.1');
 LANG='en';out.en=updOkNotes('1.22.1');LANG='ru';
 out.missing=updOkNotes('9.9.9');
 await new Promise(r=>setTimeout(r,20));
 out.afterLoad=updOkNotes('9.9.9');
 out.again=updOkNotes('9.9.9');
 await new Promise(r=>setTimeout(r,20));
 out.fetches=fetches.length;out.renders=renders;
 console.log(JSON.stringify(out));
})();
"""

ENTRY = {
    "v": "1.22.1", "date": "2026-10-21",
    "ru": {"t": "Заголовок <b>", "p": ["Первый пункт", "Второй `код` пункт"]},
    "en": {"t": "English title", "p": ["First point"]},
}


def run_js(initial, fresh=None, fresh_ok=True):
    d = tempfile.mkdtemp(prefix="ccbanner_")
    try:
        code = HARNESS.replace("INITIAL", json.dumps(initial)).replace("FRESH_OK", "true" if fresh_ok else "false") \
                      .replace("FRESH", json.dumps(fresh)) % (ESC, LOGTXT, BLOCK)
        p = os.path.join(d, "t.js")
        open(p, "w", encoding="utf-8").write(code)
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(shutil.which("node"), "нет node")
class OkBanner(unittest.TestCase):
    def test_notes_from_changelog_in_both_languages(self):
        o = run_js({"versions": [ENTRY]})
        self.assertIn("Что нового", o["ru"])
        self.assertIn("Первый пункт", o["ru"])
        self.assertIn("<code>код</code>", o["ru"])          # `код` оформляется как в истории изменений
        self.assertIn("Заголовок &lt;b&gt;", o["ru"])       # html из CHANGELOG экранируется
        self.assertNotIn("<b>Заголовок", o["ru"])
        self.assertIn("English title", o["en"])
        self.assertIn("First point", o["en"])
        self.assertNotIn("Второй", o["en"])

    def test_known_version_does_not_refetch(self):
        o = run_js({"versions": [ENTRY]})
        self.assertEqual(o["fetches"], 1)                     # только поиск для неизвестной 9.9.9

    def test_missing_version_refetches_once_and_rerenders(self):
        fresh = {"versions": [dict(ENTRY, v="9.9.9")]}
        o = run_js({"versions": [ENTRY]}, fresh)
        self.assertEqual(o["missing"], "")                    # пока грузится — плашка без описания
        self.assertIn("Первый пункт", o["afterLoad"])         # после перечитывания описание появилось
        self.assertEqual(o["fetches"], 1)                     # перечитали один раз, не на каждый рендер
        self.assertGreaterEqual(o["renders"], 1)

    def test_changelog_unavailable_gives_plain_banner_without_retry_storm(self):
        o = run_js(None, None, fresh_ok=False)
        self.assertEqual(o["ru"], "")
        self.assertEqual(o["missing"], "")
        self.assertEqual(o["fetches"], 2)                     # по одному разу на версию, не на каждый вызов


class CheckInterval(unittest.TestCase):
    def test_check_every_six_hours(self):
        self.assertEqual(cc_update.CHECK_EVERY, 6 * 3600)


if __name__ == "__main__":
    unittest.main()
