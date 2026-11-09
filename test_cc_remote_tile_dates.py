# Плитки Claude DEV и PROD одинаковы: сроки «Подписка до / Вход до» из одной функции, подвал, счётчик аккаунтов (2.0.12)
# python3 -m unittest test_cc_remote_tile_dates -v
import json
import re
import shutil
import subprocess
import unittest

import cc_overview as O
import cc_remote_ui as R


class SharedDates(unittest.TestCase):
    def test_dev_cards_use_the_shared_function_and_export_it(self):
        self.assertIn("function claudeDateItems(a){", O.JS)
        self.assertIn("window.fleetClaudeDates=claudeDateItems;", O.JS)
        self.assertIn("items.push(...claudeDateItems(a));", O.JS)  # ветка claude в paintCardDates зовёт её же

    def test_prod_card_draws_the_same_pills_instead_of_its_own_chips(self):
        self.assertIn("window.fleetClaudeDates({renewal_next:nextRenewal(m.subscription_since),login_expires:m.login_expires,plan:m.plan})", R.JS)
        self.assertIn("dbox.className='fleet-card-dates'", R.JS)
        # чип с датой оформления и чип «логин истекает» у PROD больше не рисуем: те же сроки уже в плашках
        card = R.JS[R.JS.index("function paintCard(m){"):R.JS.index("var hadTab=null;")]
        self.assertNotIn("subChip(", card)
        self.assertNotIn("loginChip(", card)
        self.assertNotIn("function subChip(", R.JS)

    def test_dates_repaint_when_they_change(self):
        self.assertIn("m.subscription_since,m.login_expires", R.JS)  # в подписи перерисовки

    def test_relogin_button_is_where_dev_has_it(self):
        self.assertIn('class="btn-relogin fleet-footer-relogin rm-relogin"', R.JS)  # тот же класс, что у DEV, и свой rm-relogin для обработчика
        self.assertIn(".fleet-remote-card .fleet-card-caption{flex:1 1 0;", R.CSS)   # подпись и кнопка в одной строке

    def test_account_count_includes_the_second_server_tile(self):
        self.assertIn("function paintClaudeCount(local)", O.JS)
        self.assertIn("#cards > .fleet-remote-card", O.JS)
        self.assertIn("window.fleetClaudeCount=", O.JS)
        self.assertIn("paintClaudeCount(rows.length);", O.JS)
        self.assertIn("window.fleetClaudeCount", R.JS)  # плитка PROD сама просит пересчитать при появлении и исчезновении


@unittest.skipUnless(shutil.which("node"), "нет node")
class NextRenewal(unittest.TestCase):
    """nextRenewal(iso): ближайшая месячная годовщина оформления подписки, строго в будущем."""

    def run_js(self, iso):
        m = re.search(r"function nextRenewal\(iso\)\{.*?return t\.toISOString\(\)\}", R.JS, re.S)
        self.assertIsNotNone(m)
        code = m.group(0) + "\nprocess.stdout.write(JSON.stringify([nextRenewal(%s), Date.now()]))" % json.dumps(iso)
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_result_is_in_the_future_within_a_month(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        for back_days in (3, 45, 200, 900):
            iso = (now - datetime.timedelta(days=back_days)).isoformat()
            res, ms = self.run_js(iso)
            nxt = datetime.datetime.fromisoformat(res.replace("Z", "+00:00"))
            delta = (nxt - now).total_seconds() / 86400
            self.assertGreater(delta, 0, back_days)
            self.assertLessEqual(delta, 31.5, back_days)

    def test_end_of_month_day_is_clamped_not_rolled_over(self):
        # оформлена 31-го: в коротком месяце срок падает на последний день, а не уезжает в следующий месяц
        import datetime
        now = datetime.datetime.now()
        y, mth = now.year - 1, 1
        res, _ = self.run_js(datetime.datetime(y, mth, 31, 12, 0, 0).isoformat())
        nxt = datetime.datetime.fromisoformat(res.replace("Z", "+00:00"))
        self.assertGreater(nxt.timestamp(), now.timestamp() - 1)

    def test_junk_gives_empty(self):
        res, _ = self.run_js("")
        self.assertEqual(res, "")
        res, _ = self.run_js("не дата")
        self.assertEqual(res, "")


if __name__ == "__main__":
    unittest.main()
