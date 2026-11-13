#!/usr/bin/env python3
"""Лимиты Claude-аккаунта этого сервера: одна строка JSON для панели cc-fleet. Токен никуда не печатается.

Опрашивающих много (панель cc-fleet, защита лимитов, обновление при подходе к порогу), а лимит запросов у Anthropic жёсткий:
при частых опросах он отвечает 429. Поэтому ответ делят все — свежий (до TTL) берётся из кэша, а после 429 запросы на время
останавливаются (Retry-After), и отдаются последние удачные цифры: ok=true, stale=true, без ошибки на панели."""
import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HOME = os.environ.get("HOME") or "/root"
HDR = {"anthropic-beta": "oauth-2025-04-20"}
CACHE_DIR = os.path.join(HOME, ".cache", "cc-fleet")
CACHE = os.path.join(CACHE_DIR, "usage.json")
TTL = 130                     # свежее этого не перезапрашиваем: панель и защита лимитов делят один ответ;
                              # 130 с ≈ 27 запросов/ч — под бюджет Anthropic (~28/ч на аккаунт); было 60 с → 429 при ≥80 %)
PROFILE_TTL = 6 * 3600        # план и дата подписки меняются редко — второй запрос (profile) не чаще раза в 6 часов
BACKOFF_MIN, BACKOFF_MAX = 120, 900   # пауза опроса после 429, секунд (Retry-After, если он есть)


def out(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def get(url, token):
    req = urllib.request.Request(url, headers=dict(HDR, Authorization="Bearer " + token))
    return json.load(urllib.request.urlopen(req, timeout=15))


def load_cache():
    try:
        d = json.load(open(CACHE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_cache(d):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CACHE + ".tmp%d" % os.getpid()
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, CACHE)
    except Exception:
        pass   # кэш — оптимизация: не получилось записать, работаем по-старому (запрос каждый раз)


def result(oa, net, **extra):
    """Ответ панели: сетевые цифры (кэш или свежие) + локальные поля (почта, модель, effort — читаются с диска каждый раз)."""
    try:
        email = (json.load(open(HOME + "/.claude.json")).get("oauthAccount") or {}).get("emailAddress", "")
    except Exception:
        email = ""
    res = {"ok": True, "email": email, "plan": net.get("plan") or "", "subscription_since": net.get("subscription_since") or ""}
    # срок жизни логина ("вход до"): refreshTokenExpiresAt (~28 дней от настоящего /login), как у локальных аккаунтов;
    # expiresAt — это лишь access-токен на несколько часов, он обновляется сам и сроком входа не является
    try:
        res["login_expires"] = datetime.fromtimestamp(int(oa["refreshTokenExpiresAt"]) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        res["login_expires"] = ""
    try:  # модель и effort по умолчанию на этом сервере (как «Модель/Effort» у Claude DEV)
        st = json.load(open(HOME + "/.claude/settings.json"))
        mid = st.get("model") or ""
        res["model"] = mid
        res["effort"] = (((st.get("modelSettings") or {}).get(mid) or {}).get("effortLevel")) or st.get("effortLevel") or ""
    except Exception:
        pass
    for k in ("five_hour", "seven_day"):
        res[k] = net.get(k) or {"pct": None, "resets_at": None}
    res.update(extra)
    return res


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
        os.makedirs(CACHE_DIR, exist_ok=True)
        lock = open(CACHE + ".lock", "a")
        fcntl.flock(lock, fcntl.LOCK_EX)      # одновременные опросы идут по очереди: первый ходит в сеть, остальные берут его ответ
    except Exception:
        lock = None
    cache = load_cache()
    net = cache.get("net") or {}
    now = time.time()
    if net and now - float(cache.get("ts") or 0) < TTL:
        out(result(oa, net, data_ts=cache.get("ts")))
    if now < float(cache.get("until") or 0):          # после 429 Anthropic не трогаем до конца паузы
        if net:
            out(result(oa, net, stale=True, stale_code=cache.get("code") or 429, retry_at=cache.get("until"), data_ts=cache.get("ts")))
        out({"ok": False, "error": "http_%s" % (cache.get("code") or 429)})
    try:
        u = get("https://api.anthropic.com/api/oauth/usage", token)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try:
                wait = int((e.headers.get("Retry-After") or "").strip())
            except Exception:
                wait = BACKOFF_MIN
            wait = max(BACKOFF_MIN, min(BACKOFF_MAX, wait))
            cache.update(until=now + wait, code=429)
            save_cache(cache)
            if net:
                out(result(oa, net, stale=True, stale_code=429, retry_at=cache["until"], data_ts=cache.get("ts")))
        out({"ok": False, "error": "http_%d" % e.code})
    except Exception:
        out({"ok": False, "error": "net"})
    net = dict(net)
    for k in ("five_hour", "seven_day"):
        v = u.get(k) or {}
        net[k] = {"pct": v.get("utilization"), "resets_at": v.get("resets_at")}
    # все остальные поля ответа — как есть, только в кэш (панели не отдаём): Anthropic кладёт сюда акции и
    # «Limit resets» (Full reset / Reset for free), формат ещё изучаем; result() их не читает, лишних запросов нет
    net["raw_other"] = {k: v for k, v in u.items() if k not in ("five_hour", "seven_day")}
    if now - float(cache.get("profile_ts") or 0) >= PROFILE_TTL:
        try:
            prof = get("https://api.anthropic.com/api/oauth/profile", token)
            a = prof.get("account") or {}
            net["plan"] = "max" if a.get("has_claude_max") else ("pro" if a.get("has_claude_pro") else "free")
            # дата оформления подписки — для панели балансера ("дата подписки")
            net["subscription_since"] = (prof.get("organization") or {}).get("subscription_created_at") or ""
            cache["profile_ts"] = now
        except Exception:
            cache["profile_ts"] = now - PROFILE_TTL + 300   # не вышло — повтор через 5 минут, а не при каждом опросе
    cache.update(net=net, ts=now, until=0, code=0)
    save_cache(cache)
    out(result(oa, net, data_ts=now))


if __name__ == "__main__":
    main()
