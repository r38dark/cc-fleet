import json, tempfile, unittest, time
from pathlib import Path
import cc_notion_ai as M

class Console:
    def __init__(s): s.PLAN = lambda: ('danger-full-access', '/opt/codex-trial', 'gpt1')
class Bridge:
    def load(s): return {'mode': 'self', 'access': 'full', 'workdir': '/opt/codex-trial', 'slot': 'gpt1'}
    def plan(s, c): return ({'full': 'danger-full-access', 'write': 'workspace-write'}[c['access']], c['workdir'])
    def project_dir(s): return '/opt/proj'
class Claude:
    def __init__(s, t): s.t = t; s.applied = []
    def capture(s): return dict(pid='1', thread_id='a'*8+'-aaaa-aaaa-aaaa-'+'a'*12, history=str(Path(s.t.d)/'h.jsonl'), cwd='/root', model='opus', effort='high')
    def apply(s, snap, pol, prompt): s.applied.append((snap, pol, prompt)); s.t.claude[0] = True
class Native:
    def __init__(s, t):
        s.b = False; s.codex = Console(); s.bridge = Bridge(); s.claude = Claude(t); s.claude_work = t.d + '/work'; s.claude_cwd = '/root'
        s.ensures = 0; s.pauses = []; s.ensure_ok = True
    def busy(s): return s.b
    def prompt(s, state, e): return 'orig-' + e
    def ensure_codex(s): s.ensures += 1; return (s.ensure_ok, '' if s.ensure_ok else 'занята')
    def _codex_pause(s, on): s.pauses.append(on)
class State:
    def __init__(s): s.manual_choices = {'claude': None, 'codex': 'full'}
    def export(s): return dict(s.manual_choices)
    @classmethod
    def from_data(cls, d, clock): x = cls(); x.manual_choices = dict(d); return x
    def apply_scenario(s, choices, confirm='', revision=None):
        if 'full' in (choices or {}).values() and confirm != 'подтверждаю': return {'ok': False, 'confirmation_required': True, 'word': 'подтверждаю'}
        return {'ok': True}
class Tasks:
    def __init__(s): s.asked = []
    def ask(s, e, text): s.asked.append((e, text)); return 'РЕЗУЛЬТАТ ' + e
class Profiles:
    def __init__(s, t):
        s.transitioning = False; s.pending = Path(t.d)/'pending.json'; s.native = Native(t); s.calls = []
        s.labels = {'claude': 'Claude · не участвует', 'codex': 'Codex Full'}; s.avail = {'claude': {'status': 'up'}, 'codex': {'status': 'up'}}
        s.state = State(); s.clock = time.time; s.tasks = Tasks()
    def update_active(s): return False
    def paused(s, e): return e == 'claude'
    def input_allowed(s, e): return not s.paused(e)
    def public(s): return {'engines': {e: {'label': l, 'role': 'solo'} for e, l in s.labels.items()}}
    def transition(s, c, m, force=None, recover_blocked=False): s.calls.append(m); return {'ok': True}
    def action(s, e, a, b): s.calls.append('action'); return {'ok': True}
    def apply_scenario(s, b): s.calls.append('scenario'); return {'ok': True}
    def exchange(s, e): return Path('/ex')/e
class H:
    def do_GET(s): pass
    def do_POST(s): pass

class T(unittest.TestCase):
    def setUp(s):
        s.d = tempfile.mkdtemp(); s.sent = []; s.runs = []; s.tg = []; s.posts = []
        (Path(s.d)/'profile_runtime').mkdir(); (Path(s.d)/'profile_runtime/claude-policy.json').write_text('{"their":1}')
        (Path(s.d)/'h.jsonl').write_text('')
        s.ns = {'BASE': s.d, 'cfg': lambda: {'screen_session': 'darqai'}, 'tg_notify': lambda t: s.sent.append(('claude', t)), 'H': H,
                'PAGE': '<html><head></head><body>x\n mirrorLoad();\n\n loadRotation();\n</body></html>', 'transcripts_dir': lambda: s.d}
        class B: BRIDGE = type('X', (), {'send': lambda self, t: s.sent.append(('codex', t))})()
        s.ns['cc_codex_bridge'] = B
        s.claude = [True]
        def run(args, timeout=30):
            s.runs.append(args)
            if args[:2] == ['screen', '-ls']: return 0, ('\t123.darqai\t(Detached)\n' if s.claude[0] else 'No Sockets')
            if args[:2] == ['screen', '-S'] and 'quit' in args: s.claude[0] = False; return 0, ''
            if args[0] == 'pgrep': return (0 if s.claude[0] else 1), ''
            if args[0] == 'systemd-run': s.claude[0] = True; return 0, ''
            if args[:2] == ['systemctl', 'is-active']: return 0, 'active\n'
            return 0, ''
        M._run = run; M.INBOX = s.d + '/inbox'
        M.NotionAI._later = lambda self, fn, *a: fn(*a)
        M.NotionAI.tg_api = lambda self, method, payload: (s.tg.append((method, payload)), {'result': {'message_id': 77}})[1]
        M.NotionAI.tg_chats = lambda self: ['262033135']
        M.NotionAI.post_chat = lambda self, text: s.posts.append(text)
        s.retries = []; M.NotionAI._codex_restore_retry = lambda self, data: s.retries.append(data)
        s.p = Profiles(s); s.nai = M.install(s.ns, s.p)
    def wait_step(s, status):
        for _ in range(100):
            if s.nai.step and s.nai.step['status'] == status: return
            time.sleep(0.02)
        s.fail('step status %s != %s' % (s.nai.step and s.nai.step['status'], status))

    def test_page_injected(s):
        page = s.ns['PAGE']; s.assertIn('naiPickerRepaint', page); s.assertIn('naiPickerStyle', page); s.assertIn('id="naiScript"', page)
        s.assertEqual(M.inject(page), page)
    def test_full_on_off(s):
        r = s.nai.on(); s.assertTrue(r['ok'], r); s.assertTrue(s.p.paused('claude') and s.p.paused('codex'))
        s.assertEqual(s.nai.kind(), 'full'); s.assertFalse(s.claude[0]); s.assertEqual(s.p.native.ensures, 0)
        s.assertEqual(s.p.native.codex.PLAN()[0], 'danger-full-access')
        r = s.nai.off(); s.assertTrue(r['ok']); s.assertTrue(s.claude[0]); s.assertFalse(s.p.paused('codex'))
    def test_orch_codex(s):
        r = s.nai.on(kind='orchestrator', follower='codex'); s.assertTrue(r['ok'], r)
        s.assertEqual(s.nai.title(), 'Notion AI → Codex'); s.assertFalse(s.p.paused('codex')); s.assertTrue(s.p.paused('claude'))
        s.assertEqual(s.p.native.codex.PLAN(), ('workspace-write', '/opt/codex-trial', 'gpt1'))
        s.assertIn('исполнитель Notion AI', s.p.native.prompt(None, 'codex')); s.assertEqual(s.p.native.prompt(None, 'claude'), 'orig-claude')
        s.assertEqual(s.p.native.ensures, 1); s.assertFalse(s.claude[0])
        pub = s.p.public(); s.assertEqual(pub['engines']['codex']['label'], 'Codex · исполнитель Notion AI'); s.assertEqual(pub['notion_ai']['follower'], 'codex')
        s.assertTrue(any(c == 'codex' and 'исполнитель' in t for c, t in s.sent))
        r = s.nai.off(); s.assertTrue(r['ok']); s.assertEqual(s.p.native.ensures, 2); s.assertEqual(s.p.native.codex.PLAN()[0], 'danger-full-access')
    def test_orch_codex_fail_rolls_back(s):
        s.p.native.ensure_ok = False; r = s.nai.on(kind='orchestrator', follower='codex')
        s.assertFalse(r['ok']); s.assertFalse(s.nai.active()); s.assertTrue(s.claude[0]); s.assertIn('Codex не принял', r['message']); s.assertEqual(len(s.retries), 1)
    def test_orch_claude_removed(s):
        r = s.nai.on(kind='orchestrator', follower='claude'); s.assertFalse(r['ok']); s.assertIn('убран', r['message']); s.assertFalse(s.nai.active())
        s.assertTrue(s.claude[0]); s.assertEqual(s.p.native.claude.applied, [])
    def test_switch_chain(s):
        s.assertTrue(s.nai.on()['ok']); s.assertTrue(s.nai.on(kind='orchestrator', follower='codex')['ok']); s.assertEqual(s.p.native.ensures, 1)
        r = s.nai.on(kind='orchestrator', follower='claude'); s.assertFalse(r['ok']); s.assertEqual(s.nai.follower(), 'codex')
        s.assertFalse(s.claude[0]); s.assertTrue(s.nai.on()['ok']); s.assertFalse(s.claude[0]); s.assertEqual(s.nai.kind(), 'full')
        s.assertEqual((Path(s.d)/'profile_runtime/claude-policy.json').read_text(), '{"their":1}')
    def test_agents(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'paused', 'label': 'Claude · не участвует'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
        s.p.state = St(); a = s.nai.agents()
        s.assertEqual((a['claude']['state'], a['codex']['state'], a['notion']['state']), ('off', 'run', 'off'))
        s.p.avail['claude']['status'] = 'down'; s.assertEqual(s.nai.agents()['claude']['state'], 'limit')
        s.p.avail['claude']['status'] = 'up'; s.nai.on(); a = s.nai.agents()
        s.assertEqual((a['claude']['state'], a['codex']['state'], a['notion']['state']), ('pause', 'pause', 'run'))
        s.nai.on(kind='orchestrator', follower='codex'); a = s.nai.agents()
        s.assertEqual((a['codex']['state'], a['codex']['text'], a['notion']['state']), ('exec', 'исполнитель', 'lead'))
        s.assertIn('agents', s.nai.public())
    def test_steps(s):
        s.nai.on(); r = s.nai.step_new('сделай X'); s.assertFalse(r['ok'])
        s.nai.on(kind='orchestrator', follower='codex'); r = s.nai.step_new('Шаг 1: проверь Y', 'dev'); s.assertTrue(r['ok'], r)
        s.assertEqual(s.tg[-1][0], 'sendMessage'); s.assertIn('nai:ok:' + r['id'], json.dumps(s.tg[-1][1]))
        s.assertFalse(s.nai.step_confirm('bad', True)['ok'])
        r2 = s.nai.step_confirm(r['id'], True, 'telegram'); s.assertTrue(r2['ok'], r2); s.wait_step('done')
        e, text = s.p.tasks.asked[-1]; s.assertEqual(e, 'codex'); s.assertIn('Права шага: дев', text); s.assertIn('Шаг 1', text)
        s.assertEqual(Path(s.nai.step['result_path']).read_text().count('РЕЗУЛЬТАТ codex'), 1)
        s.assertTrue(any('[Результат шага' in t for t in s.posts)); s.assertTrue(any(m == 'editMessageText' for m, _ in s.tg))
        r = s.nai.step_new('Шаг 2'); s.assertTrue(r['ok']); r3 = s.nai.step_new('Шаг 2б'); s.assertTrue(r3['ok'])
        s.assertTrue(s.nai.step_confirm(r3['id'], False)['ok']); s.assertEqual(s.nai.step['status'], 'rejected'); s.assertTrue(any('отклонён' in t for t in s.posts))
    def test_step_cancel_on_switch(s):
        s.nai.on(kind='orchestrator', follower='codex'); s.nai.step_new('Шаг'); s.nai.on(); s.assertEqual(s.nai.step['status'], 'cancelled')
    def test_scenario_wrapper(s):
        s.nai.on(); r = s.p.apply_scenario({'choices': {'claude': None, 'codex': 'full'}, 'revision': 1})
        s.assertTrue(r.get('confirmation_required')); s.assertTrue(s.nai.active())
        r = s.p.apply_scenario({'choices': {'claude': None, 'codex': 'full'}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok']); s.assertFalse(s.nai.active()); s.assertNotIn('scenario', s.p.calls)
        s.nai.on(); r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertTrue(r['ok']); s.assertFalse(s.nai.active()); s.assertIn('scenario', s.p.calls)
    def test_auto_blocked(s):
        s.nai.on(); s.assertFalse(s.p.transition('X', M.AUTO_MESSAGE)['ok'])

if __name__ == '__main__':
    unittest.main()


class TestViewApi(unittest.TestCase):
    """[notion-ai] /api/notion-ai/view: отмечает интерес к окну, режет хвост, idle → starting."""
    def test_view_public(self):
        import tempfile, os, json, time
        import cc_notion_ai as M
        d = tempfile.mkdtemp(); old = (M.VIEW_FILE, M.VIEW_WANT)
        M.VIEW_FILE, M.VIEW_WANT = d + '/v.json', d + '/v.want'
        try:
            self.assertEqual(M.view_public()['state'], 'starting')
            self.assertTrue(os.path.exists(M.VIEW_WANT))
            json.dump(dict(ok=True, state='idle', message='x', running=False, rows=[dict(id=str(i), kind='ai', text='t') for i in range(200)], ts=time.time()), open(M.VIEW_FILE, 'w'))
            os.utime(M.VIEW_WANT, (0, 0))
            r = M.view_public()
            self.assertEqual((r['state'], len(r['rows']), r['rows'][-1]['id']), ('starting', 120, '199'))
            self.assertLess(time.time() - os.path.getmtime(M.VIEW_WANT), 5)
        finally:
            M.VIEW_FILE, M.VIEW_WANT = old


class TestChatSend(unittest.TestCase):
    """[notion-ai] POST /api/notion-ai/send: проверка текста, метка [Панель hh:mm], повтор по request_id."""
    def test_send(self):
        import cc_notion_ai as M
        calls = []
        def fake(path, data=None, timeout=20):
            calls.append((path, data))
            return {'id': 'abcdef12', 'status': 'queued'} if path == '/post' else {'status': 'done'}
        old = M._delegate; M._delegate = fake
        try:
            self.assertFalse(M.chat_send('   ')['ok'])
            self.assertFalse(M.chat_send('x' * 4001)['ok'])
            r = M.chat_send(' привет ', 'rid-1'); self.assertTrue(r['ok']); self.assertEqual(r['id'], 'abcdef12')
            self.assertRegex(calls[-1][1]['text'], r'^\[Панель \d\d:\d\d\] привет\n\n— из панели балансера')
            n = len(calls); self.assertTrue(M.chat_send('привет', 'rid-1')['ok']); self.assertEqual(len(calls), n)
            self.assertEqual(M.chat_send_status('abcdef12')['status'], 'done')
            self.assertFalse(M.chat_send_status('../etc')['ok'])
        finally:
            M._delegate = old


class TestCfg(unittest.TestCase):
    """[notion-ai] v3: настройки Notion AI (⚙ Общие настройки → Notion AI)."""
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.old = (M.CFG_FILE, M.AUTH_KEYS, M._run)
        M.CFG_FILE = self.d + '/notion_ai.json'; M.AUTH_KEYS = self.d + '/ak'; self.runs = []
        M._run = lambda cmd, t=10: (self.runs.append(cmd), (0, 'active\n'))[1]
    def tearDown(self):
        M.CFG_FILE, M.AUTH_KEYS, M._run = self.old
    def test_defaults_and_save(self):
        c = M.load_cfg(); self.assertEqual(c['owner'], ''); self.assertEqual(M.owner(), 'владелец'); self.assertEqual(M.chat_url(), ''); self.assertTrue(c['voice'])
        ok, m, c = M.save_cfg({'owner': '  Аня  ', 'voice': False, 'tg_chat_id': '-100123'})
        self.assertTrue(ok); self.assertEqual(M.load_cfg()['owner'], 'Аня'); self.assertFalse(M.load_cfg()['voice'])
        self.assertEqual(M.tg_target(), '-100123'); self.assertEqual(self.runs, [])  # чат не меняли — окно не перезапускаем
    def test_validation(self):
        for body in ({'chat_url': 'https://evil.com/chat?t=' + 'a' * 32}, {'chat_url': 'https://app.notion.com/chat?t=abc'},
                     {'owner': ''}, {'owner': '<b>'}, {'notion_email': 'nope'}, {'tg_chat_id': '12ab'}):
            ok, m, _ = M.save_cfg(body); self.assertFalse(ok, body)
        self.assertFalse(Path(M.CFG_FILE).exists())
    def test_chat_change_restarts_view(self):
        ok, _, _ = M.save_cfg({'chat_url': 'https://app.notion.com/chat?t=' + 'b' * 32}); self.assertTrue(ok)
        self.assertTrue(any('notion-ai-view.service' in x for x in self.runs[-1]))
        self.assertEqual(M.chat_url(), 'https://app.notion.com/chat?t=' + 'b' * 32)
    def test_keys(self):
        import base64
        blob = (11).to_bytes(4, 'big') + b'ssh-ed25519' + (32).to_bytes(4, 'big') + b'k' * 32
        pub = 'ssh-ed25519 ' + base64.b64encode(blob).decode() + ' notion@ai'
        self.assertFalse(M.key_add('ssh-ed25519 !!!')[0]); self.assertFalse(M.key_add('hello')[0])
        Path(M.AUTH_KEYS).write_text('ssh-ed25519 AAAAother user@x')
        self.assertTrue(M.key_add(pub)[0]); self.assertTrue(M.key_add(pub)[0])
        lines = Path(M.AUTH_KEYS).read_text().splitlines()
        self.assertEqual(len(lines), 2); self.assertTrue(lines[1].endswith(M.KEY_MARK)); self.assertEqual(len(M.key_lines()), 1)
        M.key_remove(); self.assertEqual(Path(M.AUTH_KEYS).read_text().splitlines(), ['ssh-ed25519 AAAAother user@x'])
    def test_instruction_generic(self):
        M.save_cfg({'owner': 'Аня'}); t = M.instruction()
        self.assertIn('Владелец — Аня', t); self.assertIn('[TG чч:мм]', t); self.assertNotIn('Денис', t)
    def test_page_has_cfg(self):
        page = '<html><body><div id="scrim"><div class="modal">' + M.CFG_ANCHOR + '</div></div></body></html>'
        out = M.inject(page); self.assertIn('id="naiCfgBox"', out); self.assertIn('id="naiCfgScript"', out)
        self.assertEqual(M.inject(out).count('id="naiCfgBox"'), 1)


class TestModelCard(unittest.TestCase):
    """[notion-ai] Карточка «Notion AI» в «Активных аккаунтах»: модель и effort постоянного чата через notion-delegate /nai/model."""
    def test_model_set_and_public(self):
        import cc_notion_ai as M
        calls = []
        def fake(path, data=None, timeout=20):
            calls.append((path, data))
            if data is None: return {'ok': True, 'state': {'model': 'Opus 5.5', 'effort': 'xHigh', 'models': [{'label': 'Auto'}], 'efforts': ['Low', 'xHigh']}, 'pending': None}
            return {'id': 'abcdef12', 'status': 'queued', 'kind': 'model'}
        old = M._delegate; M._delegate = fake
        try:
            r = M.model_set({'model': ' GPT-6 Luna ', 'effort': '', 'junk': 1})
            self.assertTrue(r['ok']); self.assertEqual(r['id'], 'abcdef12'); self.assertEqual(calls[-1], ('/nai/model', {'model': 'GPT-6 Luna'}))
            self.assertTrue(M.model_set({})['ok']); self.assertEqual(calls[-1], ('/nai/model', {}))  # пусто — только перечитать список
            p = M.model_public(); self.assertEqual((p['model'], p['effort'], p['efforts']), ('Opus 5.5', 'xHigh', ['Low', 'xHigh']))
            M._delegate = lambda *a, **k: {'error': 'модели «X» нет в списке Notion'}
            r = M.model_set({'model': 'X'}); self.assertFalse(r['ok']); self.assertIn('нет в списке', r['message'])
            def boom(*a, **k): raise OSError('down')
            M._delegate = boom
            self.assertFalse(M.model_set({'effort': 'Max'})['ok'])
            self.assertTrue(M.model_public()['ok'])  # делегат молчит — отдаём последнее прочитанное из файла
        finally:
            M._delegate = old

    def test_page_has_card_without_time(self):
        import re
        ui = M.UI
        for k in ('id="fleetNotion"', 'naiModelTile', 'naiModelQ', "notion-ai/model", 'fleet-compact-account notion', 'nai-credits-link', 'Settings → Notion AI → Me'):
            self.assertIn(k, ui.replace("tile.id='fleetNotion'", 'id="fleetNotion"'), k)
        card = ui[ui.index('Карточка «Notion AI» в «Активных аккаунтах»'):ui.index('Вкладка «Notion AI» в консоли')]
        self.assertNotIn('fleet-live-meter', card)  # ни 5 часов, ни недели
        self.assertNotIn('Без лимитов по времени', card)
        self.assertIn('https://app.notion.com/space/09c55b37d4588114831c0003c4956da3', card)
        self.assertIn("CustomEvent('nai-state'", ui)
        self.assertIn("'/api/notion-ai/model'", open(M.__file__, encoding='utf-8').read())


class TestGeneralSettings(unittest.TestCase):
    """«Общие настройки»: у каждого агента главный блок на виду, остальное под спойлером; инструкции полные."""
    def test_blocks_for_every_agent_and_full_instructions(self):
        ui = M.CFG_UI
        for k in ('naiGenClaude', 'naiGenCodex', 'naiGenTg', 'naiPop', 'naiGenNaiGear', 'naiGenTgNai', 'naiCfgSave', 'naiCfgTg', 'naiCfgVoice', 'naiKeyAdd', 'naiInstr'):
            self.assertIn(k, ui)
        for k in ('/telegram:configure', '/telegram:access pair', '@BotFather', '@userinfobot', 'Получить ссылку для входа', 'по коду устройства'):
            self.assertIn(k, ui)
        self.assertEqual(ui.count('Подробно: что, где, как и почему'), 4)  # Claude, Codex, Notion AI, Telegram

    def test_one_save_sends_only_changed_fields(self):
        ui = M.CFG_UI
        sv = ui[ui.index("var sv=$i('naiCfgSave')"):]
        sv = sv[:sv.index('};')]
        for k in ("'chat_url','naiCfgUrl'", "'tg_chat_id','naiCfgTg'", "'voice','naiCfgVoice'", "'console_tab','naiCfgTab'"):
            self.assertIn(k, sv)
        self.assertIn('v!==was', ui)            # уходят только изменённые поля
        self.assertIn('if(d.cfg)data=d', ui)  # ответ без cfg не стирает поля

    def test_agent_blocks_only_in_general_view(self):
        self.assertIn('#scrim:not([data-view="general"]) .nai-gen.claude', M.CFG_UI)



class TestUnifiedMenus(unittest.TestCase):
    """[notion-ai] ⚙ Claude, Codex и Notion AI: «Переключение и лимиты» → «Модели в быстром меню» → «Свои настройки …»; сроки в карточках; полоса строками."""
    T = ('Переключение и лимиты', 'Модели в быстром меню')

    def order(self, text, ids):
        pos = [text.index(k) for k in ids]
        self.assertEqual(pos, sorted(pos), ids)

    def test_notion_ai_popup_three_sections_in_order(self):
        ui = M.CFG_UI
        self.order(ui, ('id="naiPopLim"', 'id="naiPopModels"', 'id="naiPopOwn"'))
        self.order(ui, self.T + ('Свои настройки Notion AI',))
        self.assertIn("$i('naiPopOwn').appendChild(box)", ui)  # форма настроек — в «Свои настройки»
        self.assertIn('naiPopCheck', ui)
        self.assertIn('hid.indexOf(m.label)<0||m.label===cur', M.UI)  # плитка: без галочки не показываем, кроме выбранной

    def test_model_hidden_saved_and_validated(self):
        d = tempfile.mkdtemp(); old = (M.CFG_FILE, M._run)
        M.CFG_FILE = d + '/notion_ai.json'; M._run = lambda *a, **k: (0, '')
        try:
            ok, _, c = M.save_cfg({'model_hidden': [' GPT-6 ', 'Auto', 'Auto', '', 5]})
            self.assertTrue(ok); self.assertEqual(c['model_hidden'], ['Auto', 'GPT-6'])
            ok, m, _ = M.save_cfg({'model_hidden': 'Auto'}); self.assertFalse(ok); self.assertIn('список', m)
            self.assertEqual(M.load_cfg()['model_hidden'], ['Auto', 'GPT-6'])
            old_d = M._delegate
            def boom(*a, **k): raise OSError('down')
            M._delegate = boom
            try:
                self.assertEqual(M.model_public()['hidden'], ['Auto', 'GPT-6'])
            finally:
                M._delegate = old_d
        finally:
            M.CFG_FILE, M._run = old

    def test_claude_and_codex_menus_same_scheme(self):
        import cc_overview as O
        js = O.JS
        self.order(js, ("autoGroup.id='fleetClaudeLimits'", "modelGroup.id='fleetClaudeModels'", "claudeOwn.id='fleetClaudeOwn'"))
        self.order(js, ("codexThresholds.id='fleetCxLimits'", "catalogGroup.id='fleetCxModels'", "codexOwn.id='fleetCodexOwn'"))
        for k in self.T + ('Свои настройки Claude', 'Свои настройки Codex', "post('config',{threshold", 'weekly_cap', 'codex_hidden'):
            self.assertIn(k, js, k)
        self.assertIn('#scrim:not([data-view="general"]) .fleet-common-settings{display:none}', O.CSS)  # в ⚙ Claude нет дублей общих настроек

    def test_cards_show_subscription_and_login_dates(self):
        import cc_overview as O
        js = O.JS
        self.assertIn('function paintCardDates(card,a,engine)', js)
        for k in ('Подписка до', 'Вход до', 'продлевается сам', 'renewal_next', 'login_expires'):
            self.assertIn(k, js, k)

    def test_live_strip_rows_on_subgrid(self):
        import cc_overview as O
        css = O.CSS
        self.assertIn('grid-template-columns:subgrid', css)
        self.assertNotIn('@media(max-width:1500px){.fleet-live-summary', css)

    def test_limits_config_weekly_cap_and_codex_hidden(self):
        import cc_limits as L
        src = open(L.__file__, encoding='utf-8').read()
        self.assertIn('if not 50 <= cap <= 100:', src)
        self.assertIn('snap["config"]["codex_hidden"]', src)
        self.assertIn('!hid.includes(m.id)', L.PAGE)
