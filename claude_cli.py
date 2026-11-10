#!/usr/bin/env python3
"""Версия и обновление Claude Code (npm-пакет @anthropic-ai/claude-code) на этом сервере.

Один модуль и для панели (импорт), и для второго сервера (ctl.py cli …): состояние лежит в файлах рядом с модулем, а сам npm работает
отдельным процессом (start_new_session), так что и панель, и ctl.py после запуска сразу возвращаются и потом читают итог из файлов.
Запущенные сессии Claude не трогаем: новая версия подхватится при следующем запуске.
Команды: status [check] | update [ВЕРСИЯ|latest] | rollback — печатают одну строку JSON."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

PKG = "@anthropic-ai/claude-code"
NODE_MIN = 18
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("CC_CLI_STATE_DIR") or HERE
STATE = os.path.join(STATE_DIR, "claude_cli_state.json")
LOG = os.path.join(STATE_DIR, "claude_cli.log")
CODE = os.path.join(STATE_DIR, "claude_cli.code")
LATEST_TTL = 1800     # страница сама просит проверку, если прошлой больше полчаса (поле checked в status)
RUN_LIMIT = 900       # npm дольше 15 минут — считаем зависшим
HOME = os.environ.get("HOME") or "/root"
EXTRA_BIN = ("/usr/local/bin", "/usr/bin", "/bin", HOME + "/.npm-global/bin", "/root/.npm-global/bin")


def _tool(name):
    """Путь к node/npm: CC_CLI_NODE / CC_CLI_NPM (для проверок), затем PATH и типовые папки."""
    over = os.environ.get("CC_CLI_" + name.upper())
    if over and os.access(over, os.X_OK):
        return over
    w = shutil.which(name)
    if w:
        return w
    for d in EXTRA_BIN:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _env():
    node = _tool("node")
    path = os.pathsep.join(([os.path.dirname(node)] if node else []) + [os.environ.get("PATH", "")])
    return dict(os.environ, NO_COLOR="1", PATH=path, npm_config_update_notifier="false", npm_config_fund="false", npm_config_audit="false")


def node_info():
    """→ {node: 'v20.1.0'|None, npm: bool, ready: bool}; ready — Node не старше NODE_MIN и есть npm."""
    node, npm = _tool("node"), _tool("npm")
    ver = None
    if node:
        try:
            ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=8).stdout.strip() or None
        except Exception:
            ver = None
    m = re.match(r"v?(\d+)", ver or "")
    return {"node": ver, "npm": bool(npm), "ready": bool(npm and m and int(m.group(1)) >= NODE_MIN)}


def _vtuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return None


def _pkg_json(prefix):
    return os.path.join(prefix, "lib", "node_modules", PKG, "package.json")


def _read_version(prefix):
    try:
        with open(_pkg_json(prefix), encoding="utf-8") as f:
            v = str(json.load(f).get("version") or "")
        return v if VERSION_RE.match(v) else None
    except Exception:
        return None


def find_install():
    """Где стоит Claude Code: {'kind': 'npm', 'prefix', 'version'} | {'kind': 'native', 'path'} | {'kind': None}."""
    w = shutil.which("claude", path=os.pathsep.join([os.environ.get("PATH", "")] + list(EXTRA_BIN)))
    real = os.path.realpath(w) if w else ""
    m = re.match(r"^(.*)/lib/node_modules/" + re.escape(PKG) + r"(/|$)", real)
    if m:
        prefixes = [m.group(1) or "/"]                    # claude из PATH лежит в npm-пакете — обновляем именно его
    elif real:
        return {"kind": "native", "path": real}           # claude из PATH — не npm (нативный установщик): чужой npm-пакет рядом не трогаем
    else:
        prefixes = [HOME + "/.npm-global", "/root/.npm-global", "/usr", "/usr/local"]   # claude нет в PATH — ищем пакет в типовых местах
    seen = set()
    for p in prefixes:
        if p in seen:
            continue
        seen.add(p)
        v = _read_version(p)
        if v:
            return {"kind": "npm", "prefix": p, "version": v}
    if real:
        return {"kind": "native", "path": real}
    return {"kind": None}


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(st):
    tmp = STATE + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    try:   # зомби (завершился, но не прибран) живым не считаем
        with open("/proc/%d/stat" % int(pid), encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except Exception:
        return True


def _tail(n=12):
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = [ANSI.sub("", l.rstrip())[:300] for l in f.readlines()[-n:]]
        return "\n".join(l for l in lines if l.strip())
    except Exception:
        return ""


def latest_version(timeout=25):
    npm = _tool("npm")
    if not npm:
        return None
    try:
        r = subprocess.run([npm, "view", PKG, "version"], capture_output=True, text=True, timeout=timeout, env=_env(), cwd="/")
    except Exception:
        return None
    lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    v = lines[-1] if r.returncode == 0 and lines else None
    return v if v and VERSION_RE.match(v) else None


def _finish(st):
    """Процесс npm закончился — вычисляем итог по коду выхода и версии на диске."""
    info = find_install()
    try:
        with open(CODE, encoding="utf-8") as f:
            code = int(f.read().strip())
    except Exception:
        code = None
    now = info.get("version") if info.get("kind") == "npm" else None
    st["finished"] = time.time()
    st["version_after"] = now
    if code == 0:
        st["state"], st["err"] = "done", ""
        if st.get("op") == "update" and now and st.get("from_version") and now != st["from_version"]:
            st["prev_version"] = st["from_version"]   # для кнопки «Вернуть»
        if st.get("op") == "rollback":
            st["prev_version"] = ""                   # вернули — возвращать больше нечего
    else:
        tail = [l for l in _tail(40).splitlines() if l.strip()]
        st["state"] = "failed"
        st["err"] = (tail[-1] if tail else "npm завершился с ошибкой")[:300] if code is not None else "npm остановлен до конца"
    _save(st)
    return st


def status(check=False):
    info = find_install()
    st = _load()
    if st.get("state") == "running":
        if _alive(st.get("pid")):
            if time.time() - float(st.get("started") or 0) > RUN_LIMIT:
                try:
                    os.killpg(int(st["pid"]), 15)
                except Exception:
                    pass
                st["state"], st["err"], st["finished"] = "failed", "npm работал дольше 15 минут и был остановлен", time.time()
                _save(st)
        else:
            st = _finish(st)
    if check:   # в сеть (реестр npm) ходим только по явной просьбе: опрос статуса должен быть быстрым и на втором сервере тоже
        v = latest_version()
        if v:
            st["latest"], st["latest_ts"] = v, time.time()
            _save(st)
        else:
            st["latest_ts"] = time.time()   # реестр недоступен: время проверки обновляем, прежняя «свежая» версия остаётся
            _save(st)
    cur = info.get("version") if info.get("kind") == "npm" else None
    latest = st.get("latest") or None
    a, b = _vtuple(cur), _vtuple(latest)
    nodes = node_info()
    running = st.get("state") == "running"
    prev = st.get("prev_version") or ""
    out = {"ok": True, "kind": info.get("kind"), "version": cur, "latest": latest,
           "update_available": bool(a and b and b > a), "prefix": info.get("prefix") or "",
           "prev_version": prev if prev and prev != cur else "",
           "state": st.get("state") or "idle", "op": st.get("op") or "", "target": st.get("target") or "",
           "from_version": st.get("from_version") or "", "version_after": st.get("version_after") or "",
           "err": st.get("err") or "", "log": _tail() if (running or st.get("state") in ("failed", "done")) else "",
           "node": nodes, "can_update": bool(info.get("kind") == "npm" and nodes["ready"] and not running),
           "checked": st.get("latest_ts") or 0, "ttl": LATEST_TTL}
    if info.get("kind") == "native":
        out["path"] = info.get("path")
    return out


def start(target="latest", op="update"):
    info = find_install()
    if info.get("kind") != "npm":
        return {"ok": False, "error": "not_npm" if info.get("kind") == "native" else "not_installed"}
    if target != "latest" and not VERSION_RE.match(str(target)):
        return {"ok": False, "error": "bad_target"}
    nodes = node_info()
    if not nodes["ready"]:
        return {"ok": False, "error": "no_node"}
    st = _load()
    if st.get("state") == "running" and _alive(st.get("pid")):
        return dict(status(), ok=True, already=True)
    npm = _tool("npm")
    cmd = "%s install -g --prefix %s %s >%s 2>&1; echo $? >%s" % (
        shlex.quote(npm), shlex.quote(info["prefix"]), shlex.quote(PKG + "@" + str(target)), shlex.quote(LOG), shlex.quote(CODE))
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        for p in (CODE, LOG):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
        proc = subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=_env(), cwd="/", start_new_session=True)
    except Exception as e:
        return {"ok": False, "error": "spawn", "detail": type(e).__name__}
    st.update(op=op, target=str(target), from_version=info["version"], state="running", pid=proc.pid, started=time.time(),
              finished=None, err="", prefix=info["prefix"], version_after="")
    _save(st)
    return dict(status(), ok=True)


def rollback():
    st = _load()
    prev = st.get("prev_version") or ""
    cur = (find_install() or {}).get("version")
    if not prev or prev == cur or not VERSION_RE.match(prev):
        return {"ok": False, "error": "nothing_to_rollback"}
    return start(prev, op="rollback")


def run(args):
    """Диспетчер для ctl.py: status [check] | update [версия] | rollback."""
    cmd = args[0] if args else "status"
    if cmd == "status":
        return status(check=len(args) > 1 and args[1] == "check")
    if cmd == "update":
        return start(args[1] if len(args) > 1 else "latest")
    if cmd == "rollback":
        return rollback()
    return {"ok": False, "error": "bad_command"}


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1:]), ensure_ascii=False))
