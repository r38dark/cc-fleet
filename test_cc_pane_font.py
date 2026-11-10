"""Шрифт частей разделённой консоли и опрос консоли фоновой вкладкой (владелец 63297, 10.11.26): у Claude PROD шрифт «слетал» до половины —
фоновая вкладка раз в минуту запрашивала другую ширину экрана общего tmux, а у PROD оставался режим «сжать шрифт». Настоящий JS из cc_limits.py под node."""
import json
import re
import shutil
import subprocess
import tempfile
import os
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


@unittest.skipUnless(shutil.which("node"), "нет node")
class PaneFont(unittest.TestCase):
    def test_background_tab_does_not_poll_the_console(self):
        js = r"""
let hiddenFlag=false;const document={get hidden(){return hiddenFlag},querySelectorAll:()=>[]};
const splitMq={matches:false};function syncPanes(){}function isKey(){return false}function tabKey(){}function splitKeysAvail(){return[]}
let calls=[];function ccConsole(P){calls.push(P.k)}
const PANES=[{k:'claude',hid:false},{k:'prod',hid:false},{k:'codex',hid:true}];
%s
hiddenFlag=false;tickAll();const visible=calls.slice();calls=[];hiddenFlag=true;tickAll();
console.log(JSON.stringify({visible,hidden:calls}));
""" % cut(r"^function tickAll\(\)\{[^\n]*\}$", "tickAll")
        r = node(js)
        self.assertEqual(r["visible"], ["claude", "prod"])        # у части с hid опроса и раньше не было
        self.assertEqual(r["hidden"], [])                         # фоновая вкладка консоль не опрашивает и ширину tmux не меняет

    def test_coming_back_to_the_tab_refreshes_the_console_at_once(self):
        self.assertIn("document.addEventListener('visibilitychange',()=>{if(!document.hidden)tickAll();});", SRC)

    def test_prod_part_wraps_lines_like_codex_and_dev_instead_of_shrinking_the_font(self):
        js = r"""
function isNai(k){return false}
let calls=[];
function mk(k,split){const b={style:{_pz:'0.5',getPropertyValue:n=>n==='--pz'?b.style._pz:'',removeProperty:n=>{calls.push('rm'+n);if(n==='--pz')b.style._pz=''},setProperty:(n,v)=>calls.push('set'+n+'='+v)},
 classList:{add:c=>calls.push('+'+c),remove:c=>calls.push('-'+c)},closest:()=>split?{}:null,clientWidth:100,scrollWidth:300};return {k,box:b};}
%s
const out={};
for(const k of ['prod','codex','claude']){calls=[];fitPane(mk(k,true));out[k]=calls.slice();}
calls=[];fitPane(mk('prod',false));out.prodNotSplit=calls.slice();
console.log(JSON.stringify(out));
""" % cut(r"^function fitPane\(P\)\{.*?^\}$", "fitPane")
        r = node(js)
        for k in ("prod", "codex", "claude"):
            self.assertIn("+tcwrap", r[k], k)                    # строки переносятся
            self.assertIn("rm--pz", r[k], k)                      # прежний «сжатый» масштаб снимается
            self.assertFalse([c for c in r[k] if c.startswith("set--pz")], k)   # и новый не ставится
        self.assertEqual(r["prod"], r["codex"])                   # у PROD то же, что у Codex
        self.assertNotIn("+tcwrap", r["prodNotSplit"])           # вне разделения перенос не нужен


if __name__ == "__main__":
    unittest.main()
