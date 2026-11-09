# Когда аккаунт Claude снова пригоден для работы — единое правило для балансера
# (cc_limits.py), баннера паузы (pause_ctl.py) и гейта фоновых агентов (limits_gate.py).
#
# Аккаунт пригоден, если сессия ниже порога И неделя ниже недельного потолка И он не Free.
# Если нет — он станет пригоден в момент, когда сбросятся ВСЕ окна, которые его держат:
# забита только сессия → её сброс; забита только неделя → сброс недели; обе → позднейший.
# Сравнивать аккаунты по одному сбросу сессии нельзя: сессия может освободиться через
# 5 минут, а неделя держать ещё сутки, и наоборот.
import time
from datetime import datetime, timezone


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


def dead(row):
    """Аккаунт упёрся в 100% сессии или недели — работать на нём нельзя совсем."""
    return any(((row.get(k) or {}).get("pct") or 0) >= 100 for k in ("five_hour", "seven_day"))


def manual_pick(hold, name, row, now=None):
    """Ручной выбор ещё в силе: аккаунт выбрали вручную, когда его сессия была выше порога
    или неделя на потолке (state.json → manual_hold), это окно ещё не сбросилось и аккаунт
    не упёрся в 100%. Пока так — балансер с него не уводит."""
    now = time.time() if now is None else now
    hold = hold or {}
    return (bool(name) and hold.get("account") == name
            and now < float(hold.get("until") or 0) and not dead(row or {}))


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


def fleet_summary(local, remote, ses_thr, week_cap, now=None):
    """Общая сводка для интерфейса; не меняет локальные гейты и будильники."""
    now = time.time() if now is None else now
    members, candidates, unknown = {}, {}, []
    for source, accounts in (("local", local), ("remote", remote)):
        for name, row in (accounts or {}).items():
            if not isinstance(row, dict):
                continue
            key = source + ":" + name
            pct = (row.get("five_hour") or {}).get("pct")
            week = (row.get("seven_day") or {}).get("pct")
            known = not row.get("error") and (row.get("plan") == "free" or
                    (isinstance(pct, (int, float)) and isinstance(week, (int, float))))
            if source == "remote":
                try:
                    known = known and bool(row.get("online")) and 0 <= now - float(row.get("ts") or 0) <= 900
                except (ValueError, TypeError):
                    known = False
            usable, when, held = availability(row, ses_thr, week_cap, now) if known else (None, None, "unknown")
            label = str(row.get("label") or name)
            members[key] = dict(label=label, source=source, pct=pct, wpct=week,
                                known=bool(known), usable=usable, held=held)
            if known:
                candidates[key] = row
            else:
                unknown.append(key)
    nearest_account = nearest(candidates, ses_thr, week_cap, now=now)
    next_free = {}
    if nearest_account:
        timestamp, key, held = nearest_account
        next_free = dict(acc=key, label=members[key]["label"],
                         resets_at=datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), held=held)
    all_blocked = bool(members) and not unknown and all(m["usable"] is False for m in members.values())
    return dict(accounts=members, remote_count=sum(m["source"] == "remote" for m in members.values()),
                all_blocked=all_blocked, unknown=unknown, nearest=next_free,
                all_week_capped=all_blocked and all(m["held"] != "free" and m["wpct"] is not None
                                                   and m["wpct"] >= week_cap for m in members.values()))


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
