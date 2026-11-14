"""Remote quota protection and pause notifications, independent of auto handoff."""
import time
import threading

import cc_remote as R
import cc_avail

STATE_FILE = R.BASE + "/remote_limit_guard.json"
_deployed = {}
_policy_lock=threading.Lock()


def public():
    return R.jload(STATE_FILE, {})


def agent_limits(local, snapshot, remote, remote_pause=None, now=None):
    """Отдельные состояния Claude; те же пороги/сводка, что у гейта. Без реквизитов аккаунтов."""
    now = time.time() if now is None else now
    threshold, cap = local.get("threshold", 90), local.get("weekly_cap", 99)
    pause = local.get("pause") or {}
    result = {}
    unknown = {'claude': True, 'prod': True}
    groups = (("claude", snapshot.get("accounts") or {}, {}), ("prod", {}, remote or {}))
    for engine, accounts, members in groups:
        if engine == "claude" and local.get("stale"):
            continue
        summary = cc_avail.fleet_summary(accounts, members, threshold, cap, now=now)
        unknown[engine] = bool(not summary['accounts'] or summary['unknown'])
        if not summary["all_blocked"]:
            continue
        nearest = summary.get("nearest") or {}
        chosen_key = nearest.get("acc") or next(iter(summary["accounts"]), "")
        chosen = summary["accounts"].get(chosen_key) or {}
        held = nearest.get("held") or chosen.get("held") or ""
        week = summary["all_week_capped"] or "неделя" in held
        pct = chosen.get("wpct" if week else "pct")
        hard = all((a.get("wpct" if week else "pct") or 0) >= 100 for a in summary["accounts"].values())
        manual = engine == "claude" and local.get("level") == "manual"
        # «отключена вручную» — отдельный флаг у каждого Claude (DEV: override, PROD: override_prod)
        overridden = bool(pause.get("override_prod" if engine == "prod" else "override"))
        waiting = hard or (not overridden and not manual and (not week or local.get("weekly_pause")))
        active_row = accounts.get(local.get('active')) if engine == 'claude' else None
        can_override = not cc_avail.dead(active_row) if active_row else not hard
        result[engine] = dict(window="week" if week else "5h", pct=pct,
                              threshold=cap if week else threshold,
                              resume_at=cc_avail._ts(nearest.get("resets_at") or "") or 0,
                              waiting=bool(waiting), override=overridden,
                              manual=manual, can_override=can_override)
        # Отдельные реальные сбросы выбранного ближайшего доступного аккаунта:
        # общий resume_at может быть позднейшим из двух окон и не заменяет каждый.
        row = (accounts if engine == 'claude' else members).get(chosen_key.partition(':')[2]) or {}
        windows = []
        for key, name, limit, enabled in (('five_hour', '5h', threshold, True),
                                          ('seven_day', 'week', cap, bool(local.get('weekly_pause')))):
            w = row.get(key) or {};value = w.get('pct')
            if isinstance(value, (int, float)) and (value >= 100 or waiting and enabled and value >= limit):
                windows.append(dict(window=name, resume_at=cc_avail._ts(w.get('resets_at') or '') or 0))
        result[engine]['windows'] = windows
    # Подтверждённая пауза не пропадает при устаревшем/неполном снимке процентов.
    for engine, state, confirmed in (
        ('claude', pause, pause.get('active') and not pause.get('override')),
        ('prod', remote_pause or {}, all((remote_pause or {}).get(k) for k in ('enabled','applied','blocked'))),
    ):
        if confirmed and unknown[engine] and engine not in result:
            result[engine]=dict(window='pause',pct=None,threshold=None,resume_at=state.get('resume_at') or 0,
                                waiting=True,override=False,manual=False,can_override=False)
    return result


def policy(ns, row, enabled):
    cfg = ns["cfg"]()
    pause = R.jload(R.BASE + "/pause_state.json", {})
    return dict(enabled=bool(enabled), threshold=cfg.get("threshold", 90), weekly_cap=cfg.get("weekly_cap", 99),
                weekly_pause=bool(cfg.get("weekly_pause")), override=bool(pause.get("override_prod")),
                row={k: row[k] for k in ("five_hour", "seven_day", "ts", "error", "online") if k in row})


def tick(ns):
    import cc_remote_mode as M
    mode = M.mode()
    state = public()
    for mid, member in R.members().items():
        enabled = bool(mode.get("active") and mode.get("member") == mid)
        if not enabled and not (state.get(mid) or {}).get("enabled"):
            continue
        if M.busy():
            continue
        if mid not in _deployed:
            if not M.deploy_tools(member):
                continue
            _deployed[mid] = True
        row = R.cached().get(mid) or {}
        import json
        with _policy_lock:
            result = R.ctl(mid, "guard-config", inp=json.dumps(policy(ns, row, enabled)))
        if not result or not result.get("ok"):
            continue
        info = R.ctl(mid, "guard-status") or {}
        if enabled and info.get("running") and not info.get("applied"):
            # Only an idle, empty prompt and a verified session ID may be
            # reloaded. Busy sessions keep running until their next idle point.
            result = R.ctl(mid, "guard-reload", timeout=300) or {}
            info = R.ctl(mid, "guard-status") or {}
        if not info.get("ok"):
            continue
        previous = state.get(mid) or {}
        held = bool(enabled and info.get("applied") and info.get("ready", True) and info.get("blocked"))
        current = {k: info[k] for k in ("configured", "applied", "ready", "waiting", "reasons", "resume_at", "running") if k in info}
        current.update(enabled=enabled, blocked=held, ts=time.time(), notified_blocked=bool(previous.get("notified_blocked")))
        state[mid] = current
        # Pausing is a separate preference from percentage warnings.
        if ns["cfg"]().get("pause_notify", True):
            label = member.get("label") or mid
            if held and not current["notified_blocked"]:
                reasons = "; ".join(info.get("reasons") or [])
                delivered = ns["tg_notify"]("⏸ Claude (%s): пауза по лимитам. %s. Новые действия ждут сброса; беседа сохранена." % (label, reasons))
                current["notified_blocked"] = delivered is not False
            elif current["notified_blocked"] and not held and enabled and info.get("applied"):
                delivered = ns["tg_notify"]("▶ Claude (%s): лимит снова доступен, пауза снята. Ожидавшие действия могут продолжиться в той же беседе." % label)
                if delivered is not False:
                    current["notified_blocked"] = False
        if not enabled:
            current["notified_blocked"] = False
    R.jsave(STATE_FILE, state)


def sync_policy(ns):
    """Apply a panel toggle to an already active remote guard without waking local Claude."""
    import cc_remote_mode as M
    import json
    mode=M.mode();mid=mode.get('member')
    if not mode.get('active') or mid not in R.members():return
    with _policy_lock:
        R.ctl(mid,'guard-config',inp=json.dumps(policy(ns,R.cached().get(mid) or {},True)))
