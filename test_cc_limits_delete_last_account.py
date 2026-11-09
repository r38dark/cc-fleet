# Удаление последнего Claude-аккаунта: раньше delete_account() отказывала навсегда
# ("это последний аккаунт в ротации"), даже если человек больше не пользуется Claude через
# балансер совсем — некуда было деться. Теперь разрешено: python3 -m unittest test_cc_limits_delete_last_account -v
import json
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="ccdellast_")
os.environ.setdefault("CC_LIMITS_BASE", os.path.join(TMP, "base"))
os.environ.setdefault("CC_LIMITS_PROFILES", os.path.join(TMP, "profiles"))

import cc_limits as L  # noqa: E402


def make_account(uid, email="a@b.c"):
    d = os.path.join(L.PROFILES, uid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "oauth_account.json"), "w") as f:
        json.dump({"accountUuid": "uuid-" + uid, "emailAddress": email}, f)
    with open(os.path.join(d, "credentials.json"), "w") as f:
        json.dump({"claudeAiOauth": {"accessToken": "x"}}, f)
    return d


class DeleteLastAccount(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        live = tempfile.TemporaryDirectory(prefix="cc-disconnect-live-")
        self.addCleanup(live.cleanup)
        for key, fname in (("LIVE_CFG", "config.json"), ("LIVE_CREDS", "credentials.json")):
            field = patch.object(L, key, os.path.join(live.name, fname))
            field.start()
            self.addCleanup(field.stop)
        guard = patch.object(L, "_current_screen_pid", return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        os.makedirs(L.PROFILES, exist_ok=True)
        os.makedirs(L.BASE, exist_ok=True)
        for p in os.listdir(L.PROFILES):
            import shutil
            shutil.rmtree(os.path.join(L.PROFILES, p), ignore_errors=True)
        for f in (L.SNAPSHOT, L.STATE, L.GOOD, L.LIVE_CFG):
            try:
                os.remove(f)
            except OSError:
                pass

    def test_sole_inactive_account_can_be_deleted(self):
        make_account("acc1")
        # LIVE_CFG отсутствует/не совпадает -> active_name() вернёт None, аккаунт не активный
        ok, msg, _ = L.delete_account("acc1", "подтверждаю")
        self.assertTrue(ok, msg)
        self.assertEqual(L.profile_names(), [])

    def test_sole_active_account_can_be_deleted(self):
        make_account("acc1")
        os.makedirs(os.path.dirname(L.LIVE_CFG), exist_ok=True)
        with open(L.LIVE_CFG, "w") as f:
            json.dump({"oauthAccount": {"accountUuid": "uuid-acc1"}}, f)
        self.assertEqual(L.active_name(), "acc1")
        ok, msg, _ = L.delete_account("acc1", "подтверждаю")
        self.assertTrue(ok, msg)
        self.assertEqual(L.profile_names(), [])

    def test_backend_functions_survive_zero_accounts_after_deletion(self):
        make_account("acc1")
        L.delete_account("acc1", "подтверждаю")
        snap = L.collect(force=True)  # не должно падать
        self.assertEqual(snap.get("accounts"), {})
        self.assertIsNone(snap.get("active"))
        L.switch_policy_check(snap)  # autoswitch-ветка, не должно падать
        c = L.cfg()
        c["optimize"] = True
        L.jsave(L.CONFIG, c)
        L.switch_policy_check(snap)  # optimize-ветка, тоже не должно падать
        L.model_info()  # сводка моделей не должна зависеть от наличия аккаунтов

    def test_second_real_account_still_requires_a_move_when_active(self):
        # контроль: если альтернатива ЕСТЬ, но переключиться на неё не вышло (тут её просто
        # нет в снимке лимитов) — старое поведение "нельзя удалить активный без переноса" цело
        make_account("acc1")
        make_account("acc2")
        os.makedirs(os.path.dirname(L.LIVE_CFG), exist_ok=True)
        with open(L.LIVE_CFG, "w") as f:
            json.dump({"oauthAccount": {"accountUuid": "uuid-acc1"}}, f)
        ok, msg, _ = L.delete_account("acc1", "подтверждаю")
        self.assertFalse(ok)
        self.assertIn("переключить", msg)
        self.assertEqual(sorted(L.profile_names()), ["acc1", "acc2"])  # ничего не удалено

    def test_wrong_confirm_word_still_blocks(self):
        make_account("acc1")
        ok, msg, _ = L.delete_account("acc1", "нет")
        self.assertFalse(ok)
        self.assertEqual(L.profile_names(), ["acc1"])

    def test_unknown_account_still_blocks(self):
        ok, msg, _ = L.delete_account("acc99", "подтверждаю")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
