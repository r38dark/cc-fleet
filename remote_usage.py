#!/usr/bin/env python3
"""Лимиты Claude-аккаунта этого сервера: одна строка JSON для панели cc-fleet. Токен никуда не печатается."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOME = os.environ.get("HOME") or "/root"
HDR = {"anthropic-beta": "oauth-2025-04-20"}


def out(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def get(url, token):
    req = urllib.request.Request(url, headers=dict(HDR, Authorization="Bearer " + token))
    return json.load(urllib.request.urlopen(req, timeout=15))


def main():
    try:
        oa = json.load(open(HOME + "/.claude/.credentials.json")).get("claudeAiOauth") or {}
    except Exception:
        oa = {}
    token = oa.get("accessToken")
    if not token:
        out({"ok": False, "error": "no_login"})
    if int(oa.get("expiresAt") or 0) / 1000.0 < time.time():
        out({"ok": False, "error": "token_expired"})
    try:
        u = get("https://api.anthropic.com/api/oauth/usage", token)
    except urllib.error.HTTPError as e:
        out({"ok": False, "error": "http_%d" % e.code})
    except Exception:
        out({"ok": False, "error": "net"})
    plan = ""
    try:
        a = get("https://api.anthropic.com/api/oauth/profile", token).get("account") or {}
        plan = "max" if a.get("has_claude_max") else ("pro" if a.get("has_claude_pro") else "free")
    except Exception:
        pass
    try:
        email = (json.load(open(HOME + "/.claude.json")).get("oauthAccount") or {}).get("emailAddress", "")
    except Exception:
        email = ""
    res = {"ok": True, "email": email, "plan": plan}
    try:  # модель и effort по умолчанию на этом сервере (как «Модель/Effort» у Claude DEV)
        st = json.load(open(HOME + "/.claude/settings.json"))
        mid = st.get("model") or ""
        res["model"] = mid
        res["effort"] = (((st.get("modelSettings") or {}).get(mid) or {}).get("effortLevel")) or st.get("effortLevel") or ""
    except Exception:
        pass
    for k in ("five_hour", "seven_day"):
        v = u.get(k) or {}
        res[k] = {"pct": v.get("utilization"), "resets_at": v.get("resets_at")}
    out(res)


main()
