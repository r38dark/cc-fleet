"""Сообщение в Telegram, когда в панели сменили модель и/или effort (Claude на этом сервере, Claude на втором сервере, Codex).

Одно сообщение на смену: если модель и effort сменили друг за другом за несколько секунд (два нажатия), они склеиваются в ОДНО.
Что не менялось — показывается прежним. Смена туда-обратно (A → B → A) сообщения не даёт. Только нажатия человека: автоматические
переключения (смена аккаунта, ротация Codex) сюда не звонят. Выключатель: config.json → model_change_notify = false.
"""
import threading

WINDOW = 4.0                       # смены одного исполнителя за столько секунд склеиваются в одно сообщение
ENABLED = lambda: True             # cc_limits: config.json → model_change_notify (по умолчанию включено)
SEND = {"claude": lambda text: False, "codex": lambda text: False}   # cc_limits подставляет отправку в Telegram

_FIELDS = (("model", "модель"), ("effort", "effort"), ("fast", "Fast"))
_lock = threading.Lock()
_pending = {}                      # подпись исполнителя -> {"engine", "first": {поле: что было}, "now": {поле: что стало}, "timer"}


def _norm(value):
    if value is True:
        return "вкл"
    if value is False:
        return "выкл"
    value = str(value).strip() if value is not None else ""
    return value or "—"


def changed(who, engine, before, after):
    """who — подпись («Claude DEV», «Codex · gpt1»), engine — claude|codex (какой чат), before/after — {model, effort, fast?}."""
    try:
        if not ENABLED():
            return
    except Exception:
        return
    diff = {k: (_norm(before.get(k)), _norm(after.get(k))) for k, _ in _FIELDS if k in before and k in after}
    if not any(a != b for a, b in diff.values()):
        return                                              # ничего не поменялось — молчим
    with _lock:
        p = _pending.get(who)
        if p is None:
            p = _pending[who] = {"engine": engine, "first": {}, "now": {}, "timer": None}
        for k, (old, new) in diff.items():
            p["first"].setdefault(k, old)
            p["now"][k] = new
        for k, _ in _FIELDS:
            if k in after:
                p["now"][k] = _norm(after.get(k))
        if p["timer"] is not None:
            p["timer"].cancel()
        t = threading.Timer(WINDOW, _flush, args=(who,))
        t.daemon = True
        p["timer"] = t
        t.start()


def text_for(who, first, now):
    """Текст сообщения или None, если по итогу ничего не изменилось."""
    ch = [(title, first[k], now[k]) for k, title in _FIELDS if k in first and first[k] != now.get(k)]
    if not ch:
        return None
    names = [t for t, _, _ in ch]
    head = ", ".join(names[:-1]) + " и " + names[-1] if len(names) > 1 else names[0]
    lines = ["🔄 %s: сменили %s" % (who, head)]
    for title, old, new in ch:
        lines.append("%s: %s → %s" % (title, old, new))
    for k, title in _FIELDS[:2]:                            # модель и effort показываем всегда, даже если не менялись
        if k not in first or first[k] == now.get(k):
            if now.get(k) not in (None, "—"):
                lines.append("%s: %s (без изменений)" % (title, now[k]))
    return "\n".join(lines)


def _flush(who):
    with _lock:
        p = _pending.pop(who, None)
    if not p:
        return
    text = text_for(who, p["first"], p["now"])
    if not text:
        return
    try:
        SEND.get(p["engine"], SEND["claude"])(text)
    except Exception:
        pass
