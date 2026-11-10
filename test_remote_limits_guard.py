import ast
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cc_remote as R
import cc_remote_limits as L
import cc_remote_mode as M
import remote_guard as G

NOW = 1800000000
FUTURE = "2099-01-01T00:00:00+00:00"


def row(pct=90, week=10, **kw):
    return dict(five_hour=dict(pct=pct, resets_at=FUTURE), seven_day=dict(pct=week, resets_at=FUTURE),
                online=True, error="", ts=NOW, **kw)


class Budget(unittest.TestCase):
    def setUp(self):
        self.policy = dict(enabled=True, threshold=90, weekly_cap=99, weekly_pause=True)

    def test_session_threshold(self):
        self.assertFalse(G.budget(self.policy, row(89), NOW)["blocked"])
        self.assertTrue(G.budget(self.policy, row(90), NOW)["blocked"])
        self.assertTrue(G.budget(self.policy, row(100), NOW)["blocked"])

    def test_weekly_preference_and_hard_cap(self):
        self.assertTrue(G.budget(self.policy, row(0, 99), NOW)["blocked"])
        self.policy["weekly_pause"] = False
        self.assertFalse(G.budget(self.policy, row(0, 99), NOW)["blocked"])
        self.assertTrue(G.budget(self.policy, row(0, 100), NOW)["blocked"])

    def test_disabled_and_override(self):
        for key, value in (("enabled", False), ("override", True)):
            self.assertFalse(G.budget(dict(self.policy, **{key: value}), row(100, 100), NOW)["blocked"])

    def test_all_windows_must_reset(self):
        data = row(100, 100)
        data["five_hour"]["resets_at"] = "2026-01-01T00:00:00Z"
        self.assertTrue(G.budget(self.policy, data, NOW)["blocked"])
        data["seven_day"]["resets_at"] = "2026-01-01T00:00:00Z"
        self.assertFalse(G.budget(self.policy, data, NOW)["blocked"])

    def test_unknown_usage_does_not_become_exhausted(self):
        self.assertFalse(G.budget(self.policy, {}, NOW)["blocked"])
        self.assertFalse(G.budget(self.policy, dict(error="ssh"), NOW)["blocked"])

    def test_known_high_usage_survives_error_until_reset(self):
        data = row(100)
        data["error"] = "token_expired"
        self.assertTrue(G.budget(self.policy, data, NOW)["blocked"])

    def test_latest_reset_and_unknown_reset(self):
        data = row(100, 100)
        data["five_hour"]["resets_at"] = "2098-01-01T00:00:00Z"
        state = G.budget(self.policy, data, NOW)
        self.assertEqual(state["resume_at"], G.reset_at(FUTURE) + G.RESET_GRACE)
        data["seven_day"]["resets_at"] = ""
        self.assertEqual(G.budget(self.policy, data, NOW)["resume_at"], 0)


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for key, value in dict(BASE=self.base, POLICY=self.base/"p.json", CACHE=self.base/"c.json",
                               SETTINGS=self.base/"settings.json").items():
            p = patch.object(G, key, value);p.start();self.addCleanup(p.stop)

    def install(self, pct=100):
        G.configure(dict(enabled=True, threshold=90, weekly_pause=True, weekly_cap=99, row=dict(row(pct), ts=time.time())))

    def test_preserves_private_data_boundary(self):
        self.install()
        self.assertEqual(os.stat(G.POLICY).st_mode & 0o777, 0o600)
        self.assertNotIn("row", G.load(G.POLICY))
        settings = G.load(G.SETTINGS)
        for event in ("PreToolUse", "UserPromptSubmit"):
            handler = settings["hooks"][event][0]["hooks"][0]
            self.assertEqual(handler["onFailure"], "block")
            self.assertGreater(handler["timeout"], 7*86400)

    def test_tool_and_prompt_wait_then_resume_same_call(self):
        for event in ("PreToolUse", "UserPromptSubmit"):
            self.install()
            calls = []
            def release(seconds):
                calls.append(seconds)
                self.assertEqual(G.waiters(), 1)
                self.install(0)
            with patch.object(G.time, "sleep", side_effect=release):
                G.hook(dict(hook_event_name=event))
            self.assertEqual(calls, [2])
            self.assertEqual(G.waiters(), 0)

    def test_policy_off_releases_waiter(self):
        self.install()
        with patch.object(G.time, "sleep", side_effect=lambda _: G.configure(dict(enabled=False))):
            G.hook(dict(hook_event_name="PreToolUse"))
        self.assertEqual(G.waiters(), 0)

    def test_unrelated_event_does_not_wait(self):
        self.install()
        with patch.object(G.time, "sleep") as sleep:
            G.hook(dict(hook_event_name="Stop"))
        sleep.assert_not_called()

    def test_api_failure_keeps_cached_quota(self):
        self.install()
        with patch.object(G.time, "time", return_value=time.time()+200), patch.object(G.subprocess, "run", side_effect=OSError):
            self.assertEqual(G.quota(G.load(G.POLICY))["five_hour"]["pct"], 100)

    def test_sensitive_usage_fields_are_not_saved(self):
        self.assertNotIn("email", G.row_only(dict(row(), email="private@example.invalid", access_token="not-for-storage")))


class Panel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.sent = [];self.calls = []
        self.config = dict(threshold=90, weekly_pause=True)
        self.info = dict(ok=True, applied=True, running=True, configured=True, waiting=1, blocked=True,
                         reasons=["5 ч: 90%"], resume_at=NOW+1000)
        for obj, name, value in (
            (L, "STATE_FILE", self.tmp.name+"/state.json"), (L, "_deployed", {}),
            (R, "members", lambda: {"remote":dict(host="192.0.2.1",label="Другой сервер")}),
            (R, "cached", lambda: {"remote": row()}),
            (M, "mode", lambda: dict(active=True,member="remote")), (M, "busy", lambda: False),
            (M, "deploy_tools", lambda member: True), (R, "ctl", self.ctl),
        ):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.ns=dict(cfg=lambda:self.config,tg_notify=self.sent.append)

    def ctl(self, mid, cmd, **kw):
        self.calls.append((cmd,kw))
        return dict(ok=True) if cmd=="guard-config" else dict(self.info)

    def test_pause_is_independent_of_auto_transfer(self):
        with patch("cc_remote_auto.load", return_value=dict(enabled=False)):
            L.tick(self.ns)
        self.assertTrue(L.public()["remote"]["blocked"])
        self.assertEqual(len(self.sent),1)

    def test_no_duplicate_after_panel_restart(self):
        L.tick(self.ns);L._deployed.clear();L.tick(self.ns)
        self.assertEqual(len(self.sent),1)

    def test_recovery_and_rearm(self):
        L.tick(self.ns);self.info["blocked"]=False;L.tick(self.ns)
        self.assertEqual(len(self.sent),2)
        self.assertIn("снята",self.sent[-1])
        self.info["blocked"]=True;L.tick(self.ns)
        self.assertEqual(len(self.sent),3)

    def test_respects_pause_notification_preference(self):
        self.config["pause_notify"]=False;L.tick(self.ns)
        self.assertTrue(L.public()["remote"]["blocked"])
        self.assertEqual(self.sent,[])

    def test_enabling_notifications_during_pause_sends_notice(self):
        self.config["pause_notify"]=False;L.tick(self.ns)
        self.config["pause_notify"]=True;L.tick(self.ns)
        self.assertEqual(len(self.sent),1)

    def test_failed_notification_is_retried(self):
        self.ns["tg_notify"]=lambda text:False
        L.tick(self.ns)
        self.assertFalse(L.public()["remote"]["notified_blocked"])
        self.ns["tg_notify"]=self.sent.append
        L.tick(self.ns);L.tick(self.ns)
        self.assertTrue(L.public()["remote"]["notified_blocked"])
        self.assertEqual(len(self.sent),1)

    def test_does_not_claim_pause_before_hooks_loaded(self):
        self.info["applied"]=False;L.tick(self.ns)
        self.assertFalse(L.public()["remote"]["blocked"])
        self.assertFalse(self.sent)

    def test_busy_transfer_not_touched(self):
        with patch.object(M,"busy",return_value=True):L.tick(self.ns)
        self.assertFalse(self.calls)


class Alerts(unittest.TestCase):
    def setUp(self):
        source = (Path(__file__).parent / "cc_limits.py").read_text()
        tree = ast.parse(source)
        names = {"_lim_at", "claude_limit_alerts", "_claude_limit_tick"}
        code = "\n".join(ast.get_source_segment(source, n) for n in tree.body
                         if isinstance(n, ast.FunctionDef) and n.name in names)
        self.memory = {"limit_alerts": {}}
        self.sent = []
        self.remote = {"remote": dict(row(90), ts=time.time())}
        from types import SimpleNamespace
        self.ns = dict(cfg=lambda: {}, STATE="unused", LIM_WARN=90, LIM_CLEAR=80,
                       jload=lambda *a: dict(self.memory), jsave=lambda p,v:self.memory.update(v),
                       tg_notify=self.sent.append, time=time,
                       cc_remote=SimpleNamespace(cached=lambda:self.remote))
        exec(code, self.ns)

    def tick(self):
        self.ns["_claude_limit_tick"]({"accounts":{}})

    def test_remote_only_warning_without_handoff(self):
        self.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("90%", self.sent[0])

    def test_full_and_recovery(self):
        self.tick();self.remote["remote"]["five_hour"]["pct"]=100;self.tick()
        self.assertIn("исчерпан", self.sent[-1])
        self.remote["remote"]["five_hour"]["pct"]=0;self.tick()
        self.assertIn("снова доступен", self.sent[-1])

    def test_temporary_offline_does_not_rearm_warning(self):
        self.tick();self.remote["remote"]["online"]=False;self.tick()
        self.remote["remote"]["online"]=True;self.tick()
        self.assertEqual(len(self.sent),1)

    def test_stale_or_failed_usage_does_not_warn(self):
        self.remote["remote"]["ts"]=time.time()-1000;self.tick()
        self.assertFalse(self.sent)
        self.remote["remote"].update(ts=time.time(),error="ssh");self.tick()
        self.assertFalse(self.sent)


class ProcessGate(unittest.TestCase):
    def test_real_hook_process_holds_action_then_releases_on_reset(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            shutil.copy(Path(G.__file__), base / "remote_guard.py")
            policy = base / "limits-ccfleet.json"
            cache = base / "limits-ccfleet-usage.json"
            policy.write_text(json.dumps(dict(enabled=True, threshold=90)))
            cache.write_text(json.dumps(dict(row(90), ts=time.time())))
            script = ("import remote_guard as g; from pathlib import Path; "
                      "g.hook({'hook_event_name':'PreToolUse'}); Path('executed').write_text('yes')")
            child = subprocess.Popen([os.sys.executable, "-c", script], cwd=directory,
                                     env=dict(os.environ, CC_REMOTE_TMUX="ccfleet"),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic()+5
                while not list(base.glob("limits-ccfleet-wait-*.json")) and time.monotonic()<deadline:
                    time.sleep(0.02)
                self.assertIsNone(child.poll())
                self.assertFalse((base/"executed").exists())
                # A past reset releases the same waiting process without a new prompt.
                data = dict(row(100), ts=time.time())
                data["five_hour"]["resets_at"]="2026-01-01T00:00:00Z"
                tmp = base/"new.json";tmp.write_text(json.dumps(data));os.replace(tmp,cache)
                child.wait(timeout=5)
                self.assertEqual(child.returncode,0)
                self.assertTrue((base/"executed").exists())
            finally:
                if child.poll() is None:child.kill();child.wait()


class Composer(unittest.TestCase):
    def setUp(self):
        source=(Path(__file__).parent/'remote_ctl.py').read_text()
        import re
        ns=dict(re=re,ANSI=re.compile(r"\x1b\[[0-9;?]*[A-Za-z]"))
        tree=ast.parse(source)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='composer_has_draft')
        exec(ast.get_source_segment(source,node),ns)
        self.draft=ns['composer_has_draft']
        self.rule='─'*30

    def box(self,text):return '❯ old submitted message\n'+self.rule+'\n'+text+'\n'+self.rule+'\nstatus'

    def test_dim_suggestion_is_empty_input(self):
        self.assertFalse(self.draft(self.box('❯ \x1b[2msuggestion')))

    def test_normal_text_is_a_draft(self):
        self.assertTrue(self.draft(self.box('❯ unsent draft')))

    def test_reset_dim_text_is_a_draft(self):
        self.assertTrue(self.draft(self.box('❯ \x1b[2m\x1b[22munsent draft')))

    def test_empty_composer_ignores_echo(self):
        self.assertFalse(self.draft(self.box('❯ ')))

    def test_multiline_draft_is_preserved(self):
        self.assertTrue(self.draft(self.box('❯ \n  second line')))

    def test_draft_followed_by_dim_completion_is_preserved(self):
        self.assertTrue(self.draft(self.box('❯ draft\x1b[2m suggestion')))

    def test_truecolor_parameter_is_not_dim(self):
        self.assertTrue(self.draft(self.box('❯ \x1b[38;2;200;210;220mtyped text')))


class LaunchRecovery(unittest.TestCase):
    def setUp(self):
        import re
        from types import SimpleNamespace
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for key,value in [('BASE',Path(self.tmp.name)),('NAME','fixture')]:
            p=patch.object(G,key,value);p.start();self.addCleanup(p.stop)
        source=(Path(__file__).parent/'remote_ctl.py').read_text();tree=ast.parse(source)
        names={'accept_startup_menu','guard_reload'}
        self.keys=[];self.starts=[];self.results=[{'ok':True}]
        class Done(Exception):pass
        self.Done=Done
        def out(data):raise Done(data)
        def start(*a,**kw):
            self.starts.append((a,kw));return self.results.pop(0)
        self.ns=dict(MENU_YES=re.compile('yes, (?:i accept|continue)'),MENU_TRUST=re.compile('yes, i trust'),
                     key=self.keys.append,time=SimpleNamespace(sleep=lambda _:None,time=time.time),
                     alive=lambda:True,guard_status=lambda:{'applied':False},out=out,
                     sh=lambda *a:(0,''),TMUX='fixture',ANSI=re.compile('x'),busy=lambda _:False,
                     composer_has_draft=lambda _:False,current_sid=lambda:'12345678-1234-1234-1234-123456789abc',
                     tg_state=lambda:True,start=start)
        exec('\n'.join(ast.get_source_segment(source,n) for n in tree.body
                       if isinstance(n,ast.FunctionDef) and n.name in names),self.ns)

    def test_selected_accept_is_not_moved_to_exit(self):
        self.assertTrue(self.ns['accept_startup_menu']('❯ 1. yes, i accept\n  2. no, exit'))
        self.assertEqual(self.keys,['Enter'])

    def test_selected_exit_moves_to_accept(self):
        self.assertTrue(self.ns['accept_startup_menu']('❯ 1. no, exit\n  2. yes, i trust'))
        self.assertEqual(self.keys,['Down','Enter'])

    def test_unknown_selection_is_not_confirmed(self):
        self.assertFalse(self.ns['accept_startup_menu']('  1. yes, i trust\n  2. no, exit'))
        self.assertEqual(self.keys,[])

    def test_failed_launch_restores_same_session_and_telegram(self):
        self.results=[{'ok':False},{'ok':True}]
        with self.assertRaises(self.Done) as result:self.ns['guard_reload']()
        self.assertTrue(result.exception.args[0]['restored'])
        self.assertEqual(self.starts[0][0],self.starts[1][0])
        self.assertEqual(self.starts[1][1],{'use_guard':False})

    def test_failure_cooldown_prevents_restart_loop(self):
        G.save(G.BASE/'limits-fixture-reload.json',dict(failed=True,ts=time.time()))
        with self.assertRaises(self.Done) as result:self.ns['guard_reload']()
        self.assertEqual(result.exception.args[0]['error'],'guard_reload_cooldown')
        self.assertEqual(self.starts,[])

    def test_successful_launch_uses_same_session_once(self):
        with self.assertRaises(self.Done) as result:self.ns['guard_reload']()
        self.assertTrue(result.exception.args[0]['reloaded'])
        self.assertEqual(len(self.starts),1)


if __name__ == "__main__":
    unittest.main()
