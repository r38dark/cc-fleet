"""Plugin wiring Antigravity (agy) as an independent 3rd executor in cc-fleet."""
import json
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

import cc_agy
import cc_agy_bridge
import cc_agy_console
import cc_agy_limits
import cc_agy_quota
import cc_agy_ui
import cc_cli_notice
import cc_model_notice


def _agy_bin(ns):
    try:
        configured = str(ns["cfg"]().get("agy_bin") or "").strip()
    except Exception:
        configured = ""
    return cc_agy.find_bin(configured)


def install(ns):
    base = str(ns.get("BASE") or "/opt/cc-limits")
    cc_agy.BASE = base
    cc_agy_console.BASE = base
    cc_agy_bridge.BASE = base
    cc_agy_console.BIN = lambda: _agy_bin(ns)
    cc_agy_console.WORKDIR = lambda: str(cc_agy_bridge.load().get("workdir") or "/root")
    if "_row_html" in ns:
        cc_agy_console.ROW_HTML = ns["_row_html"]

    limits = cc_agy_limits.AccountLimits(
        base, cc_agy, cc_agy_console, lambda: _agy_bin(ns), cc_agy_bridge.BRIDGE
    )
    quota = cc_agy_quota.Guard(base, limits, cc_agy_console, cc_agy_bridge.BRIDGE)
    limits.quota = quota

    cc_agy_console.QUOTA_PAUSE = limits.limit_pause
    cc_agy_console.QUOTA_ENQUEUE = cc_agy_bridge.BRIDGE.enqueue_console
    cc_agy_bridge.LIMIT_PAUSE = limits.limit_pause
    cc_agy_bridge.LIMIT_PUBLIC = limits.public
    cc_agy_bridge.LIMIT_CONFIGURE = limits.configure

    # Register Antigravity in cc_cli_notice & cc_model_notice (same mechanics as Claude & Codex)
    cc_cli_notice.NAMES["agy@local"] = ("agy", "Antigravity CLI")
    cc_cli_notice.SEND["agy"] = cc_agy_bridge.notify
    cc_model_notice.SEND["agy"] = cc_agy_bridge.notify

    def _agy_cli_view(check=False):
        st = cc_agy_console.status()
        return cc_agy.cli_status(
            check=check,
            running=st.get("running"),
            busy=st.get("busy"),
            started_version=st.get("started_version") or "",
        )

    def _agy_cli_tick(check=False):
        try:
            view = _agy_cli_view(check=check)
            cc_cli_notice.tick({"agy@local": view})
            return view
        except Exception:
            return {"ok": False}

    def _agy_updates_watcher():
        last_models_ts = 0.0
        time.sleep(25)
        while True:
            try:
                if _agy_bin(ns):
                    _agy_cli_tick(check=True)
                    now = time.time()
                    if now - last_models_ts >= 6 * 3600:
                        last_models_ts = now
                        cc_agy.models_discovery_start(_agy_bin(ns), notify_cb=cc_agy_bridge.notify)
            except Exception:
                pass
            time.sleep(1800)

    # Cross-register Telegram bot tokens so Claude, Codex, and Antigravity never collide (409)
    codex_bridge = ns.get("cc_codex_bridge")
    orig_codex_reserved = getattr(codex_bridge, "RESERVED_TOKENS", None) if codex_bridge else None

    def agy_reserved():
        tokens = set()
        if callable(orig_codex_reserved):
            try:
                tokens.update(orig_codex_reserved() or set())
            except Exception:
                pass
        if codex_bridge is not None:
            try:
                ctok = str(codex_bridge.load().get("token") or "").strip()
                if ctok:
                    tokens.add(ctok)
            except Exception:
                pass
        return tokens

    cc_agy_bridge.RESERVED_TOKENS = agy_reserved

    if codex_bridge is not None:
        def codex_reserved_with_agy():
            tokens = set()
            if callable(orig_codex_reserved):
                try:
                    tokens.update(orig_codex_reserved() or set())
                except Exception:
                    pass
            atok = str(cc_agy_bridge.load().get("token") or "").strip()
            if atok:
                tokens.add(atok)
            return tokens

        codex_bridge.RESERVED_TOKENS = codex_reserved_with_agy

    # Extend ConsoleInput with 'agy' session support
    inputs = ns.get("FLEET_INPUT")
    if inputs is not None:
        inputs.locks["agy"] = threading.Lock()
        orig_send = inputs.send
        orig_key = inputs.key

        def send_with_agy(session, text, request_id, side=False):
            if session != "agy":
                return orig_send(session, text, request_id, side=side)
            if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 48000:
                return False, "Нужно непустое сообщение размером до 48 КБ."
            if text.strip().lower() == "/stop":
                return cc_agy_bridge.BRIDGE.stop_work()
            if not inputs.locks["agy"].acquire(blocking=False):
                return False, "Предыдущий ввод в Antigravity ещё отправляется."
            try:
                if limits.limit_pause().get("active"):
                    return cc_agy_bridge.BRIDGE.enqueue_console(text.strip(), request_id)
                return cc_agy_console.send_input(text, request_id=request_id)
            finally:
                inputs.locks["agy"].release()

        def key_with_agy(session, key):
            if session != "agy":
                return orig_key(session, key)
            if key == "stop":
                return cc_agy_bridge.BRIDGE.stop_work()
            return cc_agy_console.send_key(key)

        inputs.send = send_with_agy
        inputs.key = key_with_agy

    ns["cc_agy"] = cc_agy
    ns["cc_agy_console"] = cc_agy_console
    ns["cc_agy_bridge"] = cc_agy_bridge
    ns["AGY_LIMITS"] = limits

    # Wrap HTTP handler with /api/agy/* and /api/console?s=agy
    original = ns["H"]

    class AgyHandler(original):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/console":
                q = parse_qs(parsed.query)
                if (q.get("s") or [""])[0] == "agy":
                    if not self._authed():
                        return self._send(403, {"ok": False, "message": "forbidden"})
                    if not _agy_bin(ns):
                        return self._send(200, {"ok": True, "session": "agy", "available": False, "running": False})
                    snap = cc_agy_console.snapshot(want_history=bool(q.get("history")))
                    resp = dict(cc_agy_console.status(), **snap)
                    resp["session"] = "agy"
                    return self._send(200, resp)
            if parsed.path in ("/api/agy", "/api/agy/limits", "/api/agy/bridge", "/api/agy/models", "/api/agy/models/discovery", "/api/agy/cli", "/api/agy/install", "/api/agy/login"):
                if not self._authed():
                    return self._send(403, {"ok": False, "message": "forbidden"})
                if parsed.path == "/api/agy":
                    force = bool(parse_qs(parsed.query).get("refresh"))
                    return self._send(200, limits.snapshot(force=force))
                if parsed.path == "/api/agy/limits":
                    limits.refresh()
                    return self._send(200, limits.public())
                if parsed.path == "/api/agy/bridge":
                    return self._send(
                        200,
                        {"ok": True, "available": bool(_agy_bin(ns)), "bridge": cc_agy_bridge.public()},
                    )
                if parsed.path == "/api/agy/cli":
                    chk = bool(parse_qs(parsed.query).get("check"))
                    return self._send(200, _agy_cli_tick(check=chk))
                if parsed.path == "/api/agy/models/discovery":
                    return self._send(200, cc_agy.models_discovery_status())
                if parsed.path == "/api/agy/install":
                    return self._send(200, cc_agy.install_status())
                if parsed.path == "/api/agy/login":
                    return self._send(200, cc_agy.login_status())
                models = cc_agy.gemini_models_only(cc_agy.fetch_models(_agy_bin(ns), force=False))
                return self._send(200, {"ok": True, "models": models})
            return original.do_GET(self)

        def do_POST(self):
            path = urlparse(self.path).path
            if not path.startswith("/api/agy/"):
                return original.do_POST(self)
            if not self._authed():
                return self._send(403, {"ok": False, "message": "forbidden"})
            try:
                length = int(self.headers.get("Content-Length") or "0")
                if length < 0 or length > 65536:
                    return self._send(413, {"ok": False, "message": "Слишком большой запрос."})
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("object required")
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"ok": False, "message": "Неверный JSON."})

            try:
                if path == "/api/agy/limits/config":
                    ok, msg = limits.configure(body)
                    return self._send(200, {"ok": ok, "message": msg, "state": limits.public()})
                if path == "/api/agy/prefs":
                    before_meta = cc_agy.load_meta()
                    before_info = {
                        "model": before_meta.get("model") or cc_agy.cli_default_model(),
                        "effort": before_meta.get("effort") or "",
                    }
                    ok, msg = cc_agy.set_prefs(
                        model=body.get("model"),
                        effort=body.get("effort"),
                        sub_until=body.get("sub_until"),
                        label=body.get("label"),
                    )
                    pending = False
                    if ok and ("model" in body or "effort" in body):
                        after_meta = cc_agy.load_meta()
                        after_info = {
                            "model": after_meta.get("model") or cc_agy.cli_default_model(),
                            "effort": after_meta.get("effort") or "",
                        }
                        cc_model_notice.changed("Antigravity", "agy", before_info, after_info)
                        if cc_agy_console._pid():
                            ok, msg, pending = cc_agy_console.request_settings(
                                {"model": after_meta.get("model", ""), "effort": after_meta.get("effort", "")}
                            )
                    limits.refresh(force=False)
                    return self._send(200, {"ok": ok, "message": msg, "pending": pending})
                if path == "/api/agy/console/start":
                    ok, msg = cc_agy_console.start()
                    return self._send(200, dict(cc_agy_console.status(), ok=ok, message=msg))
                if path == "/api/agy/console/stop":
                    ok, msg = cc_agy_console.stop()
                    return self._send(200, dict(cc_agy_console.status(), ok=ok, message=msg))
                if path == "/api/agy/console/restart":
                    ok, msg = cc_agy_console.restart()
                    return self._send(200, dict(cc_agy_console.status(), ok=ok, message=msg))
                if path == "/api/agy/console/cmd":
                    cmd = str(body.get("cmd") or "").strip().lower()
                    if cmd == "compact":
                        ok, msg = cc_agy_console.compact()
                    elif cmd == "new":
                        ok, msg = cc_agy_console.new_session()
                    else:
                        return self._send(400, {"ok": False, "message": "Неизвестная команда консоли."})
                    return self._send(200, dict(cc_agy_console.status(), ok=ok, message=msg))
                if path == "/api/agy/bridge/save":
                    ok, msg = cc_agy_bridge.save_settings(body)
                    return self._send(200, {"ok": ok, "message": msg, "bridge": cc_agy_bridge.public()})
                if path == "/api/agy/bridge/token":
                    ok, msg = cc_agy_bridge.set_token(body.get("token"))
                    return self._send(200, {"ok": ok, "message": msg, "bridge": cc_agy_bridge.public()})
                if path == "/api/agy/bridge/token/clear":
                    ok, msg = cc_agy_bridge.clear_token()
                    return self._send(200, {"ok": ok, "message": msg, "bridge": cc_agy_bridge.public()})
                if path == "/api/agy/models/check":
                    res = cc_agy.models_discovery_start(_agy_bin(ns), notify_cb=cc_agy_bridge.notify)
                    return self._send(200, res)
                if path == "/api/agy/cli/update":
                    ok, msg = cc_agy.cli_update(
                        target=body.get("version") or "latest",
                        on_done=lambda: _agy_cli_tick(check=False),
                    )
                    return self._send(200, dict(_agy_cli_view(check=False), ok=ok, message=msg))
                if path == "/api/agy/cli/restart":
                    ok, msg = cc_agy_console.restart()
                    return self._send(200, dict(_agy_cli_view(check=False), ok=ok, message=msg))
                if path == "/api/agy/install/start":
                    ok, msg = cc_agy.install_start()
                    return self._send(200, dict(cc_agy.install_status(), ok=ok, message=msg))
                if path == "/api/agy/install/cancel":
                    ok, msg = cc_agy.install_cancel()
                    return self._send(200, dict(cc_agy.install_status(), ok=ok, message=msg))
                if path == "/api/agy/login/start":
                    ok, msg = cc_agy.login_start()
                    return self._send(200, dict(cc_agy.login_status(), ok=ok, message=msg))
                if path == "/api/agy/login/submit":
                    ok, msg = cc_agy.login_submit(body.get("code"))
                    return self._send(200, dict(cc_agy.login_status(), ok=ok, message=msg))
                if path == "/api/agy/login/cancel":
                    ok, msg = cc_agy.login_cancel()
                    return self._send(200, dict(cc_agy.login_status(), ok=ok, message=msg))
                if path == "/api/agy/bootstrap":
                    wd = cc_agy_bridge.load().get("workdir") or cc_agy_console.WORKDIR()
                    ok, changed = cc_agy.ensure_bootstrap_config(workdir=wd, force_full_access=True)
                    msg = (
                        "Полный доступ, пропуск мастера и стиль ответов применены (" + ", ".join(changed) + ")."
                        if changed
                        else "Все настройки полного доступа, пропуска мастера и стиля уже применены."
                    )
                    return self._send(200, {"ok": ok, "changed": changed, "message": msg})
                if path == "/api/agy/console/key":
                    key = str(body.get("key") or "").strip().lower()
                    ok, msg = cc_agy_console.send_key(key)
                    return self._send(200, {"ok": ok, "message": msg})
                if path == "/api/agy/uninstall":
                    try:
                        cc_agy_console.stop()
                    except Exception:
                        pass
                    try:
                        cc_agy_bridge.save_settings({"enabled": False})
                    except Exception:
                        pass
                    ok, msg = cc_agy.uninstall()
                    try:
                        limits.accounts = []
                        limits.refresh(force=False)
                    except Exception:
                        pass
                    return self._send(200, {"ok": ok, "message": msg})
                return self._send(404, {"ok": False, "message": "unknown agy route"})
            except Exception as exc:
                return self._send(500, {"ok": False, "message": "Ошибка Antigravity: " + type(exc).__name__})

    ns["H"] = AgyHandler
    ns["PAGE"] = cc_agy_ui.inject(ns["PAGE"])

    if ns.get("__name__") == "__main__":
        limits.start()
        cc_agy_bridge.BRIDGE.sync()
        threading.Thread(target=_agy_updates_watcher, daemon=True, name="agy-updates-watch").start()
