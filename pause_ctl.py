#!/usr/bin/env python3
# Пауза по лимитам — состояние на диске + будильник, переживающий сессию.
#
# Зачем: когда все аккаунты упёрлись в 5-часовое окно, переключаться некуда и
# единственное разумное поведение — встать на паузу до ближайшего сброса. Если
# будильник поставить внутри самой сессии Claude Code, он умрёт вместе с ней
# (перезапуск, /clear, ребут). Поэтому состояние лежит в JSON рядом со снапшотом,
# а будит его системный cron: раз в минуту дёргает `wake --if-due`.
#
# Команды:
#   pause_ctl.py set [--reason "..."] [--resume-at ISO] [--note "..."]  — встать на паузу
#   pause_ctl.py status [--json]                                        — что сейчас
#   pause_ctl.py clear                                                  — снять руками
#   pause_ctl.py wake --if-due                                          — крон-тик
#   pause_ctl.py off [--by ...]  — отключить паузу (кнопка на веб-панели): работа сверх порога
#   pause_ctl.py on  [--by ...]  — включить обратно; если окно всё ещё забито — пауза сразу
#
# Пауза ставится ТОЛЬКО по сессионному (5-часовому) окну — недельный потолок её не
# касается: он держит балансер и фоновые задачи (limits_gate.py), но не разговор.
# «Отключена вручную» (override) переживает все автоматические постановки паузы
# (очередь входящих, хук инструментов) и снимается сама, когда окно отпустит,
# или кнопкой «Включить паузу».
#
# При постановке паузы и при автоматическом подъёме уходит уведомление в Telegram —
# если в config.json задан chat_id (отключается ключом "pause_notify": false).
#
# Cron (ставится install.sh):
#   * * * * * root /usr/bin/python3 /opt/cc-limits/pause_ctl.py wake --if-due >> /opt/cc-limits/pause_wake.log 2>&1
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_avail  # noqa: E402

BASE = os.environ.get("CC_LIMITS_BASE", os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "pause_state.json")
SNAP = os.path.join(BASE, "snapshot.json")
CONFIG = os.path.join(BASE, "config.json")
GATE = os.path.join(BASE, "limits_gate.py")
TG_ENV = "/root/.claude/channels/telegram/.env"
GRACE = 180  # будим не в секунду сброса, а через 3 минуты — окно отпускает не мгновенно

# Текст, который уходит в живую сессию при снятии паузы. СТРОГО ASCII: screen,
# поднятый без -U, принимает не-ASCII побайтовым мусором и швыряет его прямо во
# ввод сессии. Переопределяется ключом "pause_wake_message" в config.json.
WAKE_MSG = ("[cc-pause] limits window reset (%s). Pause lifted automatically by cron. "
            "Continue the paused task from the state saved earlier.")


def _now():
    return time.time()


def _cfg():
    try:
        d = json.load(open(CONFIG))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _threshold():
    try:
        return float(_cfg().get("threshold") or 90)
    except Exception:
        return 90.0


def _weekly_cap():
    try:
        return float(_cfg().get("weekly_cap") or 99)
    except Exception:
        return 99.0


def _screen():
    """Имя screen-сессии Claude Code: env (для тестов) → config.json → 'claude'."""
    return os.environ.get("CC_PAUSE_SCREEN") or _cfg().get("screen_session") or "claude"


def load():
    """Состояние паузы; отсутствие файла = паузы нет."""
    try:
        d = json.load(open(STATE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(d):
    """Атомарная запись — крон и сессия могут писать одновременно."""
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def accounts():
    try:
        d = json.load(open(SNAP))
    except Exception:
        return {}, "", 0.0
    return (d.get("accounts") or {}), (d.get("active") or ""), float(d.get("ts") or 0)


NO_WEEK = float("inf")  # паузе недельный потолок не нужен — см. шапку


def nearest_reset():
    """(iso, имя аккаунта) — когда раньше всех отпустит сессионное окно какого-то аккаунта."""
    nb = cc_avail.nearest(accounts()[0], _threshold(), NO_WEEK)
    if not nb:
        return "", ""
    return datetime.fromtimestamp(nb[0], tz=timezone.utc).isoformat(), nb[1]


def session_blocked():
    """(стоять?, строка) — решение будильника: все аккаунты выше сессионного порога или
    активный выше порога (балансер ещё не ушёл). Неделю не смотрим. Нет свежего снимка —
    не держим (fail-open, как limits_gate)."""
    s = level_state()
    if s.get("stale"):
        return False, "снимок лимитов устарел"
    line = s.get("line") or "?"
    if s.get("level") == "hard":
        return True, "все аккаунты выше порога сессии (%s)" % line
    a = s["accounts"].get(s.get("active")) or {}
    if a and not a.get("ses_ok", True):
        return True, "активный %s выше порога сессии (%s) — жду переключения балансера" % (
            s.get("active"), line)
    return False, "ок (%s)" % line


def level_state():
    """Сводка для баннера на веб-панели — считается по тем же файлам, что и гейт,
    но без запуска подпроцесса (страницу опрашивают часто).

    level: hard — все аккаунты выше порога сессионного окна, переключаться некуда —
                  здесь встаёт пауза (неделя не участвует);
           gate — активный не пригоден (сессия или неделя), но пригодный есть (балансер
                  вот-вот уйдёт, фоновые задачи в это время не стартуют);
           none — рабочее состояние.
    """
    accs, active, ts = accounts()
    thr = _threshold()
    st = load()
    pause = {
        "override": bool(st.get("override")),
        "override_since": st.get("override_since") or 0,
        "active": bool(st.get("active")),
        "reason": st.get("reason") or "",
        "note": st.get("note") or "",
        "since": st.get("since") or 0,
        "resume_at": st.get("resume_at") or 0,
        "checks": st.get("checks") or 0,
    }
    out = {"pause": pause, "threshold": thr, "level": "none", "accounts": {},
           "active": active, "stale": bool(not accs or (_now() - ts) > 900)}
    if out["stale"]:
        return out

    cap = _weekly_cap()
    pcts, usable, ses_ok = {}, {}, {}
    for name, row in accs.items():
        fh = row.get("five_hour") or {}
        pct = fh.get("pct")
        pcts[name] = float(pct if pct is not None else 0.0)
        ok, t, why = cc_avail.availability(row, thr, cap)
        usable[name] = ok
        ses_ok[name] = cc_avail.availability(row, thr, NO_WEEK)[0]
        out["accounts"][name] = {"pct": pct, "resets_at": fh.get("resets_at") or "",
                                 "wpct": (row.get("seven_day") or {}).get("pct"),
                                 "usable": ok, "held": why, "ses_ok": ses_ok[name],
                                 "email": row.get("email") or "", "active": name == active}
    if ses_ok and not any(ses_ok.values()):
        out["level"] = "hard"
    elif active in usable and not usable[active]:
        out["level"] = "gate"
    iso, who = nearest_reset()
    out["nearest"] = {"acc": who, "resets_at": iso, "held": "сессия" if who else ""}
    out["line"] = ", ".join("%s %.0f%%" % (n, p) for n, p in sorted(pcts.items()))
    return out


def gate():
    """(заблокировано?, строка вердикта) — тот же гейт, что и у фоновых задач."""
    try:
        r = subprocess.run([sys.executable, GATE, str(_threshold())],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 10, (r.stdout or "").strip()
    except Exception as e:
        return False, "гейт недоступен (%s)" % e


def _dur(sec):
    """Длительность паузы человеческим текстом: «41 мин», «2 ч 05 мин»."""
    sec = max(0, int(sec))
    h, m = sec // 3600, (sec % 3600) // 60
    return "%d ч %02d мин" % (h, m) if h else "%d мин" % m


def _queued():
    """Сколько входящих сообщений легло в очередь, пока держалась пауза."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tg_queue
        return len(tg_queue._pending())
    except Exception:
        return 0


def _log(msg):
    print("%s %s" % (datetime.now().strftime("%d.%m %H:%M:%S"), msg), flush=True)


def _tg(text, force=False):
    """Уведомление в Telegram: chat_id из config.json, токен — из файла телеграм-канала
    Claude Code либо из ключа "bot_token" там же. Отключается ключом "pause_notify": false.

    force=True — отправить даже при выключенных уведомлениях о паузе. Так шлёт
    подтверждение очередь (tg_queue.py): человек ждёт ответа на своё сообщение, это
    не фоновое уведомление, и глушится оно отдельным ключом "queue_ack".

    Крон-скрипт сознательно не импортирует cc_limits (тот на верхнем уровне тянет
    pyte/pexpect ради зеркала консоли — паузе они не нужны), поэтому логика продублирована
    здесь в минимальном виде. Держать синхронно с tg_notify() в cc_limits.py.
    """
    c = _cfg()
    chat_id = c.get("chat_id")
    if not chat_id or (not force and not c.get("pause_notify", True)):
        return
    token = ""
    try:
        m = re.search(r"TELEGRAM_BOT_TOKEN=(\S+)", open(TG_ENV).read())
        token = m.group(1) if m else ""
    except Exception:
        pass
    token = token or (c.get("bot_token") or "").strip()
    if not token:
        _log("телеграм: chat_id есть, токен бота не найден — уведомление пропущено")
        return
    try:
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % token,
            data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        _log("телеграм: не отправилось (%s)" % e)


def cmd_set(a):
    if load().get("override"):
        # паузу отключили кнопкой — автоматические постановки (очередь, хук) молчат,
        # пока её не включат обратно или окно не отпустит само (см. cmd_wake)
        _log("пауза отключена вручную — не ставлю (%s)" % (a.reason or "лимиты"))
        return 0
    iso, who = (a.resume_at, "") if a.resume_at else nearest_reset()
    resume_ts = 0.0
    if iso:
        try:
            resume_ts = datetime.fromisoformat(iso).timestamp() + GRACE
        except Exception:
            resume_ts = 0.0
    if not resume_ts:
        resume_ts = _now() + 3600  # окна не видно — перепроверим через час
    st = {
        "active": True,
        "since": _now(),
        "reason": a.reason or "лимиты сессионного окна",
        "note": a.note or "",
        "resume_at": resume_ts,
        "reset_of": who,
        "checks": 0,
    }
    save(st)
    when = datetime.fromtimestamp(resume_ts).strftime("%H:%M")
    _log("пауза поставлена, подъём в %s (%s)" % (when, st["reason"]))
    msg = "⏸ Claude: пауза по лимитам до %s — %s." % (when, st["reason"])
    line = level_state().get("line") or ""
    if line:
        msg += "\nСессионные окна: %s." % line
    if st["note"]:
        msg += "\nНезакрытое: %s" % st["note"]
    _tg(msg)
    return 0


def cmd_clear(_a):
    st = load()
    st.update(active=False, cleared_at=_now())
    save(st)
    _log("пауза снята вручную")
    return 0


def cmd_status(a):
    st = load()
    blocked, line = gate()
    sb, sline = session_blocked()
    out = {"pause": st, "gate_blocked": blocked, "gate": line,
           "session_blocked": sb, "session": sline}
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print("пауза: %s" % ("ОТКЛЮЧЕНА вручную с %s" % datetime.fromtimestamp(
            st.get("override_since") or 0).strftime("%d.%m %H:%M") if st.get("override")
            else "активна" if st.get("active") else "нет"))
        if st.get("active"):
            print("  причина: %s" % st.get("reason"))
            print("  подъём:  %s"
                  % datetime.fromtimestamp(st.get("resume_at") or 0).strftime("%d.%m %H:%M"))
        print("окно для паузы: %s" % sline)
        print("гейт: %s" % line)
    return 0


def cmd_wake(a):
    st = load()
    if st.get("override"):
        # отключённая вручную пауза включается обратно сама, как только окно отпустило —
        # иначе следующий забитый лимит прошёл бы уже без неё
        ls = level_state()
        if not ls.get("stale") and ls.get("level") != "hard":
            st.update(override=False, override_cleared_at=_now(), override_cleared_by="окно отпустило")
            save(st)
            _log("пауза снова включена: окно отпустило (%s)" % (ls.get("line") or "?"))
        return 0
    if not st.get("active"):
        return 0
    if a.if_due and _now() < float(st.get("resume_at") or 0):
        return 0

    blocked, line = session_blocked()
    if blocked:
        # окно ещё не отпустило — молча переставляем будильник, никого не дёргаем
        iso, who = nearest_reset()
        try:
            nxt = datetime.fromisoformat(iso).timestamp() + GRACE
        except Exception:
            nxt = _now() + 1800
        if nxt <= _now():
            nxt = _now() + 600
        st.update(resume_at=nxt, reset_of=who, checks=int(st.get("checks") or 0) + 1,
                  last_gate=line)
        save(st)
        _log("ещё рано (%s) — подъём перенесён на %s"
             % (line, datetime.fromtimestamp(nxt).strftime("%H:%M")))
        return 0

    st.update(active=False, resumed_at=_now(), last_gate=line)
    save(st)
    _log("пауза снята автоматически: %s" % line)
    stood = _dur(_now() - float(st.get("since") or _now()))
    msg = "▶️ Claude: пауза снята — окно отпустило."
    pcts = level_state().get("line") or ""
    if pcts:
        msg += "\nСессионные окна: %s." % pcts
    msg += "\nПростояли %s" % stood
    checks = int(st.get("checks") or 0)
    if checks:
        msg += ", перепроверок будильника: %d" % checks
    msg += ". Сессия разбужена, работа продолжается."
    if st.get("note"):
        msg += "\nБыло незакрыто: %s" % st["note"]
    _tg(msg)
    tmpl = _cfg().get("pause_wake_message") or WAKE_MSG
    try:
        msg = tmpl % (level_state().get("line") or "?")
    except TypeError:
        msg = tmpl  # в шаблоне нет %s — шлём как есть
    _wake_session(msg)
    return 0


def _wake_session(msg):
    """Будим живую сессию тем же способом, что и веб-кнопки панели — stuff в screen."""
    # Пока держалась пауза, входящие сообщения копились в очереди (tg_queue.py).
    # Разобрать их — первое дело после подъёма, иначе они молча потеряются.
    n = _queued()
    if n:
        msg += (" %d incoming message(s) were queued while paused: run "
                "`python3 %s take` and handle them oldest first."
                % (n, os.path.join(BASE, "tg_queue.py")))
    msg = msg.encode("ascii", "ignore").decode()  # см. комментарий у WAKE_MSG
    try:
        # Текст и Enter — ДВУМЯ раздельными stuff-вызовами, не одним "msg\r".
        # Длинная фраза, залитая одним stuff разом с хвостовым \r, может
        # осесть в поле ввода TUI непроглоченной — терминал успевает принять
        # символы, но завершающий \r не срабатывает как submit (похоже на
        # bracketed-paste: пачка байт, прилетевшая одним махом, трактуется
        # как вставка текста, а не как "напечатали и нажали Enter"; короткие
        # команды вроде "/compact\r" через тот же stuff проходят нормально
        # именно потому что это одна короткая пачка без такого разделения).
        # Пауза между текстом и Enter имитирует человека, который допечатал
        # и через мгновение нажал клавишу.
        subprocess.run(["screen", "-S", _screen(), "-X", "stuff", msg],
                       capture_output=True, timeout=10)
        time.sleep(0.3)
        subprocess.run(["screen", "-S", _screen(), "-X", "stuff", "\r"],
                       capture_output=True, timeout=10)
    except Exception as e:
        _log("инжект в screen не удался: %s" % e)


def cmd_off(a):
    """Кнопка «Отключить паузу»: входящие идут сразу, инструменты не блокируются —
    работа сверх порога, до настоящего лимита аккаунта."""
    st = load()
    was = bool(st.get("active"))
    st.update(active=False, override=True, override_since=_now(), override_by=a.by or "",
              cleared_at=_now())
    save(st)
    _log("пауза отключена вручную (%s)%s" % (a.by or "?", ", сессия стояла — бужу" if was else ""))
    _tg("▶️ Claude: пауза отключена вручную — работа сверх порога, до настоящего лимита "
        "аккаунта. Включится сама, когда отпустит сессионное окно, или кнопкой на панели.")
    if was or _queued():
        _wake_session("[cc-pause] Pause disabled manually from the web panel (%s): work past "
                      "the threshold is allowed. Continue the paused task from the state saved "
                      "earlier." % (level_state().get("line") or "?"))
    return 0


def cmd_on(a):
    """Кнопка «Включить паузу»: снимает отключение; если окно всё ещё забито — пауза сразу."""
    st = load()
    st.update(override=False, override_cleared_at=_now(), override_cleared_by=a.by or "")
    save(st)
    ls = level_state()
    _log("пауза снова включена вручную (%s)" % (a.by or "?"))
    if not ls.get("stale") and ls.get("level") == "hard":
        return cmd_set(argparse.Namespace(reason="включена вручную", resume_at="",
                                          note="окно забито (%s)" % (ls.get("line") or "")))
    _tg("⏸ Claude: пауза снова работает — встанет, когда все аккаунты упрутся в сессионное окно.")
    return 0


def main():
    p = argparse.ArgumentParser(description="пауза по лимитам Claude")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set")
    s.add_argument("--reason", default="")
    s.add_argument("--resume-at", default="", dest="resume_at")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("clear")
    s.set_defaults(fn=cmd_clear)

    for name, fn in (("off", cmd_off), ("on", cmd_on)):
        s = sub.add_parser(name)
        s.add_argument("--by", default="")
        s.set_defaults(fn=fn)

    s = sub.add_parser("wake")
    s.add_argument("--if-due", action="store_true", dest="if_due")
    s.set_defaults(fn=cmd_wake)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
