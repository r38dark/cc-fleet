"""Лимиты, пауза по порогам (5ч / неделя) и override на последние проценты для Antigravity (agy)."""
import datetime
import math
import os
import threading
import time
from pathlib import Path

WIN_NAMES = {300: "5 ч", 10080: "неделя"}
BAD = ("error", "stale", "login_required", "lapsed", "loading")


def _iso_ts(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def real_limit(account):
    """Настоящий 100% лимит исчерпан -> (bool, resume_ts or None, window_mins)."""
    wins = [w for w in (account.get("windows") or []) if w.get("pct") is not None]
    full = [w for w in wins if float(w["pct"]) >= 100.0]
    if not full and (account.get("reached") or account.get("usage_allowed") is False):
        full = [min(wins, key=lambda w: w.get("mins") or 0)] if wins else [{}]
    if not full:
        return False, None, []
    ts = [t for t in (_iso_ts(w.get("resets_at")) for w in full) if t]
    return True, (max(ts) if ts else None), [w.get("mins") for w in full if w.get("mins")]


def policy_limit(account, threshold=90, weekly_cap=99, override=False, now=None, grace=120):
    """Окна, удерживающие Antigravity по порогам; override никогда не обходит 100%."""
    now = time.time() if now is None else now
    held = []
    expired = False
    for w in account.get("windows") or []:
        m = w.get("mins")
        pct = w.get("pct")
        cap = 100 if override else threshold if m == 300 else weekly_cap if m == 10080 else 100
        if not isinstance(pct, (int, float)) or not math.isfinite(pct) or pct < cap:
            continue
        until = _iso_ts(w.get("resets_at"))
        if until is not None and now > until + grace:
            expired = True
            continue
        held.append((w, until))
    reported = bool(account.get("reached") or account.get("usage_allowed") is False)
    return held, reported, expired


def limit_pause_state(accounts, active, now=None, grace=120, threshold=90, weekly_cap=99, override=False):
    now = time.time() if now is None else now
    cur = next((a for a in accounts if a.get("slot") == active), None)
    if not cur or any(cur.get(k) for k in BAD) or not cur.get("ts") or now - cur["ts"] > 240:
        return {"active": False, "unknown": True}
    held, reported, expired = policy_limit(cur, threshold, weekly_cap, override, now, grace)
    if not held and not reported:
        return {"active": False, "expired": expired, "override": override}
    mins = sorted({w["mins"] for w, _ in held if isinstance(w.get("mins"), int) and w["mins"] > 0})
    until = max(t for _, t in held) if held and all(t is not None for _, t in held) else None
    lab = lambda a: a.get("label") or a.get("email") or a.get("slot") or "Antigravity"
    pct = lambda a, m: next((w.get("pct") for w in a.get("windows") or [] if w.get("mins") == m), None)
    hard = reported or any(float(w.get("pct") or 0) >= 100.0 for w, _ in held)
    return {
        "active": True,
        "paused": True,
        "slot": active,
        "label": lab(cur),
        "windows": mins,
        "window_names": [WIN_NAMES.get(m, f"{round(m / 60)} ч") for m in mins],
        "resume_at": until,
        "resets": {str(w["mins"]): u for w, u in held if w.get("mins") and u is not None},
        "percentages": {str(w["mins"]): w.get("pct") for w, _ in held if w.get("mins")},
        "policy": not hard,
        "hard": bool(hard),
        "override": override,
        "can_override": not hard,
        "threshold": threshold,
        "weekly_cap": weekly_cap,
        "accounts": [{"label": lab(cur), "active": True, "ses": pct(cur, 300), "week": pct(cur, 10080)}],
    }


def limit_notice_state(accounts, active, pause=None, now=None, grace=120):
    now = time.time() if now is None else now
    cur = next((a for a in accounts if a.get("slot") == active), None)
    if not cur or any(cur.get(k) for k in BAD) or not cur.get("ts") or now - cur["ts"] > 240:
        return {"active": False}
    full = []
    expired = False
    for w in cur.get("windows") or []:
        try:
            pct = float(w.get("pct"))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(pct) or pct < 100.0:
            continue
        until = _iso_ts(w.get("resets_at"))
        if until is not None and now > until + grace:
            expired = True
            continue
        full.append((w, until))
    reported = bool(cur.get("reached") or cur.get("usage_allowed") is False)
    if not full and not reported:
        return {"active": False, "expired": expired}
    mins = sorted({w["mins"] for w, _ in full if isinstance(w.get("mins"), int) and w["mins"] > 0})
    until = max(t for _, t in full) if full and all(t is not None for _, t in full) else None
    resets = {str(w["mins"]): t for w, t in full if isinstance(w.get("mins"), int) and w["mins"] > 0 and t is not None}
    lab = lambda a: a.get("label") or a.get("email") or a.get("slot") or "Antigravity"
    pct = lambda m: next((w.get("pct") for w in cur.get("windows") or [] if w.get("mins") == m), None)
    notice = dict(
        active=True,
        paused=bool((pause or {}).get("active")),
        slot=active,
        label=lab(cur),
        windows=mins,
        resets=resets,
        window_names=[WIN_NAMES.get(m, f"{round(m / 60)} ч") for m in mins],
        resume_at=until,
        accounts=[dict(label=lab(cur), active=True, ses=pct(300), week=pct(10080))],
    )
    if notice["paused"] and pause:
        if "accounts" in pause:
            notice["accounts"] = pause["accounts"]
        if until is not None and pause.get("resume_at") is not None:
            notice["resume_at"] = pause["resume_at"]
    return notice


class AccountLimits:
    """Manages Antigravity quota thresholds, soft pause override, and 5s tick loop."""

    def __init__(self, base, agy, console, binary, bridge=None):
        self.path = Path(base) / "agy_limits.json"
        self.agy = agy
        self.console = console
        self.binary = binary
        self.bridge = bridge
        self.quota = None
        self.lock = threading.RLock()
        self.accounts = []
        self.updated = 0.0
        self.refreshing = False
        self.started = False
        self.stop_event = threading.Event()
        self.last_error = ""
        self.message = "Проверяем лимиты Antigravity…"
        self.state = self.agy.jload(str(self.path), {}) or {}
        self.state.setdefault("threshold", 90)
        self.state.setdefault("weekly_cap", 99)
        self.state.setdefault("pause_override", False)
        self.state.setdefault("override_until", 0)

    def active(self):
        b = self.binary() if callable(self.binary) else self.binary
        slots = self.agy.profile_slots(b)
        return slots[0] if slots else ""

    def save(self):
        self.agy.jsave(str(self.path), self.state, mode=0o600)

    def configure(self, body):
        with self.lock:
            changed = dict(self.state)
            if "pause_override" in body:
                value = body["pause_override"]
                if not isinstance(value, bool):
                    return False, "Отключение паузы должно быть включено или выключено."
                cur = next((a for a in self.accounts if a.get("slot") == self.active()), {})
                hard, _, _ = real_limit(cur)
                if value and (
                    hard
                    or not cur
                    or any(cur.get(k) for k in BAD)
                    or not cur.get("ts")
                    or time.time() - cur["ts"] > 240
                ):
                    return False, "Настоящий лимит 100% уже исчерпан или нет свежих данных. Паузу нельзя отключить."
                changed.update(pause_override=value, override_slot=self.active() if value else "", override_until=0)
                if value:
                    wins, _, _ = policy_limit(cur, changed["threshold"], changed["weekly_cap"])
                    changed["override_until"] = max((u for _, u in wins if u), default=0)
            for key in ("threshold", "weekly_cap"):
                if key in body:
                    value = body[key]
                    if isinstance(value, bool) or not isinstance(value, int) or not 50 <= value <= 100:
                        return False, "Порог должен быть целым числом от 50 до 100."
                    changed[key] = value
            self.state = changed
            self.save()
        if self.quota is not None:
            self.quota.tick()
        return True, "Настройки лимитов Antigravity сохранены."

    def refresh(self, force=False):
        with self.lock:
            if self.refreshing or (not force and (time.time() - self.updated) < 90.0):
                return
            self.refreshing = True

        def work():
            try:
                b = self.binary() if callable(self.binary) else self.binary
                rows = self.agy.get_accounts(b, force=force) if b else []
                with self.lock:
                    self.accounts = rows
                    self.updated = time.time()
                    self.last_error = ""
                    self.message = ""
            except Exception as exc:
                self.last_error = "Не удалось обновить лимиты Antigravity: " + type(exc).__name__
            finally:
                with self.lock:
                    self.refreshing = False

        threading.Thread(target=work, name="agy-limits-snapshot", daemon=True).start()

    def snapshot(self, force=False):
        self.refresh(force)
        b = self.binary() if callable(self.binary) else self.binary
        with self.lock:
            rows = [dict(row) for row in self.accounts]
            loading = self.refreshing
        if not rows and b:
            meta = self.agy.load_meta()
            rows = [dict(meta, slot=self.agy.SLOT, windows=[], models=[], loading=True)]
        runtime = {"running": False}
        if self.console and self.console._pid():
            meta = self.console._meta()
            settings = self.console.active_settings()
            pending = meta.get("pending_settings") or {}
            runtime = dict(
                running=True,
                slot=self.agy.SLOT,
                conv_id=meta.get("conv_id") or "",
                model=settings.get("model") or self.agy.cli_default_model(),
                effort=settings.get("effort") or "",
                pending={k: pending[k] for k in ("model", "effort") if k in pending} or None,
            )
        ctx = self.agy.get_context_stats(runtime.get("conv_id") or "")
        return {
            "ok": True,
            "available": bool(b),
            "accounts": rows,
            "loading": loading,
            "ts": self.updated,
            "runtime": runtime,
            "context": ctx,
        }

    def limit_pause(self, now=None):
        active = self.active()
        if not active:
            return {"active": False, "disconnected": True}
        with self.lock:
            rows = [dict(a) for a in self.accounts]
            th, cap = self.state["threshold"], self.state["weekly_cap"]
            override = bool(self.state.get("pause_override"))
            if override:
                cur = next((a for a in rows if a.get("slot") == active), {})
                wins, reported, _ = policy_limit(cur, th, cap, now=now)
                now_ts = time.time() if now is None else now
                expired_override = bool(
                    self.state.get("override_until") and now_ts > self.state["override_until"] + 120
                )
                if (
                    self.state.get("override_slot") != active
                    or expired_override
                    or (cur and not any(cur.get(k) for k in BAD) and not wins and not reported)
                ):
                    self.state.update(pause_override=False, override_slot="", override_until=0)
                    self.save()
                    override = False
        value = limit_pause_state(rows, active, now, threshold=th, weekly_cap=cap, override=override)
        return self.quota.fallback(value, override) if self.quota and value.get("unknown") else value

    def limit_notice(self, now=None):
        active = self.active()
        if not active:
            return {"active": False}
        with self.lock:
            rows = [dict(a) for a in self.accounts if a.get("slot") == active]
            th, cap = self.state["threshold"], self.state["weekly_cap"]
            override = bool(self.state.get("pause_override"))
        pause = self.limit_pause(now)
        notice = limit_notice_state(rows, active, pause, now)
        if notice["active"]:
            return dict(notice, hard=True, override=override, can_override=False)
        if pause.get("active"):
            return dict(pause, paused=True)
        soft = limit_pause_state(rows, active, now, threshold=th, weekly_cap=cap, override=False)
        if soft.get("active"):
            return dict(soft, paused=bool(pause.get("active")), override=override)
        return notice

    def public(self):
        active = self.active()
        settings = self.console.active_settings() if (self.console and self.console._pid()) else {}
        meta = self.console._meta() if self.console else {}
        pending = meta.get("pending_settings") or {}
        with self.lock:
            return {
                "ok": True,
                "active": active,
                "threshold": self.state["threshold"],
                "weekly_cap": self.state["weekly_cap"],
                "pause_override": bool(self.state.get("pause_override")),
                "message": self.message,
                "last_error": self.last_error,
                "updated": self.updated,
                "model": settings.get("model") or self.agy.cli_default_model(),
                "effort": settings.get("effort") or "",
                "pending_model": pending.get("model"),
                "limit_pause": self.limit_pause(),
                "limit_notice": self.limit_notice(),
                "quota": self.quota.public() if self.quota else {},
            }

    def tick(self):
        self.refresh()
        if self.quota is not None:
            self.quota.tick()
        if self.console and not self.console.busy() and not self.limit_pause().get("active"):
            self.console.apply_plan()

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True

        def loop():
            try:
                self.refresh(force=False)
            except Exception:
                pass
            while not self.stop_event.wait(5):
                try:
                    self.tick()
                except Exception as exc:
                    self.last_error = "Ошибка проверки лимитов Antigravity: " + type(exc).__name__

        threading.Thread(target=loop, daemon=True, name="agy-limits").start()
