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
        for sel in ("#ctProd", '.nai-seg[data-ag="prod"]', ".fleet-live-account.prod", ".fleet-compact-account.prod", '.fleet-acc[data-engine="prod"]',
                    ".nai-h3.t-prod", '.rm-hand[data-target="prod"]', '.tpmi[data-k="prod"]'):
            self.assertIn("html.no-prod " + sel, rule, sel)
        self.assertIn("display:none!important", rule)  # тема меню консоли задаёт display:flex у .ctab — без !important атрибут hidden не работает

    def test_with_a_pair_nothing_is_hidden(self):
        self.assertIn("prodAvail()", self.page)  # решение — по тому же признаку, что и вкладка консоли: в снимке есть второй сервер
        self.assertIn("function prodAvail(){try{if(!lastSnap)return localStorage.getItem('cc_has_prod')==='1';return !!(lastSnap.remote&&Object.keys(lastSnap.remote).length)}", self.page)  # до первого снимка — по запомненному cc_has_prod (62830)


if __name__ == "__main__":
    unittest.main()
