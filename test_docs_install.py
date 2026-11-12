# docs/INSTALL.md не должен расходиться с кодом: шаги и переменные установщика, подписи кнопок панели, строки проверок мастера, файлы, на которые есть ссылки.
# python3 -m unittest test_docs_install -v
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def read(*parts):
    with open(os.path.join(HERE, *parts), encoding="utf-8") as f:
        return f.read()


DOC = read("docs", "INSTALL.md")
INSTALL = read("install.sh")
VOICE = read("voice", "install.sh")
PANEL = "\n".join(read(n) for n in ("cc_workers.py", "cc_remote_setup.py", "cc_remote_ui.py", "cc_limits.py", "cc_overview.py", "cc_labels.py"))


def slug(title):
    """Якорь GitHub: строчные, пробелы → «-», знаки препинания убраны (буквы кириллицы остаются)."""
    t = title.strip().lower()
    t = re.sub(r"[^\w\- ]", "", t, flags=re.UNICODE)
    return t.replace(" ", "-")


class Structure(unittest.TestCase):
    def test_sections_and_contents_links(self):
        heads = re.findall(r"^## (.+)$", DOC, flags=re.M)
        self.assertEqual([h.split(".")[0] for h in heads if re.match(r"\d+\.", h)], [str(i) for i in range(1, 9)])
        self.assertTrue(any(h.startswith("Приложение А") for h in heads))
        anchors = {slug(h) for h in heads}
        for a in re.findall(r"\]\(#([^)]+)\)", DOC):
            self.assertIn(a, anchors, "в оглавлении ссылка на несуществующий раздел: #" + a)

    def test_every_section_is_step_by_step_with_a_check(self):
        parts = [p for p in re.split(r"^## ", DOC, flags=re.M)[1:] if (p[0].isdigit() and not p.startswith("8.")) or p.startswith("Приложение")]  # раздел 8 — справочный, без шагов
        for p in parts:
            title = p.splitlines()[0]
            self.assertRegex(p, r"Шаг \d+ из \d+", "в разделе «%s» нет шагов «Шаг N из M»" % title)
            if title[0].isdigit() and not title.startswith("8."):
                self.assertIn("Проверка", p, "в разделе «%s» нет «Проверка»" % title)
            if title[0].isdigit() and not title.startswith("8."):
                self.assertIn("Что вижу", p, "в разделе «%s» нет таблицы «Если не вышло»" % title)

    def test_step_counts_in_each_section_are_consistent(self):
        # «Шаг k из M» внутри раздела: M одно и то же, k идёт 1..M без пропусков
        parts = re.split(r"^## ", DOC, flags=re.M)[1:]
        for p in parts:
            steps = re.findall(r"\*\*Шаг (\d+) из (\d+)", p)
            if not steps:
                continue
            totals = {m for _, m in steps}
            self.assertEqual(len(totals), 1, "разные M в разделе %s: %s" % (p.splitlines()[0], totals))
            self.assertEqual([int(k) for k, _ in steps], list(range(1, int(totals.pop()) + 1)), p.splitlines()[0])


class AgainstTheInstaller(unittest.TestCase):
    def test_all_thirteen_steps_are_described_by_their_real_titles(self):
        m = re.search(r"STEP_TITLES=\((.*?)\n\)", INSTALL, flags=re.S)
        titles = re.findall(r'"([^"]+)"', m.group(1))
        self.assertEqual(len(titles), 13)
        for n, t in enumerate(titles, 1):
            self.assertRegex(DOC, r"\| %d \| %s \|" % (n, re.escape(t)), "шаг %d «%s» не описан в таблице раздела 2" % (n, t))

    def test_environment_variables_match_both_ways(self):
        in_install = set(re.findall(r"CC_FLEET_[A-Z_]+", INSTALL)) - {"CC_FLEET_"}
        in_doc = set(re.findall(r"CC_FLEET_[A-Z_]+", DOC)) - {"CC_FLEET_"}
        self.assertEqual(sorted(in_install - in_doc), [], "переменные установщика без описания в инструкции")
        self.assertEqual(sorted(in_doc - in_install), [], "в инструкции переменные, которых нет в установщике")

    def test_defaults_in_the_table_are_the_real_ones(self):
        for var, default in (("PORT", "8877"), ("ACCOUNTS", "2"), ("THRESHOLD", "85"), ("SCREEN", "claude"), ("CODEX_USER", "codex"), ("BASE", "/opt/cc-limits"),
                             ("PROFILES", "/root/.claude-profiles"), ("SERVICE_NAME", "cc-limits")):
            self.assertIn('CC_FLEET_%s:-%s}' % (var, default), INSTALL.replace('"', ""), var)
            row = re.search(r"(?m)^\|[^\n]*`CC_FLEET_%s`[^\n]*" % var, DOC)
            self.assertIsNotNone(row, var)
            self.assertIn(default, row.group(0), "в таблице у CC_FLEET_%s не тот умолчательный: %s" % (var, row.group(0)))

    def test_sections_the_installer_points_to_exist(self):
        topics = {"2": "Установка одной командой", "3": "Аккаунты Claude", "4": "Telegram", "5": "Codex", "6": "Второй сервер"}
        for n in sorted(set(re.findall(r"docs/INSTALL\.md, раздел (\d)", INSTALL))):
            self.assertIn(n, topics, "установщик ссылается на раздел %s" % n)
            self.assertRegex(DOC, r"(?m)^## %s\. .*%s" % (n, topics[n]), "раздел %s не о «%s»" % (n, topics[n]))

    def test_installer_questions_are_all_in_the_doc(self):
        for q in ("screen-сессии", "аккаунтов Claude", "Порог авто-переключения", "обращаться", "часовой пояс", "Рабочая папка", "nginx", "Telegram", "Codex", "Голос", "Хук очереди", "Стоп-кран"):
            self.assertIn(q.lower(), DOC.lower(), q)

    def test_paths_the_doc_mentions_exist_in_the_repository(self):
        for rel in set(re.findall(r"`((?:voice|docs|scripts)/[A-Za-z0-9_./-]+)`", DOC)):
            self.assertTrue(os.path.exists(os.path.join(HERE, rel)), "в инструкции файл, которого нет в репозитории: " + rel)
        for rel in ("install.sh", "update_manifest.json", "cc_limits.py"):
            self.assertTrue(os.path.exists(os.path.join(HERE, rel)))


class AgainstThePanel(unittest.TestCase):
    def test_button_and_field_labels_exist_in_the_code(self):
        labels = ["Добавить аккаунт", "Получить ссылку для входа", "Названия серверов", "Переключение и лимиты", "Авто-переключение", "Пауза на недельном потолке",
                  "Установить Codex", "Мост Telegram", "Свои настройки Codex", "Аккаунты и лимиты ChatGPT",
                  "Второй сервер", "Установить недостающее", "Скопировать команду", "Войти заново", "Включить авто", "Изменить порог", "Передать работу в"]
        for label in labels:
            self.assertIn(label, DOC, "подпись «%s» не упомянута в инструкции" % label)
            self.assertIn(label, PANEL, "в инструкции подпись «%s», а в коде панели её нет" % label)

    def test_second_server_checks_match_the_wizard(self):
        wiz = read("cc_remote_setup.py")
        for label in ("Вход по ssh", "Вход под root", "Установлен %s", "Claude Code (/usr/bin/claude)", "Вход Claude на втором сервере", "Telegram-плагин Claude"):
            self.assertIn(label, wiz)
        for label in ("Вход по ssh", "Вход под root", "Claude Code (`/usr/bin/claude`)", "Вход Claude на втором сервере", "Telegram-плагин Claude"):
            self.assertIn(label, DOC)
        self.assertIn("Шаг 1 из 3", wiz)
        self.assertIn("ccfleet", wiz)  # умолчательное имя tmux
        self.assertIn("`ccfleet`", DOC)
        self.assertIn("remote_key", DOC)
        self.assertIn('"remote_key"', wiz)


class AgainstTheVoice(unittest.TestCase):
    def test_voice_steps_and_commands_match(self):
        titles = re.search(r"TITLES=\((.*?)\)\n", VOICE, flags=re.S).group(1)
        self.assertEqual(len(re.findall(r'"([^"]+)"', titles)), 8)
        self.assertIn("шаг N из 8", DOC)
        for cmd in ("ccfleet-say", "ccfleet-say-long", "ccfleet-transcribe", "--check", "--remove", "8879/health"):
            self.assertIn(cmd, DOC)
        for voice in ("kseniya", "aidar", "baya", "xenia", "eugene"):
            self.assertIn(voice, DOC)
        self.assertIn("5 ГБ", DOC)
        self.assertIn("~5 ГБ", INSTALL)  # вопрос установщика называет те же 5 ГБ


class Hygiene(unittest.TestCase):
    def test_installer_and_guide_know_only_the_current_agents(self):
        for text, name in ((DOC, "docs/INSTALL.md"), (INSTALL, "install.sh"), (VOICE, "voice/install.sh")):
            self.assertNotIn("no" + "tion", text.lower(), name)   # третьего агента в пакете больше нет
        self.assertIn('if owner: cfg["owner"] = owner', INSTALL)   # имя владельца — ключ owner в config.json

    def test_no_private_data_or_secrets_in_the_doc(self):
        for bad in ("Ден" + "ис", "desk" + "pharm", "farm" + "garant", "dar" + "qai", "иркутск"):
            self.assertNotIn(bad, DOC.lower() if bad.islower() else DOC, bad)
        self.assertNotRegex(DOC, r"ntn_[A-Za-z0-9]{20,}")
        self.assertNotRegex(DOC, r"\b\d{9,10}:AA[A-Za-z0-9_-]{30,}")  # токен бота

    def test_readme_points_to_the_guide(self):
        self.assertIn("docs/INSTALL.md", read("README.md"))
        self.assertIn("docs/INSTALL.md", read("README.en.md"))


if __name__ == "__main__":
    unittest.main()
