# Разделение консоли панели на 2–3 части (ПК): чистые функции раскладки (node) и обязательные части страницы
# python3 -m unittest test_cc_limits_split_console -v
import os
import shutil
import subprocess
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="ccsplit_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"], exist_ok=True)

import cc_limits as L  # noqa: E402


def pure_js():
    a = L.PAGE.index("/*SPLIT-PURE-START*/")
    b = L.PAGE.index("/*SPLIT-PURE-END*/")
    return "const SPLIT_MAX=3;\n" + L.PAGE[a:b]


CASES = r"""
const eq=(a,b,m)=>{const x=JSON.stringify(a),y=JSON.stringify(b);if(x!==y){console.log('FAIL '+m+': '+x+' != '+y);process.exitCode=1;}};
const AV=['claude','prod','codex'];
// вкладку бросили на часть
eq(splitDrop(['claude','prod'],0,1,'codex'),{keys:['claude','codex'],act:1},'вкладка заменяет часть');
eq(splitDrop(['claude','prod','codex'],0,2,'claude'),{keys:['codex','prod','claude'],act:2},'показанная модель меняется местами');
eq(splitDrop(['claude','prod'],0,1,'prod'),{keys:['claude','prod'],act:1},'на свою же часть — только выбор');
// части поменяли местами
eq(splitSwap(['a','b','c'],0,0,2),{keys:['c','b','a'],act:2},'выбранная уехала вместе с частью');
eq(splitSwap(['a','b','c'],2,0,2),{keys:['c','b','a'],act:0},'выбранная — вторая из пары');
eq(splitSwap(['a','b','c'],1,0,2),{keys:['c','b','a'],act:1},'выбранная не затронута');
eq(splitSwap(['a','b'],0,1,1),{keys:['a','b'],act:0},'сам с собой — без изменений');
// добавить часть
eq(splitAdd(['claude'],AV,null),['claude','prod'],'первая неиспользованная');
eq(splitAdd(['claude'],AV,'codex'),['claude','codex'],'названная модель');
eq(splitAdd(['claude','prod'],AV,'claude'),['claude','prod','codex'],'уже показана — берём свободную');
eq(splitAdd(['claude','prod','codex'],AV,null),null,'больше трёх нельзя');
eq(splitAdd(['claude','prod'],['claude','prod'],null),null,'свободных моделей нет');
// закрыть часть
eq(splitCloseAt(['a','b','c'],1,1),{keys:['a','c'],act:1},'закрыли выбранную — выбрана соседняя');
eq(splitCloseAt(['a','b','c'],2,0),{keys:['b','c'],act:1},'закрыли левее выбранной');
eq(splitCloseAt(['a','b','c'],0,2),{keys:['a','b'],act:0},'закрыли правее выбранной');
eq(splitCloseAt(['a','b','c'],2,2),{keys:['a','b'],act:1},'закрыли последнюю выбранную');
// вкладка
eq(splitPick(['claude','prod'],0,'prod'),{keys:['claude','prod'],act:1},'вкладка показанной — выбирает часть');
eq(splitPick(['claude','prod'],1,'codex'),{keys:['claude','codex'],act:1},'не показанной — заменяет выбранную');
console.log('done');
"""


@unittest.skipUnless(shutil.which("node"), "нет node")
class Layout(unittest.TestCase):
    def test_pure_layout_functions(self):
        path = os.path.join(TMP, "layout.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(pure_js() + CASES)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("FAIL", r.stdout)
        self.assertIn("done", r.stdout)


class Page(unittest.TestCase):
    def test_split_button_sits_in_zoom_block(self):
        zoom = L.PAGE[L.PAGE.index('<div class="tzoom">'):]
        zoom = zoom[:zoom.index("</div>")]
        self.assertIn('id="splitBtn"', zoom)
        self.assertLess(zoom.index('id="splitBtn"'), zoom.index('id="fsBtn"'))

    def test_panes_replace_global_console_state(self):
        # прежние глобальные переменные одной консоли убраны: состояние живёт в панелях
        import re
        for name in ("consShown", "consoleRequestSeq", "consoleAppliedSeq", "consIdle", "consProdRun", "cxConsRun", "STICK"):
            self.assertIsNone(re.search(r"\b" + name + r"\b", L.PAGE), name)
        for part in ("const PANES=[", "function syncPanes(", "function ccConsole(P)", "function consCur(){const ks=splitEff()",
                     "function activePane(", "splitMq=matchMedia('(min-width:1100px) and (pointer:fine)')", "SPLIT_MAX=3"):
            self.assertIn(part, L.PAGE, part)

    def test_split_only_on_wide_pointer_screens(self):
        self.assertIn("(min-width:1100px) and (pointer:fine)", L.PAGE)

    def test_hidden_split_button_stays_hidden(self):
        # у кнопок блока масштаба display задан классом (на телефоне — правилом панели) и перебивает атрибут hidden
        self.assertIn("#splitBtn[hidden]{display:none!important}", L.PAGE)

    def test_each_part_has_its_own_input_bound_to_its_model(self):
        # окно ввода части отправляет тем же кодом, что общее окно (cc_overview.py), но в модель своей части
        self.assertIn("window.fleetBindComposer=bindComposer;", L.PAGE)
        self.assertIn("function bindComposer(form,input,send,stateNode,sessionOf){", L.PAGE)
        self.assertIn("const session=sessionOf();", L.PAGE)
        self.assertNotIn("let sending=false,rotationData=null,lastRequest=null;", L.PAGE)  # состояние отправки — у каждого окна своё
        self.assertIn("window.fleetBindComposer(form,input,send,stat,()=>P.k);", L.PAGE)
        self.assertIn("function renderComps(ks){", L.PAGE)
        self.assertIn("renderHeads(ks);\n renderComps(ks);", L.PAGE)
        # общее окно скрыто только пока окна частей на месте и открыт не чат Notion AI
        self.assertIn(".termwrap.tsplit.tpcomps-on:not(.nai-on)>#fleetConsoleForm,.termwrap.tsplit.tpcomps-on:not(.nai-on)>.fleet-input-status{display:none!important}", L.PAGE)
        self.assertIn(".termwrap.nai-on .tpcomps{display:none!important}", L.PAGE)

    def test_selected_part_is_framed_as_a_whole_and_has_no_status_line(self):
        # рамка охватывает шапку, экран и окно ввода выбранной части (Денис 62461); строки «Ввод в …» у части нет
        self.assertIn("#tpFrame{display:none;position:absolute;", L.PAGE)
        self.assertIn(".termwrap.tsplit:not(.nai-on) #tpFrame.on{display:block}", L.PAGE)
        self.assertIn("renderComps(ks);\n placeFrame(ks);", L.PAGE)
        # края рамки — дробные размеры панели (округление уводило правый край под рамку блока), нижние углы — как у блока там, где часть к нему примыкает
        self.assertIn("f.style.width=b.width.toFixed(2)+'px'", L.PAGE)
        self.assertIn("f.style.borderBottomLeftRadius=idx===0?rad+'px':'0';f.style.borderBottomRightRadius=idx===PANES.length-1?rad+'px':'0';", L.PAGE)
        self.assertNotIn("tpstat", L.PAGE)
        self.assertNotIn(".termbox.tpact{box-shadow", L.PAGE)

    def test_draft_follows_the_model(self):
        self.assertIn("const DRAFTS={};", L.PAGE)
        self.assertIn("DRAFTS[P.k]=input.value", L.PAGE)

    def test_prod_history_is_refetched_for_a_new_pane_width(self):
        self.assertIn("P.k==='prod'&&Math.abs(P.box.clientWidth-(P.histW||0))>24", L.PAGE)

    def test_follow_waits_for_saved_layout(self):
        self.assertIn("||splitPending()){", L.PAGE)

    def test_notion_chat_hides_extra_parts(self):
        self.assertIn(".termwrap.nai-on .tpextra,.termwrap.nai-on .tpheads{display:none!important}", L.PAGE)

    def test_layout_is_saved_in_browser_only(self):
        self.assertIn("localStorage.setItem('cc_split'", L.PAGE)


if __name__ == "__main__":
    unittest.main()
