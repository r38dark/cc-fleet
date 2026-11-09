"""Удалённые Claude-аккаунты (на чужом сервере): запись, лимиты по ssh, состояние. Токены остаются на их сервере."""
import json
import os
import re
import subprocess
import time

BASE = os.path.dirname(os.path.abspath(__file__))
MEMBERS_FILE = os.environ.get("CC_REMOTE_MEMBERS") or BASE + "/remote_members.json"
STATE_FILE = os.environ.get("CC_REMOTE_STATE") or BASE + "/remote_state.json"
CACHE_SEC = 180
LINK_GRACE = 90.0   # обрыв ssh короче этого (дом/VPN моргнул) не показываем как «нет связи»: держим прежний вид
LINK_RETRY = 20.0   # ...а перепроверяем через столько секунд, не через весь кэш
USAGE_REMOTE = "/root/cc-remote/usage.py"


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, data):
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def members():
    d = jload(MEMBERS_FILE, {})
    return {k: v for k, v in d.items() if isinstance(v, dict) and v.get("host")} if isinstance(d, dict) else {}


def ssh_run(m, remote_cmd, timeout=25, inp=None):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new"]
    if m.get("key"):
        cmd += ["-i", m["key"]]
    if m.get("port"):
        cmd += ["-p", str(m["port"])]
    cmd += [m.get("user", "root") + "@" + m["host"], remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=inp)
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 255, str(e)[:200]


def expired_view(row, now=None):
    """Токен PROD истёк (Claude там давно не работал, обновляется он только при работе): свежих цифр нет, берём последние известные.
    Окно, чей сброс уже прошёл, считаем пустым. Возвращает копию строки; known=False, если цифр не было вовсе."""
    from datetime import datetime
    now = time.time() if now is None else now
    out, known = dict(row or {}), False
    for key in ("five_hour", "seven_day"):
        win = dict(out.get(key) or {})
        if win.get("pct") is None:
            out[key] = win
            continue
        known = True
        try:
            reset = datetime.fromisoformat(str(win.get("resets_at") or "")).timestamp()
        except ValueError:
            reset = None
        if reset is not None and reset <= now:
            win["pct"] = 0.0
        out[key] = win
    out["known"] = known
    return out


def fetch_limits(mid, force=False):
    m = members().get(mid)
    if not m:
        return None
    state = jload(STATE_FILE, {})
    old = state.get(mid) or {}
    if not force and time.time() - float(old.get("ts") or 0) < CACHE_SEC:
        return old
    code, text = ssh_run(m, "python3 " + USAGE_REMOTE)
    data = None
    if code == 0:
        try:
            data = json.loads(text.strip().splitlines()[-1])
        except Exception:
            data = None
    row = dict(old)
    row.update(label=m.get("label") or mid, ts=time.time())
    if data is None:
        now = time.time()
        since = float(old.get("fail_since") or now)
        if old.get("online") and now - since < LINK_GRACE:
            # одиночный обрыв: прежние цифры и скорая перепроверка, а не «нет связи» на все 3 минуты кэша
            row.update(fail_since=since, ts=now - CACHE_SEC + LINK_RETRY)
        else:
            row.update(online=False, error="ssh", fail_since=since)
    elif data.get("ok"):
        row.update(fail_since=0, online=True, error="", email=data.get("email") or old.get("email") or "",
                   plan=data.get("plan") or old.get("plan") or "",
                   five_hour=data.get("five_hour"), seven_day=data.get("seven_day"),
                   model=data.get("model") or old.get("model") or "", effort=data.get("effort") or old.get("effort") or "",
                   subscription_since=data.get("subscription_since") or old.get("subscription_since") or "",
                   login_expires=data.get("login_expires") or old.get("login_expires") or "")
    else:
        row.update(fail_since=0, online=True, error=str(data.get("error") or "error"))
    state[mid] = row
    jsave(STATE_FILE, state)
    return row


def refresh_all(force=False):
    res = {}
    for mid in members():
        row = fetch_limits(mid, force)
        if row:
            res[mid] = row
    return res


def cached():
    state = jload(STATE_FILE, {})
    ms = members()
    return {k: v for k, v in state.items() if k in ms}


def ctl(mid, *args, inp=None, timeout=25):
    """Команда управляющему скрипту на удалённом сервере; ответ — словарь или None."""
    import shlex
    m = members().get(mid)
    if not m:
        return None
    tmux = re.sub(r"[^A-Za-z0-9_-]", "", str(m.get("tmux") or ""))   # имя сессии tmux на втором сервере — из записи пары (иначе ctl.py ищет «ccfleet»)
    code, text = ssh_run(m, (("CC_REMOTE_TMUX=%s " % tmux) if tmux else "") + "python3 /root/cc-remote/ctl.py " + " ".join(shlex.quote(str(x)) for x in args), timeout=timeout, inp=inp)
    if code != 0:
        return None
    try:
        return json.loads(text.strip().splitlines()[-1])
    except Exception:
        return None


def claude_running(mid):
    m = members().get(mid)
    if not m:
        return False
    code, text = ssh_run(m, "tmux has-session -t %s ; echo rc=$?" % m.get("tmux", "ccfleet"))
    return "rc=0" in text
