#!/usr/bin/env python3
# Тесты cc_codex на поддельном codex: вход по коду устройства, чтение карточки через
# app-server, запись модели/Fast, удаление. Запуск: python3 -m unittest test_cc_codex
import json, os, shutil, stat, tempfile, textwrap, time, unittest

os.environ["CC_CODEX_PROFILES"] = tempfile.mkdtemp(prefix="cc-codex-test-")
import cc_codex  # noqa: E402

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    # поддельный codex: login --device-auth / app-server / logout
    import base64, json, os, sys, time
    home = os.environ["CODEX_HOME"]
    gate = os.environ.get("FAKE_CODEX_GATE", "")
    def jwt(c):
        enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
        return enc({"alg": "none"}) + "." + enc(c) + ".sig"
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        if os.environ.get("FAKE_CODEX_CHILD"):
            import subprocess
            open(os.environ["FAKE_CODEX_CHILD"], "w").write(str(subprocess.Popen(["sleep", "300"]).pid))
        print("Welcome to Codex [v\\x1b[90m0.166.0\\x1b[0m]")
        print("1. Open this link in your browser and sign in to your account")
        print("   \\x1b[94mhttps://auth.openai.com/codex/device\\x1b[0m")
        print("2. Enter this one-time code \\x1b[90m(expires in 15 minutes)\\x1b[0m")
        print("   \\x1b[94mABCD-12XYZ\\x1b[0m", flush=True)
        for _ in range(600):
            if os.path.exists(gate):
                break
            time.sleep(0.1)
        else:
            sys.exit(1)
        verdict = open(gate).read().strip()
        if verdict == "deny":
            sys.exit(1)
        email = verdict or "user@example.com"
        c = {"email": email, "https://api.openai.com/auth": {
            "chatgpt_plan_type": "plus", "chatgpt_subscription_active_until": "2026-11-30T17:40:05+00:00"}}
        json.dump({"auth_mode": "chatgpt", "tokens": {"id_token": jwt(c), "access_token": "a", "refresh_token": "r"},
                   "last_refresh": "2026-10-31T06:45:52Z"}, open(os.path.join(home, "auth.json"), "w"))
        print("Successfully logged in")
        sys.exit(0)
    if cmd == "logout":
        open(os.path.join(home, "LOGGED_OUT"), "w").write("1")
        sys.exit(0)
    if cmd == "app-server":
        cfgp = os.path.join(home, "config.toml")
        def conf():
            d = {}
            if os.path.exists(cfgp):
                for l in open(cfgp):
                    if "=" in l:
                        k, v = l.split("=", 1); d[k.strip()] = v.strip().strip('"')
            return d
        def save(d):
            open(cfgp, "w").write("".join(f'{k} = "{v}"\\n' for k, v in d.items()))
        for line in sys.stdin:
            m = json.loads(line)
            if "id" not in m:
                continue
            meth, p, res = m["method"], m.get("params") or {}, {}
            if meth == "account/read":
                pf, af = os.path.join(home, "PLAN"), os.path.join(home, "AFTER_REFRESH")
                if p.get("refreshToken"):
                    open(os.path.join(home, "REFRESHED"), "w").write("1")
                    if os.path.exists(os.path.join(home, "REFRESH_FAIL")):
                        print(json.dumps({"id": m["id"], "error": {"code": -1, "message": "401 Unauthorized"}}), flush=True)
                        continue
                    if os.path.exists(af):  # после обновления токена OpenAI показывает новый план
                        os.replace(af, pf)
                if os.path.exists(os.path.join(home, "ACCOUNT_FAIL")):
                    print(json.dumps({"id": m["id"], "error": {"code": -1, "message": "boom"}}), flush=True)
                    continue
                plan = open(pf).read().strip() if os.path.exists(pf) else "plus"
                if os.path.exists(os.path.join(home, "NOACCOUNT")):
                    res = {"account": None, "requiresOpenaiAuth": True}
                else:
                    res = {"account": {"type": "chatgpt", "email": "user@example.com", "planType": plan}, "requiresOpenaiAuth": True}
            elif meth == "account/rateLimits/read":
                if os.path.exists(os.path.join(home, "AUTHFAIL")):
                    print(json.dumps({"id": m["id"], "error": {"code": -1, "message": "401 Unauthorized"}}), flush=True)
                    continue
                res = {"ordinaryUsageAllowed": True, "rateLimits": {
                    "primary": {"usedPercent": 7, "windowDurationMins": 300, "resetsAt": 1793447278},
                    "secondary": {"usedPercent": 3, "windowDurationMins": 10080, "resetsAt": 1794034078},
                    "credits": {"hasCredits": False, "unlimited": False, "balance": "0"}, "planType": "plus",
                    "rateLimitReachedType": None}}
            elif meth == "model/list":
                eff = [{"reasoningEffort": e} for e in ("low", "medium", "high")]
                res = {"data": [
                    {"id": "gpt-x", "displayName": "GPT-X", "isDefault": True, "supportedReasoningEfforts": eff,
                     "defaultReasoningEffort": "low", "serviceTiers": [{"id": "priority", "name": "Fast"}]},
                    {"id": "gpt-y", "displayName": "GPT-Y", "isDefault": False, "supportedReasoningEfforts": eff[:1],
                     "defaultReasoningEffort": "low", "serviceTiers": []}]}
            elif meth == "config/read":
                c = conf()
                res = {"config": {"model": c.get("model"), "model_reasoning_effort": c.get("model_reasoning_effort"),
                                  "service_tier": c.get("service_tier")}}
            elif meth == "config/value/write":
                c = conf()
                if p["value"] is None:
                    c.pop(p["keyPath"], None)
                else:
                    c[p["keyPath"]] = p["value"]
                save(c)
                res = {"status": "ok"}
            print(json.dumps({"id": m["id"], "result": res}), flush=True)
        sys.exit(0)
''')


def _r(path):
    with open(path) as f:
        return f.read()


def _w(path, text=""):
    with open(path, "w") as f:
        f.write(text)


class CodexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cc-codex-fake-")
        cls.bin = os.path.join(cls.tmp, "codex")
        with open(cls.bin, "w") as f:
            f.write(FAKE)
        os.chmod(cls.bin, 0o755)

    def setUp(self):
        cc_codex._logins.clear()
        cc_codex._cache.clear()
        cc_codex._models_cache.clear()
        self.gate = os.path.join(self.tmp, f"gate{time.time_ns()}")
        os.environ["FAKE_CODEX_GATE"] = self.gate
        for d in os.listdir(cc_codex.PROFILES) if os.path.isdir(cc_codex.PROFILES) else []:
            shutil.rmtree(os.path.join(cc_codex.PROFILES, d), ignore_errors=True)

    def _wait(self, slot, want, t=8):
        end = time.time() + t
        while time.time() < end:
            st = cc_codex.login_status(slot)
            if st["state"] == want:
                return st
            time.sleep(0.1)
        self.fail(f"состояние {want} не наступило: {cc_codex.login_status(slot)}")

    def _add(self, email="user@example.com", label="Тест"):
        ok, d = cc_codex.login_start(self.bin, label=label)
        self.assertTrue(ok, d)
        _w(self.gate, email)
        self._wait(d["slot"], "done")
        return d["slot"]

    def test_login_shows_url_and_code_without_ansi(self):
        ok, d = cc_codex.login_start(self.bin, label="x")
        self.assertTrue(ok, d)
        self.assertEqual(d["url"], "https://auth.openai.com/codex/device")
        self.assertEqual(d["code"], "ABCD-12XYZ")
        self.assertEqual(d["slot"], "gpt1")
        self.assertEqual(cc_codex.login_status("gpt1")["state"], "waiting")
        cc_codex.login_cancel("gpt1")
        self.assertEqual(cc_codex.login_status("gpt1")["state"], "none")
        # отменённая попытка не оставляет временных папок
        self.assertEqual([d for d in os.listdir(cc_codex.PROFILES) if d.startswith(".login-")], [])

    def test_cancel_kills_child_process_too(self):
        # настоящий codex — обёртка node: без убийства группы бинарник-потомок оставался бы висеть сиротой
        pidf = os.path.join(self.tmp, f"child{time.time_ns()}")
        os.environ["FAKE_CODEX_CHILD"] = pidf
        try:
            ok, d = cc_codex.login_start(self.bin)
            self.assertTrue(ok, d)
            with open(pidf) as f:
                pid = int(f.read())
            self.assertTrue(self._alive(pid))
            cc_codex.login_cancel(d["slot"])
            for _ in range(30):
                if not self._alive(pid):
                    break
                time.sleep(0.1)
            self.assertFalse(self._alive(pid), "потомок процесса входа пережил отмену")
        finally:
            os.environ.pop("FAKE_CODEX_CHILD", None)

    @staticmethod
    def _alive(pid):
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False

    def test_failed_message_has_no_url_or_code_noise(self):
        ok, d = cc_codex.login_start(self.bin)
        _w(self.gate, "deny")
        st = self._wait(d["slot"], "failed")
        self.assertNotIn("ABCD-12XYZ", st["message"])
        self.assertNotIn("auth.openai.com", st["message"])

    def test_notify_called_after_success_only(self):
        got = []
        cc_codex.NOTIFY = got.append
        try:
            ok, d = cc_codex.login_start(self.bin)
            _w(self.gate, "deny")
            self._wait(d["slot"], "failed")
            self.assertEqual(got, [])
            os.remove(self.gate)
            self._add("n@example.com")
            for _ in range(20):
                if got:
                    break
                time.sleep(0.1)
            self.assertEqual(len(got), 1)
            self.assertIn("n@example.com", got[0])
            self.assertIn("PLUS", got[0])
        finally:
            cc_codex.NOTIFY = None

    def test_sweep_removes_abandoned_login_dirs(self):
        os.makedirs(cc_codex.PROFILES, exist_ok=True)
        old = os.path.join(cc_codex.PROFILES, ".login-abandoned")
        fresh = os.path.join(cc_codex.PROFILES, ".login-fresh")
        for d in (old, fresh):
            os.makedirs(d)
        t = time.time() - cc_codex.LOGIN_TTL - 700
        os.utime(old, (t, t))
        cc_codex._login_sweep()
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_login_done_creates_profile(self):
        slot = self._add()
        self.assertEqual(slot, "gpt1")
        self.assertEqual(cc_codex.profile_slots(), ["gpt1"])
        p = cc_codex.profile_dir("gpt1")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(p, "auth.json")).st_mode) & 0o077, 0)
        m = cc_codex.meta("gpt1")
        self.assertEqual((m["label"], m["email"]), ("Тест", "user@example.com"))
        self.assertIn("cli_auth_credentials_store", _r(os.path.join(p, "config.toml")))

    def test_login_denied_leaves_nothing(self):
        ok, d = cc_codex.login_start(self.bin)
        _w(self.gate, "deny")
        st = self._wait(d["slot"], "failed")
        self.assertIn("Код не подтверждён", st["message"])
        self.assertEqual(cc_codex.profile_slots(), [])
        self.assertEqual(os.listdir(cc_codex.PROFILES), [])

    def test_duplicate_account_rejected(self):
        self._add("same@example.com")
        ok, d = cc_codex.login_start(self.bin)
        _w(self.gate, "same@example.com")
        st = self._wait(d["slot"], "failed")
        self.assertIn("уже подключён как gpt1", st["message"])
        self.assertEqual(cc_codex.profile_slots(), ["gpt1"])

    def test_relogin_same_account_replaces_auth_keeps_config(self):
        slot = self._add()
        cfg = os.path.join(cc_codex.profile_dir(slot), "config.toml")
        with open(cfg, "a") as f:
            f.write('model = "gpt-x"\n')
        os.remove(self.gate)
        ok, d = cc_codex.login_start(self.bin, slot=slot)
        self.assertTrue(ok, d)
        _w(self.gate, "user@example.com")
        self._wait(slot, "done")
        self.assertIn('model = "gpt-x"', _r(cfg))
        self.assertEqual(sorted(os.listdir(cc_codex.PROFILES)), ["gpt1"])

    def test_relogin_other_email_refused(self):
        slot = self._add("a@example.com")
        os.remove(self.gate)
        ok, d = cc_codex.login_start(self.bin, slot=slot)
        _w(self.gate, "b@example.com")
        st = self._wait(slot, "failed")
        self.assertIn("другой аккаунт", st["message"])
        self.assertEqual(cc_codex.meta(slot)["email"], "a@example.com")

    def test_relogin_unknown_slot(self):
        ok, msg = cc_codex.login_start(self.bin, slot="gpt9")
        self.assertFalse(ok)

    def test_fetch_account_limits_models_settings(self):
        slot = self._add()
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertNotIn("error", d)
        self.assertEqual((d["email"], d["plan"]), ("user@example.com", "plus"))
        self.assertEqual([(w["mins"], w["pct"]) for w in d["windows"]], [(300, 7), (10080, 3)])
        self.assertTrue(d["windows"][0]["resets_at"].endswith("Z"))
        self.assertEqual([m["id"] for m in d["models"]], ["gpt-x", "gpt-y"])
        self.assertEqual(d["models"][0]["fast"], "priority")
        self.assertIsNone(d["models"][1]["fast"])
        self.assertEqual(d["sub_until"], "2026-11-30T17:40:05+00:00")
        self.assertIsNone(d["model"])
        self.assertIn("CODEX_HOME=", d["launch"])

    def test_lapsed_to_free_is_remembered(self):
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertFalse(d["lapsed"])
        self.assertEqual(cc_codex.meta(slot)["paid"], "plus")
        self.assertEqual(cc_codex.meta(slot)["email"], "user@example.com")  # прежние поля meta на месте
        _w(os.path.join(p, "PLAN"), "free")
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertEqual(d["plan"], "free")
        self.assertTrue(d["lapsed"])
        self.assertEqual(d["paid_plan"], "plus")
        self.assertEqual(cc_codex.meta(slot)["paid"], "plus")  # «был платным» не стирается Free-чтением
        _w(os.path.join(p, "PLAN"), "pro")
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertFalse(d["lapsed"])
        self.assertEqual(cc_codex.meta(slot)["paid"], "pro")

    def test_always_free_account_is_not_lapsed(self):
        slot = self._add()
        _w(os.path.join(cc_codex.profile_dir(slot), "PLAN"), "free")
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertEqual(d["plan"], "free")
        self.assertFalse(d["lapsed"])
        self.assertNotIn("paid", cc_codex.meta(slot))

    def test_lapsed_survives_failed_read(self):
        # план берётся из id_token даже если app-server молчит: метка не пропадает вместе с сетью
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        cc_codex.fetch_account(self.bin, slot)
        auth = json.loads(_r(os.path.join(p, "auth.json")))
        import base64
        enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
        auth["tokens"]["id_token"] = enc({"alg": "none"}) + "." + enc(
            {"email": "user@example.com", "https://api.openai.com/auth": {"chatgpt_plan_type": "free"}}) + ".sig"
        _w(os.path.join(p, "auth.json"), json.dumps(auth))
        _w(os.path.join(p, "ACCOUNT_FAIL"))
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertEqual(d["error"], "boom")
        self.assertEqual(d["plan"], "free")
        self.assertTrue(d["lapsed"])

    def test_renew_picks_up_new_plan(self):
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        cc_codex.get_accounts(self.bin, force=True)
        _w(os.path.join(p, "PLAN"), "free")
        d = cc_codex.get_accounts(self.bin, force=True)[0]
        self.assertTrue(d["lapsed"])
        _w(os.path.join(p, "AFTER_REFRESH"), "plus")
        ok, msg = cc_codex.renew(self.bin, slot)
        self.assertTrue(ok, msg)
        self.assertIn("Plus", msg)
        self.assertIn("30.11.2026", msg)
        self.assertTrue(os.path.exists(os.path.join(p, "REFRESHED")))
        d = cc_codex.get_accounts(self.bin)[0]  # карточка в кэше уже свежая
        self.assertEqual(d["plan"], "plus")
        self.assertFalse(d["lapsed"])

    def test_renew_still_free_says_wait(self):
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        cc_codex.fetch_account(self.bin, slot)
        _w(os.path.join(p, "PLAN"), "free")
        ok, msg = cc_codex.renew(self.bin, slot)
        self.assertFalse(ok)
        self.assertIn("Пока Free", msg)
        ok, msg = cc_codex.renew(self.bin, slot, lang="en")
        self.assertIn("Still Free", msg)
        self.assertTrue(cc_codex.get_accounts(self.bin)[0]["lapsed"])

    def test_renew_expired_session_and_bad_slot(self):
        slot = self._add()
        _w(os.path.join(cc_codex.profile_dir(slot), "REFRESH_FAIL"))
        ok, msg = cc_codex.renew(self.bin, slot)
        self.assertFalse(ok)
        self.assertIn("Войти заново", msg)
        self.assertFalse(cc_codex.renew(self.bin, "gpt9")[0])
        self.assertFalse(cc_codex.renew(self.bin, "../x")[0])

    def test_login_required_when_account_missing_or_401(self):
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        _w(os.path.join(p, "NOACCOUNT"))
        self.assertTrue(cc_codex.fetch_account(self.bin, slot)["login_required"])
        os.remove(os.path.join(p, "NOACCOUNT"))
        _w(os.path.join(p, "AUTHFAIL"))
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertTrue(d["login_required"])
        self.assertIn("401", d["error"])

    def test_stale_keeps_last_good_numbers(self):
        slot = self._add()
        good = cc_codex.get_accounts(self.bin, force=True)[0]
        self.assertEqual(good["windows"][0]["pct"], 7)
        _w(os.path.join(cc_codex.profile_dir(slot), "AUTHFAIL"))
        d = cc_codex.get_accounts(self.bin, force=True)[0]
        self.assertTrue(d["stale"])
        self.assertEqual(d["windows"][0]["pct"], 7)
        self.assertTrue(d["login_required"])

    def test_cache_not_refetched_within_ttl(self):
        slot = self._add()
        cc_codex.get_accounts(self.bin, force=True)
        _w(os.path.join(cc_codex.profile_dir(slot), "AUTHFAIL"))
        d = cc_codex.get_accounts(self.bin)[0]  # из кэша: сбой ещё не виден
        self.assertNotIn("error", d)

    def test_set_prefs_writes_and_clears(self):
        slot = self._add()
        ok, msg = cc_codex.set_prefs(self.bin, slot, "gpt-x", "high", True)
        self.assertTrue(ok, msg)
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertEqual((d["model"], d["effort"], d["fast"]), ("gpt-x", "high", True))
        ok, msg = cc_codex.set_prefs(self.bin, slot, "", "", False)
        self.assertTrue(ok, msg)
        d = cc_codex.fetch_account(self.bin, slot)
        self.assertEqual((d["model"], d["effort"], d["fast"]), (None, None, False))

    def test_set_prefs_validation(self):
        slot = self._add()
        self.assertFalse(cc_codex.set_prefs(self.bin, slot, "nope", "", False)[0])
        self.assertFalse(cc_codex.set_prefs(self.bin, slot, "gpt-y", "high", False)[0])  # у gpt-y только low
        self.assertFalse(cc_codex.set_prefs(self.bin, slot, "gpt-y", "", True)[0])  # Fast у gpt-y нет
        self.assertFalse(cc_codex.set_prefs(self.bin, "gpt9", "gpt-x", "", False)[0])
        self.assertFalse(cc_codex.set_prefs(self.bin, "../x", "gpt-x", "", False)[0])

    def test_delete_needs_word_and_logs_out(self):
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        ok, msg = cc_codex.delete_account(self.bin, slot, "нет")
        self.assertFalse(ok)
        self.assertTrue(os.path.isdir(p))
        ok, msg = cc_codex.delete_account(self.bin, slot, " Подтверждаю ")
        self.assertTrue(ok, msg)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(cc_codex.profile_slots(), [])

    def test_delete_rejects_bad_slot_and_symlink(self):
        self.assertFalse(cc_codex.delete_account(self.bin, "../etc", "confirm")[0])
        slot = self._add()
        p = cc_codex.profile_dir(slot)
        real = p + "_real"
        os.rename(p, real)
        os.symlink(real, p)
        ok, msg = cc_codex.delete_account(self.bin, slot, "confirm")
        self.assertFalse(ok)
        self.assertTrue(os.path.isdir(real))
        os.remove(p)

    def test_free_slot_reuses_gap(self):
        self._add("a@example.com")
        os.remove(self.gate)
        s2 = self._add("b@example.com")
        self.assertEqual(s2, "gpt2")
        cc_codex.delete_account(self.bin, "gpt1", "confirm")
        os.remove(self.gate)
        self.assertEqual(self._add("c@example.com"), "gpt1")

    def test_find_bin(self):
        self.assertEqual(cc_codex.find_bin(self.bin), self.bin)


if __name__ == "__main__":
    unittest.main()
