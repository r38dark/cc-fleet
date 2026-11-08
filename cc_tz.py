"""Часовой пояс владельца для текстов и записок панели: config.json → "tz" (имя IANA, например Europe/Moscow).
Пусто или неверно — зона сервера. Читается при каждом вызове, чтобы смена настройки не требовала правки кода."""
import json
import os
import time
from datetime import datetime

BASE = os.environ.get("CC_LIMITS_BASE") or os.path.dirname(os.path.abspath(__file__))


def name():
    env = str(os.environ.get("CC_FLEET_TZ") or "").strip()   # переопределение для тестов и разовых запусков
    if env:
        return env
    try:
        with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
            return str(json.load(f).get("tz") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def zone():
    tz = name()
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def label():
    """Короткая подпись зоны для записок: «Asia/Irkutsk» или имя зоны сервера («+08»)."""
    return name() or time.strftime("%Z") or "сервер"
