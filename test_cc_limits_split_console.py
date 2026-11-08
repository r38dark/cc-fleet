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
// консоль идёт за исполнителем (владелец 62577): новый встаёт на часть прежнего, а не на выбранную рукой
eq(splitFollow(['claude','codex','notion'],2,'claude','prod'),{keys:['prod','codex','notion'],act:0},'DEV→PROD: заменилась часть DEV, Notion на месте');
eq(splitFollow(['prod','codex','notion'],1,'prod','claude'),{keys:['claude','codex','notion'],act:0},'PROD→DEV: заменилась часть PROD');
eq(splitFollow(['claude','prod','notion'],2,'claude','prod'),{keys:['claude','prod','notion'],act:1},'новый уже показан — выбирается его часть');
eq(splitFollow(['codex','notion'],1,'claude','prod'),{keys:['codex','prod'],act:1},'прежнего нет на экране — как обычная вкладка');
eq(splitFollow(['claude','codex'],0,'','prod'),{keys:['prod','codex'],act:0},'прежнего исполнителя не знаем — как обычная вкладка');
eq(splitFollow(['claude','notion:a1'],1,'claude','codex'),{keys:['codex','notion:a1'],act:0},'любой исполнитель, не только PROD');
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

    def test_selected_part_has_a_muted_green_frame_only(self):
        # у частей консоли — приглушённо-зелёная рамка только выбранной (серые рамки частей убраны, владелец 62486);
        # рамка охватывает шапку, экран и окно ввода, строки «Ввод в …» у части нет (62461)
        self.assertIn(".tpfr{display:none;position:absolute;z-index:6;pointer-events:none;box-sizing:border-box;border:1px solid transparent}", L.PAGE)
        self.assertIn(".tpfr.on{z-index:7;border-color:rgba(104,172,146,.62)}", L.PAGE)
        self.assertIn(".termwrap.tsplit:not(.nai-on) .tpfr{display:block}", L.PAGE)
        self.assertIn("renderComps(ks);\n applyMax(ks);\n placeFrame(ks);", L.PAGE)
        # размеры дробные (округление уводило правый край под рамку блока), нижние углы — как у блока, соседние рамки перекрываются на 1px
        self.assertIn("f.style.width=(b.width+lap).toFixed(2)+'px'", L.PAGE)
        self.assertIn("f.style.borderBottomLeftRadius=i===0||mx?rad+'px':'0';f.style.borderBottomRightRadius=i===PANES.length-1||mx?rad+'px':'0';", L.PAGE)
        # разделительные линии между частями на месте
        self.assertIn(".tphd+.tphd{border-left:1px solid #263140}", L.PAGE)
        self.assertIn(".tpcw+.tpcw{border-left:1px solid #263140}", L.PAGE)
        self.assertNotIn("tpstat", L.PAGE)
        self.assertNotIn("#tpFrame", L.PAGE)
        self.assertNotIn(".termbox.tpact{box-shadow", L.PAGE)

    def test_top_menu_tabs_have_a_gray_frame_when_open_and_a_muted_green_one_when_active(self):
        # верхнее меню (ПК): открытая консоль — прозрачная серая рамка вокруг вкладки, активная — такая же приглушённо-зелёная
        self.assertIn("@media(min-width:1100px) and (pointer:fine){\n html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s]{align-self:center;height:30px!important;padding:0 12px!important;border-radius:8px}", L.PAGE)
        self.assertIn("html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s].tshown:not(.on){box-shadow:inset 0 0 0 1px rgba(170,182,200,.28)!important}", L.PAGE)
        self.assertIn("html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s].on{box-shadow:inset 0 0 0 1px rgba(104,172,146,.62)!important}", L.PAGE)
        self.assertIn("html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s].on::after{display:none}", L.PAGE)
        self.assertNotIn("text-decoration:underline;text-decoration-color:rgba(200,215,230,.45)", L.PAGE)

    def test_part_header_opens_a_model_menu(self):
        # клик по шапке части — выпадающее меню моделей: выбрать модель для части сразу, без перетаскивания
        for part in ("function openModelMenu(i){", "function closeModelMenu(){", "function pickPartModel(i,k){",
                     "splitCommit(splitDrop(ks,splitActIdx(ks),i,k),k);", '<span class="tpcaret" aria-hidden="true">▾</span>',
                     "const i=+c.dataset.i,m=document.getElementById('tpMenu');if(m&&+m.dataset.i===i){closeModelMenu();return;}splitActivate(i);openModelMenu(i);"):
            self.assertIn(part, L.PAGE, part)
        self.assertIn("splitKeysAvail().map(k=>{", L.PAGE)  # в меню — все доступные модели, включая Notion AI и агентов
        self.assertIn(".tpmenu{position:fixed;z-index:70;", L.PAGE)

    def test_split_keeps_the_console_block_height(self):
        # общее окно ввода со строкой статуса выше окон частей на 39px: добавлены к экрану, «Активные аккаунты» остаются на месте
        self.assertIn("height:calc(clamp(360px,41dvh,510px) + 39px)", L.PAGE)
        self.assertIn("height:calc(clamp(340px,calc(100dvh - 430px),640px) + 39px)", L.PAGE)
        self.assertIn("height:calc(clamp(320px,calc(100dvh - 470px),610px) + 39px)", L.PAGE)

    def test_claude_card_footer_has_a_visible_relogin_button(self):
        # как у карточки PROD: «Войти заново» на виду в подвале, а не только в меню ⋯
        self.assertIn("if(engine==='claude'&&footer&&!footer.querySelector('.fleet-footer-relogin'))", L.PAGE)
        self.assertIn("reloginAsk(slot,rb)", L.PAGE)

    def test_notion_chat_can_be_a_part_of_the_split_console(self):
        # Notion AI (главный чат и агенты) — отдельная часть с тем же управлением: перетаскивание, свой чат и своё окно ввода
        for part in ("function chatHtml(d,rows,stale,aid,nm,pl){", "view.innerHTML=chatHtml(d,rows,stale,agentAid,agentName,pend);",
                     "window.naiChat=function(el,aid){", "window.naiKeys=function(){", "window.naiClose=function(){if(on)close()};"):
            self.assertIn(part, L.PAGE, part)
        # ключи частей: claude / prod / codex и Notion ('notion', 'notion:<id агента>')
        self.assertIn("/^(claude|prod|codex|notion(:\\S+)?)$/.test(k)", L.PAGE)
        self.assertIn("function splitKeysAvail(){const R=document.documentElement.classList;return ['claude'].concat(prodAvail()?['prod']:[],cxAvail()&&!R.contains('ag-unlinked-codex')?['codex']:[],R.contains('ag-unlinked-notion')?[]:naiList().map(x=>x.key));}", L.PAGE)
        # чат в части: своя область, опрос и отправка у самого чата; сообщение идёт в чат, а не в консоль
        self.assertIn("P.box.classList.add('tpchat');P.nv=document.createElement('div');P.nv.className='nai-view tpnai';", L.PAGE)
        self.assertIn("if(isNai(P.k))return;", L.PAGE)
        self.assertIn("e.stopImmediatePropagation();const text=input.value;if(!text.trim())return;P.chat.send(text,", L.PAGE)
        self.assertIn("c.form.querySelector('.tpkey').hidden=isNai(P.k);", L.PAGE)
        # при разделении вкладками Notion ведёт cc_limits.py, вне разделения — прежнее окно поверх консоли
        self.assertIn("sp=window.fleetSplitOn&&window.fleetSplitOn()", L.PAGE)
        self.assertIn("if(window.fleetSplitOn&&window.fleetSplitOn()){if(on)close();return}", L.PAGE)
        self.assertIn("!(window.fleetSplitWanted&&window.fleetSplitWanted())", L.PAGE)
        self.assertIn("if(isNai(k)&&!splitEff())return;", L.PAGE)
        self.assertIn("if(ks&&window.naiClose)window.naiClose();", L.PAGE)
        # вкладки агентов создаются позже страницы — перетаскивание делегировано на #cTabs
        self.assertIn("$('#cTabs').addEventListener('dragstart',", L.PAGE)

    def test_unlinked_codex_and_notion_are_not_offered_for_the_split(self):
        # призрачные Codex и Notion AI не попадают ни в части консоли, ни в меню моделей части (владелец 62622)
        self.assertIn("cxAvail()&&!R.contains('ag-unlinked-codex')?['codex']:[]", L.PAGE)
        self.assertIn("R.contains('ag-unlinked-notion')?[]:naiList()", L.PAGE)

    def test_wizard_window_is_anchored_to_the_ghost_tile_when_there_is_no_header_button(self):
        self.assertIn("function ciAnchor(){const b=$('#cxInst');return b&&b.offsetParent!==null?b:(document.querySelector('#naiAgents .nai-seg[data-ag=\"codex\"]')||b)}", L.PAGE)
        self.assertIn("r=ciAnchor().getBoundingClientRect();", L.PAGE)

    def test_codex_tab_is_not_chosen_and_console_not_autostarted_without_login(self):
        # запомненная вкладка Codex не выбирается, пока Codex не подключён; консоль Codex сама не стартует без входа в ChatGPT (владелец 62657)
        self.assertIn("CONS==='codex'&&cxAvail()&&!document.documentElement.classList.contains('ag-unlinked-codex')?'codex':'claude'", L.PAGE)
        self.assertIn("!d.profile_paused&&ciAcc()){cxAutoGo=false;cxConsAct('start',true,P);}", L.PAGE)

    def test_draft_follows_the_model(self):
        self.assertIn("const DRAFTS={};", L.PAGE)
        self.assertIn("DRAFTS[P.k]=input.value", L.PAGE)

    def test_prod_history_is_refetched_for_a_new_pane_width(self):
        self.assertIn("P.k==='prod'&&P.box.clientWidth>0&&Math.abs(P.box.clientWidth-(P.histW||0))>24", L.PAGE)

    def test_follow_waits_for_saved_layout(self):
        self.assertIn("||splitPending()){", L.PAGE)

    def test_follow_replaces_the_previous_workers_part(self):
        # при передаче работы заменяется часть прежнего исполнителя, а не выбранная рукой (владелец 62577); часть модели, которой нет среди доступных, — по-старому, кликом
        self.assertIn("if(ks&&splitKeysAvail().includes(tabKey(b))){const ob=seen?document.getElementById({prod:'ctProd',codex:'ctCodex',notion:'ctNotion'}[seen]||'ctClaude'):null;"
                      "splitCommit(splitFollow(ks,splitActIdx(ks),ob?tabKey(ob):'',tabKey(b)),tabKey(b));return;}", L.PAGE)

    def test_notion_chat_hides_extra_parts(self):
        self.assertIn(".termwrap.nai-on .tpextra,.termwrap.nai-on .tpheads{display:none!important}", L.PAGE)

    def test_layout_is_saved_in_browser_only(self):
        self.assertIn("localStorage.setItem('cc_split'", L.PAGE)

    def test_part_can_be_expanded_to_the_whole_console(self):
        # иконка «на весь экран» у каждой части (62676): выбранная часть занимает всю консоль, остальные спрятаны, но не закрыты
        self.assertIn('data-fs="', L.PAGE)
        self.assertIn("function splitMaxToggle(i){", L.PAGE)
        self.assertIn("if(MAXED&&i===splitActIdx(ks))MAXED=false;else{splitActivate(i);MAXED=true;}", L.PAGE)
        self.assertIn(".termwrap.tpmax .fleet-console-viewport>.tphide,.termwrap.tpmax .tpheads .tphide,.termwrap.tpmax .tpcomps .tphide{display:none!important}", L.PAGE)
        self.assertIn("for(const P of PANES)if(!P.hid)ccConsole(P);", L.PAGE)  # спрятанные части не опрашиваем (у них нет ширины)
        # закрыть часть / добавить часть — выход из развёрнутого вида
        for fn in ("function splitClose(i){\n const ks=splitEff();if(!ks)return;\n MAXED=false;",
                   "function splitToggle(){\n const av=splitKeysAvail();if(av.length<2||!splitMq.matches)return;\n MAXED=false;"):
            self.assertIn(fn, L.PAGE)

    def test_part_header_has_compact_and_new_session_buttons(self):
        # «Сжать контекст» и «Новая сессия» — в шапке каждой части с консолью (62680); команда идёт модели этой части
        self.assertIn("function partActs(k,i){", L.PAGE)
        self.assertIn("if(!(k==='claude'||k==='prod'||k==='codex'))return '';", L.PAGE)  # у Notion AI кнопок нет
        self.assertIn("function splitPartCmd(i,cmd,btn){const ks=splitEff();if(!ks||i<0||i>=ks.length)return;splitActivate(i);consActCmd(cmd,btn);}", L.PAGE)
        self.assertIn("html:root:root .termwrap.tsplit:not(.nai-on) .fleet-console-toolbar .ctacts{display:none!important}", L.PAGE)

    def test_zoom_scales_every_part_by_the_same_ratio(self):
        # подгонка по ширине меряется при масштабе 100%: иначе она отменяла «+/−» у частей с длинными строками (62676)
        self.assertIn("b.style.setProperty('--tz','1');b.style.setProperty('--pz','1');", L.PAGE)
        self.assertIn("b.style.removeProperty('--tz');", L.PAGE)


if __name__ == "__main__":
    unittest.main()
