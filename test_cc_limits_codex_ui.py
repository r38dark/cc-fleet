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

    def test_console_has_no_feed_view(self):
        # вкладка Codex — всегда экран консоли: ни строки «Лента | Экран», ни ленты, ни её тексты
        for bad in ('id="cxFeed"', 'id="cxBar"', 'id="cvFeed"', 'id="cvScreen"', 'id="cxStatD"', "cxFeedPoll", "cc_cxview"):
            self.assertNotIn(bad, L.PAGE, bad)
        self.assertEqual(re.findall(r"^\s{2}(cxf[A-Z]\w*):", i18n_block("ru"), re.M), [])

    def test_quick_model_chip_between_profile_and_gear(self):
        page = L.PAGE
        grp = re.search(r'<div class="cxgrp" id="cxGrp"[^>]*>(.*?)</div><div id="langSwitch"', page, re.S).group(1)
        self.assertLess(grp.index('id="cxBtn"'), grp.index('id="cxMod"'))
        self.assertLess(grp.index('id="cxMod"'), grp.index('id="cxGear"'))
        self.assertEqual(page.count('id="cxQ"'), 1)
        self.assertRegex(page, r'<div id="cxQ"[^>]*\bhidden\b')
        # панели друг друга закрывают, клик мимо и Esc закрывают быструю панель
        self.assertIn("closest('#cxQ,#cxMod')", page)
        self.assertRegex(page, r"Escape'[^\n]*cxQClose\(\)")

    def test_bot_switch_is_not_a_profile(self):
        # «Выключен» — не профиль: бот включается отдельным выключателем над списком, профиль при этом не меняется
        self.assertNotRegex(L.PAGE, r"p\.on\b|on===false|cxpS_off|cxpOffStop")
        r = re.search(r"function cxpRender\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertLess(r.index("cxpBotHtml(b)"), r.index("cxplist"))
        tog = re.search(r"async function cxpBotToggle\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("chatgpt/bridge/save',{enabled:!b.enabled}", tog)
        self.assertNotIn("profile", tog)
        # клик по выключателю не применяет профиль и не закрывает меню
        self.assertRegex(L.PAGE, r"closest\('\[data-bot\]'\)\)\{e\.stopPropagation\(\);cxpBotToggle\(\);return;\}")

    def test_bot_switch_texts_say_pushes_still_arrive(self):
        # бот выключен — ответы и Codex молчат, но пуши о лимитах и подписке идут (мост шлёт их, пока бот подключён)
        def val(lang, key):
            return re.search(r"^\s{2}%s:'(.*)',$" % key, i18n_block(lang), re.M).group(1)
        for lang, word in (("ru", "пуши"), ("en", "pushes")):
            self.assertIn(word, val(lang, "cxpBotOff").lower())
            self.assertNotIn(word, val(lang, "cxpBotOn").lower())

    def test_form_has_project_and_own_workdir_fields(self):
        # «Проект» — всегда (Codex его только читает), «Рабочая папка Codex» — только в режиме «Самостоятельно»; project уходит, лишь если его правили
        form = re.search(r"function cxbRender\(force\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn('id="cxbProj"', form)
        self.assertIn('id="cxbDirRow"', form)
        self.assertIn("$('#cxbDirRow').hidden=!self", re.search(r"function cxbSync\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0))
        save = re.search(r"async function cxbSave\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("if(pj!==cxbProjVal(b))body.project=pj", save)

    def test_builtin_cards_show_route_arrow_and_colored_features(self):
        # две карточки: название, маршрут со стрелкой между звеньями, цветные чипы основных функций
        self.assertIn("function cxpNameHtml(p)", L.PAGE)
        self.assertIn('stroke="url(#cxpg)"', L.PAGE)
        self.assertEqual(L.PAGE.count('id="cxpg"'), 1)
        meta = re.search(r"const CXP_META=\{(.*?)\n\};", L.PAGE, re.S).group(1)
        self.assertEqual(re.findall(r"^ (\w+):\{", meta, re.M), ["orchestrator", "codex"])
        for lang in ("ru", "en"):
            blk = i18n_block(lang)
            self.assertEqual(len(re.search(r"cxpF_orchestrator:\[(.*?)\],\n", blk).group(1).split("','")), 4)
            self.assertEqual(len(re.search(r"cxpF_codex:\[(.*?)\],\n", blk).group(1).split("','")), 3)
            self.assertEqual(len(re.search(r"cxpFlow_orchestrator:\[(.*?)\],\n", blk).group(1).split("','")), 5)
            self.assertEqual(len(re.search(r"cxpRoute_orchestrator:\[(.*?)\],\n", blk).group(1).split("','")), 2)
        ru = i18n_block("ru")
        self.assertIn("cxpN_codex:'Codex'", ru)
        self.assertNotIn("Второй ИИ", ru)

    def test_console_starts_itself_like_claude(self):
        # вкладка Codex сама поднимает консоль: жать «Запустить» не нужно (как и у консоли Claude)
        poll = re.search(r"async function ccConsole\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("cxConsAct('start',true)", poll)
        self.assertRegex(poll, r"d\.running\)cxAutoGo=false")  # уже работала — дальше остановка осознанная
        # после ручной остановки сама не поднимается, пока страницу не перезагрузят
        stop = re.search(r"\$\('#ctStop'\)\.addEventListener\('click'[^\n]*", L.PAGE).group(0)
        self.assertIn("cxAutoGo=false", stop)
        self.assertIn("cxAutoGo=false;cxConsAct('start',true)", poll)  # флаг гаснет ДО запроса: опрос раз в 2 с не запустит дважды
        self.assertIn("cxcStarting", i18n_block("ru"))

    def test_no_feed_endpoint_left(self):
        with open(L.__file__, encoding="utf-8") as f:
            self.assertNotIn("/api/chatgpt/bridge/feed", f.read())

    def test_status_dots_reset_global_err_margin(self):
        # глобальное .err{margin-top:8px} сдвигало точки с классом err вниз от центра текста
        self.assertIn(".err{color:var(--bad);font-size:13px;margin-top:8px}", L.PAGE)
        for sel in (".cxdot.err", ".termdot.err"):
            m = re.search(re.escape(sel) + r"\{([^}]*)\}", L.PAGE)
            self.assertTrue(m, sel)
            self.assertIn("margin:0", m.group(1), sel)

    def test_texts_in_both_languages(self):
        keys = {lang: set(re.findall(r"^\s{2}(cx\w*):", i18n_block(lang), re.M)) for lang in ("ru", "en")}
        self.assertEqual(keys["ru"] ^ keys["en"], set())
        # cxpN_/cxpS_/… — начало ключей профилей; cxoMode_/cxoAcc_/cxoRt_ — описания вариантов состава
        pfx = ("cxpN_", "cxpS_", "cxpWhen_", "cxpRoute_", "cxpF_", "cxpFlow_", "cxpCan_", "cxpNot_")
        dyn = set(pfx) | {"cxoMode_", "cxoAcc_", "cxoRt_"}
        used = set(re.findall(r"tr\('(cx\w+)'", L.PAGE)) - dyn
        for p in pfx:
            used |= {p + i for i in ("orchestrator", "codex")}
        used |= {"cxpBotOnToast", "cxpBotOffToast"}  # tr(b.enabled?'…':'…') — в разбор по шаблону не попадает
        used |= {"cxoMode_" + i for i in ("mediator", "orchestrator", "self")}
        used |= {"cxoAcc_" + i for i in ("read", "write", "full")}
        used |= {"cxoRt_" + i for i in ("read", "dev", "full")}
        self.assertEqual(sorted(used - keys["ru"]), [])
        self.assertEqual(sorted(used - keys["en"]), [])

    def test_builtin_profiles_have_texts(self):
        import cc_codex_bridge as br
        ru = i18n_block("ru")
        for pid, _ in br.BUILTIN_PROFILES:
            for pfx in ("cxpN_", "cxpS_", "cxpWhen_", "cxpRoute_", "cxpF_", "cxpFlow_", "cxpCan_", "cxpNot_"):
                self.assertIn("%s%s:" % (pfx, pid), ru)
            self.assertIn(pid, L.PAGE[L.PAGE.index("const CXP_META="):][:600])


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
out.lapsedHtml=cxLimHtml({lapsed:true,plan:'free',sub_until:iso(-day),windows:[W(300,4),W(10080,1)]});
out.lapsedSub=cxLimSub({lapsed:true,sub_until:iso(-day)});
out.lapsedTip=cxLimTip({lapsed:true,plan:'free',email:'a@b',windows:[W(300,4)]});
out.freeHtml=cxLimHtml({plan:'free',lapsed:false,windows:[W(300,4)]});
out.lapsedLogin=cxLimHtml({lapsed:true,login_required:true});
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

    def test_lapsed_to_free_is_red_first_segment(self):
        h = self.o["lapsedHtml"]
        self.assertTrue(h.startswith('<span class="cxl bad nobar"><i>cxLimPlan</i><b>Free</b></span>'), h)
        self.assertNotIn("cxLimSub", h)                           # «подписка истекла» не дублирует красный Free
        self.assertIsNone(self.o["lapsedSub"])
        self.assertIn("cxLimFreeTip", self.o["lapsedTip"])
        self.assertNotIn("cxLimPlan", self.o["freeHtml"])         # аккаунт, который Free и был, не краснеет
        self.assertIn("cxLimLogin", self.o["lapsedLogin"])        # нужен вход — сначала он

    def test_account_is_the_one_bridge_uses(self):
        self.assertEqual(self.o["pickB"], "b")
        self.assertEqual(self.o["pickFirst"], "a")
        self.assertIsNone(self.o["none"])


CARD_JS = """
const LANG='ru';
const tr=(k,...a)=>a.length?k+'('+a.join(',')+')':k;
const acctEsc=s=>String(s==null?'':s);
const ring=()=>'RING',bar=()=>'BAR';
let cxData=null;
%s
const now=Date.now(),day=86400e3,iso=ms=>new Date(now+ms).toISOString();
const W=(mins,pct)=>({mins,pct,resets_at:iso(3600e3)});
const base={slot:'gpt1',email:'a@b',models:[],windows:[W(300,4),W(10080,1)]};
const o={};
o.lapsed=cxCard(Object.assign({},base,{plan:'free',lapsed:true,paid_plan:'plus'}));
o.plus=cxCard(Object.assign({},base,{plan:'plus',lapsed:false,sub_until:iso(20*day)}));
o.ended=cxCard(Object.assign({},base,{plan:'plus',lapsed:false,sub_until:iso(-day)}));
o.alwaysFree=cxCard(Object.assign({},base,{plan:'free',lapsed:false}));
o.login=cxCard(Object.assign({},base,{plan:'free',lapsed:true,paid_plan:'plus',login_required:true}));
cxData={accounts:[Object.assign({},base,{plan:'free',lapsed:true,paid_plan:'plus'})]};
o.sumLapsed=cxAccSummary();
cxData={accounts:[Object.assign({},base,{plan:'plus'})]};
o.sumPlus=cxAccSummary();
console.log(JSON.stringify(o));
"""


@unittest.skipUnless(__import__("shutil").which("node"), "нет node")
class FreeCard(unittest.TestCase):
    """Слёт с платного плана на Free: красная метка, заметка и кнопка «Я продлил» в карточке."""

    @classmethod
    def setUpClass(cls):
        i = L.PAGE.index("function cxWin(")
        j = L.PAGE.index("function cxRender(){")
        k = L.PAGE.index("function cxAccSummary(){")
        k2 = L.PAGE.index("function cxpRender(){")
        code = CARD_JS % (L.PAGE[i:j] + L.PAGE[k:k2])
        path = os.path.join(TMP, "card.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout)

    def test_lapsed_card_red_tag_note_and_button(self):
        h = self.o["lapsed"]
        self.assertIn('class="card lapsed"', h)
        self.assertIn('<span class="tag lpt">FREE</span>', h)
        self.assertIn("cxLapsedNote(Plus)", h)
        self.assertIn("cxRenew('gpt1',this)", h)
        self.assertIn("cxRenewBtn", h)
        self.assertNotIn("cxSubOver", h)          # устаревший срок не спорит с красным FREE

    def test_normal_card_has_no_free_marks(self):
        h = self.o["plus"]
        for bad in ("lapsed", "lpt", "cxRenew(", "cxLapsedNote"):
            self.assertNotIn(bad, h, bad)
        self.assertIn('<span class="tag plan">PLUS</span>', h)

    def test_ended_subscription_gets_renew_button_too(self):
        h = self.o["ended"]
        self.assertIn("cxRenew('gpt1',this)", h)
        self.assertNotIn("cxLapsedNote", h)       # плана Free ещё нет — заметки нет, есть чип «подписка закончилась»
        self.assertIn("cxSubOver", h)

    def test_account_that_was_always_free_is_calm(self):
        h = self.o["alwaysFree"]
        self.assertNotIn("lapsed", h)
        self.assertNotIn("cxRenew(", h)
        self.assertIn('<span class="tag plan">FREE</span>', h)

    def test_login_needed_hides_renew(self):
        self.assertNotIn("cxRenew(", self.o["login"])
        self.assertIn("cxLoginNeeded", self.o["login"])

    def test_window_summary_marks_free(self):
        self.assertIn("⛔ Free", self.o["sumLapsed"])
        self.assertNotIn("Free", self.o["sumPlus"])


QUICK_JS = """
const LANG='ru';
const tr=(k,...a)=>a.length?k+'('+a.join(',')+')':k;
const acctEsc=s=>String(s==null?'':s);
const posts=[];
const els={'#cxQ':{hidden:false,classList:{add(){},remove(){}}},'#cxMod':{setAttribute(){}},'#cxQb':{innerHTML:''}};
const $=s=>els[s];
let ACC=null,cxData={accounts:[]};
function cxLimAcc(){return ACC;}
async function acctPost(p,b){posts.push([p,b]);return{ok:true,message:'ok'};}
const toast=()=>{};
async function cxLoad(){}
%s
const ms=[
 {id:'m1',name:'M1',efforts:['low','high'],default_effort:'low',is_default:true,fast:'priority'},
 {id:'m2',name:'M2',efforts:['low','medium','high','ultra'],default_effort:'medium',is_default:false,fast:'priority'},
 {id:'m3',name:'M3',efforts:['low'],default_effort:'low',is_default:false,fast:''}];
const pick=c=>({name:c.name,eff:c.eff,ef:c.ef,known:c.known});
(async()=>{
 const o={};
 o.def=pick(cxQCur({slot:'s',models:ms}));
 o.m2=pick(cxQCur({slot:'s',models:ms,model:'m2',effort:'ultra'}));
 o.unknown=pick(cxQCur({slot:'s',models:ms,model:'zzz'}));
 o.badEffort=pick(cxQCur({slot:'s',models:ms,model:'m1',effort:'ultra'}));
 ACC={slot:'s',models:ms,model:'m2',effort:'ultra',fast:true};
 await cxQSet('m3',null);                       // у M3 нет ни усилия ultra, ни Fast — оба сбрасываются
 o.openAfterModel=!els['#cxQ'].hidden;          // выбор модели панель не закрывает: усилие ещё можно поменять
 await cxQSet(null,'high');                     // усилие меняем — модель и Fast остаются
 await cxQSet('m2',null);                       // то же значение — ничего не шлём
 els['#cxQ'].hidden=false;
 await cxQSet(null,'ultra');                    // то же усилие: ничего не шлём, но панель закрывается
 o.posts=posts.map(p=>[p[0],p[1]]);
 o.closedOnSame=els['#cxQ'].hidden;
 ACC={slot:'s',models:ms,model:'m1',effort:'',fast:false};
 cxQRender();o.html=els['#cxQb'].innerHTML;
 console.log(JSON.stringify(o));
})();
"""


EMG_JS = """
const LISTS={cxeRoute:2,cxeF:4,cxeFlow:5};
const tr=(k,...a)=>LISTS[k]?Array.from({length:LISTS[k]},(_,i)=>k+i):a.length?k+'('+a.join(',')+')':k;
const acctEsc=s=>String(s==null?'':s);
const CXP_INFO=new Set();
const cxClock=iso=>'CLK';
const posts=[],shown=[],toasts=[];
let confirmAnswer=true,cxbData={emergency:null},loads=0;
const confirm=()=>confirmAnswer;
const els={};
const $=s=>els[s]||(els[s]={value:'',disabled:false,addEventListener(){},focus(){}});
async function acctPost(p,b){posts.push([p,b]);return{ok:true,message:'ok'};}
const acctShow=h=>shown.push(h);
const acctClose=()=>{};
const cxMenuClose=()=>{};
const toast=t=>toasts.push(t);
async function cxbLoad(){loads++;}
%s
%s
(async()=>{
 const o={};
 const cfg={configured:true,active:false,hours:24,services:['svc-a.service','svc-b.service'],files:2,ssh:true,word:'аварийный',journal:[],last:null};
 o.hiddenWhenNone=cxeHtml(null)+'|'+cxeHtml({configured:false,active:false});
 o.idle=cxeHtml(cfg);
 o.idleBad=cxeHtml(Object.assign({},cfg,{last:{problems:['ACL','владельцы']}}));
 o.on=cxeHtml(Object.assign({},cfg,{active:true,until:2000,now:1000,journal:['a','b']}));
 o.activeEvenIfNotConfigured=cxeHtml({configured:false,active:true,until:2000,now:1000,services:[],files:0,ssh:false});
 const cfg0=Object.assign({},cfg,{hours:0});
 o.idle0=cxeHtml(cfg0);
 o.on0=cxeHtml(Object.assign({},cfg0,{active:true,until:null,since:1000,now:1500,journal:['a']}));
 cxbData={emergency:cfg};
 cxeOn();
 o.dialog=shown[0];
 o.dialogNoSvc=(()=>{shown.length=0;cxbData={emergency:Object.assign({},cfg,{services:[],files:0,ssh:false})};cxeOn();return shown[0];})();
 o.dialog0=(()=>{shown.length=0;cxbData={emergency:cfg0};cxeOn();return shown[0];})();
 cxbData={emergency:Object.assign({},cfg,{active:true})};
 const n=shown.length;cxeOn();o.noDialogWhenActive=shown.length===n;
 cxbData={emergency:cfg};
 await cxeOff();
 confirmAnswer=false;await cxeOff();
 o.posts=posts;o.loads=loads;
 console.log(JSON.stringify(o));
})();
"""


@unittest.skipUnless(__import__("shutil").which("node"), "нет node")
class Emergency(unittest.TestCase):
    """Красная карточка «Аварийный»: скрыта без настройки, включается только через окно со словом, выключается кнопкой."""

    @classmethod
    def setUpClass(cls):
        i = L.PAGE.index("const CXP_ARR=")
        j = L.PAGE.index("function cxpNameHtml(")
        k = L.PAGE.index("function cxeLeftTxt(")
        k2 = L.PAGE.index("function cxpRender(){")
        path = os.path.join(TMP, "emg.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(EMG_JS % (L.PAGE[i:j], L.PAGE[k:k2]))
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout)

    def test_hidden_until_configured(self):
        self.assertEqual(self.o["hiddenWhenNone"], "|")
        self.assertIn('id="cxEmg"', self.o["activeEvenIfNotConfigured"])   # включённый режим видно всегда, даже если настройку убрали

    def test_idle_card_has_only_turn_on_button(self):
        h = self.o["idle"]
        self.assertIn('data-emg="on"', h)
        self.assertNotIn('data-emg="off"', h)
        self.assertNotIn("cxemg on", h)
        self.assertIn("cxeS(24)", h)
        self.assertEqual(h.count("<i>"), 4)               # четыре цветные функции
        self.assertEqual(self.o["idleBad"].count("cxeLastBad"), 1)
        self.assertIn("ACL; владельцы", self.o["idleBad"])

    def test_active_card_is_red_with_time_and_off_button(self):
        h = self.o["on"]
        self.assertIn('class="cxemg on"', h)
        self.assertIn('data-emg="off"', h)
        self.assertNotIn('data-emg="on"', h)
        self.assertIn("cxeUntil(CLK,", h)
        self.assertIn("cxeStat(2,2,true)", h)
        self.assertIn('class="cxemj"', h)

    def test_no_time_limit_card_and_dialog(self):
        # hours=0: срока нет — ни «до …», ни «осталось», в окне подтверждения вместо «само выключится» строка про отсутствие срока
        h = self.o["on0"]
        self.assertIn('data-emg="off"', h)
        self.assertIn("cxeNoLimit(CLK)", h)
        self.assertNotIn("cxeUntil", h)
        self.assertIn("cxeS(0)", self.o["idle0"])
        self.assertIn("cxeConfEnd(0)", self.o["dialog0"])
        self.assertEqual(L.PAGE.count("cxeNoLimit:t=>"), 2)
        self.assertEqual(L.PAGE.count("cxeConfEnd:h=>h?"), 2)   # обе локали различают «0 = без срока»

    def test_confirm_dialog_lists_what_opens_and_asks_for_word(self):
        d = self.o["dialog"]
        for k in ("cxeConfProj", "cxeConfSvc(svc-a.service, svc-b.service)", "cxeConfFiles", "cxeConfRoot", "cxeConfEnd(24)", "cxeConfWord(аварийный)"):
            self.assertIn(k, d)
        self.assertIn('id="cxeWord"', d)
        self.assertIn('id="cxeGo"', d)
        # без сервисов и файлов в списке нет лишних пунктов (про root и доступы молчим, когда их нет)
        n = self.o["dialogNoSvc"]
        self.assertNotIn("cxeConfSvc", n)
        self.assertNotIn("cxeConfRoot", n)
        self.assertNotIn("cxeConfFiles", n)
        self.assertTrue(self.o["noDialogWhenActive"])

    def test_off_asks_first_and_posts_only_on_yes(self):
        self.assertEqual(self.o["posts"], [["chatgpt/emergency/off", {}]])   # «нет» в подтверждении запроса не шлёт
        self.assertEqual(self.o["loads"], 1)

    def test_click_routes_and_no_word_in_page_state(self):
        self.assertIn("em.dataset.emg==='on'?cxeOn():cxeOff()", L.PAGE)
        self.assertEqual(L.PAGE.count("'chatgpt/emergency/on'"), 1)
        self.assertEqual(L.PAGE.count("'chatgpt/emergency/off'"), 1)
        self.assertIn("${cxeHtml(cxbData.emergency)}", L.PAGE)

    def test_server_routes_exist(self):
        with open(L.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('action == "emergency/on"', src)
        self.assertIn('action == "emergency/off"', src)
        self.assertIn('"emergency": cc_codex_emergency.public()', src)


@unittest.skipUnless(__import__("shutil").which("node"), "нет node")
class QuickSwitch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        i = L.PAGE.index("function cxQCur(a){")
        j = L.PAGE.index("async function cxpApply(")
        path = os.path.join(TMP, "quick.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(QUICK_JS % L.PAGE[i:j])
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout)

    def test_current_values(self):
        self.assertEqual(self.o["def"], {"name": "M1", "eff": "low", "ef": "", "known": False})      # по умолчанию: усилие модели
        self.assertEqual(self.o["m2"], {"name": "M2", "eff": "ultra", "ef": "ultra", "known": True})
        self.assertEqual(self.o["unknown"]["name"], "zzz")                                            # чужая модель из config.toml видна как есть
        self.assertEqual(self.o["badEffort"]["ef"], "")                                               # усилия нет у модели → «по умолчанию»

    def test_changes_go_to_prefs_with_safe_combination(self):
        self.assertEqual(self.o["posts"], [
            ["chatgpt/prefs", {"slot": "s", "model": "m3", "effort": "", "fast": False}],
            ["chatgpt/prefs", {"slot": "s", "model": "m2", "effort": "high", "fast": True}],
        ])

    def test_effort_choice_closes_panel_even_without_change(self):
        self.assertTrue(self.o["closedOnSame"])
        self.assertTrue(self.o["openAfterModel"])

    def test_panel_lists_default_models_and_efforts(self):
        h = self.o["html"]
        self.assertIn('data-m=""', h)
        for m in ("m1", "m2", "m3"):
            self.assertIn('data-m="%s"' % m, h)
        self.assertIn('data-e=""', h)
        self.assertIn('data-e="high"', h)
        self.assertNotIn('data-e="ultra"', h)     # у M1 такого усилия нет


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

    def test_renew_route_delegates_and_rechecks_bridge_on_success(self):
        import threading
        ticked = threading.Event()
        with mock.patch.object(L.cc_codex, "renew", return_value=(True, "✅ План: Plus")) as rn, \
                mock.patch.object(L.cc_codex_bridge.BRIDGE, "limits_tick", side_effect=ticked.set):
            self.assertEqual(self.post("renew", {"slot": "gpt1", "lang": "en"}), (200, {"ok": True, "message": "✅ План: Plus"}))
            rn.assert_called_once_with("/x/codex", "gpt1", lang="en")
            self.assertTrue(ticked.wait(3), "после успешного «Я продлил» мост не сверил карточку")
        ticked.clear()
        with mock.patch.object(L.cc_codex, "renew", return_value=(False, "Пока Free")), \
                mock.patch.object(L.cc_codex_bridge.BRIDGE, "limits_tick", side_effect=ticked.set):
            self.assertEqual(self.post("renew", {"slot": "gpt1"}), (200, {"ok": False, "message": "Пока Free"}))
            self.assertFalse(ticked.wait(0.3))

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


class ConsoleColors(unittest.TestCase):
    """Блок сообщения пользователя в Codex (фон SGR 48;5;8 = 7f7f7f у pyte) рисуется без серой полосы."""

    def _html(self, row_html):
        import pyte
        screen = pyte.Screen(20, 2)
        pyte.Stream(screen).feed("\x1b[39;48;5;8m  вопрос        \x1b[0m\r\n\x1b[41mкрасный\x1b[0m")
        return [row_html(screen.buffer[y], 20) for y in range(2)]

    def test_codex_mirror_drops_user_block_band(self):
        # серой полосы нет вовсе (как в консоли Claude), текст остаётся
        rows = self._html(L.cc_codex_console.ROW_HTML)
        self.assertNotIn("background", rows[0])
        self.assertIn("вопрос", rows[0])

    def test_codex_mirror_keeps_other_backgrounds(self):
        # красный фон ANSI (базовый 41) остаётся как есть
        rows = self._html(L.cc_codex_console.ROW_HTML)
        self.assertIn("background:#e05b5b", rows[1])

    def test_claude_console_colors_unchanged(self):
        rows = self._html(L._row_html)
        self.assertIn("background:#7f7f7f", rows[0])


if __name__ == "__main__":
    unittest.main()