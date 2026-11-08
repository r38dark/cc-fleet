"""Мастер «Второй сервер»: подключение второго сервера, на который панель передаёт работу Claude (по ssh).

Что делает мастер (кнопки в «Общие настройки» → «Второй сервер»):
  1. «Проверить»   — заходит на второй сервер по ключу панели и проверяет: вход по ssh, root, python3, tmux, rsync, Claude Code
                    (/usr/bin/claude), вход Claude (.credentials.json), Telegram-плагин. Нужное и недостающее показывает списком.
  2. «Установить недостающее» — apt-get install tmux rsync python3 (если на втором сервере есть apt).
  3. «Подключить» — кладёт ctl.py и usage.py на второй сервер, создаёт там ключ для обратного ssh (сюда), добавляет его в
                    authorized_keys этого сервера с ограничением from=<адрес второго сервера>, проверяет обратный доступ и записывает
                    пару в remote_members.json (host, port, key, tmux, back_host, back_key).
  4. «Отключить»  — убирает пару и ключ обратного ssh с этого сервера (на втором сервере ничего не удаляется).
Вход в Claude на втором сервере делает кнопка «Войти заново» на его карточке (ссылка и код, токен остаётся там)."""
import json
import os
import re
import shlex
import socket
import subprocess
import threading
import time

import cc_remote as R

BASE = R.BASE
KEY_PATH = os.environ.get("CC_REMOTE_KEY") or os.path.join(BASE, "remote_key")   # ключ панели для входа на второй сервер
HOME = os.path.expanduser("~")
AUTH_FILE = os.environ.get("CC_REMOTE_AUTH") or os.path.join(HOME, ".ssh", "authorized_keys")   # на ЭТОМ сервере
BACK_KEY = "/root/.ssh/id_ed25519_ccfleet_back"      # на втором сервере: ключ обратного ssh сюда (тот же путь, что в cc_remote_mode)
DEFAULT_TMUX = "ccfleet"
MEMBER_ID = "prod"                                   # ключ записи в remote_members.json (в коде — «место работы на втором сервере»)
MARK = "cc-fleet-back"                               # метка строки в authorized_keys: по ней мастер находит и убирает свою строку

_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,251}|[0-9A-Fa-f:]{2,45}")
_TMUX = re.compile(r"[A-Za-z0-9_-]{1,30}")
_job = {"id": 0, "state": "idle", "title": "", "text": "", "checks": None, "ts": 0.0}
_job_lock = threading.Lock()


# ---------------------------------------------------------------- ключ панели и данные этого сервера
def panel_key():
    """Ключ панели для входа на второй сервер: создаётся при первом обращении. → {"path", "pub"}."""
    if not os.path.exists(KEY_PATH):
        os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "cc-fleet-panel", "-f", KEY_PATH],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError("ssh-keygen: " + (r.stderr or r.stdout).strip()[:200])
        os.chmod(KEY_PATH, 0o600)
    with open(KEY_PATH + ".pub", encoding="utf-8") as f:
        return {"path": KEY_PATH, "pub": f.read().strip()}


def default_back_host():
    """Адрес этого сервера для второго: домен из public_url, иначе исходящий IP."""
    try:
        cfg = R.jload(os.path.join(BASE, "config.json"), {})
        url = str(cfg.get("public_url") or "")
        m = re.match(r"https?://([^/:]+)", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        out = subprocess.run(["ip", "-4", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return ""


def local_checks():
    """Что нужно на ЭТОМ сервере: ssh, ssh-keygen, rsync."""
    out = []
    for tool, hint in (("ssh", "apt-get install -y openssh-client"), ("ssh-keygen", "apt-get install -y openssh-client"),
                       ("rsync", "apt-get install -y rsync")):
        ok = subprocess.run(["sh", "-c", "command -v %s" % tool], capture_output=True, timeout=5).returncode == 0
        out.append({"id": "local_" + tool, "label": "На этом сервере есть %s" % tool, "ok": ok, "block": True,
                    "hint": "" if ok else "Поставь: " + hint})
    return out


# ---------------------------------------------------------------- проверка второго сервера
_PROBE = r"""
echo uid=$(id -u)
echo os=$( (. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME") | head -1)
echo python3=$(command -v python3)
echo tmux=$(command -v tmux)
echo rsync=$(command -v rsync)
echo apt=$(command -v apt-get)
echo claude=$([ -x /usr/bin/claude ] && echo /usr/bin/claude)
echo claude_other=$(command -v claude)
echo login=$([ -s /root/.claude/.credentials.json ] && echo yes)
echo tg=$( (ls -d /root/.claude/plugins/cache/*/telegram* /root/.claude/channels/telegram 2>/dev/null | head -1) )
"""


def _member(host, port, user, tmux):
    m = {"host": host, "user": user, "key": panel_key()["path"], "tmux": tmux}
    if port and int(port) != 22:
        m["port"] = int(port)
    return m


def valid_fields(host, port, user, tmux, back_host):
    """→ (ok, сообщение, поля)."""
    host, user, tmux, back_host = (str(x or "").strip() for x in (host, user or "root", tmux or DEFAULT_TMUX, back_host))
    try:
        port = 22 if port is None or str(port).strip() == "" else int(port)
    except (TypeError, ValueError):
        return False, "Порт — число от 1 до 65535.", {}
    if not _HOST.fullmatch(host):
        return False, "Адрес второго сервера: IP или имя (латиница, цифры, точка, дефис).", {}
    if not (1 <= port <= 65535):
        return False, "Порт — число от 1 до 65535.", {}
    if user != "root":
        return False, "Сейчас поддерживается вход под root.", {}
    if not _TMUX.fullmatch(tmux):
        return False, "Имя сессии tmux: латиница, цифры, «_» и «-», до 30 знаков.", {}
    if back_host and not _HOST.fullmatch(back_host):
        return False, "Адрес этого сервера для второго: IP или имя.", {}
    return True, "", {"host": host, "port": port, "user": user, "tmux": tmux, "back_host": back_host}


def probe(m):
    """Проверки второго сервера. → {"checks": [...], "ready": bool, "apt": bool, "missing": [...]}.
    block=True — без этого подключить нельзя; остальное — предупреждение."""
    code, text = R.ssh_run(m, _PROBE, timeout=40)
    checks = []
    if code != 0:
        if code == 124:
            detail, hint = "нет ответа за 40 с", "Проверь адрес и порт, что сервер включён и ssh доступен с этого сервера."
        elif code == 255:
            detail = (text or "").strip().splitlines()[-1][:200] if (text or "").strip() else "вход не удался"
            hint = ("Добавь ключ панели (шаг 1) в /root/.ssh/authorized_keys на втором сервере, проверь адрес и порт; "
                    "на втором сервере разрешены вход root по ключу (PermitRootLogin prohibit-password или yes) и ssh.")
        else:
            detail, hint = "код %s" % code, "Проверь вход вручную: ssh -i %s root@адрес" % KEY_PATH
        checks.append({"id": "ssh", "label": "Вход по ssh", "ok": False, "block": True, "detail": detail, "hint": hint})
        return {"checks": checks, "ready": False, "apt": False, "missing": []}
    info = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip()
    apt = bool(info.get("apt"))
    missing = [t for t in ("tmux", "rsync", "python3") if not info.get(t)]
    checks.append({"id": "ssh", "label": "Вход по ssh", "ok": True, "block": True, "detail": info.get("os") or ""})
    checks.append({"id": "root", "label": "Вход под root", "ok": info.get("uid") == "0", "block": True,
                   "hint": "" if info.get("uid") == "0" else "Нужен root: добавь ключ панели в /root/.ssh/authorized_keys."})
    for tool in ("python3", "tmux", "rsync"):
        ok = bool(info.get(tool))
        checks.append({"id": tool, "label": "Установлен %s" % tool, "ok": ok, "block": True,
                       "hint": "" if ok else ("Нажми «Установить недостающее» (apt-get)." if apt else "Поставь %s вручную." % tool)})
    cl = bool(info.get("claude"))
    other = info.get("claude_other")
    if cl:
        hint = ""
    elif other:
        hint = "Claude Code найден в %s, а панель ждёт /usr/bin/claude: выполни на втором сервере  ln -sf %s /usr/bin/claude" % (other, other)
    else:
        hint = "Поставь Claude Code на втором сервере (см. инструкцию, раздел «Второй сервер»), затем проверь ещё раз."
    checks.append({"id": "claude", "label": "Claude Code (/usr/bin/claude)", "ok": cl, "block": True, "hint": hint})
    login = info.get("login") == "yes"
    checks.append({"id": "login", "label": "Вход Claude на втором сервере", "ok": login, "block": False,
                   "hint": "" if login else "Не обязательно сейчас: после подключения нажми «Войти заново» на карточке второго сервера."})
    tg = bool(info.get("tg"))
    checks.append({"id": "tg", "label": "Telegram-плагин Claude", "ok": tg, "block": False,
                   "hint": "" if tg else "Нужен, чтобы на втором сервере Claude отвечал в Telegram (инструкция: «Второй сервер» → Telegram)."})
    ready = all(c["ok"] for c in checks if c.get("block"))
    return {"checks": checks, "ready": ready, "apt": apt, "missing": missing}


def check(fields):
    ok, msg, f = valid_fields(fields.get("host"), fields.get("port"), fields.get("user"), fields.get("tmux"), fields.get("back_host"))
    if not ok:
        return {"ok": False, "message": msg}
    local = local_checks()
    res = probe(_member(f["host"], f["port"], f["user"], f["tmux"]))
    res["checks"] = local + res["checks"]
    res["ready"] = res["ready"] and all(c["ok"] for c in local)
    return dict(res, ok=True, message="Готово к подключению." if res["ready"] else "Есть что поправить — см. список.")


def install_missing(fields):
    """apt-get install недостающего на втором сервере. → (ok, сообщение)."""
    ok, msg, f = valid_fields(fields.get("host"), fields.get("port"), fields.get("user"), fields.get("tmux"), fields.get("back_host"))
    if not ok:
        return False, msg
    m = _member(f["host"], f["port"], f["user"], f["tmux"])
    res = probe(m)
    if not res["checks"][0]["ok"]:
        return False, "Нет входа по ssh: сначала добавь ключ панели."
    if not res["missing"]:
        return True, "Всё нужное уже есть."
    if not res["apt"]:
        return False, "На втором сервере нет apt-get: поставь вручную: " + ", ".join(res["missing"]) + "."
    cmd = "DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq %s" % " ".join(res["missing"])
    code, text = R.ssh_run(m, cmd, timeout=420)
    if code != 0:
        return False, "apt-get не справился (код %s): %s" % (code, (text or "").strip()[-200:])
    return True, "Установлено: " + ", ".join(res["missing"]) + "."


# ---------------------------------------------------------------- authorized_keys этого сервера
def _auth_read():
    try:
        with open(AUTH_FILE, encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _auth_write(lines):
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    tmp = "%s.tmp%d" % (AUTH_FILE, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n" if lines else "")
    os.chmod(tmp, 0o600)
    os.replace(tmp, AUTH_FILE)


def auth_add(pub, src_ip, member=MEMBER_ID):
    """Строка обратного ключа: только с адреса второго сервера, без терминала и пересылок. Старую строку этой пары заменяет."""
    tag = "%s:%s" % (MARK, member)
    keep = [ln for ln in _auth_read() if tag not in ln]
    opts = 'from="%s",no-pty,no-agent-forwarding,no-X11-forwarding,no-port-forwarding' % src_ip
    keep.append("%s %s %s" % (opts, pub.strip(), tag))
    _auth_write(keep)


def auth_remove(member=MEMBER_ID):
    tag = "%s:%s" % (MARK, member)
    lines = _auth_read()
    keep = [ln for ln in lines if tag not in ln]
    if len(keep) != len(lines):
        _auth_write(keep)
        return True
    return False


# ---------------------------------------------------------------- подключение
def connect(fields):
    """Подключает второй сервер. → (ok, сообщение, шаги [{"label", "ok"}])."""
    steps = []

    def step(label, ok, extra=""):
        steps.append({"label": label, "ok": ok, "detail": extra})
        return ok

    ok, msg, f = valid_fields(fields.get("host"), fields.get("port"), fields.get("user"), fields.get("tmux"), fields.get("back_host"))
    if not ok:
        return False, msg, steps
    back_host = f["back_host"] or default_back_host()
    if not back_host:
        return False, "Не определил адрес этого сервера для второго: впиши его в поле «Адрес этого сервера».", steps
    m = _member(f["host"], f["port"], f["user"], f["tmux"])
    res = probe(m)
    if not step("Проверка второго сервера", res["ready"], "; ".join(c["label"] for c in res["checks"] if c.get("block") and not c["ok"])):
        return False, "Второй сервер не готов: " + "; ".join((c["label"] + (" — " + c["hint"] if c.get("hint") else "")) for c in res["checks"] if c.get("block") and not c["ok"]), steps
    try:
        import cc_remote_mode as M
        deployed = M.deploy_tools(m)
    except Exception as exc:
        deployed = False
        steps.append({"label": "ctl.py и usage.py", "ok": False, "detail": type(exc).__name__})
    if not deployed:
        return False, "Не получилось положить ctl.py и usage.py на второй сервер.", steps
    step("ctl.py и usage.py на втором сервере", True)
    keycmd = ("mkdir -p /root/.ssh && chmod 700 /root/.ssh && [ -f %(k)s ] || ssh-keygen -q -t ed25519 -N '' -C cc-fleet-back -f %(k)s; cat %(k)s.pub"
              % {"k": BACK_KEY})
    code, text = R.ssh_run(m, keycmd, timeout=40)
    pub = (text or "").strip().splitlines()[-1] if code == 0 and (text or "").strip() else ""
    if not step("Ключ обратного ssh на втором сервере", pub.startswith("ssh-")):
        return False, "Не удалось создать ключ обратного ssh на втором сервере.", steps
    try:
        src_ip = socket.gethostbyname(f["host"])
    except OSError:
        src_ip = f["host"]
    try:
        auth_add(pub, src_ip)
        step("Ключ добавлен в authorized_keys этого сервера (только с адреса второго)", True)
    except OSError as exc:
        step("Ключ добавлен в authorized_keys этого сервера", False, type(exc).__name__)
        return False, "Не удалось записать %s: %s" % (AUTH_FILE, type(exc).__name__), steps
    back = ("ssh -i %s -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new root@%s true && echo BACK_OK"
            % (BACK_KEY, shlex.quote(back_host)))
    code, text = R.ssh_run(m, back, timeout=40)
    back_ok = "BACK_OK" in (text or "")
    if not step("Обратный доступ: второй сервер входит сюда", back_ok, "" if back_ok else (text or "").strip()[-160:]):
        auth_remove()  # без работающего обратного входа ключ на этом сервере не оставляем
        return False, ("Второй сервер не достучался сюда по адресу %s (порт 22). Проверь адрес в поле «Адрес этого сервера» и что ssh "
                       "на этом сервере доступен с второго." % back_host), steps
    members = R.jload(R.MEMBERS_FILE, {})
    members = members if isinstance(members, dict) else {}
    mid = next((k for k, v in members.items() if isinstance(v, dict) and v.get("host") == f["host"]), MEMBER_ID)
    rec = dict(members.get(mid) or {})
    rec.update(label=rec.get("label") or "Claude PROD", host=f["host"], user=f["user"], key=m["key"], tmux=f["tmux"],
               back_host=back_host, back_key=BACK_KEY)
    if f["port"] != 22:
        rec["port"] = f["port"]
    else:
        rec.pop("port", None)
    members[mid] = rec
    R.jsave(R.MEMBERS_FILE, members)
    try:
        os.chmod(R.MEMBERS_FILE, 0o600)
    except OSError:
        pass
    step("Пара записана в remote_members.json", True)
    try:  # первый опрос сразу: карточка второго сервера появляется в панели не через минуту, а сейчас (нет входа Claude — карточка скажет «Войти заново»)
        R.fetch_limits(mid, True)
    except Exception:
        pass
    return True, "Второй сервер подключён.", steps


def remove(member=MEMBER_ID):
    """Убирает пару и ключ обратного ssh с этого сервера. → (ok, сообщение)."""
    members = R.jload(R.MEMBERS_FILE, {})
    members = members if isinstance(members, dict) else {}
    ids = [member] if member in members else list(members)[:1]
    if not ids:
        return False, "Второй сервер не подключён."
    for k in ids:
        members.pop(k, None)
        auth_remove(k)
    auth_remove(MEMBER_ID)
    R.jsave(R.MEMBERS_FILE, members)
    return True, "Второй сервер отключён: пара и ключ обратного входа убраны с этого сервера (на втором сервере ничего не удалялось)."


def status():
    """Состояние для страницы: ключ панели, подключённая пара, адрес по умолчанию."""
    members = R.members()
    mid = next(iter(members), "")
    m = members.get(mid) or {}
    try:
        key = panel_key()
        pub, kerr = key["pub"], ""
    except Exception as exc:
        pub, kerr = "", str(exc)[:160]
    return {"ok": True, "pub": pub, "key_error": kerr, "default_tmux": DEFAULT_TMUX, "back_host": default_back_host(),
            "member": ({"host": m.get("host"), "port": m.get("port") or 22, "tmux": m.get("tmux") or DEFAULT_TMUX,
                        "back_host": m.get("back_host") or "", "label": m.get("label") or ""} if m else None)}


# ---------------------------------------------------------------- фоновые задачи (apt-get и подключение дольше минуты)
def start_job(title, fn):
    """Запускает fn() → dict в потоке; одновременно одна задача. → (ok, id | сообщение)."""
    with _job_lock:
        if _job["state"] == "running" and time.time() - _job["ts"] < 600:
            return False, "Уже идёт: " + _job["title"]
        _job.update(id=_job["id"] + 1, state="running", title=title, text="", checks=None, ts=time.time())
        jid = _job["id"]

    def run():
        try:
            res = fn()
        except Exception as exc:
            res = {"ok": False, "message": "Сбой: %s" % type(exc).__name__}
        with _job_lock:
            if _job["id"] == jid:
                _job.update(state="ok" if res.get("ok") else "error", text=res.get("message", ""), checks=res.get("steps"), ts=time.time())

    threading.Thread(target=run, daemon=True, name="remote-setup").start()
    return True, jid


def job_view():
    with _job_lock:
        return dict(id=_job["id"], state=_job["state"], title=_job["title"], message=_job["text"], steps=_job["checks"])


# ---------------------------------------------------------------- страница и маршруты
UI = r"""
<style>
#fleetRemoteSetup .rs-row{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;margin:10px 0 4px}
#fleetRemoteSetup label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--fleet-muted,#8c9bad)}
#fleetRemoteSetup input{padding:7px 9px;border:1px solid var(--fleet-line,#263140);border-radius:7px;background:var(--fleet-terminal,#0b0d10);color:var(--txt,#e8eaf0);font:13px system-ui,sans-serif}
#fleetRemoteSetup input:focus-visible{outline:1px solid var(--fleet-accent,#73dbb7)}
#fleetRemoteSetup .rs-step{margin:12px 0 4px;font-size:12px;font-weight:600;color:var(--txt,#e8eaf0)}
#fleetRemoteSetup .rs-step i{font-style:normal;color:var(--fleet-accent,#73dbb7);margin-right:6px}
#fleetRemoteSetup pre{margin:6px 0;padding:8px 10px;white-space:pre-wrap;word-break:break-all;font:11px/1.5 ui-monospace,Consolas,monospace;background:var(--fleet-terminal,#0b0d10);border:1px solid var(--fleet-line,#263140);border-radius:7px;color:#cfe9e0}
#fleetRemoteSetup .rs-list{margin:8px 0;padding:0;list-style:none;font-size:12px}
#fleetRemoteSetup .rs-list li{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--fleet-line,#1d2733)}
#fleetRemoteSetup .rs-list .ic{flex:none;width:16px}
#fleetRemoteSetup .rs-list small{display:block;color:var(--fleet-muted,#8c9bad);font-size:11px;margin-top:2px}
#fleetRemoteSetup .rs-msg{min-height:16px;margin-top:6px;font-size:11px;color:var(--fleet-muted,#8c9bad)}
#fleetRemoteSetup .rs-msg.bad{color:#ef8f8f}#fleetRemoteSetup .rs-msg.ok{color:#68ac92}
#fleetRemoteSetup .rs-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
</style>
<script>
(function(){try{
var base=(typeof API!=='undefined'?API:location.origin+'/cc-hook/'),tok=(typeof TOKEN!=='undefined'?TOKEN:'');
function $i(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function api(path,body){return fetch(base+path,body?{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':tok},body:JSON.stringify(body)}:{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.json()})}
var st=null,sec=null,last=null,busy=false;
function msg(t,cls){var m=$i('rsMsg');if(m){m.textContent=t||'';m.className='rs-msg'+(cls?' '+cls:'')}}
function fields(){return {host:$i('rsHost').value.trim(),port:$i('rsPort').value.trim()||'22',back_host:$i('rsBack').value.trim(),tmux:$i('rsTmux').value.trim()||st.default_tmux}}
function copy(txt,btn){try{navigator.clipboard.writeText(txt).then(function(){var o=btn.textContent;btn.textContent='Скопировано';setTimeout(function(){btn.textContent=o},1400)})}catch(e){}}
function list(items){return '<ul class="rs-list">'+items.map(function(c){var ic=c.ok?'✅':(c.block===false?'⚠️':'🔴');return '<li><span class="ic">'+ic+'</span><span>'+esc(c.label)+(c.detail?' · '+esc(c.detail):'')+((!c.ok&&c.hint)?'<small>'+esc(c.hint)+'</small>':'')+'</span></li>'}).join('')+'</ul>'}
function render(){
 if(!sec||!st)return;var body=sec.querySelector('[data-body]');
 if(st.member){
  body.innerHTML='<div class="fleet-catalog-note">Подключён: <b>'+esc(st.member.host)+'</b>'+(st.member.port&&st.member.port!=22?':'+esc(st.member.port):'')+' · сессия tmux «'+esc(st.member.tmux)+'» · обратный адрес этого сервера: '+esc(st.member.back_host||'—')+'. Вход в Claude на втором сервере — кнопка «Войти заново» на его карточке.</div>'
   +'<div class="rs-acts"><button type="button" class="ghostbtn" id="rsRecheck">Проверить связь</button><button type="button" class="ghostbtn" id="rsDrop">Отключить</button></div><div id="rsOut"></div><div class="rs-msg" id="rsMsg"></div>';
  $i('rsRecheck').onclick=function(){run('check',{host:st.member.host,port:st.member.port,back_host:st.member.back_host,tmux:st.member.tmux})};
  $i('rsDrop').onclick=function(){if(!confirm('Отключить второй сервер? Пара и ключ обратного входа уберутся с этого сервера, на втором ничего не удалится.'))return;api('remote/setup/remove',{}).then(function(d){msg(d.message,d.ok?'ok':'bad');if(d.ok)load()})};
  return}
 var cmd="echo '"+st.pub+"' >> /root/.ssh/authorized_keys";
 body.innerHTML='<div class="fleet-catalog-note">Второй сервер — машина, на которую панель передаёт работу Claude (когда лимит кончился здесь). Нужен доступ по ssh под root.</div>'
  +'<div class="rs-step"><i>1</i>Шаг 1 из 3 · Ключ панели — добавь на втором сервере</div>'
  +'<div class="fleet-catalog-note">Выполни на втором сервере эту команду (или вставь строку в /root/.ssh/authorized_keys):</div><pre id="rsKey">'+esc(cmd)+'</pre><div class="rs-acts"><button type="button" class="ghostbtn" id="rsCopy">Скопировать команду</button></div>'
  +'<div class="rs-step"><i>2</i>Шаг 2 из 3 · Адрес второго сервера и проверка</div>'
  +'<div class="rs-row"><label>Адрес (IP или имя)<input id="rsHost" placeholder="203.0.113.10" autocomplete="off" spellcheck="false"></label><label>Порт ssh<input id="rsPort" value="22" size="5" autocomplete="off"></label>'
  +'<label>Адрес этого сервера для второго<input id="rsBack" autocomplete="off" spellcheck="false"></label><label>Сессия tmux<input id="rsTmux" size="10" autocomplete="off" spellcheck="false"></label></div>'
  +'<div class="rs-acts"><button type="button" class="ghostbtn" id="rsCheck">Проверить</button></div>'
  +'<div id="rsOut"></div>'
  +'<div class="rs-step"><i>3</i>Шаг 3 из 3 · Подключить</div><div class="fleet-catalog-note">Мастер положит ctl.py и usage.py на второй сервер, создаст там ключ обратного входа (сюда, только с его адреса), проверит связь в обе стороны и запишет пару.</div>'
  +'<div class="rs-acts"><button type="button" class="ghostbtn" id="rsFix" hidden>Установить недостающее</button><button type="button" class="ghostbtn" id="rsGo" disabled>Подключить</button></div><div class="rs-msg" id="rsMsg"></div>';
 $i('rsBack').value=st.back_host||'';$i('rsTmux').value=st.default_tmux;
 $i('rsCopy').onclick=function(){copy(cmd,this)};
 $i('rsCheck').onclick=function(){run('check',fields())};
 $i('rsFix').onclick=function(){run('fix',fields())};
 $i('rsGo').onclick=function(){run('connect',fields())};
 if(last)show(last)}
function show(d){last=d;var out=$i('rsOut');if(!out)return;var items=(d.checks||[]).concat(d.steps||[]);out.innerHTML=items.length?list(items):'';
 var fix=$i('rsFix'),go=$i('rsGo');if(fix)fix.hidden=!(d.checks||[]).some(function(c){return !c.ok&&c.block&&c.hint&&/apt-get/.test(c.hint)});if(go)go.disabled=!d.ready}
function run(what,f){
 if(busy)return;busy=true;msg('Работаю…');
 var path=what==='check'?'remote/setup/check':what==='fix'?'remote/setup/fix':'remote/setup/connect';
 api(path,f).then(function(d){
  if(d.job){poll(d.job,what,f);return}
  busy=false;msg(d.message,d.ok?'ok':'bad');if(d.checks){d.ready=!!d.ready;show(d)}if(what==='connect'&&d.ok)load()
 }).catch(function(){busy=false;msg('Панель не ответила.','bad')})}
function poll(jid,what,f){api('remote/setup/job').then(function(j){
  if(j.state==='running'){msg((j.title||'Работаю')+'…');setTimeout(function(){poll(jid,what,f)},2000);return}
  busy=false;msg(j.message,j.state==='ok'?'ok':'bad');if(j.steps)show({checks:[],steps:j.steps,ready:false});
  if(what==='fix'){run('check',f)}else if(what==='connect'&&j.state==='ok')load()
 }).catch(function(){busy=false;msg('Панель не ответила.','bad')})}
function load(){return api('remote/setup').then(function(d){if(d&&d.ok){st=d;render()}})}
function place(){var c=document.querySelector('#scrim .fleet-common-settings');if(!c)return false;
 if(!sec){sec=document.createElement('section');sec.className='fleet-settings-group';sec.id='fleetRemoteSetup';
  sec.innerHTML='<div class="fleet-settings-group-title">Второй сервер</div><div data-body><div class="fleet-catalog-note">Загрузка…</div></div>';c.append(sec);load()}
 else if(c.lastElementChild!==sec&&!c.contains(document.activeElement))c.append(sec);
 return true}
var n=0;(function tryPlace(){if(!place()&&++n<40)setTimeout(tryPlace,250)})();
var sc=$i('scrim');if(sc&&window.MutationObserver)new MutationObserver(function(){if(!sc.hidden&&sc.dataset.view==='general'){place()}}).observe(sc,{attributes:true,attributeFilter:['hidden','data-view']});
}catch(e){console.warn('remote-setup',e)}})();
</script>
"""


def inject(page):
    return page.replace("</body>", UI + "</body>", 1) if "</body>" in page else page + UI


def install(ns):
    """Маршруты /api/remote/setup* и блок «Второй сервер» в «Общие настройки»."""
    base = ns["H"]
    posts = ("/api/remote/setup/check", "/api/remote/setup/fix", "/api/remote/setup/connect", "/api/remote/setup/remove")

    class SetupHandler(base):
        def do_GET(self):
            from urllib.parse import urlparse
            path = urlparse(self.path).path
            if path not in ("/api/remote/setup", "/api/remote/setup/job"):
                return base.do_GET(self)
            if not self._authed():
                return self._send(403, {"ok": False, "message": "forbidden"})
            if path.endswith("/job"):
                return self._send(200, job_view())
            return self._send(200, status())

        def do_POST(self):
            from urllib.parse import urlparse
            path = urlparse(self.path).path
            if path not in posts:
                return base.do_POST(self)
            if not self._authed():
                return self._send(403, {"ok": False, "message": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length") or "0")
                body = json.loads(self.rfile.read(min(max(n, 0), 8192)) or b"{}") if n else {}
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            if path.endswith("/check"):
                return self._send(200, check(body))
            if path.endswith("/remove"):
                ok, message = remove()
                return self._send(200, {"ok": ok, "message": message})

            def fix():
                ok, message = install_missing(body)
                return {"ok": ok, "message": message}

            def go():
                ok, message, steps = connect(body)
                return {"ok": ok, "message": message, "steps": steps}
            ok, jid = start_job("Устанавливаю недостающее" if path.endswith("/fix") else "Подключаю второй сервер", fix if path.endswith("/fix") else go)
            return self._send(200 if ok else 409, {"ok": ok, "job": jid} if ok else {"ok": False, "message": jid})

    ns["H"] = SetupHandler
    ns["PAGE"] = inject(ns["PAGE"])
