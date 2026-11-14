"""[remote] «Двойная работа»: режим говорит «работа на Claude PROD», а основной Claude здесь (с Telegram) запущен.

Так бывает, когда Claude DEV поднялся мимо панели (автозапуск после перезагрузки сервера, ручной скрипт), а PROD остановили
не кнопкой: флаг режима остался на PROD, шапка показывает «PROD работает», пауза DEV держится, но задание уже забрал DEV.
Оба слушают одного Telegram-бота: ответы дублируются или теряются.

Панель ничего не переключает сама (на PROD могут ещё работать): держит расхождение HOLD_SEC подряд, показывает плашку
(remote_mode.split) и один раз пишет в Telegram. Выход выбирает владелец: «Оставить DEV» (снять режим PROD, как «Вернуть мне»)
или «Остановить DEV» (работа остаётся на PROD)."""
import os
import threading
import time

import cc_remote as R

FILE = os.environ.get("CC_REMOTE_SPLIT") or R.BASE + "/remote_split.json"
HOLD_SEC = 120     # сколько подряд расхождение должно держаться, прежде чем показать плашку
STALE_SEC = 150    # проверка не шла дольше — «подряд» не подтверждено: отсчёт начинаем заново, плашку не показываем
ACTIONS = ("keep_dev", "stop_dev")
_lock = threading.Lock()
_mem = {"first": 0.0, "seen": 0.0, "notified": 0.0}
_loaded = [False]


def suspect(active, busy, running):
    """Расхождение: режим «работа на PROD», вне операции передачи, а основной Claude с Telegram здесь запущен."""
    return bool(active and running and not busy)


def advance(now, flag, st):
    """Один шаг счётчика. Возвращает (новое состояние, писать ли в Telegram). Не трогает файлы и часы."""
    first, seen, notified = (float(st.get(k) or 0) for k in ("first", "seen", "notified"))
    if not flag:
        return dict(first=0.0, seen=0.0, notified=0.0), False
    if not first or now - seen > STALE_SEC:
        first, notified = now, 0.0
    on = now - first >= HOLD_SEC
    notify = on and not notified
    return dict(first=first, seen=now, notified=now if notify else notified), notify


def _load():
    if _loaded[0]:
        return
    _loaded[0] = True
    d = R.jload(FILE, {})
    if isinstance(d, dict):
        for k in _mem:
            try:
                _mem[k] = float(d.get(k) or 0)
            except (TypeError, ValueError):
                pass


def _save():
    try:
        R.jsave(FILE, dict(_mem))
    except OSError:
        pass


def public(now=None):
    """Для remote_mode.public(): {} — расхождения нет; иначе {on, since}. since — когда расхождение замечено."""
    now = time.time() if now is None else now
    with _lock:
        _load()
        first, seen = _mem["first"], _mem["seen"]
    if first and now - first >= HOLD_SEC and now - seen <= STALE_SEC:
        return dict(on=True, since=first)
    return {}


def _text(minutes):
    return ("⚠️ Двойная работа: режим «работа на Claude PROD», а основной Claude DEV с Telegram запущен уже %d мин "
            "(мог подняться сам, например после перезагрузки сервера). Оба слушают одного бота: ответы могут дублироваться "
            "или теряться. Панель ничего не переключала. Открой панель: «Оставить DEV» вернёт работу сюда, «Остановить DEV» "
            "оставит её на PROD." % max(1, int(minutes)))


def tick(ns=None, now=None):
    """Проверка раз в TICK_SEC из потока панели. Ошибки не пробрасываются."""
    import cc_remote_mode as M
    now = time.time() if now is None else now
    try:
        wk = M._wk()
        flag = wk is not None and suspect(M.active(), M.busy(), wk.claude_running())
    except Exception:
        return public(now)
    with _lock:
        _load()
        st, notify = advance(now, flag, _mem)
        first = st["first"]
        if st != _mem:
            _mem.update(st)
            _save()
    if notify:
        try:
            (ns or M._NS)["tg_notify"](_text((now - first) / 60))
        except Exception:
            pass
    return public(now)


def resolve(action, force=False):
    """POST /api/remote/split {action, force?}. keep_dev: вернуть работу на DEV (как «Вернуть мне»); stop_dev: остановить Claude DEV."""
    import cc_remote_mode as M
    if action not in ACTIONS:
        return {"ok": False, "message": "Неизвестное действие."}
    wk = M._wk()
    if wk is None:
        return {"ok": False, "message": "Панель ещё не готова."}
    with M.LOCK:
        if M.busy():
            return {"ok": False, "busy": True, "message": "Операция уже идёт."}
        if not (M.active() and wk.claude_running()):
            tick()
            return {"ok": True, "message": "Расхождения уже нет."}
        if action == "keep_dev":
            return M.off("Claude DEV запущен сам: оставляем работу на нём (кнопка в панели)", force)
        stopped = bool(wk.stop_claude())
    tick()
    if not stopped:
        return {"ok": False, "message": "Claude DEV не остановился: проверь консоль."}
    return {"ok": True, "message": "Claude DEV остановлен. Работа остаётся на Claude PROD."}
