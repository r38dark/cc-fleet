# Notion-агент рядом с аккаунтами Claude: показываем, подключён ли он, и как называется.
# Сетевых запросов здесь нет: состояние берётся из файла входа Claude Code (блок mcpOAuth) и config.json.
# Токены наружу не отдаём — только факты (есть вход / нет, имя агента, срок токена).
import json
import os

CREDS = lambda: os.path.expanduser("~/.claude/.credentials.json")  # cc_limits подменяет на LIVE_CREDS
CONFIG = lambda: {}  # cc_limits отдаёт сюда cfg().get("notion_agent")

# [notion-ai] Резерв (Claude недоступен → Codex + Notion-агент) убран целиком: нет сторожа, галочек, паузы
# и служебного профиля. Остались: признак подключения Notion, имя/ссылка агента и расчёт «лимиты Claude кончились»
# (им пользуются профили и агент Notion AI).
SOLO_PROFILE = lambda: False  # cc_limits: самостоятельный профиль Codex Full


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


def public(lv=None):
    """Что показывает карточка на странице. available=False — Notion не подключён, карточки нет.
    lv — уже посчитанное состояние пауз (иначе считаем здесь)."""
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
        "role": "helper",
    }


def save(conf, body):
    """Новые настройки агента из окна ⚙ блока Notion. Возвращает (ok, новый_conf, ключ_ошибки).
    Пустая ссылка в запросе = оставить прежнюю; стереть можно только явным clear_url.
    Ссылка агента — agent://…, её не показываем после сохранения (см. public())."""
    new = dict(conf or {})
    new.pop("enabled", None)  # ключ старого переключателя «включить/выключить агента»: его больше нет, из конфига убираем
    if "name" in body:
        name = str(body["name"] or "").strip()
        if len(name) > 80 or any(ord(c) < 32 for c in name):
            return False, conf, "name"
        if name:
            new["name"] = name
        else:
            new.pop("name", None)
    new.pop("reserve", None)  # [notion-ai] галочки резерва из старых настроек убираем: резерва больше нет
    if "reserve" in body:
        return False, conf, "reserve"
    if body.get("clear_url") is True:
        new.pop("url", None)
    elif str(body.get("url") or "").strip():
        url = str(body["url"]).strip()
        if not url.startswith("agent://") or len(url) > 300 or any(c.isspace() or ord(c) < 32 for c in url):
            return False, conf, "url"
        new["url"] = url
    return True, new, ""


def claude_status(lv):
    """down — лимиты всех аккаунтов кончились и Claude стоит на паузе; up — работает; unknown — снимку не верим.
    «Кончились» — ровно то, что ставит паузу (pause_ctl.level_state): hard (сессии) или week (недельный потолок,
    если пауза по неделе включена). Не считаем: ручной выбор аккаунта, отключённую вручную паузу, старый снимок."""
    if not isinstance(lv, dict) or lv.get("ok") is False or lv.get("stale") or "level" not in lv:
        return "unknown"
    if (lv.get("pause") or {}).get("override") or lv.get("manual"):
        return "up"
    return "down" if lv.get("level") in ("hard", "week") else "up"


def active():
    """[notion-ai] Резерва нет — всегда выключен (оставлено для старых вызовов)."""
    return False


def tick():
    """[notion-ai] Сторожа резерва нет; cc_profiles подменяет tick своим тактом профилей."""
    return None


def codex_args():
    """Ключи `-c` с инструментами Notion-агента для Codex. [notion-ai] Резерв убран — Codex Notion не видит."""
    return []


def codex_note(conf=None):
    """Строка в начало сообщений Codex: только для самостоятельного профиля Codex Full."""
    if SOLO_PROFILE():
        import cc_codex_bridge
        return "[Профиль Codex Full: работаешь самостоятельно. " + cc_codex_bridge.team_note("Claude и Notion-агент не используются.") + "]"
    return ""


def start():
    """[notion-ai] Сторожа резерва больше нет; cc_profiles подменяет start запуском такта профилей."""
    return None
