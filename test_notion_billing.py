"""Тесты даты оплаты Notion AI и счётчика до следующей оплаты (billing_info, parse_paid_at, save_cfg)."""
import os
os.environ["CC_FLEET_TZ"] = "Asia/Irkutsk"   # зона владельца в тестах не зависит от config.json и пояса сервера
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import cc_notion_ai as M

IRK = timezone(timedelta(hours=8))


def at(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=IRK)


class Parse(unittest.TestCase):
    def test_ok(s):
        s.assertEqual(M.parse_paid_at('2026-11-06 17:06'), at(2026, 11, 6, 17, 6))
        s.assertEqual(M.parse_paid_at('2026-11-06T17:06'), at(2026, 11, 6, 17, 6))
        s.assertEqual(M.parse_paid_at(' 2026-11-06 17:06 '), at(2026, 11, 6, 17, 6))

    def test_bad(s):
        for v in ('', None, 5, '2026-02-30 10:00', '2026-13-01 10:00', '06.11.2026 17:06', '2026-11-06', '2026-11-06 25:00'):
            s.assertIsNone(M.parse_paid_at(v), v)


class Info(unittest.TestCase):
    def info(s, paid, now, **kw):
        return M.billing_info(dict(paid_at=paid, **kw), now)

    def test_first_period(s):
        r = s.info('2026-11-06 17:06', at(2026, 11, 6, 19, 0))
        s.assertTrue(r['ok'])
        s.assertEqual((r['next_text'], r['days_left'], r['hours_left'], r['renewals']), ('06.12.2026 17:06', 29, 22, 0))
        s.assertEqual(r['next_at'], '2026-12-06T17:06:00+08:00')
        s.assertEqual(r['period_start'], '2026-11-06T17:06:00+08:00')
        s.assertEqual(r['seconds_left'], 29 * 86400 + 22 * 3600 + 6 * 60)

    def test_boundary_equal_is_past(s):
        r = s.info('2026-11-06 17:06', at(2026, 12, 6, 17, 6, 0))
        s.assertEqual((r['next_at'], r['renewals']), ('2027-01-06T17:06:00+08:00', 1))
        r = s.info('2026-11-06 17:06', at(2026, 12, 6, 17, 5, 59))
        s.assertEqual((r['next_at'], r['renewals'], r['seconds_left']), ('2026-12-06T17:06:00+08:00', 0, 1))

    def test_clamp_is_not_cumulative(s):
        s.assertEqual(s.info('2026-01-31 10:00', at(2026, 2, 10))['next_at'], '2026-02-28T10:00:00+08:00')
        s.assertEqual(s.info('2026-01-31 10:00', at(2026, 3, 1))['next_at'], '2026-03-31T10:00:00+08:00')
        s.assertEqual(s.info('2026-01-31 10:00', at(2026, 2, 28, 12))['next_at'], '2026-03-31T10:00:00+08:00')
        s.assertEqual(s.info('2027-12-31 10:00', at(2028, 1, 15))['next_at'], '2028-01-31T10:00:00+08:00')
        s.assertEqual(s.info('2027-12-31 10:00', at(2028, 2, 1))['next_at'], '2028-02-29T10:00:00+08:00')  # високосный

    def test_year_wrap_and_long_gap(s):
        r = s.info('2026-11-06 17:06', at(2027, 12, 7))
        s.assertEqual((r['next_at'], r['renewals']), ('2028-01-06T17:06:00+08:00', 13))
        s.assertEqual(r['period_start'], '2027-12-06T17:06:00+08:00')

    def test_future_start(s):
        r = s.info('2026-11-06 17:06', at(2026, 11, 1))
        s.assertEqual((r['next_at'], r['renewals']), ('2026-12-06T17:06:00+08:00', 0))

    def test_other_timezone_now(s):
        utc = timezone.utc
        r = M.billing_info(dict(paid_at='2026-11-06 17:06'), datetime(2026, 11, 6, 11, 0, tzinfo=utc))  # = 19:00 Иркутск
        s.assertEqual((r['days_left'], r['hours_left']), (29, 22))

    def test_empty(s):
        r = M.billing_info(dict(paid_at='', plan='Plus'))
        s.assertEqual((r['ok'], r['plan']), (False, 'Plus'))
        s.assertTrue(r['reason'])
        s.assertFalse(M.billing_info({})['ok'])

    def test_default_now(s):
        r = M.billing_info(dict(paid_at='2026-11-06 17:06'))
        s.assertTrue(r['ok'])
        s.assertGreater(r['seconds_left'], 0)
        s.assertLessEqual(r['seconds_left'], 32 * 86400)


class Save(unittest.TestCase):
    def setUp(s):
        s.tmp = tempfile.mkdtemp()
        s.old = M.CFG_FILE
        M.CFG_FILE = os.path.join(s.tmp, 'notion_ai.json')
        s.calls = []
        s.run_old = M._run
        M._run = lambda a, t=30: s.calls.append(a) or (0, '')

    def tearDown(s):
        M.CFG_FILE = s.old
        M._run = s.run_old

    def test_defaults_and_save(s):
        s.assertEqual((M.load_cfg()['paid_at'], M.load_cfg()['plan']), ('', ''))
        ok, msg, cfg = M.save_cfg({'paid_at': '2026-11-06T17:06', 'plan': '  Plus   plan '})
        s.assertTrue(ok, msg)
        s.assertEqual((cfg['paid_at'], cfg['plan']), ('2026-11-06 17:06', 'Plus plan'))
        s.assertEqual(json.load(open(M.CFG_FILE))['paid_at'], '2026-11-06 17:06')
        s.assertEqual(M.load_cfg()['paid_at'], '2026-11-06 17:06')

    def test_bad_values_not_saved(s):
        M.save_cfg({'paid_at': '2026-11-06 17:06'})
        for body in ({'paid_at': '06.11.2026'}, {'paid_at': '2026-02-30 10:00'}, {'paid_at': '2023-12-31 23:59'},
                     {'paid_at': (datetime.now(IRK) + timedelta(days=5)).strftime('%Y-%m-%d %H:%M')},
                     {'plan': 'x' * 31}, {'plan': 'a<b'}, {'plan': 'a\x07b'}):
            ok, msg, cfg = M.save_cfg(body)
            s.assertFalse(ok, body)
            s.assertEqual((cfg['paid_at'], cfg['plan']), ('2026-11-06 17:06', ''))
        s.assertEqual(M.load_cfg()['paid_at'], '2026-11-06 17:06')

    def test_clear(s):
        M.save_cfg({'paid_at': '2026-11-06 17:06', 'plan': 'Plus'})
        ok, msg, cfg = M.save_cfg({'paid_at': '', 'plan': ''})
        s.assertTrue(ok)
        s.assertEqual((cfg['paid_at'], cfg['plan']), ('', ''))

    def test_other_fields_untouched(s):
        M.save_cfg({'owner': 'Владелец'})
        M.save_cfg({'paid_at': '2026-11-06 17:06'})
        s.assertEqual(M.load_cfg()['owner'], 'Владелец')

    def test_cfg_public_has_fields(s):
        M.save_cfg({'paid_at': '2026-11-06 17:06'})
        s.assertEqual(M.cfg_public()['cfg']['paid_at'], '2026-11-06 17:06')


class Inject(unittest.TestCase):
    def test_acct_block_once(s):
        page = '<html><head></head><body><div class="modalh" id="modelsHdr"></div>\n mirrorLoad();\n\n loadRotation();</body></html>'
        a = M.inject(page)
        s.assertEqual(a.count('id="naiAcctScript"'), 1)
        s.assertEqual(M.inject(a).count('id="naiAcctScript"'), 1)
        s.assertIn("document.getElementById('fleetCodex')", a)
        s.assertIn("box.id='fleetNotionAcct'", a)  # id не должен совпадать с плиткой «Notion AI» в «Активных аккаунтах» (fleetNotion)
        s.assertNotIn("box.id='fleetNotion'", a)
        s.assertLess(a.index('id="naiAcctScript"'), a.rindex('</body>'))


class ModelList(unittest.TestCase):
    def test_service_items_hidden(s):
        old = (M.model_cached, M._delegate)
        M.model_cached = lambda: dict(model='Auto', effort='', ts=1, models_ts=1, efforts=[], models=[
            dict(label='Auto'), dict(label='Opus 5.5', tags=['Beta']), dict(label='Connect ChatGPT plan'),
            dict(label='Sonnet 5.5', more=True), dict(label='Restricted models', more=True)])
        M._delegate = lambda *a, **k: (_ for _ in ()).throw(OSError('нет сервиса'))
        try:
            labels = [m['label'] for m in M.model_public()['models']]
        finally:
            M.model_cached, M._delegate = old
        s.assertEqual(labels, ['Auto', 'Opus 5.5', 'Sonnet 5.5'])


class OwnerParse(unittest.TestCase):
    LT, GT = chr(60), chr(62)

    def tg(s, mid, text, ts='2026-11-06T10:20:11.000Z', extra=''):
        return s.LT + 'channel source="plugin:telegram:telegram" chat_id="1" message_id="%s" user="d" ts="%s"%s' % (mid, ts, extra) + s.GT + '\n' + text + '\n' + s.LT + '/channel' + s.GT

    def rec(s, content, typ='user', meta=False, ts='2026-11-06T09:00:00.000Z'):
        if typ == 'queue-operation':
            return json.dumps(dict(type=typ, operation='enqueue', timestamp=ts, content=content))
        return json.dumps(dict(type=typ, isMeta=meta, timestamp=ts, message=dict(role='user', content=content)))

    def lines(s):
        return [
            'обрезанный хвост строки',
            s.rec(s.tg(10, 'первое\n  из   двух  строк'), meta=True),
            s.rec('вопрос из консоли', ts='2026-11-06T10:30:00.000Z'),
            s.rec('[PANEL] Profile switched to you'),
            s.rec(s.LT + 'system-reminder' + s.GT + 'служебное'),
            s.rec('служебная вставка', meta=True),
            s.rec([dict(type='tool_result', content='x')]),
            s.rec([dict(type='text', text='часть один'), dict(type='text', text='часть два')], ts='2026-11-06T10:40:00.000Z'),
            s.rec(s.tg(12, '', ts='2026-11-06T11:00:00.000Z', extra=' image_path="/x.png"'), meta=True),
            s.rec(s.tg(10, 'дубль того же message_id'), meta=True),
            s.rec(s.tg(13, 'из очереди', ts='2026-11-06T11:05:00.000Z'), typ='queue-operation'),
            s.rec(s.tg(14, 'чужой источник').replace('plugin:telegram:telegram', 'plugin:other'), meta=True),
            s.rec(s.tg(15, 'с хвостом', ts='2026-11-06T11:10:00.000Z') + chr(10) + s.LT + 'system-reminder' + s.GT + 'хвост', meta=True, ts='2026-11-06T11:10:00.000Z'),
            s.rec(s.tg(16, 'Caveat: служебный текст')),
        ]

    def test_filtering_order_and_time(s):
        r = M.parse_owner_messages(s.lines())
        s.assertEqual([m['text'] for m in r], ['первое из двух строк', 'вопрос из консоли', 'часть один часть два', '[вложение]', 'из очереди', 'с хвостом'])
        s.assertEqual([m['src'] for m in r], ['Telegram', 'консоль', 'консоль', 'Telegram', 'Telegram', 'Telegram'])
        s.assertEqual(r[0]['ts'], at(2026, 11, 6, 18, 20, 11))           # UTC+8
        s.assertEqual(r[1]['ts'], at(2026, 11, 6, 18, 30))               # поле timestamp записи
        s.assertEqual(r[3]['ts'], at(2026, 11, 6, 19, 0))

    def test_limit_and_truncate(s):
        r = M.parse_owner_messages(s.lines(), limit=3)
        s.assertEqual([m['text'] for m in r], ['[вложение]', 'из очереди', 'с хвостом'])
        r = M.parse_owner_messages([s.rec('я' * 50)], max_chars=10)
        s.assertEqual(r[0]['text'], 'я' * 9 + '…')
        s.assertEqual(M.parse_owner_messages(s.lines(), limit=0), [])

    def test_bad_input(s):
        s.assertEqual(M.parse_owner_messages(['', '{', '[]', '{"type":"user"}', json.dumps(dict(type='user', message=dict(content=5)))]), [])

    def test_render(s):
        now = at(2026, 11, 6, 19, 40)
        out = M.render_owner_last(M.parse_owner_messages(s.lines(), limit=2), now)
        s.assertTrue(out.startswith('# Последние сообщения владельца\n\nСобрано панелью автоматически 06.11.2026 19:40 (Asia/Irkutsk)'))
        s.assertIn('- 06.11 19:05 · Telegram: из очереди\n', out)
        s.assertTrue(out.endswith('\n'))
        s.assertIn('Сообщений не найдено.', M.render_owner_last([], now))

    def test_tail_lines(s):
        f = os.path.join(tempfile.mkdtemp(), 'h.jsonl')
        s.assertEqual(M.read_tail_lines(f), [])
        open(f, 'w', encoding='utf-8').write('aaaa\nbbbb\ncccc\n')
        s.assertEqual(M.read_tail_lines(f), ['aaaa', 'bbbb', 'cccc'])
        s.assertEqual(M.read_tail_lines(f, 8), ['cccc'])  # первая (обрезанная) строка отброшена
        s.assertEqual(M.read_tail_lines(f, 0), [])

    def test_card_state(s):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'card.md')
        r = M.card_state(p)
        s.assertEqual((r['exists'], r['size'], r['stale'], r['empty'], r['too_big']), (False, 0, False, False, False))
        open(p, 'w').write('  \n')
        s.assertTrue(M.card_state(p)['empty'])
        open(p, 'w').write('текст')
        r = M.card_state(p)
        s.assertEqual((r['exists'], r['empty'], r['stale'], r['too_big'], r['age_days']), (True, False, False, False, 0.0))
        old = datetime.now().timestamp() - 8 * 86400
        os.utime(p, (old, old))
        r = M.card_state(p)
        s.assertTrue(r['stale'])
        s.assertEqual(r['age_days'], 8.0)
        open(p, 'w').write('x' * 8001)
        s.assertTrue(M.card_state(p)['too_big'])
        open(p, 'w').write('x' * 8000)
        s.assertFalse(M.card_state(p)['too_big'])


if __name__ == '__main__':
    unittest.main()
