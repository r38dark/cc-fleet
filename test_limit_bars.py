"""Шкала лимита на плитках активных аккаунтов (вариант «Затухание и пульс»): расчёт переменных и раскраска плиток — настоящий JS из cc_overview.py под node."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
SRC = (HERE / "cc_overview.py").read_text(encoding="utf-8")


def cut(pattern, what):
    m = re.search(pattern, SRC, re.S | re.M)
    assert m, "в cc_overview.py не найдено: " + what
    return m.group(0)


def node(js):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.js")
        Path(p).write_text(js, encoding="utf-8")
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout)


FUNCS = cut(r"^ function limitBarVars\(u5,uw\)\{.*?^ \}$", "limitBarVars") + "\n" + cut(r"^ function paintLimitBars\(\)\{.*?^ \}$", "paintLimitBars")


def alpha(css):
    return float(re.search(r",([0-9.]+)\)$", css).group(1))


@unittest.skipUnless(shutil.which("node"), "нет node")
class LimitBars(unittest.TestCase):
    def test_fill_is_what_is_left_and_shrinks_with_usage_green_to_red(self):
        r = node(FUNCS + "\nconsole.log(JSON.stringify([limitBarVars(0,0),limitBarVars(.5,.5),limitBarVars(1,1)]));")
        self.assertEqual([x["--r5"] for x in r], [1, 0.5, 0])          # заливка = остаток пятичасового, убывает
        self.assertTrue(r[0]["--c5"].startswith("hsla(150,"))          # много осталось — зелёный
        self.assertTrue(r[1]["--c5"].startswith("hsla(75,"))           # половина — жёлто-зелёный
        self.assertTrue(r[2]["--c5"].startswith("hsla(0,"))            # почти нет — красный

    def test_five_hour_layer_is_very_transparent_and_weekly_line_is_bright(self):
        r = node(FUNCS + "\nconsole.log(JSON.stringify(limitBarVars(.4,.4)));")
        self.assertLessEqual(alpha(r["--c5"]), 0.12)                    # «очень сильно прозрачно»
        self.assertGreaterEqual(alpha(r["--cwu"]), 0.8)                 # недельная линия яркая
        self.assertLessEqual(alpha(r["--cwg"]), 0.4)                    # свечение под линией мягкое
        self.assertEqual(r["--uw"], 0.4)                                # растёт слева направо по расходу недели

    def test_garbage_is_clamped(self):
        r = node(FUNCS + "\nconsole.log(JSON.stringify([limitBarVars(-1,5),limitBarVars(NaN,undefined),limitBarVars(Infinity,'x')]));")
        self.assertEqual([(x["--r5"], x["--uw"]) for x in r], [(1, 1), (1, 0), (1, 0)])

    def test_paint_sets_variables_pulse_flag_and_skips_tiles_without_numbers(self):
        js = r'''
const mk=(s,w)=>{const attrs={},vars={};return {attrs,vars,style:{setProperty:(k,v)=>{vars[k]=v}},setAttribute:(k,v)=>{attrs[k]=v},removeAttribute:k=>{delete attrs[k]},
  querySelector:sel=>{const k=sel.includes('=session')?s:w;return k===undefined?null:{textContent:k}}}};
const tiles=[mk('4%','100%'),mk('69%','30%'),mk('—',undefined),mk('0%',undefined),mk('90%','20%'),mk(undefined,'40%')];
const document={querySelectorAll:()=>tiles};
FUNCS_HERE
paintLimitBars();
console.log(JSON.stringify(tiles.map(t=>({lb:t.attrs['data-lb']||null,crit:t.attrs['data-crit']||null,r5:t.vars['--r5'],uw:t.vars['--uw']}))));
'''.replace("FUNCS_HERE", FUNCS)
        r = node(js)
        near = lambda got, want: self.assertAlmostEqual(got, want, places=9)
        self.assertEqual((r[0]["lb"], r[0]["crit"], r[0]["uw"]), ("1", "0", 1))
        near(r[0]["r5"], 0.96)
        self.assertEqual((r[1]["lb"], r[1]["crit"], r[1]["uw"]), ("1", "0", 0.3))
        near(r[1]["r5"], 0.31)
        self.assertEqual(r[2], {"lb": None, "crit": None})              # нет чисел — шкалы нет, переменные не ставились
        self.assertEqual((r[3]["lb"], r[3]["r5"]), ("1", 1))            # 0% потрачено — это число: заливка на всю плитку
        self.assertEqual(r[4]["crit"], "1")                             # осталось меньше 15% — плитка «дышит»
        near(r[4]["r5"], 0.1)
        self.assertEqual((r[5]["lb"], r[5]["crit"], r[5]["r5"]), ("1", "0", 1))   # нет пятичасового, есть недельный: пульса нет

    def test_every_tile_gets_the_bar_and_styles_are_in_place(self):
        self.assertIn("document.querySelectorAll('#fleetActiveAccounts .fleet-compact-account').forEach(t=>{", SRC)
        for part in ("[data-lb]::before", "[data-lb]::after", "calc(var(--r5,0)*100%)", "calc(var(--uw,0)*100%)", "max(0px,calc(100% - 46px))", "isolation:isolate",
                     "fleetLbBreath", '[data-crit="1"]::before', "prefers-reduced-motion:reduce", "new MutationObserver(",
                     "[data-lb]::after{inset:-1px;", "2px no-repeat", "9px no-repeat"):
            self.assertIn(part, SRC, part)
        self.assertNotIn("overflow:hidden;isolation", SRC)              # плитки не обрезаем: у них раскрывающаяся карточка
        self.assertNotIn("box-shadow:0 0 10px var(--cwu", SRC)          # линия не торчит за закругления: слой с радиусом плитки, а не отдельная полоска

    def test_composer_placeholder_does_not_wrap_or_make_a_scrollbar(self):
        # на телефоне кнопки ↑ ↓ ⏎ Esc сужают поле: подсказка переносилась на 2 строки и давала серую полосу прокрутки
        for part in (".fleet-composer textarea::placeholder,.tpcomp textarea::placeholder{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
                     ".fleet-composer textarea:placeholder-shown,.tpcomp textarea:placeholder-shown{overflow:hidden}"):
            self.assertIn(part, SRC, part)


if __name__ == "__main__":
    unittest.main()
