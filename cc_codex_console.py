#!/usr/bin/env python3
# cc_codex_console — консоль Codex в панели cc-limits: интерактивный `codex` в screen-сессии
# и зеркало её экрана на странице (вкладка «Codex» рядом с консолью Claude).
#
# Только просмотр: из панели в консоль ничего не печатается (как и у консоли Claude). Печатать —
# в самой сессии (`screen -r`) или через мост Telegram. Права сессии — те же, что у моста
# (cc_codex_bridge.plan): песочница и рабочая папка берутся из его настроек, полный доступ
# сюда сам не попадает. Экран берём из лога screen и собираем через pyte (hardcopy портит
# не-ASCII — см. консоль Claude в cc_limits.py).
import os, pwd, re, subprocess, threading, time

import cc_codex

BASE = "/opt/cc-limits"  # cc_limits подставляет свой каталог данных
BIN = lambda: None  # cc_limits подставляет codex_bin
PLAN = lambda: ("read-only", None, None)  # cc_limits: → (песочница, рабочая папка, слот ChatGPT) по настройкам моста
ROW_HTML = None  # cc_limits подставляет _row_html(line, ncols): одна раскраска на обе консоли
pyte = None  # cc_limits передаёт модуль pyte

NAME = "cc-codex"  # имя screen-сессии
COLS, ROWS = 100, 32  # размер окна: детачнутая сессия иначе 80x24
HISTORY_LINES = 2000  # скроллбэк сверх экрана
LOG_MAX = 16 * 1024 * 1024  # лог растёт, пока Codex что-то рисует; сверх лимита обнуляем
_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")

_lock = threading.Lock()  # start/stop
_mlock = threading.Lock()  # состояние зеркала
_m = {"pid": None, "screen": None, "stream": None, "offset": 0, "geom": (0, 0)}


def _dir():
    """Папка консоли: у пользователя codex_user (screen пишет лог от его имени), иначе рядом с панелью."""
    u = cc_codex.runas_user()
    return os.path.join(pwd.getpwnam(u).pw_dir if u else BASE, "codex_console")


def _log():
    return os.path.join(_dir(), "console.log")


def _meta_path():
    return os.path.join(_dir(), "console.json")


def _ctl(args, timeout=10):
    """screen от имени пользователя Codex (сокеты screen у каждого пользователя свои)."""
    argv, env = cc_codex.wrap(["screen"] + list(args), cc_codex.PROFILES)
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)


def _pid():
    """PID живой сессии cc-codex или None."""
    try:
        out = _ctl(["-ls"]).stdout
    except Exception:
        return None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\." + re.escape(NAME) + r"\s", line)
        if m and "Dead" not in line:
            return m.group(1)
    return None


def _meta():
    return cc_codex.jload(_meta_path(), {}) or {}


def status():
    b = BIN()
    if not b:
        return {"available": False}
    pid = _pid()
    sandbox, cwd, slot = PLAN()
    st = {"available": True, "running": bool(pid), "plan_sandbox": sandbox, "plan_cwd": cwd}
    if pid:
        meta = _meta()
        if meta.get("pid") == pid:
            st.update(sandbox=meta.get("sandbox"), cwd=meta.get("cwd"), started=meta.get("started"))
    return st


def start(lang="ru"):
    """Запустить `codex` в screen-сессии. → (ok, сообщение)."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    with _lock:
        b = BIN()
        if not b:
            return False, t("Codex не установлен на сервере.", "Codex is not installed on this server.")
        if _pid():
            return True, t("Консоль уже запущена.", "The console is already running.")
        sandbox, cwd, slot = PLAN()
        if sandbox not in _SANDBOXES:
            return False, t("Неизвестные права доступа.", "Unknown access rights.")
        slots = cc_codex.profile_slots()
        if not slot or slot not in slots:
            slot = slots[0] if slots else ""
        if not slot:
            return False, t("Нет входа в ChatGPT: добавь аккаунт в окне Codex.", "Not signed in to ChatGPT: add an account in the Codex window.")
        if not cwd or not os.path.isdir(cwd):
            return False, t("Рабочая папка не найдена.", "Working folder not found.")
        d, log = _dir(), _log()
        os.makedirs(d, exist_ok=True)
        cc_codex.own(d)
        if os.path.exists(log):
            os.replace(log, log + ".prev")
        open(log, "w").close()
        cc_codex.own(log)
        # размер окна задаём stty внутри сессии: так codex рисует под COLS x ROWS, а зеркало читает его из pty
        script = 'stty cols "$1" rows "$2"; shift 2; exec "$@"'
        # по умолчанию screen сбрасывает лог раз в 10 секунд — зеркало отставало бы; свой rc задаёт 1 секунду с самого старта
        rc = os.path.join(d, "console.rc")
        with open(rc, "w") as f:
            f.write("logfile flush 1\n")
        cc_codex.own(rc)
        argv = ["screen", "-c", rc, "-dmS", NAME, "-L", "-Logfile", log, "sh", "-c", script, "sh", str(COLS), str(ROWS),
                b, "--no-alt-screen", "-s", sandbox, "-C", cwd]
        argv, env = cc_codex.wrap(argv, cc_codex.profile_dir(slot), {"TERM": "xterm-256color", "LANG": "C.UTF-8"})
        p = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return False, t("Не удалось запустить консоль: ", "Could not start the console: ") + (cc_codex._strip(p.stderr or p.stdout)[-200:] or "?")
        pid = None
        for _ in range(20):
            pid = _pid()
            if pid:
                break
            time.sleep(0.2)
        if not pid:
            return False, t("Консоль Codex сразу закрылась — проверь вход в ChatGPT.", "The Codex console closed right away — check the ChatGPT sign-in.")
        cc_codex._jsave(_meta_path(), {"pid": pid, "sandbox": sandbox, "cwd": cwd, "slot": slot,
                                       "started": int(time.time())})
        cc_codex.own(_meta_path())
        return True, t("Консоль Codex запущена.", "The Codex console is running.")


def stop(lang="ru"):
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    with _lock:
        if not _pid():
            return True, t("Консоль уже остановлена.", "The console is already stopped.")
        _ctl(["-S", NAME, "-X", "quit"])
        for _ in range(20):
            if not _pid():
                return True, t("Консоль Codex остановлена.", "The Codex console is stopped.")
            time.sleep(0.2)
        return False, t("Не удалось остановить консоль.", "Could not stop the console.")


def _dims(pid):
    """Размер окна screen — прямо с pty (TIOCGWINSZ), screen о нём не спрашиваем."""
    import fcntl, struct, termios
    try:
        for cpid in subprocess.run(["pgrep", "-P", pid], capture_output=True, timeout=5, text=True).stdout.split():
            try:
                link = os.readlink(f"/proc/{cpid}/fd/0")
            except OSError:
                continue
            if link.startswith("/dev/pts/"):
                fd = os.open(link, os.O_RDONLY | os.O_NOCTTY)
                try:
                    rows, cols, _x, _y = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0)))
                finally:
                    os.close(fd)
                if cols > 0 and rows > 0:
                    return max(cols, 20), max(rows, 5)
    except Exception:
        pass
    return COLS, ROWS


def _reset(pid, cols, rows):
    _m.update(pid=pid, screen=pyte.HistoryScreen(cols, rows, history=HISTORY_LINES), offset=0, geom=(cols, rows))
    _m["stream"] = pyte.ByteStream(_m["screen"])


def snapshot(want_history=False):
    """→ (экран HTML, скроллбэк HTML | None); None, если сессия не запущена."""
    pid = _pid()
    if not pid:
        with _mlock:
            _m.update(pid=None, screen=None, stream=None, offset=0)
        return None
    cols, rows = _dims(pid)
    with _mlock:
        if _m["pid"] != pid or _m["screen"] is None:
            _reset(pid, cols, rows)
        elif _m["geom"] != (cols, rows):
            _m["screen"].resize(rows, cols)
            _m["geom"] = (cols, rows)
        log = _log()
        try:
            size = os.path.getsize(log)
        except OSError:
            size = 0
        if size < _m["offset"]:
            _reset(pid, cols, rows)  # лог пересоздан — собираем экран с начала
        if size > _m["offset"]:
            with open(log, "rb") as f:
                f.seek(_m["offset"])
                data = f.read()
            _m["stream"].feed(data)
            _m["offset"] += len(data)
        if _m["offset"] > LOG_MAX:
            try:
                os.truncate(log, 0)  # экран уже в pyte; новые байты screen допишет с начала файла
                _m["offset"] = 0
            except OSError:
                pass
        screen = _m["screen"]
        cur = list(zip(screen.display, (ROW_HTML(screen.buffer[y], cols) for y in range(rows))))
        while cur and not cur[-1][0].strip():
            cur.pop()
        current_html = "\n".join(h for _, h in cur)
        history_html = None
        if want_history:
            history_html = "\n".join(ROW_HTML(line, cols) for line in screen.history.top)
    return current_html, history_html
