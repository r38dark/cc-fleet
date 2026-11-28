"""Interactive screen-backed Antigravity CLI (agy) console and live pyte HTML mirror."""
import fcntl
import glob
import json
import os
import re
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

import cc_agy

try:
    import pyte
except ImportError:
    pyte = None

BASE = "/opt/cc-limits"
BIN = lambda: cc_agy.find_bin()
ROW_HTML = None
QUOTA_PAUSE = lambda: {}
QUOTA_ENQUEUE = None
WORKDIR = lambda: "/root"

NAME = "cc-agy"
UNIT = "cc-agy-console.service"
SCREEN_BIN = "/usr/bin/screen"
COLS, ROWS = 110, 34
HISTORY_LINES = 2000
LOG_MAX = 16 * 1024 * 1024
FROZEN_MAX = 1_500_000

PROMPT_WAIT = 20.0
START_WAIT = 35.0
ENTER_RETRY = 2.5
PASTE_DELAY = 0.14
POLL = 0.10

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_SLASH_RE = re.compile(r"(/[A-Za-z][A-Za-z0-9_-]{0,79})(?:[ \t]+(.*))?", re.S)

_lock = threading.Lock()
_ask_lock = threading.Lock()
_paste_lock = threading.Lock()
_mlock = threading.Lock()
_m = {"pid": None, "screen": None, "stream": None, "offset": 0, "geom": (0, 0)}
_frozen_cache = {"key": None, "data": None}
_watcher = {"conv_id": None, "offset": 0, "last_step": -1}


class ConsoleError(Exception):
    pass


class Aborted(ConsoleError):
    pass


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)


def _dir():
    return os.path.join(BASE, "agy_console")


def _log():
    return os.path.join(_dir(), "console.log")


def _meta_path():
    return os.path.join(_dir(), "console.json")


def _rc_path():
    return os.path.join(_dir(), "console.rc")


def _meta():
    return cc_agy.jload(_meta_path(), {}) or {}


def _save_meta(data):
    os.makedirs(_dir(), exist_ok=True)
    cc_agy.jsave(_meta_path(), data, mode=0o600)


def _ctl(args, timeout=10.0):
    return subprocess.run(
        [SCREEN_BIN] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _pid():
    meta = _meta()
    known = str(meta.get("pid") or "")
    if known.isdigit():
        proc = Path(f"/proc/{known}")
        try:
            comm = (proc / "comm").read_text(errors="ignore").strip().lower()
            cmdline = (proc / "cmdline").read_bytes().split(b"\0")
            if comm == "screen" and NAME.encode() in cmdline:
                return known
        except OSError:
            pass
    try:
        out = _ctl(["-ls"]).stdout
    except Exception:
        return None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\." + re.escape(NAME) + r"\s", line)
        if m and "Dead" not in line:
            return m.group(1)
    return None


def quota_paused():
    try:
        return bool((QUOTA_PAUSE() or {}).get("active"))
    except Exception:
        return False


def busy():
    return _ask_lock.locked()


def active_settings():
    meta = _meta()
    return {
        "model": meta.get("model") or cc_agy.cli_default_model(),
        "effort": meta.get("effort") or "",
        "conv_id": meta.get("conv_id") or "",
        "workdir": meta.get("workdir") or WORKDIR(),
    }


def status():
    pid = _pid()
    meta = _meta()
    b = BIN()
    return {
        "available": bool(b),
        "running": bool(pid),
        "pid": pid or "",
        "busy": busy(),
        "quota_paused": quota_paused(),
        "cwd": meta.get("workdir") or WORKDIR(),
        "conv_id": meta.get("conv_id") or "",
        "model": meta.get("model") or cc_agy.cli_default_model(),
        "effort": meta.get("effort") or "",
        "pending_settings": meta.get("pending_settings") or {},
        "started": meta.get("started") or 0,
        "started_version": meta.get("started_version") or "",
    }


def _retire_unit(timeout=10.0):
    subprocess.run(["systemctl", "stop", UNIT], capture_output=True, timeout=timeout, check=False)
    subprocess.run(["systemctl", "reset-failed", UNIT], capture_output=True, timeout=5, check=False)
    end = time.time() + timeout
    while time.time() < end:
        st = subprocess.run(["systemctl", "is-active", UNIT], capture_output=True, text=True, timeout=5, check=False)
        if st.stdout.strip() in ("inactive", "failed", "unknown", ""):
            return True
        time.sleep(0.2)
    return False


def _write_rc():
    os.makedirs(_dir(), exist_ok=True)
    with open(_rc_path(), "w", encoding="utf-8") as fh:
        fh.write(
            "defutf8 on\n"
            "logfile flush 1\n"
            "term screen-256color\n"
            'termcapinfo * "Km=\\E[M"\n'
        )


def _start_locked(conv_id=None, workdir=None, model=None, effort=None, restarting=False):
    b = BIN()
    if not b:
        return False, "Antigravity CLI (agy) не установлен на сервере."
    if _pid():
        return True, "Консоль Antigravity уже запущена."
    _retire_unit()

    prev = _meta()
    ameta = cc_agy.load_meta()
    cwd = workdir or prev.get("workdir") or WORKDIR()
    if not os.path.isdir(cwd):
        cwd = "/root"
    try:
        cc_agy.ensure_bootstrap_config(workdir=cwd)
    except Exception:
        pass
    cid = prev.get("conv_id") if conv_id is None else conv_id
    mod = ameta.get("model", "") if model is None else model
    eff = ameta.get("effort", "") if effort is None else effort

    os.makedirs(_dir(), exist_ok=True)
    log_path = _log()
    if os.path.exists(log_path):
        try:
            os.replace(log_path, log_path + ".prev")
        except OSError:
            pass
    open(log_path, "w", encoding="utf-8").close()
    _write_rc()

    meta = {
        "pid": "",
        "unit": UNIT,
        "workdir": cwd,
        "conv_id": cid or "",
        "model": mod or "",
        "effort": eff or "",
        "started": time.time(),
        "started_version": cc_agy.cli_version(b),
        "restarting": bool(restarting),
        "pending_settings": {},
    }
    _save_meta(meta)

    agy_args = [b, "--dangerously-skip-permissions"]
    if cid:
        agy_args.extend(["--conversation", str(cid)])
    if mod:
        agy_args.extend(["--model", str(mod)])
    if eff:
        agy_args.extend(["--effort", str(eff)])

    script = 'stty cols "$1" rows "$2"; shift 2; exec "$@"'
    screen_cmd = [
        SCREEN_BIN,
        "-c", _rc_path(),
        "-U", "-D", "-mS", NAME,
        "-L", "-Logfile", log_path,
        "sh", "-c", script, "sh", str(COLS), str(ROWS),
        *agy_args,
    ]
    path_env = "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    unit_cmd = [
        "/usr/bin/systemd-run",
        f"--unit={UNIT}",
        "--collect",
        "--no-block",
        "--property=Type=exec",
        "--property=KillMode=control-group",
        f"--working-directory={cwd}",
        "--setenv=HOME=/root",
        "--setenv=LANG=en_US.UTF-8",
        "--setenv=TERM=xterm-256color",
        f"--setenv=PATH={path_env}",
        "--",
        *screen_cmd,
    ]
    p = subprocess.run(unit_cmd, capture_output=True, text=True, timeout=15, check=False)
    if p.returncode != 0:
        return False, "Не удалось запустить консоль Antigravity: " + ((p.stderr or p.stdout).strip()[-200:] or "?")

    pid = None
    for _ in range(30):
        pid = _pid()
        if pid:
            break
        time.sleep(0.2)
    if not pid:
        return False, "Консоль Antigravity сразу закрылась при запуске."

    meta["pid"] = pid
    meta["restarting"] = False
    _save_meta(meta)
    threading.Thread(target=_auto_pass_onboarding, args=(pid,), daemon=True, name="agy-onboard").start()
    return True, "Консоль Antigravity запущена."


def _auto_pass_onboarding(target_pid):
    """Automatically dismiss any remaining first-run onboarding/trust prompt inside cc-agy."""
    deadline = time.time() + 22.0
    steps_sent = 0
    while time.time() < deadline and steps_sent < 8:
        time.sleep(0.7)
        if _pid() != target_pid:
            return
        try:
            raw = Path(_log()).read_text(encoding="utf-8", errors="replace")[-12000:]
        except OSError:
            continue
        clean = _strip_ansi(raw)
        if "for shortcuts" in clean:
            return
        act = cc_agy._onboarding_action(clean)
        if act:
            with _paste_lock:
                for seq in act:
                    _ctl(["-S", NAME, "-p", "0", "-X", "stuff", seq.decode("latin1")])
                    time.sleep(0.18)
            steps_sent += 1
            time.sleep(0.5)


def start(conv_id=None, workdir=None, model=None, effort=None):
    with _lock:
        return _start_locked(conv_id=conv_id, workdir=workdir, model=model, effort=effort)


def stop():
    with _lock:
        meta = _meta()
        meta["restarting"] = False
        _save_meta(meta)
        if _pid():
            _ctl(["-S", NAME, "-X", "quit"])
            time.sleep(0.35)
        _retire_unit()
        _ctl(["-wipe"])
        return True, "Консоль Antigravity остановлена."


def restart(conv_id=None, workdir=None, model=None, effort=None):
    with _lock:
        meta = _meta()
        meta["restarting"] = True
        _save_meta(meta)
        if _pid():
            _ctl(["-S", NAME, "-X", "quit"])
            time.sleep(0.35)
        _retire_unit()
        _ctl(["-wipe"])
        return _start_locked(
            conv_id=conv_id,
            workdir=workdir,
            model=model,
            effort=effort,
            restarting=True,
        )


def ensure(workdir=None, conv_id=None, model=None, effort=None):
    with _lock:
        pid = _pid()
        meta = _meta()
        ameta = cc_agy.load_meta()
        cwd = workdir or meta.get("workdir") or WORKDIR()
        if not os.path.isdir(cwd):
            cwd = "/root"
        cid = (meta.get("conv_id") or "") if conv_id is None else (conv_id or "")
        mod = (ameta.get("model") or "") if model is None else (model or "")
        eff = (ameta.get("effort") or "") if effort is None else (effort or "")
        same = (
            bool(pid)
            and os.path.realpath(meta.get("workdir") or "") == os.path.realpath(cwd)
            and (meta.get("conv_id") or "") == cid
            and (meta.get("model") or "") == mod
            and (meta.get("effort") or "") == eff
            and not meta.get("pending_settings")
        )
        if same:
            return True, ""
        if pid:
            meta["restarting"] = True
            _save_meta(meta)
            _ctl(["-S", NAME, "-X", "quit"])
            time.sleep(0.35)
            _retire_unit()
            _ctl(["-wipe"])
        return _start_locked(conv_id=cid, workdir=cwd, model=mod, effort=eff, restarting=bool(pid))


def request_settings(values):
    """Save pending model/effort/workdir/new_session settings and apply immediately if idle."""
    with _lock:
        meta = _meta()
        pending = dict(meta.get("pending_settings") or {})
        pending.update(values or {})
        meta["pending_settings"] = pending
        _save_meta(meta)
    if busy() or quota_paused():
        return True, "Настройки сохранены и применятся после завершения текущего ответа.", True
    ok, msg = apply_plan()
    return ok, msg, False


def apply_plan():
    if busy() or quota_paused():
        return False, "Консоль занята или на паузе."
    with _lock:
        meta = _meta()
        pending = meta.get("pending_settings") or {}
        if not pending:
            return True, ""
        cid = "" if pending.get("new_session") else (pending.get("conv_id") if "conv_id" in pending else meta.get("conv_id") or "")
        cwd = pending.get("workdir") or meta.get("workdir") or WORKDIR()
        mod = pending.get("model") if "model" in pending else meta.get("model") or ""
        eff = pending.get("effort") if "effort" in pending else meta.get("effort") or ""
        meta["pending_settings"] = {}
        meta["restarting"] = True
        _save_meta(meta)
        if _pid():
            _ctl(["-S", NAME, "-X", "quit"])
            time.sleep(0.35)
        _retire_unit()
        _ctl(["-wipe"])
        return _start_locked(conv_id=cid, workdir=cwd, model=mod, effort=eff, restarting=True)


def _wait_ready():
    end = time.time() + PROMPT_WAIT
    last_size = -1
    stable = 0
    saw = False
    while time.time() < end:
        if not _pid():
            raise ConsoleError("Консоль Antigravity закрылась при запуске.")
        try:
            raw = Path(_log()).read_text(encoding="utf-8", errors="replace")
            size = len(raw)
            clean = _strip_ansi(raw)
            if "for shortcuts" in clean or "\n>" in clean:
                saw = True
        except OSError:
            size = 0
        if size > 0 and size == last_size and saw:
            stable += 1
            if stable >= 3:
                return
        else:
            stable = 0
        last_size = size
        time.sleep(0.2)


def _paste_text(text):
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", cleaned).strip()
    if cleaned[:1] in ("/", "!", "@"):
        cleaned = "» " + cleaned
    return cleaned


def _paste(text):
    paste_path = os.path.join(_dir(), "paste.txt")
    with _paste_lock:
        os.makedirs(_dir(), exist_ok=True)
        with open(paste_path, "w", encoding="utf-8") as fh:
            fh.write("\x1b[200~" + text + "\x1b[201~")
        try:
            r1 = _ctl(["-S", NAME, "-p", "0", "-X", "@readbuf", paste_path])
            r2 = _ctl(["-S", NAME, "-p", "0", "-X", "paste", "."])
            if r1.returncode != 0 or r2.returncode != 0:
                return False
            time.sleep(PASTE_DELAY if len(text) < 1200 else 0.35)
            return _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"]).returncode == 0
        finally:
            try:
                os.unlink(paste_path)
            except OSError:
                pass


def interrupt():
    with _paste_lock:
        if not _pid():
            return False
        return _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\x1b"]).returncode == 0


def send_key(key):
    keys = {
        "escape": "\x1b",
        "enter": "\r",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
        "tab": "\t",
    }
    if key not in keys:
        return False, "Неизвестная клавиша."
    if key != "escape" and quota_paused():
        return False, "Antigravity на паузе по лимитам. Сообщения отправляйте через поле ввода — они встанут в очередь."
    if not _pid():
        return False, "Консоль Antigravity не запущена."
    with _paste_lock:
        res = _ctl(["-S", NAME, "-p", "0", "-X", "stuff", keys[key]])
    return res.returncode == 0, ("Клавиша передана в консоль Antigravity." if res.returncode == 0 else "Консоль не приняла клавишу.")


def send_input(text, request_id=None):
    """Send text or slash command from the Web Console into agy screen."""
    if quota_paused():
        if QUOTA_ENQUEUE is not None:
            return QUOTA_ENQUEUE(text, request_id or f"web-{int(time.time()*1000)}")
        return False, "Antigravity на паузе по лимитам."
    if not _pid():
        ok, msg = start()
        if not ok:
            return False, msg
        _wait_ready()
    cleaned = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not cleaned:
        return False, "Пустое сообщение."
    cmd_m = _SLASH_RE.fullmatch(cleaned)
    if cmd_m:
        if busy():
            return False, "В консоли Antigravity идёт ответ: команду можно отправить после завершения."
        prefix, args = cmd_m.groups()
        with _paste_lock:
            r1 = _ctl(["-S", NAME, "-p", "0", "-X", "stuff", prefix + (" " if args else "")])
            if r1.returncode != 0:
                return False, "Консоль Antigravity недоступна."
            if args:
                time.sleep(0.25)
                ok = _paste(args)
                return ok, ("Команда передана в консоль Antigravity." if ok else "Не удалось передать аргументы команды.")
            time.sleep(0.25)
            r2 = _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"])
            return r2.returncode == 0, ("Команда передана в консоль Antigravity." if r2.returncode == 0 else "Консоль не приняла Enter.")
    ok = _paste(cleaned)
    return ok, ("Ввод передан в консоль Antigravity." if ok else "Не удалось передать ввод в консоль Antigravity.")


def compact():
    if quota_paused():
        return False, "Antigravity на паузе по лимитам."
    if busy():
        return False, "В консоли Antigravity идёт ответ — сжатие доступно после завершения."
    with _ask_lock:
        if not _pid():
            ok, msg = start()
            if not ok:
                return False, msg
            _wait_ready()
        log_path = Path(_log())
        off0 = log_path.stat().st_size if log_path.is_file() else 0
        with _paste_lock:
            r1 = _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "/compact"])
            time.sleep(0.2)
            r2 = _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"])
            if r1.returncode != 0 or r2.returncode != 0:
                return False, "Не удалось отправить /compact в консоль Antigravity."
        end = time.time() + 45.0
        last_size = off0
        saw = False
        quiet = 0
        while time.time() < end:
            if not _pid():
                return False, "Консоль закрылась во время сжатия."
            cur = log_path.stat().st_size if log_path.is_file() else last_size
            if cur > off0:
                saw = True
                if cur == last_size:
                    quiet += 1
                    if quiet >= 8:
                        return True, "Контекст сжат (/compact выполнен)."
                else:
                    quiet = 0
            last_size = cur
            time.sleep(0.35)
        return True, "Команда /compact отправлена в консоль Antigravity."


def new_session():
    if busy():
        interrupt()
        time.sleep(0.4)
    ok, msg = restart(conv_id="")
    if ok:
        with _lock:
            _watcher["conv_id"] = None
            _watcher["offset"] = 0
            _watcher["last_step"] = -1
    return ok, ("Новая сессия Antigravity запущена." if ok else msg)


def _transcript_for(conv_id):
    if not conv_id:
        return None
    cand = cc_agy.BRAIN_DIR / str(conv_id) / ".system_generated" / "logs" / "transcript.jsonl"
    return cand if cand.is_file() else None


def _find_new_transcript(since, known):
    newest = None
    for raw in glob.glob(str(cc_agy.BRAIN_DIR / "*" / ".system_generated" / "logs" / "transcript.jsonl")):
        p = Path(raw)
        if p in known:
            continue
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt >= since and (newest is None or mt > newest[0]):
            newest = (mt, p)
    return newest[1] if newest else None


def _read_events(path, offset):
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return [], offset
    if not chunk:
        return [], offset
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return [], offset
    complete = chunk[: last_nl + 1]
    events = []
    for line in complete.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
        except ValueError:
            continue
    return events, offset + len(complete)


def _remember_conv(conv_id):
    with _lock:
        meta = _meta()
        if meta.get("conv_id") != conv_id:
            meta["conv_id"] = conv_id
            _save_meta(meta)


def ask(prompt, abort=None, timeout=600, workdir=None, conv_id=None, on_conv_id=None):
    """Send prompt from Telegram into interactive agy screen and return (reply, conv_id)."""
    text = _paste_text(prompt)
    if not text:
        raise ConsoleError("Пустое сообщение.")
    with _ask_lock:
        ok, msg = ensure(workdir=workdir, conv_id=conv_id)
        if not ok:
            raise ConsoleError(msg)
        meta = _meta()
        if time.time() - float(meta.get("started") or 0) < 8.0:
            _wait_ready()

        active_cid = (meta.get("conv_id") or "") if conv_id is None else (conv_id or "")
        tpath = _transcript_for(active_cid)
        offset = tpath.stat().st_size if tpath else 0
        known = {
            Path(p)
            for p in glob.glob(str(cc_agy.BRAIN_DIR / "*" / ".system_generated" / "logs" / "transcript.jsonl"))
        }
        if tpath in known and active_cid:
            known.discard(tpath)

        sent_at = time.time()
        if not _paste(text):
            raise ConsoleError("Не удалось отправить текст в консоль Antigravity.")

        seen_input = False
        retried_enter = False
        start_deadline = sent_at + START_WAIT
        turn_deadline = sent_at + timeout
        last_tick = time.time()

        while True:
            now = time.time()
            dt_step = max(0.0, now - last_tick)
            last_tick = now

            if abort and abort.is_set():
                interrupt()
                raise Aborted("Запрос отменён.")

            if quota_paused():
                # Freeze deadline clocks while SIGSTOPped by quota guard
                start_deadline += dt_step
                turn_deadline += dt_step
                time.sleep(0.4)
                continue

            if not _pid():
                raise ConsoleError("Консоль Antigravity закрылась во время выполнения запроса.")

            if tpath is None:
                found = _find_new_transcript(sent_at - 2.0, known)
                if found is not None:
                    tpath = found
                    offset = 0
                    active_cid = found.parents[2].name
                    _remember_conv(active_cid)
                    if on_conv_id:
                        on_conv_id(active_cid)

            if tpath is not None:
                events, offset = _read_events(tpath, offset)
                for ev in events:
                    ev_type = ev.get("type")
                    if not seen_input:
                        if ev_type == "USER_INPUT":
                            seen_input = True
                        continue
                    if ev_type == "PLANNER_RESPONSE":
                        tcs = ev.get("tool_calls") or []
                        if ev.get("status") == "DONE" and not tcs:
                            step_idx = int(ev.get("step_index") or 0)
                            if _watcher["conv_id"] != active_cid:
                                _watcher["conv_id"] = active_cid
                                _watcher["offset"] = 0
                                _watcher["last_step"] = step_idx
                            else:
                                _watcher["last_step"] = max(_watcher["last_step"], step_idx)
                            content = (ev.get("content") or "").strip()
                            return (content or "(пустой ответ)"), active_cid

            if not seen_input:
                if not retried_enter and now > sent_at + ENTER_RETRY:
                    retried_enter = True
                    _ctl(["-S", NAME, "-p", "0", "-X", "stuff", "\r"])
                if now > start_deadline:
                    raise ConsoleError("Antigravity не начал обработку запроса за 35 сек. Проверьте консоль.")

            if now > turn_deadline:
                interrupt()
                raise ConsoleError(f"Превышен таймаут ({timeout} сек). Запрос прерван.")

            time.sleep(POLL)


def poll_unsolicited(conv_id=None):
    """Forward follow-up PLANNER_RESPONSE replies (subagents, background tasks, web input)."""
    cid = conv_id or (_meta().get("conv_id") or "")
    if not cid:
        return []
    if not _ask_lock.acquire(blocking=False):
        return []
    try:
        tpath = _transcript_for(cid)
        if tpath is None:
            return []
        if _watcher["conv_id"] != cid:
            _watcher["conv_id"] = cid
            try:
                _watcher["offset"] = tpath.stat().st_size
            except OSError:
                _watcher["offset"] = 0
            _watcher["last_step"] = -1
            return []
        events, new_off = _read_events(tpath, _watcher["offset"])
        _watcher["offset"] = new_off
        replies = []
        for ev in events:
            step_idx = int(ev.get("step_index") or 0)
            if step_idx <= _watcher["last_step"]:
                continue
            if ev.get("type") != "PLANNER_RESPONSE":
                continue
            if ev.get("status") == "DONE" and not (ev.get("tool_calls") or []):
                _watcher["last_step"] = step_idx
                content = (ev.get("content") or "").strip()
                if content:
                    replies.append(content)
        return replies
    finally:
        _ask_lock.release()


def _dims(pid):
    try:
        kids = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        for kid in kids:
            try:
                with open(f"/proc/{kid}/fd/0", "rb") as fd:
                    rows, cols = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))[:2]
                if 20 <= cols <= 400 and 10 <= rows <= 200:
                    return cols, rows
            except OSError:
                continue
    except OSError:
        pass
    return COLS, ROWS


def _render_screen(screen, want_history=False):
    cols = screen.columns
    row_fn = ROW_HTML
    if row_fn is None:
        lines = [line.rstrip() for line in screen.display]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines), ("" if not want_history else "")
    cur = [row_fn(screen.buffer[y], cols) for y in range(screen.lines)]
    while cur and not cur[-1]:
        cur.pop()
    hist = ""
    if want_history and hasattr(screen, "history") and screen.history.top:
        hlines = [row_fn(row, cols) for row in screen.history.top]
        while hlines and not hlines[-1]:
            hlines.pop()
        hist = "\n".join(hlines)
    return "\n".join(cur), hist


def frozen_snapshot(want_history=False):
    if pyte is None:
        return {"ok": True, "running": False, "html": "", "history": "", "cols": COLS, "rows": ROWS, "stopped": 0}
    path = _log()
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        prev = path + ".prev"
        if os.path.isfile(prev):
            path = prev
    try:
        st = os.stat(path)
    except OSError:
        return {"ok": True, "running": False, "html": "", "history": "", "cols": COLS, "rows": ROWS, "stopped": 0}
    key = (path, st.st_mtime_ns, st.st_size, bool(want_history))
    if _frozen_cache["key"] == key and _frozen_cache["data"] is not None:
        return dict(_frozen_cache["data"])
    try:
        with open(path, "rb") as fh:
            if st.st_size > FROZEN_MAX:
                fh.seek(st.st_size - FROZEN_MAX)
            raw = fh.read()
    except OSError:
        raw = b""
    scr = pyte.HistoryScreen(COLS, ROWS, history=HISTORY_LINES)
    pyte.ByteStream(scr).feed(raw)
    html_cur, hist = _render_screen(scr, want_history=want_history)
    data = {
        "ok": True,
        "running": False,
        "current": html_cur,
        "html": html_cur,
        "history": hist if want_history else None,
        "cols": COLS,
        "rows": ROWS,
        "stopped": int(st.st_mtime),
    }
    _frozen_cache["key"] = key
    _frozen_cache["data"] = data
    return dict(data)


def snapshot(want_history=False):
    pid = _pid()
    if not pid:
        return frozen_snapshot(want_history=want_history)
    if pyte is None:
        return {"ok": True, "running": True, "html": "(pyte не установлен)", "cols": COLS, "rows": ROWS}
    cols, rows = _dims(pid)
    log_path = _log()
    with _mlock:
        if _m["pid"] != pid or _m["screen"] is None or _m["geom"] != (cols, rows):
            scr = pyte.HistoryScreen(cols, rows, history=HISTORY_LINES)
            stream = pyte.ByteStream(scr)
            _m.update(pid=pid, screen=scr, stream=stream, offset=0, geom=(cols, rows))
        try:
            size = os.path.getsize(log_path)
            if size < _m["offset"]:
                _m["offset"] = 0
            with open(log_path, "rb") as fh:
                fh.seek(_m["offset"])
                chunk = fh.read()
            if chunk:
                _m["stream"].feed(chunk)
                _m["offset"] += len(chunk)
            if _m["offset"] > LOG_MAX:
                try:
                    with open(log_path, "wb"):
                        pass
                    _m["offset"] = 0
                except OSError:
                    pass
        except OSError:
            pass
        html_cur, hist = _render_screen(_m["screen"], want_history=want_history)
        return {
            "ok": True,
            "running": True,
            "current": html_cur,
            "html": html_cur,
            "history": hist if want_history else None,
            "cols": cols,
            "rows": rows,
            "pid": pid,
            "busy": busy(),
            "quota_paused": quota_paused(),
        }
