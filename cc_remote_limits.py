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
    """Quota state for the single connected Claude, without account identifiers."""
    now = time.time() if now is None else now
    remote = remote or {}
    engine = "prod" if remote or local.get("remote") else "claude"
    pause = local.get("pause") or {}
    state = (remote_pause or {}) if engine == "prod" else pause
    threshold, cap = local.get("threshold", 90), local.get("weekly_cap", 99)
    if engine == "prod":
        row = next(iter(remote.values()), {})
        try:
            fresh = bool(row.get("online")) and 0 <= now - float(row.get("ts") or 0) <= 900
        except (ValueError, TypeError):
            fresh = False
        confirmed = all(state.get(k) for k in ("enabled", "applied", "blocked"))
    else:
        row = (snapshot.get("accounts") or {}).get(snapshot.get("active") or local.get("active"), {})
        fresh = not local.get("stale")
        confirmed = bool(state.get("active") and not state.get("override"))

    session = (row.get("five_hour") or {}).get("pct")
    week_pct = (row.get("seven_day") or {}).get("pct")
    known = fresh and not row.get("error") and all(isinstance(v, (float, int)) for v in (session, week_pct))
    if not known:
        return {engine: dict(window="pause", pct=None, threshold=None, resume_at=state.get("resume_at") or 0,
                             waiting=True, override=False, can_override=False)} if confirmed else {}
    available, until, held = cc_avail.availability(row, threshold, cap, now)
    if available or row.get("plan") == "free":
        return {}
    weekly_pause = bool(local.get("weekly_pause"))
    week = "неделя" in held
    if session >= threshold and week_pct < 100 and not weekly_pause:
        week = False
        _, until, _ = cc_avail.availability(row, threshold, 100, now)
    hard = cc_avail.dead(row)
    overridden = bool(pause.get("override_prod" if engine == "prod" else "override"))
    waiting = hard or (not overridden and (not week or weekly_pause))
    windows = []
    for key, label, limit, enabled in (("five_hour", "5h", threshold, True), ("seven_day", "week", cap, weekly_pause)):
        window = row.get(key) or {}
        value = window.get("pct")
        if value >= 100 or waiting and enabled and value >= limit:
            windows.append(dict(window=label, resume_at=cc_avail._ts(window.get("resets_at") or "") or 0))
    return {engine: dict(window="week" if week else "5h", pct=week_pct if week else session,
                         threshold=cap if week else threshold, resume_at=until or 0,
                         waiting=waiting, override=overridden, can_override=not hard, windows=windows)}


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
