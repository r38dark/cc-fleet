"""One presentation name for Claude, independent of where its process runs."""
import re

_ROLE = r"(?:TPROD|TDEV|PROD|DEV)"
_LONG = re.compile(r"\bClaude(?:\s+на)?\s+" + _ROLE + r"\b")
_PROFILE = re.compile(r"\b" + _ROLE + r"\s+Full\b")
# These are application-facing labels, never physical routing keys (claude/dev/prod).
_HEADING = re.compile(r"\b(Профиль|Настройки|Модели|Консоль|Лимиты|аккаунт|На)\s+" + _ROLE + r"\b")
_DISPLAY_FIELDS = {"label", "name", "text", "message", "reason", "stage", "error",
                   "hint", "detail", "handoff_message", "line", "title", "limit_label"}
_CONSOLE_PATHS = {"/api/console", "/api/remote/console"}


def text(value):
    if not isinstance(value, str):
        return value
    value = _LONG.sub("Claude", value)
    value = _PROFILE.sub("Full", value)
    return _HEADING.sub(r"\1 Claude", value)


def _display_values(body, is_display=False):
    if isinstance(body, dict):
        return {key: _display_values(value, key in _DISPLAY_FIELDS) for key, value in body.items()}
    if isinstance(body, list):
        return [_display_values(item, is_display) for item in body]
    return text(body) if is_display else body


def finish(body, ctype=""):
    if isinstance(body, (bytes, bytearray)) and ctype.startswith("text/html"):
        return text(bytes(body).decode("utf-8")).encode("utf-8")
    return _display_values(body)


def install(ns):
    """Normalize generated panel and notification text. There is no naming endpoint."""
    base = ns["H"]

    class ClaudeNameHandler(base):
        def _send(self, code, body, *args, **kw):
            path = str(getattr(self, "path", "") or "").split("?", 1)[0]
            if path not in _CONSOLE_PATHS:
                ctype = args[0] if args else kw.get("ctype", "application/json")
                body = finish(body, ctype)
            return base._send(self, code, body, *args, **kw)

    ns["H"] = ClaudeNameHandler
    notify = ns.get("tg_notify")
    if notify:
        def tg_notify(message, *args, **kwargs):
            return notify(text(message), *args, **kwargs)
        ns["tg_notify"] = tg_notify
