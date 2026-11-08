import os
os.environ["CC_FLEET_TZ"] = "Asia/Irkutsk"   # зона владельца в тестах не зависит от config.json и пояса сервера
import json, tempfile, unittest, time, threading
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
        s.lock = threading.RLock(); s.transitioning = False; s.pending = Path(t.d)/'pending.json'; s.native = Native(t); s.calls = []
        s.labels = {'claude': 'Claude · не участвует', 'codex': 'Codex Full'}; s.avail = {'claude': {'status': 'up'}, 'codex': {'status': 'up'}}
        s.state = State(); s.clock = time.time; s.tasks = Tasks()
    def update_active(s): return False
    def paused(s, e): return e == 'claude'
    def input_allowed(s, e): return not s.paused(e)
    def public(s): return {'engines': {e: {'label': l, 'role': 'solo'} for e, l in s.labels.items()}}
    def transition(s, c, m, force=None, recover_blocked=False): s.calls.append(m); return {'ok': True}
    def action(s, e, a, b): s.calls.append('action'); return {'ok': True}
    def apply_scenario(s, b): s.calls.append('scenario'); return getattr(s, 'scenario_result', {'ok': True})
    def exchange(s, e): return Path('/ex')/e
class H:
    def do_GET(s): pass
    def do_POST(s): pass

class T(unittest.TestCase):
    def setUp(s):
        s.d = tempfile.mkdtemp(); s.sent = []; s.runs = []; s.tg = []; s.posts = []
        (Path(s.d)/'profile_runtime').mkdir(); (Path(s.d)/'profile_runtime/claude-policy.json').write_text('{"their":1}')
        (Path(s.d)/'h.jsonl').write_text('')
        s.ns = {'BASE': s.d, 'cfg': lambda: {'screen_session': 'testscreen'}, 'tg_notify': lambda t: s.sent.append(('claude', t)), 'H': H,
                'PAGE': '<html><head></head><body>x\n mirrorLoad();\n\n loadRotation();\n</body></html>', 'transcripts_dir': lambda: s.d}
        class B: BRIDGE = type('X', (), {'send': lambda self, t: s.sent.append(('codex', t))})()
        s.ns['cc_codex_bridge'] = B
        s.claude = [True]
        def run(args, timeout=30):
            s.runs.append(args)
            if args[:2] == ['screen', '-ls']: return 0, ('\t123.testscreen\t(Detached)\n' if s.claude[0] else 'No Sockets')
            if args[:2] == ['screen', '-S'] and 'quit' in args: s.claude[0] = False; return 0, ''
            if args[0] == 'pgrep': return (0 if s.claude[0] else 1), ''
            if args[0] == 'systemd-run': s.claude[0] = True; return 0, ''
            if args[:2] == ['systemctl', 'is-active']: return 0, 'active\n'
            return 0, ''
        M._run = run; M.INBOX = s.d + '/inbox'; M.SIDE_FLAG = s.d + '/side_claude.json'   # stop_claude стирает флаг побочной сессии: не по боевому пути
        M.NotionAI._later = lambda self, fn, *a: fn(*a)
        M.notion_installed = lambda: True   # на боевом пути /root/notion_web есть не везде: по умолчанию «Notion AI поставлен»
        M.NotionAI.tg_api = lambda self, method, payload: (s.tg.append((method, payload)), {'result': {'message_id': 77}})[1]
        M.NotionAI.tg_chats = lambda self: ['100000001']
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
        s.assertEqual((a['claude']['state'], a['codex']['state'], a['notion']['state']), ('pause', 'run', 'run'))   # агент Notion на паузу не ставится
        s.assertEqual((a['claude']['text'], a['notion']['text']), ('пауза', 'работает'))
        s.assertNotIn('на паузе', a['notion']['label'])
        s.assertIn('на паузе', a['claude']['label']); s.assertNotIn('не участвует', a['claude']['label'])
        s.assertNotIn('выкл', json.dumps(a, ensure_ascii=False))
        s.p.avail['claude']['status'] = 'down'; s.assertEqual(s.nai.agents()['claude']['state'], 'limit')
        s.p.avail['claude']['status'] = 'up'; s.nai.on(); a = s.nai.agents()
        s.assertEqual((a['claude']['state'], a['codex']['state'], a['notion']['state']), ('pause', 'pause', 'run'))
        s.nai.on(kind='orchestrator', follower='codex'); a = s.nai.agents()
        s.assertEqual((a['codex']['state'], a['codex']['text'], a['notion']['state']), ('exec', 'исполнитель', 'lead'))
        s.assertIn('agents', s.nai.public())
    def test_unlinked_codex_and_notion_are_ghost_tiles(s):
        # Codex без аккаунтов и Notion AI без службы — «призрачные» плитки с предложением установить, а не «работает»
        class St:
            def public(_): return {'engines': {'claude': {'role': 'solo', 'label': 'Claude Full'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
        s.p.state = St()
        s.ns['cc_codex'] = type('C', (), {'profile_slots': staticmethod(lambda: [])})
        M.notion_installed = lambda: False
        a = s.nai.agents()
        s.assertEqual((a['codex']['state'], a['codex']['text']), ('unlinked', 'не подключён'))
        s.assertEqual((a['notion']['state'], a['notion']['text']), ('unlinked', 'не установлен'))
        s.assertEqual(a['claude']['state'], 'run')   # Claude не затронут
        s.assertEqual(s.nai.public()['agents']['codex']['state'], 'unlinked')
        # подключили Codex (есть аккаунт) и поставили Notion AI — плитки обычные
        s.ns['cc_codex'] = type('C', (), {'profile_slots': staticmethod(lambda: ['gpt1'])})
        M.notion_installed = lambda: True
        a = s.nai.agents()
        s.assertEqual((a['codex']['state'], a['notion']['state']), ('run', 'run'))
    def test_unlinked_check_failure_keeps_tiles_working(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'solo', 'label': 'Claude Full'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
        s.p.state = St()
        class Bad:
            @staticmethod
            def profile_slots(): raise OSError('нет доступа')
        s.ns['cc_codex'] = Bad
        s.assertEqual(s.nai.agents()['codex']['state'], 'run')   # не смогли проверить — рабочее не прячем
    def test_ghost_tiles_ui_is_in_the_page(s):
        import cc_notion_ai as N
        src = Path(N.__file__).read_text(encoding='utf-8')
        for part in ("function linkPop(k,anchor){", "function ghostMark(){", "'ag-unlinked-'+a[0]", ".nai-seg.s-unlinked{",
                     "html.ag-unlinked-codex #ctCodex", "html.ag-unlinked-notion #cTabs .ctab[data-s=\"notion\"]",
                     "if(agState(s.dataset.ag).state==='unlinked'){linkPop(s.dataset.ag,s);return}"):
            s.assertIn(part, src, part)
    def test_codex_with_single_account_is_not_paused_by_notion_profile(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'paused', 'label': 'Claude · не участвует'}, 'codex': {'role': 'solo', 'label': 'Codex Full · самостоятельно'}}}
            def _codex_free(_): return True
        s.p.state = St(); s.nai.on(); a = s.nai.agents()
        s.assertEqual((a['claude']['state'], a['codex']['state'], a['notion']['state']), ('pause', 'run', 'run'))
        s.assertNotIn('на паузе', a['codex']['label'])
        s.assertTrue(s.p.paused('claude')); s.assertFalse(s.p.paused('codex'))
        s.assertNotIn('на паузе', s.p.public()['engines']['codex']['label']); s.assertIn('на паузе', s.p.public()['engines']['claude']['label'])
        s.assertFalse(any('Codex на паузе' in t for who, t in s.sent if who == 'codex'), 'в чат Codex про паузу не пишем')
        s.assertTrue(any('Codex работает сам' in t for who, t in s.sent if who == 'claude'))

    def test_codex_with_several_accounts_is_still_paused_by_notion_profile(s):
        class St:
            def public(_): return {'engines': {'claude': {'role': 'paused', 'label': 'Claude'}, 'codex': {'role': 'solo', 'label': 'Codex Full'}}}
            def _codex_free(_): return False
        s.p.state = St(); s.nai.on(); a = s.nai.agents()
        s.assertEqual(a['codex']['state'], 'pause'); s.assertTrue(s.p.paused('codex'))
        s.assertTrue(any('Codex на паузе' in t for who, t in s.sent if who == 'codex'))

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
        s.nai.on(); s.claude[0] = False
        r = s.p.apply_scenario({'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1})
        s.assertFalse(r['ok']); s.assertTrue(s.nai.active()); s.assertNotIn('scenario', s.p.calls)
    def test_missing_snapshot_does_not_stop_bridge(s):
        s.claude[0] = False; s.nai.on(); before=len(s.runs)
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertFalse(r['ok']);s.assertTrue(s.nai.active());s.assertFalse(any(a[:3]==['systemctl','stop',M.BRIDGE_UNIT] for a in s.runs[before:]))
    def test_staging_failure_restores_notion(s):
        s.claude[0]=False;s.nai.on();s.nai.handoff_snapshot_load=lambda: {'thread_id':'known'}
        s.nai.bridge_state=lambda fresh=False:'inactive' if not s.nai.active() else 'active'
        def fail(snapshot):raise M.NAIError('test launch failed')
        s.nai.handoff_start_staging=fail;s.nai.handoff_stop_staging=lambda:True
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertFalse(r['ok']);s.assertIn('Notion AI восстановлен',r['message']);s.assertTrue(s.nai.active())
    def test_confirmed_staging_preserves_snapshot(s):
        s.claude[0]=False;s.nai.on();snap={'thread_id':'known','telegram_channel':True,'sandbox_root':True}
        s.nai.handoff_snapshot_load=lambda:snap;s.nai.bridge_state=lambda fresh=False:'inactive' if not s.nai.active() else 'active'
        s.nai.handoff_start_staging=lambda snapshot:True
        s.p.native.claude.capture=lambda:dict(snap)
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertTrue(r['ok']);s.assertFalse(s.nai.active());s.assertIn('scenario',s.p.calls)
        s.assertFalse(s.p.native._handoff_telegram);s.assertFalse(s.p.native._handoff_sandbox_root)
    def test_codex_to_claude_resumes_known_session(s):
        s.claude[0]=False;snap={'thread_id':'known','telegram_channel':True,'sandbox_root':True}
        s.nai.handoff_snapshot_load=lambda:snap;s.nai.bridge_state=lambda fresh=False:'inactive'
        calls=[];s.nai.handoff_start_staging=lambda snapshot:calls.append(snapshot)
        s.p.native.claude.capture=lambda:dict(snap)
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertTrue(r['ok']);s.assertEqual(calls,[snap]);s.assertIn('scenario',s.p.calls)
        s.assertIsNone(s.p.native._handoff_snapshot)
    def test_codex_to_claude_refuses_active_bridge(s):
        s.claude[0]=False;s.nai.handoff_snapshot_load=lambda:{'thread_id':'known'}
        s.nai.bridge_state=lambda fresh=False:'active'
        s.nai.handoff_start_staging=lambda snapshot:s.fail('started despite active bridge')
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertFalse(r['ok']);s.assertNotIn('scenario',s.p.calls)
    def test_codex_to_claude_failure_stops_staging(s):
        s.claude[0]=False;s.nai.handoff_snapshot_load=lambda:{'thread_id':'known'}
        s.nai.bridge_state=lambda fresh=False:'inactive'
        s.nai.handoff_start_staging=lambda snapshot:True
        stopped=[];s.nai.handoff_stop_staging=lambda:stopped.append(True) or True
        s.p.scenario_result={'ok':False,'message':'тестовая ошибка'}
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertFalse(r['ok']);s.assertEqual(stopped,[True]);s.assertFalse(s.nai.active())
        s.assertIn('Исходный профиль сохранён',r['message'])
    def test_staging_explicitly_disables_telegram_plugin(s):
        s.claude[0]=False
        snap={'thread_id':'known','cwd':s.d,'model':'claude-test','effort':'xhigh'}
        s.nai.handoff_valid_snapshot=lambda _:True
        s.ns['screen_hardcopy']=lambda:'❯'
        s.p.native.claude.capture=lambda:{'thread_id':'known'}
        s.assertTrue(s.nai.handoff_start_staging(snap))
        args=next(a for a in s.runs if a[0]=='systemd-run')
        s.assertNotIn('--channels',args)
        settings=json.loads(args[args.index('--settings')+1])
        s.assertIs(settings['enabledPlugins']['telegram@claude-plugins-official'],False)
    def test_resume_snapshot_validation_and_do_not_overwrite(s):
        tid='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        history=Path(s.d)/(tid+'.jsonl');history.write_text('test')
        s.ns['cfg']=lambda:{'screen_session':'testscreen','transcripts_dir':s.d}
        good={'thread_id':tid,'history':str(history),'cwd':s.d,'model':'claude-test','effort':'xhigh'}
        s.assertTrue(s.nai.handoff_snapshot_save(good));s.assertEqual(s.nai.handoff_snapshot_load(),good)
        s.assertFalse(s.nai.handoff_snapshot_save(dict(good,thread_id='bad')))
        s.assertFalse(s.nai.handoff_snapshot_save(dict(good,history='/etc/passwd')))
        s.assertFalse(s.nai.handoff_snapshot_save(dict(good,model='bad model')))
        s.assertEqual(s.nai.handoff_snapshot_load(),good)
    def test_scenario_error_restores_notion(s):
        s.claude[0]=False;s.nai.on();snap={'thread_id':'known','telegram_channel':True,'sandbox_root':True}
        s.nai.handoff_snapshot_load=lambda:snap;s.nai.bridge_state=lambda fresh=False:'inactive' if not s.nai.active() else 'active'
        s.nai.handoff_start_staging=lambda snapshot:True;s.nai.handoff_stop_staging=lambda:True
        s.p.scenario_result={'ok':False,'message':'ошибка перехода'}
        r=s.p.apply_scenario({'choices':{'claude':'full','codex':None},'confirm':'подтверждаю','revision':1})
        s.assertFalse(r['ok']);s.assertTrue(s.nai.active());s.assertIn('Notion AI восстановлен',r['message'])
        s.assertIsNone(s.p.native._handoff_snapshot);s.assertFalse(s.p.native._handoff_telegram)
    def test_codex_switch_does_not_start_old_claude(s):
        s.nai.on();s.assertFalse(s.claude[0]);before=len(s.runs)
        r=s.p.apply_scenario({'choices':{'claude':None,'codex':'write'},'confirm':'подтверждаю','revision':1})
        s.assertTrue(r['ok']);s.assertFalse(s.claude[0]);s.assertFalse(any(a[0]=='systemd-run' for a in s.runs[before:]))
    def test_codex_failure_restores_notion(s):
        s.claude[0]=False;s.nai.on();s.p.scenario_result={'ok':False,'message':'проверочный отказ'}
        r=s.p.apply_scenario({'choices':{'claude':None,'codex':'write'},'confirm':'подтверждаю','revision':1})
        s.assertFalse(r['ok']);s.assertTrue(s.nai.active());s.assertIn('Notion AI восстановлен',r['message'])
    def test_bridge_stop_failure_preserves_notion(s):
        s.claude[0]=False;s.nai.on();old=M._run
        def failing(args,timeout=30):
            if args[:3]==['systemctl','stop',M.BRIDGE_UNIT]:return 1,'failed'
            return old(args,timeout)
        M._run=failing
        try:
            r=s.nai.off(notify=False);s.assertFalse(r['ok']);s.assertTrue(s.nai.active())
        finally:M._run=old
    def handoff_test_setup(s):
        old_timeout, old_delay = M.HANDOFF_READY_TIMEOUT, M.HANDOFF_ENTER_DELAY
        s.addCleanup(setattr, M, 'HANDOFF_READY_TIMEOUT', old_timeout)
        s.addCleanup(setattr, M, 'HANDOFF_ENTER_DELAY', old_delay)
        M.HANDOFF_READY_TIMEOUT, M.HANDOFF_ENTER_DELAY = 1, 0.01
        folder = Path(s.d) / 'profile_exchange/codex/outbox/agent_handoff'
        folder.mkdir(parents=True)
        for name in ('claude.md', 'codex.md', 'notion.md'):
            (folder / name).write_text(name)
        s.ns['screen_hardcopy'] = lambda: '❯ ready'
        old_dir = M.CLAUDE_HISTORY_DIR
        s.addCleanup(setattr, M, 'CLAUDE_HISTORY_DIR', old_dir)
        M.CLAUDE_HISTORY_DIR = str(Path(s.d) / 'history')   # настоящую папку бесед тесты не читают
        return folder
 
    def handoff_stuff(s):
        return [x for x in s.runs if x[:2] == ['screen', '-S'] and 'stuff' in x]
 
    def test_handoff_claude_text_is_safe(s):
        folder = s.handoff_test_setup()
        text = s.nai.handoff_sync_text('claude')
        s.assertTrue(text.isascii())
        s.assertIn(str(folder), text)
        s.assertFalse(any(ord(c) in {36, 92, 94, 34, 39, 96} or ord(c) < 32 or ord(c) == 127 for c in text))
 
    def project_setup(s, card='# Карточка\nЦель: тест\n'):
        folder = s.handoff_test_setup()
        proj = folder / 'current_project'
        proj.mkdir()
        if card is not None:
            (proj / 'card.md').write_text(card)
        return folder, proj

    def test_project_hint_when_card(s):
        folder, proj = s.project_setup()
        text = s.nai.handoff_sync_text('claude')
        s.assertTrue(text.isascii())
        s.assertFalse(any(ord(c) in {36, 92, 94, 34, 39, 96} or ord(c) < 32 or ord(c) == 127 for c in text))
        s.assertIn('current project folder ' + str(proj), text)
        s.assertIn('card.md first, then owner_last.md', text)
        s.assertNotIn('Read all .md notes', text)
        s.assertNotIn('older than', text)
        for target in ('codex', 'notion'):
            t = s.nai.handoff_sync_text(target)
            s.assertIn('текущего проекта ' + str(proj), t)
            s.assertIn(str(folder) + '/' + target + '.md', t)
            s.assertIn('Архив', t)

    def test_project_hint_without_card_is_old(s):
        s.project_setup(card=None)
        s.assertIn('Read all .md notes', s.nai.handoff_sync_text('claude'))
        s.assertIn('Прочитай все записки', s.nai.handoff_sync_text('codex'))

    def test_project_hint_stale_empty_big(s):
        import os
        folder, proj = s.project_setup()
        old = time.time() - 10 * 86400
        os.utime(proj / 'card.md', (old, old))
        s.assertIn('older than 7 days', s.nai.handoff_sync_text('claude'))
        s.assertIn('старше 7 дней', s.nai.handoff_sync_text('codex'))
        (proj / 'card.md').write_text('   \n')
        s.assertIn('card is empty', s.nai.handoff_sync_text('claude'))
        (proj / 'card.md').write_text('x' * 9000)
        s.assertIn('longer than 8000 bytes', s.nai.handoff_sync_text('claude'))
        s.assertTrue(s.nai.handoff_sync_text('claude').isascii())

    def test_project_refresh_and_signature(s):
        folder, proj = s.project_setup()
        tg = '<channel source="plugin:telegram:telegram" chat_id="1" message_id="7" user="d" ts="2026-11-06T10:20:11.000Z">\nпривет, проверка\n</channel>'
        hist = Path(s.d) / 'hist.jsonl'
        hist.write_text(json.dumps(dict(type='user', isMeta=True, timestamp='2026-11-06T10:20:11.838Z', message=dict(role='user', content=tg))) + '\n')
        (Path(s.d) / 'profile_runtime/last-claude-session.json').write_text(json.dumps(dict(history=str(hist))))
        s.assertTrue(s.nai.handoff_sync('notion'))
        text = (proj / 'owner_last.md').read_text()
        s.assertIn('06.11 18:20 · Telegram: привет, проверка', text)  # UTC+8
        s.assertEqual(oct((proj / 'owner_last.md').stat().st_mode & 0o777), '0o644')
        sig = json.loads((Path(s.d) / 'profile_runtime/handoff-sync.json').read_text())['notion']
        names = [x[0] for x in sig]
        s.assertIn('current_project/card.md', names)
        s.assertIn('current_project/owner_last.md', names)
        s.assertNotIn('notion.md', names)
        s.assertIn('codex.md', names)
        s.assertIn('current_project', ' '.join(str(x) for x in s.posts))  # подсказка про папку ушла в чат Notion
        s.assertEqual([x for x in proj.iterdir() if x.name.startswith('.owner_last')], [])  # временный файл убран

    def history_files(s, **files):
        """Папка бесед в песочнице: {имя: (строки, сколько секунд назад изменена)}."""
        import os
        folder = Path(M.CLAUDE_HISTORY_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        for name, (lines, ago) in files.items():
            path = folder / (name + '.jsonl')
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            stamp = time.time() - ago
            os.utime(path, (stamp, stamp))
        return folder

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
        s.assertTrue(s.nai.handoff_refresh_owner_last())
        last = (proj / 'owner_last.md').read_text()
        s.assertIn('07.11 17:20 · Telegram: свежий вопрос с PROD', last)
        s.assertNotIn('старое сообщение', last)
        tail = (proj / 'handoff_tail.md').read_text()
        s.assertIn('STATE: FINISHED', tail)
        s.assertIn('свежий вопрос с PROD', tail)
        s.assertEqual(oct((proj / 'handoff_tail.md').stat().st_mode & 0o777), '0o644')
        s.assertEqual([x for x in proj.iterdir() if x.name.startswith('.') and 'tmp' in x.name], [])

    def test_refresh_merges_prod_and_new_conversation(s):
        from test_cc_handoff_tail import tg, say
        folder, proj = s.project_setup()
        s.history_files(prod=([tg('2', '2026-11-07T09:20:00.000Z', 'вопрос на PROD')], 120),
                        dev=([tg('3', '2026-11-07T09:25:00.000Z', 'вопрос после возврата')], 10))
        s.nai.handoff_refresh_owner_last()
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
        s.nai.handoff_refresh_owner_last()
        last = (proj / 'owner_last.md').read_text()
        s.assertIn('настоящее', last)
        s.assertNotIn('task-notification', last)
        s.assertNotIn('This session is being continued', last)

    def test_sync_text_continues_when_unfinished(s):
        from test_cc_handoff_tail import tg
        folder, proj = s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'доделай правку')], 5))
        s.nai.handoff_refresh_owner_last()
        s.assertEqual(s.nai.handoff_tail_state(), 'unfinished')
        text = s.nai.handoff_sync_text('claude')
        s.assertTrue(text.isascii())
        s.assertFalse(any(ord(c) in {36, 92, 94, 34, 39, 96} or ord(c) < 32 or ord(c) == 127 for c in text))
        s.assertIn('card.md first, then owner_last.md, then handoff_tail.md', text)
        s.assertIn('Continue from the last step', text)
        s.assertNotIn('Do not start any work', text)
        s.assertIn('Продолжи с последнего шага', s.nai.handoff_sync_text('codex'))
        notion = s.nai.handoff_sync_text('notion')
        s.assertIn('Работу сам не выполняй', notion)
        s.assertIn('какой следующий шаг предлагаешь', notion)

    def test_sync_text_stays_quiet_when_finished(s):
        from test_cc_handoff_tail import tg, say, reply, result
        folder, proj = s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'вопрос'), reply('2026-11-07T09:20:10.000Z', 'r', 'ответ'),
                            result('2026-11-07T09:20:11.000Z', 'r', 'sent'), say('2026-11-07T09:20:12.000Z', 'готово')], 5))
        s.nai.handoff_refresh_owner_last()
        s.assertEqual(s.nai.handoff_tail_state(), 'finished')
        text = s.nai.handoff_sync_text('claude')
        s.assertIn('Do not start any work', text)
        s.assertNotIn('Continue from the last step', text)
        s.assertIn('Не начинай работу', s.nai.handoff_sync_text('codex'))

    def test_card_behind_conversation_is_reported(s):
        import os
        from test_cc_handoff_tail import tg
        folder, proj = s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'вопрос')], 5))
        old = time.time() - 3600
        os.utime(proj / 'card.md', (old, old))
        s.nai.handoff_refresh_owner_last()
        s.assertIn('behind the conversation', s.nai.handoff_sync_text('claude'))
        s.assertIn('отстаёт от беседы', s.nai.handoff_sync_text('codex'))
        os.utime(proj / 'card.md', None)
        s.assertNotIn('behind the conversation', s.nai.handoff_sync_text('claude'))

    def test_sync_delivers_unfinished_rule_to_console(s):
        from test_cc_handoff_tail import tg
        s.project_setup()
        s.history_files(a=([tg('2', '2026-11-07T09:20:00.000Z', 'доделай')], 5))
        s.assertTrue(s.nai.handoff_sync('claude'))
        calls = s.handoff_stuff()
        s.assertIn('Continue from the last step', calls[0][-1])
        s.assertEqual(calls[1][-1], '\r')

    def test_project_no_card_no_refresh(s):
        folder, proj = s.project_setup(card=None)
        s.assertFalse(s.nai.handoff_refresh_owner_last())
        s.assertFalse((proj / 'owner_last.md').exists())
        s.assertFalse(any(x[0].startswith('current_project') for x in s.nai.handoff_sync_signature('claude')))

    def test_handoff_claude_screen_delivery(s):
        s.handoff_test_setup()
        s.assertTrue(s.nai.handoff_sync('claude'))
        calls = s.handoff_stuff()
        s.assertEqual(len(calls), 2)
        s.assertEqual(calls[0][:7], ['screen', '-S', 'testscreen', '-p', '0', '-X', 'stuff'])
        s.assertEqual(calls[0][-1], s.nai.handoff_sync_text('claude'))
        s.assertEqual(calls[1][-1], '\r')
        s.assertEqual(s.tg, [])
        s.assertEqual(s.sent, [])
 
    def test_handoff_claude_timeout(s):
        s.handoff_test_setup()
        s.ns['screen_hardcopy'] = lambda: 'loading'
        s.assertFalse(s.nai.handoff_sync('claude'))
        s.assertEqual(s.handoff_stuff(), [])
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())
 
    def test_handoff_deduplicates_other_notes(s):
        folder = s.handoff_test_setup()
        s.assertTrue(s.nai.handoff_sync('claude'))
        s.assertFalse(s.nai.handoff_sync('claude'))
        (folder / 'claude.md').write_text('own note changed significantly')
        s.assertFalse(s.nai.handoff_sync('claude'))
        s.assertEqual(len(s.handoff_stuff()), 2)
        (folder / 'codex.md').write_text('another note with changed length')
        s.assertTrue(s.nai.handoff_sync('claude'))
        s.assertEqual(len(s.handoff_stuff()), 4)
 
    def test_handoff_disabled(s):
        s.handoff_test_setup()
        (Path(s.d) / 'handoff_sync.disabled').touch()
        s.assertFalse(s.nai.handoff_sync('claude'))
        s.assertEqual(s.handoff_stuff(), [])
        s.assertEqual(s.tg, [])
        s.assertEqual(s.sent, [])
 
    def test_handoff_codex_delivery(s):
        s.handoff_test_setup()
        calls = []
        class Console:
            def send_input(self, text):
                calls.append(text)
                return True, ''
        s.ns['cc_codex_console'] = Console()
        s.assertTrue(s.nai.handoff_sync('codex'))
        s.assertFalse(s.nai.handoff_sync('codex'))
        s.assertEqual(len(calls), 1)
        s.assertIn('[Панель]', calls[0])
        s.assertIn('Прочитай', calls[0])
        s.assertEqual(s.tg, [])
        s.assertEqual(s.sent, [])
 
    def test_handoff_codex_missing_module(s):
        s.handoff_test_setup()
        s.ns.pop('cc_codex_console', None)
        s.assertFalse(s.nai.handoff_sync('codex'))
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())
 
    def test_handoff_notion_delivery(s):
        s.handoff_test_setup()
        s.assertTrue(s.nai.handoff_sync('notion'))
        s.assertEqual(len(s.posts), 1)
        s.assertTrue(s.posts[0].startswith('[Панель '))
        s.assertIn('не вызывай', s.posts[0])
        s.assertEqual(s.tg, [])
        s.assertEqual(s.sent, [])
 
    def test_handoff_scenario_success_and_failure(s):
        calls = []
        s.nai.handoff_sync = lambda target: calls.append(target)
        body = {'choices': {'claude': 'full', 'codex': None}, 'confirm': 'подтверждаю', 'revision': 1}
        s.assertTrue(s.p.apply_scenario(body)['ok'])
        s.assertEqual(calls, ['claude'])
        calls.clear()
        s.p.scenario_result = {'ok': False}
        s.assertFalse(s.p.apply_scenario(body)['ok'])
        s.assertEqual(calls, [])
 
    def test_handoff_on_and_rollback(s):
        calls = []
        s.nai.handoff_sync = lambda target: calls.append(target)
        s.claude[0] = False
        s.assertTrue(s.nai.on(by='откат переключения')['ok'])
        s.assertEqual(calls, [])
        s.assertTrue(s.nai.off(notify=False, restore_claude=False)['ok'])
        s.assertTrue(s.nai.on(by='панель')['ok'])
        s.assertEqual(calls, ['notion'])
 
    def test_handoff_off_started(s):
        calls = []
        s.nai.handoff_sync = lambda target: calls.append(target)
        s.assertTrue(s.nai.on()['ok'])
        calls.clear()
        s.assertTrue(s.nai.off(notify=False)['ok'])
        s.assertEqual(calls, ['claude'])
 
    def test_handoff_catches_sender_exception(s):
        s.handoff_test_setup()
        class Console:
            def send_input(self, text):
                raise RuntimeError('test')
        s.ns['cc_codex_console'] = Console()
        s.assertFalse(s.nai.handoff_sync('codex'))
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())
        s.assertEqual(s.tg, [])
        s.assertEqual(s.sent, [])
 
    def test_handoff_lock_busy(s):
        s.handoff_test_setup()
        s.nai._sync_lock = threading.Lock()
        s.nai._sync_lock.acquire()
        try:
            s.assertFalse(s.nai.handoff_sync('notion'))
        finally:
            s.nai._sync_lock.release()
        s.assertEqual(s.posts, [])
 
    def test_handoff_rejects_unsafe_claude_input(s):
        s.handoff_test_setup()
        for c in (chr(36), chr(92), chr(94), chr(34), chr(39), chr(96), '\n', 'я'):
            s.assertFalse(s.nai.handoff_send_claude('test' + c))
        s.assertEqual(s.handoff_stuff(), [])
 
    def test_handoff_send_failure_does_not_save(s):
        s.handoff_test_setup()
        s.nai.handoff_send_claude = lambda text: False
        s.assertFalse(s.nai.handoff_sync('claude'))
        s.assertFalse((Path(s.d) / 'profile_runtime/handoff-sync.json').exists())
 
    def test_handoff_empty_notes(s):
        folder = s.handoff_test_setup()
        (folder / 'codex.md').unlink()
        (folder / 'notion.md').unlink()
        s.assertFalse(s.nai.handoff_sync('claude'))
        s.assertEqual(s.handoff_stuff(), [])

    def test_auto_blocked(s):
        s.nai.on(); s.assertFalse(s.p.transition('X', M.AUTO_MESSAGE)['ok'])

    def test_fallback_snapshot_skips_side_conversation(s):
        """R4-2: самая свежая по времени беседа может быть побочной (вопрос из консоли) — снимок берётся с основной."""
        import os
        def write(name, rows, age):
            p = Path(s.d) / ('%s.jsonl' % (name * 8 + '-1111-1111-1111-' + name * 12)); p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
            t = time.time() - age; os.utime(p, (t, t)); return p
        asst = lambda model: {'type': 'assistant', 'message': {'role': 'assistant', 'model': model, 'content': []}}
        main = write('a', [{'type': 'user', 'message': {'role': 'user', 'content': 'доделай правку'}}, asst('claude-main-model')], 100)
        write('b', [{'type': 'user', 'message': {'role': 'user', 'content': M.HT.SIDE_MARK + ': x] сколько будет 2+2?'}}, asst('claude-side-model')], 5)
        snap = s.nai.fallback_snapshot()
        s.assertEqual(snap['history'], str(main)); s.assertEqual(snap['model'], 'claude-main-model')

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


class TestAgents(unittest.TestCase):
    """Агенты Notion (07.11.26): список и задания идут в notion-delegate, проверка аргументов, сообщение в чат выбранного агента."""
    AID = '88737d8f-63f5-4bdc-93b8-4a440d669ce2'

    def _with(self, fake, fn):
        import cc_notion_ai as M
        old = M._delegate; M._delegate = fake
        try: return fn(M)
        finally: M._delegate = old

    def test_send_to_agent(self):
        calls = []
        def fake(path, data=None, timeout=20):
            calls.append((path, data)); return {'id': 'abcdef13', 'status': 'queued'}
        def run(M):
            self.assertTrue(M.chat_send('привет агенту', 'rid-ag', self.AID)['ok'])
            self.assertEqual(calls[-1][1]['aid'], self.AID)
            M.chat_send('в главный', 'rid-main'); self.assertNotIn('aid', calls[-1][1])
            M.chat_send('плохой id', 'rid-bad', '../x'); self.assertNotIn('aid', calls[-1][1])
        self._with(fake, run)

    def test_actions_validate(self):
        calls = []
        def fake(path, data=None, timeout=20):
            calls.append((path, data)); return {'id': '0123abcd', 'stage': 'в очереди'}
        def run(M):
            self.assertFalse(M.agents_action('drop', {})['ok'])
            self.assertFalse(M.agents_action('settings', {'aid': '../../etc'})['ok'])
            self.assertEqual(calls, [])
            r = M.agents_action('create', {'name': 'Агент', 'model': 'Opus 5.5', 'effort': 'High', 'ssh': 'yes'})
            self.assertTrue(r['ok']); self.assertEqual(calls[-1][0], '/agents/create'); self.assertIs(calls[-1][1]['ssh'], False)  # только true включает доступ
            M.agents_action('create', {'name': 'Агент', 'ssh': True}); self.assertIs(calls[-1][1]['ssh'], True)
            M.agents_action('settings', {'aid': self.AID, 'effort': 'Max'}); self.assertEqual(calls[-1], ('/agents/settings', {'aid': self.AID, 'effort': 'Max'}))
            self.assertFalse(M.agents_view('x')['ok']); self.assertEqual(M.agents_job('../x')['status'], 'unknown')
        self._with(fake, run)

    def test_telegram_actions_return_at_once_without_a_job(self):
        calls = []
        def fake(path, data=None, timeout=20):
            calls.append((path, data)); return {'ok': True, 'message': 'Сохранено', 'tg': '-100123456'}
        def run(M):
            r = M.agents_action('tg', {'aid': self.AID, 'tg_chat_id': ' -100123456 '})
            self.assertEqual((r['ok'], r['tg']), (True, '-100123456'))
            self.assertEqual(calls[-1], ('/agents/tg', {'aid': self.AID, 'tg_chat_id': '-100123456'}))
            M.agents_action('tgtest', {'name': 'Торговля', 'tg_chat_id': '@trade_channel'})
            self.assertEqual(calls[-1], ('/agents/tgtest', {'name': 'Торговля', 'tg_chat_id': '@trade_channel'}))
            M.agents_action('create', {'name': 'Агент', 'tg_chat_id': '-100123456'}); self.assertEqual(calls[-1][1]['tg_chat_id'], '-100123456')
            M.agents_action('create', {'name': 'Агент'}); self.assertEqual(calls[-1][1]['tg_chat_id'], '')  # пусто — основной канал
            M.agents_action('settings', {'aid': self.AID, 'instructions': True}); self.assertIs(calls[-1][1]['instructions'], True)
            M.agents_action('settings', {'aid': self.AID, 'instructions': 'yes'}); self.assertNotIn('instructions', calls[-1][1])
            M.agents_action('settings', {'aid': self.AID, 'newkey': True}); self.assertIs(calls[-1][1]['newkey'], True)
            M.agents_action('settings', {'aid': self.AID, 'newkey': 'yes'}); self.assertNotIn('newkey', calls[-1][1])
            self.assertFalse(M.agents_action('tg', {'aid': '../x'})['ok'])
        self._with(fake, run)
        def refuse(path, data=None, timeout=20): return {'error': 'Telegram: нужен id чата'}
        r = self._with(refuse, lambda M: M.agents_action('tg', {'aid': self.AID, 'tg_chat_id': 'x'}))
        self.assertFalse(r['ok']); self.assertIn('нужен id', r['message'])

    def test_public_list_tells_who_gets_telegram(self):
        def fake(path, data=None, timeout=20): return {'ok': True, 'agents': [], 'models': [], 'efforts': [], 'jobs': []}
        r = self._with(fake, lambda M: M.agents_public())
        self.assertIn('tg_agent', r)

    def test_agents_ui_progress_telegram_and_one_block(self):
        import cc_notion_ai as M
        ui = M.UI
        # создание: окно закрывается сразу, ход — в строке под проектом с полосой по времени; повторного окна с прогрессом нет
        self.assertIn("if(label.kind==='create')close()", ui)
        for needle in ('nai-ag-prog', 'nai-pg-bar', 'function fillProg', 'function fmtEta', "'/'+j.steps+' · '", 'Осталось примерно'):
            self.assertIn(needle, ui)
        self.assertNotIn("Создаю агента… (~3–4 мин)", ui.split("function onClick")[1].split("window.naiAgentPop")[0].replace("'Создаю агента… (около 3 мин)'", ''))
        # Telegram: поле в форме и в окне агента, проверка, сохранение, приём из Telegram
        for needle in ("tgBlock('naiNewTg','naiNewTgId'", "tgBlock('naiAgTg','naiAgTgId'", "data-do=\"tgtest\"", "data-do=\"agtgsave\"", "post('tgtest'", "post('tg'", 'naiAgRecv', 'tg_agent', 'Основной канал Claude', 'tg_chat_id:tv.id'):
            self.assertIn(needle, ui)
        # ключ SSH: состояние доступа и «Новый ключ SSH» в окне агента; форма честно говорит, где хранится ключ
        for needle in ('data-do="newkey"', "newkey:true", 'Новый ключ SSH', 'Выдать ключ SSH', 'вход проверен', 'хранится в инструкции агента в Notion'):
            self.assertIn(needle, ui)
        # введённое в форму не пропадает, когда она перерисовывается
        for needle in ('function snap()', 'cur.name=n.value', "if(cur&&t.id==='naiNewName')cur.name=t.value"):
            self.assertIn(needle, ui)
        # Notion AI и его агенты — одним блоком в верхнем меню, рамка только когда агенты есть
        for needle in ("grp.id='naiGrp'", "grp.classList.toggle('nai-grp-on',L.length>0&&tabOn)", '.nai-grp:not(:has(.ctab:not([hidden])))'):
            self.assertIn(needle, ui)

    def test_settings_form_has_the_token_field_as_a_password_input(self):
        import cc_notion_ai as M
        ui = M.CFG_UI
        self.assertIn('id="naiCfgPat" type="password"', ui)
        self.assertIn("['notion_token','naiCfgPat']", ui)
        self.assertIn('notion.so/profile/integrations', ui)  # «как подключить с нуля» говорит, где взять токен

    def test_public_filters_and_errors(self):
        def fake(path, data=None, timeout=20):
            return {'ok': True, 'agents': [{'aid': self.AID, 'name': 'A'}], 'models': [{'label': 'Opus 5.5'}, {'label': 'Connect ChatGPT plan'}], 'efforts': ['Low'], 'jobs': []}
        r = self._with(fake, lambda M: M.agents_public())
        self.assertTrue(r['ok']); self.assertEqual([m['label'] for m in r['models']], ['Opus 5.5'])
        def down(path, data=None, timeout=20): raise OSError('нет')
        self.assertFalse(self._with(down, lambda M: M.agents_public())['ok'])

    def test_page_has_agents_ui(self):
        import cc_notion_ai as M
        for needle in ('naiAgentQ', 'window.naiConsoleOpen', "notion-ai/agents/view/", 'nai-atab', 'Новый агент'):
            self.assertIn(needle, M.UI)


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
    def test_server_address_and_telegram_agent_settings(self):
        ok, _, c = M.save_cfg({'ssh_host': ' srv.example.org '}); self.assertTrue(ok); self.assertEqual(M.load_cfg()['ssh_host'], 'srv.example.org')
        ok, _, _ = M.save_cfg({'ssh_host': '203.0.113.7'}); self.assertTrue(ok)
        ok, _, _ = M.save_cfg({'ssh_host': ''}); self.assertTrue(ok); self.assertEqual(M.load_cfg()['ssh_host'], '')  # пусто — внешний IP сервера
        for bad in ('bad host', 'a;b', 'x' * 120, '-srv'):
            ok, _, _ = M.save_cfg({'ssh_host': bad}); self.assertFalse(ok, bad)
        aid = 'a1b2c3d4-0000-0000-0000-000000000000'
        ok, _, _ = M.save_cfg({'tg_agent': aid}); self.assertTrue(ok); self.assertEqual(M.load_cfg()['tg_agent'], aid)
        ok, _, _ = M.save_cfg({'tg_agent': ''}); self.assertTrue(ok); self.assertEqual(M.load_cfg()['tg_agent'], '')
        ok, _, _ = M.save_cfg({'tg_agent': '../x'}); self.assertFalse(ok)
    def test_notion_api_token_goes_to_its_own_file_and_never_back_to_the_page(self):
        import os as _os
        old = M.PAT_FILE
        M.PAT_FILE = self.d + '/notion_pat'
        self.addCleanup(setattr, M, 'PAT_FILE', old)
        tok = 'ntn_' + 'A1b2C3d4' * 5
        self.assertFalse(M.pat_set())
        for bad in ('abc', 'ntn_short', 'ntn_ bad token with spaces ' + 'x' * 30, 'ghp_' + 'a' * 40):
            ok, m, _ = M.save_cfg({'notion_token': bad}); self.assertFalse(ok, bad); self.assertIn('ntn_', m)
        self.assertFalse(Path(M.PAT_FILE).exists())
        ok, m, c = M.save_cfg({'notion_token': '  ' + tok + '  ', 'owner': 'Аня'}); self.assertTrue(ok, m)
        self.assertEqual(Path(M.PAT_FILE).read_text().strip(), tok)
        self.assertEqual(oct(_os.stat(M.PAT_FILE).st_mode & 0o777), '0o600')
        self.assertTrue(M.pat_set())
        self.assertEqual(M.load_cfg()['owner'], 'Аня')  # остальные поля сохранились вместе с токеном
        pub = json.dumps(M.cfg_public())
        self.assertNotIn(tok, pub); self.assertNotIn('A1b2C3d4', pub)  # ни токена, ни его кусков в ответе панели
        self.assertNotIn(tok, Path(M.CFG_FILE).read_text())              # и в файле настроек его нет
        self.assertTrue(M.cfg_public()['status']['pat'])
        ok, _, _ = M.save_cfg({'notion_token': ''}); self.assertTrue(ok)  # пустое поле — токен не меняется
        self.assertEqual(Path(M.PAT_FILE).read_text().strip(), tok)

    def test_check_tells_whether_the_token_works(self):
        old = (M.PAT_FILE, M._delegate, M.delegate_health, M.tg_me)
        M.PAT_FILE = self.d + '/notion_pat'
        M.delegate_health = lambda: {'auth': 'ok'}
        M.tg_me = lambda fresh=False: ''
        self.addCleanup(lambda: [setattr(M, k, v) for k, v in zip(('PAT_FILE', '_delegate', 'delegate_health', 'tg_me'), old)])
        item = lambda: [x for x in M.cfg_check()['items'] if x['name'] == 'Токен Notion API'][0]
        i = item(); self.assertTrue(i['ok']); self.assertIn('не задан', i['text'])      # не задан — не ошибка, нужен только для агентов
        Path(M.PAT_FILE).write_text('ntn_' + 'x' * 40)
        M._delegate = lambda path, data=None, timeout=20: {'ok': True, 'agents': [1, 2]}
        i = item(); self.assertTrue(i['ok']); self.assertIn('агентов: 2', i['text'])
        M._delegate = lambda path, data=None, timeout=20: {'ok': False, 'error': 'Notion API 401: API token is invalid'}
        i = item(); self.assertFalse(i['ok']); self.assertIn('401', i['text'])
        def down(path, data=None, timeout=20): raise OSError('нет')
        M._delegate = down
        i = item(); self.assertFalse(i['ok']); self.assertIn('не отвечает', i['text'])

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
        self.assertIn('Владелец — Аня', t); self.assertIn('[TG чч:мм]', t); self.assertNotIn('farm', t.lower())
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
        for k in ('id="fleetNotion"', 'naiModelTile', 'naiModelQ', "notion-ai/model", 'fleet-compact-account notion'):
            self.assertIn(k, ui.replace("tile.id='fleetNotion'", 'id="fleetNotion"'), k)
        card = ui[ui.index('Карточка «Notion AI» в «Активных аккаунтах»'):ui.index('Вкладка «Notion AI» в консоли')]
        self.assertNotIn('fleet-live-meter', card)  # ни 5 часов, ни недели
        self.assertNotIn('Без лимитов по времени', card)
        self.assertNotIn('Для лимитов: Settings', card)
        self.assertNotIn('app.notion.com/space', ui)  # общей ссылки «Открыть Notion» на пространство больше нет
        self.assertNotIn('nai-credits-link', ui)
        self.assertIn("CustomEvent('nai-state'", ui)
        self.assertIn("'/api/notion-ai/model'", open(M.__file__, encoding='utf-8').read())


class TestAgentLink(unittest.TestCase):
    """У каждого агента в списке своя стрелка на его чат в Notion (08.11.26)."""

    def test_arrow_links_to_agent_chat(self):
        ui = M.UI
        self.assertIn("'https://app.notion.com/agent/'+h+'?wfv=chat'", ui)
        self.assertIn('class="nai-ag-go"', ui)
        self.assertIn("replace(/-/g,'')", ui)  # id агента в ссылке без дефисов, как в сервисе notion-delegate
        self.assertIn('nai-ag-line', ui)
        self.assertIn('.nai-ag-line .nai-ag-row{flex:1 1 auto;width:auto;margin:0}', ui)  # отступ button не растягивает стрелку

    def test_arrow_is_not_inside_the_settings_button(self):
        ui = M.UI
        row = ui[ui.index('class="nai-ag-line"'):ui.index('nai-ag-go" href')]
        self.assertIn('</button>', row)  # ссылка стоит после закрытия кнопки: <a> внутри <button> недопустим


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


class TestHeaderPopups(unittest.TestCase):
    """Окно справки по аккаунту в шапке (07.11, ): три кнопки PROD не влезали в строку и вылезали из окна."""

    def setUp(self):
        self.src = open(M.__file__, encoding='utf-8').read()

    def test_button_row_wraps_and_text_never_breaks_inside_a_button(self):
        self.assertIn(".nai-pop .nai-row{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}", self.src)
        self.assertIn(".nai-pop button{height:32px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", self.src)

    def test_prod_popup_is_drawn_like_the_reference(self):
        # референс значок, заголовок, «Закрыть» с крестиком, «Включить авто» с переключателем, широкая кнопка с иконкой
        for part in ('class="nai-ph"', 'class="nai-pi ', 'class="nai-sw"', 'role="switch" aria-checked="', "pp.classList.add('ag-'+k,'rich')"):
            self.assertIn(part, self.src)
        self.assertIn(".nai-pop.ag-prod .nai-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px}", self.src)
        self.assertIn(".nai-pop.ag-prod button.nai-yes{grid-column:1/-1;height:40px;background:#6f59f9", self.src)  # главная кнопка на своей строке
        self.assertIn(".nai-pop.rich .nai-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px}", self.src)  # то же окно у DEV, Codex и Notion AI
        self.assertIn("'Claude PROD',codex:'Codex',notion:'Notion AI'})[k])+(gp.text?' - '+esc(gp.text):'')", self.src)  # заголовок как на картинке: «Claude PROD - пауза»
        self.assertIn(".nai-auto[aria-checked=\"true\"] .nai-sw::after{transform:translateX(11px)}", self.src)

    def test_switch_shows_the_real_auto_state(self):
        i = self.src.index("function richPop(k,anchor,rm)")
        body = self.src[i:self.src.index("function ask(anchor)")]
        self.assertIn("ao=!!((rm.auto&&rm.auto()||{}).enabled)", body)
        self.assertIn("aria-checked=\"'+ao+'\"", body)
        # подпись постоянная («Включить авто»), включено/выключено показывает сам переключатель; пояснение — с процентом порога
        self.assertIn('<span class="nai-bl">Включить авто</span>', body)
        self.assertNotIn("'Выключить авто'", body)
        self.assertIn("thr=thrNow()", body)
        self.assertIn("'% лимита работа сама перейдёт на второй аккаунт.'", body)
        self.assertIn("'% лимита работа сама не перейдёт.'", body)
        self.assertNotIn("Автопередача при лимитах: '", body)  # прежняя строка заменена пояснением, лишних строк в окне нет
        self.assertIn("class=\"nai-lnk2\">Изменить порог</a>", body)
        self.assertIn("document.getElementById('gear')", body)  # ссылка открывает «Настройки» с порогом
        self.assertIn("typeof THR==='number'", self.src)
        self.assertIn('class="nai-bl"', body)  # подписи с многоточием: на узком экране не обрезаются молча
        self.assertIn("au.onclick=function(){var on=!((rm.auto()||{}).enabled);", body)  # по клику переключает то же, что раньше


class TestPopupTail(unittest.TestCase):
    """Окна шапки: хвост-облачко указывает на нажатый значок, сам значок подсвечен."""

    def setUp(self):
        with open(M.__file__, encoding='utf-8') as f:
            self.src = f.read()

    def test_tail_points_at_the_pressed_icon(self):
        self.assertIn("tl.className='nai-tail'", self.src)
        self.assertIn("t.style.left=(Math.max(20,Math.min(r.left+r.width/2-left,w-20))-6)+'px'", self.src)  # центр хвоста = центр значка
        self.assertIn("function openPop(html,wide,anchor,cls)", self.src)  # класс окна известен до первого размещения, иначе «над значком» считается по неверной высоте
        self.assertIn("</div>',false,anchor,'ag-'+k+' rich');", self.src)
        self.assertIn("pp.classList.add('ag-'+k,'rich');", self.src)
        self.assertIn("sb.style.overflowY='auto'", self.src)  # места нет ни снизу, ни сверху: прокручивается содержимое, а не вся оболочка с хвостом
        self.assertIn("'<div class=\"nai-pb\">'+html+'</div>'", self.src)
        self.assertIn("pop.classList.toggle('up',up)", self.src)  # нет места снизу — окно над значком, хвост внизу
        self.assertIn(".nai-pop:not(.up) .nai-tail{top:-7px;border-right:0;border-bottom:0}", self.src)
        self.assertIn(".nai-pop.up .nai-tail{bottom:-7px;border-left:0;border-top:0}", self.src)

    def test_pressed_icon_is_highlighted_and_released_on_close(self):
        self.assertIn("popAnchor.classList.add('nai-pressed')", self.src)
        self.assertIn("popAnchor.classList.remove('nai-pressed')", self.src)
        self.assertIn(".nai-seg.nai-pressed{", self.src)

    def test_every_header_popup_gets_its_anchor(self):
        i = self.src.index("function ask(anchor)")
        self.assertIn("</div>',false,anchor,'ag-notion');p.classList.add('ag-notion')", self.src[i:i + 1500])  # раньше окно «Notion AI» не знало, откуда открыто
        self.assertIn("ask(s)", self.src)


class TestHeaderPopupsHandoff(unittest.TestCase):
    """окна всех четырёх значков одинаковые — «авто» у пары DEV↔PROD и кнопка передачи работы у каждого."""

    def setUp(self):
        self.src = open(M.__file__, encoding='utf-8').read()
        i = self.src.index("function richPop(k,anchor,rm)")
        self.body = self.src[i:self.src.index("function ask(anchor)")]

    def test_every_icon_opens_the_same_window(self):
        i = self.src.index("function agentPop(k,anchor)")
        route = self.src[i:i + 260]
        self.assertIn("(k==='prod'||k==='claude'||k==='codex'))return richPop(k,anchor,window.fleetRemote)", route)  # DEV и Codex — раньше старое окно «Закрыть / Выбор профиля»
        j = self.src.index("function ask(anchor)")
        self.assertIn("return richPop('notion',anchor,window.fleetRemote)", self.src[j:j + 220])
        self.assertIn("function agentPop(k,anchor){if(window.fleetRemote&&window.fleetRemote.handInfo", self.src)  # без модуля передачи — прежнее простое окно

    def test_auto_switch_only_for_the_dev_prod_pair(self):
        self.assertIn("pair=k==='claude'||k==='prod'", self.body)
        self.assertIn("(pair?'<button type=\"button\" class=\"nai-auto\"", self.body)

    def test_handoff_button_target_rule(self):
        # работа не у этого агента — одна кнопка «Передать работу в <он>»; работа у него — блок из трёх кнопок
        self.assertIn("act=wk===own,hi=act?null:rm.handInfo(own,md)", self.body)
        self.assertIn("(act?hand3(own,md,rm):'<button type=\"button\" class=\"nai-yes\"", self.body)
        self.assertIn("rm.hand(own,anchor)", self.body)
        self.assertIn("(hi.dis?' disabled':'')", self.body)

    def test_active_model_gets_three_buttons_for_the_other_three(self):
        i = self.src.index("function hand3(own,md,rm)")
        f = self.src[i:self.src.index("function richPop(k,anchor,rm)")]
        self.assertIn("['dev','prod','codex','notion'].filter(function(t){return t!==own})", f)   # всегда остальные три, себя нет
        self.assertIn("rm.handInfo(t,md)", f)                                                    # доступность та же, что у кнопок плиток
        self.assertIn("(h.dis?' disabled':'')", f)
        self.assertIn('class="nai-h3n"', f)                                                      # почему серая — видно и на телефоне, без подсказки
        self.assertIn("pp.querySelectorAll('.nai-h3').forEach(function(b){b.onclick=function(){var t=this.dataset.t;closePop();rm.hand(t,anchor)}});", self.body)
        self.assertIn(".nai-pop.rich .nai-hand3{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}", self.src)

    def test_profile_picker_stays_reachable_as_a_link(self):
        self.assertIn('class="nai-lnk">Выборе профиля</a>', self.body)
        self.assertIn("document.getElementById('cxBtn')", self.body)

    def test_notion_keeps_its_off_switch(self):
        self.assertIn("notionOn?'<button type=\"button\" class=\"nai-tog\">", self.body)
        self.assertIn("send('off',{})", self.body)

    def test_remote_ui_exports_what_the_window_needs(self):
        import cc_remote_ui as U
        self.assertIn("handInfo:handInfo,hand:hOpen", U.JS)
        i = U.JS.index("function handInfo(tg,md)")
        self.assertIn("here||busy||off||lock", U.JS[i:i + 900])
        j = U.JS.index("function paintHand()")
        self.assertIn("handInfo(b.dataset.target,md)", U.JS[j:j + 300])  # кнопки плиток и окна значков берут состояние из одного места


class TestUnifiedWindows(unittest.TestCase):
    """Окна шестерёнок и моделей: одно правило размещения, одна прокрутка, скрытое остаётся скрытым."""

    def setUp(self):
        import cc_overview as O
        self.js, self.css = O.JS, O.CSS

    def test_project_knows_nothing_about_the_supervisor(self):
        # проект лежит на GitHub и ставится другими людьми без супервизора; балансер у него открывается чистой страницей
        import cc_notion_ai as N
        for name, text in (("cc_overview", self.js + self.css), ("cc_notion_ai", open(N.__file__, encoding="utf-8").read())):
            self.assertNotIn("svnav", text, name)
            self.assertNotIn("fleetTop", text, name)

    def test_one_placement_rule_for_every_window(self):
        self.assertIn("window.fleetPlace=function(panel,anchor,width)", self.js)
        self.assertIn("function placePanel(panel,anchor,width){window.fleetPlace(panel,anchor,width)}", self.js)
        # под кнопкой, если помещается целиком; иначе над ней; иначе сдвигаем вверх, а не режем окно
        self.assertIn("const top=below+h<=vh-gap?below:above>=gap?above:Math.max(gap,vh-gap-h);", self.js)
        self.assertIn("panel.style.maxHeight=(vh-gap*2)+'px'", self.js)
        self.assertNotIn("Math.min(r.bottom+8,Math.max(12,innerHeight-240))", self.js)  # прежний «остаток под кнопкой»
        self.assertIn("new ResizeObserver(", self.js)  # содержимое выросло после открытия — окно встаёт заново

    def test_other_files_use_the_same_rule(self):
        import cc_notion_ai as N, cc_remote_ui as R
        def read(m):
            with open(m.__file__, encoding="utf-8") as f:
                return f.read()
        self.assertIn("window.fleetPlace(q,t,340)", read(N))
        self.assertIn("window.fleetPlace(pop,a,580)", read(N))
        self.assertIn("window.fleetPlace(qp,t,340)", read(R))

    def test_hidden_window_stays_hidden(self):
        # регрессия: правило display:flex перебило [hidden] и скрытые окна торчали ниже экрана
        self.assertIn(".fleet-quick-panel:not([hidden]),html:root:root:root .fleet-settings-panel:not([hidden]){display:flex", self.css)
        self.assertIn(".fleet-quick-panel[hidden],html:root:root:root .fleet-settings-panel[hidden]{display:none}", self.css)

    def test_only_the_body_scrolls(self):
        self.assertIn(".fleet-settings-panel>.cxpbody{flex:1 1 auto;min-height:0;overflow-x:hidden;overflow-y:auto", self.css)
        self.assertIn(".fleet-quick-panel .cxqlist{max-height:none;overflow:visible}", self.css)
        self.assertIn(".fleet-settings-panel .fleet-model-catalog{max-height:none;overflow:visible}", self.css)


class TestActiveStrip(unittest.TestCase):
    """Активные аккаунты одной полосой."""

    def setUp(self):
        import cc_overview
        self.css = cc_overview.CSS
        self.js = cc_overview.JS

    def test_phone_console_fills_the_screen(self):
        # на телефоне окно консоли (вкладки, консоль, ввод) тянется до низа экрана, «Активные аккаунты» ниже, после прокрутки
        self.assertIn("html.fleet-term-fill:root:root:not(.conly) .termwrap{height:var(--fleet-term-fill)!important;min-height:0}", self.css)
        self.assertIn(".termwrap .fleet-console-viewport{flex:1 1 0;height:auto;min-height:150px}", self.css)
        self.assertIn("function fitConsoleFill(){", self.js)
        self.assertIn("h=Math.max(380,Math.round(vh-top-12))", self.js)  # экран минус верх окна минус поле 12 px, но не ниже 380
        self.assertIn("document.activeElement===input&&fillShown&&h<fillShown", self.js)  # экранная клавиатура окно не сжимает
        self.assertIn("window.visualViewport?.addEventListener('resize',fitConsoleFill)", self.js)
        # без посчитанной высоты (рабочий стол, полный экран) прежняя раскладка: правила привязаны к классу fleet-term-fill
        self.assertEqual(self.css.count("height:var(--fleet-term-fill)"), 1)  # переменная нужна только одному правилу, и оно привязано к классу

    def test_fullscreen_dock_lists_every_engine(self):
        # нижняя панель полного экрана показывала только аккаунты Claude; PROD, Codex и Notion AI достраиваются из ячеек полосы
        self.assertIn("function dockExtras(){", self.js)
        self.assertIn("c.dataset.engine!=='claude'", self.js)  # родные аккаунты Claude рисует прежний код
        self.assertIn("window.renderDock=function(){const r=rd.apply(this,arguments);try{dockExtras()}catch(e){}return r}", self.js)
        self.assertIn("dchip dx ", self.js)  # метка dx у достроенных чипов
        self.assertIn("ag-pause-'+eng", self.js)
        self.assertIn(".dpop .dsub{", self.css)

    def test_prod_has_the_same_settings_window_as_claude(self):
        # у PROD должно быть столько же настроек, сколько у родного Claude
        import cc_remote_ui as U
        js = U.JS
        self.assertIn('class="hdrgear fleet-provider-gear rm-gear" title="Настройки PROD"', js)        # шестерёнка в плитке
        self.assertIn("sp.className='cxpop fleet-settings-panel rm-settings'", js)                    # то же окно, что у Claude и Codex
        self.assertIn("window.fleetPlace(sp,spBtn,580)", js)                                          # то же размещение
        self.assertIn('<h3>Настройки PROD</h3>', js)
        for group in ('Переключение и лимиты', 'Модели в быстром меню'):
            self.assertIn('<div class="fleet-settings-group-title">' + group + '</div>', js)
        self.assertNotIn('group-title">Аккаунты и копии', js)                                         # вход друга не копируем
        self.assertIn("post('config',{threshold:t,weekly_cap:c})", js)                                 # пороги общие с родным Claude
        self.assertIn('<input type="checkbox" class="rm-wk">', js)                                     # пауза на недельном потолке (общая настройка weekly_pause)
        self.assertIn("post('config',{weekly_pause:c.checked})", js)
        self.assertIn('<input type="checkbox" class="rm-auto">', js)                                  # автопередача — тот же обработчик, что в шапке и карточке
        self.assertIn("box.append.apply(box,nodes)", js)                                              # настоящий пул моделей переезжает в окно и обратно
        self.assertIn("g.append(n)", js)
        self.assertIn("sClose();\n", js)                                                              # быстрый выбор модели закрывает окно настроек

    def test_header_has_no_refresh_now_icon(self):
        # иконки «Обновить сейчас» рядом с шестерёнкой нет; сам элемент остаётся, на него ссылаются скрипты (title, disabled, вставка панели Notion перед ним)
        self.assertIn("html:root:root .hdr #rfBtn{display:none!important}", self.css)
        import cc_limits as L
        self.assertIn('id="rfBtn"', L.PAGE if hasattr(L, "PAGE") else open(L.__file__, encoding="utf-8").read())

    def test_fold_arrow_stays_where_the_unfold_arrow_was(self):
        # стрелка «свернуть» раскрытой плитки не уезжает влево за название, а стоит там же, где стрелка «развернуть» свёрнутой ячейки
        css = self.css
        tile = "html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open"
        self.assertIn(tile + ">.fleet-live-account{position:relative}", css)
        self.assertIn(tile + " .fleet-live-name{padding-right:34px}", css)  # длинное название не заезжает под стрелку
        self.assertIn(tile + " .fleet-live-name::after{position:absolute;right:17px;top:19px;width:7px;height:7px;margin:0;vertical-align:baseline}", css)
        # те же границы ширины, что у стрелки ячейки: плотный режим 1260–1579 и телефонный до 900
        self.assertIn("@media(min-width:1260px) and (max-width:1579px){" + tile + " .fleet-live-name::after{right:14px}}", css)
        self.assertIn("@media(max-width:900px){" + tile + " .fleet-live-name::after{right:21px;top:20.5px}}", css)
        # прежнее «в потоке за названием» (margin-left у ::after раскрытой плитки) не должно вернуться в полосу
        strip = css[css.index("Стрелка «свернуть» у раскрытой плитки"):]
        self.assertNotIn("margin-left:9px", strip[:1500])

    def test_cells_sit_side_by_side_only_when_there_is_room(self):
        # у него две строки при ширине окна меньше 1580 px — порог снижен до 1260 px, ячейки плотнее
        self.assertIn("@media(min-width:1260px){html:root:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{grid-template-columns:repeat(2,minmax(0,1fr))}}", self.css)
        self.assertIn("@media(min-width:1260px) and (max-width:1579px){", self.css)  # плотный вид: зазоры 9px, шрифт 11.5px
        self.assertIn("@media(min-width:1260px) and (max-width:1379px){", self.css)  # самый узкий: без подписей «Модель:» и «Effort:»
        self.assertNotIn("@media(min-width:1580px){html:root:root:root #fleetActiveAccounts", self.css)
        self.assertIn(".fleet-compact-account:has(.fleet-compact-warning:not(:empty)) .fleet-compact-window[data-window=\"week\"] .fleet-compact-range{display:none}", self.css)  # с пометкой «проверить» на узком экране дата не помещается
        self.assertIn("#fleetActiveAccounts.fleet-acc-mode .fleet-acc.open{grid-column:1/-1}", self.css)  # раскрытый аккаунт занимает всю ширину

    def test_only_claude_accounts_share_a_row(self):
        # «в одну строку — только аккаунты Claude»; Codex и Notion AI — каждый на всю ширину
        self.assertIn(".fleet-acc:has(>.fleet-compact-account.codex),", self.css)
        self.assertIn(".fleet-acc:has(>.fleet-compact-account.notion){grid-column:1/-1}", self.css)

    def test_active_account_is_framed_by_its_own_border_without_overlap(self):
        for e in ("claude", "prod", "codex", "notion"):
            self.assertIn("html:root:root:root.ag-live-%s #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.%s" % (e, e), self.css)
        self.assertIn("{border-color:#49d6aa;box-shadow:none}", self.css)  # рамка на границе ячейки, тени и отрицательных отступов нет
        self.assertNotIn("inset 0 0 0 1px #49d6aa}\nhtml:root:root:root", self.css)

    def test_reference_pieces_are_there(self):
        self.assertNotIn('content:"пауза"', self.css)  # серой плашки «пауза» в строке аккаунта нет, состояние — значок ⏸
        self.assertNotIn('· пауза";color:var(--fleet-muted)', self.css)  # и текста « · пауза» через точку тоже
        self.assertIn('.fleet-compact-name::before{content:"";display:inline-block;flex:none;', self.css)  # значок не схлопывается у длинного имени
        import cc_remote_ui
        self.assertNotIn('.fleet-compact-name::after{content:" · пауза"', open(cc_remote_ui.__file__, encoding='utf-8').read())  # у PROD так же
        self.assertIn('.fleet-compact-window[data-window="week"] .fleet-compact-range::before', self.css)  # значок календаря у даты сброса
        # время сброса окна 5ч по Иркутску показывается и в свёрнутой строке (раньше было скрыто)
        self.assertIn('.fleet-compact-window[data-window="session"] .fleet-compact-range{display:inline-flex', self.css)
        self.assertNotIn('.fleet-compact-window[data-window="session"] .fleet-compact-range{display:none}', self.css)
        self.assertIn('function fiveHourClock(date)', self.js)
        self.assertIn("liveClockFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:window.FLEET_TZ", self.js)  # время только по Иркутску
        self.assertIn("text=minutes<=0?'сброс ожидается':fiveHourClock(end)+' · через '", self.js)  # в плитке: «20:00 · через 35 мин»
        self.assertIn("@media(min-width:1380px) and (max-width:1899px){", self.css)  # DEV и PROD делят строку: подписи колонок убраны
        self.assertIn("weekday:'short'", self.js)  # «пт 13.11 02:00»
