"""Профиль Claude «Opus → Sonnet»: выбор моделей из пула, политика и запуск консоли, сторож модели."""
import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cc_limits
from cc_claude_profile import ClaudeProfile, ProfileError
from cc_manual_scenarios import DUO_ID
from cc_profile_state import ProfileState
from cc_profiles import NativeProfiles

POOL = {
    'claude-opus-5-5': 'Opus 5.5', 'claude-opus-5-1': 'Opus 5.1', 'claude-opus-4-8': 'Opus 4.8',
    'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-sonnet-5': 'Sonnet 5', 'claude-haiku-5-5': 'Haiku 5.5',
    'claude-sonnet-5-5-20261001': 'Sonnet 5.5 (дата)',
}


def duo_state(engine_claude='duo'):
    state = ProfileState()
    assert state.apply_scenario({'claude': engine_claude, 'codex': None}, 'подтверждаю', state.revision)['ok']
    return state


def full_state():
    state = ProfileState()
    assert state.apply_scenario({'claude': 'full', 'codex': None}, 'подтверждаю', state.revision)['ok']
    return state


def make_native(tmp, pool=None, cfg=None, settings_model='claude-sonnet-5-5'):
    """NativeProfiles без реальных консолей: только то, что нужно политике, промпту и выбору модели."""
    pool = POOL if pool is None else pool
    native = NativeProfiles.__new__(NativeProfiles)
    native.ns = {
        'cfg': lambda: dict(cfg or {}),
        'all_models': lambda: dict(pool),
        'jload': lambda path, default=None: {'model': settings_model} if path == 'SETTINGS' else default,
        'SETTINGS': 'SETTINGS',
        'effort_support': lambda model: ('low', 'medium', 'high') if 'sonnet' in model else ('low', 'medium', 'high', 'xhigh', 'max'),
    }
    native.base = Path(tmp)
    native.claude_cwd = str(Path(tmp) / 'cwd')
    native.claude_work = str(Path(tmp) / 'work')
    native.bridge = types.SimpleNamespace(project_dir=lambda: '', team_note=lambda *a, **k: '')
    native.manager = types.SimpleNamespace(exchange=lambda e: Path(tmp) / 'ex' / e)
    return native


class DuoModels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)

    def test_takes_latest_opus_and_latest_sonnet_from_the_pool(self):
        self.assertEqual(make_native(self.tmp.name).duo_models(), ('claude-opus-5-5', 'claude-sonnet-5-5'))

    def test_version_is_not_hardcoded(self):
        pool = dict(POOL);pool.update({'claude-opus-5-9': 'Opus 5.9', 'claude-sonnet-6': 'Sonnet 6'})
        self.assertEqual(make_native(self.tmp.name, pool).duo_models(), ('claude-opus-5-9', 'claude-sonnet-6'))

    def test_hidden_and_disabled_models_are_skipped(self):
        cfg = {'model_hidden': ['claude-opus-5-5']}
        self.assertEqual(make_native(self.tmp.name, cfg=cfg).duo_models()[0], 'claude-opus-5-1')
        cfg = {'enabled_models': ['claude-opus-5-1', 'claude-sonnet-5']}
        self.assertEqual(make_native(self.tmp.name, cfg=cfg).duo_models(), ('claude-opus-5-1', 'claude-sonnet-5'))

    def test_dated_and_other_families_are_never_picked(self):
        pool = {'claude-sonnet-5-5-20261001': 'x', 'claude-haiku-5-5': 'y', 'claude-opus-5-5': 'Opus 5.5'}
        with self.assertRaises(ProfileError) as cm:make_native(self.tmp.name, pool).duo_models()
        self.assertEqual(str(cm.exception), 'duo_models_missing')

    def test_missing_opus_or_sonnet_is_a_clear_error(self):
        for pool in ({'claude-sonnet-5-5': 'S'}, {'claude-opus-5-5': 'O'}, {}):
            with self.assertRaises(ProfileError) as cm:make_native(self.tmp.name, pool).duo_models()
            self.assertEqual(str(cm.exception), 'duo_models_missing')


class DuoPolicyAndPrompt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.native = make_native(self.tmp.name)

    def test_duo_policy_carries_models_and_executor_agent(self):
        policy = self.native.claude_policy(duo_state())
        self.assertEqual(policy['access'], 'full');self.assertFalse(policy['paused'])
        self.assertEqual(policy['expected_model'], 'claude-opus-5-5');self.assertEqual(policy['subagent_model'], 'claude-sonnet-5-5')
        self.assertEqual(list(policy['agents']), ['executor']);self.assertEqual(policy['agents']['executor']['model'], 'claude-sonnet-5-5')
        json.dumps(policy, ensure_ascii=False)  # политика пишется в файл для хука — должна сериализоваться

    def test_full_policy_has_no_duo_keys(self):
        policy = self.native.claude_policy(full_state())
        for key in ('expected_model', 'subagent_model', 'agents'):self.assertNotIn(key, policy)

    def test_duo_prompt_names_both_models_and_forbids_own_edits(self):
        text = self.native.prompt(duo_state(), 'claude')
        self.assertIn('Opus 5.5', text);self.assertIn('Sonnet 5.5', text);self.assertIn('subagent_type=executor', text)
        self.assertIn('Сам проект не меняй', text);self.assertIn('Codex в этом профиле не участвует', text)

    def test_full_prompt_is_not_the_duo_prompt(self):
        self.assertNotIn('executor', self.native.prompt(full_state(), 'claude'))


class DuoConsoleModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.native = make_native(self.tmp.name)
        self.snap = dict(model='claude-sonnet-5-5', effort='high', thread_id='t')

    def test_entering_duo_switches_console_to_opus_and_keeps_supported_effort(self):
        out = self.native._claude_snapshot(self.snap, full_state(), duo_state())
        self.assertEqual(out['model'], 'claude-opus-5-5');self.assertEqual(out['effort'], 'high')
        self.assertEqual(self.snap['model'], 'claude-sonnet-5-5')  # исходный снимок не мутируется

    def test_unsupported_effort_is_dropped_when_model_changes(self):
        snap = dict(self.snap, model='claude-opus-5-5', effort='max')
        out = self.native._claude_snapshot(snap, duo_state(), full_state())
        self.assertEqual(out['model'], 'claude-sonnet-5-5');self.assertIsNone(out['effort'])

    def test_leaving_duo_returns_the_default_model_from_settings(self):
        snap = dict(self.snap, model='claude-opus-5-5')
        self.assertEqual(self.native._claude_snapshot(snap, duo_state(), full_state())['model'], 'claude-sonnet-5-5')

    def test_other_transitions_keep_the_snapshot_untouched(self):
        self.assertEqual(self.native._claude_snapshot(self.snap, full_state(), full_state()), self.snap)
        self.assertEqual(self.native._claude_snapshot(self.snap, duo_state(), duo_state()), self.snap)


class DuoPreflight(unittest.TestCase):
    def test_prod_remote_session_refuses_duo(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = make_native(tmp)
            native.ns['REMOTE_MODE'] = types.SimpleNamespace(active=lambda: True, ready=True)
            native.claude = types.SimpleNamespace(prepare=lambda *a, **k: None)
            native.busy = lambda: False
            native.ns['cc_codex'] = types.SimpleNamespace(own=lambda p: None)
            native.bridge = types.SimpleNamespace(_state=lambda: {}, project_dir=lambda: '', team_note=lambda *a, **k: '')
            with self.assertRaises(ProfileError) as cm:
                native.preflight(full_state(), duo_state(), ['claude'], {'claude_remote': {'tg': True}})
            self.assertEqual(str(cm.exception), 'claude_duo_prod_unsupported')


class DuoCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        cmd = '/usr/bin/claude --resume --dangerously-skip-permissions --agents {"old":{}} --channels plugin:telegram'
        self.adapter = ClaudeProfile(dict(BASE=self.tmp.name, cfg=lambda: dict(claude_cmd=cmd)))
        self.snap = dict(thread_id='11111111-1111-1111-1111-111111111111', model='claude-opus-5-5', effort='high')
        self.policy = dict(access='full', subagent_model='claude-sonnet-5-5',
                           agents=dict(executor=dict(description='d', prompt='p', model='claude-sonnet-5-5')))

    def test_duo_command_sets_subagent_env_model_and_agents(self):
        argv = self.adapter.command(self.snap, self.policy, 'role')
        self.assertIn('CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-5-5', argv[:argv.index('/usr/bin/claude')])
        self.assertEqual(argv[argv.index('--model') + 1], 'claude-opus-5-5')
        agents = json.loads(argv[argv.index('--agents') + 1])
        self.assertEqual(agents['executor']['model'], 'claude-sonnet-5-5')
        self.assertEqual(argv.count('--agents'), 1)  # прежний --agents из команды запуска заменён нашим
        self.assertNotIn('old', agents)

    def test_command_without_duo_keeps_user_agents_and_sets_no_subagent_env(self):
        argv = self.adapter.command(self.snap, dict(access='full'), 'role')
        self.assertFalse([a for a in argv if a.startswith('CLAUDE_CODE_SUBAGENT_MODEL')])
        self.assertIn('--agents', argv)  # без профиля пользовательские флаги не трогаем

    def test_agents_json_keeps_cyrillic_unescaped(self):
        self.policy['agents']['executor']['description'] = 'Исполнитель на Sonnet'
        argv = self.adapter.command(self.snap, self.policy, 'role')
        self.assertIn('Исполнитель на Sonnet', argv[argv.index('--agents') + 1])


class ModelWatchExpectsProfileModel(unittest.TestCase):
    """Сторож модели не должен слать «модель сменилась», когда Opus выбран профилем, а дефолт в настройках — Sonnet."""

    def setUp(self):
        self.mw = copy.deepcopy(cc_limits._MW)
        self.addCleanup(lambda: (cc_limits._MW.clear(), cc_limits._MW.update(self.mw)))
        cc_limits._MW.update(cand=None, cand_n=0, last='Sonnet 5.5', away=False)
        self.sent = []
        self.expected = None
        pool = {'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-opus-5-5': 'Opus 5.5'}

        def fake_jload(path, default=None):
            path = str(path)
            if path.endswith('claude-policy.json'):
                return {'expected_model': self.expected} if self.expected else {}
            return {'model': 'claude-sonnet-5-5'}

        for target, value in (('jload', fake_jload), ('all_models', lambda: pool), ('tg_notify', lambda m: self.sent.append(m)),
                              ('status_model_name', lambda txt: txt)):
            p = patch.object(cc_limits, target, value);p.start();self.addCleanup(p.stop)

    def tick(self, name):
        cc_limits._model_watch_tick(name);cc_limits._model_watch_tick(name)

    def test_switch_to_opus_without_profile_is_reported(self):
        self.tick('Opus 5.5')
        self.assertEqual(len(self.sent), 1);self.assertIn('Opus 5.5', self.sent[0])

    def test_switch_to_opus_is_silent_when_the_profile_expects_it(self):
        self.expected = 'claude-opus-5-5'
        self.tick('Opus 5.5')
        self.assertEqual(self.sent, [])

    def test_other_model_under_duo_is_still_reported(self):
        self.expected = 'claude-opus-5-5'
        self.tick('Haiku 5.5')
        self.assertEqual(len(self.sent), 1)


if __name__ == '__main__':unittest.main()
