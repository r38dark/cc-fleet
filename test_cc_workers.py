"""Общая механика исполнителей (cc_workers): шапка Claude DEV/PROD/Codex, указатель беседы Claude, передача работы,
уведомления о смене профиля, блоки общих настроек. python3 -m unittest test_cc_workers -v"""
import os
os.environ["CC_FLEET_TZ"] = "Asia/Irkutsk"   # зона владельца в тестах не зависит от config.json и пояса сервера
import json, tempfile, unittest, time, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
import cc_workers as M

TID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
IRK = timezone(timedelta(hours=8))


class Console:
    def __init__(s): s.PLAN = lambda: ('danger-full-access', '/opt/codex-trial', 'gpt1')
class Bridge:
    def load(s): return {'mode': 'self', 'access': 'full', 'workdir': '/opt/codex-trial', 'slot': 'gpt1'}
    def project_dir(s): return '/opt/proj'
class Claude:
    def __init__(s, t): s.t = t; s.applied = []
    def capture(s): return dict(pid='1', thread_id=TID, history=str(Path(s.t.d)/'h.jsonl'), cwd='/root', model='opus', effort='high')
class Native:
    def __init__(s, t):
        s.b = False; s.codex = Console(); s.bridge = Bridge(); s.claude = Claude(t); s.claude_work = t.d + '/work'; s.claude_cwd = '/root'
    def busy(s): return s.b
    def prompt(s, state, e): return 'orig-' + e
class State:
    def __init__(s): s.manual_choices = {'claude': None, 'codex': 'full'}; s.revision = 1
    def export(s): return dict(s.manual_choices)
    @classmethod
    def from_data(cls, d, clock): x = cls(); x.manual_choices = dict(d); return x
    def apply_scenario(s, choices, confirm='', revision=None):
        if 'full' in (choices or {}).values() and confirm != 'подтверждаю': return {'ok': False, 'confirmation_required': True, 'word': 'подтверждаю'}
        return {'ok': True}
class Profiles:
    def __init__(s, t):
        s.lock = threading.RLock(); s.transitioning = False; s.pending = Path(t.d)/'pending.json'; s.native = Native(t); s.calls = []
        s.labels = {'claude': 'Claude · не участвует', 'codex': 'Codex Full'}; s.avail = {'claude': {'status': 'up'}, 'codex': {'status': 'up'}}
        s.state = State(); s.clock = time.time
    def update_active(s): return False
    def paused(s, e): return e == 'claude'
    def public(s): return {'engines': {e: {'label': l, 'role': 'solo'} for e, l in s.labels.items()}, 'revision': 1}
    def transition(s, c, m, force=None, recover_blocked=False):
        s.calls.append(m)
        if getattr(s, 'next_labels', None): s.labels = s.next_labels
        return {'ok': True}
    def action(s, e, a, b): s.calls.append('action'); return {'ok': True}
    def apply_scenario(s, b): s.calls.append('scenario'); return getattr(s, 'scenario_result', {'ok': True})
    def exchange(s, e): return Path('/ex')/e
class H:
    def do_GET(s): s._send(404, {'ok': False, 'base': True})
    def do_POST(s): s._send(404, {'ok': False, 'base': True})


class Base(unittest.TestCase):
    def setUp(s):
        s.d = tempfile.mkdtemp(); s.sent = []; s.runs = []
        (Path(s.d)/'profile_runtime').mkdir(); (Path(s.d)/'h.jsonl').write_text('')
        s.ns = {'BASE': s.d, 'cfg': lambda: {'screen_session': 'testscreen', 'chat_id': '100000001'}, 'tg_notify': lambda t: s.sent.append(('claude', t)), 'H': H,
                'PAGE': '<html><head></head><body>x\n mirrorLoad();\n\n loadRotation();\n</body></html>', 'transcripts_dir': lambda: s.d}
        class B: BRIDGE = type('X', (), {'send': lambda self, t: s.sent.append(('codex', t))})()
        s.ns['cc_codex_bridge'] = B
        s.claude = [True]; s.side = [False]
        def run(args, timeout=30):
            s.runs.append(args)
            if args[:2] == ['screen', '-ls']: return 0, ('\t123.testscreen\t(Detached)\n' if s.claude[0] else 'No Sockets')
            if args[:2] == ['screen', '-S'] and 'quit' in args: s.claude[0] = False; return 0, ''
            if args[0] == 'pgrep': return (0 if s.claude[0] and not s.side[0] else 1), ''
            if args[0] == 'systemd-run': s.claude[0] = True; return 0, ''
            if args[:2] == ['systemctl', 'is-active']: return 0, 'active\n'
            return 0, ''
        old = (M._run, M.SIDE_FLAG, M.Workers._later)
        s.addCleanup(lambda: (setattr(M, '_run', old[0]), setattr(M, 'SIDE_FLAG', old[1]), setattr(M.Workers, '_later', old[2])))
        M._run = run; M.SIDE_FLAG = s.d + '/side_claude.json'   # stop_claude стирает флаг побочной сессии: не по боевому пути
        M.Workers._later = lambda self, fn, *a: fn(*a)
        s.p = Profiles(s); s.wk = M.install(s.ns, s.p)


class T(Base):
    def test_page_injected_once(s):
        page = s.ns['PAGE']
        for mark in ('id="wkScript"', 'id="wkCfgScript"', 'id="wkStyle"'):
            s.assertEqual(page.count(mark), 1, mark)
        s.assertNotIn('wkPickerStyle', page)   # меню профиля плиток — часть обзора (cc_overview), не вставка этого модуля
        s.assertEqual(M.inject(page), page)
        s.assertIs(s.ns['WORKERS'], s.wk)

    def test_agents(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'paused', 'label': 'Claude · не участвует'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
        s.p.state = St(); a = s.wk.agents()
        s.assertEqual(set(a), {'claude', 'prod', 'codex'})   # третьего агента нет
        s.assertEqual((a['claude']['state'], a['codex']['state'], a['prod']['state']), ('pause', 'run', 'pause'))
        s.assertEqual(a['claude']['text'], 'пауза')
        s.assertIn('на паузе', a['claude']['label']); s.assertNotIn('не участвует', a['claude']['label'])
        s.assertNotIn('выкл', json.dumps(a, ensure_ascii=False))
        s.p.avail['claude']['status'] = 'down'; s.assertEqual(s.wk.agents()['claude']['state'], 'limit')
        s.assertEqual(set(s.wk.public()), {'ok', 'agents'})

    def test_leader_and_executor_states(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'leader', 'label': 'Claude · оркестратор'}, 'codex': {'role': 'executor', 'label': 'Codex · исполнитель Claude'}}}
        s.p.state = St(); a = s.wk.agents()
        s.assertEqual((a['claude']['state'], a['claude']['text'], a['codex']['state'], a['codex']['text']), ('lead', 'ведущий', 'exec', 'исполнитель'))

    def test_unlinked_codex_is_a_ghost_tile(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'solo', 'label': 'Claude Full'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
        s.p.state = St()
        s.ns['cc_codex'] = type('C', (), {'profile_slots': staticmethod(lambda: [])})
        a = s.wk.agents()
        s.assertEqual((a['codex']['state'], a['codex']['text']), ('unlinked', 'не подключён'))
        s.assertEqual(a['claude']['state'], 'run')
        s.ns['cc_codex'] = type('C', (), {'profile_slots': staticmethod(lambda: ['gpt1'])})
        s.assertEqual(s.wk.agents()['codex']['state'], 'run')

    def test_unlinked_check_failure_keeps_tiles_working(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'solo', 'label': 'Claude Full'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
        s.p.state = St()
        class Bad:
            @staticmethod
            def profile_slots(): raise OSError('нет доступа')
        s.ns['cc_codex'] = Bad
        s.assertEqual(s.wk.agents()['codex']['state'], 'run')   # не смогли проверить — рабочее не прячем

    def test_profile_change_is_announced_in_both_chats(s):
        s.p.next_labels = {'claude': 'Claude Full · самостоятельно', 'codex': 'Codex · на паузе'}
        s.assertTrue(s.p.transition('X', 'Сценарий применён к консолям.')['ok'])
        s.assertIn(('claude', '🔀 Профиль Claude: Claude Full · самостоятельно'), s.sent)
        s.assertIn(('codex', '🔀 Профиль Codex: Codex · на паузе'), s.sent)
        s.sent.clear(); s.p.next_labels = {'claude': 'Claude · на паузе', 'codex': 'Codex Full'}
        s.p.transition('X', M.AUTO_MESSAGE)
        s.assertIn(('claude', '🔀 Профиль Claude: Claude · на паузе (автоматически)'), s.sent)   # автосценарий больше не откладывается
        s.sent.clear(); s.p.transition('X', 'без изменений')
        s.assertEqual(s.sent, [])   # подписи не поменялись — сообщений нет

    def test_wrappers_left_alone(s):
        # пауза, публичное состояние, действия, подсказка и план Codex — без подмен
        s.assertEqual(s.p.paused('claude'), True); s.assertEqual(s.p.paused('codex'), False)
        s.assertIs(s.p.public.__func__, Profiles.public); s.assertIs(s.p.paused.__func__, Profiles.paused)
        s.assertEqual(s.p.native.prompt(None, 'codex'), 'orig-codex')
        s.assertEqual(s.p.native.codex.PLAN()[0], 'danger-full-access')
        s.assertEqual(s.p.action('codex', 'apply', {}), {'ok': True})


class Scenario(Base):
    def test_codex_to_claude_resumes_known_session(s):
        s.claude[0] = False; snap = {'thread_id': 'known', 'telegram_channel': True, 'sandbox_root': True}
        s.wk.handoff_snapshot_load = lambda: snap
        calls = []; s.wk.handoff_start_staging = lambda snapshot: calls.append(snapshot)
        s.p.native.claude.capture = lambda: dict(snap)
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok']); s.assertEqual(calls, [snap]); s.assertIn('scenario', s.p.calls)
        s.assertIsNone(s.p.native._handoff_snapshot); s.assertFalse(s.p.native._handoff_telegram); s.assertFalse(s.p.native._handoff_sandbox_root)

    def test_remote_claude_scenario_does_not_require_local_history(s):
        s.claude[0] = False; s.p.native._remote = lambda: object()
        s.wk.handoff_snapshot_load = lambda: s.fail('local history queried for remote session')
        s.wk.handoff_start_staging = lambda snapshot: s.fail('local session started for remote session')
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok']); s.assertIn('scenario', s.p.calls); s.assertFalse(s.claude[0])

    def test_remote_scenario_failure_is_not_replaced_with_local_staging(s):
        s.claude[0] = False; s.p.native._remote = lambda: object()
        s.p.scenario_result = {'ok': False, 'busy': True}
        s.wk.handoff_start_staging = lambda snapshot: s.fail('local session started after remote failure')
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertFalse(r['ok']); s.assertTrue(r['busy']); s.assertFalse(s.claude[0])

    def test_local_scenario_still_requires_verified_history(s):
        s.claude[0] = False; s.p.native._remote = lambda: None; s.wk.handoff_snapshot_load = lambda: None
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertFalse(r['ok']); s.assertNotIn('scenario', s.p.calls); s.assertFalse(s.claude[0])
        s.assertIn('Не найдена проверенная беседа Claude', r['message'])

    def test_codex_to_claude_failure_stops_staging(s):
        s.claude[0] = False; s.wk.handoff_snapshot_load = lambda: {'thread_id': 'known'}
        s.wk.handoff_start_staging = lambda snapshot: True
        stopped = []; s.wk.handoff_stop_staging = lambda: stopped.append(True) or True
        s.p.scenario_result = {'ok': False, 'message': 'тестовая ошибка'}
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertFalse(r['ok']); s.assertEqual(stopped, [True]); s.assertIn('Исходный профиль сохранён', r['message'])

    def test_unconfirmed_scenario_is_not_staged(s):
        s.claude[0] = False; s.wk.handoff_snapshot_load = lambda: s.fail('dry run must stop first')
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'revision': 1})
        s.assertTrue(r.get('confirmation_required'))

    def test_codex_scenario_does_not_start_claude(s):
        s.claude[0] = False; before = len(s.runs)
        r = s.p.apply_scenario({'choices': {'claude': None, 'codex': 'full'}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok']); s.assertFalse(s.claude[0]); s.assertFalse(any(a[0] == 'systemd-run' for a in s.runs[before:]))

    def test_staging_explicitly_disables_telegram_plugin(s):
        s.claude[0] = False
        snap = {'thread_id': 'known', 'cwd': s.d, 'model': 'claude-test', 'effort': 'xhigh'}
        s.wk.handoff_valid_snapshot = lambda _: True
        s.ns['screen_hardcopy'] = lambda: '❯'
        s.p.native.claude.capture = lambda: {'thread_id': 'known'}
        s.assertTrue(s.wk.handoff_start_staging(snap))
        args = next(a for a in s.runs if a[0] == 'systemd-run')
        s.assertNotIn('--channels', args)
        settings = json.loads(args[args.index('--settings') + 1])
        s.assertIs(settings['enabledPlugins']['telegram@claude-plugins-official'], False)

    def test_resume_snapshot_validation_and_do_not_overwrite(s):
        history = Path(s.d)/(TID + '.jsonl'); history.write_text('test')
        s.ns['cfg'] = lambda: {'screen_session': 'testscreen', 'transcripts_dir': s.d}
        good = {'thread_id': TID, 'history': str(history), 'cwd': s.d, 'model': 'claude-test', 'effort': 'xhigh'}
        s.assertTrue(s.wk.handoff_snapshot_save(good)); s.assertEqual(s.wk.handoff_snapshot_load(), good)
        s.assertFalse(s.wk.handoff_snapshot_save(dict(good, thread_id='bad')))
        s.assertFalse(s.wk.handoff_snapshot_save(dict(good, history='/etc/passwd')))
        s.assertFalse(s.wk.handoff_snapshot_save(dict(good, model='bad model')))
        s.assertEqual(s.wk.handoff_snapshot_load(), good)

    def test_handoff_note_after_scenario_success_only(s):
        calls = []; s.wk.handoff_sync = lambda target: calls.append(target)
        body = {'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1}
        s.assertTrue(s.p.apply_scenario(body)['ok']); s.assertEqual(calls, ['claude'])
        calls.clear(); s.p.scenario_result = {'ok': False}
        s.assertFalse(s.p.apply_scenario(body)['ok']); s.assertEqual(calls, [])
        calls.clear(); s.p.scenario_result = {'ok': True}
        s.p.apply_scenario({'choices': {'claude': 'orchestrator', 'codex': 'executor'}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertEqual(calls, ['claude', 'codex'])


class ClaudePointer(Base):
    """Указатель беседы Claude (last-claude-session.json) пишет общий код: перед остановкой Claude и перед сменой профиля.
    Раньше его писало только включение профиля третьего агента — без него «Codex → Claude» после PROD отказывал."""

    def setUp(s):
        super().setUp()
        s.hist = Path(s.d)/(TID + '.jsonl'); s.hist.write_text('{}\n')
        s.ns['cfg'] = lambda: {'screen_session': 'testscreen', 'transcripts_dir': s.d}
        s.live = dict(pid='1', thread_id=TID, history=str(s.hist), cwd=s.d, model='claude-test', effort='high', telegram_channel=True, sandbox_root=False, bypass=True)
        s.p.native.claude.capture = lambda: dict(s.live)

    def pointer(s):
        try:
            return json.loads((Path(s.d)/'profile_runtime/last-claude-session.json').read_text())
        except OSError:
            return None

    def test_stop_claude_saves_the_running_conversation(s):
        s.assertIsNone(s.pointer())
        s.assertTrue(s.wk.stop_claude()); s.assertFalse(s.claude[0])
        p = s.pointer(); s.assertEqual((p['thread_id'], p['history'], p['model'], p['telegram_channel']), (TID, str(s.hist), 'claude-test', True))

    def test_side_session_does_not_overwrite_the_pointer(s):
        s.wk.handoff_snapshot_save(dict(s.live, model='main-model'))
        Path(M.SIDE_FLAG).write_text('{}'); s.side[0] = True   # в screen побочная сессия: без плагина Telegram
        s.live['model'] = 'side-model'
        s.assertTrue(s.wk.stop_claude())
        s.assertEqual(s.pointer()['model'], 'main-model')
        s.assertFalse(Path(M.SIDE_FLAG).exists())

    def test_capture_failure_keeps_the_old_pointer(s):
        s.wk.handoff_snapshot_save(dict(s.live))
        def boom(): raise RuntimeError('нет консоли')
        s.p.native.claude.capture = boom
        s.assertTrue(s.wk.stop_claude()); s.assertEqual(s.pointer()['thread_id'], TID)

    def test_profile_switch_saves_the_pointer_while_claude_runs(s):
        r = s.p.apply_scenario({'choices': {'claude': None, 'codex': 'full'}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok']); s.assertEqual(s.pointer()['thread_id'], TID)

    def test_prod_then_codex_then_claude_resumes_the_same_conversation(s):
        # передача на PROD гасит Claude (указатель пишется до остановки), возврат сразу в Codex Claude не будит,
        # выбор Claude Full поднимает ту же беседу из указателя
        s.assertTrue(s.wk.stop_claude())
        staged = []
        def stage(snapshot):
            staged.append(snapshot['thread_id']); s.claude[0] = True; return True
        s.wk.handoff_start_staging = stage
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok'], r); s.assertEqual(staged, [TID]); s.assertIn('scenario', s.p.calls)


class Telegram(Base):
    def test_telegram_block_data(s):
        old = M.tg_me
        M.tg_me = lambda fresh=False: 'test_bot'
        s.addCleanup(setattr, M, 'tg_me', old)
        s.assertEqual(s.wk.tg_public(), {'ok': True, 'status': {'tg_bot': 'test_bot', 'tg_default': '100000001'}})

    def test_bot_name_without_token_is_none(s):
        old = (M.TG_ENV, dict(M._TG_ME))
        s.addCleanup(lambda: (setattr(M, 'TG_ENV', old[0]), M._TG_ME.update(old[1])))
        M.TG_ENV = s.d + '/нет.env'; M._TG_ME.update(ts=0, v='old')
        s.assertIsNone(M.tg_me())


class Api(Base):
    def call(s, path):
        h = object.__new__(s.ns['H']); out = []
        h.path = path; h._authed = lambda: True; h._send = lambda code, body: out.append((code, body))
        h.do_GET()
        return out[0]

    def test_routes(s):
        code, body = s.call('/api/workers')
        s.assertEqual(code, 200); s.assertEqual(set(body['agents']), {'claude', 'prod', 'codex'})
        old = M.tg_me
        M.tg_me = lambda fresh=False: 'b'
        s.addCleanup(setattr, M, 'tg_me', old)
        s.assertEqual(s.call('/api/workers/telegram')[1]['status']['tg_bot'], 'b')
        s.assertEqual(s.call('/api/workers/other'), (404, {'ok': False, 'base': True}))   # чужие пути — дальше по цепочке

    def test_forbidden_without_token(s):
        h = object.__new__(s.ns['H']); out = []
        h.path = '/api/workers'; h._authed = lambda: False; h._send = lambda code, body: out.append(code)
        h.do_GET(); s.assertEqual(out, [403])


class Handoff(Base):
    def setup_folder(s):
        old_timeout, old_delay, old_dir = M.HANDOFF_READY_TIMEOUT, M.HANDOFF_ENTER_DELAY, M.CLAUDE_HISTORY_DIR
        s.addCleanup(setattr, M, 'HANDOFF_READY_TIMEOUT', old_timeout)
        s.addCleanup(setattr, M, 'HANDOFF_ENTER_DELAY', old_delay)
        s.addCleanup(setattr, M, 'CLAUDE_HISTORY_DIR', old_dir)
        M.HANDOFF_READY_TIMEOUT, M.HANDOFF_ENTER_DELAY = 1, 0.01
        M.CLAUDE_HISTORY_DIR = str(Path(s.d) / 'history')   # настоящую папку бесед тесты не читают
        folder = Path(s.d) / 'profile_exchange/codex/outbox/agent_handoff'
        folder.mkdir(parents=True)
        for name in ('claude.md', 'codex.md'):
            (folder / name).write_text(name)
        s.ns['screen_hardcopy'] = lambda: '❯ ready'
        return folder

    def project_setup(s, card='# Карточка\nЦель: тест\n'):
        folder = s.setup_folder()
        proj = folder / 'current_project'
        proj.mkdir()
        if card is not None:
            (proj / 'card.md').write_text(card)
        return folder, proj

    def stuff(s):
        return [x for x in s.runs if x[:2] == ['screen', '-S'] and 'stuff' in x]

    def history_files(s, **files):
        folder = Path(M.CLAUDE_HISTORY_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        for name, (lines, ago) in files.items():
            path = folder / (name + '.jsonl')
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            stamp = time.time() - ago
            os.utime(path, (stamp, stamp))
        return folder

    def codex_console(s):
        calls = []
        class Console:
            def send_input(self, text):
                calls.append(text)
                return True, ''
        s.ns['cc_codex_console'] = Console()
        return calls

    def safe(s, text):
        return text.isascii() and not any(ord(c) in {36, 92, 94, 34, 39, 96} or ord(c) < 32 or ord(c) == 127 for c in text)

    def test_claude_text_is_safe(s):
        folder = s.setup_folder()
        text = s.wk.handoff_sync_text('claude')
        s.assertTrue(s.safe(text)); s.assertIn(str(folder), text)

    def test_unknown_target(s):
        s.setup_folder()
        s.assertFalse(s.wk.handoff_sync('прежний агент'))
        with s.assertRaises(ValueError):
            s.wk.handoff_sync_text('прежний агент')

    def test_project_hint_when_card(s):
        folder, proj = s.project_setup()
        text = s.wk.handoff_sync_text('claude')
        s.assertTrue(s.safe(text))
        s.assertIn('current project folder ' + str(proj), text)
        s.assertIn('card.md first, then owner_last.md', text)
        s.assertNotIn('Read all .md notes', text)
        s.assertNotIn('older than', text)
        t = s.wk.handoff_sync_text('codex')
        s.assertIn('текущего проекта ' + str(proj), t)
        s.assertIn(str(folder) + '/codex.md', t)
        s.assertIn('Архив', t)

    def test_project_hint_without_card_is_old(s):
        s.project_setup(card=None)
        s.assertIn('Read all .md notes', s.wk.handoff_sync_text('claude'))
        s.assertIn('Прочитай все записки', s.wk.handoff_sync_text('codex'))

    def test_project_hint_stale_empty_big(s):
        folder, proj = s.project_setup()
        old = time.time() - 10 * 86400
        os.utime(proj / 'card.md', (old, old))
        s.assertIn('older than 7 days', s.wk.handoff_sync_text('claude'))
        s.assertIn('старше 7 дней', s.wk.handoff_sync_text('codex'))
        (proj / 'card.md').write_text('   \n')
        s.assertIn('card is empty', s.wk.handoff_sync_text('claude'))
        (proj / 'card.md').write_text('x' * 9000)
        s.assertIn('longer than 8000 bytes', s.wk.handoff_sync_text('claude'))
        s.assertTrue(s.wk.handoff_sync_text('claude').isascii())

    def test_project_refresh_and_signature(s):
        folder, proj = s.project_setup()
        tg = '<channel source="plugin:telegram:telegram" chat_id="1" message_id="7" user="d" ts="2026-11-06T10:20:11.000Z">\nпривет, проверка\n</channel>'
        hist = Path(s.d) / 'hist.jsonl'
        hist.write_text(json.dumps(dict(type='user', isMeta=True, timestamp='2026-11-06T10:20:11.838Z', message=dict(role='user', content=tg))) + '\n')
        (Path(s.d) / 'profile_runtime/last-claude-session.json').write_text(json.dumps(dict(history=str(hist))))
        calls = s.codex_console()
        s.assertTrue(s.wk.handoff_sync('codex'))
        text = (proj / 'owner_last.md').read_text()
        s.assertIn('06.11 18:20 · Telegram: привет, проверка', text)  # UTC+8
        s.assertEqual(oct((proj / 'owner_last.md').stat().st_mode & 0o777), '0o644')
        sig = json.loads((Path(s.d) / 'profile_runtime/handoff-sync.json').read_text())['codex']
        names = [x[0] for x in sig]
        s.assertIn('current_project/card.md', names)
        s.assertIn('current_project/owner_last.md', names)
        s.assertNotIn('codex.md', names)
        s.assertIn('claude.md', names)
        s.assertIn('current_project', calls[0])   # подсказка про папку ушла в консоль Codex
        s.assertEqual([x for x in proj.iterdir() if x.name.startswith('.owner_last')], [])  # временный файл убран

    def test_refresh_prefers_fresh_conversation_over_stale_pointer(s):
        """Баг 07.11: после работы на PROD указатель last-claude-session.json смотрит на старую беседу."""
        from test_cc_handoff_tail import tg, say, reply, result
        folder, proj = s.project_setup()
        old = Path(s.d) / 'old.jsonl'
        old.write_text(tg('1', '2026-11-06T10:20:11.000Z', 'старое сообщение') + '\n')
        (Path(s.d) / 'profile_runtime/last-claude-session.json').write_text(json.dumps(dict(history=str(old))))
        s.history_files(prod=([tg('2', '2026-11-07T09:20:00.000Z', 'свежий вопрос с PROD'),
                               reply('2026-11-07T09:20:10.000Z', 'r', 'ответил'), result('2026-11-07T09:20:11.000Z', 'r', 'sent'),
                               say('2026-11-07T09:20:12.000Z', 'готово')], 60))
        s.assertTrue(s.wk.handoff_refresh_owner_last())
        last = (proj / 'owner_last.md').read_text()
        s.assertIn('07.11 17:20 · Telegram: свежий вопрос с PROD', last)
        s.assertNotIn('старое сообщение', last)
        tail = (proj / 'handoff_tail.md').read_text()
        s.assertIn('STATE: FINISHED', tail)
        s.assertIn('свежий вопрос с PROD', tail)
        s.assertEqual(oct((proj / 'handoff_tail.md').stat().st_mode & 0o777), '0o644')
        s.assertEqual([x for x in proj.iterdir() if x.name.startswith('.') and 'tmp' in x.name], [])

    def test_refresh_merges_prod_and_new_conversation(s):
        from test_cc_handoff_tail import tg
        folder, proj = s.project_setup()
        s.history_files(prod=([tg('2', '2026-11-07T09:20:00.000Z', 'вопрос на PROD')], 120),
                        dev=([tg('3', '2026-11-07T09:25:00.000Z', 'вопрос после возврата')], 10))
        s.wk.handoff_refresh_owner_last()
        last = (proj / 'owner_last.md').read_text()
        s.assertIn('вопрос на PROD', last)
        s.assertIn('вопрос после возврата', last)
        s.assertLess(last.index('вопрос на PROD'), last.index('вопрос после возврата'))

    def test_service_inserts_are_not_owner_messages(s):
        from test_cc_handoff_tail import tg
        folder, proj = s.project_setup()
        note = json.dumps(dict(type='user', timestamp='2026-11-07T09:21:00.000Z', message=dict(role='user', content='<task-notification><task-id>x</task-id></task-notification>')))
        resumed = json.dumps(dict(type='user', timestamp='2026-11-07T09:22:00.000Z', message=dict(role='user', content='This session is being continued from a previous conversation')))
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'настоящее'), note, resumed], 5))
        s.wk.handoff_refresh_owner_last()
        last = (proj / 'owner_last.md').read_text()
        s.assertIn('настоящее', last)
        s.assertNotIn('task-notification', last)
        s.assertNotIn('This session is being continued', last)

    def test_sync_text_continues_when_unfinished(s):
        from test_cc_handoff_tail import tg
        folder, proj = s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'доделай правку')], 5))
        s.wk.handoff_refresh_owner_last()
        s.assertEqual(s.wk.handoff_tail_state(), 'unfinished')
        text = s.wk.handoff_sync_text('claude')
        s.assertTrue(s.safe(text))
        s.assertIn('card.md first, then owner_last.md, then handoff_tail.md', text)
        s.assertIn('Continue from the last step', text)
        s.assertNotIn('Do not start any work', text)
        s.assertIn('Продолжи с последнего шага', s.wk.handoff_sync_text('codex'))

    def test_sync_text_stays_quiet_when_finished(s):
        from test_cc_handoff_tail import tg, say, reply, result
        folder, proj = s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'вопрос'), reply('2026-11-07T09:20:10.000Z', 'r', 'ответ'),
                            result('2026-11-07T09:20:11.000Z', 'r', 'sent'), say('2026-11-07T09:20:12.000Z', 'готово')], 5))
        s.wk.handoff_refresh_owner_last()
        s.assertEqual(s.wk.handoff_tail_state(), 'finished')
        text = s.wk.handoff_sync_text('claude')
        s.assertIn('Do not start any work', text)
        s.assertNotIn('Continue from the last step', text)
        s.assertIn('Не начинай работу', s.wk.handoff_sync_text('codex'))

    def test_card_behind_conversation_is_reported(s):
        from test_cc_handoff_tail import tg
        folder, proj = s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'вопрос')], 5))
        old = time.time() - 3600
        os.utime(proj / 'card.md', (old, old))
        s.wk.handoff_refresh_owner_last()
        s.assertIn('behind the conversation', s.wk.handoff_sync_text('claude'))
        s.assertIn('отстаёт от беседы', s.wk.handoff_sync_text('codex'))
        os.utime(proj / 'card.md', None)
        s.assertNotIn('behind the conversation', s.wk.handoff_sync_text('claude'))

    def test_sync_delivers_unfinished_rule_to_console(s):
        from test_cc_handoff_tail import tg
        s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'доделай')], 5))
        s.assertTrue(s.wk.handoff_sync('claude'))
        calls = s.stuff()
        s.assertIn('Continue from the last step', calls[0][-1])
        s.assertEqual(calls[1][-1], '\r')

    def test_project_no_card_no_refresh(s):
        folder, proj = s.project_setup(card=None)
        s.assertFalse(s.wk.handoff_refresh_owner_last())
        s.assertFalse((proj / 'owner_last.md').exists())
        s.assertFalse(any(x[0].startswith('current_project') for x in s.wk.handoff_sync_signature('claude')))

    def test_claude_screen_delivery(s):
        s.setup_folder()
        s.assertTrue(s.wk.handoff_sync('claude'))
        calls = s.stuff()
        s.assertEqual(len(calls), 2)
        s.assertEqual(calls[0][:7], ['screen', '-S', 'testscreen', '-p', '0', '-X', 'stuff'])
        s.assertEqual(calls[0][-1], s.wk.handoff_sync_text('claude'))
        s.assertEqual(calls[1][-1], '\r')
        s.assertEqual(s.sent, [])

    def test_claude_timeout(s):
        s.setup_folder()
        s.ns['screen_hardcopy'] = lambda: 'loading'
        s.assertFalse(s.wk.handoff_sync('claude'))
        s.assertEqual(s.stuff(), [])
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())

    def test_deduplicates_other_notes(s):
        folder = s.setup_folder()
        s.assertTrue(s.wk.handoff_sync('claude'))
        s.assertFalse(s.wk.handoff_sync('claude'))
        (folder / 'claude.md').write_text('own note changed significantly')
        s.assertFalse(s.wk.handoff_sync('claude'))
        s.assertEqual(len(s.stuff()), 2)
        (folder / 'codex.md').write_text('another note with changed length')
        s.assertTrue(s.wk.handoff_sync('claude'))
        s.assertEqual(len(s.stuff()), 4)

    def test_disabled(s):
        s.setup_folder()
        (Path(s.d) / 'handoff_sync.disabled').touch()
        s.assertFalse(s.wk.handoff_sync('claude'))
        s.assertEqual(s.stuff(), [])
        s.assertEqual(s.sent, [])

    def test_codex_delivery(s):
        s.setup_folder()
        calls = s.codex_console()
        s.assertTrue(s.wk.handoff_sync('codex'))
        s.assertFalse(s.wk.handoff_sync('codex'))
        s.assertEqual(len(calls), 1)
        s.assertIn('[Панель]', calls[0])
        s.assertIn('Прочитай', calls[0])
        s.assertEqual(s.sent, [])

    def test_codex_missing_module(s):
        s.setup_folder()
        s.ns.pop('cc_codex_console', None)
        s.assertFalse(s.wk.handoff_sync('codex'))
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())

    def test_catches_sender_exception(s):
        s.setup_folder()
        class Console:
            def send_input(self, text):
                raise RuntimeError('test')
        s.ns['cc_codex_console'] = Console()
        s.assertFalse(s.wk.handoff_sync('codex'))
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())
        s.assertEqual(s.sent, [])

    def test_lock_busy(s):
        s.setup_folder()
        calls = s.codex_console()
        s.wk._sync_lock = threading.Lock()
        s.wk._sync_lock.acquire()
        try:
            s.assertFalse(s.wk.handoff_sync('codex'))
        finally:
            s.wk._sync_lock.release()
        s.assertEqual(calls, [])

    def test_rejects_unsafe_claude_input(s):
        s.setup_folder()
        for c in (chr(36), chr(92), chr(94), chr(34), chr(39), chr(96), '\n', 'я'):
            s.assertFalse(s.wk.handoff_send_claude('test' + c))
        s.assertEqual(s.stuff(), [])

    def test_send_failure_does_not_save(s):
        s.setup_folder()
        s.wk.handoff_send_claude = lambda text: False
        s.assertFalse(s.wk.handoff_sync('claude'))
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())

    def test_empty_notes(s):
        folder = s.setup_folder()
        (folder / 'codex.md').unlink()
        s.assertFalse(s.wk.handoff_sync('claude'))
        s.assertEqual(s.stuff(), [])


def at(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=IRK)


class OwnerParse(unittest.TestCase):
    """owner_last.md: последние сообщения владельца из истории Claude."""
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


def LV(level="hard", **kw):
    """Состояние пауз как отдаёт pause_ctl.level_state()."""
    d = {"ok": True, "level": level, "stale": False, "pause": {"override": False}, "line": "acc1 91%, acc2 96%",
         "nearest": {"resets_at": "2026-11-01T08:00:00Z"}}
    d.update(kw)
    return d


class ClaudeStatus(unittest.TestCase):
    """Расчёт «лимиты Claude кончились» для доступности в профилях (cc_profiles.claude_status)."""

    def setUp(self):
        import cc_profiles
        self.f = cc_profiles.claude_status

    def test_pause_levels_mean_down(self):
        self.assertEqual(self.f(LV("hard")), "down")
        self.assertEqual(self.f(LV("week")), "down")

    def test_working_levels_mean_up(self):
        for lvl in ("none", "gate", "weekrisk", "manual"):
            self.assertEqual(self.f(LV(lvl)), "up", lvl)

    def test_manual_pick_and_disabled_pause_are_up(self):
        self.assertEqual(self.f(LV("hard", manual={"account": "a"})), "up")
        self.assertEqual(self.f(LV("hard", pause={"override": True})), "up")

    def test_no_trust_in_stale_or_broken_snapshot(self):
        for lv in (LV("hard", stale=True), {"ok": False, "level": "none"}, {}, None, "x", {"pause": {}}):
            self.assertEqual(self.f(lv), "unknown", lv)


class OldState(unittest.TestCase):
    """Записи прежних версий с убранными режимами читаются как обычный профиль, без падений."""

    def test_profile_state_with_old_service_and_choices(self):
        from cc_profile_state import ProfileState
        raw = ProfileState().export()
        raw.update(service={'engine': 'codex', 'kind': 'reserve', 'source': 'manual'},
                   restore={'selected': {'claude': 'claude_solo_full', 'codex': 'codex_solo_full'},
                            'last_solo': {'claude': 'claude_solo_full', 'codex': 'codex_solo_full'}, 'leader': None,
                            'manual_choices': {'claude': 'full', 'codex': None}},
                   manual_choices={'claude': None, 'codex': 'reserve'})
        st = ProfileState.from_data(raw)
        pub = st.public()
        s = self
        s.assertIsNone(pub['service'])
        s.assertEqual(pub['manual_scenario']['choices'], {'claude': 'full', 'codex': None})   # прежний сценарий: Claude Full
        s.assertEqual((pub['engines']['claude']['role'], pub['engines']['claude']['selected']), ('solo', 'claude_solo_full'))
        s.assertNotIn('reserve', json.dumps(pub))

    def test_unknown_selected_profile_becomes_full(self):
        from cc_profile_state import ProfileState
        raw = ProfileState().export()
        raw['selected'] = {'claude': 'gone_mode', 'codex': 'reserve'}
        st = ProfileState.from_data(raw)
        s = self
        s.assertEqual(st.selected, {'claude': 'claude_solo_full', 'codex': 'codex_solo_full'})

    def test_codex_bridge_old_profile_reads_as_not_chosen(self):
        import cc_codex_bridge as B
        s = {'profile': 'reserve', 'mode': 'self', 'access': 'write', 'task_rights': 'dev'}
        self.assertEqual(B.active_profile(s), '')
        self.assertEqual(B.active_profile(dict(s, profile='codex_solo_full', access='full')), 'codex_solo_full')
        ok, _ = B.apply_profile('reserve')
        self.assertFalse(ok)   # «такого профиля нет» — без исключения

    def test_old_pause_kind_is_an_ordinary_pause(self):
        import pause_ctl
        d = tempfile.mkdtemp()
        names = ('STATE', 'SNAP', 'CONFIG', 'CC_STATE')
        old = {k: getattr(pause_ctl, k) for k in names}
        self.addCleanup(lambda: [setattr(pause_ctl, k, v) for k, v in old.items()])
        for k, f in zip(names, ('pause_state.json', 'snapshot.json', 'config.json', 'state.json')):
            setattr(pause_ctl, k, os.path.join(d, f))
        Path(pause_ctl.STATE).write_text(json.dumps({'active': True, 'kind': 'reserve', 'since': 1, 'resume_at': 0}))
        p = pause_ctl.level_state()['pause']
        self.assertTrue(p['active'])
        self.assertNotIn('grace', p)   # отсчёта «доделывает» прежнего режима нет: обычная пауза
        self.assertTrue(pause_ctl.release_for_remote())   # и снимается при передаче на PROD, как любая пауза по лимитам


class Page(unittest.TestCase):
    """Строки интерфейса модуля: шапка, окна значков, меню профиля на плитках, общие настройки."""

    def setUp(self):
        self.src = open(M.__file__, encoding='utf-8').read()
        i = self.src.index("function richPop(k,anchor,rm)")
        self.body = self.src[i:self.src.index("function agentPop(k,anchor)")]

    def test_no_third_agent_anywhere(self):
        low = self.src.lower()
        for word in ('no' + 'tion', 'na' + 'i-', 'na' + 'i_', "'na" + "i"):
            self.assertNotIn(word, low, word)

    def test_header_three_agents(self):
        self.assertIn("var AGS=[['claude','Claude DEV','DEV'],['prod','Claude PROD','PROD'],['codex','Codex','Codex']];", M.UI)
        self.assertIn("bar.id='wkAgents'", M.UI)
        self.assertIn("+'workers'", M.UI)   # опрос GET /api/workers
        self.assertIn("new CustomEvent('wk-state'", M.UI)
        self.assertIn('window.wkReload=load;', M.UI)

    def test_updates_block_is_first_in_general_settings(self):
        # «Обновления» — самым первым блоком окна «Общие настройки»
        self.assertIn("[upd,cl,cx,tg].forEach(function(x){if(x)c.append(x)});", M.CFG_UI)

    def test_general_settings_blocks_and_instructions(self):
        ui = M.CFG_UI
        for k in ('wkGenClaude', 'wkGenCodex', 'wkGenTg', 'wkTgCx'):
            self.assertIn(k, ui)
        for k in ('/telegram:configure', '/telegram:access pair', '@BotFather', '@userinfobot', 'Получить ссылку для входа', 'по коду устройства'):
            self.assertIn(k, ui)
        self.assertEqual(ui.count('Подробно: что, где, как и почему'), 3)  # Claude, Codex, Telegram
        self.assertIn('#scrim:not([data-view="general"]) .wk-gen.claude', ui)
        self.assertIn("call('telegram')", ui)   # бот и чат — GET /api/workers/telegram

    def test_auto_confirm_is_inside_the_tile_popup(self):
        # подтверждение «Включить/Выключить авто» — в самом окне плитки, не отдельным окном под ним (владелец 62664)
        self.assertIn("c.className='wk-cfm'", self.src)
        self.assertIn("c.querySelector('.wk-cn').onclick=function(){c.style.display='none';row.style.display='';placePop();setTimeout(function(){c.remove()},0)};", self.src)
        import cc_overview
        self.assertIn(".fleet-ask{z-index:100000}", cc_overview.CSS)

    def test_ghost_tile_ui_is_in_the_page(self):
        for part in ("function linkPop(k,anchor){", "function ghostMark(){", "'ag-unlinked-'+a[0]", ".wk-seg.s-unlinked{",
                     "html.ag-unlinked-codex #ctCodex",
                     "if(agState(s.dataset.ag).state==='unlinked'){linkPop(s.dataset.ag,s);return}",
                     "if(un!==unSig){unSig=un;try{if(typeof consTabs==='function')consTabs()}catch(_){}}"):
            self.assertIn(part, self.src, part)

    def test_button_row_wraps_and_text_never_breaks_inside_a_button(self):
        self.assertIn(".wk-pop .wk-row{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}", self.src)
        self.assertIn(".wk-pop button{height:32px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", self.src)

    def test_prod_popup_is_drawn_like_the_reference(self):
        for part in ('class="wk-ph"', 'class="wk-pi ', 'class="wk-sw"', 'role="switch" aria-checked="', "pp.classList.add('ag-'+k,'rich')"):
            self.assertIn(part, self.src)
        self.assertIn(".wk-pop.ag-prod .wk-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px}", self.src)
        self.assertIn(".wk-pop.ag-prod button.wk-yes{grid-column:1/-1;height:40px;background:#6f59f9", self.src)
        self.assertIn(".wk-pop.rich .wk-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px}", self.src)
        self.assertIn("({claude:'Claude DEV',prod:'Claude PROD',codex:'Codex'})[k])+(gp.text?' - '+esc(gp.text):'')", self.src)
        self.assertIn(".wk-auto[aria-checked=\"true\"] .wk-sw::after{transform:translateX(11px)}", self.src)

    def test_switch_shows_the_real_auto_state(self):
        body = self.body
        self.assertIn("ao=!!((rm.auto&&rm.auto()||{}).enabled)", body)
        self.assertIn("aria-checked=\"'+ao+'\"", body)
        self.assertIn('<span class="wk-bl">Включить авто</span>', body)
        self.assertNotIn("'Выключить авто'", body)
        self.assertIn("thr=thrNow()", body)
        self.assertIn("'% лимита работа сама перейдёт на второй аккаунт.'", body)
        self.assertIn("'% лимита работа сама не перейдёт.'", body)
        self.assertIn("class=\"wk-lnk2\">Изменить порог</a>", body)
        self.assertIn("document.getElementById('gear')", body)
        self.assertIn("typeof THR==='number'", self.src)
        self.assertIn("au.onclick=function(){var on=!((rm.auto()||{}).enabled)", body)

    def test_tail_points_at_the_pressed_icon(self):
        self.assertIn("tl.className='wk-tail'", self.src)
        self.assertIn("t.style.left=(Math.max(20,Math.min(r.left+r.width/2-left,w-20))-6)+'px'", self.src)
        self.assertIn("function openPop(html,wide,anchor,cls)", self.src)
        self.assertIn("</div>',false,anchor,'ag-'+k+' rich');", self.src)
        self.assertIn("sb.style.overflowY='auto'", self.src)
        self.assertIn("'<div class=\"wk-pb\">'+html+'</div>'", self.src)
        self.assertIn("pop.classList.toggle('up',up)", self.src)
        self.assertIn(".wk-pop:not(.up) .wk-tail{top:-7px;border-right:0;border-bottom:0}", self.src)
        self.assertIn(".wk-pop.up .wk-tail{bottom:-7px;border-left:0;border-top:0}", self.src)

    def test_pressed_icon_is_highlighted_and_released_on_close(self):
        self.assertIn("popAnchor.classList.add('wk-pressed')", self.src)
        self.assertIn("popAnchor.classList.remove('wk-pressed')", self.src)
        self.assertIn(".wk-seg.wk-pressed{", self.src)

    def test_every_icon_opens_the_same_window(self):
        i = self.src.index("function agentPop(k,anchor)")
        self.assertIn("(k==='prod'||k==='claude'||k==='codex'))return richPop(k,anchor,window.fleetRemote)", self.src[i:i + 260])
        self.assertIn("pair=k==='claude'||k==='prod'", self.body)
        self.assertIn("(pair?'<button type=\"button\" class=\"wk-auto\"", self.body)

    def test_handoff_button_target_rule(self):
        self.assertIn("act=wk===own,hi=act?null:rm.handInfo(own,md)", self.body)
        self.assertIn("(act?hand3(own,md,rm):'<button type=\"button\" class=\"wk-yes\"", self.body)
        self.assertIn("rm.hand(own,anchor)", self.body)
        self.assertIn("(hi.dis?' disabled':'')", self.body)

    def test_active_model_gets_buttons_for_the_other_two(self):
        i = self.src.index("function hand3(own,md,rm)")
        f = self.src[i:self.src.index("function richPop(k,anchor,rm)")]
        self.assertIn("['dev','prod','codex'].filter(function(t){return t!==own})", f)
        self.assertIn("rm.handInfo(t,md)", f)
        self.assertIn('class="wk-h3n"', f)
        self.assertIn("pp.querySelectorAll('.wk-h3').forEach(function(b){b.onclick=function(){var t=this.dataset.t;closePop();rm.hand(t,anchor)}});", self.body)
        self.assertIn(".wk-pop.rich .wk-hand3{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}", self.src)

    def test_profile_picker_stays_reachable_as_a_link(self):
        self.assertIn('class="wk-lnk">Выборе профиля</a>', self.body)
        self.assertIn("document.getElementById('cxBtn')", self.body)

    def test_remote_ui_exports_what_the_window_needs(self):
        import cc_remote_ui as U
        self.assertIn("handInfo:handInfo,hand:hOpen", U.JS)
        self.assertIn("window.wkReload&&window.wkReload()", U.JS)

    def test_tile_profile_menu(self):
        import cc_overview
        js = cc_overview.JS
        self.assertIn("const TPN={claude:'Claude DEV',codex:'Codex'}", js)
        self.assertIn("const tpOpts=()=>{const cur=manualCurrent();return TPO[tpEng].map(o=>({...o,cur:manualSame(o.draft,cur),why:''}))};", js)
        self.assertIn("await tpApply(eng,{claude:o.draft.claude,codex:o.draft.codex},mirrorState.revision,'');", js)
        self.assertIn('.tp-pop{--tp-c:var(--fleet-claude)}', cc_overview.CSS)
        self.assertFalse(hasattr(M, 'PICKER_JS'))

    def test_console_auto_follow_and_codex_tab(self):
        self.assertIn("var ids={claude:'ctClaude',prod:'ctProd',codex:'ctCodex'};", M.UI)
        self.assertIn("window.ccConsAuto={pick:pickWorking,tick:tick", M.UI)
        import cc_limits as L
        self.assertIn("$('#ctProd').hidden=!pv;$('#ctCodex').hidden=!av;", L.PAGE)   # вкладка Codex прячется, пока он недоступен
        self.assertNotIn('showCodex', M.UI)   # видимость вкладки решает одно место — consTabs()
        self.assertIn("if(btn && btn.hidden && typeof consTabs==='function') consTabs();", M.UI)

    def test_scripts_are_valid_javascript(self):
        import re, shutil, subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('нет node')
        d = tempfile.mkdtemp()
        parts = re.findall(r'<script[^>]*>(.*?)</script>', M.UI + M.CFG_UI, re.S)
        for i, js in enumerate(parts):
            p = os.path.join(d, '%d.js' % i)
            open(p, 'w', encoding='utf-8').write(js)
            r = subprocess.run([node, '--check', p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_whole_page_scripts_are_valid_javascript(self):
        # страница панели целиком (cc_limits + cc_overview + cc_workers + cc_remote_ui): каждый встроенный скрипт разбирается node
        import re, shutil, subprocess, sys
        node = shutil.which('node')
        if not node:
            self.skipTest('нет node')
        if 'cc_limits' not in sys.modules:
            tmp = tempfile.mkdtemp(prefix='ccwk_')
            os.environ.setdefault('CC_LIMITS_BASE', os.path.join(tmp, 'base'))
            os.environ.setdefault('CC_LIMITS_PROFILES', os.path.join(tmp, 'profiles'))
            os.makedirs(os.environ['CC_LIMITS_BASE'], exist_ok=True)
        import cc_limits as L
        page = L.PAGE
        for mark in ('id="wkScript"', 'id="wkCfgScript"', 'const TPN='):
            self.assertIn(mark, page)   # общая механика и меню профиля плиток — в настоящей странице
        d = tempfile.mkdtemp()
        blocks = re.findall(r'<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>', page, re.S)
        n = 0
        for attrs, js in blocks:
            if 'type=' in attrs and 'javascript' not in attrs and 'module' not in attrs:
                continue
            p = os.path.join(d, '%d.js' % n); n += 1
            open(p, 'w', encoding='utf-8').write(js)
            r = subprocess.run([node, '--check', p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertGreater(n, 3)


if __name__ == '__main__':
    unittest.main()
