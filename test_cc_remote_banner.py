# Баннер «Уперлись в лимиты — переключаться некуда» при работе на Claude PROD (, 07.11.26):
# python3 -m unittest test_cc_remote_banner -v
# Настоящий JS ccpRender из cc_limits.py гоняется под node с подставными tr/$; без node JS-тесты пропускаются.
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="ccrb_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402  (после подмены путей)
import pause_ctl  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "cc_limits.py"), encoding="utf-8").read()


def _cut(pattern, what):
    m = re.search(pattern, SRC, re.S | re.M)
    assert m, "в cc_limits.py не найдено: " + what
    return m.group(0)


JS = "\n".join([
    _cut(r"^const ccpEsc=.*?;$", "ccpEsc"),
    _cut(r"^function ccpLeft\(untilMs\)\{.*?^\}$", "ccpLeft"),
    _cut(r"^function ccpAt\(ms\)\{.*?\}$", "ccpAt"),
    _cut(r"^function ccpWhy\(a,thr,wcap\)\{.*?^\}$", "ccpWhy"),
    _cut(r"^function ccpHeld\(a\)\{.*?^\}$", "ccpHeld"),
    _cut(r"^function ccpRender\(\)\{.*?^\}$", "ccpRender"),
])

HARNESS = r"""
const LANG='ru',CCP_GRACE=120;
function tr(k,...a){return k+'('+a.join('|')+')';}
const el={hidden:true,className:'',innerHTML:''};
function $(s){return s==='#ccPause'?el:null;}
let ccpData=null;
%s
const out=[];
for(const d of CASES){ccpData=d;el.hidden=true;el.innerHTML='';ccpRender();out.push({hidden:el.hidden,html:el.innerHTML});}
console.log(JSON.stringify(out));
"""

HARD = {"level": "hard", "active": "acc3", "threshold": 90, "weekly_cap": 99, "stale": False,
        "accounts": {"acc3": {"pct": 91, "wpct": 62, "held": "сессия", "ses_ok": False, "usable": False, "active": True}},
        "pause": {"active": False, "override": False}, "nearest": {"acc": "acc3", "resets_at": "2026-11-07T17:00:00+00:00"}}


def render(cases):
    p = os.path.join(TMP, "h.js")
    with open(p, "w", encoding="utf-8") as f:
        f.write(("const CASES=%s;\n" % json.dumps(cases, ensure_ascii=False)) + HARNESS % JS)
    r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr[-800:])
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "нет node")
class Banner(unittest.TestCase):
    def case(self, **kw):
        d = json.loads(json.dumps(HARD))
        for k, v in kw.items():
            d[k] = v
        return d

    def test_hard_without_remote_still_shows_nowhere(self):
        r = render([self.case()])[0]
        self.assertFalse(r["hidden"])
        self.assertIn("ccpHardTitle", r["html"])

    def test_dev_limit_levels_hidden_while_work_is_on_prod(self):
        for lvl in ("hard", "week", "weekrisk", "gate"):
            r = render([self.case(level=lvl, remote=True)])[0]
            self.assertTrue(r["hidden"], lvl)
            self.assertEqual(r["html"], "", lvl)

    def test_real_pause_banner_kept_while_on_prod(self):
        # стоящая пауза и отключённая кнопкой пауза — не «некуда», их баннер остаётся
        pz = {"active": True, "override": False, "kind": "session", "reason": "лимиты", "resume_at": 0}
        r = render([self.case(remote=True, pause=pz)])[0]
        self.assertFalse(r["hidden"])
        self.assertIn("ccpPauseTitle", r["html"])


class PauseState(unittest.TestCase):
    def test_api_pause_reports_remote_flag(self):
        for active in (True, False):
            with mock.patch.object(pause_ctl, "level_state", return_value={"level": "hard", "pause": {"active": False}}), \
                    mock.patch.object(pause_ctl, "_remote_active", return_value=active):
                d = L.pause_state()
            self.assertTrue(d["ok"])
            self.assertEqual(d["level"], "hard")  # сам уровень не меняется: по нему решает автовозврат
            self.assertIs(d["remote"], active)


def tearDownModule():
    shutil.rmtree(TMP, True)


if __name__ == "__main__":
    unittest.main()
