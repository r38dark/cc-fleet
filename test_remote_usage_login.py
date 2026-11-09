# Скрипт лимитов на втором сервере: «вход до» — срок жизни логина (refreshTokenExpiresAt), а не токена доступа (2.0.13)
# python3 -m unittest test_remote_usage_login -v
import io
import json
import os
import runpy
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def run_usage(oauth):
    """Запускает remote_usage.py с поддельным HOME и сетью; возвращает его JSON."""
    home = tempfile.mkdtemp(prefix="usage_")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", ".credentials.json"), "w") as f:
        json.dump({"claudeAiOauth": oauth}, f)
    with open(os.path.join(home, ".claude.json"), "w") as f:
        json.dump({"oauthAccount": {"emailAddress": "a@example.com"}}, f)

    def fake_urlopen(req, timeout=0):
        url = getattr(req, "full_url", req)
        if "oauth/usage" in url:
            body = {"five_hour": {"utilization": 5, "resets_at": "x"}, "seven_day": {"utilization": 9, "resets_at": "y"}}
        else:
            body = {"account": {"has_claude_pro": True}, "organization": {"subscription_created_at": "2026-11-04T11:46:15Z"}}
        return io.BytesIO(json.dumps(body).encode())

    buf = io.StringIO()
    with mock.patch.dict(os.environ, {"HOME": home}), mock.patch("urllib.request.urlopen", fake_urlopen), redirect_stdout(buf):
        try:
            runpy.run_path(os.path.join(HERE, "remote_usage.py"), run_name="__main__")
        except SystemExit:
            pass
    return json.loads(buf.getvalue().strip().splitlines()[-1])


class LoginExpires(unittest.TestCase):
    def test_login_expires_is_the_refresh_token_date_not_the_access_token(self):
        access = int((time.time() + 5 * 3600) * 1000)          # токен доступа живёт часы и обновляется сам
        refresh = int((time.time() + 27 * 86400) * 1000)       # настоящий логин — недели
        res = run_usage({"accessToken": "t", "expiresAt": access, "refreshTokenExpiresAt": refresh})
        self.assertTrue(res["ok"])
        self.assertEqual(res["login_expires"], datetime.fromtimestamp(refresh / 1000.0, tz=timezone.utc).isoformat())

    def test_without_refresh_date_it_is_unknown_not_the_access_token(self):
        access = int((time.time() + 5 * 3600) * 1000)
        res = run_usage({"accessToken": "t", "expiresAt": access})
        self.assertTrue(res["ok"])
        self.assertEqual(res["login_expires"], "")  # часы токена доступа сроком входа не показываем


if __name__ == "__main__":
    unittest.main()
