"""Клавиши консоли в окне ввода: кнопки ↑ ↓ ⏎ Esc и клавиатура (проверка исходников страницы, как соседние test_cc_fleet_*)."""
import re
import unittest
from pathlib import Path

HERE = Path(__file__).parent


def src(name):
    return (HERE / name).read_text(encoding="utf-8")


class ConsoleKeysTest(unittest.TestCase):
    def test_overview_buttons_and_click_handler(self):
        s = src("cc_overview.py")
        for key in ("up", "down", "enter", "escape"):
            self.assertIn('data-console-key="%s"' % key, s)
        # обработчик вешается на все кнопки и ставит нажатия в очередь, а не на одну Esc
        self.assertIn("form.querySelectorAll('[data-console-key]')", s)
        self.assertIn("keyQ=keyQ.then(", s)
        self.assertNotIn("form.querySelector('[data-console-key]').addEventListener", s)

    def test_overview_keyboard_only_after_click_on_console(self):
        s = src("cc_overview.py")
        self.assertIn("{ArrowUp:'up',ArrowDown:'down',Enter:'enter',Escape:'escape'}", s)
        self.assertIn("closest('#termBox,.tpextra,.fleet-console-viewport')", s)
        # в поле ввода, кнопках, ссылках и с модификаторами клавиши не перехватываются; у чата Notion AI клавиш нет
        self.assertIn("input,textarea,select,button,a,[contenteditable=", s)
        self.assertIn("e.ctrlKey||e.altKey||e.metaKey||e.shiftKey", s)
        self.assertIn("indexOf('notion')===0", s)

    def test_split_parts_have_same_keys(self):
        s = src("cc_limits.py")
        for key in ("up", "down", "enter", "escape"):
            self.assertRegex(s, r'class="tpkey" data-console-key="%s"' % key)
        # кнопка отправки ищется по классу: индекс ребёнка сдвигается при добавлении кнопок
        self.assertIn("send=form.querySelector('.tpsend')", s)
        self.assertNotIn("send=form.children[2]", s)
        self.assertIn("c.form.querySelectorAll('.tpkey').forEach(b=>{b.hidden=isNai(P.k);})", s)

    def test_notion_chat_locks_every_console_key(self):
        s = src("cc_notion_ai.py")
        self.assertIn("querySelectorAll('#fleetConsoleForm [data-console-key]')", s)
        self.assertIn("keys.forEach(function(k){k.disabled=true})", s)
        self.assertIn("keys.forEach(function(k){k.disabled=saved.key})", s)

    def test_server_accepts_the_four_keys(self):
        s = src("cc_fleet.py")
        m = re.search(r"keys = \{([^}]*)\}", s)
        self.assertIsNotNone(m)
        for key in ("escape", "enter", "up", "down"):
            self.assertIn("'%s'" % key, m.group(1))


if __name__ == "__main__":
    unittest.main()
