#!/usr/bin/env python3
# cc_codex_console — консоль Codex в панели cc-limits: интерактивный `codex` в screen-сессии
# и зеркало её экрана на странице (вкладка «Codex» рядом с консолью Claude).
#
# Из панели в консоль ничего не печатается (как и у консоли Claude). Печатать — в самой сессии
# (`screen -r`) или через мост Telegram: мост вводит сообщения прямо сюда (ask) и читает ответ из файла
# сессии Codex (rollout), так что консоль и Telegram — один разговор. Права сессии — те же, что у моста
# (cc_codex_bridge.plan): песочница и рабочая папка берутся из его настроек, полный доступ
# сюда сам не попадает. Экран берём из лога screen и собираем через pyte (hardcopy портит
# не-ASCII — см. консоль Claude в cc_limits.py).
import glob, json, os, pwd, re, shutil, subprocess, threading, time

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
APPROVAL = "never"  # никаких запросов подтверждения на экране: их некому нажать, мост ждал бы вечно
PROMPT_WAIT = 25  # после старта ждём, пока консоль нарисует поле ввода, секунд
START_WAIT = 40  # консоль должна принять сообщение (начать ход), секунд
PASTE_DELAY = 1.0  # пауза между вставкой и Enter: длинная вставка принимается не мгновенно
POLL = 0.5
TAIL = 512 * 1024  # сколько хвоста rollout смотреть, определяя «идёт ход»
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

_lock = threading.Lock()  # start/stop
_ask_lock = threading.Lock()  # одно сообщение в консоль за раз
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
        prev = _meta()
        tids = dict(prev.get("tids") or {})
        tid = tids.get(os.path.realpath(cwd))
        if tid and not find_rollout(slot, tid):
            tids.pop(os.path.realpath(cwd), None)
            tid = None
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
        # прошлый разговор этой папки продолжается (`codex resume`): остановка и перезапуск его не теряют
        argv = ["screen", "-c", rc, "-dmS", NAME, "-L", "-Logfile", log, "sh", "-c", script, "sh", str(COLS), str(ROWS),
                b] + (["resume", tid] if tid else []) + ["--no-alt-screen", "-s", sandbox, "-a", APPROVAL, "-C", cwd]
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
        cc_codex._jsave(_meta_path(), {"pid": pid, "sandbox": sandbox, "cwd": cwd, "slot": slot, "approval": APPROVAL,
                                       "started": int(time.time()), "tids": tids})
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


# ---------------------------------------------------------------- ввод из моста и ответ из файла сессии
class ConsoleError(Exception):
    pass


class Aborted(ConsoleError):
    """Запрос прерван по /stop или /new."""


def usable():
    """Можно ли вести разговор через консоль: есть codex и screen."""
    return bool(BIN()) and bool(shutil.which("screen"))


def _sessions(slot):
    return os.path.join(cc_codex.profile_dir(slot), "sessions")


def _tid_of(path):
    m = re.search(r"-(" + _UUID + r")\.jsonl$", path)
    return m.group(1) if m else None


def find_rollout(slot, tid):
    """Файл сессии Codex по id разговора или None."""
    hits = glob.glob(os.path.join(_sessions(slot), "*", "*", "*", f"rollout-*-{tid}.jsonl"))
    return hits[0] if hits else None


def _new_rollout(slot, cwd, since, exclude=None):
    """Самый свежий файл сессии с этой рабочей папкой, тронутый не раньше since (сегодня и вчера)."""
    days = sorted(glob.glob(os.path.join(_sessions(slot), "????", "??", "??")))[-2:]
    best = None
    want = os.path.realpath(cwd)
    for day in days:
        for path in glob.glob(os.path.join(day, "rollout-*.jsonl")):
            try:
                mt = os.path.getmtime(path)
                if path == exclude or mt < since or (best and mt <= best[0]):
                    continue
                with open(path, encoding="utf-8") as f:
                    meta = json.loads(f.readline()).get("payload") or {}
            except (OSError, ValueError):
                continue
            if os.path.realpath(str(meta.get("cwd") or "")) == want:
                best = (mt, path)
    return best[1] if best else None


def _events(path, off):
    """→ (события, новый сдвиг): читаем только полные строки, недописанная остаётся до следующего раза."""
    try:
        with open(path, "rb") as f:
            f.seek(off)
            data = f.read()
    except OSError:
        return [], off
    end = data.rfind(b"\n")
    if end < 0:
        return [], off
    out = []
    for line in data[:end + 1].splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out, off + end + 1


def _utc(iso):
    """Время события rollout (ISO, UTC) → секунды с эпохи; 0, если не разобрать."""
    import datetime
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _turn_open(path, since=0):
    """Идёт ли в сессии ход: последний task_started без task_complete/turn_aborted. Ход, начатый раньше since
    (запуска консоли), остался от убитого процесса — он не считается."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL))
            data = f.read()
    except OSError:
        return False
    cur, began = None, 0
    for line in data.splitlines():
        if b"task_started" in line or b"task_complete" in line or b"turn_aborted" in line:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            p = ev.get("payload") or {}
            if p.get("type") == "task_started":
                cur, began = p.get("turn_id"), _utc(ev.get("timestamp"))
            elif p.get("type") in ("task_complete", "turn_aborted") and p.get("turn_id") == cur:
                cur = None
    return cur is not None and began >= since


def _paste_text(text):
    """Что реально печатается в консоль: без управляющих символов (ESC закрыл бы вставку), без начала, которое
    консоль примет за команду (`/…` — команда Codex, `!…` — shell, `$…` — навык, `@…` — файл)."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", t).strip()
    if t[:1] in ("/", "!", "$", "@"):
        t = "» " + t
    return t


def _paste(text):
    """Вставить текст как вставку из буфера (bracketed paste): так проходят кириллица, переводы строк и длинные тексты,
    а `stuff` пришлось бы чистить от $ \\ ^ кавычек, и длинное он гонит по символу."""
    path = os.path.join(_dir(), "paste.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\x1b[200~" + text + "\x1b[201~")
    cc_codex.own(path)
    try:
        for cmd in ("readbuf", path), ("paste", "."):
            p = _ctl(["-S", NAME, "-p", "0", "-X"] + list(cmd))
            if p.returncode != 0:
                return False
        time.sleep(PASTE_DELAY)
        return _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"]).returncode == 0
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def interrupt():
    """Esc в консоль: Codex прерывает текущий ход."""
    try:
        return _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\x1b"]).returncode == 0
    except Exception:
        return False


def _wait_ready():
    """Свежая консоль рисует поле ввода не сразу: ждём, пока лог перестанет расти."""
    end, last, still = time.time() + PROMPT_WAIT, -1, 0
    while time.time() < end:
        try:
            size = os.path.getsize(_log())
        except OSError:
            size = 0
        still = still + 1 if size == last and size > 0 else 0
        if still >= 3:
            return
        last = size
        time.sleep(POLL)


def _remember(slot_cwd, tid):
    meta = _meta()
    tids = dict(meta.get("tids") or {})
    if tids.get(slot_cwd) != tid:
        tids[slot_cwd] = tid
        meta["tids"] = tids
        cc_codex._jsave(_meta_path(), meta)
        cc_codex.own(_meta_path())


def ensure(lang="ru"):
    """Консоль идёт с правами из настроек моста. Права или папка сменились — перезапуск (разговор папки продолжается),
    но не посреди запроса. → (ok, сообщение)."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    st = status()
    if not st.get("available"):
        return False, t("Codex не установлен на сервере.", "Codex is not installed on this server.")
    if st.get("running"):
        meta = _meta()
        same = (st.get("sandbox") == st.get("plan_sandbox") and meta.get("approval") == APPROVAL
                and os.path.realpath(str(st.get("cwd") or "")) == os.path.realpath(str(st.get("plan_cwd") or "")))
        if same:
            return True, ""
        tid = (meta.get("tids") or {}).get(os.path.realpath(str(st.get("cwd") or "")))
        path = find_rollout(meta.get("slot") or "", tid) if tid else None
        if path and _turn_open(path, meta.get("started") or 0):
            return False, t("Права или папка Codex сменились, но в консоли идёт запрос: дождись ответа или /stop.",
                            "Codex access or folder changed, but a request is running in the console: wait for the reply or /stop.")
        ok, msg = stop(lang)
        if not ok:
            return ok, msg
    return start(lang)


def forget(lang="ru"):
    """Начать разговор заново (/new): консоль останавливается, забыв прошлые разговоры; следующий запуск — чистый."""
    with _lock:
        meta = _meta()
        if meta.get("tids"):
            meta["tids"] = {}
            cc_codex._jsave(_meta_path(), meta)
            cc_codex.own(_meta_path())
    if _pid():
        stop(lang)


def ask(prompt, abort=None, timeout=1200, lang="ru"):
    """Напечатать prompt в консоль и дождаться ответа Codex из файла сессии. → (ответ, id разговора).
    ConsoleError — консоль не приняла запрос / закрылась / не ответила; Aborted — abort (Event) взведён."""
    text = _paste_text(prompt)
    if not text:
        raise ConsoleError("Пустое сообщение.")
    aborted = lambda: bool(abort and abort.is_set())
    with _ask_lock:
        ok, msg = ensure(lang)
        if not ok:
            raise ConsoleError(msg)
        meta = _meta()
        slot, cwd = meta.get("slot") or "", meta.get("cwd") or ""
        key = os.path.realpath(cwd)
        if time.time() - (meta.get("started") or 0) < PROMPT_WAIT + 10:
            _wait_ready()
        tid = (meta.get("tids") or {}).get(key)
        path = find_rollout(slot, tid) if tid else None
        if path and _turn_open(path, meta.get("started") or 0):
            raise ConsoleError("В консоли Codex уже идёт запрос. Подожди ответа или /stop.")
        off = os.path.getsize(path) if path else 0
        sent = time.time()
        if aborted():
            raise Aborted()
        if not _paste(text):
            raise ConsoleError("Не удалось напечатать в консоль Codex.")
        # --- ждём начала хода
        turn, answer, last_say = None, "", ""
        enter_again = sent + START_WAIT / 3
        deadline = sent + START_WAIT
        while True:
            if aborted():
                raise Aborted()
            if not turn:
                if path is None or time.time() > sent + 3:
                    found = _new_rollout(slot, cwd, sent - 2, exclude=path)
                    if found and (path is None or found != path):
                        path, off = found, 0
                if path:
                    evs, off = _events(path, off)
                else:
                    evs = []
            else:
                evs, off = _events(path, off)
            for ev in evs:
                p = ev.get("payload") or {}
                kind = p.get("type")
                if not turn:
                    if ev.get("type") == "event_msg" and kind == "task_started":
                        turn = p.get("turn_id")
                        deadline = time.time() + timeout
                    continue
                if ev.get("type") == "response_item" and kind == "message" and p.get("role") == "assistant":
                    for c in p.get("content") or []:
                        if c.get("type") == "output_text" and (c.get("text") or "").strip():
                            last_say = c["text"].strip()
                if ev.get("type") == "event_msg" and p.get("turn_id") == turn:
                    if kind == "task_complete":
                        answer = (p.get("last_agent_message") or "").strip() or last_say
                        tid = _tid_of(path) or tid
                        if tid:
                            _remember(key, tid)
                        if not answer:
                            raise ConsoleError("Codex не вернул ответа.")
                        return answer, tid
                    if kind == "turn_aborted":
                        if aborted():
                            raise Aborted()
                        raise ConsoleError("Запрос в консоли Codex прерван.")
            if not _pid():
                raise ConsoleError("Консоль Codex закрылась, не ответив.")
            now = time.time()
            if not turn and now > enter_again:
                enter_again = deadline + 1  # один раз: Enter мог уйти раньше, чем консоль приняла вставку
                _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"])
            if now > deadline:
                if turn:
                    interrupt()
                    raise ConsoleError("Codex не ответил за отведённое время, запрос прерван.")
                raise ConsoleError("Консоль Codex не приняла сообщение: посмотри её экран на вкладке Codex.")
            time.sleep(POLL)


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
