#!/usr/bin/env python3
"""Управление Claude на этом сервере (в tmux) по командам панели cc-fleet. Печатает одну строку JSON.
Команды: status | screen [строк] | ansi КОЛОНОК ИСТОРИЯ | setmodel МОДЕЛЬ ЭФФОРТ | start SID|- TG(0/1) | stop | tg 0/1 | send ФАЙЛ | sendin (stdin) | key КЛАВИША | hist | histtail ПУТЬ СМЕЩЕНИЕ"""
import json
import os
import re
import subprocess
import sys
import shlex
from pathlib import Path
import time

HOME = os.environ.get("HOME") or "/root"
TMUX = os.environ.get("CC_REMOTE_TMUX") or "ccfleet"
SETTINGS = HOME + "/.claude/settings.json"
CLAUDE = "/usr/bin/claude"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROJ = HOME + "/.claude/projects/-root"  # беседы Claude, запущенного из /root


def out(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def sh(args, inp=None, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, input=inp, timeout=timeout)
        return r.returncode, r.stdout
    except Exception as e:
        return 255, str(e)


def alive():
    return sh(["tmux", "has-session", "-t", TMUX])[0] == 0


def screen(n=60):
    code, text = sh(["tmux", "capture-pane", "-t", TMUX, "-p", "-J", "-S", "-%d" % n])
    return ANSI.sub("", text) if code == 0 else ""


# Claude Code 2.1.x пишет «✢ Determining… (18s)» без «esc to interrupt»; законченный ответ — «✻ Baked for 1s» (без «…»)
SPIN = re.compile(r"^\s*[✢✻✶✳✽✺·*]\s+[A-Z][a-z]+…", re.M)  # счётчик «(18s)» появляется не сразу, поэтому по нему не ловим


# «esc to interrupt» как признак работы: в начале строки, после «(» или «·»; фраза из текста задания («…по «esc to interrupt»…») не считается
ESC_LIVE = re.compile(r"(?:^|[(·])\s*esc to interrupt", re.I | re.M)
TAIL = 14  # строк живой области снизу (спиннер, поле ввода, статус); выше — история: эхо задания и ответы


# пункт меню «No, exit» отдельной строкой (окна доверия и обхода разрешений); в тексте беседы фраза стоит внутри предложения
MENU_NO = re.compile(r"^\s*(?:❯\s*)?(?:\d\.\s*)?no, exit\s*$", re.M)
MENU_YES = re.compile(r"^\s*(?:❯\s*)?(?:\d\.\s*)?yes, (?:i accept|continue)\b", re.M)
MENU_TRUST = re.compile(r"^\s*(?:❯\s*)?(?:\d\.\s*)?yes, i trust\b", re.M)


def live_tail(text, n=TAIL):
    lines = [x for x in text.splitlines() if x.strip()]
    return "\n".join(lines[-n:])


def busy(text):
    # раньше фраза «esc to interrupt» искалась по всему экрану: эхо задания с этой фразой (карточка дела) держало «занят» до конца теста (07.11.26)
    t = live_tail(text)
    return bool(ESC_LIVE.search(t)) or bool(SPIN.search(t))


def dismiss_survey():
    """Опрос «How is Claude doing this session?» съедает цифры 0–3 из ввода: закрываем его клавишей 0."""
    if "0: Dismiss" in screen(15):
        key("0")
        time.sleep(0.6)


def tg_state(new=None):
    try:
        d = json.load(open(SETTINGS))
    except Exception:
        return None
    ep = d.setdefault("enabledPlugins", {})
    key = next((k for k in ep if "telegram" in k), "telegram@claude-plugins-official")
    if new is not None:
        ep[key] = bool(new)
        tmp = SETTINGS + ".tmp%d" % os.getpid()
        json.dump(d, open(tmp, "w"), ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS)
    return bool(ep.get(key))


def key(k):
    sh(["tmux", "send-keys", "-t", TMUX, k])


def accept_startup_menu(text):
    if not (MENU_YES.search(text) or MENU_TRUST.search(text)):
        return False
    current = next((line for line in text.splitlines() if "❯" in line), "")
    if "no, exit" in current:
        key("Down")
        time.sleep(0.4)
    elif not any(word in current for word in ("yes, i trust", "yes, i accept", "yes, continue")):
        return False
    key("Enter")
    return True


def start(sid, tg, use_guard=True):
    tg_state(1 if tg else 0)
    sh(["tmux", "kill-session", "-t", TMUX])
    cmd = "cd /root; export IS_SANDBOX=1 CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1; exec %s --dangerously-skip-permissions" % CLAUDE
    try:
        import remote_guard as guard
        if not guard.SETTINGS.exists():
            guard.configure(dict(enabled=True, threshold=90, weekly_cap=99, weekly_pause=False))
        if use_guard and guard.SETTINGS.exists():
            cmd = cmd.replace("; exec ", "; export CC_FLEET_LIMIT_GUARD=1; exec ")
            cmd += " --settings " + shlex.quote(str(guard.SETTINGS))
    except ImportError:
        return ({"ok": False, "error": "limit_guard_missing"})
    if tg:
        cmd += " --channels plugin:telegram@claude-plugins-official"
    if sid and sid != "-":
        cmd += " --resume " + sid
    code, _ = sh(["tmux", "new-session", "-d", "-s", TMUX, "-x", "230", "-y", "50", cmd])
    if code != 0:
        return ({"ok": False, "error": "tmux"})
    end = time.time() + 120
    seen = ""
    while time.time() < end:
        time.sleep(2)
        if not alive():
            return ({"ok": False, "error": "exited", "screen": screen(15)[-600:]})
        seen = screen(40)
        low = live_tail(seen).lower()  # только живая область: после --resume выше история беседы с теми же словами (07.11.26)
        if accept_startup_menu(low):
            continue
        if ("❯" in low and "esc to interrupt" not in low and "loading" not in low
              and "resuming" not in low and not MENU_NO.search(low)):
            time.sleep(2)
            return ({"ok": True, "tg": bool(tg), "sid": sid})
    return ({"ok": False, "error": "timeout", "screen": seen[-600:]})


def hist_file():
    """Файл активной беседы: самый свежий *.jsonl в папке проекта."""
    best, mt = "", -1.0
    try:
        for n in os.listdir(PROJ):
            p = os.path.join(PROJ, n)
            if n.endswith(".jsonl") and os.path.isfile(p) and os.path.getmtime(p) > mt:
                best, mt = p, os.path.getmtime(p)
    except OSError:
        pass
    return best


def guard_status():
    import remote_guard as guard
    result = dict(guard.status(), ok=True, running=alive(), applied=False)
    code, text = sh(["tmux", "display-message", "-p", "-t", TMUX, "#{pane_pid}"])
    try:
        env = Path("/proc/%d/environ" % int(text.strip())).read_bytes().split(b"\0")
        result["applied"] = b"CC_FLEET_LIMIT_GUARD=1" in env
    except (OSError, ValueError):
        pass
    tail = live_tail(screen(40)).lower() if result["running"] else ""
    result["ready"] = bool(result["running"] and "❯" in tail and not MENU_NO.search(tail))
    return result


def composer_has_draft(raw):
    """Ignore the dim placeholder and old echoed prompts; preserve real input."""
    lines = raw.splitlines()
    rules = [i for i, line in enumerate(lines) if re.match(r"^\s*[─━]{5,}", ANSI.sub("", line))]
    if len(rules) >= 2:
        lines = lines[rules[-2] + 1:rules[-1]]
    prompts = [i for i, line in enumerate(lines) if re.match(r"^\s*❯", ANSI.sub("", line))]
    if not prompts:
        return False
    i = prompts[-1]
    if any(ANSI.sub("", line).strip() for line in lines[i+1:]):
        return True
    line = lines[i]
    plain = ANSI.sub("", line)
    content = re.sub(r"^\s*❯\s*", "", plain)
    if not content:
        return False
    # Claude renders a suggestion in dim SGR 2 after the prompt, with the
    # cursor still on the empty input. Actual typed characters use normal SGR.
    dim, offset, column = False, 0, 0
    start = plain.index("❯") + 1
    for match in list(ANSI.finditer(line)) + [None]:
        end = match.start() if match else len(line)
        segment = line[offset:end]
        visible = segment[max(0, start-column):]
        if visible.strip() and not dim:
            return True
        column += len(segment)
        if not match:
            break
        if match.group().endswith("m"):
            values = [int(v or 0) for v in match.group()[2:-1].split(";")]
            j = 0
            while j < len(values):
                value = values[j]
                if value in (38, 48) and j+1 < len(values):
                    j += 5 if values[j+1] == 2 else 3
                    continue
                if value in (0, 22):
                    dim = False
                elif value == 2:
                    dim = True
                j += 1
        offset = match.end()
    return False



def current_sid():
    code, text = sh(["tmux", "display-message", "-p", "-t", TMUX, "#{pane_pid}"])
    sid = ""
    try:
        pid = int(text.strip())
        args = Path("/proc/%d/cmdline" % pid).read_bytes().decode().split("\0")
        for flag in ("--resume", "--session-id"):
            if flag in args:
                candidate = args[args.index(flag) + 1]
                if re.fullmatch(r"[0-9a-fA-F-]{36}", candidate):
                    sid = candidate
        if not sid:
            path = hist_file()
            # A new conversation has no --resume argument. Only consider a
            # transcript written during this process's lifetime.
            stat = Path("/proc/%d/stat" % pid).read_text()
            ticks = float(stat[stat.rfind(")") + 2:].split()[19])
            uptime = float(Path("/proc/uptime").read_text().split()[0])
            started = time.time() - uptime + ticks / os.sysconf("SC_CLK_TCK")
            if path and os.path.getmtime(path) >= started:
                candidate = Path(path).stem
                if re.fullmatch(r"[0-9a-fA-F-]{36}", candidate):
                    sid = candidate
    except (OSError, ValueError, IndexError):
        pass
    return sid


def guard_reload():
    if not alive() or guard_status().get("applied"):
        out(dict(ok=True, reloaded=False))
    _, raw = sh(["tmux", "capture-pane", "-t", TMUX, "-p", "-e", "-J", "-S", "-40"])
    text = ANSI.sub("", raw)
    if busy(text) or composer_has_draft(raw):
        out(dict(ok=True, reloaded=False, waiting=True))
    sid = current_sid()
    if not sid:
        out(dict(ok=False, error="guard_session_unknown"))
    import remote_guard as guard
    attempt = guard.BASE / ("limits-" + guard.NAME + "-reload.json")
    previous = guard.load(attempt)
    if previous.get("failed") and time.time() - float(previous.get("ts") or 0) < 300:
        out(dict(ok=False, error="guard_reload_cooldown"))
    telegram = bool(tg_state())
    result = start(sid, telegram)
    if not result.get("ok"):
        # Restore the same conversation if the new launch fails. Do not loop
        # through repeated restarts and never leave the console silently dead.
        restored = start(sid, telegram, use_guard=False)
        guard.save(attempt, dict(failed=True, ts=time.time()))
        out(dict(ok=False, error="guard_reload_failed", restored=bool(restored.get("ok"))))
    guard.save(attempt, dict(failed=False, ts=time.time()))
    out(dict(ok=True, reloaded=True))


def main():
    a = sys.argv[1:] or ["status"]
    c = a[0]
    if c == "guard-config":
        import remote_guard as guard
        out(guard.configure(json.load(sys.stdin)))
    if c == "guard-status":
        out(guard_status())
    if c == "guard-reload":
        guard_reload()
    if c == "cli":  # cli status [check] | update [версия] | rollback — Claude Code на этом сервере (модуль claude_cli.py лежит рядом)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import claude_cli
        res = claude_cli.run(a[1:])
        if isinstance(res, dict) and res.get('ok') and (a[1:2] or ['status'])[0] == 'status':
            started = 0
            if alive():
                try:
                    started = float(sh(['tmux', 'display', '-p', '-t', TMUX, '#{session_created}'])[1].strip() or 0)
                except ValueError:
                    started = 0
            res['restart'] = {'running': alive(), 'started': started, 'tg': bool(tg_state())}   # для кнопки «Перезапустить Claude»
        out(res)
    if c == "status":
        s = screen(40) if alive() else ""
        out({"ok": True, "running": alive(), "busy": busy(s), "tg": tg_state()})
    if c == "screen":
        out({"ok": True, "running": alive(), "text": screen(int(a[1]) if len(a) > 1 else 60)})
    if c == "start":
        out(start(a[1] if len(a) > 1 else "-", len(a) > 2 and a[2] == "1"))
    if c == "stop":
        sh(["tmux", "kill-session", "-t", TMUX])
        out({"ok": True, "running": alive()})
    if c == "tg":
        out({"ok": True, "tg": tg_state(1 if a[1] == "1" else 0)})
    if c == "key":
        key(a[1])
        out({"ok": True})
    if c == "send":
        if not alive():
            out({"ok": False, "error": "not_running"})
        sh(["tmux", "load-buffer", "-b", "ccmsg", a[1]])
        sh(["tmux", "paste-buffer", "-b", "ccmsg", "-t", TMUX])
        time.sleep(1.5)
        key("Enter")
        out({"ok": True})
    if c == "ansi":  # ansi КОЛОНОК ИСТОРИЯ: экран с цветами; КОЛОНОК=0 не менять размер; ИСТОРИЯ=0 — видимый экран, N — N строк истории
        cols = int(a[1]) if len(a) > 1 else 0
        hist = int(a[2]) if len(a) > 2 else 0
        if not alive():
            out({"ok": True, "running": False, "text": "", "cols": 0, "rows": 0})
        if 60 <= cols <= 300:
            _, info = sh(["tmux", "display", "-p", "-t", TMUX, "#{window_width}"])
            if info.strip() != str(cols):
                sh(["tmux", "resize-window", "-t", TMUX, "-x", str(cols), "-y", "50"])
        _, info = sh(["tmux", "display", "-p", "-t", TMUX, "#{pane_width} #{pane_height}"])
        w, h = (info.split() + ["0", "0"])[:2]
        cap = ["tmux", "capture-pane", "-t", TMUX, "-p", "-e"] + (["-S", "-%d" % hist, "-E", "-1"] if hist else [])
        code, text = sh(cap, timeout=20)
        out({"ok": code == 0, "running": True, "cols": int(w), "rows": int(h), "text": text})
    if c == "setmodel":  # setmodel МОДЕЛЬ ЭФФОРТ ('-' = не менять): settings.json + /model, /effort в запущенной сессии
        mid = a[1] if len(a) > 1 and a[1] != "-" else ""
        eff = a[2] if len(a) > 2 and a[2] != "-" else ""
        if not re.fullmatch(r"[A-Za-z0-9._\[\]-]{0,80}", mid) or not re.fullmatch(r"[a-z]{0,12}", eff):
            out({"ok": False, "error": "bad_args"})
        try:
            d = json.load(open(SETTINGS))
        except Exception:
            out({"ok": False, "error": "settings"})
        if mid:
            d["model"] = mid
        cur = d.get("model") or ""
        if eff:
            if cur:
                d.setdefault("modelSettings", {}).setdefault(cur, {})["effortLevel"] = eff
            d["effortLevel"] = eff
        tmp = SETTINGS + ".tmp%d" % os.getpid()
        json.dump(d, open(tmp, "w"), ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS)
        applied, running, wait = [], alive(), False
        if running and busy(screen(40)):
            wait = True
        elif running:
            for cmd in (("/model " + mid) if mid else "", ("/effort " + eff) if eff else ""):
                if cmd:
                    sh(["tmux", "send-keys", "-t", TMUX, "-l", cmd])
                    time.sleep(1)
                    key("Enter")
                    time.sleep(2)
                    applied.append(cmd)
            try:  # Claude Code сам переписывает настройки при /model и /effort: закрепляем выбранное ещё раз
                d = json.load(open(SETTINGS))
                if mid:
                    d["model"] = mid
                want = eff or d.get("effortLevel") or ""  # сменили только модель: effort сессии остался прежним — настройки выравниваем под него
                if want and (d.get("model") or ""):
                    d.setdefault("modelSettings", {}).setdefault(d["model"], {})["effortLevel"] = want
                    d["effortLevel"] = want
                tmp = SETTINGS + ".tmp%d" % os.getpid()
                json.dump(d, open(tmp, "w"), ensure_ascii=False, indent=2)
                os.replace(tmp, SETTINGS)
            except Exception:
                pass
        out({"ok": True, "running": running, "applied": applied, "wait": wait})
    if c == "sendin":  # текст из stdin: как ввод человека в консоль (занято — отказ; «sendin queue» — обычный текст ставим в очередь Claude)
        text = sys.stdin.read()
        if not alive():
            out({"ok": False, "error": "not_running"})
        queue_ok = len(a) > 1 and a[1] == "queue" and not text.lstrip().startswith("/")
        if busy(screen(40)) and not queue_ok:
            out({"ok": False, "error": "busy"})
        dismiss_survey()
        m = re.fullmatch(r"(/[A-Za-z][A-Za-z0-9_-]{0,79})(?:[ \t]+(.*))?", text, re.S)
        if m:
            prefix, rest = m.groups()
            sh(["tmux", "send-keys", "-t", TMUX, "-l", prefix + (" " if rest else "")])
            time.sleep(1)
            if not rest:
                key("Enter")
                out({"ok": True})
            text = rest
        sh(["tmux", "load-buffer", "-b", "ccmsg", "-"], inp=text)
        sh(["tmux", "paste-buffer", "-p", "-b", "ccmsg", "-t", TMUX])
        time.sleep(1)
        key("Enter")
        for _ in range(12):  # Claude начинает отвечать через 3–4 с: пока «занят» не появился, второй ввод и возврат работы проскочили бы
            time.sleep(0.7)
            if busy(screen(40)):
                break
        out({"ok": True})
    if c == "hist":  # путь и размер файла активной беседы: точка отсчёта, чтобы дождаться именно нового ответа
        p = hist_file()
        out({"ok": bool(p), "path": p, "size": os.path.getsize(p) if p else 0})
    if c == "histtail":  # histtail ПУТЬ СМЕЩЕНИЕ: новые байты файла беседы (base64, до 200 КБ за раз); чужие пути не читаем
        import base64
        path = a[1] if len(a) > 1 else ""
        try:
            off = max(int(a[2]), 0) if len(a) > 2 else 0
        except ValueError:
            off = -1
        if off < 0 or not path.startswith(PROJ + "/") or not path.endswith(".jsonl") or os.path.realpath(path) != path:
            out({"ok": False, "error": "bad_args"})
        try:
            with open(path, "rb") as f:
                f.seek(off)
                data = f.read(200000)
        except OSError:
            out({"ok": False, "error": "read"})
        out({"ok": True, "size": off + len(data), "b64": base64.b64encode(data).decode()})
    out({"ok": False, "error": "unknown"})


main()
