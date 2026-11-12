"""Возобновление только получателя; работа и собственная квота отправителя не затрагиваются."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cc_profiles import NativeProfiles, Profiles
from cc_profile_state import ProfileState
from cc_claude_profile import ProfileError
from test_cc_profiles import FakeNative, legacy_pair_state


class HandoffNative(FakeNative):
    def __init__(self):
        super().__init__()
        self.receiving_busy = set()
        self.checked = []

    def busy_for(self, engine):
        self.checked.append(engine)
        return engine in self.receiving_busy

    def preflight(self, before, after, changed, captured, handoff_engine=None):
        if handoff_engine:
            assert changed == [handoff_engine]
            if self.busy_for(handoff_engine):raise ProfileError('console_busy')


class Activation(unittest.TestCase):
    def setup_profiles(self, root, sender):
        native=HandoffNative();profiles=Profiles(root,native)
        choices={engine:'full' if engine==sender else None for engine in ('claude','codex')}
        result=profiles.apply_scenario(dict(choices=choices,confirm='подтверждаю',revision=profiles.state.revision))
        self.assertTrue(result['ok'],result)
        native.applied.clear()
        return profiles,native

    def test_both_directions_preserve_sender_plan_and_own_quota(self):
        for sender,receiver in (('claude','codex'),('codex','claude')):
            with self.subTest(sender=sender),tempfile.TemporaryDirectory() as root,patch.object(ProfileState,'codex_independent',staticmethod(lambda:False)):
                profiles,native=self.setup_profiles(root,sender)
                quota=Path(root)/'pause_state.json';quota.write_text(json.dumps({'active':True,'kind':'week','resume_at':1800007200}))
                before=quota.read_bytes();sender_plan=copy.deepcopy(native.plan(profiles.state,sender))
                native.busy_value=True  # отправитель работает, получатель свободен
                result=profiles.resume_for_handoff(receiver)
                self.assertTrue(result['ok'],result)
                self.assertEqual(native.plan(profiles.state,sender),sender_plan)
                self.assertFalse(profiles.paused(sender));self.assertFalse(profiles.paused(receiver))
                self.assertEqual(native.applied[-1][2],[receiver])
                self.assertEqual(quota.read_bytes(),before)
                restored=Profiles(root,HandoffNative())
                self.assertFalse(restored.paused(sender));self.assertFalse(restored.paused(receiver))

    def test_already_active_receiver_does_not_reconfigure_either_console(self):
        with tempfile.TemporaryDirectory() as root:
            native=HandoffNative();profiles=Profiles(root,native);before=profiles.state.export()
            self.assertTrue(profiles.resume_for_handoff('codex')['ok'])
            self.assertEqual(profiles.state.export(),before);self.assertEqual(native.applied,[])

    def test_busy_receiver_does_not_change_profiles(self):
        with tempfile.TemporaryDirectory() as root,patch.object(ProfileState,'codex_independent',staticmethod(lambda:False)):
            profiles,native=self.setup_profiles(root,'claude');before=profiles.state.export()
            native.receiving_busy.add('codex')
            self.assertTrue(profiles.resume_for_handoff('codex').get('busy'))
            self.assertEqual(profiles.state.export(),before);self.assertEqual(native.applied,[])

    def test_failure_rolls_back_only_receiver(self):
        with tempfile.TemporaryDirectory() as root,patch.object(ProfileState,'codex_independent',staticmethod(lambda:False)):
            profiles,native=self.setup_profiles(root,'claude');before=profiles.state.export();native.fail=True
            self.assertFalse(profiles.resume_for_handoff('codex')['ok'])
            self.assertEqual(profiles.state.export(),before)
            self.assertEqual(native.rollbacks,[['codex']]);self.assertFalse(profiles.pending.exists())

    def test_sender_change_is_rejected_before_any_console_operation(self):
        with tempfile.TemporaryDirectory() as root:
            profiles,native=self.setup_profiles(root,'claude');before=profiles.state.export()
            candidate=legacy_pair_state('codex',profiles.state)
            self.assertFalse(profiles.transition(candidate,'invalid handoff',handoff_engine='codex')['ok'])
            self.assertEqual(profiles.state.export(),before);self.assertEqual(native.applied,[])

    def test_dry_run_has_no_state_or_console_effect(self):
        with tempfile.TemporaryDirectory() as root,patch.object(ProfileState,'codex_independent',staticmethod(lambda:False)):
            profiles,native=self.setup_profiles(root,'codex');before=profiles.state.export()
            self.assertTrue(profiles.resume_for_handoff('claude',dry_run=True)['ok'])
            self.assertEqual(profiles.state.export(),before);self.assertEqual(native.applied,[])


class BusyScope(unittest.TestCase):
    def test_codex_turn_does_not_mark_claude_busy(self):
        native=NativeProfiles.__new__(NativeProfiles)
        native.ns={'session_busy':lambda:False}
        native.codex=SimpleNamespace(busy=lambda:True)
        native.bridge=SimpleNamespace(BRIDGE=SimpleNamespace(busy=lambda:True))
        native.manager=SimpleNamespace(input_allowed=lambda e:True)
        self.assertFalse(native.busy_for('claude'))
        self.assertTrue(native.busy_for('codex'));self.assertTrue(native.busy())


if __name__=='__main__':unittest.main()
