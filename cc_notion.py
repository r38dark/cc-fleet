# Notion-агент рядом с аккаунтами Claude: показываем, подключён ли он, и как называется.
# Сетевых запросов здесь нет: состояние берётся из файла входа Claude Code (блок mcpOAuth) и config.json.
# Токены наружу не отдаём — только факты (есть вход / нет, имя агента, срок токена).
import json
import os

CREDS = lambda: os.path.expanduser("~/.claude/.credentials.json")  # cc_limits подменяет на LIVE_CREDS
CONFIG = lambda: {}  # cc_limits отдаёт сюда cfg().get("notion_agent")


def _entry():
    """Запись входа Notion из mcpOAuth; None — Notion не подключён."""
    try:
        with open(CREDS()) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    for key, val in ((doc or {}).get("mcpOAuth") or {}).items():
        if not isinstance(val, dict):
            continue
        url = str(val.get("serverUrl") or "")
        if val.get("serverName") == "notion" or "mcp.notion.com" in url or key.startswith("notion|"):
            return val
    return None


def public():
    """Что показывает карточка на странице. available=False — Notion не подключён, карточки нет."""
    e = _entry()
    if not e:
        return {"available": False}
    conf = CONFIG() or {}
    exp = e.get("expiresAt")
    try:
        exp = int(exp) // 1000 if exp else None  # в файле миллисекунды
    except (TypeError, ValueError):
        exp = None
    return {
        "available": True,
        # токен доступа живёт около суток, но Claude Code обновляет его сам по refreshToken —
        # «подключён» значит, что есть чем обновлять, а не что токен свежий
        "connected": bool(e.get("refreshToken") or e.get("accessToken")),
        "can_refresh": bool(e.get("refreshToken")),
        "expires_at": exp,
        "agent": {"name": str(conf.get("name") or "")[:80], "set": bool(conf.get("url"))},
        "role": "helper",  # reserve — когда появится резервный режим
    }
