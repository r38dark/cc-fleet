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
    _cut(r"^function ccpAgents\(d\)\{.*?^\}$", "ccpAgents"),
    _cut(r"^function ccpRender\(\)\{.*?^\}$", "ccpRender"),
])

HARNESS = r"""
const LANG='ru';
const document={getElementById:()=>null};
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

    def test_dev_pause_banner_hidden_while_work_is_on_prod(self):
        # пауза по лимитам, «пауза отключена» и ручной выбор относятся к DEV: работа идёт на PROD, баннер не нужен (пауза видна на плитке)
        for kind in ("session", "week"):
            pz = {"active": True, "override": False, "kind": kind, "reason": "лимиты", "resume_at": 0}
            r = render([self.case(remote=True, pause=pz)])[0]
            self.assertTrue(r["hidden"], kind)
            self.assertEqual(r["html"], "", kind)
        off = {"active": False, "override": True}
        r = render([self.case(remote=True, level="none", pause=off)])[0]
        self.assertTrue(r["hidden"])
        r = render([self.case(remote=True, level="manual", pause={"active": False, "override": False}, manual={"account": "acc3", "until": 0})])[0]
        self.assertTrue(r["hidden"])

    def test_old_service_pause_record_is_hidden_while_on_prod_like_any_limits_pause(self):
        # запись прежнего служебного вида паузы — обычная пауза: при работе на PROD баннер DEV не показывается
        pz = {"active": True, "override": False, "kind": "reserve", "reason": "старая запись", "resume_at": 0}
        r = render([self.case(remote=True, pause=pz)])[0]
        self.assertTrue(r["hidden"])

    def test_pause_banner_shown_while_work_is_on_dev(self):
        pz = {"active": True, "override": False, "kind": "week", "reason": "лимиты", "resume_at": 0}
        r = render([self.case(remote=False, pause=pz)])[0]
        self.assertFalse(r["hidden"])
        self.assertIn("ccpPauseTitle", r["html"])


    # владелец 62577: пока автопередача вот-вот отдаст работу Claude PROD, «некуда» не правда — баннер говорит «ищу»
    def test_search_banner_while_handoff_is_coming(self):
        for lvl in ("hard", "week", "weekrisk"):
            r = render([self.case(level=lvl, handoff="у Claude DEV нет лимита, на Claude PROD есть")])[0]
            self.assertFalse(r["hidden"], lvl)
            self.assertIn("ccpSearchTitle", r["html"], lvl)
            self.assertNotIn("ccpHardTitle", r["html"], lvl)
            self.assertNotIn("ccp-btn", r["html"], lvl)    # «Отключить паузу» не нужна: паузы нет
            self.assertNotIn("ccp-timer", r["html"], lvl)  # таймера «до сброса» тоже: ждать сброса не придётся

    def test_no_handoff_keeps_nowhere_banner(self):
        for h in ("", None):
            r = render([self.case(handoff=h)])[0]
            self.assertIn("ccpHardTitle", r["html"])
            self.assertNotIn("ccpSearchTitle", r["html"])

    def test_real_pause_banner_wins_over_search(self):
        pz = {"active": True, "override": False, "kind": "session", "reason": "лимиты", "resume_at": 0}
        r = render([self.case(handoff="ok", pause=pz)])[0]
        self.assertIn("ccpPauseTitle", r["html"])
        self.assertNotIn("ccpSearchTitle", r["html"])


class PauseState(unittest.TestCase):
    def state(self, lvl, ready, remote=False):
        import cc_remote_auto
        with mock.patch.object(pause_ctl, "level_state", return_value={"level": lvl, "pause": {"active": False}}), \
                mock.patch.object(pause_ctl, "_remote_active", return_value=remote), \
                mock.patch.object(cc_remote_auto, "handoff_ready", **ready):
            return L.pause_state()

    def test_handoff_flag_only_when_nowhere_to_go_and_handoff_is_ready(self):
        ok = {"return_value": (True, "у Claude DEV нет лимита, на Claude PROD есть")}
        no = {"return_value": (False, "автопередача выключена")}
        for lvl in ("hard", "week", "weekrisk"):
            self.assertTrue(self.state(lvl, ok)["handoff"], lvl)
            self.assertEqual(self.state(lvl, no)["handoff"], "", lvl)
        for lvl in ("none", "gate", "manual"):  # работа есть где вести — «ищу» не нужно
            self.assertEqual(self.state(lvl, ok)["handoff"], "", lvl)

    def test_no_handoff_flag_when_work_is_already_on_prod(self):
        self.assertEqual(self.state("hard", {"return_value": (True, "ок")}, remote=True)["handoff"], "")

    def test_handoff_check_failure_keeps_old_banner(self):
        d = self.state("hard", {"side_effect": RuntimeError("нет файла")})
        self.assertTrue(d["ok"])
        self.assertEqual(d["handoff"], "")
        self.assertEqual(d["level"], "hard")

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
