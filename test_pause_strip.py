"""Пауза в окнах консоли Claude PROD и Codex (63532: большая серая иконка по центру части, текст — сверху и в title): настоящий JS из cc_limits.py под node с подделкой документа."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
SRC = (HERE / "cc_limits.py").read_text(encoding="utf-8")


def cut(pattern, what):
    m = re.search(pattern, SRC, re.S | re.M)
    assert m, "в cc_limits.py не найдено: " + what
    return m.group(0)


def node(js):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.js")
        Path(p).write_text(js, encoding="utf-8")
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout)


FUNC = (cut(r"^function ccpsHtml\(k\)\{.*?^\}$", "ccpsHtml") + "\n" + cut(r"^const PAUSE_ICO=.*?;$", "PAUSE_ICO") + "\n"
        + cut(r"^function ccpPlain\(h\)\{[^\n]*\}$", "ccpPlain") + "\n" + cut(r"^function ccpPartStrip\(\)\{.*?^\}$", "ccpPartStrip"))

HARNESS = r'''
const els={};let box=null;
const mkEl=()=>({hidden:false,style:{},className:'',innerHTML:'',title:'',appendChild(c){}});
const wrap={classList:{contains:c=>SPLIT&&c==='tsplit'},getBoundingClientRect:()=>({left:100,top:50}),appendChild(c){box=c}};
const document={querySelector:()=>wrap,getElementById:id=>id==='ccps'?box:(els[id]||null),
  createElement:()=>{const e=mkEl();Object.defineProperty(e,'id',{set(v){this._id=v;els[v]=this},get(){return this._id}});return e}};
const window={innerWidth:1400};
const PANES=PANES_JSON.map(p=>({k:p.k,hid:!!p.hid,box:{offsetParent:p.off?null:{},getBoundingClientRect:()=>({left:p.l,top:p.t,width:p.w,height:p.h||400})}}));
const T={ccpsTitle:'Claude на паузе по лимитам',ccpsTitleCx:'Codex на паузе по лимитам',ccpsBody:'Сообщения в Telegram встают в очередь.',ccpsBodyCx:'Сообщения из Telegram ждут в очереди.',
  ccpsUntil:(at,left)=>' до '+at+' (осталось '+left+')',cxlpWin:m=>m===300?'окно 5 ч':'окно неделя'};
const tr=(k,...a)=>typeof T[k]==='function'?T[k](...a):T[k];
const ccpAt=ms=>'23:10', ccpLeft=ms=>'12 мин 00 с', ccpEsc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let ccpData=DATA_JSON, cxlpData=CX_JSON;
FUNC_HERE
ccpPartStrip();
console.log(JSON.stringify(Object.keys(els).filter(k=>k!=='ccps').map(k=>({id:k,hidden:els[k].hidden,html:els[k].innerHTML,title:els[k].title,top:els[k].style.top,left:els[k].style.left,width:els[k].style.width,height:els[k].style.height}))));
'''


def run(data, panes, split=False, cx=None):
    js = (HARNESS.replace("FUNC_HERE", FUNC).replace("DATA_JSON", json.dumps(data)).replace("CX_JSON", json.dumps(cx))
          .replace("PANES_JSON", json.dumps(panes)).replace("SPLIT", "true" if split else "false"))
    return node(js)


BLOCKED = {"remote_pause": {"enabled": True, "applied": True, "blocked": True, "resume_at": 1794324600, "reasons": ["5 ч: 90% (порог 90%)"]}}
CODEX = {"active": True, "paused": True, "resume_at": 1794324600, "windows": [300]}
PANES = [{"k": "claude", "l": 100, "t": 50, "w": 600}, {"k": "prod", "l": 720, "t": 50, "w": 600}]
PANES_CX = [{"k": "claude", "l": 100, "t": 50, "w": 600}, {"k": "codex", "l": 720, "t": 50, "w": 600}]


@unittest.skipUnless(shutil.which("node"), "нет node")
class PauseStrip(unittest.TestCase):
    def test_prod_icon_over_prod_part_with_time_reason_and_queue_note_in_title(self):
        r = run(BLOCKED, PANES)
        self.assertEqual([x["id"] for x in r], ["ccps1"])                # только часть PROD, у Claude DEV иконки нет
        x = r[0]
        self.assertFalse(x["hidden"])
        self.assertIn("<svg", x["html"])                                 # большая иконка паузы, а не текст
        self.assertNotIn("Claude на паузе", x["html"])
        for part in ("Claude на паузе по лимитам", "до 23:10", "осталось 12 мин", "5 ч: 90% (порог 90%)", "очередь"):
            self.assertIn(part, x["title"])                              # подробный текст — подсказка (и сверху в баннере)
        self.assertNotIn("<b>", x["title"])
        self.assertEqual((x["top"], x["left"], x["width"], x["height"]), ("0px", "620px", "600px", "400px"))   # на всю часть: иконка по центру

    def test_codex_strip_only_when_codex_is_paused_on_limits(self):
        r = run({}, PANES_CX, cx=CODEX)
        self.assertEqual([x["id"] for x in r], ["ccps1"])
        self.assertIn("<svg", r[0]["html"])
        for part in ("Codex на паузе по лимитам", "до 23:10", "окно 5 ч", "очереди"):
            self.assertIn(part, r[0]["title"])
        for cx in (None, {"active": False}, {"active": True, "paused": False, "resume_at": 1794324600}):
            self.assertEqual(run({}, PANES_CX, cx=cx), [], cx)           # просто предупреждение о лимите — не пауза, полосы нет

    def test_each_strip_goes_only_over_its_own_part(self):
        r = run(BLOCKED, PANES_CX, cx=CODEX)                             # у PROD-части нет, у Codex-части есть
        self.assertEqual([x["id"] for x in r], ["ccps1"])
        self.assertIn("Codex на паузе", r[0]["title"])
        both = [{"k": "prod", "l": 100, "t": 50, "w": 600}, {"k": "codex", "l": 720, "t": 50, "w": 600}]
        r = run(BLOCKED, both, cx=CODEX)
        self.assertEqual({x["id"]: ("Claude на паузе" in x["title"], "Codex на паузе" in x["title"]) for x in r},
                         {"ccps0": (True, False), "ccps1": (False, True)})

    def test_split_mode_icon_still_covers_the_whole_part(self):
        r = run(BLOCKED, PANES, split=True)
        self.assertEqual((r[0]["top"], r[0]["height"]), ("0px", "400px"))     # иконка по центру части, сдвигов под надпись больше нет

    def test_not_shown_when_not_blocked_or_state_missing(self):
        for data in ({}, {"remote_pause": {}}, {"remote_pause": dict(BLOCKED["remote_pause"], blocked=False)},
                     {"remote_pause": dict(BLOCKED["remote_pause"], applied=False)}, {"remote_pause": dict(BLOCKED["remote_pause"], enabled=False)}):
            self.assertEqual(run(data, PANES), [], data)                 # полосы нет и не создаётся

    def test_hidden_when_part_is_not_visible_and_reason_is_escaped(self):
        r = run(BLOCKED, [{"k": "prod", "l": 0, "t": 0, "w": 600, "off": 1}])
        self.assertEqual(r, [])                                          # часть скрыта — полоса не создаётся
        data = {"remote_pause": dict(BLOCKED["remote_pause"], reasons=["<b>x</b>"])}
        r = run(data, PANES)
        self.assertIn("<b>x</b>", r[0]["title"])                         # title — обычный текст: сущности раскодированы, разметки в нём нет
        self.assertNotIn("<b>x</b>", r[0]["html"])

    def test_no_until_time_still_explains(self):
        data = {"remote_pause": dict(BLOCKED["remote_pause"], resume_at=0)}
        r = run(data, PANES)
        self.assertNotIn("до 23:10", r[0]["title"])
        self.assertIn("очередь", r[0]["title"])

    def test_texts_in_both_languages_styles_and_timer_are_in_place(self):
        for key in ("ccpsTitle:", "ccpsTitleCx:", "ccpsUntil:", "ccpsBody:", "ccpsBodyCx:"):
            self.assertEqual(SRC.count(key), 2, key)                     # по одному разу в ru и en
        for part in (".ccps-box{", ".ccps{", ".ccps svg{", "setInterval(ccpPartStrip,1000)", "addEventListener('resize',ccpPartStrip)"):
            self.assertIn(part, SRC, part)

    def test_top_banner_carries_the_console_text_and_its_countdown_ticks(self):
        # 63532: два текста паузы → один. Верхний баннер Claude PROD берёт тексты консольной полосы (до часа, осталось, причина, очередь Telegram)
        i = SRC.index("const rp=d&&d.remote_pause;")
        j = SRC.index("const fleet=d&&d.fleet;", i)
        part = SRC[i:j]
        for need in ("tr('ccpsTitle')", "tr('ccpsUntil'", "tr('ccpsBody')", "ccp-left", "(rp.reasons||[])"):
            self.assertIn(need, part, need)
        self.assertNotIn("Claude на втором сервере: пауза по лимитам", SRC)
        self.assertNotIn("Новые действия ждут сброса лимита.", SRC)
        tick = SRC[SRC.index("function ccpTick(){"):]
        self.assertIn("#ccPause .ccp-left", tick[:400])               # «осталось …» в тексте идёт каждую секунду
        icon = SRC[SRC.index("const PAUSE_ICO="):]
        self.assertIn("pointer-events:none", SRC[SRC.index(".ccps{"):SRC.index(".ccps svg{")])  # иконка не мешает консоли
        self.assertIn("currentColor", icon[:200])                      # цвет — серый прозрачный из CSS


if __name__ == "__main__":
    unittest.main()
