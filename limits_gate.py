#!/usr/bin/env python3
# Гейт лимитов — «можно ли сейчас запускать фоновый (headless) прогон Claude».
#
# Зачем: фоновые задачи (cron, вотчеры, автоответчики) идут по ТОМУ ЖЕ активному
# аккаунту, что и живая интерактивная сессия. Если окно уже почти выбрано, такой
# прогон просто добивает остаток и падает на 429 — а окно нужно человеку.
#
# rc=10 — работать нельзя: либо активный аккаунт не пригоден (ждём, пока балансер
#         уйдёт на свежий), либо не пригоден НИ ОДИН (переключаться некуда).
#         Не пригоден = сессия выше порога. Неделя не держит: она сбрасывается раз
#         в 7 дней, гейт стоял бы сутками (балансер всё равно уходит с аккаунта у потолка).
# rc=0  — есть живой аккаунт, запускаться можно.
# Fail-open: снапшота нет или он протух — НЕ блокируем (лишний прогон лучше
#            молча стоящего демона).
#
# Запуск:  python3 limits_gate.py [порог]      # порог по умолчанию — из config.json
# В своём скрипте:
#   python3 /opt/cc-limits/limits_gate.py || exit 0   # rc=10 => просто не стартуем
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_avail  # noqa: E402

BASE = os.environ.get("CC_LIMITS_BASE", os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "snapshot.json")
CONFIG = os.path.join(BASE, "config.json")
MAX_AGE = 900  # снапшот старше 15 минут считаем неизвестным состоянием


def _default_threshold():
    try:
        return float(json.load(open(CONFIG)).get("threshold") or 90)
    except Exception:
        return 90.0


def _weekly_cap():
    try:
        return float(json.load(open(CONFIG)).get("weekly_cap") or 99)
    except Exception:
        return 99.0


def main():
    ceil = float(sys.argv[1]) if len(sys.argv) > 1 else _default_threshold()
    try:
        d = json.load(open(SNAP))
    except Exception as e:
        print("snapshot недоступен (%s) — гейт пропускает" % e)
        return 0

    active = d.get("active")
    row = (d.get("accounts") or {}).get(active)
    if not row or time.time() - float(d.get("ts") or 0) > MAX_AGE:
        print("Нет свежих лимитов Claude, запуск разрешён.")
        return 0
    available, _, reason = cc_avail.availability(row, ceil, float("inf"))
    print("Лимиты Claude доступны." if available else "Claude ждёт сброса лимита: " + str(reason))
    return 0 if available else 10


if __name__ == "__main__":
    sys.exit(main())
