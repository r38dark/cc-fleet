# Когда аккаунт Claude снова пригоден для работы — единое правило для балансера
# (cc_limits.py), баннера паузы (pause_ctl.py) и гейта фоновых агентов (limits_gate.py).
#
# Аккаунт пригоден, если сессия ниже порога И неделя ниже недельного потолка И он не Free.
# Если нет — он станет пригоден в момент, когда сбросятся ВСЕ окна, которые его держат:
# забита только сессия → её сброс; забита только неделя → сброс недели; обе → позднейший.
# Сравнивать аккаунты по одному сбросу сессии нельзя: сессия может освободиться через
# 5 минут, а неделя держать ещё сутки, и наоборот.
import time
from datetime import datetime


def _ts(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return None


def availability(row, ses_thr, week_cap, now=None):
    """(пригоден сейчас?, ts когда станет пригоден | None, что держит).

    ts == now для пригодного; None — держит окно без известного времени сброса или Free."""
    now = time.time() if now is None else now
    if row.get("plan") == "free":
        return False, None, "free"
    held, times = [], []
    for key, lim, name in (("five_hour", ses_thr, "сессия"), ("seven_day", week_cap, "неделя")):
        w = row.get(key) or {}
        pct = w.get("pct")
        if pct is None or pct < lim:
            continue
        held.append(name)
        t = _ts(w.get("resets_at") or "")
        # сброс уже прошёл, а данные ещё старые — считаем «вот-вот», свежие придут на тике
        times.append(max(t, now) if t is not None else None)
    if not held:
        return True, now, ""
    if None in times:
        return False, None, "+".join(held)
    return False, max(times), "+".join(held)


def nearest(accs, ses_thr, week_cap, exclude=(), now=None):
    """(ts, имя, что держит) аккаунта, который раньше всех станет пригоден; None — не знаем."""
    best = None
    for n, row in accs.items():
        if n in exclude:
            continue
        _ok, t, why = availability(row, ses_thr, week_cap, now)
        if t is not None and (best is None or t < best[0]):
            best = (t, n, why)
    return best


def next_reset_ts(accs, now=None):
    """Ближайший будущий сброс любого окна любого аккаунта — когда балансеру стоит проснуться."""
    now = time.time() if now is None else now
    ts = [t for row in accs.values() for k in ("five_hour", "seven_day")
          for t in [_ts(((row.get(k) or {}).get("resets_at")) or "")] if t is not None and t > now]
    return min(ts) if ts else None


def reset_passed(row, now=None):
    """В закэшированных данных аккаунта есть сброс, который уже наступил — кэш устарел."""
    now = time.time() if now is None else now
    for k in ("five_hour", "seven_day"):
        t = _ts(((row.get(k) or {}).get("resets_at")) or "")
        if t is not None and t <= now:
            return True
    return False
