"""Сообщения в Telegram про обновления Claude Code и Codex: вышла новая версия (один раз на версию) и обновление прошло или не удалось.

Сами программы обновляются по кнопке в панели (claude_cli.py); здесь только сторож: сравнивает их состояние с тем, о чём уже сказали
(cli_notice.json рядом с config.json). Прошлые обновления не пересказываются: первое знакомство с программой только запоминается; о версии, которая уже
вышла и ждёт, скажет один раз. Выключатель: config.json → cli_update_notify = false.
"""
import json
import os
import tempfile
import threading

STATE = None                       # путь к cli_notice.json — cc_limits подставляет рядом с config.json
ENABLED = lambda: True             # cc_limits: config.json → cli_update_notify (по умолчанию включено)
SEND = {"claude": lambda text: False, "codex": lambda text: False}   # cc_limits подставляет отправку в Telegram

NAMES = {"claude@local": ("claude", "Claude Code (DEV)"),
         "claude@remote": ("claude", "Claude Code (PROD)"),
         "codex@local": ("codex", "Codex")}
_lock = threading.Lock()


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(d):
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE), prefix=".cli_notice")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, STATE)
    except OSError:
        pass


def _restart_hint(key, v):
    r = v.get("restart") or {}
    if not r.get("stale"):
        return ""
    if key == "codex@local":
        return "\nКонсоль Codex работает на старой версии — кнопка «Перезапустить консоль Codex» в панели (разговор продолжится)."
    where = "на PROD" if key == "claude@remote" else ""
    return "\nЗапущенный Claude %s работает на старой версии — кнопка «Перезапустить Claude» в панели (начнётся новая сессия)." % where


def _available_text(key, name, v):
    return "⬆ Вышла новая версия %s: %s → %s\nОбновить: значок версии в шапке панели или ⚙ → «Claude Code и Codex»." % (
        name, v.get("version") or "?", v.get("latest"))


def _result_text(key, name, v):
    after = v.get("version_after") or v.get("version") or "?"
    before = v.get("from_version") or ""
    if v.get("state") == "failed":
        return "❌ Обновление %s не удалось: %s" % (name, (v.get("err") or "причина неизвестна").strip()[:200])
    if v.get("op") == "rollback":
        return "↩ %s возвращён на версию %s%s" % (name, after, _restart_hint(key, v))
    if before and before == after:
        return "ℹ %s: обновление выполнено, версия не изменилась (%s)" % (name, after)
    return "✅ %s обновлён: %s → %s%s" % (name, before or "?", after, _restart_hint(key, v))


def tick(views):
    """views: {ключ: словарь claude_cli.status() (+ «restart»)}. Шлёт сообщения о новой версии и об итоге обновления.
    → список отправленных (движок, текст) — для тестов."""
    try:
        if not ENABLED():
            return []
    except Exception:
        return []
    out = []
    with _lock:
        st = _load()
        seen, fin = st.setdefault("latest", {}), st.setdefault("finished", {})
        for key, v in (views or {}).items():
            if key not in NAMES or not isinstance(v, dict) or v.get("ok") is False or not v.get("kind"):
                continue
            engine, name = NAMES[key]
            if v.get("update_available") and v.get("latest") and seen.get(key) != v["latest"] and v.get("state") != "running":
                out.append((engine, _available_text(key, name, v)))
                seen[key] = v["latest"]
            f = float(v.get("finished") or 0)
            if key not in fin:
                fin[key] = f                                  # первое знакомство с этой программой: прошлые обновления не пересказываем
            elif v.get("state") in ("done", "failed") and f and f != fin[key]:
                out.append((engine, _result_text(key, name, v)))
                fin[key] = f
        _save(st)
    for engine, text in out:
        try:
            SEND.get(engine, SEND["claude"])(text)
        except Exception:
            pass
    return out
