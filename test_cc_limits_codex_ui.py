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

    def test_header_has_no_language_switch(self):
        # переключатель RU·EN из шапки убран (на телефоне занимал целую строку): ни элемента, ни кнопок смены
        page = L.PAGE
        for bad in ('id="langSwitch"', 'setLang(', 'renderLangSwitch'):
            self.assertNotIn(bad, page, bad)

    def test_language_comes_from_link_or_saved_choice(self):
        # без кнопки язык задаётся ссылкой ?lang=en|ru (и запоминается), иначе сохранённый выбор, иначе русский
        page = L.PAGE
        self.assertIn("localStorage.getItem('cc_lang')||'ru'", page)
        self.assertIn("new URLSearchParams(location.search).get('lang')", page)
        self.assertIn("q==='ru'||q==='en'", page)

    def test_header_buttons_left_and_codex_right(self):
        # ↻ ⚙ + стоят слева, у «Оптимизации»; блок Codex — в правой группе, последним
        page = L.PAGE
        order = [page.index(k) for k in ('id="optWrap"', 'id="rfBtn"', 'id="gear"', 'id="addAcct"', 'id="cxGrp"')]
        self.assertEqual(order, sorted(order))
        self.assertLess(page.index('class="hdrbtns"'), page.index('class="hdrctl"'))
        self.assertGreater(page.index('id="rfBtn"'), page.index('class="hdrbtns"'))
        self.assertIn('html:root:root .hdrbtns{order:3', page)

    def test_header_split_group_profile_menu_and_gear(self):
        # «>_ Профиль ▾» и шестерёнка — одна группа; меню профилей и окно настроек — разные панели
        page = L.PAGE
        grp = re.search(r'<div class="cxgrp" id="cxGrp"[^>]*>(.*?)</div></div></div>\s*<div class="ccpause"', page, re.S)
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
        grp = re.search(r'<div class="cxgrp" id="cxGrp"[^>]*>(.*?)</div></div></div>\s*<div class="ccpause"', page, re.S).group(1)
        self.assertLess(grp.index('id="cxBtn"'), grp.index('id="cxMod"'))
        self.assertLess(grp.index('id="cxMod"'), grp.index('id="cxGear"'))
        self.assertEqual(page.count('id="cxQ"'), 1)
        self.assertRegex(page, r'<div id="cxQ"[^>]*\bhidden\b')
        # панели друг друга закрывают, клик мимо и Esc закрывают быструю панель
        self.assertIn("closest('#cxQ,#cxMod')", page)
        self.assertRegex(page, r"Escape'[^\n]*cxQClose\(\)")

    def test_add_account_dialog_explains_device_code_signin(self):
        """Окно «+»: человек с нуля узнаёт, что вход по коду устройства включается в ChatGPT (Безопасность) и что в рабочем
        пространстве это делает администратор — и по-русски, и по-английски."""
        src = open(os.path.join(os.path.dirname(__file__), "cc_limits.py"), encoding="utf-8").read()
        ru = re.search(r"cxAddSub:'([^\n]*)',", src).group(1)
        en = re.findall(r"cxAddSub:'([^\n]*)',", src)[1]
        for text, words in ((ru, ("Безопасность", "администратор", "код")), (en, ("Security", "admin", "code"))):
            for w in words:
                self.assertIn(w, text)

    def test_bot_switch_is_not_a_profile(self):
        # «Выключен» — не профиль; выключатель бота в меню профилей не нужен (просьба владельца): он живёт только в ⚙ → «Мост Telegram»
        self.assertNotRegex(L.PAGE, r"p\.on\b|on===false|cxpS_off|cxpOffStop")
        r = re.search(r"function cxpRender\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertNotIn("cxpBotHtml", r)
        self.assertNotRegex(L.PAGE, r"cxpBot|data-bot|\.cxbot\b|\.cxsw\b")
        form = re.search(r"function cxbRender\(force\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn('id="cxbOn"', form)
        self.assertIn("const on=$('#cxbOn')", L.PAGE)
        self.assertIn("enabled:!!(on&&on.checked)", L.PAGE)

    def test_profiles_menu_is_side_drawer_on_desktop_only(self):
        # ПК (>640 px): шторка справа на всю высоту, с крестиком и скримом; телефон — выпадающее меню под кнопкой, как раньше
        self.assertIn('id="cxMenuScrim"', L.PAGE)
        self.assertRegex(L.PAGE, r"@media \(min-width:641px\)\{[^@]*\.cxpop\.cxmenu\{[^}]*right:0[^}]*height:100%")
        self.assertRegex(L.PAGE, r"@media \(max-width:640px\)\{\s*\.cxscrim\{display:none!important\}")
        place = re.search(r"function cxMenuPlace\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("innerWidth>640", place)
        # «назад» закрывает шторку, а не приложение: pushState + popstate
        self.assertIn("history.pushState({cxm:1}", L.PAGE)
        self.assertRegex(L.PAGE, r"addEventListener\('popstate'")
        # крестик в шапке закрывает меню
        self.assertIn('data-close="1"', L.PAGE)
        self.assertRegex(L.PAGE, r"closest\('\[data-close\]'\)\)\{e\.stopPropagation\(\);cxMenuClose\(\);return;\}")

    def test_console_tabs_are_coloured_orange_claude_blue_codex(self):
        # вкладки консолей: Claude — спокойный оранжевый, Codex — спокойный синий (просьба владельца); перекрывают скины
        self.assertRegex(L.PAGE, r"html:root:root \.iconbtn\.ctab\[data-s\]\{--tc:224,144,90;")
        self.assertRegex(L.PAGE, r'html:root:root \.iconbtn\.ctab\[data-s="codex"\]\{--tc:104,154,236;')
        self.assertRegex(L.PAGE, r"\.iconbtn\.ctab\[data-s\]\.on\{")

    def test_console_tabs_inactive_is_outline_only_active_is_filled(self):
        # просьба владельца (60742): неактивная вкладка — только окантовка без фона, активная окрашена целиком
        css = L.PAGE
        base = re.search(r"^html:root:root \.iconbtn\.ctab\[data-s\]\{([^}]*)\}$", css, re.M).group(1)
        self.assertIn("background:transparent", base)
        self.assertIn("box-shadow:none", base)             # скин blocks рисует жёсткую тень — это тоже «фон»
        self.assertRegex(base, r"border:1px solid rgba\(var\(--tc\),\.7\)")
        hov = re.search(r"^html:root:root \.iconbtn\.ctab\[data-s\]:hover\{([^}]*)\}$", css, re.M).group(1)
        self.assertIn("background:transparent", hov)      # наведение заливку не даёт
        on = re.search(r"^html:root:root \.iconbtn\.ctab\[data-s\]\.on\{([^}]*)\}$", css, re.M).group(1)
        self.assertIn("background:rgb(var(--tc))", on)    # сплошная заливка цветом вкладки, не прозрачная
        self.assertNotRegex(on, r"background:rgba")
        self.assertIn("color:var(--ton)", on)
        # «активная» стоит ПОСЛЕ «наведения»: активная под курсором остаётся залитой
        self.assertGreater(css.index(".iconbtn.ctab[data-s].on{"), css.index(".iconbtn.ctab[data-s]:hover{"))
        # у каждой вкладки свой тёмный цвет текста на заливке (оранжевая и синяя читаются)
        self.assertRegex(css, r"\.iconbtn\.ctab\[data-s\]\{--tc:224,144,90;[^}]*--ton:#[0-9a-f]{6}")
        self.assertRegex(css, r'\.iconbtn\.ctab\[data-s="codex"\]\{--tc:104,154,236;[^}]*--ton:#[0-9a-f]{6}')
        # плашки под кнопками нет: тёмная подложка контейнера делала неактивную вкладку «залитой»
        self.assertRegex(css, re.compile(r"^\.ctabs\{[^}]*background:transparent[^}]*\}$", re.M))
        self.assertNotRegex(css, r"\.ctabs\{[^}]*background:rgba")

    def test_console_tabs_rules_beat_every_skin(self):
        # правило вкладок специфичнее любого скина (по скинам .iconbtn красится фоном/тенью/рамкой)
        css = L.PAGE
        for skin in ("phosphor", "aurora", "slate", "blocks"):
            self.assertRegex(css, r'html\[data-skin="%s"\] \.hdrgear,html\[data-skin="%s"\] \.iconbtn\{' % (skin, skin))
        self.assertIn("html:root:root .iconbtn.ctab[data-s]{", css)

    def test_form_has_project_and_own_workdir_fields(self):
        # «Проект» — всегда (Codex его только читает), «Рабочая папка Codex» — только в режиме «Самостоятельно»; project уходит, лишь если его правили
        form = re.search(r"function cxbRender\(force\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn('id="cxbProj"', form)
        self.assertIn('id="cxbDirRow"', form)
        self.assertIn("$('#cxbDirRow').hidden=b.mode!=='self'", re.search(r"function cxbSync\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0))
        save = re.search(r"async function cxbSave\(\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("if(pj!==cxbProjVal(b))body.project=pj", save)

    def test_form_texts_follow_profile(self):
        # профиль «Codex»: рабочая папка (там он может всё) идёт первой, проект — «только чтение»; в «Оркестраторе» проект как был
        form = re.search(r"function cxbRender\(force\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("${self?dirBlock+projBlock:projBlock+dirBlock}", form)
        self.assertIn("tr(self?'cxbProjectSelf':'cxbProject')", form)
        self.assertIn("tr(self?'cxbProjHintSelf':'cxbProjHint')", form)
        for lang, word in (("ru", "создавать файлы и папки"), ("en", "create files and folders")):
            blk = i18n_block(lang)
            for key in ("cxbProjectSelf", "cxbProjHintSelf", "cxbDirSelf"):
                self.assertRegex(blk, r"(?m)^\s{2}%s:'.+',$" % key)
            self.assertIn(word, re.search(r"(?m)^\s{2}cxbDirSelf:'(.*)',$", blk).group(1))

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


class NoComposer(unittest.TestCase):
    """Сборщик своего профиля и ручные списки режим/доступ/права убраны: профиль задаёт режим."""

    def test_composer_and_manual_lists_are_gone(self):
        page = L.PAGE
        for bad in ('id="cxpc"', 'id="cxPrW"', "cxpNewBtn", "cxpcRender", "cxpDraft", "cxpSave", "cxpGoCompose",
                    "profile/save", 'id="cxbMode"', 'id="cxbAcc"', 'id="cxbRights"', 'id="cxbConf"', "cxbConfRow"):
            self.assertNotIn(bad, page, bad)
        menu = re.search(r'<div id="cxMenu".*?</div></div>', page, re.S).group(0)
        self.assertNotIn("cxpc", menu)
        self.assertEqual(page.count('id="cxLim"'), 1)

    def test_bridge_form_keeps_slot_folders_token_chat_switch(self):
        page = L.PAGE
        for need in ('id="cxbSlot"', 'id="cxbProj"', 'id="cxbDir"', 'id="cxbTok"', 'id="cxbChat"', 'id="cxbOn"'):
            self.assertIn(need, page, need)

    def test_save_sends_no_mode_fields(self):
        """Форма моста не шлёт режим/доступ/права — профиль не сбрасывается при сохранении токена, чата, папок."""
        m = re.search(r"async function cxbSave\(\)\{.*?\n\}\n", L.PAGE, re.S)
        self.assertTrue(m)
        for bad in ("cxbMode", "cxbAcc", "cxbRights", "task_rights", "confirm"):
            self.assertNotIn(bad, m.group(0), bad)


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
                mock.patch.object(L.cc_codex_bridge, "delete_profile", return_value=(False, "no")) as dl:
            self.assertEqual(self.post("bridge/profile/apply", {"id": "orchestrator", "confirm": "x", "lang": "en"}),
                             (200, {"ok": True, "message": "ok"}))
            ap.assert_called_once_with("orchestrator", "x", lang="en")
            # сборка своего профиля убрана — маршрута больше нет
            self.assertEqual(self.post("bridge/profile/save", {"name": "Ночной"})[0], 404)
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


class NotionBlock(unittest.TestCase):
    """Блок Notion в шапке левее кнопки Codex: переключатель, шестерёнка и маршрут сохранения."""

    def test_block_sits_left_of_codex_group_and_no_card_under_accounts(self):
        page = L.PAGE
        self.assertIn('id="ntGrp"', page)
        self.assertLess(page.index('id="ntGrp"'), page.index('id="cxGrp"'))
        for need in ('id="ntBtn"', 'role="switch"', 'id="ntGear"', 'id="ntPop"'):
            self.assertIn(need, page)
        # старой плитки среди аккаунтов нет
        self.assertNotIn("notionCard", page)
        self.assertNotIn(".card.notion", page)
        self.assertIn("ntApply(d.notion)", page)

    def test_every_nt_text_has_both_languages(self):
        ru, en = i18n_block("ru"), i18n_block("en")
        keys = lambda b: set(re.findall(r"^\s*(nt[A-Za-z0-9]+):", b, re.M))
        self.assertTrue(keys(ru), "в ru нет ключей nt*")
        self.assertEqual(keys(ru), keys(en))

    def test_setup_steps_have_no_personal_names(self):
        # инструкция «с нуля» уходит в публичный репозиторий: ни настоящей ссылки агента
        blob = i18n_block("ru") + i18n_block("en")
        self.assertNotRegex(blob, r"agent://[A-Za-z0-9]")  # «agent://…» как подсказка формата — можно, настоящий id — нет
        # сама команда стоит в разметке окна (не в словаре) и одна на оба языка
        self.assertEqual(L.PAGE.count("claude mcp add --transport http notion https://mcp.notion.com/mcp"), 1)

    def test_only_one_popup_open_at_a_time(self):
        # каждое из окон закрывает окно Notion при открытии, а оно — их
        page = L.PAGE
        for fn in ("cxPopOpen", "cxMenuOpen", "cxQOpen"):
            m = re.search(r"function %s\([^)]*\)\{(.*?)\n\}" % fn, page, re.S)
            self.assertTrue(m, fn)
            self.assertIn("ntClose()", m.group(1), fn)
        self.assertIn("ntPop", re.search(r"addEventListener\('pointerdown'.*?\}\);", page, re.S).group(0))

    def test_mobile_row_codex_not_squeezed_below_280(self):
        # на телефоне блок Notion держит размер, а Codex не сжимается меньше 280 px: не хватает места — уходит на свою строку
        # (иначе при шапке из индикатора, переключателя и ⚙ кнопки Codex налезают друг на друга)
        self.assertIn("html:root:root .ntgrp{flex:none}", L.PAGE)
        self.assertIn("html:root:root .cxgrp{flex:1 1 280px;min-width:0}", L.PAGE)
        self.assertIn("html:root:root .hdrctl{flex:1 1 100%;min-width:0;flex-wrap:wrap;justify-content:flex-end}", L.PAGE)


class NotionReservePage(unittest.TestCase):
    """Секция «Резерв» в окне Notion: две галочки (авто и аварийный), пояснение про переключатель, строка состояния и живой опрос."""

    def test_two_checkboxes_and_status_line_in_popup(self):
        page = L.PAGE
        for need in ('id="ntResAuto"', 'id="ntResEmg"', 'id="ntResSt"'):
            self.assertIn(need, page)
        # ручной резерв — только переключателем в шапке: галочки «вручную» в окне больше нет
        self.assertNotIn('id="ntResManual"', page)
        # две оставшиеся галочки идут в одном теле запроса сохранения и не трогают ручной резерв
        self.assertIn("reserve:{auto:$('#ntResAuto').checked,auto_emergency:$('#ntResEmg').checked}", page)

    def test_emergency_checkbox_needs_auto(self):
        # «сразу включать аварийный режим» не имеет смысла без «включать само»: недоступна и при отрисовке, и при клике
        self.assertIn("e.disabled=!rv.auto", L.PAGE)
        self.assertIn("$('#ntResEmg').disabled=!body.reserve.auto", L.PAGE)

    def test_header_switch_is_the_reserve_and_icon_is_only_an_indicator(self):
        page = L.PAGE
        self.assertIn("b.classList.toggle('res',res)", page)
        self.assertIn("$('#ntBtnName').textContent=tr('ntBtnRes')", page)
        # иконка — не кнопка и ни на что не нажимается; переключатель — кнопка role=switch
        self.assertIn('<span id="ntInd" class="hdrgear ntind" role="img"', page)
        self.assertIn('id="ntBtn" class="hdrgear ntbtn" type="button" role="switch"', page)
        self.assertNotIn("ntInd').addEventListener", page)
        # точка индикатора: зелёная — подключён, красная — нужен вход
        self.assertIn("$('#ntDot').className='cxdot '+(ok?'on':'err')", page)

    def test_status_poll_is_light_and_stops_with_the_window(self):
        page = L.PAGE
        self.assertIn("fetch(API+'notion?token='+TOKEN)", page)  # а не весь снимок аккаунтов
        self.assertIn("setInterval(ntRefresh,4000)", page)       # пока окно открыто
        close = re.search(r"function ntClose\(\)\{(.*?)\n\}", page, re.S).group(1)
        self.assertIn("clearInterval(ntPollT)", close)           # закрыли — опрос снят
        self.assertIn("setInterval(ntRefresh,15000)", page)      # кнопка в шапке тоже живая

    def test_idle_text_tells_when_auto_is_armed(self):
        self.assertIn("tr(rv.auto?'ntResIdleAuto':'ntResIdle')", L.PAGE)

    def test_reserve_texts_have_no_personal_names_or_internal_words(self):
        blob = i18n_block("ru") + i18n_block("en")
        for line in re.findall(r"^\s*(ntRes\w*:.*)$", blob, re.M):
            self.assertNotRegex(line, r"(?i)\b(прод|дев|хаб|prod|dev|hub)\b", line)


class ReserveProfileAndPausePage(unittest.TestCase):
    """Профиль «Резерв» в меню Codex и баннер паузы резерва: оба языка, без ручного выбора, понятные подписи."""

    KEYS = ("ntResSwNote", "ntResConfirm", "ntSwTipOff", "ntSwTipOn", "ntSwTipAuto", "cxpN_reserve", "cxpS_reserve", "cxpS_reserveOn", "ccpResTitle", "ccpResSub", "ccpHintResOff")

    def test_new_texts_exist_in_both_languages_and_are_not_empty(self):
        for lang in ("ru", "en"):
            blk = i18n_block(lang)
            for k in self.KEYS:
                m = re.search(r"^\s*%s:'(.+)',?$" % k, blk, re.M)
                self.assertTrue(m, "%s нет в %s" % (k, lang))
                self.assertGreater(len(m.group(1)), 3 if k == "cxpN_reserve" else 8, k)  # имя профиля короткое

    def test_new_texts_have_no_internal_words_or_personal_names(self):
        blob = i18n_block("ru") + i18n_block("en")
        for k in self.KEYS:
            line = re.search(r"^\s*%s:.*$" % k, blob, re.M).group(0)
            self.assertNotRegex(line, r"(?i)\b(прод|дев|хаб|prod|dev|hub)\b", line)
            self.assertNotRegex(line, r"agent://[A-Za-z0-9]")

    def test_reserve_card_is_last_and_cannot_be_picked_by_hand(self):
        page = L.PAGE
        card = page[page.index("const rsv=`"):][:900]
        self.assertIn('data-id="reserve" data-auto="1"', card)
        self.assertIn('aria-disabled="true"', card)
        self.assertIn("${items}${rsv}", page)  # после обычных профилей, внутри того же radiogroup
        # клик и клавиши по такой карточке только поясняют, профиль не применяют
        self.assertEqual(page.count("if(r.dataset.auto){toast(tr('cxpS_reserve'));return;}"), 2)
        for handler in ("const r=e.target.closest('.cxprof');if(r){if(r.dataset.auto)",):
            self.assertIn(handler, page)

    def test_reserve_card_active_state_comes_from_bridge_profile(self):
        page = L.PAGE
        self.assertRegex(page, r"const rs=[^;\n]*profile\s*===?\s*'reserve'")
        self.assertIn("tr(rs?'cxpS_reserveOn':'cxpS_reserve')", page)
        self.assertIn("rsv${rs?' act':''}", page)

    def test_header_names_reserve_when_bridge_runs_on_it(self):
        self.assertIn("b&&b.profile==='reserve'?tr('cxpN_reserve')", L.PAGE)

    def test_reserve_is_not_a_builtin_card_the_meta_stays_two(self):
        import cc_codex_bridge as br
        self.assertNotIn("reserve", [p for p, _ in br.BUILTIN_PROFILES])
        meta = L.PAGE[L.PAGE.index("const CXP_META="):][:600]
        self.assertNotIn("reserve", meta)

    def test_pause_banner_has_its_own_reserve_branch_with_emergency_exit(self):
        page = L.PAGE
        branch = re.search(r"if\(pause\.kind==='reserve'\)\{(.*?)\}", page, re.S)
        self.assertTrue(branch)
        for need in ("ccpResTitle", "ccpResSub", "act:'off'", "ccpHintResOff"):
            self.assertIn(need, branch.group(1))
        # без будильника: у паузы резерва нет «подъём в …», ветка стоит раньше обычных
        self.assertLess(page.index("pause.kind==='reserve'"), page.index("tr('ccpBtnOff')", page.index("pause.kind==='reserve'")))

    def test_switch_explains_what_reserve_mode_means(self):
        self.assertIn("<div class=\"ntnote\">${tr('ntResSwNote')}</div>", L.PAGE)
        self.assertIn(".ntnote{", L.PAGE)
        # перед включением — окно подтверждения с пояснением, что значит резервный режим
        for lang, need in (("ru", ("Точно перейти в резервный режим?", "Claude встанет на паузу", "Codex и Notion-агент", "Выключишь переключатель")),
                           ("en", ("Really switch to reserve mode?", "Claude is paused", "Codex and the Notion agent", "Turn the switch off"))):
            conf = re.search(r"^\s*ntResConfirm:'(.+)',?$", i18n_block(lang), re.M).group(1)
            for part in need:
                self.assertIn(part, conf, lang)

    def test_reserve_card_styles_exist(self):
        page = L.PAGE
        for need in ('.cxprof[data-id="reserve"]{--pc:', ".cxprof.rsv:not(.act){opacity:.65;cursor:default}"):
            self.assertIn(need, page)


NT_JS = """
const classes={};
const mk=id=>({id,hidden:false,title:'',textContent:'',className:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;},classList:{toggle:(c,on)=>{const s=classes[id]||(classes[id]=new Set());on?s.add(c):s.delete(c);}}});
const els={'#ntGrp':mk('g'),'#ntBtn':mk('b'),'#ntBtnName':mk('n'),'#ntGear':mk('gear'),'#ntInd':mk('ind'),'#ntDot':mk('dot'),'#ntPop':{hidden:true}};
const $=s=>els[s];
const tr=(k,...a)=>a.length?k+'('+a.join(',')+')':k;
const toasts=[];const toast=t=>toasts.push(t);
function ntClose(){}function ntResPaint(){}
const calls=[],timers=[];const ccpLoad=()=>calls.push('load'),cxbLoad=f=>calls.push('cxb'+(f?'!':'')),ntRefresh=()=>calls.push('refresh'),setTimeout=(f,ms)=>timers.push([f,ms]);
%s
(()=>{
 const o={};
 const base={available:true,connected:true,reserve:{active:false,ready:true,manual:false,claude:'up'}};
 const res=(a,c)=>Object.assign({},base,{reserve:{active:a,ready:true,manual:false,claude:c||'up'}});
 const snap=()=>({g:[...(classes.g||[])].sort().join(','),b:[...(classes.b||[])].sort().join(','),checked:els['#ntBtn'].attrs['aria-checked'],disabled:els['#ntBtn'].attrs['aria-disabled'],dot:els['#ntDot'].className,tip:els['#ntBtn'].title});
 ntApply(base);o.idle=snap();
 ntApply(Object.assign({},base,{connected:false}));o.bad=snap();
 ntApply(Object.assign({},base,{reserve:{active:false,ready:false,manual:false,claude:'up'}}));o.notReady=snap();
 ntApply(Object.assign({},base,{reserve:{active:true,ready:true,manual:true,why:'manual',claude:'up'}}));o.manual=snap();
 ntApply(Object.assign({},base,{reserve:{active:true,ready:false,manual:true,why:'manual',claude:'up'}}));o.manualLost=snap();  // агент пропал, галочка осталась: выключить можно
 ntApply(res(true));o.res=snap();o.toastsWithoutClick=toasts.length;   // сам по себе (авто-случай) тост не нужен
 ntAfter();ntApply(res(false));o.toastOff=toasts.slice();                // человек нажал, резерв снялся
 ntAfter();ntApply(res(true));o.toastOn=toasts.slice(1);
 ntAfter();ntApply(res(false,'down'));o.toastDown=toasts.slice(2);
 ntApply(res(false,'down'));o.noRepeat=toasts.length;                    // тот же показ ещё раз — без повторного тоста
 ntSync();o.syncNow=calls.splice(0);o.timerMs=timers.map(t=>t[1]);   // сразу — один ccpLoad; позже — ntRefresh + ccpLoad
 timers.forEach(t=>t[0]());o.syncLater=calls.splice(0);
 console.log(JSON.stringify(o));
})();
"""

BANNER_JS = """
const LANG='ru';
let T=1000000000000;Date.now=()=>T;
const tr=(k,...a)=>a.length?k+'('+a.join(',')+')':k;
const el={hidden:true,className:'',innerHTML:''};
const $=s=>s==='#ccPause'?el:null;
const CCP_GRACE_STUB=0;
%s
const out=(pause)=>{ccpData={stale:false,level:'none',threshold:90,weekly_cap:99,accounts:{},active:'a',pause:Object.assign({active:true,kind:'reserve',since:T/1000-5,resume_at:0,reason:'r',override:false},pause)};ccpRender();return el.innerHTML;};
const o={};
o.none=out({notice_ts:0,grace:120});
o.mid=out({notice_ts:T/1000-30,grace:120});
o.late=out({notice_ts:T/1000-500,grace:120});
o.noGraceField=out({notice_ts:T/1000-30});   // старый ответ сервера без поля grace — берём константу страницы
o.limits=(()=>{ccpData={stale:false,level:'none',threshold:90,weekly_cap:99,accounts:{},active:'a',pause:{active:true,kind:'session',since:T/1000-5,resume_at:T/1000+600,reason:'r',override:false}};ccpRender();return el.innerHTML;})();
o.untilMid=T+90000;
console.log(JSON.stringify(o));
"""


@unittest.skipUnless(__import__("shutil").which("node"), "нет node")
class NotionInstantAndFrame(unittest.TestCase):
    """Тумблер и галочки Notion действуют сразу, рамка блока одна на всю группу, баннер резерва показывает отсчёт «доделывает»."""

    @classmethod
    def setUpClass(cls):
        page = L.PAGE
        i, j = page.index("let ntData=null,ntPrevRes"), page.index("// строка «что с резервом сейчас»")
        path = os.path.join(TMP, "nt_apply.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(NT_JS % page[i:j])
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout)
        i, j = page.index("let ccpData=null"), page.index("function ccpTick(){")
        path = os.path.join(TMP, "banner.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(BANNER_JS % page[i:j])
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.b = json.loads(r.stdout)

    # --- переключатель в шапке = ручной резерв; иконка N = только индикатор ---
    def _run_toggle(self, reserve, confirm_answer, notion_after):
        m = re.search(r"async function ntToggle\(\)\{.*?\n\}\n", L.PAGE, re.S)
        self.assertTrue(m)
        js = (
            "let ntData={available:true,connected:true,reserve:%s};\n"
            "const seen=[];const asked=[];const toasts=[];function ntAfter(){}function ntSync(){}const toast=t=>toasts.push(t);const tr=k=>k;\n"
            "const confirm=t=>{asked.push(t);return %s;};\n"
            "function ntApply(n){seen.push(JSON.parse(JSON.stringify(n)));ntData=n;}\n"
            "const posted=[];const acctPost=async(u,b)=>{posted.push([u,b]);return {ok:true,notion:%s};};\n"
            % (json.dumps(reserve), "true" if confirm_answer else "false", json.dumps(notion_after))
            + m.group(0) +
            "ntToggle().then(()=>console.log(JSON.stringify({seen,posted,asked,toasts})));\n"
        )
        path = os.path.join(TMP, "nt_toggle.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_turning_reserve_on_asks_first_and_posts_only_manual(self):
        r0 = {"active": False, "ready": True, "manual": False, "auto": True, "claude": "up"}
        after = {"available": True, "connected": True, "reserve": dict(r0, active=True, manual=True, why="manual")}
        out = self._run_toggle(r0, True, after)
        self.assertEqual(out["asked"], ["ntResConfirm"])                       # сначала окно с пояснением
        self.assertEqual(out["posted"], [["notion/save", {"reserve": {"manual": True}}]])  # на сервер уходит только «вручную»
        first = out["seen"][0]                                                # показ ДО ответа сервера (мгновенный отклик)
        self.assertEqual((first["reserve"]["manual"], first["reserve"]["active"], first["reserve"]["why"]), (True, True, "manual"))

    def test_declined_confirm_changes_nothing(self):
        r0 = {"active": False, "ready": True, "manual": False, "claude": "up"}
        out = self._run_toggle(r0, False, {})
        self.assertEqual(out["asked"], ["ntResConfirm"])
        self.assertEqual((out["seen"], out["posted"]), ([], []))              # ни показа, ни запроса: Claude не остановлен

    def test_not_ready_reserve_does_not_ask_and_explains(self):
        r0 = {"active": False, "ready": False, "manual": False, "claude": "up"}
        out = self._run_toggle(r0, True, {})
        self.assertEqual((out["asked"], out["seen"], out["posted"]), ([], [], []))
        self.assertEqual(out["toasts"], ["ntResNotReady"])

    def test_turning_off_needs_no_confirmation_and_clears_manual_at_once_keeping_auto(self):
        r0 = {"active": True, "ready": True, "manual": True, "auto": True, "why": "manual", "claude": "up"}
        after = {"available": True, "connected": True, "reserve": dict(r0, active=False, manual=False, why="")}
        out = self._run_toggle(r0, False, after)                              # confirm даже «нет» не мешает: выключение подтверждения не требует
        self.assertEqual(out["asked"], [])
        first = out["seen"][0]
        self.assertEqual((first["reserve"]["manual"], first["reserve"]["active"], first["reserve"]["auto"]), (False, False, True))
        self.assertEqual(out["posted"], [["notion/save", {"reserve": {"manual": False}}]])

    def test_turning_off_manual_while_limits_are_over_keeps_reserve_active_by_auto(self):
        r0 = {"active": True, "ready": True, "manual": True, "auto": True, "why": "manual", "claude": "down"}
        out = self._run_toggle(r0, True, {"available": True, "connected": True, "reserve": dict(r0, manual=False, why="claude_down")})
        first = out["seen"][0]["reserve"]
        self.assertEqual((first["manual"], first["active"], first["why"]), (False, True, "claude_down"))

    # --- рамка блока ---
    def test_group_classes_follow_state(self):
        o = self.o
        self.assertEqual(o["idle"]["g"], "")              # подключён, резерва нет: рамки нет совсем
        self.assertEqual(o["bad"]["g"], "bad")            # нет связи: красная
        self.assertEqual(o["res"]["g"], "res")            # идёт резерв: зелёная
        self.assertEqual(o["res"]["b"], "res")            # подпись переключателя тоже зелёная
        self.assertEqual(o["manual"]["g"], "res")

    def test_indicator_dot_shows_only_connection(self):
        o = self.o
        self.assertEqual(o["idle"]["dot"], "cxdot on")
        self.assertEqual(o["bad"]["dot"], "cxdot err")
        self.assertEqual(o["manual"]["dot"], "cxdot on")  # резерв точку не трогает: она про подключение

    def test_switch_state_follows_manual_flag_and_ready(self):
        o = self.o
        self.assertEqual((o["idle"]["checked"], o["idle"]["disabled"]), ("false", "false"))
        self.assertEqual((o["manual"]["checked"], o["manual"]["disabled"]), ("true", "false"))
        self.assertEqual((o["res"]["checked"], o["res"]["disabled"]), ("false", "false"))   # включился сам — переключатель ручной, он «выкл»
        self.assertEqual((o["notReady"]["checked"], o["notReady"]["disabled"]), ("false", "true"))
        self.assertIn("dis", o["notReady"]["b"])
        self.assertEqual(o["notReady"]["tip"], "ntResNotReady")
        self.assertEqual((o["manualLost"]["checked"], o["manualLost"]["disabled"]), ("true", "false"))  # агент пропал, а галочка осталась: выключить можно
        self.assertEqual(o["idle"]["tip"], "ntSwTipOff")
        self.assertEqual(o["manual"]["tip"], "ntSwTipOn")
        self.assertEqual(o["res"]["tip"], "ntSwTipAuto")

    def test_frame_is_drawn_on_both_buttons_of_the_group_and_beats_skins(self):
        css = L.PAGE
        rules = re.findall(r"^(html:root \.ntgrp[^{]*)\{([^}]*)\}$", css, re.M)
        sel = {a: b for a, b in rules}
        # без резерва рамка есть — обычная серая рамка скина, как у группы Codex; своего «прозрачного» правила у блока нет
        self.assertNotIn("html:root .ntgrp .hdrgear", sel)
        self.assertNotIn("border-color:transparent", "".join(sel.values()))
        # обе кнопки группы (переключатель и ⚙) красятся одним правилом по классу группы:
        # зелёная рамка — ТОЛЬКО при включённом резерве; «просто включён» цвета не меняет; нет связи — красная; жёлтого нет совсем
        self.assertIn("rgba(52,192,124", sel["html:root .ntgrp.res .hdrgear"])
        self.assertIn("var(--bad)", sel["html:root .ntgrp.bad .hdrgear"])
        self.assertNotIn("html:root .ntgrp.enab .hdrgear", sel)
        self.assertNotIn("--warn", "".join(sel.values()))
        self.assertIn(".ntbtn.res{color:var(--ok)}", css)
        self.assertNotIn(".ntbtn.res{color:var(--warn)}", css)
        self.assertNotIn(".ntbtn.res .ntsw::after{background:var(--warn)}", css)
        # правила стоят позже всех скинов и в ТОЙ ЖЕ специфичности, что и их :hover (0,3,1) — выигрывают порядком
        # (правило «.hdrgear.ntbtn{color}» у blocks красит только текст, рамку и тень не трогает — в счёт не идёт)
        last_skin = max(m.start() for m in re.finditer(r'html\[data-skin="(?:phosphor|aurora|slate|blocks)"\] \.hdrgear(?::hover)?[,{]', css))
        self.assertGreater(css.index("html:root .ntgrp.res .hdrgear{"), last_skin)
        self.assertGreater(css.index("html:root .ntgrp.bad .hdrgear{"), last_skin)
        # старые рамки по кнопке (они красили только переключатель и не доходили до ⚙) убраны
        for old in ('.ntbtn[aria-checked="true"]{border-color', ".ntbtn.bad{border-color", ".ntbtn.res{border-color"):
            self.assertNotIn(old, css)
        self.assertNotIn(".ntgbtn[aria-expanded=\"true\"]{border-color", css)  # открытое ⚙ рамку группы не перекрашивает

    # --- тосты о смене режима ---
    def test_toast_only_after_a_human_action(self):
        o = self.o
        self.assertEqual(o["toastsWithoutClick"], 0)
        self.assertEqual(o["toastOff"], ["ntResOffToast(false)"])
        self.assertEqual(o["toastOn"], ["ntResOnToast"])
        self.assertEqual(o["toastDown"], ["ntResOffToast(true)"])  # лимиты ещё кончились: честный текст
        self.assertEqual(o["noRepeat"], 3)

    def test_every_change_syncs_banner_right_away_and_again_later(self):
        o = self.o
        self.assertEqual(o["syncNow"], ["load", "cxb!"])       # баннер паузы и имя профиля в шапке Codex — сразу, без ожидания опросов
        self.assertEqual(o["timerMs"], [2500])                 # и ровно один догоняющий вызов
        self.assertEqual(o["syncLater"], ["refresh", "load", "cxb!"])  # блок Notion, баннер и шапка Codex — после долгих шагов (пауза, профиль, перезапуск консоли)
        page = L.PAGE
        for fn in ("ntToggle", "ntResSave", "ntSave"):
            body = re.search(r"(?:async )?function %s\([^)]*\)\{(.*?)\n\}\n" % fn, page, re.S).group(1)
            self.assertIn("ntSync()", body, fn)
            self.assertIn("ntAfter()", body, fn)

    def test_switching_shows_result_on_screen_without_waiting_for_server(self):
        body = re.search(r"async function ntToggle\(\)\{(.*?)\n\}\n", L.PAGE, re.S).group(1)
        self.assertIn("ntApply(Object.assign({},prev,{reserve:Object.assign({},rv,{manual:next,active:act", body)
        self.assertLess(body.index("confirm(tr('ntResConfirm'))"), body.index("ntApply("))  # сначала вопрос, потом показ
        self.assertIn("ntActAt=0;ntApply(prev)", body)  # неудачное сохранение откатывает показ без тоста о смене режима

    # --- баннер паузы резерва ---
    def test_banner_before_first_refusal_explains_without_a_timer(self):
        h = self.b["none"]
        self.assertIn("ccpResGrace", h)
        self.assertNotIn("ccp-timer", h)
        self.assertIn("ccpResSub", h)

    def test_banner_counts_down_from_the_first_refusal(self):
        h = self.b["mid"]
        self.assertIn("ccpResGraceNow", h)
        self.assertIn('data-until="%d"' % self.o_until(), h)
        self.assertIn('data-grace="1"', h)
        self.assertIn("ccpResGraceL", h)

    def o_until(self):
        return self.b["untilMid"]

    def test_banner_after_grace_says_tools_are_blocked_and_drops_the_timer(self):
        h = self.b["late"]
        self.assertIn("ccpResLocked", h)
        self.assertNotIn("ccp-timer", h)

    def test_banner_uses_page_constant_when_server_sends_no_grace(self):
        h = self.b["noGraceField"]
        self.assertIn('data-until="%d"' % self.b["untilMid"], h)  # 30 с прошло из 120: осталось 90 — по константе страницы

    def test_limits_pause_banner_has_no_grace_texts_or_marker(self):
        h = self.b["limits"]
        self.assertNotIn("ccpResGrace", h)
        self.assertNotIn("data-grace", h)

    def test_page_grace_equals_hook_and_pause_ctl(self):
        import pause_ctl
        m = re.search(r"const CCP_GRACE=(\d+);", L.PAGE)
        self.assertTrue(m)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks", "pause_tool_gate.py"), encoding="utf-8") as f:
            hook = f.read()
        self.assertEqual(int(m.group(1)), int(re.search(r"^GRACE = (\d+)", hook, re.M).group(1)))
        self.assertEqual(int(m.group(1)), pause_ctl.RESERVE_GRACE)

    def test_new_texts_exist_in_both_languages(self):
        for lang in ("ru", "en"):
            blk = i18n_block(lang)
            for k in ("ccpResGrace", "ccpResGraceNow", "ccpResGraceL", "ccpResLocked", "ntResOnToast", "ntResOffToast"):
                m = re.search(r"^\s*%s:(.+),?$" % k, blk, re.M)
                self.assertTrue(m, "%s нет в %s" % (k, lang))
                self.assertGreater(len(m.group(1)), 12, k)
                self.assertNotRegex(m.group(1), r"(?i)\b(прод|дев|хаб|prod|dev|hub)\b", k)

    def test_grace_banner_poll_is_faster_until_first_refusal(self):
        tick = re.search(r"function ccpTick\(\)\{(.*?)\n\}\n", L.PAGE, re.S).group(1)
        self.assertIn("pz.kind==='reserve'&&!pz.notice_ts&&Date.now()-ccpLoadedAt>4000", tick)
        self.assertIn("if(t.dataset.grace){if(Date.now()>=until)ccpRender();return;}", tick)  # конец отсчёта: надпись меняется, опроса нет


class NotionRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import http.server
        import threading
        cls.dir = tempfile.mkdtemp(prefix="ccntr_", dir=TMP)
        cls.creds = os.path.join(cls.dir, "c.json")
        with open(cls.creds, "w") as f:
            json.dump({"mcpOAuth": {"notion|h": {"serverName": "notion", "accessToken": "SECRET-N", "refreshToken": "SECRET-R"}}}, f)
        cls.keep = (L.cc_notion.CREDS, L.cc_notion.CONFIG)
        # резерв при сохранении сразу «тикает»: настоящее сообщение в Telegram и настоящий аварийный режим тесту ни к чему
        cls.keep2 = (L.cc_notion.NOTIFY, L.cc_notion.EMERGENCY, L.cc_notion.LEVEL, L.cc_notion.BASE)
        cls.sent = []
        L.cc_notion.NOTIFY = cls.sent.append
        L.cc_notion.EMERGENCY = None
        L.cc_notion.LEVEL = lambda: {"ok": True, "level": "none", "pause": {}}
        L.cc_notion.BASE = cls.dir
        L.cc_notion.CREDS = lambda: cls.creds
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), L.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        L.cc_notion.CREDS, L.cc_notion.CONFIG = cls.keep
        L.cc_notion.NOTIFY, L.cc_notion.EMERGENCY, L.cc_notion.LEVEL, L.cc_notion.BASE = cls.keep2

    def setUp(self):
        c = L.cfg()
        c.pop("notion_agent", None)
        c["hook_token"] = "t-secret"  # установщик всегда его создаёт; без него пустой токен «совпал» бы с пустым
        L.jsave(L.CONFIG, c)

    def post(self, body, auth=True):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(self.url + "/api/notion/save", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Auth-User": "t"} if auth else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_every_save_runs_the_reserve_tick_right_away(self):
        """Тумблер, имя, ссылка и галочки — любое сохранение сразу запускает такт резерва (а не ждёт опроса раз в 30 с)."""
        ticks = []
        keep = L.cc_notion.tick
        L.cc_notion.tick = lambda: ticks.append(1)
        try:
            for body in ({"enabled": False}, {"name": "x"}, {"reserve": {"manual": False}}, {"clear_url": True}):
                before = len(ticks)
                code, _ = self.post(body)
                self.assertEqual(code, 200, body)
                self.assertEqual(len(ticks), before + 1, body)
            before = len(ticks)
            code, _ = self.post({"name": "y" * 500})  # непринятое поле — сохранения нет, такт не нужен
            self.assertEqual(code, 400)
            self.assertEqual(len(ticks), before)
        finally:
            L.cc_notion.tick = keep

    def test_save_returns_public_without_secrets_and_without_enabled(self):
        code, out = self.post({"name": "Helper", "url": "agent://s/a"})
        self.assertEqual(code, 200)
        self.assertNotIn("enabled", out["notion"])
        self.assertNotIn("enabled", L.cfg()["notion_agent"])
        self.assertNotIn("SECRET", json.dumps(out))

    def test_url_is_saved_but_never_returned(self):
        code, out = self.post({"name": "Helper", "url": "agent://s/a"})
        self.assertEqual(code, 200)
        self.assertEqual(L.cfg()["notion_agent"], {"name": "Helper", "url": "agent://s/a"})
        self.assertEqual(out["notion"]["agent"], {"name": "Helper", "set": True})
        self.assertNotIn("agent://", json.dumps(out))
        code, out = self.post({"clear_url": True})
        self.assertEqual(code, 200)
        self.assertEqual(out["notion"]["agent"]["set"], False)

    def test_bad_field_is_400_with_message_and_config_untouched(self):
        self.post({"name": "Helper", "url": "agent://s/a"})
        code, out = self.post({"url": "http://evil", "lang": "en"})
        self.assertEqual(code, 400)
        self.assertEqual(out["field"], "url")
        self.assertIn("“url”", out["message"])
        self.assertEqual(L.cfg()["notion_agent"]["url"], "agent://s/a")
        code, out = self.post({"reserve": {"manual": "yes"}})
        self.assertEqual((code, out["field"]), (400, "reserve"))

    def test_needs_auth(self):
        self.assertEqual(self.post({"enabled": False}, auth=False)[0], 403)
        self.assertNotIn("notion_agent", L.cfg())

    def get(self, auth=True):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(self.url + "/api/notion", headers={"X-Auth-User": "t"} if auth else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_reserve_flags_saved_and_returned(self):
        self.post({"name": "Helper", "url": "agent://s/a"})
        code, out = self.post({"reserve": {"manual": True, "auto": True, "auto_emergency": False}})
        self.assertEqual(code, 200)
        self.assertEqual(L.cfg()["notion_agent"]["reserve"], {"manual": True, "auto": True, "auto_emergency": False})
        rv = out["notion"]["reserve"]
        self.assertTrue(rv["manual"] and rv["auto"])
        self.assertFalse(rv["auto_emergency"])
        self.assertNotIn("agent://", json.dumps(out))

    def test_reserve_switch_roundtrip_manual_on_then_off(self):
        # переключатель резерва в шапке: включил — резерв сразу активен и Claude на паузе; выключил — сразу снят, авто-галочка цела
        self.post({"name": "Helper", "url": "agent://s/a"})
        self.post({"reserve": {"auto": True, "auto_emergency": False}})
        code, out = self.post({"reserve": {"manual": True}})
        self.assertEqual(code, 200)
        self.assertTrue(out["notion"]["reserve"]["active"])
        self.assertTrue(out["notion"]["reserve"]["manual"])
        code, out = self.post({"reserve": {"manual": False}})
        self.assertEqual(code, 200)
        self.assertEqual(L.cfg()["notion_agent"]["reserve"], {"manual": False, "auto": True, "auto_emergency": False})
        self.assertFalse(out["notion"]["reserve"]["active"])        # Claude работает
        self.assertTrue(out["notion"]["reserve"]["auto"])

    def test_old_enabled_key_in_config_is_dropped_on_next_save(self):
        c = L.cfg()
        c["notion_agent"] = {"name": "Helper", "url": "agent://s/a", "enabled": False}
        L.jsave(L.CONFIG, c)
        code, out = self.post({"name": "Helper"})
        self.assertEqual(code, 200)
        self.assertNotIn("enabled", L.cfg()["notion_agent"])

    def test_manual_reserve_is_active_in_the_same_answer(self):
        # быстрый случай (без аварийного режима): ответ уже с новым состоянием, страница не ждёт опроса
        self.post({"name": "Helper", "url": "agent://s/a"})
        code, out = self.post({"reserve": {"manual": True}})
        self.assertEqual(code, 200)
        self.assertTrue(out["notion"]["reserve"]["active"])
        self.assertEqual(out["notion"]["role"], "reserve")
        code, out = self.post({"reserve": {"manual": False}})
        self.assertFalse(out["notion"]["reserve"]["active"])

    def test_bad_reserve_is_400_and_config_untouched(self):
        self.post({"name": "Helper", "url": "agent://s/a"})
        for bad in ({"manual": "yes"}, {"zzz": True}, "on", [True]):
            code, out = self.post({"reserve": bad})
            self.assertEqual((code, out["field"]), (400, "reserve"), bad)
        self.assertNotIn("reserve", L.cfg()["notion_agent"])

    def test_light_get_returns_public_state_without_secrets(self):
        self.post({"name": "Helper", "url": "agent://s/a"})
        code, out = self.get()
        self.assertEqual(code, 200)
        self.assertIn("reserve", out)
        self.assertEqual(out["agent"], {"name": "Helper", "set": True})
        self.assertNotIn("agent://", json.dumps(out))
        self.assertNotIn("SECRET", json.dumps(out))

    def test_light_get_needs_auth(self):
        self.assertEqual(self.get(auth=False)[0], 403)


if __name__ == "__main__":
    unittest.main()