# Notion-агент рядом с аккаунтами Claude: показываем, подключён ли он, и как называется.
# Сетевых запросов здесь нет: состояние берётся из файла входа Claude Code (блок mcpOAuth) и config.json.
# Токены наружу не отдаём — только факты (есть вход / нет, имя агента, срок токена).
import json
import os
import threading
import time
from datetime import datetime

CREDS = lambda: os.path.expanduser("~/.claude/.credentials.json")  # cc_limits подменяет на LIVE_CREDS
CONFIG = lambda: {}  # cc_limits отдаёт сюда cfg().get("notion_agent")

# --- резерв: Claude недоступен (лимиты всех аккаунтов кончились) → работает Codex, а к Notion-агенту он ходит сам
BASE = "/opt/cc-limits"  # cc_limits подставляет свой каталог данных
LEVEL = lambda: {}  # cc_limits: pause_ctl.level_state() — тот же расчёт, что у баннера паузы
NOTIFY = lambda text: None  # cc_limits: сообщение человеку в телеграм
EMERGENCY = None  # cc_limits: cc_codex_emergency (включить/выключить вместе с резервом)
NOW = time.time  # в тестах подменяется
HOLD = 120  # сколько секунд «лимиты кончились / снова есть» должно держаться, прежде чем резерв включится или выключится
TICK = 30  # как часто сторож сверяет состояние, секунд
RESERVE_KEYS = ("manual", "auto", "auto_emergency")
PAUSE = lambda on: None  # cc_limits: резерв включён вручную → Claude на паузу (True) / снять паузу (False)
PROFILE = lambda active, flipped: None  # cc_limits: профиль Codex следует за резервом (cc_codex_bridge.reserve_profile)
APPLY = lambda: None  # cc_limits: перезапуск консоли Codex, чтобы она подхватила (или потеряла) инструменты агента
MCP_URL = "https://mcp.notion.com/mcp"  # тот же адрес, что в инструкции подключения для Claude Code
# Codex видит ровно эти четыре инструмента Notion (остальные не показываются ему вовсе) и вызывает их без вопросов:
# спросить некого, а без этого режим «никогда не спрашивать» отклоняет любой вызов MCP.
CODEX_TOOLS = ("notion-search-agents", "notion-spawn-session", "notion-wait-session", "notion-send-message-to-session")
_lock = threading.RLock()
_run = threading.Lock()  # весь такт целиком: быстрые щелчки не перемешивают побочные действия (пауза, профиль, перезапуск консоли)
_watch = {"t": None}


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
        "enabled": conf.get("enabled") is not False,
        "role": "reserve" if _st().get("active") else "helper",
        "reserve": reserve_public(conf, lv),
    }


def save(conf, body):
    """Новые настройки агента из окна ⚙ блока Notion. Возвращает (ok, новый_conf, ключ_ошибки).
    Пустая ссылка в запросе = оставить прежнюю; стереть можно только явным clear_url.
    Ссылка агента — agent://…, её не показываем после сохранения (см. public())."""
    new = dict(conf or {})
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            return False, conf, "enabled"
        new["enabled"] = body["enabled"]
    if "name" in body:
        name = str(body["name"] or "").strip()
        if len(name) > 80 or any(ord(c) < 32 for c in name):
            return False, conf, "name"
        if name:
            new["name"] = name
        else:
            new.pop("name", None)
    if "reserve" in body:
        raw = body["reserve"]
        if not isinstance(raw, dict) or any(k not in RESERVE_KEYS or not isinstance(v, bool) for k, v in raw.items()):
            return False, conf, "reserve"
        res = dict(new.get("reserve") or {})
        res.update(raw)
        new["reserve"] = res
    # выключили блок — ручная галочка резерва снимается сама: включил обратно — Claude работает,
    # резерв «вручную» включается отдельным действием (авто-галочка остаётся: она про лимиты, а не про человека)
    if body.get("enabled") is False and (new.get("reserve") or {}).get("manual") is True:
        new["reserve"] = dict(new["reserve"], manual=False)
    if body.get("clear_url") is True:
        new.pop("url", None)
    elif str(body.get("url") or "").strip():
        url = str(body["url"]).strip()
        if not url.startswith("agent://") or len(url) > 300 or any(c.isspace() or ord(c) < 32 for c in url):
            return False, conf, "url"
        new["url"] = url
    return True, new, ""


# ---------------------------------------------------------------- резерв
def reserve_conf(conf):
    """Три галочки резерва (по умолчанию все выключены): manual — «работать только с агентом»,
    auto — включаться само, когда лимиты всех аккаунтов Claude кончились, auto_emergency — и включать
    вместе с этим аварийный режим Codex."""
    raw = (conf or {}).get("reserve")
    raw = raw if isinstance(raw, dict) else {}
    return {k: raw.get(k) is True for k in RESERVE_KEYS}


def claude_status(lv):
    """down — лимиты всех аккаунтов кончились и Claude стоит на паузе; up — работает; unknown — снимку не верим.
    «Кончились» — ровно то, что ставит паузу (pause_ctl.level_state): hard (сессии) или week (недельный потолок,
    если пауза по неделе включена). Не считаем: ручной выбор аккаунта, отключённую вручную паузу, старый снимок."""
    if not isinstance(lv, dict) or lv.get("ok") is False or lv.get("stale") or "level" not in lv:
        return "unknown"
    if (lv.get("pause") or {}).get("override") or lv.get("manual"):
        return "up"
    return "down" if lv.get("level") in ("hard", "week") else "up"


def _level():
    try:
        return LEVEL()
    except Exception:
        return {"ok": False}


def _ready(conf):
    """Резерв возможен, когда агент подключён, включён и ссылка задана."""
    return bool(_entry()) and (conf or {}).get("enabled") is not False and bool((conf or {}).get("url"))


def _path():
    return os.path.join(BASE, "notion_reserve.json")


def _st():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _st_save(st):
    tmp = _path() + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, _path())


def active():
    """Резерв сейчас включён (вручную или само)."""
    return bool(_st().get("active"))


def _clock(iso):
    """ISO-время сброса → «чч:мм» по часам сервера; не разобралось — пусто."""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def reserve_public(conf, lv=None):
    r = reserve_conf(conf)
    st = _st()
    lv = _level() if lv is None else lv
    out = dict(r, active=bool(st.get("active")), paused=bool(st.get("pause")), why=st.get("why") if st.get("active") else "",
               since=st.get("since") if st.get("active") else None, claude=claude_status(lv),
               ready=_ready(conf), reset=_clock(((lv or {}).get("nearest") or {}).get("resets_at")))
    emg = EMERGENCY
    if emg is not None:
        try:
            out["emergency"] = {"configured": bool((emg.CONFIG() or {}).get("project")), "active": bool(emg.active()),
                                "by_reserve": bool(st.get("emg"))}
        except Exception:
            out["emergency"] = {"configured": False, "active": False, "by_reserve": False}
    return out


def _msg_on(conf, lv, emg_line):
    name = str((conf or {}).get("name") or "").strip()
    reset = _clock(((lv or {}).get("nearest") or {}).get("resets_at"))
    line = str((lv or {}).get("line") or "")
    week = (lv or {}).get("level") == "week"
    head = "🔴 Лимиты всех аккаунтов Claude кончились" + (" (недельный потолок)" if week else "") + (f": {line}" if line else "") + "."
    return "\n".join([
        head + (f" Claude на паузе, ближайший сброс в {reset}." if reset else " Claude на паузе."),
        "🔁 Включён РЕЗЕРВ: работает Codex + Notion-агент" + (f" «{name}»" if name else "") + ".",
        emg_line,
        "🔧 Как работаем: ты ставишь задачу Codex → он отправляет агенту нужный текст → агент возвращает результат → "
        "Codex внедряет и проверяет → каждое изменение ждёт твоё «да».",
        "⏱ Выключится само, когда Claude снова сможет работать."])


def tick():
    """Раз в TICK секунд и сразу после любого сохранения настроек: понять, кончились ли лимиты;
    включить или выключить резерв и (если разрешено) аварийный режим.
    Такты идут строго по одному: следующий ждёт конца предыдущего и читает уже свежие настройки."""
    with _run:
        _tick()


def _tick():
    """Один такт. Человеку уходит ОДНО сообщение при начале случая «лимиты кончились» и одно при его конце.
    Состояние переживает перезапуск панели."""
    with _lock:
        conf = CONFIG() or {}
        r = reserve_conf(conf)
        st = _st()
        was_active = bool(st.get("active"))
        now = NOW()
        lv = _level()
        stt = claude_status(lv)
        if stt == "down":  # состояние должно продержаться HOLD секунд: одиночный сбой снимка резерв не включает
            st["up_since"] = None
            st["down_since"] = st.get("down_since") or now
            if now - st["down_since"] >= HOLD:
                st["down"] = True
        elif stt == "up":
            st["down_since"] = None
            st["up_since"] = st.get("up_since") or now
            if now - st["up_since"] >= HOLD and st.get("down"):
                st["down"] = False
                st["emg_skip"] = False  # новый случай — аварийный режим можно пробовать заново
        # unknown: таймеры и состояние не трогаем — не включаем и не выключаем по непроверенным данным
        ready = _ready(conf)
        down = bool(st.get("down"))
        want = ready and (r["manual"] or (r["auto"] and down))
        want_pause = bool(ready and r["manual"])  # вручную включённый резерв отключает Claude; «лимиты кончились» его и так остановили
        pause_flip = want_pause != bool(st.get("pause"))
        st["pause"] = want_pause
        auto_case = ready and r["auto"] and down  # резерв и аварийный режим включает «лимиты кончились», а не человек
        want_emg = auto_case and r["auto_emergency"]
        emg = EMERGENCY
        emg_line = ""
        emg_off = False
        if want:
            if not st.get("active"):
                st.update(active=True, since=now)
            st["why"] = "manual" if r["manual"] else "claude_down"
        elif st.get("active"):
            st.update(active=False, ended=now)
        if emg is not None:
            if st.get("emg") and not emg.active():  # режим выключили руками или вышел срок — в этом же случае назад не включаем
                st.update(emg=False, emg_skip=True)
            if want_emg and not st.get("emg") and not st.get("emg_skip") and not emg.active():
                ok, msg = emg.on("", "ru", auto="лимиты Claude кончились")
                if ok:
                    st["emg"] = True
                    emg_line = "🆘 Аварийный режим ВКЛЮЧЁН: Codex получил полный доступ к проекту."
                else:
                    st["emg_skip"] = True  # не долбим каждые TICK секунд
                    emg_line = "⚠️ Аварийный режим НЕ включился: " + str(msg)[:300] + " Резерв работает без полного доступа."
            elif want_emg and emg.active() and not st.get("emg"):
                emg_line = "🆘 Аварийный режим уже был включён тобой — оставлен как есть."
            if st.get("emg") and not want_emg and emg.active():
                emg.off("лимиты Claude снова доступны", "ru", quiet=True)
                st["emg"] = False
                emg_off = True
        on_msg = off_msg = None
        flipped = bool(st.get("active")) != was_active
        if auto_case and not st.get("notified"):
            on_msg = _msg_on(conf, lv, emg_line or "🔒 Аварийный режим не включался (галочка выключена): Codex работает с обычными правами.")
            st["notified"] = True
        elif st.get("notified") and not auto_case:
            if down and not st.get("active"):  # резерв выключили руками, а лимиты Claude всё ещё кончились
                off_msg = ("⏸ Резерв Codex + Notion-агент выключен вручную, но лимиты Claude всё ещё кончились: "
                           "Claude остаётся на паузе до сброса окна" +
                           (", аварийный режим снят, доступы возвращены." if emg_off else "."))
            else:
                off_msg = ("✅ Claude снова может работать: " + ("резерв Codex + Notion-агент выключен" if not st.get("active")
                           else "резерв остаётся включённым — он был включён вручную") +
                           (", аварийный режим снят, доступы возвращены." if emg_off else "."))
            st["notified"] = False
        _st_save(st)
    if pause_flip:  # пауза Claude — раньше всего остального: пока не встала, он ещё тратит лимиты
        try:
            PAUSE(want_pause)
        except Exception:
            pass
    try:  # профиль Codex: включить «Резерв» при включении, вернуть прежний при выключении (возврат повторяется каждый такт)
        PROFILE(bool(st.get("active")), flipped)
    except Exception:
        pass
    if flipped:  # консоль Codex берёт инструменты агента при запуске: перезапуск (разговор продолжится), но не посреди ответа
        try:
            APPLY()
        except Exception:
            pass
    if on_msg:
        NOTIFY(on_msg)
    if off_msg:
        NOTIFY(off_msg)


def codex_args():
    """Ключи `-c` для запуска Codex: подключить Notion с четырьмя инструментами агента — но ТОЛЬКО пока резерв включён.
    Вне резерва пусто: Codex Notion не видит. Те же ключи годятся и для консоли, и для `codex exec`."""
    if not active():
        return []
    tools = ",".join('"%s"' % t for t in CODEX_TOOLS)
    return ["-c", 'mcp_servers.notion.url="%s"' % MCP_URL,
            "-c", "mcp_servers.notion.enabled_tools=[%s]" % tools,
            "-c", 'mcp_servers.notion.default_tools_approval_mode="approve"']


def codex_note(conf=None):
    """Одна строка в начало каждого сообщения Codex, пока резерв включён: что случилось и как работать с агентом.
    Вне резерва пусто. Ссылку агента сюда не кладём — Codex находит его по имени через notion-search-agents."""
    if not active():
        return ""
    conf = CONFIG() if conf is None else conf
    name = str(((conf or {}).get("name")) or "").strip()[:80] or "Notion-агент"
    cause = ("Claude отключён человеком вручную" if _st().get("why") == "manual"
             else "Claude недоступен, лимиты кончились")
    return ("[РЕЗЕРВ: " + cause + " — работаешь ты вместе с Notion-агентом «%s». "
            "Инструменты агента: notion-search-agents (найди его по имени, scope=workspace), notion-spawn-session (поставить задачу: "
            "agent_url + initial_message), notion-wait-session (ждать ответ, до 60 с, повторяй пока не готов), "
            "notion-send-message-to-session (дослать). Других инструментов Notion у тебя нет, get_tool_access вызывать не нужно. "
            "Агент видит ТОЛЬКО присланный текст: ни сервера, ни файлов. Присылай ему нужные куски кода (50–150 строк) и чёткое задание, "
            "секреты, ключи и пароли не присылай никогда. Результат проси готовым текстом или патчем. Внедряй сам и обязательно проверяй "
            "(тесты, запуск, чтение результата): ответ агента на веру не принимай. Любое изменение — только после «да» человека; "
            "коротко говори человеку, что и зачем отправил агенту и что получил.]") % name


def _loop():
    while True:
        try:
            tick()
        except Exception as e:
            print(f"notion-reserve: {type(e).__name__} {e}", flush=True)
        time.sleep(TICK)


def start():
    """Из cc_limits при старте: запустить сторож резерва."""
    if not (_watch["t"] and _watch["t"].is_alive()):
        _watch["t"] = threading.Thread(target=_loop, daemon=True, name="notion-reserve")
        _watch["t"].start()
