#!/usr/bin/env python3
# cc_codex_emergency — «аварийный режим» Codex: полный доступ к проекту без ограничения срока, когда Claude недоступен.
#
# Включает человек, только в панели и только вводом слова «аварийный». Что происходит при включении:
#  • проект подключается в домашнюю папку пользователя Codex (bind-mount) и ему выдаётся запись по ACL (setfacl);
#  • узкое правило sudo: только `systemctl restart` для перечисленных юнитов (файл в /etc/sudoers.d, проверяется visudo);
#  • в домашнюю папку Codex копируются перечисленные файлы с доступами и ключ SSH (после выключения затираются);
#  • мост и консоль Codex переключаются на «самостоятельно + полный доступ» в этом проекте, прежние настройки запоминаются.
# Выключается вручную: настройки возвращаются, процессы Codex в проекте останавливаются, sudo, ACL,
# копии и mount снимаются, файлы, созданные Codex в проекте, возвращаются прежнему владельцу. Состояние лежит в файле,
# поэтому перезапуск панели или сервера режим не забывает (reconcile при старте).
# Всё, что Codex читает в этом режиме, уходит на серверы OpenAI — на это человек соглашается, вводя слово.
# Настраивается в config.json (ключ "codex_emergency"): project, services, files, ssh_key, hours. Не задано — режима нет.
import json, os, pwd, re, shutil, signal, subprocess, threading, time

import cc_codex
import cc_codex_bridge

BASE = "/opt/cc-limits"  # cc_limits подставляет свой каталог данных
CONFIG = lambda: {}  # cc_limits: config.json "codex_emergency"
NOTIFY = lambda text: None  # cc_limits: сообщение человеку в телеграм
NOW = time.time  # в тестах подменяется
WORDS = ("аварийный", "emergency")  # слово-подтверждение
HOURS = 0  # профили не ограничены по времени
WARN_LEFT = 3600  # за сколько секунд до конца напомнить (при сроке)
TICK = 20  # как часто сторож сверяет срок, секунд
SUDOERS = "/etc/sudoers.d/cc-codex-emergency"
MOUNTINFO = "/proc/self/mountinfo"
PROC = "/proc"
MARK = "<!-- cc-limits: аварийный режим; файл уберётся при выключении -->"
PREV_KEYS = ("mode", "access", "workdir", "project", "task_rights", "profile")
_UNIT = re.compile(r"^[A-Za-z0-9_.@-]{1,120}$")
_SUFFIX = (".service", ".timer", ".socket", ".target", ".path")
_lock = threading.RLock()  # включение и выключение идут по одному
_watch = {"t": None}


class EmergencyError(Exception):
    pass


def _run(argv, timeout=60):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


RUN = _run  # в тестах подменяется


def _tail(r):
    return cc_codex._strip((r.stderr or r.stdout or "")).strip()[-300:] or f"код {r.returncode}"


# ---------------------------------------------------------------- состояние и журнал
def state_path():
    return os.path.join(BASE, "codex_emergency.json")


def log_path():
    return os.path.join(BASE, "codex_emergency.log")


def _st():
    return cc_codex.jload(state_path(), {}) or {}


def _st_save(st):
    cc_codex._jsave(state_path(), st)


def _without_deadline():
    """Убирает и сохранённый старый срок, сохраняя состояние доступа."""
    with _lock:
        state = _st()
        if state.get('active') and (state.get('until') is not None or (state.get('plan') or {}).get('hours')):
            state['until'], state['warned'] = None, False
            if state.get('plan'):
                state['plan']['hours'] = 0
            _st_save(state)
        return state


def journal(msg):
    """Строка в журнал режима (читается в панели и после перезапуска)."""
    line = time.strftime("%Y-%m-%d %H:%M:%S ", time.localtime(NOW())) + msg
    print(f"codex-emergency: {msg}", flush=True)
    try:
        p = log_path()
        if os.path.exists(p) and os.path.getsize(p) > 512 * 1024:
            os.replace(p, p + ".old")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _journal_tail(n=8):
    try:
        with open(log_path(), encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f.readlines()[-n:]]
    except OSError:
        return []


def _clock(ts):
    return time.strftime("%d.%m %H:%M", time.localtime(ts))


def _until_txt(ts):
    return f"действует до {_clock(ts)}" if ts else "без срока, снимет человек"


def active():
    return bool(_st().get("active"))


def until():
    st = _without_deadline()
    return st.get("until") if st.get("active") else None


def status_line():
    """Строка для /status в телеграме: пусто, если режим не включён."""
    if not active():
        return ""
    u = until()
    return f"🆘 АВАРИЙНЫЙ режим: Codex с полным доступом {('до ' + _clock(u)) if u else 'без срока'} (снять: /emergency_off)"


# ---------------------------------------------------------------- план из настроек
def _units(raw):
    """Имена юнитов из настроек → (список для sudoers, список для показа)."""
    out, show = [], []
    for u in raw or []:
        u = str(u).strip()
        if not _UNIT.match(u):
            raise EmergencyError(f"неверное имя сервиса: {u[:60]}")
        full = u if u.endswith(_SUFFIX) else u + ".service"
        show.append(full)
        out.append(full)
        if full.endswith(".service"):
            out.append(full[:-len(".service")])  # `systemctl restart name` без суффикса — тот же юнит
    return out, show


def _inside(path, parent):
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def _plan(lang="ru"):
    """Настройки → (план, ошибка). Ничего не меняет в системе."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    c = CONFIG() or {}
    u = cc_codex.runas_user()
    if not u:
        return None, t("Нужен отдельный пользователь ОС для Codex (config.json → codex_user) и панель, запущенная от root.",
                       "A separate OS user for Codex (config.json → codex_user) and a panel running as root are required.")
    proj = str(c.get("project") or "").strip()
    if not proj:
        return None, t("Аварийный режим не настроен: нет config.json → codex_emergency.project.",
                       "Emergency mode is not set up: config.json → codex_emergency.project is missing.")
    real, err = cc_codex_bridge.check_workdir(proj)
    if err:
        return None, t("Проект: ", "Project: ") + err
    pw = pwd.getpwnam(u)
    edir = os.path.join(pw.pw_dir, "emergency")
    # в проекте не должно оказаться ни настроек панели, ни профилей входа, ни домашней папки Codex: ACL -R открыл бы их
    for bad in (BASE, cc_codex.PROFILES, pw.pw_dir, "/root/.ssh", "/root/.claude", "/root/.codex-profiles"):
        if _inside(os.path.realpath(bad), real):
            return None, t("В этой папке лежат ключи и настройки — открыть её целиком нельзя.",
                           "This folder holds keys and settings — it cannot be opened as a whole.")
    if _inside(real, edir):
        return None, t("Проект не может лежать в папке режима.", "The project cannot live inside the mode folder.")
    try:
        svc, show = _units(c.get("services"))
    except EmergencyError as e:
        return None, str(e)
    files, seen = [], set()
    for src in c.get("files") or []:
        src = os.path.realpath(str(src))
        if not os.path.isfile(src):
            return None, t("Файл не найден: ", "File not found: ") + src
        name = os.path.basename(src)
        if name in seen:
            return None, t("Два файла с одним именем: ", "Two files share a name: ") + name
        seen.add(name)
        files.append([src, os.path.join(edir, "files", name)])
    key = None
    if c.get("ssh_key"):
        ksrc = os.path.realpath(str(c["ssh_key"]))
        if not os.path.isfile(ksrc):
            return None, t("Ключ SSH не найден: ", "SSH key not found: ") + ksrc
        key = [ksrc, os.path.join(edir, "ssh", os.path.basename(ksrc))]
    hours = 0
    st = os.stat(real)
    return {"user": u, "uid": pw.pw_uid, "gid": pw.pw_gid, "home": pw.pw_dir, "edir": edir,
            "mnt": os.path.join(edir, "project"), "project": real, "owner": [st.st_uid, st.st_gid],
            "svc": svc, "svc_show": show, "files": files, "key": key, "hours": hours,
            "gitconfig": os.path.join(edir, "gitconfig")}, ""


def _slot():
    s = cc_codex_bridge.load()
    slots = cc_codex.profile_slots()
    slot = s.get("slot") or (slots[0] if slots else "")
    return slot if slot in slots else ""


def _agents_path():
    slot = _slot()
    return os.path.join(cc_codex.profile_dir(slot), "AGENTS.md") if slot else ""


# ---------------------------------------------------------------- шаги включения (каждый можно повторять)
def _mounted(path):
    try:
        with open(MOUNTINFO, encoding="utf-8", errors="replace") as f:
            for ln in f:
                parts = ln.split()
                if len(parts) > 4 and parts[4].replace("\\040", " ") == path:
                    return True
    except OSError:
        pass
    return False


def _own(path, p):
    try:
        os.chown(path, p["uid"], p["gid"], follow_symlinks=False)
    except OSError:
        pass


def _step_mount(p):
    os.makedirs(p["mnt"], exist_ok=True)
    _own(p["edir"], p)
    os.chmod(p["edir"], 0o755)
    if _mounted(p["mnt"]):
        return
    r = RUN(["mount", "--bind", p["project"], p["mnt"]])
    if r.returncode:
        raise EmergencyError("mount: " + _tail(r))


def _step_acl(p):
    r = RUN(["setfacl", "-R", "-m", f"u:{p['user']}:rwX", p["project"]], 900)
    if r.returncode:
        raise EmergencyError("setfacl: " + _tail(r))


def _put(src, dst, p, mode=0o600):
    """Копия файла для Codex: владелец — он, права 0600; на месте остаётся только пока режим включён."""
    d = os.path.dirname(dst)
    os.makedirs(d, exist_ok=True)
    _own(d, p)
    os.chmod(d, 0o700)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.chmod(tmp, mode)
    _own(tmp, p)
    os.replace(tmp, dst)


def _step_files(p):
    for src, dst in p["files"]:
        _put(src, dst, p)
    if p["key"]:
        _put(p["key"][0], p["key"][1], p)


def _step_git(p):
    """git считает проект чужим (владелец root) — разрешаем именно эту папку и задаём подпись коммитов."""
    text = f"[safe]\n\tdirectory = {p['mnt']}\n[user]\n\tname = Codex\n\temail = codex@localhost\n"
    with open(p["gitconfig"], "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p["gitconfig"], 0o644)
    _own(p["gitconfig"], p)


def _step_sudo(p, until_ts):
    if not p["svc"]:
        return
    systemctl = os.path.realpath(shutil.which("systemctl") or "/usr/bin/systemctl")
    cmds = ", ".join(f"{systemctl} restart {u}" for u in p["svc"])
    text = (f"# cc-limits: аварийный режим Codex ({_until_txt(until_ts)}); файл удаляется при выключении режима\n"
            f"{p['user']} ALL=(root) NOPASSWD: {cmds}\n")
    tmp = SUDOERS + ".tmp"  # с точкой в имени sudo файл не читает, пока он не проверен
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o440)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    r = RUN(["visudo", "-cf", tmp])
    if r.returncode:
        os.unlink(tmp)
        raise EmergencyError("sudoers: " + _tail(r))
    os.chmod(tmp, 0o440)
    os.replace(tmp, SUDOERS)


AGENTS_TEXT = """{mark}
# Codex — АВАРИЙНЫЙ режим (включил человек, {until})

Claude сейчас недоступен, работаешь ты. У тебя полный доступ к проекту — на ответственности человека.
Проект: {mnt} — это тот же проект, что на сервере, писать в него можно. Путь у тебя другой, чем в самом проекте
и сервисах: в настройках и скриптах абсолютные пути сервера вне этой папки тебе недоступны, это не ошибка.

Что можно: читать и править проект, запускать скрипты и тесты, коммитить (git уже настроен), перезапускать сервисы:
`sudo -n systemctl restart <юнит>`, разрешены только: {services}.
Файлы с доступами для работы: {files_dir}. Ключ для другого сервера: {key} (`ssh -i <ключ> …`).

Правила:
1. Перед правкой файла сделай копию `имя.bak_<дата>`. Перед любым действием на другом сервере — бэкап.
   На другом сервере правь точечно — не заменяй файл целиком.
   Вход туда может быть под root, а приложение там работает под другим пользователем (узнай по владельцу папки
   кода: `ls -ld <папка>`). Правь и запускай от его имени (`sudo -u <пользователь> …`), а если правил от root —
   верни владельца (`chown <пользователь>: <файл>`). Файлов под root в папке приложения оставлять нельзя: сервис не
   сможет их писать.
2. О разрушительном (удаление данных, смена схемы, перезапуск того, что держит чужие задания) сначала напиши
   человеку и дождись «да».
3. Прочитай AGENTS.md и docs/HANDOFF.md проекта, если они есть, — там правила проекта.
4. {ending}: всё незаконченное опиши человеку.
5. Отвечай коротко и по делу; сделал — одной-двумя строками что и где.
"""


def _step_agents(p, until_ts):
    path = _agents_path()
    if not path or not os.path.isdir(os.path.dirname(path)):
        return
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            if not f.read(200).startswith(MARK):
                journal("в папке входа Codex уже есть свой AGENTS.md — режим его не трогает")
                return
    text = AGENTS_TEXT.format(mark=MARK, until=_until_txt(until_ts), mnt=p["mnt"],
                              ending="Режим выключится сам, человек может выключить и раньше" if until_ts
                              else "Режим выключит человек, когда решит",
                              services=", ".join(p["svc_show"]) or "(список пуст)",
                              files_dir=os.path.join(p["edir"], "files") if p["files"] else "(нет)",
                              key=p["key"][1] if p["key"] else "(нет)")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o644)
    cc_codex.own(path)


def _apply(p, until_ts):
    _step_mount(p)
    _step_acl(p)
    _step_files(p)
    _step_git(p)
    _step_sudo(p, until_ts)
    _step_agents(p, until_ts)


# ---------------------------------------------------------------- шаги выключения (терпят отсутствие любого куска)
def _wipe(path):
    """Файл с доступами затирается нулями и удаляется."""
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _kill_codex(p):
    """Остановить процессы пользователя Codex, чья текущая папка — проект или папка режима."""
    base = (p["mnt"], p["edir"])
    for sig in (signal.SIGTERM, signal.SIGKILL):
        hit = []
        try:
            pids = [x for x in os.listdir(PROC) if x.isdigit()]
        except OSError:
            return
        for pid in pids:
            try:
                if os.stat(os.path.join(PROC, pid)).st_uid != p["uid"]:
                    continue
                cwd = os.readlink(os.path.join(PROC, pid, "cwd"))
            except OSError:
                continue
            if any(_inside(cwd, b) for b in base):
                hit.append(int(pid))
        for pid in hit:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        if not hit:
            return
        time.sleep(1.0 if sig == signal.SIGTERM else 0.3)


def _teardown(p, prev, why):
    """Снять всё, что включил режим. → список того, что снять не удалось."""
    bad = []

    def step(name, fn):
        try:
            fn()
        except Exception as e:
            bad.append(f"{name}: {str(e)[:160]}")

    def settings():
        with cc_codex_bridge._lock:
            s = cc_codex_bridge.load()
            if prev:
                s.update({k: prev.get(k, s.get(k)) for k in PREV_KEYS})
            elif s.get("workdir") == p["mnt"]:
                s.update(mode="mediator", access="read", workdir="", project="", profile="")  # прежнее забылось — самый тихий режим
            cc_codex_bridge._save(s)
        cc_codex_bridge.BRIDGE.sync()

    def stop_codex():
        cc_codex_bridge.BRIDGE.cancel.set()
        proc = cc_codex_bridge.BRIDGE.proc
        if proc:
            cc_codex._kill(proc)
        con = cc_codex_bridge.CONSOLE
        if con is not None:
            con.stop()
        _kill_codex(p)

    def sudo():
        try:
            os.unlink(SUDOERS)
        except FileNotFoundError:
            pass
        try:
            os.unlink(SUDOERS + ".tmp")
        except FileNotFoundError:
            pass

    def files():
        for _, dst in p.get("files") or []:
            _wipe(dst)
        if p.get("key"):
            _wipe(p["key"][1])
        _wipe(p["gitconfig"])
        for d in ("files", "ssh"):
            try:
                os.rmdir(os.path.join(p["edir"], d))
            except OSError:
                pass

    def agents():
        path = _agents_path()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                ours = f.read(200).startswith(MARK)
            if ours:
                os.unlink(path)

    def umount():
        if _mounted(p["mnt"]):
            r = RUN(["umount", p["mnt"]])
            if r.returncode:
                r = RUN(["umount", "-l", p["mnt"]])  # занят — отцепляем сразу, закроется когда отпустят
            if r.returncode:
                raise EmergencyError(_tail(r))
        try:
            os.rmdir(p["mnt"])
        except OSError:
            pass
        try:
            os.rmdir(p["edir"])
        except OSError:
            pass

    def chown_back():
        r = RUN(["find", p["project"], "-xdev", "-user", p["user"], "-exec", "chown", "-h",
                 f"{p['owner'][0]}:{p['owner'][1]}", "{}", "+"], 900)
        if r.returncode:
            raise EmergencyError("chown: " + _tail(r))

    def acl():
        # -x оставляет на каждом файле пустую запись mask — следующее включение приняло бы её за «свои ACL» проекта;
        # до включения ACL в проекте не было вовсе (on() это проверяет), поэтому снимаем все целиком
        RUN(["setfacl", "-R", "-b", p["project"]], 900)
        r = RUN(["getfacl", "-R", "-s", "-p", p["project"]], 900)  # проверка: расширенных ACL не осталось
        if "# file:" in (r.stdout or ""):
            raise EmergencyError("ACL для Codex остались")

    # сначала то, что опаснее всего оставить (sudo), и останов Codex; потом уборка в проекте
    step("sudo", sudo)
    step("настройки", settings)
    step("остановка Codex", stop_codex)
    step("копии доступов", files)
    step("AGENTS", agents)
    step("mount", umount)
    step("владельцы", chown_back)
    step("ACL", acl)
    journal(f"выключен ({why})" + (": остались хвосты — " + "; ".join(bad) if bad else ": всё снято"))
    return bad


def _forget_conv(cwd):
    """Разговоры папки режима не продолжаются: у каждого включения чистый разговор (чужие разговоры не трогаем)."""
    with cc_codex_bridge._lock:
        st = cc_codex_bridge._state()
        for k in [k for k in st["threads"] if k.endswith("|" + cwd)]:
            del st["threads"][k]
        cc_codex_bridge._state_save(st)
    con = cc_codex_bridge.CONSOLE
    if con is not None:
        meta = con._meta()
        tids = dict(meta.get("tids") or {})
        if tids.pop(os.path.realpath(cwd), None) is not None:
            meta["tids"] = tids
            cc_codex._jsave(con._meta_path(), meta)
            cc_codex.own(con._meta_path())


# ---------------------------------------------------------------- включение и выключение
def on(word, lang="ru", auto=None):
    """Включить режим. → (ok, сообщение). Слово «аварийный» — и есть подтверждение.
    auto — причина автовключения (резерв, когда лимиты Claude кончились): слово не нужно, человек
    заранее разрешил это галочкой, а единственное сообщение о включении шлёт тот, кто включил."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    if not auto and str(word or "").strip().lower() not in WORDS:
        return False, t("Введи слово «аварийный».", "Type the word «emergency».")
    with _lock:
        if _st().get("active"):
            return False, t("Аварийный режим уже включён.", "Emergency mode is already on.")
        p, err = _plan(lang)
        if err:
            return False, err
        chk = RUN(["getfacl", "-R", "-s", "-p", p["project"]], 300)
        if "# file:" in (chk.stdout or ""):
            return False, t("В проекте уже есть свои права ACL — режим их не смешивает. Сними их или обратись к админу.",
                            "The project already has its own ACLs — the mode will not mix with them.")
        s = cc_codex_bridge.load()
        now = NOW()
        st = {"active": True, "since": now, "until": None, "warned": False,
              "prev": {k: s.get(k) for k in PREV_KEYS}, "plan": p}
        if auto:
            st["auto"] = str(auto)[:80]
        _st_save(st)  # сначала запись, потом действия: оборвалось на середине — при старте панели доубирается
        journal(f"включение{(' (само: ' + st['auto'] + ')') if auto else ''}: {('до ' + _clock(st['until'])) if st['until'] else 'без срока'}, сервисов {len(p['svc_show'])}, файлов {len(p['files'])}"
                + (", ключ SSH" if p["key"] else ""))
        try:
            _apply(p, st["until"])
            with cc_codex_bridge._lock:
                s = cc_codex_bridge.load()
                s.update(mode="self", access="full", workdir=p["mnt"], project="", profile="")
                cc_codex_bridge._save(s)
            _forget_conv(p["mnt"])  # у режима каждый раз чистый разговор
            cc_codex_bridge.BRIDGE.sync()
        except Exception as e:
            journal(f"ошибка включения: {str(e)[:200]} — откат")
            _teardown(p, st["prev"], "откат")
            _st_save({"active": False, "last": {"ended": NOW(), "why": "ошибка включения", "error": str(e)[:300]}})
            return False, t("Не удалось включить, всё отменено: ", "Could not turn on, everything was undone: ") + str(e)[:300]
    if not auto:
        NOTIFY(f"🆘 Аварийный режим Codex ВКЛЮЧЁН {('до ' + _clock(st['until'])) if st['until'] else 'без срока'}.\n"
               f"Codex получил полный доступ к проекту" + (f" и перезапуск сервисов ({len(p['svc_show'])})" if p["svc"] else "") +
               ". Выключить — в меню профилей панели или /emergency_off." + ("" if st["until"] else " Срока нет: само не выключится."))
    threading.Thread(target=_restart_console, daemon=True, name="codex-emg-console").start()
    return True, t("Аварийный режим включён.", "Emergency mode is on.")


def off(why="кнопка", lang="ru", quiet=False):
    """Выключить режим и снять всё. → (ok, сообщение). quiet — без своего сообщения в телеграм:
    выключает резерв и пишет человеку одно общее сообщение сам."""
    t = lambda ru, en: cc_codex._t(lang, ru, en)
    with _lock:
        st = _st()
        if not st.get("active"):
            return True, t("Аварийный режим не включён.", "Emergency mode is not on.")
        bad = _teardown(st["plan"], st.get("prev"), why)
        _st_save({"active": False, "last": {"ended": NOW(), "why": why, "problems": bad}})
    if not quiet or bad:  # тихо — только если всё снято; проблему человек должен увидеть всегда
        NOTIFY(("✅ Аварийный режим Codex выключен (" + why + "). Доступы сняты.") if not bad else
               ("⚠️ Аварийный режим Codex выключен (" + why + "), но не всё снято: " + "; ".join(bad)[:600] +
                "\nПроверь вручную."))
    threading.Thread(target=_restart_console, daemon=True, name="codex-emg-console").start()
    return (not bad), (t("Аварийный режим выключен.", "Emergency mode is off.") if not bad else
                       t("Выключен, но не всё снято: ", "Turned off, but not everything was undone: ") + "; ".join(bad)[:300])


def _restart_console():
    """Консоль Codex подхватывает новые права и папку сразу (не посреди запроса — тогда при следующем сообщении)."""
    con = cc_codex_bridge.CONSOLE
    try:
        if con is not None and con._pid():
            con.ensure()
    except Exception as e:
        journal(f"консоль: {type(e).__name__} {e}")


# ---------------------------------------------------------------- сторож срока
def tick():
    """Совместимость со старым вызовом: снимаем старый срок, не выключаем доступ."""
    _without_deadline()


def reconcile():
    """При старте панели: режим включён и срок не вышел — довести до рабочего состояния (после ребута mount пропал);
    срок вышел — выключить; режим не включён, а следы остались — убрать."""
    with _lock:
        st = _without_deadline()
        if st.get("active"):
            try:
                _apply(st["plan"], st["until"])
                journal("после перезапуска панели доступы восстановлены")
            except Exception as e:
                journal(f"после перезапуска восстановить не удалось: {str(e)[:200]} — выключаю")
                return off("сбой после перезапуска")
            return
        stray = os.path.exists(SUDOERS)
        p, _ = _plan()
        if p and _mounted(p["mnt"]):
            stray = True
        if stray:
            try:
                os.unlink(SUDOERS)
            except FileNotFoundError:
                pass
            if p:
                _teardown(p, None, "уборка следов")
                _st_save({"active": False, "last": {"ended": NOW(), "why": "уборка следов"}})


def _loop():
    while True:
        try:
            tick()
        except Exception as e:
            journal(f"сторож: {type(e).__name__} {e}")
        time.sleep(TICK)


def start():
    """Из cc_limits при старте: привести в порядок и запустить сторож."""
    try:
        reconcile()
    except Exception as e:
        journal(f"reconcile: {type(e).__name__} {e}")


# ---------------------------------------------------------------- для панели и для запуска Codex
def env_extra():
    """Переменные окружения Codex: пока режим включён — git-настройки (чужой владелец проекта, подпись коммитов)."""
    st = _st()
    if not st.get("active"):
        return {}
    return {"GIT_CONFIG_GLOBAL": st["plan"]["gitconfig"]}


def public():
    """Состояние для панели. Пути и содержимое доступов наружу не отдаются, только имена сервисов и счётчики."""
    st = _without_deadline()
    p, err = _plan()
    jr = _journal_tail(40)
    if st.get("active"):  # в карточке включённого режима — только строки текущего включения, не прошлых
        jr = jr[max((i for i, ln in enumerate(jr) if " включение:" in ln), default=0):]
    out = {"configured": bool(p), "problem": err, "word": WORDS[0], "active": bool(st.get("active")), "now": NOW(),
           "journal": jr[-8:]}
    if p:
        out.update(services=p["svc_show"], files=len(p["files"]), ssh=bool(p["key"]), hours=p["hours"])
    if st.get("active"):
        out.update(since=st["since"], until=st["until"], auto=bool(st.get("auto")))
    elif st.get("last"):
        out["last"] = st["last"]
    return out
