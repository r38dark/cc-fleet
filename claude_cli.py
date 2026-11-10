#!/usr/bin/env python3
"""Версия и обновление Claude Code и Codex на этом сервере: npm-пакеты (@anthropic-ai/claude-code, @openai/codex) и нативная установка Claude Code
(~/.local/share/claude/versions).

Один модуль и для панели (импорт), и для второго сервера (ctl.py cli …, там только Claude Code): состояние лежит в файлах рядом с модулем, а сам npm /
`claude update` работает отдельным процессом (start_new_session), так что и панель, и ctl.py после запуска сразу возвращаются и потом читают итог из
файлов. Запущенные сессии не трогаем: новая версия подхватится при следующем запуске. Программу ради версии не запускаем (версия — из package.json
или из имени папки версии).
Команды (Claude Code): status [check] | update [ВЕРСИЯ|latest] | rollback — печатают одну строку JSON."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

TOOLS = {"claude": {"pkg": "@anthropic-ai/claude-code", "bin": "claude"},
         "codex": {"pkg": "@openai/codex", "bin": "codex"}}
PKG = TOOLS["claude"]["pkg"]
NODE_MIN = 18
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("CC_CLI_STATE_DIR") or HERE
LATEST_TTL = 1800     # страница сама просит проверку, если прошлой больше полчаса (поле checked в status)
RUN_LIMIT = 900       # npm / обновление дольше 15 минут — считаем зависшим
HOME = os.environ.get("HOME") or "/root"
EXTRA_BIN = ("/usr/local/bin", "/usr/bin", "/bin", HOME + "/.local/bin", HOME + "/.npm-global/bin", "/root/.npm-global/bin")
BIN_HINT = {}         # панель подсказывает, где её Codex (cc_limits.codex_bin()): {"codex": "/путь/к/codex"}


def _files(tool):
    return (os.path.join(STATE_DIR, "%s_cli_state.json" % tool), os.path.join(STATE_DIR, "%s_cli.log" % tool), os.path.join(STATE_DIR, "%s_cli.code" % tool))


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


def _env(native=False):
    node = _tool("node")
    path = os.pathsep.join(([os.path.dirname(node)] if node else []) + [os.environ.get("PATH", "")])
    env = dict(os.environ, NO_COLOR="1", PATH=path, npm_config_update_notifier="false", npm_config_fund="false", npm_config_audit="false")
    if native:   # страховка: подкоманда update плагины не поднимает, но если бы подняла — Telegram-канал основной сессии (bot.pid) не трогаем
        env["TELEGRAM_STATE_DIR"] = os.path.join(STATE_DIR, "tg_off")
    return env


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


def _read_version(root, pkg, local):
    p = os.path.join(root, "node_modules" if local else os.path.join("lib", "node_modules"), pkg, "package.json")
    try:
        with open(p, encoding="utf-8") as f:
            v = str(json.load(f).get("version") or "")
        return v if VERSION_RE.match(v) else None
    except Exception:
        return None


def _native_link(start, versions_dir):
    """Ссылка, которая прямо указывает в папку версий (её переставляет и `claude update`, и наш «Вернуть»)."""
    p, seen = start, set()
    while p and os.path.islink(p) and p not in seen:
        seen.add(p)
        t = os.readlink(p)
        t = t if os.path.isabs(t) else os.path.normpath(os.path.join(os.path.dirname(p), t))
        if os.path.dirname(t) == versions_dir:
            return p
        p = t
    return None


def _native_versions(versions_dir):
    out = []
    try:
        for n in os.listdir(versions_dir):
            p = os.path.join(versions_dir, n)
            if VERSION_RE.match(n) and os.path.isfile(p) and os.access(p, os.X_OK):
                out.append(n)
    except OSError:
        pass
    return sorted(out, key=_vtuple)


def _native_prev(info):
    """Самая новая из сохранённых версий старше текущей — на неё можно вернуться, даже если обновляли не кнопкой."""
    cur = _vtuple(info.get("version"))
    older = [v for v in _native_versions(info.get("versions_dir") or "") if cur and _vtuple(v) < cur]
    return older[-1] if older else ""


def find_install(tool="claude"):
    """Где стоит программа: {'kind': 'npm', 'prefix', 'local', 'version'} | {'kind': 'native', 'version', 'versions_dir', 'link', 'bin'} | {'kind': None}.
    local — пакет лежит в <папка>/node_modules (без lib), ставится `npm install --prefix <папка>` без -g."""
    t = TOOLS[tool]
    pkg = t["pkg"]
    w = BIN_HINT.get(tool) or shutil.which(t["bin"], path=os.pathsep.join([os.environ.get("PATH", "")] + list(EXTRA_BIN)))
    real = os.path.realpath(w) if w else ""
    m = re.match(r"^(.*)/lib/node_modules/" + re.escape(pkg) + r"(/|$)", real)
    if m:
        prefixes = [(m.group(1) or "/", False)]            # программа из PATH лежит в глобальном npm-пакете — обновляем именно его
    else:
        m = re.match(r"^(.*)/node_modules/" + re.escape(pkg) + r"(/|$)", real)
        if m:
            prefixes = [(m.group(1) or "/", True)]         # локальная установка: <папка>/node_modules/<пакет>
        elif real and tool == "claude":
            d, ver = os.path.dirname(real), os.path.basename(real)
            if VERSION_RE.match(ver) and os.path.basename(d) == "versions":
                return {"kind": "native", "version": ver, "versions_dir": d, "link": _native_link(w, d), "bin": w}   # нативная: ссылка → versions/X.Y.Z
            return {"kind": "native", "version": None, "path": real, "bin": w}              # нативный бинарь непривычного вида: только показываем
        elif real:
            return {"kind": "native", "version": None, "path": real, "bin": w}
        elif tool == "claude":
            prefixes = [(HOME + "/.npm-global", False), ("/root/.npm-global", False), ("/usr", False), ("/usr/local", False)]   # в PATH нет — типовые места
        else:
            prefixes = []
    seen = set()
    for p, local in prefixes:
        if (p, local) in seen:
            continue
        seen.add((p, local))
        v = _read_version(p, pkg, local)
        if v:
            return {"kind": "npm", "prefix": p, "local": local, "version": v}
    return {"kind": None}


def _load(tool):
    try:
        with open(_files(tool)[0], encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(tool, st):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = _files(tool)[0]
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, path)


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


def _tail(tool, n=12):
    try:
        with open(_files(tool)[1], encoding="utf-8", errors="replace") as f:
            lines = [ANSI.sub("", l.rstrip())[:300] for l in f.readlines()[-n:]]
        return "\n".join(l for l in lines if l.strip())
    except Exception:
        return ""


def latest_version(tool="claude", timeout=15):
    """Свежая версия: CC_CLI_LATEST (для проверок) → реестр npm по HTTPS (нативной установке npm не нужен) → `npm view`."""
    pkg = TOOLS[tool]["pkg"]
    over = os.environ.get("CC_CLI_LATEST")
    if over:
        return over if VERSION_RE.match(over) else None
    if os.environ.get("CC_CLI_REGISTRY") != "npm":
        try:
            req = urllib.request.Request("https://registry.npmjs.org/" + pkg + "/latest", headers={"User-Agent": "cc-fleet", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                v = str(json.load(r).get("version") or "")
            if VERSION_RE.match(v):
                return v
        except Exception:
            pass
    npm = _tool("npm")
    if not npm:
        return None
    try:
        r = subprocess.run([npm, "view", pkg, "version"], capture_output=True, text=True, timeout=25, env=_env(), cwd="/")
    except Exception:
        return None
    lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    v = lines[-1] if r.returncode == 0 and lines else None
    return v if v and VERSION_RE.match(v) else None


def _finish(tool, st):
    """Процесс закончился — вычисляем итог по коду выхода и версии на диске."""
    info = find_install(tool)
    try:
        with open(_files(tool)[2], encoding="utf-8") as f:
            code = int(f.read().strip())
    except Exception:
        code = None
    now = info.get("version") if info.get("kind") in ("npm", "native") else None
    st["finished"] = time.time()
    st["version_after"] = now
    if code == 0:
        st["state"], st["err"] = "done", ""
        if st.get("op") == "update" and now and st.get("from_version") and now != st["from_version"]:
            st["prev_version"] = st["from_version"]   # для кнопки «Вернуть»
        if st.get("op") == "rollback":
            st["prev_version"] = ""                   # вернули — возвращать больше нечего
    else:
        tail = [l for l in _tail(tool, 40).splitlines() if l.strip()]
        st["state"] = "failed"
        st["err"] = (tail[-1] if tail else "обновление завершилось с ошибкой")[:300] if code is not None else "обновление остановлено до конца"
    _save(tool, st)
    return st


def status(check=False, tool="claude"):
    info = find_install(tool)
    st = _load(tool)
    if st.get("state") == "running":
        if _alive(st.get("pid")):
            if time.time() - float(st.get("started") or 0) > RUN_LIMIT:
                try:
                    os.killpg(int(st["pid"]), 15)
                except Exception:
                    pass
                st["state"], st["err"], st["finished"] = "failed", "обновление шло дольше 15 минут и было остановлено", time.time()
                _save(tool, st)
        else:
            st = _finish(tool, st)
    if check:   # в сеть (реестр npm) ходим только по явной просьбе: опрос статуса должен быть быстрым и на втором сервере тоже
        v = latest_version(tool)
        if v:
            st["latest"], st["latest_ts"] = v, time.time()
        else:
            st["latest_ts"] = time.time()   # реестр недоступен: время проверки обновляем, прежняя «свежая» версия остаётся
        _save(tool, st)
    kind = info.get("kind")
    cur = info.get("version") if kind in ("npm", "native") else None
    latest = st.get("latest") or None
    a, b = _vtuple(cur), _vtuple(latest)
    nodes = node_info()
    running = st.get("state") == "running"
    prev = st.get("prev_version") or (_native_prev(info) if kind == "native" else "")
    if kind == "npm":
        can = nodes["ready"]
    elif kind == "native":
        can = bool(cur and info.get("bin") and info.get("link"))
    else:
        can = False
    out = {"ok": True, "tool": tool, "kind": kind, "version": cur, "latest": latest,
           "update_available": bool(a and b and b > a), "prefix": info.get("prefix") or "",
           "prev_version": prev if prev and prev != cur else "",
           "state": st.get("state") or "idle", "op": st.get("op") or "", "target": st.get("target") or "",
           "from_version": st.get("from_version") or "", "version_after": st.get("version_after") or "",
           "err": st.get("err") or "", "log": _tail(tool) if (running or st.get("state") in ("failed", "done")) else "",
           "node": nodes, "can_update": bool(can and not running),
           "checked": st.get("latest_ts") or 0, "ttl": LATEST_TTL}
    if kind == "native":
        out["path"] = info.get("path") or info.get("link") or ""
    return out


def _spawn(tool, cmd, native):
    for p in _files(tool)[1:]:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    return subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=_env(native), cwd="/", start_new_session=True)


def start(target="latest", op="update", tool="claude"):
    info = find_install(tool)
    kind = info.get("kind")
    if kind == "native" and not (info.get("version") and info.get("link") and info.get("bin")):
        return {"ok": False, "error": "not_npm"}          # нативный бинарь непривычного вида: что и как обновлять, не знаем
    if kind not in ("npm", "native"):
        return {"ok": False, "error": "not_installed"}
    if target != "latest" and not VERSION_RE.match(str(target)):
        return {"ok": False, "error": "bad_target"}
    if kind == "npm" and not node_info()["ready"]:
        return {"ok": False, "error": "no_node"}
    st = _load(tool)
    if st.get("state") == "running" and _alive(st.get("pid")):
        return dict(status(tool=tool), ok=True, already=True)
    log, code = _files(tool)[1], _files(tool)[2]
    if kind == "native":
        # штатное обновление нативной установки: `claude update` скачивает свежую версию в папку версий и переставляет ссылку (номер версии выбрать нельзя)
        cmd = "%s update >%s 2>&1; echo $? >%s" % (shlex.quote(info["bin"]), shlex.quote(log), shlex.quote(code))
        target = "latest"
    else:
        flags = [] if info.get("local") else ["-g"]      # локальная установка (<папка>/node_modules) — без -g
        cmd = "%s install %s --prefix %s %s >%s 2>&1; echo $? >%s" % (
            shlex.quote(_tool("npm")), " ".join(flags), shlex.quote(info["prefix"]), shlex.quote(TOOLS[tool]["pkg"] + "@" + str(target)), shlex.quote(log), shlex.quote(code))
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        proc = _spawn(tool, cmd, kind == "native")
    except Exception as e:
        return {"ok": False, "error": "spawn", "detail": type(e).__name__}
    st.update(op=op, target=str(target), from_version=info["version"], state="running", pid=proc.pid, started=time.time(),
              finished=None, err="", prefix=info.get("prefix") or "", version_after="")
    _save(tool, st)
    return dict(status(tool=tool), ok=True)


def _native_rollback(info, prev):
    """Вернуть нативную установку на сохранённую версию: ссылка переставляется атомарно (файлы версий не трогаем)."""
    dst = os.path.join(info["versions_dir"], prev)
    if prev not in _native_versions(info["versions_dir"]) or not info.get("link"):
        return {"ok": False, "error": "nothing_to_rollback"}
    tmp = info["link"] + ".tmp%d" % os.getpid()
    try:
        os.symlink(dst, tmp)
        os.replace(tmp, info["link"])
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return {"ok": False, "error": "spawn", "detail": type(e).__name__}
    st = _load("claude")
    st.update(op="rollback", target=prev, from_version=info["version"], version_after=prev, state="done", err="", finished=time.time(), prev_version="")
    _save("claude", st)
    return dict(status(tool="claude"), ok=True)


def rollback(tool="claude"):
    info = find_install(tool)
    st = _load(tool)
    prev = st.get("prev_version") or (_native_prev(info) if info.get("kind") == "native" else "")
    if not prev or prev == info.get("version") or not VERSION_RE.match(prev):
        return {"ok": False, "error": "nothing_to_rollback"}
    if st.get("state") == "running" and _alive(st.get("pid")):
        return dict(status(tool=tool), ok=True, already=True)
    if info.get("kind") == "native":
        return _native_rollback(info, prev)
    return start(prev, op="rollback", tool=tool)


def run(args):
    """Диспетчер для ctl.py (Claude Code на втором сервере): status [check] | update [версия] | rollback."""
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
