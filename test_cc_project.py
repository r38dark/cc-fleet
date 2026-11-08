"""Тесты команды cc-project (папка «текущий проект»): new, архив, show, check."""
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent / 'cc-project')


class CcProject(unittest.TestCase):
    def setUp(s):
        s.root = Path(tempfile.mkdtemp())
        s.dir = s.root / 'current_project'

    def run_cp(s, *args):
        env = dict(os.environ, CC_PROJECT_DIR=str(s.dir))
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env, timeout=30)

    def mode(s, p):
        return stat.S_IMODE(os.stat(p).st_mode)

    def test_new_in_empty_dir(s):
        r = s.run_cp('new', 'Тест задачи', '--by', 'Claude')
        s.assertEqual(r.returncode, 0, r.stderr)
        s.assertEqual(r.stdout.strip().splitlines(), ['Новая карточка: ' + str(s.dir / 'card.md')])
        card = s.dir / 'card.md'
        text = card.read_text(encoding='utf-8')
        s.assertTrue(text.startswith('# Карточка дела: Тест задачи\nНачато: '))
        s.assertIn('(Claude)', text.splitlines()[1])
        for h in ('## Цель', '## Этап', '## Сделано и проверено', '## Следующий шаг', '## Файлы и места', '## Открытые вопросы', '## Нельзя без слова владельца'):
            s.assertIn(h, text)
        s.assertEqual((s.mode(card), s.mode(s.dir)), (0o666, 0o777))
        s.assertFalse((s.dir / 'archive').exists())
        s.assertEqual([p.name for p in s.dir.iterdir()], ['card.md'])

    def test_second_new_archives(s):
        s.run_cp('new', 'Первая: задача №1!')
        (s.dir / 'card.md').write_text('# Карточка дела: Первая: задача №1!\nстарый текст\n', encoding='utf-8')
        r = s.run_cp('new', 'Вторая')
        s.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        s.assertEqual(len(lines), 2)
        s.assertTrue(lines[1].startswith('Старая в архиве: ' + str(s.dir / 'archive') + '/'))
        archived = list((s.dir / 'archive').iterdir())
        s.assertEqual(len(archived), 1)
        name = archived[0].name
        s.assertRegex(name, r'^\d{8}-\d{4}_карточка_дела_первая_задача_1\.md$')
        s.assertIn('старый текст', archived[0].read_text(encoding='utf-8'))
        s.assertIn('# Карточка дела: Вторая', (s.dir / 'card.md').read_text(encoding='utf-8'))
        s.assertEqual(s.mode(s.dir / 'archive'), 0o777)
        s.assertEqual(s.mode(s.dir / 'card.md'), 0o666)

    def test_archive_name_collision(s):
        for i in range(3):
            s.run_cp('new', 'Задача %d' % i)
        names = sorted(p.name for p in (s.dir / 'archive').iterdir())
        s.assertEqual(len(names), 2)
        # третий и четвёртый вызовы в ту же минуту не затирают друг друга
        s.run_cp('new', 'Ещё')
        s.assertEqual(len(list((s.dir / 'archive').iterdir())), 3)

    def test_bad_titles_leave_files(s):
        s.run_cp('new', 'Нормальная')
        before = (s.dir / 'card.md').read_text(encoding='utf-8')
        for title in ('', '   ', 'x' * 101, 'a\x07b'):
            r = s.run_cp('new', title)
            s.assertEqual(r.returncode, 2, title)
            s.assertTrue(r.stderr.strip())
        s.assertEqual((s.dir / 'card.md').read_text(encoding='utf-8'), before)
        s.assertFalse((s.dir / 'archive').exists())
        s.assertEqual(s.run_cp('new', 'x' * 100).returncode, 0)

    def test_empty_old_card_not_archived(s):
        s.dir.mkdir()
        (s.dir / 'card.md').write_text('  \n\n')
        r = s.run_cp('new', 'Новая')
        s.assertEqual(r.returncode, 0, r.stderr)
        s.assertFalse((s.dir / 'archive').exists())
        s.assertEqual(len(r.stdout.strip().splitlines()), 1)

    def test_check_states(s):
        r = s.run_cp('check')
        s.assertEqual(r.returncode, 1)
        s.assertIn('Карточки нет', r.stdout)
        s.assertEqual(s.run_cp('show').returncode, 0)
        s.run_cp('new', 'Нормальная')
        r = s.run_cp('check')
        s.assertEqual(r.returncode, 0, r.stdout)
        s.assertIn('Карточка: есть', r.stdout)
        card = s.dir / 'card.md'
        card.write_text('  \n')
        r = s.run_cp('check')
        s.assertEqual(r.returncode, 1)
        s.assertIn('Пуста', r.stdout)
        card.write_text('x' * 8001)
        r = s.run_cp('check')
        s.assertEqual(r.returncode, 1)
        s.assertIn('Слишком длинная', r.stdout)
        card.write_text('нормально')
        old = time.time() - 8 * 86400
        os.utime(card, (old, old))
        r = s.run_cp('check')
        s.assertEqual(r.returncode, 1)
        s.assertIn('Устарела', r.stdout)
        s.assertIn('Возраст: 8.0', r.stdout)
        r = s.run_cp('show')
        s.assertEqual(r.returncode, 0)
        s.assertIn('Устарела', r.stdout)


if __name__ == '__main__':
    unittest.main()
