#!/usr/bin/env python3
"""Лимиты Claude-аккаунта этого сервера: одна строка JSON для панели cc-fleet. Токен никуда не печатается.

Опрашивающих много (панель cc-fleet, защита лимитов, обновление при подходе к порогу), а лимит запросов у Anthropic жёсткий:
при частых опросах он отвечает 429. Поэтому ответ делят все — свежий (до TTL) берётся из кэша, а после 429 запросы на время
останавливаются (Retry-After), и отдаются последние удачные цифры: ok=true, stale=true, без ошибки на панели."""
import fcntl
import hashlib
import json
import os
import pwd
import stat
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
# Общий кэш нескольких входов ОДНОГО аккаунта на этом сервере (например, root и обычный пользователь): каждый вход пишет свой файл
# <логин>.json (только проценты, время сброса, тариф, хэш почты — без токенов и самой почты), читают все. Свежие цифры одного входа
# берёт другой — один запрос к Anthropic на аккаунт вместо двух; у кого токен устарел, тот видит цифры живого входа.
# Каталог создаёт администратор (режим 1777, файлы предсозданы каждым владельцем); нет каталога — всё работает как раньше.
SHARED_DIR = os.environ.get("CC_FLEET_USAGE_SHARED") or "/var/lib/cc-fleet-shared"
SHARED_MAX_AGE = 600          # токен устарел: цифры общего кэша не старше 10 минут считаем живыми


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


def acct_hash():
    """Хэш почты аккаунта этого входа: чтобы не смешать цифры разных аккаунтов (сама почта в общий файл не попадает)."""
    try:
        mail = (json.load(open(HOME + "/.claude.json")).get("oauthAccount") or {}).get("emailAddress") or ""
    except Exception:
        mail = ""
    return hashlib.sha256(mail.strip().lower().encode()).hexdigest()[:12] if mail else ""


def shared_read(acct):
    """(лучший общий кэш или None, самая поздняя пауза после 429). Читаются только файлы <логин>.json, чей владелец — этот самый
    логин (чужой пользователь файл подменить не может), и только того же аккаунта (хэш почты)."""
    best, until = None, 0.0
    try:
        names = os.listdir(SHARED_DIR)
    except OSError:
        return None, 0.0
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        try:
            uid = pwd.getpwnam(name[:-5]).pw_uid
            path = os.path.join(SHARED_DIR, name)
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != uid:
                continue
            d = json.load(open(path))
            if not isinstance(d, dict) or not isinstance(d.get("net"), dict):
                continue
            if acct and d.get("acct") and d["acct"] != acct:
                continue
            ts = float(d.get("ts") or 0)
            until = max(until, float(d.get("until") or 0))
            if ts and (best is None or ts > float(best["ts"])):
                best = dict(d, ts=ts)
        except Exception:
            continue
    return best, until


def shared_write(acct, cache):
    """Положить свои свежие цифры в общий кэш (файл <логин>.json). Не получилось — не беда: у входа есть личный кэш."""
    try:
        net = cache.get("net") or {}
        doc = {"ts": cache.get("ts") or 0, "until": cache.get("until") or 0, "code": cache.get("code") or 0, "acct": acct,
               "net": {k: net.get(k) for k in ("five_hour", "seven_day", "plan", "subscription_since") if k in net}}
        path = os.path.join(SHARED_DIR, pwd.getpwuid(os.getuid()).pw_name + ".json")
        if not os.path.isdir(SHARED_DIR):
            return
        tmp = "%s.tmp%d" % (path, os.getpid())
        with open(tmp, "w") as f:
            json.dump(doc, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        pass


def shared_lock():
    """Общий замок на время опроса: два входа не ходят в сеть одновременно. Открываем БЕЗ создания (в каталоге с липким битом
    ядро не даёт открыть чужой файл с O_CREAT), файл замка предсоздан администратором."""
    try:
        f = open(os.path.join(SHARED_DIR, ".lock"), "rb")      # режим чтения: файл не создаётся; замок снимается, когда объект закрыт
        fcntl.flock(f, fcntl.LOCK_EX)
        return f
    except Exception:
        return None


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
    acct = acct_hash()
    sh_lock = shared_lock()                   # общий замок: сначала он, потом личный (порядок один у всех входов)
    sh, sh_until = shared_read(acct)
    if int(oa.get("expiresAt") or 0) / 1000.0 < time.time():
        # токен этого входа устарел (Claude под ним давно не работал), а аккаунт тот же: цифры другого входа, если они свежие
        if sh and time.time() - float(sh["ts"]) < SHARED_MAX_AGE:
            out(result(oa, sh["net"], data_ts=sh["ts"], shared=True))
        out({"ok": False, "error": "token_expired"})
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        lock = open(CACHE + ".lock", "a")
        fcntl.flock(lock, fcntl.LOCK_EX)      # одновременные опросы идут по очереди: первый ходит в сеть, остальные берут его отве
    except Exception:
        lock = None
    cache = load_cache()
    net = cache.get("net") or {}
    now = time.time()
    # свежее из двух: личный кэш или общий (его мог обновить другой вход); общий — только если он новее личного
    own_ts = float(cache.get("ts") or 0)
    if sh and float(sh["ts"]) > own_ts:
        net, own_ts, shared_used = sh["net"], float(sh["ts"]), True
    else:
        shared_used = False
    if net and now - own_ts < TTL:
        if not shared_used and own_ts > float((sh or {}).get("ts") or 0):
            shared_write(acct, cache)             # свои свежие цифры, которых ещё нет в общем кэше (например, с прошлого запуска), — туда
        out(result(oa, net, data_ts=own_ts, **({"shared": True} if shared_used else {})))
    until = max(float(cache.get("until") or 0), sh_until)      # пауза после 429 общая: аккаунт у входов один
    if now < until:                                             # после 429 Anthropic не трогаем до конца паузы
        if net:
            out(result(oa, net, stale=True, stale_code=cache.get("code") or 429, retry_at=until, data_ts=own_ts))
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
            shared_write(acct, dict(cache, net=net or cache.get("net") or {}, ts=own_ts))
            if net:
                out(result(oa, net, stale=True, stale_code=429, retry_at=cache["until"], data_ts=own_ts))
        out({"ok": False, "error": "http_%d" % e.code})
    except Exception:
        out({"ok": False, "error": "net"})
    net = dict(cache.get("net") or {})
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
    shared_write(acct, cache)
    out(result(oa, net, data_ts=now))


if __name__ == "__main__":
    main()
