# Чистая установка: пока второй сервер не подключён, в интерфейсе нет ничего про «Claude B» (вкладки, плашки шапки, карточки, кнопок передачи).
# python3 -m unittest test_clean_install_ui -v
import unittest

import cc_limits as L


class NoSecondServer(unittest.TestCase):
    def setUp(self):
        self.page = L.PAGE

    def test_class_is_set_early_from_memory_and_updated_from_every_snapshot(self):
        head = self.page[:self.page.index("<meta charset")]
        self.assertIn("cc_has_prod", head)            # страница не мигает при загрузке: решение берётся из localStorage ещё в <head>
        self.assertIn("classList.add('no-prod')", head)
        self.assertIn("lastSnap=d;noProdSync();", self.page)
        self.assertIn("function noProdSync()", self.page)
        self.assertIn("classList.toggle('no-prod',!hp)", self.page)

    def test_everything_about_the_second_server_is_hidden_by_one_rule(self):
        rule = self.page[self.page.index("html.no-prod #ctProd"):]
        rule = rule[:rule.index("}")]
        for sel in ("#ctProd", '.wk-seg[data-ag="prod"]', ".fleet-live-account.prod", ".fleet-compact-account.prod", '.fleet-acc[data-engine="prod"]',
                    ".wk-h3.t-prod", '.rm-hand[data-target="prod"]', '.tpmi[data-k="prod"]'):
            self.assertIn("html.no-prod " + sel, rule, sel)
        self.assertIn("display:none!important", rule)  # тема меню консоли задаёт display:flex у .ctab — без !important атрибут hidden не работает

    def test_only_the_active_claude_location_is_selected(self):
        self.assertIn("localStorage.getItem('cc_has_prod')==='1'", self.page)
        self.assertIn("!Object.keys(lastSnap.accounts||{}).length||!!lastSnap.remote_mode?.active", self.page)
        self.assertIn("Object.keys(lastSnap.accounts||{}).length&&!prodAvail()", self.page)


if __name__ == "__main__":
    unittest.main()
