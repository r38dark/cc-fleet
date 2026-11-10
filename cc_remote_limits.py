"""Remote quota protection and pause notifications, independent of auto handoff."""
import time

import cc_remote as R

STATE_FILE = R.BASE + "/remote_limit_guard.json"
_deployed = {}


def public():
    return R.jload(STATE_FILE, {})


def policy(ns, row, enabled):
    cfg = ns["cfg"]()
    pause = R.jload(R.BASE + "/pause_state.json", {})
    return dict(enabled=bool(enabled), threshold=cfg.get("threshold", 90), weekly_cap=cfg.get("weekly_cap", 99),
                weekly_pause=bool(cfg.get("weekly_pause")), override=bool(pause.get("override")),
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
