#!/usr/bin/env python3
# cc_codex_console — консоль Codex в панели cc-limits: интерактивный `codex` в screen-сессии
# и зеркало её экрана на странице (вкладка «Codex» рядом с консолью Claude).
#
# Ввод с панели, из самой сессии
# (`screen -r`) или через мост Telegram: мост вводит сообщения прямо сюда (ask) и читает ответ из файла
# сессии Codex (rollout), так что консоль и Telegram — один разговор. Права сессии — те же, что у моста
# (cc_codex_bridge.plan): песочница и рабочая папка берутся из его настроек, полный доступ
# сюда сам не попадает. Экран берём из лога screen и собираем через pyte (hardcopy портит
# не-ASCII — см. консоль Claude в cc_limits.py).
import glob, json, os, pwd, re, shutil, stat, subprocess, threading, time

import cc_codex
import cc_session
import cc_codex_terminal

BASE = "/opt/cc-limits"  # cc_limits подставляет свой каталог данных
BIN = lambda: None  # cc_limits подставляет codex_bin
PLAN = lambda: ("read-only", None, None)  # cc_limits: → (песочница, рабочая папка, слот ChatGPT) по настройкам моста
ROW_HTML = None  # cc_limits подставляет _row_html(line, ncols): одна раскраска на обе консоли
pyte = None  # cc_limits передаёт модуль pyte

NAME = "cc-codex"  # имя screen-сессии
UNIT = 'cc-codex-console.service'
COLS, ROWS = 100, 32  # размер окна: детачнутая сессия иначе 80x24
CLI_CWD = "/opt/codex-trial"  # каталог запуска команды из `cxw`


def cli_cwd():
    """Каталог запуска юнита консоли: у нас на деве это /opt/codex-trial, на чистой установке его нет —
    тогда корень (рабочая папка самого codex задаётся отдельно, ключом --cd)."""
    return CLI_CWD if os.path.isdir(CLI_CWD) else "/"

HISTORY_LINES = 2000  # скроллбэк сверх экрана
LOG_MAX = 16 * 1024 * 1024  # лог растёт, пока Codex что-то рисует; сверх лимита обнуляем
_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
APPROVAL = "never"  # никаких запросов подтверждения на экране: их некому нажать, мост ждал бы вечно
PRESERVE_THREAD = lambda: False
INPUT_ALLOWED = lambda: True
PAUSED = lambda: False  # cc_profiles.bind подставляет: роль Codex в профиле балансера «пауза»
MCP = lambda: []  # cc_limits: ключи `-c` с инструментами Notion-агента (пусто вне резерва); сменились — консоль перезапускается
PROMPT_WAIT = 25  # после старта ждём, пока консоль нарисует поле ввода, секунд
START_WAIT = 40  # консоль должна принять сообщение (начать ход), секунд
ENTER_RETRY = 3.0  # если первый Enter не начал ход — одна ранняя повторная попытка
PASTE_DELAY = 1.0  # пауза между вставкой и Enter: длинная вставка принимается не мгновенно
POLL = 0.5
CMD_DELAY = 1.5  # между набранной командой (/compact) и Enter
CMD_WAIT = 15  # сколько ждать, что Codex начал ход после команды, секунд
TAIL = 512 * 1024  # сколько хвоста rollout смотреть, определяя «идёт ход»
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

_lock = threading.Lock()  # start/stop
_ask_lock = threading.Lock()  # одно сообщение в консоль за раз
_live_lock = threading.Lock()  # короткие операции с вводом, без ожидания ответа модели
_live_request = None
LIVE_INPUT = True
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


def _ctl(args, timeout=10, terminal=None):
    """screen от имени пользователя Codex (сокеты screen у каждого пользователя свои)."""
    terminal = terminal or cc_codex_terminal.runtime(_meta(), BASE, _dir())
    extra = {"SCREENDIR": terminal["screen_dir"]} if terminal["screen_dir"] else {}
    argv, env = cc_codex.wrap([terminal["screen_bin"]] + list(args), cc_codex.PROFILES, extra)
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)


def _known_pid():
    """Проверяем живой screen и его сокет; сбой отдельного `screen -ls` не означает остановку."""
    try:
        meta = _meta()
        pid = str(meta.get('pid') or '')
        if not pid.isdigit():
            return None
        user = cc_codex.runas_user()
        pw = pwd.getpwnam(user) if user else pwd.getpwuid(os.geteuid())
        proc = '/proc/'+pid
        if os.stat(proc).st_uid != pw.pw_uid:
            return None
        with open(proc+'/comm') as stream:
            if stream.read().strip().lower() != 'screen':
                return None
        with open(proc+'/cmdline', 'rb') as stream:
            if NAME.encode() not in stream.read().split(b'\0'):
                return None
        terminal = cc_codex_terminal.runtime(meta, BASE, _dir())
        directory = terminal['screen_dir'] or '/run/screen/S-'+pw.pw_name
        socket = os.stat(os.path.join(directory, pid+'.'+NAME))
        if not stat.S_ISSOCK(socket.st_mode) or socket.st_uid != pw.pw_uid:
            return None
        return pid
    except (OSError, KeyError, ValueError):
        return None


def _pid(terminal=None):
    """PID живой сессии cc-codex или None."""
    known = _known_pid() if terminal is None else None
    if known:
        return known
    try:
        out = _ctl(["-ls"], terminal=terminal).stdout
    except Exception:
        return None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\." + re.escape(NAME) + r"\s", line)
        if m and "Dead" not in line:
            return m.group(1)
    return None


def _meta():
    return cc_codex.jload(_meta_path(), {}) or {}


def frozen():
    """Процесс Codex заморожен паузой профиля: cc_profiles._codex_pause шлёт SIGSTOP и пишет pid и время старта
    в profile_runtime/codex-paused.json. Верим только живому процессу: состояние T и то же время старта
    (файл после остановки консоли остаётся со старым pid, pid мог достаться другому процессу)."""
    try:
        with open(os.path.join(BASE, "profile_runtime", "codex-paused.json")) as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return False
    for row in rows if isinstance(rows, list) else []:
        try:
            with open("/proc/%d/stat" % int(row["pid"])) as f:
                tail = f.read().rsplit(")", 1)[1].split()
            if tail[0] == "T" and tail[19] == str(row["start"]):
                return True
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
    return False


def status():
    b = BIN()
    if not b:
        return {"available": False}
    pid = _pid()
    sandbox, cwd, slot = PLAN()
    st = {"available": True, "running": bool(pid), "plan_sandbox": sandbox, "plan_cwd": cwd, "plan_slot": slot}
    try:
        profile_paused = bool(PAUSED())
    except Exception:
        profile_paused = False
    if profile_paused:
        st["profile_paused"] = True  # и у остановленной консоли: страница по этому признаку не запускает её сама
    if pid:
        meta = _meta()
        if meta.get("pid") == pid:
            st.update(sandbox=meta.get("sandbox"), cwd=meta.get("cwd"), started=meta.get("started"))
        fr = frozen()
        if fr:
            st["frozen"] = True
        if fr or profile_paused:
            st["paused"] = True  # пауза по профилю: процесс могли запустить заново и он уже не заморожен — плашка всё равно нужна
    return st


def active_settings():
    """Модель/effort и ID берутся из индекса действующей беседы, без токенов."""
    meta = _meta()
    return cc_session.capture(meta, cc_codex.profile_dir)


def current_turn_open():
    if not _pid():
        return False
    meta = _meta()
    settings = active_settings()
    path = settings.get('rollout_path')
    if not path and settings.get('thread_id'):
        path = find_rollout(meta.get('slot') or '', settings['thread_id'])
    return bool(path and _turn_open(path, meta.get('started') or 0))


def busy():
    return _ask_lock.locked() or current_turn_open()


def apply_plan():
    """Применить сохранённый профиль в паузе, не прерывая принятый ввод."""
    if not _pid() or not _ask_lock.acquire(blocking=False):
        return False, 'Изменения ожидают свободной консоли.'
    try:
        if current_turn_open():
            return False, 'Изменения применятся после ответа.'
        before = _meta().get('started')
        ok, message = ensure()
        if ok and _meta().get('started') != before:
            ok, message = verify_ready()
        return ok, message
    finally:
        _ask_lock.release()


def request_settings(values, lang='ru'):
    """Отложить применение модели, если идёт ответ; явный выбор никогда не теряется."""
    meta = _meta()
    desired = active_settings()
    desired.update(meta.get('pending_settings') or {})
    desired.update({key: values[key] for key in ('model', 'effort', 'service_tier') if key in values})
    meta['pending_settings'] = desired
    cc_codex._jsave(_meta_path(), meta)
    cc_codex.own(_meta_path())
    if not _ask_lock.acquire(blocking=False):
        return True, 'Модель сохранена; будет применена после текущего ответа.', True
    try:
        if current_turn_open():
            return True, 'Модель сохранена; будет применена после текущего ответа.', True
        ok, message = ensure(lang)
        if ok:
            ok, message = verify_ready()
        return ok, ('Модель и уровень рассуждений применены к консоли.' if ok else message), False
    finally:
        _ask_lock.release()


def send_input(text, lang='ru'):
    """Явный ввод человека: slash-команды не превращаются в обычный текст."""
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 48000:
        return False, 'Нужно непустое сообщение размером до 48 КБ.'
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', text.replace('\r\n', '\n').replace('\r', '\n')).strip()
    if not INPUT_ALLOWED():
        return False, 'Codex на паузе: активен служебный режим другой стороны.'
    is_command = bool(re.fullmatch(r'/[A-Za-z][A-Za-z0-9_-]{0,79}(?:[ \t]+.*)?', text, re.S))
    # обычное сообщение можно отправлять, пока Codex отвечает: он поставит его в очередь. Не пускаем только пока консоль
    # занята запросом моста (его ответ читается из файла сессии) и слэш-команды в ходе ответа.
    if not _ask_lock.acquire(blocking=False):
        return False, 'В консоли Codex идёт запрос моста Telegram. Повтори через несколько секунд.'
    if is_command and current_turn_open():
        _ask_lock.release()
        return False, 'В консоли Codex идёт ответ: команду можно отправить после его завершения (или нажми Esc).'
    try:
        ok, message = ensure(lang)
        if not ok:
            return False, message
        meta = _meta()
        if time.time() - (meta.get('started') or 0) < PROMPT_WAIT + 10:
            _wait_ready()
        command = re.fullmatch(r'(/[A-Za-z][A-Za-z0-9_-]{0,79})(?:[ \t]+(.*))?', text)
        if command:
            prefix, args = command.groups()
            ok = _ctl(['-S', NAME, '-p', '0', '-X', 'stuff', prefix+(' ' if args else '')]).returncode == 0
            if ok:
                time.sleep(CMD_DELAY)
                ok = _paste(args) if args else _ctl(['-S', NAME, '-p', '0', '-X', 'stuff', '\r']).returncode == 0
        else:
            ok = _paste(text)
        return ok, 'Ввод передан в консоль Codex.' if ok else 'Консоль не приняла ввод.'
    finally:
        _ask_lock.release()


def _retire_unit():
    """The screen socket can disappear before systemd has released its unit."""
    subprocess.run(['/usr/bin/systemctl','stop',UNIT],capture_output=True,timeout=20)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        result=subprocess.run(['/usr/bin/systemctl','show',UNIT,'-p','LoadState','--value'],capture_output=True,text=True,timeout=5)
        if result.stdout.strip()=='not-found' or result.returncode==0 and not result.stdout.strip():return True
        if result.returncode:return False
        time.sleep(.1)
    return False


def start(lang="ru"):
    """Запустить `codex` в screen-сессии. → (ok, сообщение)."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    with _lock:
        b = BIN()
        if not b:
            return False, t("Codex не установлен на сервере.", "Codex is not installed on this server.")
        if _pid():
            return True, t("Консоль уже запущена.", "The console is already running.")
        if not _retire_unit():
            return False, t('Предыдущая служба консоли ещё останавливается. Повтори подключение.', 'The previous console service is still stopping. Retry the connection.')
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
        settings = cc_session.capture(prev, cc_codex.profile_dir, cwd, prev.get("slot") or slot)
        settings.update(prev.get("pending_settings") or {})
        tids = dict(prev.get("tids") or {})
        tid = settings.get('thread_id') or tids.get(os.path.realpath(cwd))
        if settings.get('new_session'):
            tid = None
            settings.pop('rollout_path', None)
        if tid and not (settings.get('rollout_path') and os.path.isfile(settings['rollout_path'])) and not find_rollout(slot, tid):
            return False, t('Файл выбранной беседы не найден. Перезапуск отменён, чтобы не открыть другой разговор.',
                            'The selected conversation file is missing. Restart cancelled to avoid opening a different conversation.')
        if tid:
            tids[os.path.realpath(cwd)] = tid
        d, log = _dir(), _log()
        os.makedirs(d, exist_ok=True)
        cc_codex.own(d)
        terminal = cc_codex_terminal.target(BASE, d)
        if terminal["screen_dir"]:
            os.makedirs(terminal["screen_dir"], mode=0o700, exist_ok=True)
            os.chmod(terminal["screen_dir"], 0o700)
            cc_codex.own(terminal["screen_dir"])
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
            f.write("term screen-256color\n")
            if terminal["screen_rgb"]:
                f.write("truecolor on\n")
            # Screen 4.9 maps the outer SGR mouse prefix ESC[< to its X10 prefix
            # ESC[M without converting the payload; Codex then types coordinates.
            # Keep the legacy key prefix so SGR reports pass through unchanged.
            f.write('termcapinfo * "Km=\\E[M"\n')
        cc_codex.own(rc)
        mcp = list(MCP())
        # прошлый разговор этой папки продолжается (`codex resume`): остановка и перезапуск его не теряют
        # Экран работает как foreground-процесс отдельной transient-службы systemd.
        # Поэтому KillMode=control-group у cc-limits не завершает консоль при рестарте моста.
        # Один локальный TUI в screen принимает ввод и от cxw, и от Telegram-моста.
        # Запускаем обычную команду пользователя; metadata ID нужен мосту для чтения rollout.
        codex_bin = "./node_modules/.bin/codex" if os.path.abspath(b) == os.path.join(CLI_CWD, "node_modules/.bin/codex") else b
        settings["thread_id"] = tid or settings.get("thread_id")
        codex_args = cc_session.launch_args(codex_bin, settings, sandbox, APPROVAL, mcp)
        argv = [terminal["screen_bin"], "-c", rc, "-D", "-mS", NAME, "-L", "-Logfile", log, "sh", "-c", script, "sh", str(COLS), str(ROWS)] + codex_args
        extra = {"TERM": "xterm-256color", "LANG": "C.UTF-8"}
        if terminal["screen_dir"]:
            extra["SCREENDIR"] = terminal["screen_dir"]
        argv, env = cc_codex.wrap(argv, cc_codex.profile_dir(slot), extra)
        # systemd-run стартует юнит с чистым окружением (env панели ему не передаётся): без codex_user
        # CODEX_HOME терялся и codex брал ~/.codex — просил вход заново. Задаём переменные юниту явно.
        # У runuser переменные уже внутри команды (env -i K=V) — там ничего не добавляем.
        setenv = []
        if argv and os.path.basename(argv[0]) != 'runuser':
            _e = dict(cc_codex.EXTRA_ENV() or {}, **extra)
            _e['CODEX_HOME'] = cc_codex.profile_dir(slot)
            setenv = ['--setenv=%s=%s' % (k, v) for k, v in _e.items()]
        # systemd запускает ExecStart с ограниченным PATH; runuser должен быть абсолютным путём.
        if argv and argv[0] == "runuser":
            argv[0] = shutil.which("runuser") or "/usr/sbin/runuser"
        unit_cwd = cli_cwd()
        unit_argv = ["/usr/bin/systemd-run", "--unit="+UNIT, "--collect", "--no-block",
                     "--property=Type=exec", "--property=KillMode=control-group",
                     *setenv, "--working-directory=" + unit_cwd, "--", *argv]
        p = subprocess.run(unit_argv, env={"PATH": "/usr/bin:/bin"}, cwd=unit_cwd,
                           capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return False, t("Не удалось запустить консоль: ", "Could not start the console: ") + (cc_codex._strip(p.stderr or p.stdout)[-200:] or "?")
        pid = None
        for _ in range(20):
            pid = _pid(terminal=terminal)
            if pid:
                break
            time.sleep(0.2)
        if not pid:
            return False, t("Консоль Codex сразу закрылась — проверь вход в ChatGPT.", "The Codex console closed right away — check the ChatGPT sign-in.")
        cc_codex._jsave(_meta_path(), {"pid": pid, "sandbox": sandbox, "cwd": cwd, "slot": slot, "approval": APPROVAL,
                                       "mcp": mcp, "started": time.time(), "tids": tids,
                                       "settings": settings, "history_home": settings.get("history_home"), **terminal})
        cc_codex.own(_meta_path())
        return True, t("Консоль Codex запущена.", "The Codex console is running.")


def stop(lang="ru"):
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    with _lock:
        if not _pid():
            ok=_retire_unit()
            return ok, t("Консоль уже остановлена.", "The console is already stopped.") if ok else t('Служба консоли ещё останавливается.', 'The console service is still stopping.')
        _ctl(["-S", NAME, "-X", "quit"])
        if not _retire_unit():return False, t('Служба консоли ещё останавливается.', 'The console service is still stopping.')
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
    shared = cc_session.capture(_meta(), cc_codex.profile_dir)
    if shared.get("thread_id") == tid and shared.get("rollout_path") and os.path.isfile(shared["rollout_path"]):
        return shared["rollout_path"]
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


def _open_turn_id(path, since=0):
    """Последнее управляющее событие: начало длинного хода может быть далеко за хвостом."""
    try:
        with open(path, 'rb') as stream:
            stream.seek(0, os.SEEK_END)
            pos, carry = stream.tell(), b''
            completed = set()
            while pos:
                count = min(TAIL, pos)
                pos -= count
                stream.seek(pos)
                lines = (stream.read(count) + carry).split(b'\n')
                carry = lines[0] if pos else b''
                for line in reversed(lines[1:] if pos else lines):
                    if not any(marker in line for marker in (b'task_started', b'task_complete', b'turn_aborted')):
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    payload = event.get('payload') or {}
                    if event.get('type') != 'event_msg':
                        continue
                    kind = payload.get('type')
                    if kind in ('task_complete', 'turn_aborted'):
                        completed.add(payload.get('turn_id'))
                    if kind == 'task_started':
                        tid = payload.get('turn_id')
                        return tid if tid not in completed and _utc(event.get('timestamp')) >= since else None
    except OSError:
        return False
    return False


def _turn_open(path, since=0):
    return bool(_open_turn_id(path, since))


def mark():
    """Точка в файле сессии Codex перед отправкой сообщения: путь, сдвиг и открытый ход (если есть).
    По ней recover() после перезапуска балансера находит ход, на который уже никто не ждёт. None — файла ещё нет."""
    try:
        meta = _meta()
        saved = active_settings() if _pid() else {}
        path = saved.get('rollout_path')
        tid = saved.get('thread_id') or (meta.get('tids') or {}).get(os.path.realpath(meta.get('cwd') or ''))
        if not path and tid:
            path = find_rollout(meta.get('slot') or '', tid)
        if not path or not os.path.isfile(path):
            return None
        return {'path': path, 'off': os.path.getsize(path), 'turn': _open_turn_id(path, meta.get('started') or 0) or None}
    except Exception:
        return None


def recover(point, sent, abort=None, timeout=None, lang='ru'):
    """Дочитать ход, ожидание которого оборвал перезапуск балансера. point — результат mark() до отправки сообщения,
    sent — время отправки. → (ответ, id разговора); (None, id) — ход прерван или так и не начался.
    ConsoleError — консоль закрылась, не ответив; Aborted — abort (Event) взведён."""
    point = point or {}
    meta = _meta()
    slot, cwd = meta.get('slot') or '', meta.get('cwd') or ''
    path, off, turn = point.get('path'), point.get('off') or 0, point.get('turn')
    last_say, quiet, switched = '', time.time(), False
    deadline = None if timeout is None else time.time() + timeout
    while True:
        if abort is not None and abort.is_set():
            raise Aborted()
        if path is None:
            path, off = _new_rollout(slot, cwd, sent - 2), 0
        events, off = _events(path, off) if path else ([], off)
        for event in events:
            payload = event.get('payload') or {}
            kind = payload.get('type')
            if event.get('type') == 'response_item' and kind == 'message':
                if turn and payload.get('role') == 'assistant' and payload.get('channel') in (None, 'final'):
                    for content in payload.get('content') or []:
                        if content.get('type') == 'output_text' and (content.get('text') or '').strip():
                            last_say = content['text'].strip()
                continue
            if event.get('type') != 'event_msg':
                continue
            if kind == 'task_started' and not turn and payload.get('root_turn_id', payload.get('turn_id')) == payload.get('turn_id'):
                turn, last_say = payload.get('turn_id'), ''
            elif turn and payload.get('turn_id') == turn:
                if kind == 'task_complete':
                    answer = (payload.get('last_agent_message') or '').strip() or last_say
                    return (answer or None), _tid_of(path)
                if kind == 'turn_aborted':  # уточнение могло оборвать ход и начать новый: ждём ещё START_WAIT
                    turn, last_say, quiet = None, '', time.time()
        now = time.time()
        if not turn and now > quiet + START_WAIT:
            if not switched and path:  # сообщение могло открыть новый файл сессии
                switched = True
                found = _new_rollout(slot, cwd, sent - 2, exclude=path)
                if found:
                    path, off, quiet = found, 0, now
                    continue
            return None, _tid_of(path) if path else None
        if not _pid():
            raise ConsoleError('Консоль Codex закрылась, не ответив.')
        if deadline is not None and now > deadline:
            raise ConsoleError('Codex не ответил за отведённое время.')
        time.sleep(POLL)


def _paste_text(text):
    """Что реально печатается в консоль: без управляющих символов (ESC закрыл бы вставку), без начала, которое
    консоль примет за команду (`/…` — команда Codex, `!…` — shell, `$…` — навык, `@…` — файл)."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", t).strip()
    if t[:1] in ("/", "!", "$", "@"):
        t = "» " + t
    return t


def _input_ack_key(text):
    """TUI может убрать пустые строки во вставке. Содержимое строк и отступы сохраняем."""
    return '\n'.join(line for line in str(text).replace('\r\n', '\n').replace('\r', '\n').strip().split('\n') if line.strip())


def _paste(text):
    """Вставить текст как вставку из буфера (bracketed paste): так проходят кириллица, переводы строк и длинные тексты,
    а `stuff` пришлось бы чистить от $ \\ ^ кавычек, и длинное он гонит по символу."""
    path = os.path.join(_dir(), "paste.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\x1b[200~" + text + "\x1b[201~")
    cc_codex.own(path)
    try:
        # Screen quiet prefix suppresses its buffer-read status on attached displays.
        for cmd in ("@readbuf", path), ("paste", "."):
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


def verify_ready(wait=True):
    """PID недостаточно: не фиксируем смену аккаунта перед модальным отказом CLI."""
    if wait:_wait_ready()
    if not _pid():
        return False, 'Консоль закрылась при запуске.'
    try:
        with open(_log(), 'rb') as stream:
            raw = stream.read()
        if pyte is not None:
            cols, rows = _dims(_pid())
            frame = pyte.Screen(cols, rows)
            pyte.ByteStream(frame).feed(raw)
            visible = '\n'.join(frame.display).lower()
        else:
            visible = cc_codex._strip(raw.decode('utf-8', 'replace')).lower()
    except OSError:
        return False, 'Нет подтверждения готовности консоли.'
    visible = ' '.join(visible.split())
    if 'this conversation is open in another app' in visible:
        return False, 'Беседа занята другим подключением Codex. Повторное подключение требует освобождения беседы.'
    blockers = ('failed to load',
                'error loading', 'sign in to', 'log in to', 'conversation not found',
                'failed to resume', 'refresh token has already been used')
    if any(text in visible for text in blockers):
        return False, 'Консоль запросила вход или не смогла открыть выбранную беседу.'
    if not any(marker in visible for marker in ('›', '❯', '? for shortcuts', 'context left')):
        return False, 'Поле ввода Codex не подтвердило готовность.'
    return True, ''


def _remember(slot_cwd, tid):
    meta = _meta()
    tids = dict(meta.get("tids") or {})
    if tids.get(slot_cwd) != tid:
        tids[slot_cwd] = tid
        meta["tids"] = tids
        if meta.get('settings'):
            meta['settings']['thread_id'] = tid
            meta['settings'].pop('new_session', None)
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
        same = (not meta.get("pending_settings") and (not st.get("plan_slot") or meta.get("slot") == st.get("plan_slot"))
                and st.get("sandbox") == st.get("plan_sandbox") and meta.get("approval") == APPROVAL
                and list(meta.get("mcp") or []) == list(MCP())
                and os.path.realpath(str(st.get("cwd") or "")) == os.path.realpath(str(st.get("plan_cwd") or "")))
        if same:
            return True, ""
        tid = (meta.get("tids") or {}).get(os.path.realpath(str(st.get("cwd") or "")))
        path = active_settings().get("rollout_path") or (find_rollout(meta.get("slot") or "", tid) if tid else None)
        if path and _turn_open(path, meta.get("started") or 0):
            return False, t("Права или папка Codex сменились, но в консоли идёт запрос: дождись ответа или /stop.",
                            "Codex access or folder changed, but a request is running in the console: wait for the reply or /stop.")
        saved = active_settings()
        saved.update(meta.get("pending_settings") or {})
        new_cwd = os.path.realpath(str(st.get("plan_cwd") or ""))
        if new_cwd != os.path.realpath(str(st.get("cwd") or "")):
            saved["cwd"] = new_cwd
            if not PRESERVE_THREAD():
                saved["thread_id"] = (meta.get("tids") or {}).get(new_cwd)
                saved.pop("rollout_path", None)
                saved["new_session"] = not bool(saved["thread_id"])
        meta["pending_settings"] = saved
        cc_codex._jsave(_meta_path(), meta)
        cc_codex.own(_meta_path())
        ok, msg = stop(lang)
        if not ok:
            return ok, msg
    return start(lang)


def forget(lang="ru"):
    """Начать разговор заново (/new): консоль останавливается, забыв прошлые разговоры; следующий запуск — чистый."""
    with _lock:
        meta = _meta()
        saved = active_settings()
        saved.update(meta.get('pending_settings') or {})
        saved.update(new_session=True, thread_id=None)
        if meta.get('slot'):
            saved['history_home'] = cc_codex.profile_dir(meta['slot'])
        saved.pop('rollout_path', None)
        meta['pending_settings'] = saved
        meta["tids"] = {}
        cc_codex._jsave(_meta_path(), meta)
        cc_codex.own(_meta_path())
    if _pid():
        stop(lang)


def compact(lang="ru"):
    """Кнопка «Сжать контекст»: /compact вводится в консоль, как это сделал бы человек (команда, затем Enter —
    вставкой она не сработала бы, см. _paste_text). Посреди хода или без консоли не вводим. → (ok, сообщение)."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    if not _pid():
        return False, t("Консоль Codex не запущена.", "The Codex console is not running.")
    busy = (False, t("Codex сейчас отвечает: дождись ответа или останови его.", "Codex is replying right now: wait for the reply or stop it."))
    if not _ask_lock.acquire(blocking=False):
        return busy
    try:
        meta = _meta()
        tid = (meta.get("tids") or {}).get(os.path.realpath(str(meta.get("cwd") or "")))
        path = find_rollout(meta.get("slot") or "", tid) if tid else None
        if path and _turn_open(path, meta.get("started") or 0):
            return busy
        off = os.path.getsize(path) if path else 0
        if _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "/compact"]).returncode != 0:
            return False, t("Не удалось напечатать в консоль Codex.", "Could not type into the Codex console.")
        time.sleep(CMD_DELAY)  # пока набрана не вся команда, Enter выбрал бы подсказку списка
        if _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"]).returncode != 0:
            return False, t("Не удалось напечатать в консоль Codex.", "Could not type into the Codex console.")
        if not path:
            return True, t("Команда /compact отправлена в консоль Codex.", "The /compact command was sent to the Codex console.")
        end = time.time() + CMD_WAIT
        while time.time() < end:  # сжатие — обычный ход с событием compacted: убеждаемся, что Codex его начал
            evs, off = _events(path, off)
            if any((e.get("payload") or {}).get("type") == "task_started" for e in evs):
                return True, t("Сжатие запущено: Codex заменяет разговор краткой выжимкой.",
                               "Compaction started: Codex is replacing the conversation with a short summary.")
            time.sleep(POLL)
        return False, t("Команда отправлена, но Codex не начал сжатие — повтори.", "The command was sent but Codex did not start compacting — try again.")
    finally:
        _ask_lock.release()


def clear_live():
    with _live_lock:
        if not _live_request:
            return 0
        count = len(_live_request['queue'])
        _live_request['queue'].clear()
        return count


def _ask_live(prompt, abort=None, timeout=None, lang='ru', pull=None):
    """Один читатель результата; новые сообщения вводит между чтениями, а не после ответа."""
    global _live_request
    text = _paste_text(prompt)
    if not text:
        raise ConsoleError('Пустое сообщение.')
    aborted = lambda: bool(abort and abort.is_set())
    request = dict(queue=[text], awaiting=[], aborted=aborted)
    with _ask_lock:
        if aborted():
            raise Aborted()
        if not INPUT_ALLOWED():
            raise ConsoleError('Codex на паузе: активен служебный режим другой стороны.')
        meta = _meta()
        saved = active_settings() if _pid() else {}
        path = saved.get('rollout_path')
        turn = _open_turn_id(path, meta.get('started') or 0) if path else None
        # У уже работающей консоли сохраняем модель, права и текущий ход.
        if not turn:
            ok, message = ensure(lang)
            if not ok:
                raise ConsoleError(message)
            meta = _meta()
            if time.time()-(meta.get('started') or 0) < PROMPT_WAIT+10:
                _wait_ready()
            saved = active_settings()
            path = saved.get('rollout_path')
        slot, key = meta.get('slot') or '', os.path.realpath(meta.get('cwd') or '')
        tid = saved.get('thread_id') or (meta.get('tids') or {}).get(key)
        if not path and tid:
            path = find_rollout(slot, tid)
        off = os.path.getsize(path) if path else 0
        if path:
            turn = _open_turn_id(path, meta.get('started') or 0)
        attached_running = bool(turn)
        started = time.time()
        deadline = None if timeout is None else started+timeout
        last_say, finished, last_input, sent_count = '', False, started, 0
        with _live_lock:
            _live_request = request
        try:
            while True:
                if aborted():
                    raise Aborted()
                if pull:
                    with _live_lock:
                        # Забираем по одному: ещё не отправленные сообщения остаются у моста.
                        capacity = 1 if not request['queue'] and len(request['awaiting']) < 20 else 0
                    incoming = pull(capacity) if capacity else []
                    with _live_lock:
                        request['queue'].extend(_paste_text(value) for value in incoming)
                with _live_lock:
                    queued = request['queue'].pop(0) if request['queue'] else None
                    if queued is not None:
                        last_input = time.time()
                        request['awaiting'].append((queued, last_input))
                if queued is not None:
                    sent_count += 1
                    if aborted():
                        raise Aborted()
                    if not INPUT_ALLOWED():
                        raise ConsoleError('Codex на паузе: ввод не передан.')
                    if not _paste(queued):
                        raise ConsoleError('Не удалось подтвердить ввод в консоль. Проверь вкладку Codex перед повтором.')
                if path is None:
                    path = _new_rollout(slot, key, started-2)
                    off = 0
                events, off = _events(path, off) if path else ([], off)
                for event in events:
                    payload = event.get('payload') or {}
                    kind = payload.get('type')
                    if event.get('type') == 'response_item' and kind == 'message':
                        if payload.get('role') == 'user':
                            incoming = ''.join(c.get('text','') for c in payload.get('content') or []
                                               if c.get('type') in ('input_text','text'))
                            with _live_lock:
                                if request['awaiting'] and _input_ack_key(incoming) == _input_ack_key(request['awaiting'][0][0]):
                                    request['awaiting'].pop(0)
                                    # Ответ, записанный до принятия уточнения, ему не соответствует.
                                    last_say = ''
                                    if finished:
                                        turn, finished = None, False
                        elif payload.get('role') == 'assistant' and payload.get('channel') in (None,'final'):
                            for content in payload.get('content') or []:
                                if content.get('type') == 'output_text' and (content.get('text') or '').strip():
                                    last_say = content['text'].strip()
                    if event.get('type') != 'event_msg':
                        continue
                    if kind == 'task_started' and payload.get('root_turn_id',payload.get('turn_id')) == payload.get('turn_id'):
                        if payload.get('turn_id') != turn:
                            turn, finished, last_say = payload.get('turn_id'), False, ''
                        tid = _tid_of(path) or tid
                        if tid:
                            _remember(key,tid)
                    if payload.get('turn_id') == turn:
                        if kind == 'task_complete':
                            finished = True
                        elif kind == 'turn_aborted':
                            if aborted():
                                raise Aborted()
                            with _live_lock:
                                pending = request['queue'] or request['awaiting']
                            if not pending and sent_count == 1 and not attached_running:
                                raise ConsoleError('Запрос в консоли Codex прерван.')
                            turn, finished, last_say = None, False, ''
                with _live_lock:
                    if finished and last_say and not request['queue'] and not request['awaiting']:
                        _live_request = None
                        return last_say, _tid_of(path) or tid
                    oldest = request['awaiting'][0][1] if request['awaiting'] else None
                if not _pid():
                    raise ConsoleError('Консоль Codex закрылась, не ответив.')
                now = time.time()
                if oldest and now-oldest > START_WAIT:
                    raise ConsoleError('Не получил подтверждение приёма сообщения. Оно могло попасть в консоль; проверь вкладку Codex перед повтором.')
                if (not turn or finished and not last_say) and now-last_input > START_WAIT and not oldest:
                    raise ConsoleError('Консоль приняла сообщение, но новый ответ не подтверждён. Проверь вкладку Codex.')
                if deadline is not None and now > deadline:
                    interrupt()
                    raise ConsoleError('Codex не ответил за отведённое время, запрос прерван.')
                time.sleep(POLL)
        finally:
            with _live_lock:
                if _live_request is request:
                    _live_request = None


def ask(prompt, abort=None, timeout=None, lang="ru", live=False, pull=None):  # timeout: None — ход без ограничения
    """Напечатать prompt в консоль и дождаться ответа Codex из файла сессии. → (ответ, id разговора).
    ConsoleError — консоль не приняла запрос / закрылась / не ответила; Aborted — abort (Event) взведён."""
    if live:
        return _ask_live(prompt, abort, timeout, lang, pull)
    if not INPUT_ALLOWED():
        raise ConsoleError('Codex на паузе: активен служебный режим другой стороны.')
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
        enter_again = sent + ENTER_RETRY
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
                        tid = _tid_of(path) or tid
                        if tid:
                            _remember(key, tid)
                        deadline = None if timeout is None else time.time() + timeout
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
            if deadline is not None and now > deadline:
                if turn:
                    interrupt()
                    raise ConsoleError("Codex не ответил за отведённое время, запрос прерван.")
                raise ConsoleError("Не получил подтверждение, что Codex начал обработку за 40 секунд. Сообщение могло попасть в консоль; проверь вкладку Codex, прежде чем повторять.")
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


FROZEN_MAX = 1536 * 1024  # хвост лога остановленной консоли, который разбираем (как у консоли Claude)
_fz_lock = threading.Lock()
_fz = {"key": None, "current": "", "history": ""}


def frozen_snapshot(want_history=False):
    """→ (экран HTML, скроллбэк HTML | None, время последнего вывода): последний экран остановленной консоли.
    Берётся из лога screen (после остановки он остаётся; при новом запуске уходит в .prev). Лога нет → ("", ""/None, 0).
    Разбор кэшируется по (файл, mtime, размер): страница опрашивает раз в 2 с."""
    log = _log()
    path = None
    for p in (log, log + ".prev"):
        try:
            if os.path.getsize(p) > 0:
                path = p
                break
        except OSError:
            pass
    if not path:
        return "", ("" if want_history else None), 0
    try:
        st = os.stat(path)
    except OSError:
        return "", ("" if want_history else None), 0
    key = (path, st.st_mtime_ns, st.st_size)
    with _fz_lock:
        if _fz["key"] != key:
            try:
                with open(path, "rb") as f:
                    if st.st_size > FROZEN_MAX:
                        f.seek(st.st_size - FROZEN_MAX)
                    data = f.read()
                scr = pyte.HistoryScreen(COLS, ROWS, history=HISTORY_LINES)
                pyte.ByteStream(scr).feed(data)
                cur = list(zip(scr.display, (ROW_HTML(scr.buffer[y], COLS) for y in range(ROWS))))
                while cur and not cur[-1][0].strip():
                    cur.pop()
                _fz.update(key=key, current="\n".join(h for _, h in cur),
                           history="\n".join(ROW_HTML(line, COLS) for line in scr.history.top))
            except Exception as e:
                print("codex-console: последний экран не разобран:", type(e).__name__, flush=True)
                _fz.update(key=key, current="", history="")
        return _fz["current"], (_fz["history"] if want_history else None), int(st.st_mtime)


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
