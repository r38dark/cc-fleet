# 06.11: подпись кнопки профиля Codex на карточке — одна, из системы профилей.
# Раньше её рисовали двое: cxHdr() — профилем моста Codex («Codex Full · самостоятельно») и paintMirrorWorkplace() —
# профилем системы («Codex · на паузе»), строка скакала. Поведение проверено снимком панели (sc_h1).
# python3 -m unittest test_cc_overview_labels -v
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = 'const savedCxHdr=cxHdr;cxHdr=function(){savedCxHdr();paintMirrorWorkplace()};'


class CodexButtonLabel(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, 'cc_overview.py'), encoding='utf-8') as f:
            self.src = f.read()

    def test_header_repaint_is_followed_by_profile_system_label(self):
        self.assertEqual(self.src.count(WRAP), 1)
        self.assertLess(self.src.index('const savedCxbRender=cxbRender;'), self.src.index(WRAP))

    def test_profile_system_painter_writes_the_same_node(self):
        self.assertIn("putText(button.querySelector('.cxbtnname'),state.label)", self.src)
        self.assertIn("button=document.getElementById('cxBtn')", self.src)


if __name__ == '__main__':
    unittest.main()
