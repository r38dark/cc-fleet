"""Датчик «занят» в remote_ctl.py: эхо задания с фразой «esc to interrupt» не должно держать Claude занятым."""
import re
import unittest

SRC = open(__file__.replace("test_remote_ctl_busy.py", "remote_ctl.py"), encoding="utf-8").read()
# берём только определения датчика (без main(), который завершает процесс)
PART = SRC[SRC.index("SPIN = re.compile"):SRC.index("def dismiss_survey")]
NS = {"re": re}
exec(PART, NS)
busy = NS["busy"]

BOX = "\n".join(["─" * 60, "❯ ", "─" * 60, "  claude-sonnet-5-5 │ root │ xhigh", "  current ○○○○○○○○○○ 1%",
                 "  weekly  ○○○○○○○○○○ 9%", "  ⏵⏵ bypass permissions on (shift+tab to cycle)"])
ECHO = "\n".join("  Строка %d. занятость определялась по «esc to interrupt», спиннер «✢ Determining…»" % i for i in range(1, 40))


class BusyTest(unittest.TestCase):
    def test_idle_after_answer(self):
        self.assertFalse(busy("● ок\n\n✻ Cooked for 1s\n\n" + BOX))

    def test_spinner_line_is_busy(self):
        self.assertTrue(busy("● читаю файл\n\n✻ Ionizing… (12s · ↓ 1.3k tokens)\n\n" + BOX))

    def test_old_style_marker_is_busy(self):
        self.assertTrue(busy("текст\n✻ Thinking… (12s · esc to interrupt)\n" + BOX))
        self.assertTrue(busy("текст\n" + BOX + "\n  esc to interrupt"))

    def test_phrase_in_echoed_task_is_not_busy(self):
        # эхо длинного задания с фразой осталось выше ответа: Claude уже свободен
        self.assertFalse(busy(ECHO + "\n\n● ок\n\n✻ Cooked for 1s\n\n" + BOX))

    def test_phrase_in_echoed_task_while_working_is_busy(self):
        self.assertTrue(busy(ECHO + "\n\n✻ Ionizing… (3s)\n\n" + BOX))

    def test_spinner_text_in_echo_is_not_busy(self):
        self.assertFalse(busy("* Done… в старом списке\n" + ECHO + "\n\n● ок\n\n" + BOX))

    def test_empty(self):
        self.assertFalse(busy(""))


class SendinQueueTest(unittest.TestCase):
    def test_queue_flag_lets_plain_text_in_while_busy_but_not_commands(self):
        part = SRC[SRC.index('if c == "sendin"'):SRC.index('dismiss_survey()', SRC.index('if c == "sendin"'))]
        self.assertIn('a[1] == "queue"', part)
        self.assertIn('not text.lstrip().startswith("/")', part)   # слэш-команды в ходе ответа по-прежнему не принимаются
        self.assertIn('busy(screen(40)) and not queue_ok', part)


if __name__ == "__main__":
    unittest.main()
