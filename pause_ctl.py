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
# Пауза ставится по сессионному (5-часовому) окну. Недельный потолок ставит её, только
# если включён ключ "weekly_pause" (⚙ Настройки → «Пауза на недельном потолке», v1.21.0):
# активный дошёл до weekly_cap и переключаться некуда — стоим, пока не освободится другой
# аккаунт или не сбросится неделя. Ключ выключен — неделя паузу не ставит, панель и
# Telegram предупреждают, что заполнение до 100% никто не остановит.
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
CC_STATE = os.path.join(BASE, "state.json")  # состояние балансера (cc_limits.py): ручной выбор
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


def _weekly_pause():
    """Опция «Пауза на недельном потолке»: по умолчанию выключена."""
    return bool(_cfg().get("weekly_pause"))


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


NO_WEEK = float("inf")  # сессионной паузе недельный потолок не нужен — см. шапку


def _nearest(week=False):
    """(iso, имя, что держит) — когда снова будет где работать. week=True — пауза на недельном
    потолке: неделю смотрим у всех. week=False — сессионная пауза: активный ждёт только сброса
    своей сессии, а другой аккаунт — и сессии, и недели: на аккаунт с неделей на потолке
    балансер не переключает, его пустая сессия работы не даст."""
    accs, active, _ts = accounts()
    thr, cap = _threshold(), _weekly_cap()
    if week:
        nb = cc_avail.nearest(accs, thr, cap)
    else:
        nbs = [cc_avail.nearest(accs, thr, cap, exclude=(active,))]
        if active in accs:
            nbs.append(cc_avail.nearest({active: accs[active]}, thr, NO_WEEK))
        nbs = [x for x in nbs if x]
        nb = min(nbs) if nbs else None
    if not nb:
        return "", "", ""
    return datetime.fromtimestamp(nb[0], tz=timezone.utc).isoformat(), nb[1], nb[2]


def nearest_reset(week=False):
    """(iso, имя аккаунта) — когда раньше всех отпустит окно какого-то аккаунта."""
    iso, who, _held = _nearest(week)
    return iso, who


def _week_reason(s):
    """Причина паузы на недельном потолке — человеческим текстом."""
    a = s["accounts"].get(s.get("active")) or {}
    return "неделя %s на %.0f%% (потолок %.0f%%), переключаться некуда" % (
        s.get("active"), a.get("wpct") or 0, s.get("weekly_cap") or _weekly_cap())


def _held_text(a):
    """Что держит аккаунт: «сессия 91%», «неделя 100%», «сессия 93%, неделя 99%», «Free»."""
    if a.get("error"):
        return "ошибка"
    held = a.get("held") or ""
    if held == "free":
        return "Free"
    out = []
    if "сессия" in held:
        out.append("сессия %.0f%%" % (a.get("pct") or 0))
    if "неделя" in held:
        out.append("неделя %.0f%%" % (a.get("wpct") or 0))
    return ", ".join(out) or "?"


def _hard_reason(s):
    """Причина паузы «переключаться некуда» — что держит каждый аккаунт."""
    accs = s.get("accounts") or {}
    if not any(a.get("ses_ok") for a in accs.values()):
        return "все аккаунты выше порога сессии (%s), переключаться некуда" % (s.get("line") or "?")
    act = s.get("active")
    a = accs.get(act) or {}
    rest = ", ".join("%s — %s" % (n, _held_text(r)) for n, r in sorted(accs.items()) if n != act)
    return "%s: сессия %.0f%% (порог %.0f%%), переключаться некуда: %s" % (
        act, a.get("pct") or 0, s.get("threshold") or _threshold(), rest)


def session_blocked():
    """(стоять?, строка) — решение будильника: все аккаунты выше сессионного порога или
    активный выше порога (балансер ещё не ушёл). Неделю смотрим, только если включена
    «Пауза на недельном потолке». Нет свежего снимка — не держим (fail-open, как limits_gate)."""
    s = level_state()
    if s.get("stale"):
        return False, "снимок лимитов устарел"
    line = s.get("line") or "?"
    if s.get("level") == "hard":
        return True, _hard_reason(s)
    if s.get("level") == "week":
        return True, _week_reason(s)
    if s.get("level") == "manual":
        return False, "активный %s выбран вручную — работа идёт до 100%% (%s)" % (s.get("active"), line)
    a = s["accounts"].get(s.get("active")) or {}
    if a and not a.get("ses_ok", True):
        return True, "активный %s выше порога сессии (%s) — жду переключения балансера" % (
            s.get("active"), line)
    if a and s.get("weekly_pause") and (a.get("wpct") or 0) >= s.get("weekly_cap", 99):
        return True, "активный %s на недельном потолке — жду переключения балансера" % s.get("active")
    return False, "ок (%s)" % line


def week_blocked():
    """(стоять?, строка) — то же для паузы на недельном потолке: держим, пока уйти некуда или
    балансер ещё не ушёл с аккаунта на потолке. Сессию активного здесь не смотрим: оптимизация
    уходит и на аккаунт с сессией чуть выше порога — работать там она разрешила сама, а если
    забьются все сессии, встанет обычная сессионная пауза (уровень hard)."""
    s = level_state()
    if s.get("stale"):
        return False, "снимок лимитов устарел"
    line = s.get("line") or "?"
    if s.get("level") == "hard":
        return True, _hard_reason(s)
    if s.get("level") == "week":
        return True, _week_reason(s)
    a = s["accounts"].get(s.get("active")) or {}
    if a and s.get("weekly_pause") and (a.get("wpct") or 0) >= s.get("weekly_cap", 99):
        return True, "активный %s на недельном потолке — жду переключения балансера" % s.get("active")
    return False, "ок (%s)" % line


def level_state():
    """Сводка для баннера на веб-панели — считается по тем же файлам, что и гейт,
    но без запуска подпроцесса (страницу опрашивают часто).

    level: hard — активный выше порога сессии, и переключаться некуда: каждый другой
                  аккаунт выше порога сессии, на недельном потолке, Free или с ошибкой —
                  здесь встаёт пауза (неделя самого активного не участвует);
           manual — активный не пригоден, но выбран вручную (state.json → manual_hold):
                  балансер не уводит с него до сброса окна или до 100%, паузы нет;
           week — активный дошёл до недельного потолка, пригодных нет, и включена
                  «Пауза на недельном потолке» — здесь тоже встаёт пауза;
           weekrisk — то же, но опция выключена: паузы нет, заполнение до 100% никто
                  не остановит — панель и Telegram предупреждают;
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
        "kind": st.get("kind") or "session",
    }
    c = _cfg()
    out = {"pause": pause, "threshold": thr, "level": "none", "accounts": {},
           "active": active, "stale": bool(not accs or (_now() - ts) > 900),
           "weekly_cap": _weekly_cap(), "weekly_pause": _weekly_pause(),
           # уйдёт ли балансер с забитого сам: выключенное авто-переключение не уводит
           "autoswitch": bool(c.get("optimize") or c.get("autoswitch", True))}
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
                                 "error": bool(row.get("error")),
                                 "email": row.get("email") or "", "active": name == active}
    a = accs.get(active) or {}
    aw = (a.get("seven_day") or {}).get("pct")
    week_full = a.get("plan") != "free" and aw is not None and aw >= cap
    # уйти есть куда — пригодный аккаунт без ошибки (на ошибочный балансер не переключает)
    other_ok = any(ok for n, ok in usable.items() if n != active and not accs[n].get("error"))
    # ручной выбор забитого аккаунта балансер уважает (при оптимизации ручных переключений нет)
    try:
        hold = (json.load(open(CC_STATE)) or {}).get("manual_hold") or {}
    except Exception:
        hold = {}
    if (active in usable and not usable[active] and not c.get("optimize")
            and cc_avail.manual_pick(hold, active, a)):
        out["manual"] = {"account": active, "until": float(hold.get("until") or 0)}
    # до v1.21.6 «некуда» считалось только по сессиям: аккаунт с пустой сессией, но неделей
    # на потолке сходил за свободный — паузы не было, и активный добивался до 100%
    out["line"] = ", ".join("%s %.0f%%" % (n, p) for n, p in sorted(pcts.items()))
    if out.get("manual"):
        out["level"] = "manual"  # выбор человека: работа идёт до 100%, паузы нет
    elif active in ses_ok and not ses_ok[active] and not other_ok:
        out["level"] = "hard"
        out["why"] = _hard_reason(out)
    elif week_full and not other_ok:
        out["level"] = "week" if out["weekly_pause"] else "weekrisk"
    elif active in usable and not usable[active]:
        out["level"] = "gate"
    iso, who, held = _nearest(out["level"] in ("week", "weekrisk"))
    out["nearest"] = {"acc": who, "resets_at": iso, "held": held}
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
    ls = level_state()
    week = not ls.get("stale") and ls.get("level") == "week"
    iso, who = (a.resume_at, "") if a.resume_at else nearest_reset(week)
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
        # очередь и хук передают общую «сессионную» причину — пишем настоящую: что держит
        # активный и почему переключаться некуда
        "reason": (_week_reason(ls) if week else ls.get("why") if ls.get("level") == "hard"
                   and not ls.get("stale") else (a.reason or "лимиты сессионного окна")),
        "kind": "week" if week else "session",
        "note": a.note or "",
        "resume_at": resume_ts,
        "reset_of": who,
        "checks": 0,
    }
    save(st)
    when = datetime.fromtimestamp(resume_ts).strftime("%H:%M")
    _log("пауза поставлена, подъём в %s (%s)" % (when, st["reason"]))
    msg = "⏸ Claude: пауза по лимитам до %s — %s." % (when, st["reason"])
    line = ls.get("line") or ""
    if line:
        msg += "\nСессионные окна: %s." % line
    if week:
        msg += ("\nПоднимусь сам, когда освободится другой аккаунт или сбросится неделя. "
                "Продолжить сразу — «Отключить паузу» на панели.")
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
        if not ls.get("stale") and ls.get("level") not in ("hard", "week"):
            st.update(override=False, override_cleared_at=_now(), override_cleared_by="окно отпустило")
            save(st)
            _log("пауза снова включена: окно отпустило (%s)" % (ls.get("line") or "?"))
        return 0
    if not st.get("active"):
        return 0
    # пауза на неделе может стоять сутками, а уйти становится куда раньше будильника
    # (добавили аккаунт, выключили опцию, сняли потолок) — её проверяем каждую минуту
    week = st.get("kind") == "week"
    due = _now() >= float(st.get("resume_at") or 0)
    if a.if_due and not due and not week:
        return 0

    blocked, line = week_blocked() if week else session_blocked()
    if week and not blocked and level_state().get("stale"):
        blocked = True  # снимок протух — не снимаем недельную паузу вслепую
    if blocked:
        if a.if_due and not due:
            return 0  # неделя ещё держит — будильник не переставляем раньше срока
        # окно ещё не отпустило — молча переставляем будильник, никого не дёргаем
        iso, who = nearest_reset(week)
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
    msg = ("▶️ Claude: пауза на недельном потолке снята — есть куда работать." if week
           else "▶️ Claude: пауза снята — окно отпустило.")
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
        "аккаунта. Включится сама, когда освободится окно, или кнопкой на панели.")
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
    if not ls.get("stale") and ls.get("level") in ("hard", "week"):
        return cmd_set(argparse.Namespace(reason="включена вручную", resume_at="",
                                          note="окно забито (%s)" % (ls.get("line") or "")))
    _tg("⏸ Claude: пауза снова работает — встанет, когда активный упрётся в сессионное окно, "
        "а переключаться будет некуда"
        + (" или активный дойдёт до недельного потолка без запасного аккаунта." if _weekly_pause() else "."))
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
