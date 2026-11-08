# время сброса 5ч налезало на подпись «Неделя» — колонка 5ч была уже своего содержимого.
# Замер делался в браузере (30 ширин от 320 до 2200 px, худшие данные «100%» и «88.88 88:88»); здесь — страж от возврата фиксированной узкой ширины.
import re
import unittest

import cc_overview

SEL = 'html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="session"]'


class SessionColumn(unittest.TestCase):
    def test_column_is_never_narrower_than_its_content(self):
        css = cc_overview.CSS
        fixed = css.index(SEL + '{flex:0 0 var(--cses)}')            # старое правило: жёсткая ширина
        auto = css.index(SEL + '{flex:0 0 auto;min-width:var(--cses)}')  # новое: по содержимому, --cses только нижняя граница
        self.assertGreater(auto, fixed, 'новое правило должно идти после старого и перекрывать его')
        block = css[css.rfind('@media', 0, auto):auto]
        self.assertIn('min-width:641px', block, 'телефон (до 640 px) не трогаем')

    def test_range_does_not_wrap(self):
        self.assertIn(SEL + ' .fleet-compact-range{white-space:nowrap}', cc_overview.CSS)

    def test_floor_covers_widest_content_per_range(self):
        css = cc_overview.CSS
        tail = css[css.index('налезало на подпись'):]
        self.assertIn('--cses:128px', tail)    # 120 px текста + запас под «100%»
        self.assertIn('--cses:118px', tail)    # плотные плитки 1260–1579: 112 px + запас
        self.assertNotIn('--cses:86px', tail)

    def test_narrow_two_per_row_drops_week_date_instead_of_overflowing(self):
        css = cc_overview.CSS
        tail = css[css.index('налезало на подпись'):]
        self.assertIn('@media(min-width:1260px) and (max-width:1379px)', tail)
        self.assertIn('.fleet-compact-window[data-window="week"] .fleet-compact-range', tail)


class SendIcon(unittest.TestCase):
    def test_send_button_is_enter_key_icon_not_up_arrow(self):
        """кнопка отправки в консоль — значок клавиши Enter (↵), а не стрелка вверх."""
        self.assertNotIn("send.textContent='↑'", cc_overview.JS)
        i = cc_overview.JS.index("send.innerHTML='<svg")
        self.assertIn('<polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>', cc_overview.JS[i:i + 400])
        self.assertIn('#fleetSend svg{', cc_overview.CSS)


class ConsoleActionButtons(unittest.TestCase):
    """«Сжать контекст» и «Новая сессия» на вкладках Claude DEV и PROD, а не только у Codex (и не только в сложенной карточке)."""

    def setUp(self):
        import cc_limits
        self.page = cc_limits.PAGE

    def test_buttons_are_always_visible_on_claude_prod_and_codex_tabs(self):
        # на PROD кнопок не было, пока Claude на PROD не запущен — теперь видны всегда; кнопки остановки консоли нет
        self.assertIn("function ctActsSync(){const k=consCur(),show=k==='claude'||k==='prod'||k==='codex';", self.page)
        self.assertNotIn("ctActsClaude", self.page)
        self.assertNotIn('id="ctStop"', self.page)
        i = self.page.index("async function ccConsole(P){")
        self.assertIn("ctActsSync();", self.page[i:i + 260])      # пересчёт на каждом опросе, не только после ответа сервера

    def test_phone_tabs_share_the_whole_row(self):
        # телефон (62686): вкладки моделей растянуты на всю ширину ряда, а не уезжают вправо
        self.assertIn("html:root:root .fleet-console-toolbar #cTabs>.ctab{flex:1 1 auto;min-width:0;justify-content:center}", self.page)

    def test_each_tab_runs_its_own_command(self):
        self.assertIn("function consActCmd(cmd,anchor){const s=consCur();return s==='codex'?cxConsCmd(cmd,anchor):s==='prod'?prodSessionCmd(cmd,anchor):sessionCmd(cmd,anchor||", self.page)
        self.assertIn("text:cmd==='compact'?'/compact':'/clear'", self.page)       # PROD: команда уходит в консоль PROD
        self.assertIn("askProdCompact", self.page)                                 # подтверждение перед сжатием, как у DEV и Codex
        self.assertIn("addEventListener('click',()=>consActCmd('compact'))", self.page)

    def test_tab_refresh_does_not_reset_titles_to_codex(self):
        i = self.page.index("function consTabs(){")
        self.assertNotIn("'cxcNewTip'", self.page[i:i + 1200])   # consTabs зовут часто: раньше он каждый раз ставил «Новая сессия Codex» на вкладках Claude
        self.assertIn("ctActsSync();  // подсказки кнопок", self.page[i:i + 1200])

    def test_titles_follow_the_tab(self):
        i = self.page.index("function ctActsSync()")
        body = self.page[i:i + 700]
        self.assertIn("k==='codex'?'cxcCompactTip':'compactTitle'", body)    # у Codex свои подсказки, у Claude — свои; пересчёт при каждой смене вкладки
        self.assertIn("k==='codex'?'cxcNewTip':'newSessionTitle'", body)

class SingleClaudeRow(unittest.TestCase):
    """Второй сервер не подключён (Claude PROD скрыт) — строка Claude на всю ширину, как Codex и Notion AI (правка владельца)."""

    def test_lone_claude_row_spans_the_full_width(self):
        css = cc_overview.CSS
        rule = 'html.no-prod:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="claude"]{grid-column:1/-1}'
        self.assertIn(rule, css)
        # Codex и Notion AI на всю ширину были и раньше: правило для Claude не должно их менять
        self.assertIn('.fleet-acc:has(>.fleet-compact-account.codex),', css)
        self.assertIn('.fleet-acc:has(>.fleet-compact-account.notion){grid-column:1/-1}', css)
        self.assertNotIn('html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="claude"]{grid-column:1/-1}', css)  # без no-prod две строки Claude остаются рядом


if __name__ == '__main__':
    unittest.main()
