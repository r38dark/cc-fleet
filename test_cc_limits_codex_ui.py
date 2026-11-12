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

    def test_gear_popup_accounts_section_is_last(self):
        # ⚙-окно: «Мост Telegram и все настройки» сверху, «Аккаунты и лимиты ChatGPT» — в самом низу
        self.assertLess(L.PAGE.index('id="cxBrW"'), L.PAGE.index('id="cxAccW"'))

    def test_bridge_card_footer_save_left_delete_right(self):
        page = L.PAGE
        foot = page[page.index('class="cxbrow cxbfoot"'):]
        foot = foot[:foot.index("</div>")]
        self.assertLess(foot.index('id="cxbSave"'), foot.index('id="cxbDel"'))
        self.assertIn('onclick="cxbDelAcct()"', foot)
        self.assertIn("{margin-left:auto}", page[page.index(".cxbfoot .btn-del"):][:60])
        # удаляется аккаунт из поля «Аккаунт ChatGPT»; «первый подходящий» — кнопка неактивна; подтверждение — то же окно, что у «Удалить» в карточке
        m = re.search(r"function cxbDelAcct\(\)\{(.*?)\}\n", page)
        self.assertTrue(m)
        self.assertIn("cxDel(sel.value)", m.group(1))
        self.assertIn("btn.disabled=!has", page)
        self.assertIn('onchange="cxbDelSync()"', page)

    def test_wipe_button_is_last_in_gear_popup(self):
        # «Удалить Codex целиком» — в самом низу окна ⚙, после секции аккаунтов; подтверждение словом, как у удаления аккаунта
        page = L.PAGE
        self.assertLess(page.index('id="cxAccW"'), page.index('id="cxWipeW"'))
        self.assertNotIn('id="ntPop"', page)  # прежнего блока резерва больше нет
        m = re.search(r"function cxWipe\(\)\{(.*?)\n\}\n", page, re.S)
        self.assertTrue(m)
        self.assertIn("acctPost('chatgpt/wipe',{confirm:inp.value})", m.group(1))
        self.assertIn("tr('delWord')", m.group(1))
        self.assertIn("ciWizSet(true)", m.group(1))  # после удаления мастер начат: «Codex +» возвращается
        for lang in ("ru", "en"):
            keys = set(re.findall(r"^\s{2}(cx\w*):", i18n_block(lang), re.M))
            self.assertEqual(sorted({"cxWipe", "cxWipeTip", "cxWipeTitle", "cxWipeWarn"} - keys), [], lang)

    def test_header_shows_only_codex_plus_when_no_account_left(self):
        # шаг 2 мастера (аккаунтов нет): значок, профиль и ⚙ скрыты; последний удалённый аккаунт возвращает «Codex +»
        page = L.PAGE
        m = re.search(r"function cxHdr\(\)\{(.*?)\n const b=cxbData", page, re.S)
        self.assertTrue(m)
        self.assertIn("ciStage()===2", m.group(1))
        self.assertIn("grp.hidden=hide", m.group(1))
        m = re.search(r"function cxAfterDel\(\)\{(.*?)\n\}\n", page, re.S)
        self.assertTrue(m)
        self.assertIn("ciWizSet(true)", m.group(1))
        self.assertIn("accounts", m.group(1))
        self.assertIn("cxAfterDel();", page[page.index("function cxDel(slot)"):])
        self.assertIn("await cxSettle()", page)

    def test_install_wizard_is_three_steps(self):
        page = L.PAGE
        for needle in ("function ciStage()", "function ciBody1(", "function ciBody2(", "function ciBody3(",
                       "function ciFinish(", 'onclick="ciFinish(true)"', "function ciLogin(", "async function ciBot("):
            self.assertIn(needle, page, needle)
        # шаг 3 необязательный: кнопка пропуска есть, бот без токена и chat_id не отправляется
        self.assertIn("cxiSkip", page)
        # после установки мастер идёт дальше сам, а не закрывается: шаг 1 → 2 (вход) → 3 (бот) считает ciStage по данным сервера
        stage = page[page.index("function ciStage()"):][:420]
        self.assertIn("return 1", stage)
        self.assertIn("return 2", stage)
        self.assertIn("return b&&b.token_set?0:3", stage)

    def test_install_wizard_same_width_as_gear_popup(self):
        w = re.search(r"\.cxpop\{[^}]*?(width:min\([^;}]*\))", L.PAGE).group(1)
        self.assertIn(".cxpop.cxinstpop{" + w + "}", L.PAGE)

    def test_wizard_texts_both_languages(self):
        # ключи шагов собираются в коде по таблице, поэтому парность проверяем явно
        need = ("cxiS1", "cxiS1n", "cxiS1ok", "cxiS2", "cxiS2ok", "cxiS2Hint", "cxiS3", "cxiS3Hint", "cxiLogin",
                "cxiBot", "cxiSkip", "cxiSkipped", "cxiAllDone", "cxiBotNoTok", "cxiBotNoChat",
                "cxbDelAcct", "cxbDelTip", "cxbDelPick")
        for lang in ("ru", "en"):
            keys = set(re.findall(r"^\s{2}(cx\w*):", i18n_block(lang), re.M))
            self.assertEqual(sorted(set(need) - keys), [], lang)
        self.assertIn("Пропустить этот шаг и завершить", i18n_block("ru"))

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

    def test_console_follows_the_working_agent(self):
        # консоль идёт за исполнителем: сменился remote_mode.worker — вкладка переключается сама, ручной выбор не трогаем
        page = L.PAGE
        self.assertRegex(page, r"function consFollow\(d\)\{")
        self.assertIn("d.remote_mode.worker", page)
        self.assertIn("{prod:'ctProd',codex:'ctCodex'}[w]||'ctClaude'", page)
        self.assertRegex(page, r"lastSnap=d;(noProdSync\(\);)?consFollow\(d\);")
        # запоминаем, за кем уже последовали: и в памяти страницы (localStorage может быть закрыт), и в localStorage
        self.assertIn("let consFollowed='',consFollowWait=0;", page)
        self.assertIn("localStorage.setItem('cc_conworker',w)", page)
        # пока нужной вкладки нет (PROD/Codex недоступны) — не запоминаем, ждём до 30 с и повторяем
        self.assertIn("if(!b||(w==='prod'&&!prodAvail())||(w==='codex'&&!cxAvail())||splitPending()){", page)
        self.assertIn("setTimeout(()=>consFollow(lastSnap),700)", page)
        # запоминаем ДО клика: клик зовёт consPick -> consTabs, а запоминание после клика зациклило бы переключение
        self.assertLess(page.index("consFollowed=w;try{localStorage.setItem('cc_conworker',w)"), page.index("b.click();  // обычный клик"))
        # смена вкладки не зависит от скрытости кнопки: на только что открытой странице кнопка PROD ещё скрыта
        self.assertNotIn("||b.hidden||", page[page.index("function consFollow"):page.index("function consFollow") + 700])

    def test_console_tabs_inactive_is_outline_only_active_is_filled(self):
        # просьба владельца: неактивная вкладка — только окантовка без фона, активная окрашена целиком
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

    def test_skins_removed_panel_is_always_classic(self):
        # скины убраны: нет выбора «Оформление», правил html[data-skin=…] и чтения cc_skin
        css = L.PAGE
        self.assertNotIn('id="skinGrid"', css)
        self.assertNotIn('id="skinTitle"', css)
        self.assertNotRegex(css, r'html\[data-skin=')
        self.assertIn("localStorage.removeItem('cc_skin')", css)
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
        self.assertEqual(re.findall(r"^ (\w+):\{", meta, re.M), ["orchestrator", "codex", "codex_solo_full"])
        for lang in ("ru", "en"):
            blk = i18n_block(lang)
            self.assertEqual(len(re.search(r"cxpF_orchestrator:\[(.*?)\],\n", blk).group(1).split("','")), 4)
            self.assertEqual(len(re.search(r"cxpF_codex:\[(.*?)\],\n", blk).group(1).split("','")), 3)
            self.assertEqual(len(re.search(r"cxpF_codex_solo_full:\[(.*?)\],\n", blk).group(1).split("','")), 4)
            self.assertEqual(len(re.search(r"cxpFlow_codex_solo_full:\[(.*?)\],\n", blk).group(1).split("','")), 3)
            self.assertEqual(len(re.search(r"cxpRoute_codex_solo_full:\[(.*?)\],\n", blk).group(1).split("','")), 2)
            self.assertEqual(len(re.search(r"cxpFlow_orchestrator:\[(.*?)\],\n", blk).group(1).split("','")), 5)
            self.assertEqual(len(re.search(r"cxpRoute_orchestrator:\[(.*?)\],\n", blk).group(1).split("','")), 2)
        ru = i18n_block("ru")
        self.assertIn("cxpN_codex:'Codex'", ru)
        self.assertNotIn("Второй ИИ", ru)

    def test_console_starts_itself_like_claude(self):
        # вкладка Codex сама поднимает консоль: жать «Запустить» не нужно (как и у консоли Claude)
        poll = re.search(r"async function ccConsole\(P\)\{.*?\n\}\n", L.PAGE, re.S).group(0)
        self.assertIn("cxConsAct('start',true,P)", poll)
        self.assertRegex(poll, r"d\.running\)cxAutoGo=false")  # уже работала — дальше остановка осознанная
        # кнопки остановки консоли нет: ручной остановки нет, флаг сбрасывается только при запуске
        self.assertNotIn("id=\"ctStop\"", L.PAGE)
        self.assertIn("cxAutoGo=false;cxConsAct('start',true,P)", poll)  # флаг гаснет ДО запроса: опрос раз в 2 с не запустит дважды
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

    def test_emergency_block_and_dot_keep_current_red_state(self):
        # аварийный блок закрашен красным целиком (настоящая рамка и сплошная полоса, не обрезаемая тень);
        # мигающая точка Codex в аварийном режиме — зелёная, не красная
        on = re.search(r"\.cxemg\.on\{([^}]*)\}", L.PAGE).group(1)
        self.assertIn("border-color:var(--bad)", on)
        self.assertIn("box-shadow:0 0 0 1px", on)
        self.assertRegex(L.PAGE, r"\.cxemg::before\{[^}]*background:linear-gradient")
        dot = re.search(r"\.cxdot\.emg\{([^}]*)\}", L.PAGE).group(1)
        self.assertIn("background:var(--bad)", dot)
        self.assertIn("animation:cxpulse", dot)
        self.assertIn("#cxBtn.emg{border-color:var(--bad)}", L.PAGE)

    def test_codex_console_tab_needs_an_account(self):
        # «Удалить Codex целиком» оставляет бинарь, но убирает входы: вкладка консоли Codex после этого не нужна
        self.assertIn("function cxAvail()", L.PAGE)
        self.assertIn("function baseCur(){return CONS==='prod'&&prodAvail()?'prod':CONS==='codex'&&cxAvail()&&!document.documentElement.classList.contains('ag-unlinked-codex')?'codex':'claude';}", L.PAGE)
        self.assertIn("function consCur(){const ks=splitEff();return ks?ks[splitActIdx(ks)]:baseCur();}", L.PAGE)
        self.assertIn("const av=cxAvail(),pv=prodAvail(),cur=consCur()", L.PAGE)

    def test_texts_in_both_languages(self):
        keys = {lang: set(re.findall(r"^\s{2}(cx\w*):", i18n_block(lang), re.M)) for lang in ("ru", "en")}
        self.assertEqual(keys["ru"] ^ keys["en"], set())
        # cxpN_/cxpS_/… — начало ключей профилей; cxoMode_/cxoAcc_/cxoRt_ — описания вариантов состава
        pfx = ("cxpN_", "cxpS_", "cxpWhen_", "cxpRoute_", "cxpF_", "cxpFlow_", "cxpCan_", "cxpNot_")
        dyn = set(pfx) | {"cxoMode_", "cxoAcc_", "cxoRt_"}
        used = set(re.findall(r"tr\('(cx\w+)'", L.PAGE)) - dyn
        for p in pfx:
            used |= {p + i for i in ("orchestrator", "codex", "codex_solo_full")}
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
const asked=[];
const window={fleetAsk:async(a,t,y)=>{asked.push(t);return true}};
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
 o.asked=asked.length;
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

    def test_change_asks_before_posting(self):
        self.assertEqual(self.o["asked"], 2)   # окно «Точно?» перед каждой отправкой, при том же значении не спрашиваем

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
            # одиночный маршрут применения не обходит общий выбор сценария (cc_manual_scenarios): оркестратор выбирают в общем окне
            code, out = self.post("bridge/profile/apply", {"id": "orchestrator", "confirm": "x", "lang": "en"})
            self.assertEqual((code, out["ok"]), (200, False))
            self.assertIn("общем окне", out["message"])
            ap.assert_not_called()
            # сборка своего профиля убрана — маршрута больше нет
            self.assertEqual(self.post("bridge/profile/save", {"name": "Ночной"})[0], 404)
            # свои профили прежних версий убраны: удалять нечего, маршрут отвечает отказом без обращения к мосту
            code, out = self.post("bridge/profile/delete", {"id": "c1"})
            self.assertEqual((code, out["ok"]), (200, False))
            self.assertIn("встроенные", out["message"])
            dl.assert_not_called()

    def test_delete_route_frees_bridge_slot_only_on_success(self):
        # удалённый аккаунт: мост, привязанный к нему, возвращается к «первый подходящий»; при отказе привязка не трогается
        with mock.patch.object(L.cc_codex, "delete_account", return_value=(True, "удалён")) as de, \
                mock.patch.object(L.cc_codex_bridge, "drop_slot") as dr:
            self.assertEqual(self.post("delete", {"slot": "gpt2", "confirm": "удалить"}), (200, {"ok": True, "message": "удалён"}))
            de.assert_called_once_with("/x/codex", "gpt2", "удалить", lang=None, before=L.cc_codex_bridge.prepare_disconnect)
            dr.assert_called_once_with("gpt2")
        with mock.patch.object(L.cc_codex, "delete_account", return_value=(False, "нет")), \
                mock.patch.object(L.cc_codex_bridge, "drop_slot") as dr:
            self.assertEqual(self.post("delete", {"slot": "gpt2", "confirm": "x"}), (200, {"ok": False, "message": "нет"}))
            dr.assert_not_called()

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
    """Блок сообщения пользователя в Codex (фон SGR 48;5;8 = 7f7f7f у pyte) рисуется тёмной читаемой полосой."""

    def _html(self, row_html):
        import pyte
        screen = pyte.Screen(20, 2)
        pyte.Stream(screen).feed("\x1b[39;48;5;8m  вопрос        \x1b[0m\r\n\x1b[41mкрасный\x1b[0m")
        return [row_html(screen.buffer[y], 20) for y in range(2)]

    def test_codex_mirror_shows_user_block_on_dark_readable_band(self):
        # сообщение человека выделено полосой, но не светло-серой: светлый текст на ней был нечитаем
        rows = self._html(L.cc_codex_console.ROW_HTML)
        self.assertIn("background:#303744", rows[0])
        self.assertNotIn("#7f7f7f", rows[0])
        self.assertIn("вопрос", rows[0])

    def test_codex_mirror_keeps_other_backgrounds(self):
        # красный фон ANSI (базовый 41) остаётся как есть
        rows = self._html(L.cc_codex_console.ROW_HTML)
        self.assertIn("background:#e05b5b", rows[1])

    def test_claude_console_colors_unchanged(self):
        rows = self._html(L._row_html)
        self.assertIn("background:#7f7f7f", rows[0])








BANNER_JS = """
const LANG='ru';
let T=1000000000000;Date.now=()=>T;
const tr=(k,...a)=>a.length?k+'('+a.join(',')+')':k;
const el={hidden:true,className:'',innerHTML:''};
const $=s=>s==='#ccPause'?el:null;
%s
const out=(kind)=>{ccpData={stale:false,level:'none',threshold:90,weekly_cap:99,accounts:{},active:'a',pause:{active:true,kind:kind,since:T/1000-5,resume_at:T/1000+600,reason:'r',override:false}};ccpRender();return el.innerHTML;};
console.log(JSON.stringify({limits:out('session'),old:out('reserve')}));
"""


@unittest.skipUnless(__import__("shutil").which("node"), "нет node")
class PauseBanner(unittest.TestCase):
    """Баннер паузы по лимитам: обычный вид с будильником; запись прежнего служебного вида паузы показывается так же."""

    @classmethod
    def setUpClass(cls):
        page = L.PAGE
        i, j = page.index("let ccpData=null"), page.index("function ccpTick(){")
        path = os.path.join(TMP, "banner.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(BANNER_JS % page[i:j])
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.b = json.loads(r.stdout)

    def test_limits_pause_has_title_and_alarm_timer(self):
        h = self.b["limits"]
        self.assertIn("ccpPauseTitle", h)
        self.assertIn("ccp-timer", h)
        self.assertNotIn("data-grace", h)

    def test_old_service_pause_record_is_an_ordinary_pause(self):
        self.assertIn("ccpPauseTitle", self.b["old"])
        self.assertNotIn("data-grace", self.b["old"])

    def test_no_texts_of_the_removed_service_pause(self):
        self.assertNotIn("ccpRes", L.PAGE)
        self.assertNotIn("CCP_GRACE", L.PAGE)
        tick = re.search(r"function ccpTick\(\)\{(.*?)\n\}\n", L.PAGE, re.S).group(1)
        self.assertNotIn("dataset.grace", tick)


if __name__ == "__main__":
    unittest.main()