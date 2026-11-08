"""Хвост беседы для передачи работы: разбор записи беседы, состояние ЗАВЕРШЕНО / НЕ ЗАВЕРШЕНО, скрытие секретов."""
import os
os.environ["CC_FLEET_TZ"] = "Asia/Irkutsk"   # зона владельца в тестах не зависит от config.json и пояса сервера
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone

import cc_handoff_tail as T

NOW = datetime(2026, 11, 7, 9, 21, 0, tzinfo=timezone.utc)   # 17:21 Иркутск


def tg(mid, ts, text):
    body = '<channel source="plugin:telegram:telegram" chat_id="1" message_id="%s" user="d" user_id="1" ts="%s">\n%s\n</channel>' % (mid, ts, text)
    return json.dumps(dict(type='user', isMeta=True, timestamp=ts, message=dict(role='user', content=body)))


def say(ts, text):
    return json.dumps(dict(type='assistant', timestamp=ts, message=dict(role='assistant', content=[dict(type='text', text=text)])))


def tool(ts, tid, name, inp):
    return json.dumps(dict(type='assistant', timestamp=ts, message=dict(role='assistant', content=[dict(type='tool_use', id=tid, name=name, input=inp)])))


def result(ts, tid, text, error=False):
    return json.dumps(dict(type='user', timestamp=ts, message=dict(role='user', content=[dict(type='tool_result', tool_use_id=tid, content=text, is_error=error)])))


def reply(ts, tid, text):
    return tool(ts, tid, 'mcp__plugin_telegram_telegram__reply', dict(chat_id='1', text=text))


class Events(unittest.TestCase):
    def test_answered_message_is_finished(self):
        lines = [tg('7', '2026-11-07T09:20:00.000Z', 'могу включать?'),
                 tool('2026-11-07T09:20:05.000Z', 'a', 'Bash', dict(command='echo 1', description='проверка')),
                 result('2026-11-07T09:20:06.000Z', 'a', 'ok'),
                 reply('2026-11-07T09:20:10.000Z', 'b', 'да, включай'),
                 result('2026-11-07T09:20:11.000Z', 'b', 'sent (id: 9)'),
                 say('2026-11-07T09:20:12.000Z', 'Ответил владельцу.')]
        info = T.analyse(T.read_events(lines))
        self.assertEqual(info['state'], 'finished')
        self.assertEqual(info['owner']['text'], 'могу включать?')

    def test_unanswered_telegram_message_is_unfinished(self):
        lines = [say('2026-11-07T09:19:00.000Z', 'готово'), tg('8', '2026-11-07T09:20:00.000Z', 'сделай ещё одно')]
        info = T.analyse(T.read_events(lines))
        self.assertEqual(info['state'], 'unfinished')
        self.assertIn('без ответа', info['reason'])

    def test_plain_text_is_not_an_answer_to_telegram(self):
        # владелец читает только Telegram: текст в консоли без telegram reply — ответом не считается
        lines = [tg('8', '2026-11-07T09:20:00.000Z', 'вопрос'), say('2026-11-07T09:20:05.000Z', 'думаю вслух')]
        self.assertEqual(T.analyse(T.read_events(lines))['state'], 'unfinished')

    def test_console_message_answered_by_text(self):
        lines = [json.dumps(dict(type='user', timestamp='2026-11-07T09:20:00.000Z', message=dict(role='user', content='привет из консоли'))),
                 say('2026-11-07T09:20:05.000Z', 'привет')]
        events = T.read_events(lines)
        self.assertEqual(events[0]['src'], 'консоль')
        self.assertEqual(T.analyse(events)['state'], 'finished')

    def test_cut_on_tool_call_is_unfinished(self):
        lines = [tg('9', '2026-11-07T09:20:00.000Z', 'правь файл'),
                 reply('2026-11-07T09:20:03.000Z', 'r', 'принял'), result('2026-11-07T09:20:04.000Z', 'r', 'sent'),
                 tool('2026-11-07T09:20:10.000Z', 'e', 'Edit', dict(file_path='/root/a.py'))]
        info = T.analyse(T.read_events(lines))
        self.assertEqual(info['state'], 'unfinished')
        self.assertIn('Edit', info['reason'])

    def test_cut_after_tool_result_is_unfinished(self):
        lines = [tg('9', '2026-11-07T09:20:00.000Z', 'правь файл'),
                 reply('2026-11-07T09:20:03.000Z', 'r', 'принял'), result('2026-11-07T09:20:04.000Z', 'r', 'sent'),
                 tool('2026-11-07T09:20:10.000Z', 'e', 'Edit', dict(file_path='/root/a.py')), result('2026-11-07T09:20:11.000Z', 'e', 'edited')]
        self.assertEqual(T.analyse(T.read_events(lines))['state'], 'unfinished')

    def test_empty_is_unknown(self):
        self.assertEqual(T.analyse([])['state'], 'unknown')

    def test_panel_messages_and_subagents_are_not_owner(self):
        panel = json.dumps(dict(type='user', timestamp='2026-11-07T09:20:00.000Z', message=dict(role='user', content='[PANEL 17:20] Profile switched')))
        side = json.dumps(dict(type='user', isSidechain=True, timestamp='2026-11-07T09:20:01.000Z', message=dict(role='user', content='внутренний запрос')))
        self.assertEqual(T.read_events([panel, side, 'не json']), [])

    def test_duplicate_telegram_message_counted_once(self):
        queue = json.dumps(dict(type='queue-operation', timestamp='2026-11-07T09:20:00.000Z',
                                content='<channel source="plugin:telegram:telegram" message_id="5" ts="2026-11-07T09:20:00.000Z">\nодин раз\n</channel>'))
        events = T.read_events([queue, tg('5', '2026-11-07T09:20:00.000Z', 'один раз')])
        self.assertEqual([e['text'] for e in events if e['kind'] == 'owner'], ['один раз'])

    def test_foreign_channel_ignored(self):
        body = '<channel source="plugin:other:x" message_id="1" ts="2026-11-07T09:20:00.000Z">чужое</channel>'
        row = json.dumps(dict(type='user', isMeta=True, timestamp='2026-11-07T09:20:00.000Z', message=dict(role='user', content=body)))
        self.assertEqual(T.read_events([row]), [])


class Redact(unittest.TestCase):
    def test_secrets_hidden_paths_kept(self):
        text = ('password=hunter2 token: abc123 Authorization: Bearer abcdefghijklmnop sk-ant-api03-abcdefghijklmnopqrstuvwxyz '  # privacy-ok
                'AKIAABCDEFGHIJKLMNOP0123 ' + 'A1b2C3d4' * 8 + ' /opt/cc-limits/profile_exchange/codex/outbox/agent_handoff/current_project/card.md '  # privacy-ok
                'project_friend_claude_prod_clone_20261106 d94da257-f3d7-42f6-9f4c-3bd36531050a')
        out = T.redact(text)
        for secret in ('hunter2', 'abc123', 'abcdefghijklmnop', 'sk-ant-api03', 'AKIAABCDEFGH', 'A1b2C3d4A1b2C3d4'):
            self.assertNotIn(secret, out)
        self.assertIn('/opt/cc-limits/profile_exchange/codex/outbox/agent_handoff/current_project/card.md', out)
        self.assertIn('project_friend_claude_prod_clone_20261106', out)
        self.assertIn('d94da257-f3d7-42f6-9f4c-3bd36531050a', out)

    def test_separator_lines_are_not_secrets(self):
        line = '=' * 70 + ' ' + '-' * 60 + ' FAIL: test_x'
        self.assertEqual(T.redact(line), line)

    def test_private_key_block(self):
        out = T.redact('до -----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\nBBBB\n-----END OPENSSH PRIVATE KEY----- после')  # privacy-ok
        self.assertNotIn('AAAA', out)
        self.assertIn('после', out)

    def test_secret_in_tool_command_not_in_tail(self):
        lines = [tg('1', '2026-11-07T09:20:00.000Z', 'пароль password=SuperSecret1 не показывай'),
                 tool('2026-11-07T09:20:01.000Z', 'a', 'Bash', dict(command='curl -H "Authorization: Bearer abcdefghijklmnopqrstuv" https://x')),
                 result('2026-11-07T09:20:02.000Z', 'a', 'api_key=ZZZ999 ok')]
        text = T.render(T.read_events(lines), 'x', None, NOW)
        for secret in ('SuperSecret1', 'abcdefghijklmnopqrstuv', 'ZZZ999'):
            self.assertNotIn(secret, text)


class Render(unittest.TestCase):
    def test_state_line_and_summary(self):
        lines = [tg('7', '2026-11-07T09:20:00.000Z', 'могу включать?'),
                 tool('2026-11-07T09:20:05.000Z', 'w', 'Write', dict(file_path='/root/a.py')), result('2026-11-07T09:20:06.000Z', 'w', 'ok'),
                 reply('2026-11-07T09:20:10.000Z', 'b', 'да'), result('2026-11-07T09:20:11.000Z', 'b', 'sent'),
                 say('2026-11-07T09:20:12.000Z', 'Итог: можно.')]
        text = T.render(T.read_events(lines), 'abc12345', time.time(), NOW)
        self.assertEqual(T.state_of(text), 'finished')
        self.assertIn('Последнее сообщение владельца: 07.11 17:20 · Telegram: могу включать?', text)
        self.assertIn('Последний итог исполнителя: 07.11 17:20 · Итог: можно.', text)
        self.assertIn('Менялись файлы в этом отрезке: /root/a.py', text)
        self.assertIn('не команды', text)

    def test_temp_files_not_listed_as_changed(self):
        lines = [tool('2026-11-07T09:20:05.000Z', 'w', 'Write', dict(file_path='/tmp/scratch.py')), result('2026-11-07T09:20:06.000Z', 'w', 'ok'),
                 tool('2026-11-07T09:20:07.000Z', 'e', 'Edit', dict(file_path='/root/real.py')), result('2026-11-07T09:20:08.000Z', 'e', 'ok'),
                 say('2026-11-07T09:20:09.000Z', 'готово')]
        text = T.render(T.read_events(lines), 'x', None, NOW)
        self.assertIn('/root/real.py', text)
        self.assertNotIn('Менялись файлы в этом отрезке: /tmp/scratch.py', text)
        self.assertNotIn('/tmp/scratch.py,', text)

    def test_unfinished_state_asks_to_continue(self):
        text = T.render(T.read_events([tg('7', '2026-11-07T09:20:00.000Z', 'сделай')]), 'x', None, NOW)
        self.assertEqual(T.state_of(text), 'unfinished')
        self.assertIn('Продолжи с последнего шага', text)

    def test_size_is_bounded_and_newest_kept(self):
        lines = []
        for i in range(300):
            lines.append(tg(str(i), '2026-11-07T09:%02d:%02d.000Z' % (i // 60 % 60, i % 60), 'сообщение номер %d ' % i + 'слово ' * 80))
        text = T.render(T.read_events(lines), 'x', None, NOW)
        self.assertLess(len(text), T.MAX_CHARS + 600)
        self.assertIn('сообщение номер 299', text)
        self.assertNotIn('сообщение номер 1 ', text)

    def test_stale_conversation_is_flagged(self):
        text = T.render(T.read_events([say('2026-11-07T01:00:00.000Z', 'давно')]), 'x', NOW.timestamp() - 10 * 3600, NOW)
        self.assertIn('ВНИМАНИЕ', text)

    def test_state_of_garbage(self):
        self.assertEqual(T.state_of(''), '')
        self.assertEqual(T.state_of('нет такой строки'), '')


class Files(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def write(self, name, lines, mtime):
        path = os.path.join(self.d, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        os.utime(path, (mtime, mtime))
        return path

    def test_recent_transcripts_order_and_window(self):
        now = time.time()
        old = self.write('old.jsonl', ['{}'], now - 10 * 3600)
        mid = self.write('mid.jsonl', ['{}'], now - 100)
        new = self.write('new.jsonl', ['{}'], now - 10)
        self.write('notes.txt', ['x'], now)
        self.assertEqual(T.recent_transcripts(self.d, 3), [new, mid, old])
        self.assertEqual(T.recent_transcripts(self.d, 3, window=3600), [new, mid])
        self.assertEqual(T.recent_transcripts(os.path.join(self.d, 'нет'), 3), [])

    def test_build_merges_conversations_by_time(self):
        """После работы на PROD свежих бесед две: принесённая с PROD и новая на dev. Хвост видит обе, по времени."""
        now = time.time()
        prod = self.write('prod.jsonl', [tg('1', '2026-11-07T09:20:00.000Z', 'вопрос владельцу'), reply('2026-11-07T09:20:10.000Z', 'r', 'ответ'),
                                          result('2026-11-07T09:20:11.000Z', 'r', 'sent'), say('2026-11-07T09:20:12.000Z', 'готово')], now - 60)
        dev = self.write('dev.jsonl', [json.dumps(dict(type='user', timestamp='2026-11-07T09:21:04.000Z', message=dict(role='user', content='[PANEL] Profile switched')))], now - 5)
        text = T.build([dev, prod], now=NOW)
        self.assertEqual(T.state_of(text), 'finished')
        self.assertIn('вопрос владельцу', text)
        self.assertIn('prod.jso'[:8], text)
        self.assertLess(text.index('вопрос владельцу'), text.index('ответ'))

    def test_last_owner_message_found_behind_huge_tool_results(self):
        """R4-3: после сообщения владельца картинки и крупные результаты занимают больше TAIL_BYTES — оно не должно теряться."""
        now = time.time()
        big = 'x' * 700000
        lines = [tg('1', '2026-11-07T09:00:00.000Z', 'старый вопрос'), reply('2026-11-07T09:00:05.000Z', 'r0', 'ответ'),
                 result('2026-11-07T09:00:06.000Z', 'r0', 'sent'),
                 tg('2', '2026-11-07T09:10:00.000Z', 'последняя просьба владельца')]
        for i in range(4):  # 4 × 0,7 МБ = 2,8 МБ после сообщения, больше окна 1,5 МБ
            lines += [tool('2026-11-07T09:11:0%d.000Z' % i, 't%d' % i, 'Read', dict(file_path='/f%d' % i)),
                      result('2026-11-07T09:11:1%d.000Z' % i, 't%d' % i, big)]
        path = self.write('big.jsonl', lines, now)
        self.assertGreater(os.path.getsize(path), T.TAIL_BYTES + 1000000)   # сообщение владельца точно вне первого окна
        text = T.build([path], now=NOW)
        self.assertIn('Последнее сообщение владельца: 07.11 17:10', text)   # 09:10 UTC = 17:10 Иркутск
        self.assertIn('последняя просьба владельца', text)
        self.assertEqual(T.state_of(text), 'unfinished')

    def test_window_stops_at_cap_when_no_owner_message(self):
        """Беседа без сообщений владельца не читается бесконечно: окно упирается в MAX_TAIL_BYTES."""
        now = time.time()
        lines = []
        for i in range(8):
            lines += [tool('2026-11-07T09:11:0%d.000Z' % i, 't%d' % i, 'Read', dict(file_path='/f%d' % i)),
                      result('2026-11-07T09:11:1%d.000Z' % i, 't%d' % i, 'y' * 700000)]
        path = self.write('noowner.jsonl', lines, now)
        old_cap, calls = T.MAX_TAIL_BYTES, []
        real = T.read_tail_lines
        T.MAX_TAIL_BYTES = 3000000
        T.read_tail_lines = lambda p, max_bytes=T.TAIL_BYTES: (calls.append(max_bytes), real(p, max_bytes))[1]
        try:
            events = T.read_events_tail(path)
        finally:
            T.MAX_TAIL_BYTES, T.read_tail_lines = old_cap, real
        self.assertEqual(calls, [1500000, 3000000])   # удвоили один раз и остановились на потолке
        self.assertTrue(events)
        self.assertFalse(any(e['kind'] == 'owner' for e in events))

    def test_small_conversation_read_once(self):
        path = self.write('small.jsonl', [tg('1', '2026-11-07T09:00:00.000Z', 'привет')], time.time())
        self.assertEqual([e['text'] for e in T.read_events_tail(path)], ['привет'])
        self.assertEqual(T.read_events_tail(os.path.join(self.d, 'нет.jsonl')), [])

    def test_build_without_files_is_unknown(self):
        self.assertEqual(T.state_of(T.build([], now=NOW)), 'unknown')

    def side_lines(self, question='сколько будет 2+2?', answer='4'):
        """Побочная беседа как её пишет Claude: служебные строки, напоминание, потом вопрос с меткой и ответ."""
        return [json.dumps(dict(type='permission-mode', permissionMode='bypassPermissions')),
                json.dumps(dict(type='user', isMeta=True, timestamp='2026-11-07T09:30:00.000Z', message=dict(role='user', content='<system-reminder>x</system-reminder>'))),
                json.dumps(dict(type='user', timestamp='2026-11-07T09:30:05.000Z', message=dict(role='user', content=[dict(type='text', text='<system-reminder>y</system-reminder>')]))),
                json.dumps(dict(type='user', timestamp='2026-11-07T09:30:10.000Z', message=dict(role='user', content=[dict(type='text', text=T.SIDE_MARK + ': ответь здесь] ' + question)]))),
                say('2026-11-07T09:30:15.000Z', answer)]

    def test_side_mark_matches_cc_fleet_label(self):
        import cc_fleet
        self.assertTrue(cc_fleet.SIDE_LABEL.startswith(T.SIDE_MARK))

    def test_side_transcript_detected_by_first_human_message(self):
        now = time.time()
        side = self.write('side.jsonl', self.side_lines(), now)
        str_side = self.write('str_side.jsonl', [json.dumps(dict(type='user', timestamp='2026-11-07T09:30:10.000Z', message=dict(role='user', content=T.SIDE_MARK + ': x] вопрос')))], now)
        main = self.write('main.jsonl', [json.dumps(dict(type='user', timestamp='2026-11-07T09:00:00.000Z', message=dict(role='user', content='[PANEL 17:00] передача'))),
                                         json.dumps(dict(type='user', timestamp='2026-11-07T09:00:05.000Z', message=dict(role='user', content='починь снимок')))], now)
        later = self.write('later.jsonl', [json.dumps(dict(type='user', timestamp='2026-11-07T09:00:00.000Z', message=dict(role='user', content='обычная просьба'))),
                                           json.dumps(dict(type='user', timestamp='2026-11-07T09:01:00.000Z', message=dict(role='user', content=T.SIDE_MARK + ': x] позже')))], now)
        empty = self.write('empty.jsonl', [], now)
        self.assertTrue(T.is_side_transcript(side))
        self.assertTrue(T.is_side_transcript(str_side))
        self.assertFalse(T.is_side_transcript(main))
        self.assertFalse(T.is_side_transcript(later))   # метка не в первом сообщении — беседа основная
        self.assertFalse(T.is_side_transcript(empty))
        self.assertFalse(T.is_side_transcript(os.path.join(self.d, 'нет.jsonl')))

    def test_recent_transcripts_skip_side_conversations(self):
        now = time.time()
        side = self.write('side.jsonl', self.side_lines(), now - 5)
        main = self.write('main.jsonl', [tg('1', '2026-11-07T09:00:00.000Z', 'задача')], now - 100)
        old = self.write('old.jsonl', [tg('2', '2026-11-07T01:00:00.000Z', 'давно')], now - 10 * 3600)
        self.assertEqual(T.recent_transcripts(self.d, 3), [main, old])
        self.assertEqual(T.recent_transcripts(self.d, 1), [main])
        self.assertEqual(T.recent_transcripts(self.d, 3, window=3600), [main])   # окно считается от самой свежей основной
        self.assertNotIn(side, T.recent_transcripts(self.d, 5))

    def test_side_question_after_unfinished_main_keeps_state_unfinished(self):
        """R4-2: основная работа оборвалась на вызове, потом в консоли задали побочный вопрос и получили ответ."""
        now = time.time()
        main = self.write('main.jsonl', [tg('1', '2026-11-07T09:20:00.000Z', 'доделай правку'),
                                         tool('2026-11-07T09:20:05.000Z', 'a', 'Edit', dict(file_path='/f.py'))], now - 100)
        self.write('side.jsonl', self.side_lines(), now - 5)
        text = T.build(T.recent_transcripts(self.d, 3), now=NOW)
        self.assertEqual(T.state_of(text), 'unfinished')
        self.assertIn('доделай правку', text)
        self.assertNotIn('2+2', text)
        self.assertIn(os.path.basename(main)[:8], text)


if __name__ == '__main__':
    unittest.main()
